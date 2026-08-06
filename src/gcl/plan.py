"""The plan file: parse it, and refuse to call it ready when it is not.

One artifact holds the whole run. The units declare their own dependencies,
manager, scopes, and route, so the graph is derived from the plan rather than
compiled into a second file that can drift away from it.

Everything checked here is something a model under time pressure has actually
skipped, or something prose cannot enforce: a missing field, a dependency that
names nothing, two units that would write the same file at the same time.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from gcl import budget as budget_module
from gcl.errors import ContractError, PlanError

#: Routes that mean "nothing was routed here". A plan may carry one while it is
#: being written; a dispatch may not. `local` is the example plan's placeholder.
PLACEHOLDER_ROUTES = frozenset({"", "local", "default", "tbd", "none"})

#: `review` is deliberately absent. A review is a manager's verdict and an
#: artifact, never a node in the graph, because a review node needs a reviewer
#: agent and that is the role this design removes.
UNIT_KINDS = frozenset({"explore", "implement", "verify", "integrate", "repair", "release"})

RISK_LEVELS = frozenset({"low", "medium", "high", "critical"})

SECTIONS = (
    "Goal and Requirements",
    "Grounding",
    "Decisions and Evidence",
    "Units",
    "Verification and Done",
    "Risks and Recovery",
)

_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n(.*)\Z", re.DOTALL)
_HEADING = re.compile(r"^##\s+\d+\.\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Unit:
    """One dispatchable unit of work. Nineteen fields, all load-bearing."""

    unit_id: str
    title: str
    objective: str
    kind: str
    dependencies: tuple[str, ...]
    acceptance_ids: tuple[str, ...]
    read_scope: tuple[str, ...]
    write_scope: tuple[str, ...]
    forbidden_scope: tuple[str, ...]
    procedure: tuple[str, ...]
    commands: dict[str, tuple[str, ...]]
    expected_artifacts: tuple[str, ...]
    output_contract: tuple[str, ...]
    progress_contract: dict[str, Any]
    manager_id: str
    risk: str
    route: dict[str, str]
    attempt_limit: int
    stop_conditions: tuple[str, ...]

    @property
    def primary_route(self) -> str:
        return str(self.route.get("primary") or "")

    @property
    def fallback_route(self) -> str:
        return str(self.route.get("fallback") or "")

    @property
    def is_routed(self) -> bool:
        return self.primary_route.lower() not in PLACEHOLDER_ROUTES


@dataclass(frozen=True)
class Plan:
    plan_id: str
    plan_version: int
    readiness: str
    approved: bool
    approval: dict[str, Any]
    bounds: dict[str, Any]
    budget: dict[str, Any]
    requirements: tuple[dict[str, Any], ...]
    acceptance: tuple[dict[str, Any], ...]
    managers: tuple[dict[str, Any], ...]
    units: tuple[Unit, ...]
    sections: dict[str, str] = field(default_factory=dict)
    source: Path | None = None
    content_hash: str = ""

    def unit(self, unit_id: str) -> Unit:
        for candidate in self.units:
            if candidate.unit_id == unit_id:
                return candidate
        raise ContractError(f"no unit {unit_id} in plan {self.plan_id}")

    @property
    def unit_ids(self) -> tuple[str, ...]:
        return tuple(unit.unit_id for unit in self.units)

    @property
    def max_active_workers(self) -> int:
        return int(self.bounds.get("max_active_workers", 8))


_UNIT_SEQUENCES = (
    "dependencies",
    "acceptance_ids",
    "read_scope",
    "write_scope",
    "forbidden_scope",
    "procedure",
    "expected_artifacts",
    "output_contract",
    "stop_conditions",
)


def _strings(value: Any, *, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raise PlanError(f"{where} must be a list, not a single string")
    if not isinstance(value, list):
        raise PlanError(f"{where} must be a list")
    return tuple(str(item) for item in value)


def _unit_from_mapping(raw: Any) -> Unit:
    if not isinstance(raw, dict):
        raise PlanError("every entry in `units` must be a mapping")
    unit_id = str(raw.get("unit_id") or "")
    if not unit_id:
        raise PlanError("a unit is missing `unit_id`")
    commands_raw = raw.get("commands") or {}
    if not isinstance(commands_raw, dict):
        raise PlanError(f"unit {unit_id}: `commands` must be a mapping of red/green lists")
    route_raw = raw.get("route") or {}
    if not isinstance(route_raw, dict):
        raise PlanError(f"unit {unit_id}: `route` must be a mapping with `primary`")
    progress_raw = raw.get("progress_contract") or {}
    if not isinstance(progress_raw, dict):
        raise PlanError(f"unit {unit_id}: `progress_contract` must be a mapping")
    sequences = {
        name: _strings(raw.get(name), where=f"unit {unit_id}: `{name}`") for name in _UNIT_SEQUENCES
    }
    return Unit(
        unit_id=unit_id,
        title=str(raw.get("title") or ""),
        objective=str(raw.get("objective") or ""),
        kind=str(raw.get("kind") or "implement"),
        commands={
            key: _strings(commands_raw.get(key), where=f"unit {unit_id}: `commands.{key}`")
            for key in ("red", "green")
        },
        progress_contract=dict(progress_raw),
        manager_id=str(raw.get("manager_id") or ""),
        risk=str(raw.get("risk") or ""),
        route={key: str(value) for key, value in route_raw.items()},
        attempt_limit=int(raw.get("attempt_limit") or 0),
        **sequences,
    )


def parse(text: str, *, source: Path | None = None) -> Plan:
    """Parse a plan file. Raises PlanError with the fix, never a bare KeyError."""

    match = _FRONTMATTER.match(text)
    if not match:
        raise PlanError(
            "plan must open with a YAML frontmatter block delimited by --- lines; "
            "see the template written by `gcl init`"
        )
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as error:  # pragma: no cover - message passthrough
        raise PlanError(f"plan frontmatter is not valid YAML: {error}") from error
    if not isinstance(meta, dict):
        raise PlanError("plan frontmatter must be a mapping")

    body = match.group(2)
    for required in ("plan_id", "plan_version", "readiness"):
        if not meta.get(required):
            raise PlanError(f"plan frontmatter is missing `{required}`")

    units = tuple(_unit_from_mapping(raw) for raw in (meta.get("units") or []))
    seen: set[str] = set()
    for unit in units:
        if unit.unit_id in seen:
            raise PlanError(f"duplicate unit_id {unit.unit_id}")
        seen.add(unit.unit_id)

    sections = {name: _section_body(body, name) for name in _headings(body)}
    return Plan(
        plan_id=str(meta["plan_id"]),
        plan_version=int(meta["plan_version"]),
        readiness=str(meta["readiness"]),
        approved=bool(meta.get("approved", False)),
        approval=dict(meta.get("approval") or {}),
        bounds=dict(meta.get("bounds") or {}),
        budget=dict(meta.get("budget") or {}),
        requirements=tuple(meta.get("requirements") or []),
        acceptance=tuple(meta.get("acceptance") or []),
        managers=tuple(meta.get("managers") or []),
        units=units,
        sections=sections,
        source=source,
        content_hash=content_hash(text),
    )


def load(path: str | Path) -> Plan:
    resolved = Path(path)
    if not resolved.is_file():
        raise PlanError(f"no plan at {resolved}. Run `gcl init` to write a starting one.")
    return parse(resolved.read_text(encoding="utf-8"), source=resolved)


def _headings(body: str) -> list[str]:
    return [match.group(1) for match in _HEADING.finditer(body)]


def _section_body(body: str, name: str) -> str:
    positions = [(match.start(), match.group(1)) for match in _HEADING.finditer(body)]
    for index, (start, heading) in enumerate(positions):
        if heading != name:
            continue
        end = positions[index + 1][0] if index + 1 < len(positions) else len(body)
        return body[start:end].strip()
    return ""


def content_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def approval_hash(plan: Plan) -> str:
    """Hash what approval is actually binding: the units and their contracts.

    Reformatting the prose does not invalidate an approval. Changing a scope, a
    command, an acceptance id, or a route does.
    """

    payload = [
        {
            "unit_id": unit.unit_id,
            "objective": unit.objective,
            "kind": unit.kind,
            "dependencies": sorted(unit.dependencies),
            "acceptance_ids": sorted(unit.acceptance_ids),
            "read_scope": sorted(unit.read_scope),
            "write_scope": sorted(unit.write_scope),
            "forbidden_scope": sorted(unit.forbidden_scope),
            "commands": {key: list(value) for key, value in sorted(unit.commands.items())},
            "expected_artifacts": sorted(unit.expected_artifacts),
            "output_contract": sorted(unit.output_contract),
            "progress_contract": dict(sorted(unit.progress_contract.items())),
            "manager_id": unit.manager_id,
            "route": dict(sorted(unit.route.items())),
            "attempt_limit": unit.attempt_limit,
        }
        for unit in sorted(plan.units, key=lambda item: item.unit_id)
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Readiness
# --------------------------------------------------------------------------

_REQUIRED_UNIT_FIELDS = (
    "title",
    "objective",
    "acceptance_ids",
    "read_scope",
    "write_scope",
    "forbidden_scope",
    "procedure",
    "expected_artifacts",
    "output_contract",
    "progress_contract",
    "stop_conditions",
)


def readiness_defects(plan: Plan) -> list[str]:
    """Every reason this plan cannot be dispatched, in one pass.

    Returns a list rather than raising on the first problem: a planner fixing one
    field at a time and re-running is the slow path this exists to avoid.
    """

    defects: list[str] = []
    if plan.readiness != "ready":
        defects.append(
            f"plan readiness is `{plan.readiness}`, not `ready`; "
            "execution may only begin from a ready plan"
        )
    if not plan.units:
        defects.append("plan declares no units")
    if not plan.acceptance:
        defects.append("plan declares no acceptance criteria")
    if not plan.requirements:
        defects.append("plan declares no requirements")

    missing_sections = [name for name in SECTIONS if name not in plan.sections]
    if missing_sections:
        defects.append("plan is missing sections: " + ", ".join(missing_sections))

    acceptance_ids = {str(item.get("id")) for item in plan.acceptance if isinstance(item, dict)}
    manager_ids = {str(item.get("id")) for item in plan.managers if isinstance(item, dict)}
    unit_ids = set(plan.unit_ids)
    covered_acceptance: set[str] = set()

    for unit in plan.units:
        defects.extend(_unit_defects(unit, unit_ids, acceptance_ids, manager_ids))
        covered_acceptance.update(unit.acceptance_ids)

    uncovered = sorted(acceptance_ids - covered_acceptance)
    if uncovered:
        defects.append(
            "acceptance criteria with no unit that satisfies them: " + ", ".join(uncovered)
        )

    defects.extend(_bounds_defects(plan))
    defects.extend(budget_module.defects(plan.budget))
    return defects


def _unit_defects(
    unit: Unit, unit_ids: set[str], acceptance_ids: set[str], manager_ids: set[str]
) -> list[str]:
    defects: list[str] = []
    for name in _REQUIRED_UNIT_FIELDS:
        if not getattr(unit, name):
            defects.append(f"unit {unit.unit_id} is missing {name.replace('_', ' ')}")

    # Not `(unit.manager_id,)`. A one-tuple is always truthy, which is how a unit
    # with no manager once passed this gate and reached execution with nobody
    # assigned to review it.
    if not unit.manager_id:
        defects.append(f"unit {unit.unit_id} has no manager_id, so nothing would review it")
    elif manager_ids and unit.manager_id not in manager_ids:
        defects.append(f"unit {unit.unit_id} names undeclared manager {unit.manager_id}")

    if unit.kind not in UNIT_KINDS:
        defects.append(
            f"unit {unit.unit_id} has kind `{unit.kind}`; allowed kinds are "
            + ", ".join(sorted(UNIT_KINDS))
            + " (a review is a manager verdict, never a node)"
        )
    if unit.risk not in RISK_LEVELS:
        defects.append(f"unit {unit.unit_id} risk must be one of {sorted(RISK_LEVELS)}")
    if not unit.commands.get("green"):
        defects.append(f"unit {unit.unit_id} declares no green command, so nothing proves it works")
    if not 1 <= unit.attempt_limit <= 10:
        defects.append(f"unit {unit.unit_id} attempt_limit must be between 1 and 10")

    unknown_dependencies = sorted(set(unit.dependencies) - unit_ids)
    if unknown_dependencies:
        defects.append(f"unit {unit.unit_id} depends on unknown units: {unknown_dependencies}")
    if unit.unit_id in unit.dependencies:
        defects.append(f"unit {unit.unit_id} depends on itself")

    unknown_acceptance = sorted(set(unit.acceptance_ids) - acceptance_ids)
    if acceptance_ids and unknown_acceptance:
        defects.append(f"unit {unit.unit_id} cites unknown acceptance ids: {unknown_acceptance}")

    defects.extend(_progress_defects(unit))

    # A packet that both grants and denies a path is incoherent, and the worker
    # resolves it by guessing.
    write_overlap = sorted(_scope_overlap(unit.write_scope, unit.forbidden_scope))
    if write_overlap:
        defects.append(
            f"unit {unit.unit_id} has paths in both write_scope and forbidden_scope: "
            f"{write_overlap}"
        )
    read_overlap = sorted(_scope_overlap(unit.read_scope, unit.forbidden_scope))
    if read_overlap:
        defects.append(
            f"unit {unit.unit_id} has paths in both read_scope and forbidden_scope: "
            f"{read_overlap}. A path that is merely not writable belongs in read scope "
            "alone; forbidden means the worker may not even look."
        )
    return defects


def _progress_defects(unit: Unit) -> list[str]:
    """The progress contract is what makes a stall distinguishable from work.

    Without it, an agent 900 items into a long job and an agent wedged in a dead
    loop produce the same observation: nothing new on disk.
    """

    defects: list[str] = []
    contract = unit.progress_contract
    if not contract:
        return defects
    for key in ("checkpoint_every", "writes_incrementally", "command_timeout_seconds"):
        if key not in contract:
            defects.append(f"unit {unit.unit_id} progress contract is missing {key}")
    timeout = contract.get("command_timeout_seconds")
    if timeout is not None and not (isinstance(timeout, int) and not isinstance(timeout, bool)):
        defects.append(f"unit {unit.unit_id} command_timeout_seconds must be an integer")
    elif isinstance(timeout, int) and not isinstance(timeout, bool) and timeout <= 0:
        defects.append(f"unit {unit.unit_id} command_timeout_seconds must be positive")
    incremental = contract.get("writes_incrementally")
    if incremental is not None and not isinstance(incremental, bool):
        defects.append(f"unit {unit.unit_id} writes_incrementally must be true or false")
    return defects


def _bounds_defects(plan: Plan) -> list[str]:
    defects: list[str] = []
    for key in ("max_active_workers", "attempt_limit"):
        value = plan.bounds.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            defects.append(f"bounds.{key} must be a positive integer")
    ceiling = plan.bounds.get("cost_ceiling")
    if not isinstance(ceiling, (int, float)) or isinstance(ceiling, bool):
        defects.append("bounds.cost_ceiling must be an explicit number, even if generous")
    return defects


# --------------------------------------------------------------------------
# Scope comparison
# --------------------------------------------------------------------------


def normalize_scope(entry: str) -> str:
    """Normalize a scope entry for comparison.

    Case-folded because Windows treats `SRC/Store.py` and `src/store.py` as one
    file, and a plan that spells them differently would otherwise pass a check
    the filesystem then fails.
    """

    text = entry.strip().replace("\\", "/").casefold()
    while text.startswith("./"):
        text = text[2:]
    text = text.rstrip("*")
    return text.rstrip("/")


def scopes_overlap(left: str, right: str) -> bool:
    """True when two scope entries could name the same file.

    A directory contains its files, so `src/` overlaps `src/store.py`. Prefix
    comparison alone would also call `src/store` a parent of `src/store_v2.py`,
    which it is not, so the boundary has to land on a separator.
    """

    first, second = normalize_scope(left), normalize_scope(right)
    if not first or not second:
        return False
    if first == second:
        return True
    return first.startswith(second + "/") or second.startswith(first + "/")


def _scope_overlap(left: tuple[str, ...], right: tuple[str, ...]) -> set[str]:
    return {first for first in left for second in right if scopes_overlap(first, second)}
