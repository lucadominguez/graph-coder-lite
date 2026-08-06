"""The worker packet: everything a fresh agent needs, and nothing outside its scope.

The text here is the part of the system that was paid for in failed runs. A
worker that is not told what a valid artifact contains will hand back an empty
file that satisfies every criterion the plan wrote down. A worker that is not
told to write incrementally is indistinguishable from a hung one. A worker that
is not told who reviews it will mark itself complete.

Send a packet verbatim. Rewriting it in your own words is how a scope leaks.
"""

from __future__ import annotations

from typing import Any

from gcl.plan import Plan, Unit

#: Where workers append progress lines. It sits outside every unit's write scope
#: on purpose, so a worker logging progress never collides with another worker's
#: files, and it is the single exception a packet grants to the write scope.
PROGRESS_DIR = ".gcl/progress"


def review_line(unit: Unit) -> str:
    if not unit.manager_id:
        return (
            "No manager is assigned to review this unit. Stop and report this: a unit "
            "with no reviewer is a plan defect, not a licence to self-approve."
        )
    return (
        f"Submit your report to manager {unit.manager_id} for review. Only its passing "
        "review completes this unit; you do not mark yourself complete."
    )


def output_contract_block(unit: Unit) -> str:
    """What a valid artifact contains, restated to the worker before it starts.

    A unit whose only gate is its acceptance prose can be "completed" by a
    scraper that returns nothing: the code ran, the file exists, and no criterion
    described the contents.
    """

    if not unit.output_contract:
        return "Output contract: none declared. Escalate rather than inventing one."
    lines = ["Output contract. Your work is not done until every one of these holds:"]
    lines.extend(f"- {check}" for check in unit.output_contract)
    lines.append(
        "Verify these yourself against the artifact you produced and quote the result in "
        "your report. A file that exists but is empty or malformed is a failure, not a "
        "completion."
    )
    return "\n".join(lines)


def progress_block(unit: Unit) -> str:
    """Tell the worker how to be legible from outside while it runs.

    A running worker's transcript cannot be read, so the Director watching it has
    the filesystem and nothing else. A worker that buffers all its output to the
    end looks exactly like one that is stuck.
    """

    contract = unit.progress_contract or {}
    cadence = str(contract.get("checkpoint_every") or "each step")
    incremental = bool(contract.get("writes_incrementally", True))
    timeout = contract.get("command_timeout_seconds")

    lines = [
        f"Progress protocol. Append one line to {PROGRESS_DIR}/{unit.unit_id}.log at this "
        f"cadence: {cadence}. Writing that log is permitted despite the write scope above, "
        "and it is the only path outside that scope you may touch."
    ]
    if incremental:
        lines.append(
            "Write your output incrementally at the same cadence. Do not hold results in "
            "memory and write once at the end: a long run that dies before its final write "
            "loses everything, and until that write lands you cannot be told apart from an "
            "agent that is stuck."
        )
    else:
        lines.append(
            "This unit writes its output once, in a single pass, so the progress log is the "
            "only sign of life you emit. Keep it current."
        )
    if isinstance(timeout, int) and not isinstance(timeout, bool) and timeout > 0:
        lines.append(
            f"No single command may run longer than {timeout} seconds. Bound long commands "
            "yourself, with a timeout or by splitting the work into batches that each "
            "report. A worker inside a long blocking call cannot answer a message, cannot "
            "report, and will be cancelled as hung rather than waited on."
        )
    lines.append(
        "Your transcript cannot be read while you run, so these are the only signs that you "
        "are making progress, and a long silent stretch is read as a stall."
    )
    return " ".join(lines)


def report_template(unit: Unit) -> str:
    return "\n".join(
        [
            f"Report for {unit.unit_id}.",
            "State, in this order: what you changed, the exact files you wrote, the "
            "commands you ran with their real output, each output-contract assertion and "
            "whether it holds, anything you did that the packet did not describe, and "
            "anything that blocked you.",
            "Do not claim a command passed without its output. Do not report success for "
            "an assertion you did not check.",
        ]
    )


