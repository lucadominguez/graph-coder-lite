"""Run state in one JSON file, with the transitions that are actually legal.

The only structural rule worth enforcing in code is that `completed` is
unreachable from `running`. A worker that finishes goes to `awaiting_review`,
and only a manager's passing verdict moves it on. Everything else here is
bookkeeping that survives a reload.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from gcl.budget import ROLES
from gcl.errors import StateError

STATE_DIR = ".gcl"
STATE_FILE = "state.json"

PENDING = "pending"
READY = "ready"
RUNNING = "running"
AWAITING_REVIEW = "awaiting_review"
REPAIR_REQUIRED = "repair_required"
COMPLETED = "completed"
BLOCKED = "blocked"
HUMAN_REQUIRED = "human_required"
FAILED = "failed"

STATES = (
    PENDING,
    READY,
    RUNNING,
    AWAITING_REVIEW,
    REPAIR_REQUIRED,
    COMPLETED,
    BLOCKED,
    HUMAN_REQUIRED,
    FAILED,
)

#: `running -> completed` is absent on purpose. It is the transition a Director
#: reaches for when a worker says it is done, and taking it skips the only
#: review in the system.
TRANSITIONS: dict[str, frozenset[str]] = {
    PENDING: frozenset({READY, BLOCKED, HUMAN_REQUIRED}),
    READY: frozenset({RUNNING, BLOCKED, HUMAN_REQUIRED}),
    RUNNING: frozenset({AWAITING_REVIEW, FAILED, BLOCKED, HUMAN_REQUIRED}),
    AWAITING_REVIEW: frozenset({COMPLETED, REPAIR_REQUIRED, HUMAN_REQUIRED, FAILED}),
    REPAIR_REQUIRED: frozenset({RUNNING, HUMAN_REQUIRED, FAILED}),
    COMPLETED: frozenset(),
    BLOCKED: frozenset({READY, HUMAN_REQUIRED, FAILED}),
    HUMAN_REQUIRED: frozenset({READY, RUNNING, FAILED, COMPLETED}),
    FAILED: frozenset({READY, HUMAN_REQUIRED}),
}


#: The three states only a manager verdict may produce. `gcl set` refuses them,
#: so every completed unit carries a review record by construction rather than by
#: convention, and a `repair_required` always names the defect it found.
VERDICT_STATES = {
    "pass": COMPLETED,
    "repair_required": REPAIR_REQUIRED,
    "human_required": HUMAN_REQUIRED,
}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class RunState:
    """The durable state of one run. Rebuild from this after a reload, not from memory."""

    def __init__(self, path: Path, payload: dict[str, Any] | None = None) -> None:
        self.path = path
        self.payload: dict[str, Any] = payload or {
            "plan_id": "",
            "plan_hash": "",
            "nodes": {},
            "events": [],
        }

    @classmethod
    def load(cls, root: Path) -> RunState:
        path = Path(root) / STATE_DIR / STATE_FILE
        if not path.is_file():
            return cls(path)
        return cls(path, json.loads(path.read_text(encoding="utf-8")))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.payload, indent=2, sort_keys=False) + "\n", encoding="utf-8"
        )

    # -- nodes -------------------------------------------------------------

    @property
    def nodes(self) -> dict[str, dict[str, Any]]:
        return self.payload.setdefault("nodes", {})

    def states(self) -> dict[str, str]:
        return {unit_id: str(node.get("status", PENDING)) for unit_id, node in self.nodes.items()}

    def status(self, unit_id: str) -> str:
        return str(self.nodes.get(unit_id, {}).get("status", PENDING))

    def attempts(self, unit_id: str) -> int:
        return int(self.nodes.get(unit_id, {}).get("attempts", 0))

    def sync(self, unit_ids: list[str], *, plan_id: str, plan_hash: str) -> None:
        """Add units the plan gained; keep the state of the ones it already had."""

        self.payload["plan_id"] = plan_id
        self.payload["plan_hash"] = plan_hash
        for unit_id in unit_ids:
            self.nodes.setdefault(unit_id, {"status": PENDING, "attempts": 0})
        for unit_id in list(self.nodes):
            if unit_id not in unit_ids:
                self.nodes[unit_id]["status"] = "superseded"

    def transition(self, unit_id: str, target: str, *, note: str = "") -> dict[str, Any]:
        if target not in STATES:
            raise StateError(f"unknown state `{target}`; valid states are {', '.join(STATES)}")
        current = self.status(unit_id)
        allowed = TRANSITIONS.get(current, frozenset())
        if target not in allowed:
            hint = ""
            if current == RUNNING and target == COMPLETED:
                hint = (
                    " A worker that finished goes to awaiting_review; only a manager's "
                    "passing review completes it."
                )
            raise StateError(
                f"{unit_id} cannot go from {current} to {target}. Legal next states: "
                + (", ".join(sorted(allowed)) or "(none, this is terminal)")
                + "."
                + hint
            )
        node = self.nodes.setdefault(unit_id, {"status": PENDING, "attempts": 0})
        node["status"] = target
        node["updated_at"] = _now()
        if target == RUNNING:
            node["attempts"] = int(node.get("attempts", 0)) + 1
        if note:
            node["note"] = note
        self.event("state", unit_id=unit_id, to=target, note=note)
        return node

    def review(
        self,
        unit_id: str,
        verdict: str,
        *,
        evidence: list[str] | None = None,
        defects: list[str] | None = None,
        repairs: list[str] | None = None,
        question: str = "",
        attempted: list[str] | None = None,
        impacted: list[str] | None = None,
    ) -> dict[str, Any]:
        """Apply a manager verdict, refusing one that is not actually a review.

        A `repair_required` with no bounded defect and no repair instruction is a
        complaint, not a review: the worker is sent back with nothing to act on.
        A `human_required` with no question and no account of what was already
        tried leaves whoever picks it up starting from zero. A `pass` with no
        evidence is the worker's own say-so wearing a manager's name.
        """

        if verdict not in VERDICT_STATES:
            raise StateError(
                f"unknown verdict `{verdict}`; expected one of {', '.join(sorted(VERDICT_STATES))}"
            )
        current = self.status(unit_id)
        if current != AWAITING_REVIEW:
            raise StateError(
                f"a review applies to a unit in awaiting_review, and {unit_id} is {current}. "
                "A worker submits its report first."
            )

        if verdict == "pass" and not evidence:
            raise StateError(
                f"{unit_id}: a pass needs at least one piece of evidence (--evidence). "
                "Quote the real command output or the artifact check you ran; a worker's "
                "own claim of success is not evidence."
            )
        if verdict == "repair_required":
            if not defects:
                raise StateError(f"{unit_id}: repair_required needs at least one --defect")
            if not repairs:
                raise StateError(
                    f"{unit_id}: repair_required needs at least one --repair instruction. "
                    "A defect with no instruction is a complaint, not a review."
                )
        if verdict == "human_required":
            if not question:
                raise StateError(
                    f"{unit_id}: human_required needs --question, the exact decision "
                    "the user has to make"
                )
            if not attempted:
                raise StateError(
                    f"{unit_id}: human_required needs at least one --attempted, so the next "
                    "reader does not repeat what already failed"
                )

        record = {
            "at": _now(),
            "verdict": verdict,
            "evidence": list(evidence or []),
            "defects": list(defects or []),
            "repair_instructions": list(repairs or []),
            "question": question,
            "attempts_made": list(attempted or []),
            "impacted_units": list(impacted or []),
        }
        node = self.nodes.setdefault(unit_id, {"status": PENDING, "attempts": 0})
        node.setdefault("reviews", []).append(record)
        self.transition(unit_id, VERDICT_STATES[verdict], note=verdict)
        self.event("review", unit_id=unit_id, verdict=verdict)
        return record

    def reviews(self, unit_id: str) -> list[dict[str, Any]]:
        return list(self.nodes.get(unit_id, {}).get("reviews", []))

    def unverified_completions(self) -> list[str]:
        """Completed units with no passing review recorded against them.

        After an interruption a unit can be left marked complete by a write that
        landed while the review that justified it did not. Treating that as done
        is how unverified work reaches the units downstream of it.
        """

        return sorted(
            unit_id
            for unit_id, node in self.nodes.items()
            if node.get("status") == COMPLETED
            and not any(review.get("verdict") == "pass" for review in node.get("reviews", []))
        )

    # -- usage -------------------------------------------------------------

    @property
    def usage(self) -> list[dict[str, Any]]:
        return self.payload.setdefault("usage", [])

    def record_usage(
        self,
        *,
        role: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        unit: str = "",
    ) -> dict[str, Any]:
        """Persist what a model turn cost.

        The postmortem run could not reconstruct its own spend afterwards, which
        is why it could not stop. A workflow that cannot measure its principal
        optimization target cannot enforce it.
        """

        if role not in ROLES:
            raise StateError(f"unknown role `{role}`; expected one of {', '.join(sorted(ROLES))}")
        for name, value in (("input_tokens", input_tokens), ("output_tokens", output_tokens)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise StateError(f"{name} must be a non-negative integer")
        record = {
            "at": _now(),
            "role": role,
            "provider": provider.strip().lower(),
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "unit": unit,
        }
        self.usage.append(record)
        return record

    # -- events ------------------------------------------------------------

    def event(self, kind: str, **payload: Any) -> dict[str, Any]:
        record = {"at": _now(), "kind": kind, **payload}
        self.payload.setdefault("events", []).append(record)
        return record

    @property
    def events(self) -> list[dict[str, Any]]:
        return self.payload.setdefault("events", [])
