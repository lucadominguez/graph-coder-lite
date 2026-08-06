"""The `gcl` command line. Seven commands, and none of them writes your code."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from gcl import graph as graph_module
from gcl import packet as packet_module
from gcl import plan as plan_module
from gcl.errors import GclError, StateError
from gcl.state import VERDICT_STATES, RunState

DEFAULT_PLAN = "PLAN.md"

#: Shipped as package data, so `gcl init` works from an installed wheel and not
#: only from a checkout. It doubles as the format spec and as a CI fixture, so a
#: change that breaks the schema breaks the example in the same run.
TEMPLATE = Path(__file__).resolve().parent / "templates" / "example-plan.md"


def _plan_path(args: argparse.Namespace) -> Path:
    return Path(args.root) / args.plan


def _load(args: argparse.Namespace) -> plan_module.Plan:
    return plan_module.load(_plan_path(args))


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, default=str))


def cmd_init(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root)
    target = _plan_path(args)
    created = False
    if not target.exists():
        target.write_text(TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
        created = True
    state = RunState.load(root)
    state.event("init", plan=str(target))
    state.save()
    return {
        "ok": True,
        "plan": str(target),
        "created": created,
        "state": str(state.path),
        "next": "Fill in the six sections and the units, then run `gcl check`.",
    }


def cmd_check(args: argparse.Namespace) -> dict[str, Any]:
    plan = _load(args)
    defects = plan_module.readiness_defects(plan)
    defects.extend(graph_module.structural_defects(plan))
    order = []
    try:
        order = graph_module.topological_order(plan)
    except GclError:
        pass
    payload = {
        "ok": not defects,
        "plan_id": plan.plan_id,
        "plan_version": plan.plan_version,
        "readiness": plan.readiness,
        "units": len(plan.units),
        "managers": len(plan.managers),
        "topological_order": order,
        "defects": defects,
    }
    if defects:
        payload["next"] = (
            "Fix these in the plan itself, not in the packet you hand a worker. "
            "A plan that is not ready cannot be approved or dispatched."
        )
    return payload


def cmd_emit(args: argparse.Namespace) -> dict[str, Any]:
    plan = _load(args)
    defects = plan_module.readiness_defects(plan) + graph_module.structural_defects(plan)
    state = RunState.load(Path(args.root))
    state.sync(list(plan.unit_ids), plan_id=plan.plan_id, plan_hash=plan_module.approval_hash(plan))

    spawn_ids, queued = graph_module.dispatch_round(plan, state.states())
    if args.unit:
        spawn_ids = [unit_id for unit_id in args.unit if unit_id in plan.unit_ids]
        queued = []
    units = [plan.unit(unit_id) for unit_id in spawn_ids]
    flight = graph_module.preflight(plan, units)
    if defects:
        flight["ready_to_dispatch"] = False
        flight.setdefault("warnings", []).insert(
            0, f"the plan has {len(defects)} unresolved defects; run `gcl check`"
        )
    state.save()
    return {
        "ok": True,
        "preflight": flight,
        "spawn": packet_module.emit(plan, units),
        "queued": queued,
        "max_active_workers": plan.max_active_workers,
    }


def cmd_status(args: argparse.Namespace) -> dict[str, Any]:
    plan = _load(args)
    state = RunState.load(Path(args.root))
    state.sync(list(plan.unit_ids), plan_id=plan.plan_id, plan_hash=plan_module.approval_hash(plan))
    states = state.states()
    ready, queued = graph_module.dispatch_round(plan, states)
    blocked_by: dict[str, list[str]] = {}
    for unit in plan.units:
        if states.get(unit.unit_id) in ("completed", "running", "awaiting_review"):
            continue
        waiting = [
            dependency
            for dependency in unit.dependencies
            if states.get(dependency) != graph_module.TERMINAL_PASS
        ]
        if waiting:
            blocked_by[unit.unit_id] = waiting
    state.save()
    return {
        "ok": True,
        "plan_id": plan.plan_id,
        "states": states,
        "frontier": ready,
        "queued": queued,
        "waiting_on_dependencies": blocked_by,
        "complete": all(status == "completed" for status in states.values()) and bool(states),
    }


def cmd_set(args: argparse.Namespace) -> dict[str, Any]:
    plan = _load(args)
    state = RunState.load(Path(args.root))
    state.sync(list(plan.unit_ids), plan_id=plan.plan_id, plan_hash=plan_module.approval_hash(plan))
    if args.unit not in plan.unit_ids:
        raise GclError(f"no unit {args.unit} in the plan")
    if args.state in VERDICT_STATES.values():
        raise GclError(
            f"`{args.state}` is a manager verdict, not a transition you record by hand. "
            f"Use `gcl review {args.unit} --verdict <pass|repair_required|human_required>`, "
            "which requires the evidence or the defect that justifies it."
        )
    node = state.transition(args.unit, args.state, note=args.note or "")
    state.save()
    return {"ok": True, "unit": args.unit, "node": node}


def cmd_review(args: argparse.Namespace) -> dict[str, Any]:
    """Record a manager verdict. The only way a unit reaches `completed`."""

    plan = _load(args)
    state = RunState.load(Path(args.root))
    state.sync(list(plan.unit_ids), plan_id=plan.plan_id, plan_hash=plan_module.approval_hash(plan))
    if args.unit not in plan.unit_ids:
        raise GclError(f"no unit {args.unit} in the plan")

    impacted = graph_module.blocked_by(plan, args.unit) if args.verdict == "human_required" else []
    try:
        record = state.review(
            args.unit,
            args.verdict,
            evidence=args.evidence,
            defects=args.defect,
            repairs=args.repair,
            question=args.question or "",
            attempted=args.attempted,
            impacted=impacted,
        )
    except StateError as error:
        raise GclError(str(error)) from error

    payload: dict[str, Any] = {
        "ok": True,
        "unit": args.unit,
        "verdict": args.verdict,
        "status": state.status(args.unit),
        "review": record,
    }
    if args.verdict == "human_required":
        # Say plainly what is blocked and what continues, computed rather than
        # estimated. An isolated failure must not stop independent work.
        payload["blocked"] = impacted
        payload["still_runnable"] = graph_module.still_runnable(plan, state.states(), args.unit)
    if args.verdict == "pass":
        payload["now_eligible"] = [
            unit_id
            for unit_id in graph_module.frontier(plan, state.states())
            if args.unit in plan.unit(unit_id).dependencies
        ]
    state.save()
    return payload


def cmd_recover(args: argparse.Namespace) -> dict[str, Any]:
    """Reconcile after an interruption, without inventing what happened.

    Two things survive a crash badly: a unit left `running` whose worker is gone,
    and a unit marked `completed` by a write that landed while the review that
    justified it did not.
    """

    plan = _load(args)
    state = RunState.load(Path(args.root))
    # Read the stored hash before syncing, which overwrites it. Comparing after
    # the write made this check unable to fire.
    stored = state.payload.get("plan_hash", "")
    current = plan_module.approval_hash(plan)
    state.sync(list(plan.unit_ids), plan_id=plan.plan_id, plan_hash=current)

    unverified = state.unverified_completions()
    interrupted = [
        unit_id
        for unit_id, status in state.states().items()
        if status in ("running", "awaiting_review")
    ]
    if args.apply:
        for unit_id in unverified:
            state.nodes[unit_id]["status"] = "failed"
            state.event("recover", unit_id=unit_id, reason="completed with no passing review")
        for unit_id in interrupted:
            state.nodes[unit_id]["status"] = "failed"
            state.event("recover", unit_id=unit_id, reason="in flight when the session ended")
        state.save()

    return {
        "ok": True,
        "applied": bool(args.apply),
        "completed_without_a_passing_review": unverified,
        "in_flight_when_the_session_ended": interrupted,
        "plan_changed_since_the_state_was_written": stored != current,
        "next": (
            "Re-run with --apply to reopen these as failed attempts. Nothing is inferred to "
            "have completed: a unit whose evidence you cannot produce is not done."
            if (unverified or interrupted) and not args.apply
            else "Nothing to reconcile."
            if not (unverified or interrupted)
            else "Reopened. Re-dispatch them; the attempt counts are preserved."
        ),
    }


def cmd_route_set(args: argparse.Namespace) -> dict[str, Any]:
    """Write routes into the plan.

    Hand-editing is not the fallback for this: every unrouted unit holds the
    identical line `primary: local`, so a text edit cannot target one of them.
    """

    path = _plan_path(args)
    plan = plan_module.load(path)
    targets = args.unit or [
        unit.unit_id for unit in plan.units if not unit.is_routed or args.overwrite
    ]
    unknown = sorted(set(targets) - set(plan.unit_ids))
    if unknown:
        raise GclError(f"no such units: {', '.join(unknown)}")

    text = path.read_text(encoding="utf-8")
    changed: list[str] = []
    for unit_id in targets:
        updated, did = _rewrite_route(text, unit_id, args.model, args.fallback)
        if did:
            text = updated
            changed.append(unit_id)
    if changed:
        path.write_text(text, encoding="utf-8")

    state = RunState.load(Path(args.root))
    state.event("route", units=changed, model=args.model, evidence=args.evidence)
    state.save()
    return {
        "ok": True,
        "routed": changed,
        "model": args.model,
        "fallback": args.fallback,
        "evidence": args.evidence,
        "note": (
            "Carry the evidence basis into the plan's routing note. A route chosen from a "
            "harness model list is a weaker basis than a measured one, and the user is "
            "approving a cost estimate built on it."
        ),
    }


def _rewrite_route(text: str, unit_id: str, model: str, fallback: str | None) -> tuple[str, bool]:
    """Replace the route block of exactly one unit, located by its unit_id."""

    anchor = re.search(rf"^(\s*)-\s+unit_id:\s*{re.escape(unit_id)}\s*$", text, re.MULTILINE)
    if not anchor:
        return text, False
    start = anchor.end()
    next_unit = re.search(r"^\s*-\s+unit_id:", text[start:], re.MULTILINE)
    end = start + (next_unit.start() if next_unit else len(text) - start)
    block = text[start:end]

    primary = re.search(r"^(\s*)primary:.*$", block, re.MULTILINE)
    if not primary:
        return text, False
    indent = primary.group(1)
    replacement = f"{indent}primary: {model}"
    block = block[: primary.start()] + replacement + block[primary.end() :]
    if fallback:
        existing = re.search(r"^(\s*)fallback:.*$", block, re.MULTILINE)
        line = f"{indent}fallback: {fallback}"
        if existing:
            block = block[: existing.start()] + line + block[existing.end() :]
        else:
            insert = block.find("\n", block.find(replacement)) + 1
            block = block[:insert] + line + "\n" + block[insert:]
    return text[:start] + block + text[end:], True


def cmd_approve(args: argparse.Namespace) -> dict[str, Any]:
    plan = _load(args)
    defects = plan_module.readiness_defects(plan) + graph_module.structural_defects(plan)
    if defects:
        raise GclError(
            f"the plan has {len(defects)} defects and cannot be approved. Run `gcl check`."
        )
    binding = plan_module.approval_hash(plan)
    state = RunState.load(Path(args.root))
    state.event("approved", plan_id=plan.plan_id, plan_hash=binding, rendered_in_full=args.rendered)
    state.save()
    if not args.rendered:
        raise GclError(
            "approval requires that the full plan was rendered to the user, not a summary. "
            "Render it, then pass --rendered."
        )
    path = _plan_path(args)
    text = path.read_text(encoding="utf-8")
    text = _set_frontmatter(text, "approved", "true")
    text = _set_frontmatter(text, "approval", f"\n  plan_hash: {binding}")
    path.write_text(text, encoding="utf-8")
    return {"ok": True, "plan_hash": binding, "note": "Any change to a unit contract voids this."}


def _set_frontmatter(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^{re.escape(key)}:.*(?:\n[ \t]+.*)*$", re.MULTILINE)
    line = f"{key}: {value}".rstrip()
    if pattern.search(text):
        return pattern.sub(line, text, count=1)
    return text.replace("---\n", f"---\n{line}\n", 1)


def cmd_verify(args: argparse.Namespace) -> dict[str, Any]:
    """What the manager checks before a unit may be completed.

    This does not decide the verdict. It gathers the evidence the verdict has to
    rest on, so a review cannot be recorded against an artifact nobody looked at.
    """

    plan = _load(args)
    unit = plan.unit(args.unit)
    root = Path(args.root)
    written = []
    for entry in unit.write_scope:
        candidate = root / entry
        written.append(
            {
                "path": entry,
                "exists": candidate.exists(),
                "bytes": candidate.stat().st_size if candidate.is_file() else None,
            }
        )
    missing = [item["path"] for item in written if not item["exists"]]
    return {
        "ok": True,
        "unit": unit.unit_id,
        "review_owner": unit.manager_id,
        "write_scope": written,
        "missing_paths": missing,
        "output_contract": list(unit.output_contract),
        "green_commands": list(unit.commands.get("green") or ()),
        "next": (
            "Run every green command yourself and quote the real output. Check each "
            "output-contract assertion against the artifact's contents, not its existence. "
            "A worker's own claim of success is not evidence."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gcl", description=__doc__)
    parser.add_argument("--root", default=".", help="project root (default: current directory)")
    parser.add_argument("--plan", default=DEFAULT_PLAN, help=f"plan file (default: {DEFAULT_PLAN})")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("init", help="write a starting plan and state file").set_defaults(
        handler=cmd_init
    )
    commands.add_parser("check", help="validate the plan and list every defect").set_defaults(
        handler=cmd_check
    )

    emit = commands.add_parser("emit", help="packets for the units that are ready now")
    emit.add_argument("--unit", action="append", help="emit these units instead of the frontier")
    emit.set_defaults(handler=cmd_emit)

    commands.add_parser("status", help="frontier, states, and what blocks what").set_defaults(
        handler=cmd_status
    )

    setter = commands.add_parser("set", help="record a state transition")
    setter.add_argument("unit")
    setter.add_argument("state")
    setter.add_argument("--note", default="")
    setter.set_defaults(handler=cmd_set)

    review = commands.add_parser("review", help="record a manager verdict")
    review.add_argument("unit")
    review.add_argument(
        "--verdict", required=True, choices=["pass", "repair_required", "human_required"]
    )
    review.add_argument(
        "--evidence", action="append", help="pass: real command output or artifact check"
    )
    review.add_argument("--defect", action="append", help="repair_required: one bounded defect")
    review.add_argument("--repair", action="append", help="repair_required: one instruction")
    review.add_argument("--question", help="human_required: the decision the user must make")
    review.add_argument("--attempted", action="append", help="human_required: what was tried")
    review.set_defaults(handler=cmd_review)

    recover = commands.add_parser("recover", help="reconcile after an interrupted session")
    recover.add_argument(
        "--apply", action="store_true", help="reopen what cannot be shown to have finished"
    )
    recover.set_defaults(handler=cmd_recover)

    route = commands.add_parser("route", help="routing operations").add_subparsers(
        dest="route_command", required=True
    )
    route_set = route.add_parser("set", help="write a model into the plan's units")
    route_set.add_argument("--model", required=True)
    route_set.add_argument("--fallback")
    route_set.add_argument("--unit", action="append")
    route_set.add_argument("--overwrite", action="store_true", help="also replace real routes")
    route_set.add_argument(
        "--evidence", default="operator", help="where this choice came from, recorded as-is"
    )
    route_set.set_defaults(handler=cmd_route_set)

    approve = commands.add_parser("approve", help="bind approval to the unit contracts")
    approve.add_argument(
        "--rendered", action="store_true", help="the full plan was shown to the user"
    )
    approve.set_defaults(handler=cmd_approve)

    verify = commands.add_parser("verify", help="gather review evidence for one unit")
    verify.add_argument("unit")
    verify.set_defaults(handler=cmd_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = args.handler(args)
    except GclError as error:
        _print({"ok": False, "error": str(error)})
        return 1
    _print(payload)
    return 0 if payload.get("ok", True) else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
