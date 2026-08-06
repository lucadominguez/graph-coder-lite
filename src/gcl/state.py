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

    # -- events ------------------------------------------------------------

    def event(self, kind: str, **payload: Any) -> dict[str, Any]:
        record = {"at": _now(), "kind": kind, **payload}
        self.payload.setdefault("events", []).append(record)
        return record

    @property
    def events(self) -> list[dict[str, Any]]:
        return self.payload.setdefault("events", [])
