"""The graph, derived from the plan rather than compiled into a second file.

Units declare their own dependencies and manager, so there is nothing here to
keep in sync with the plan and nothing to recompile after an edit. What this
module does is answer the three questions prose cannot: is the dependency graph
acyclic, what is dispatchable right now, and could two units that run together
write the same file.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from gcl.errors import ContractError
from gcl.plan import Plan, Unit, scopes_overlap

#: A worker is only eligible once its dependencies passed review. `completed` is
#: reachable only through `awaiting_review`, which is what stops a worker from
#: completing itself.
TERMINAL_PASS = "completed"


@dataclass(frozen=True)
class ScopeConflict:
    left: str
    right: str
    paths: tuple[str, ...]

    def describe(self) -> str:
        return f"{self.left} and {self.right} can run at the same time and both write " + ", ".join(
            self.paths
        )


def topological_order(plan: Plan) -> list[str]:
    """Kahn's algorithm. Raises with the cycle members rather than a bare failure."""

    indegree: dict[str, int] = {unit.unit_id: 0 for unit in plan.units}
    dependents: dict[str, list[str]] = defaultdict(list)
    for unit in plan.units:
        for dependency in unit.dependencies:
            if dependency not in indegree:
                raise ContractError(f"unit {unit.unit_id} depends on unknown unit {dependency}")
            indegree[unit.unit_id] += 1
            dependents[dependency].append(unit.unit_id)

    ready = sorted(unit_id for unit_id, count in indegree.items() if count == 0)
    order: list[str] = []
    while ready:
        current = ready.pop(0)
        order.append(current)
        for dependent in dependents[current]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
        ready.sort()

    if len(order) != len(indegree):
        stuck = sorted(set(indegree) - set(order))
        raise ContractError(
            "dependency cycle between units: "
            + ", ".join(stuck)
            + ". Iteration is expressed as bounded attempts and repair units, never as a cycle."
        )
    return order


def ancestors(plan: Plan) -> dict[str, set[str]]:
    """Every unit each unit transitively depends on."""

    result: dict[str, set[str]] = {}
    for unit_id in topological_order(plan):
        unit = plan.unit(unit_id)
        collected: set[str] = set()
        for dependency in unit.dependencies:
            collected.add(dependency)
            collected |= result.get(dependency, set())
        result[unit_id] = collected
    return result


def concurrent_pairs(plan: Plan) -> list[tuple[str, str]]:
    """Pairs with no dependency path between them, so nothing orders their writes."""

    reach = ancestors(plan)
    ids = sorted(reach)
    pairs: list[tuple[str, str]] = []
    for index, left in enumerate(ids):
        for right in ids[index + 1 :]:
            if left in reach[right] or right in reach[left]:
                continue
            pairs.append((left, right))
    return pairs


def scope_conflicts(plan: Plan) -> list[ScopeConflict]:
    """Units that could run in the same round and write the same file.

    Two workers in one write scope is the conflict the graph exists to prevent,
    and it is invisible by eye once a plan has more than a handful of units.
    """

    conflicts: list[ScopeConflict] = []
    for left_id, right_id in concurrent_pairs(plan):
        left, right = plan.unit(left_id), plan.unit(right_id)
        shared = sorted(
            {
                first
                for first in left.write_scope
                for second in right.write_scope
                if scopes_overlap(first, second)
            }
        )
        if shared:
            conflicts.append(ScopeConflict(left=left_id, right=right_id, paths=tuple(shared)))
    return conflicts


def read_scope_gaps(plan: Plan) -> list[str]:
    """A unit that cannot read anything its dependency produced will fail on arrival.

    The packet bounds a worker to its read scope, so a dependency whose every
    artifact is invisible to the dependent is a plan defect rather than a runtime
    surprise. This does not demand that a dependent list every artifact of every
    dependency: units legitimately depend on ordering without consuming the whole
    output. It catches the edge that carries nothing.
    """

    gaps: list[str] = []
    for unit in plan.units:
        for dependency_id in unit.dependencies:
            dependency = plan.unit(dependency_id)
            if not dependency.expected_artifacts:
                continue
            visible = any(
                scopes_overlap(artifact, entry)
                for artifact in dependency.expected_artifacts
                for entry in unit.read_scope
            )
            if not visible:
                gaps.append(
                    f"unit {unit.unit_id} depends on {dependency_id} but its read scope "
                    f"covers none of that unit's artifacts "
                    f"({', '.join(sorted(dependency.expected_artifacts))}), so the worker "
                    "cannot see what it was told to build on"
                )
    return gaps


def structural_defects(plan: Plan) -> list[str]:
    """Defects that need the whole graph to see, not one unit at a time."""

    defects: list[str] = []
    try:
        topological_order(plan)
    except ContractError as error:
        return [str(error)]
    defects.extend(conflict.describe() for conflict in scope_conflicts(plan))
    defects.extend(read_scope_gaps(plan))

    depth = max(len(chain) for chain in ancestors(plan).values()) if plan.units else 0
    limit = int(plan.bounds.get("max_depth", 6))
    if depth > limit:
        defects.append(f"longest dependency chain is {depth}, over the max_depth bound of {limit}")
    return defects


def frontier(plan: Plan, states: dict[str, str]) -> list[str]:
    """Units eligible to dispatch now.

    A dependency counts only when it reached `completed`, and a unit reaches
    `completed` only through a passing manager review. That is the whole gate: a
    worker's own claim that it finished never makes its dependents eligible.
    """

    ready: list[str] = []
    for unit in plan.units:
        if states.get(unit.unit_id, "pending") not in ("pending", "ready"):
            continue
        if all(states.get(dependency) == TERMINAL_PASS for dependency in unit.dependencies):
            ready.append(unit.unit_id)
    return sorted(ready)


def dispatch_round(plan: Plan, states: dict[str, str]) -> tuple[list[str], list[str]]:
    """Split the frontier into what to spawn now and what waits.

    Overflow is queued, never dropped and never serialized because watching one
    worker at a time felt easier to follow.
    """

    active = sum(1 for state in states.values() if state in ("running", "awaiting_review"))
    capacity = max(plan.max_active_workers - active, 0)
    ready = frontier(plan, states)
    return ready[:capacity], ready[capacity:]


def preflight(plan: Plan, units: list[Unit] | None = None) -> dict[str, object]:
    """Whether this plan is fit to dispatch, in terms a Director can check.

    Both checks exist because a real run failed them silently: every node still
    carried a placeholder route, so the workers ran on whatever default the
    harness supplied, unrouted and unmetered, and nothing in the output said so.

    This reports rather than raises. The example plan ships deliberately
    unrouted so it parses without a model list, and refusing to emit it would
    break the quickstart.
    """

    candidates = list(units if units is not None else plan.units)
    unrouted = sorted(unit.unit_id for unit in candidates if not unit.is_routed)
    unapproved = not plan.approved
    warnings: list[str] = []
    if unrouted:
        warnings.append(
            f"{len(unrouted)} units carry a placeholder route instead of a real model, which "
            "means routing was skipped and the workers will run on whatever default the "
            "harness supplies: "
            + ", ".join(unrouted[:5])
            + ". Fix with `gcl route set --model <model> --fallback <model>`."
        )
    if unapproved:
        warnings.append(
            "the plan is not approved. Render it in full, get the user's approval, then "
            "record it with `gcl approve`."
        )
    return {
        "ready_to_dispatch": not warnings,
        "dispatchable_units": len(candidates),
        "unrouted_units": unrouted,
        "approved": plan.approved,
        "warnings": warnings,
    }