def build(plan: Plan, unit: Unit) -> str:
    """The full packet text for one unit."""

    acceptance = _acceptance_text(plan, unit)
    commands_green = unit.commands.get("green") or ()
    commands_red = unit.commands.get("red") or ()

    blocks = [
        f"Unit {unit.unit_id}: {unit.title}",
        f"Objective: {unit.objective}",
        review_line(unit),
        "",
        f"Read scope (you may read nothing else): {_list(unit.read_scope)}",
        f"Write scope (you may write nothing else): {_list(unit.write_scope)}",
        f"Forbidden, even if reading it would help: {_list(unit.forbidden_scope)}",
        "",
        "Procedure:\n" + _numbered(unit.procedure),
        "",
        f"Acceptance:\n{acceptance}",
        "",
        f"Expected artifacts: {_list(unit.expected_artifacts)}",
        output_contract_block(unit),
        "",
        _commands_block(commands_red, commands_green),
        "",
        progress_block(unit),
        "",
        "Stop and report instead of continuing when:\n" + _bulleted(unit.stop_conditions),
        "",
        "If you need something outside your read scope, ask your manager for it. Do not "
        "widen your own scope, and do not work around a missing input by inventing it.",
        "",
        report_template(unit),
    ]
    return "\n".join(block for block in blocks if block is not None)


def emit(plan: Plan, units: list[Unit]) -> list[dict[str, Any]]:
    """One spawn descriptor per unit, ready to hand to a subagent tool."""

    return [
        {
            "id": unit.unit_id,
            "content": build(plan, unit),
            "kind": unit.kind,
            "depends_on": list(unit.dependencies),
            "model": unit.primary_route,
            "fallback_model": unit.fallback_route or None,
            # Visible, not headless. A headless worker does the work and never
            # appears in the swarm roster, so the Director cannot see it start,
            # stall, or finish, and the status roster becomes fiction.
            "spawn_mode": "visible",
            "metadata": {
                "review_owner": unit.manager_id,
                "write_scopes": list(unit.write_scope),
                "read_scopes": list(unit.read_scope),
                "forbidden_scopes": list(unit.forbidden_scope),
                "acceptance_ids": list(unit.acceptance_ids),
                "risk": unit.risk,
                "max_attempts": unit.attempt_limit,
                "command_timeout_seconds": unit.progress_contract.get("command_timeout_seconds"),
                "checkpoint_every": unit.progress_contract.get("checkpoint_every"),
            },
        }
        for unit in units
    ]


def _acceptance_text(plan: Plan, unit: Unit) -> str:
    descriptions = {
        str(item.get("id")): str(item.get("description", ""))
        for item in plan.acceptance
        if isinstance(item, dict)
    }
    lines = [
        f"- {acceptance_id}: {descriptions.get(acceptance_id, '(not described in the plan)')}"
        for acceptance_id in unit.acceptance_ids
    ]
    return "\n".join(lines) if lines else "- (none declared)"


def _commands_block(red: tuple[str, ...], green: tuple[str, ...]) -> str:
    lines = []
    if red:
        lines.append(
            "Run these first. They should fail now; if one already passes, the work may "
            "already be done or the command may be checking the wrong thing, and either "
            "way you stop and report:\n" + _bulleted(red)
        )
    lines.append(
        "These must pass when you are done, and their real output goes in your report:\n"
        + _bulleted(green)
    )
    return "\n\n".join(lines)


def _list(values: tuple[str, ...]) -> str:
    return ", ".join(values) if values else "(none)"


def _bulleted(values: tuple[str, ...]) -> str:
    return "\n".join(f"- {value}" for value in values) if values else "- (none)"


def _numbered(values: tuple[str, ...]) -> str:
    return (
        "\n".join(f"{index}. {value}" for index, value in enumerate(values, 1))
        if values
        else "1. (none declared)"
    )
