"""The skills are the product. These pin the rules that were paid for in real runs.

Each assertion below corresponds to a failure that actually happened. A future
edit is free to reword any of them; it is not free to delete the rule.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
ACTIVE = ("graph-coder-lite", "gcl-plan", "gcl-review")


def read(relative: str) -> str:
    """Read a skill with its hard wrapping collapsed.

    The files are wrapped at 80 columns, so a phrase these tests pin can span a
    newline. Collapsing whitespace lets an assertion be about the rule rather
    than about where the line happened to break.
    """

    return " ".join(raw(relative).split())


def raw(relative: str) -> str:
    """The file exactly as a skill loader sees it, wrapping included."""

    return (SKILLS / relative).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def orchestrator() -> str:
    return read("graph-coder-lite/SKILL.md")


@pytest.fixture(scope="module")
def dispatch() -> str:
    return read("graph-coder-lite/references/dispatch.md")


@pytest.fixture(scope="module")
def planner() -> str:
    return read("gcl-plan/SKILL.md")


@pytest.fixture(scope="module")
def reviewer() -> str:
    return read("gcl-review/SKILL.md")


@pytest.fixture(scope="module")
def every_skill() -> str:
    return "\n".join(read(f"{name}/SKILL.md") for name in ACTIVE)


def test_exactly_the_three_skills_exist():
    present = {path.parent.name for path in SKILLS.glob("*/SKILL.md")}
    assert present == set(ACTIVE)


@pytest.mark.parametrize("name", ACTIVE)
def test_every_skill_has_frontmatter_with_a_matching_name(name):
    text = raw(f"{name}/SKILL.md")
    assert text.startswith("---\n")
    header = text.split("---", 2)[1]
    assert f"name: {name}" in header
    assert "description:" in header


class TestTheCutsHeld:
    """The simplification is only real if the removed phases stay removed."""

    def test_the_removed_passes_are_named_as_removed(self, reviewer):
        # The skills are allowed to mention rehearsal; they are required to
        # mention it only to say there is not one. A phrase ban would forbid the
        # sentence that does the work.
        assert "no rehearsal pass before it and no second opinion after it" in reviewer

    def test_no_skill_describes_running_a_rehearsal(self, every_skill):
        for procedure in ("cold rehearsal", "rehearse each", "Product Contract"):
            assert procedure.lower() not in every_skill.lower()

    def test_there_are_four_phases(self, orchestrator):
        assert "Four phases" in orchestrator
        for phase in ("1. GROUND", "2. PLAN", "3. APPROVE", "4. EXECUTE"):
            assert phase in orchestrator

    def test_review_is_a_verdict_and_never_a_node(self, planner):
        assert "no `review` member" in planner
        assert "never a unit" in planner

    def test_the_single_review_is_stated_as_the_only_one(self, reviewer):
        # Removing the rehearsal pass makes this review load-bearing, so the
        # skill has to say that rather than assume it.
        assert "only review in the system" in reviewer


class TestAuthorityBoundaries:
    def test_the_director_never_implements(self, orchestrator):
        assert "never becomes the implementer of last resort" in orchestrator
        assert "You do not implement" in orchestrator

    def test_a_manager_never_edits_files(self, reviewer):
        assert "may never edit repository files" in reviewer
        assert "it is a repair for a worker, not advice" in reviewer

    def test_a_repair_is_a_spawn_not_a_fix(self, reviewer):
        assert "Repairs are spawns" in reviewer

    def test_a_worker_never_reviews_itself(self, orchestrator):
        assert "review its own work" in orchestrator


class TestDispatchMechanics:
    def test_global_swarm_cleanup_is_forbidden_with_its_reason(self, dispatch):
        # A run followed this advice and stopped every worker on the machine,
        # including agents belonging to unrelated projects.
        assert "Never open with `swarm cleanup --force`" in dispatch
        assert "unrelated projects" in dispatch

    def test_spawns_must_be_visible(self, dispatch, orchestrator):
        assert "spawn_mode: visible" in dispatch
        assert "not optional" in dispatch
        assert "spawning headless" in orchestrator

    def test_the_batch_path_is_marked_brittle_with_the_fallback(self, dispatch):
        assert "run_plan" in dispatch
        assert "Only the coordinator can assign tasks" in dispatch
        assert "drop straight to per-unit spawns" in dispatch

    def test_both_signals_are_watched(self, dispatch):
        # A worker blocked on a 429 writes nothing, exactly like one that is
        # thinking. One run watched a directory for two minutes.
        assert "filesystem" in dispatch and "swarm status" in dispatch
        assert "429" in dispatch
        assert "two minutes" in dispatch

    def test_a_live_transcript_cannot_be_read(self, dispatch):
        assert "cannot read a live worker's transcript" in dispatch
        assert "read_context" in dispatch

    def test_the_stall_table_survives_with_its_bound(self, dispatch):
        assert "under 60s" in dispatch and "300s" in dispatch
        assert "Stop it before spawning its replacement" in dispatch

    def test_a_placeholder_route_stops_dispatch(self, dispatch, orchestrator):
        assert "ready_to_dispatch: false" in dispatch
        assert "not the run that was approved" in dispatch
        assert "placeholder route" in orchestrator

    def test_packets_go_out_verbatim(self, orchestrator, dispatch):
        assert "verbatim" in orchestrator and "verbatim" in dispatch

    def test_a_harness_without_subagents_stops_the_run(self, dispatch):
        assert "cannot run the graph" in dispatch
        assert "Do not silently degrade" in dispatch

    def test_parallel_and_serial_are_both_named_as_mistakes(self, dispatch):
        assert "linear chain" in dispatch
        assert "reverse mistake" in dispatch


class TestContractsThatMakeWorkersCheap:
    def test_the_output_contract_is_a_gate(self, planner):
        assert "gate, not a description" in planner
        assert "satisfied by a scraper that returns nothing" in planner

    def test_the_progress_contract_explains_the_stall_problem(self, planner):
        assert "900 items" in planner
        assert "checkpoint_every" in planner
        assert "writes_incrementally" in planner

    def test_the_command_timeout_carries_its_reason(self, planner):
        assert "command_timeout_seconds" in planner
        assert "cannot answer a message" in planner

    def test_concurrent_writers_are_refused_including_on_windows(self, planner):
        assert "must not write the same file" in planner
        assert "SRC/Store.py" in planner

    def test_one_manager_per_branch_not_per_worker(self, planner):
        assert "never one per worker" in planner

    def test_the_cost_model_prefers_cheapest_that_passes(self, orchestrator):
        assert "Cheapest-that-passes, not cheapest" in orchestrator
        assert "pays for its context twice" in orchestrator


class TestTheBudgetIsEnforcedNotIntended:
    """A run spent a fifth of a weekly allowance on a notes app. These are why."""

    def test_the_planner_makes_a_budget_mandatory_with_its_reason(self, planner):
        assert "circuit breaker, not an intention" in planner
        assert "control_plane_share_max" in planner
        assert "cannot be stopped when it starts costing more than the work is worth" in planner

    def test_the_protected_provider_is_explained_by_why_price_fails(self, planner, orchestrator):
        for text in (planner, orchestrator):
            assert "no marginal dollar price" in text
        assert "weekly quota is finite" in planner
        assert "--allow-protected" in orchestrator

    def test_the_control_plane_is_named_as_overhead(self, planner, reviewer):
        assert "overhead, not work" in planner
        assert "your turns are in it" in reviewer

    def test_spend_must_be_recorded_as_it_happens(self, orchestrator, reviewer):
        assert "gcl usage record" in orchestrator and "gcl usage record" in reviewer
        assert "cannot measure its own spend cannot be stopped" in orchestrator
        assert "An unrecorded turn is not a free one" in reviewer

    def test_clearing_a_stop_alone_is_named_as_a_failed_execution(self, orchestrator):
        assert "raising the budget yourself to clear a stop" in orchestrator
        assert "never yours" in orchestrator


class TestGates:
    def test_completion_requires_a_passing_review(self, orchestrator):
        assert "a worker that says it is done is not done" in orchestrator.lower()

    def test_the_escalation_ladder_is_bounded(self, orchestrator, reviewer):
        for text in (orchestrator, reviewer):
            assert "human_required" in text
            assert "lengthen" in text or "nothing may lengthen" in text

    def test_a_blocked_branch_does_not_stop_the_others(self, orchestrator, reviewer):
        for text in (orchestrator, reviewer):
            assert "dependents and nothing else" in text

    def test_approval_needs_the_full_plan(self, orchestrator):
        assert "A summary is not an approval view" in orchestrator

    def test_secrets_never_enter_the_plan(self, orchestrator):
        assert "Never ask for a plaintext key" in orchestrator

    def test_a_green_build_is_not_evidence(self, orchestrator):
        assert "green build is not evidence" in orchestrator


def test_every_command_the_orchestrator_names_exists():
    """Read the file unwrapped: the collapsed fixture is one line, so a line-wise
    check against it silently sees a single token and passes on nothing."""

    from gcl.cli import build_parser

    parser = build_parser()
    known = set()
    for action in parser._subparsers._group_actions:  # noqa: SLF001
        known.update(action.choices)
    block = raw("graph-coder-lite/SKILL.md").split("## Commands")[1].split("```")[1]
    # `gcl route set` and `gcl usage record` are subcommands; the word after
    # `gcl` is the one that has to be registered.
    named = {line.split()[1] for line in block.strip().splitlines() if line.startswith("gcl ")}
    assert named
    assert named <= known


def test_no_em_dashes_in_any_skill(every_skill, dispatch):
    for text in (every_skill, dispatch):
        assert "—" not in text
