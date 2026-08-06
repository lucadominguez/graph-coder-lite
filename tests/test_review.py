"""The manager verdict, and what makes one a review rather than an assertion."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

import pytest

from gcl import graph as graph_module
from gcl import plan as plan_module
from gcl.cli import main
from gcl.errors import StateError
from gcl.state import RunState


def gcl(project, *argv: str) -> tuple[int, dict]:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = main(["--root", str(project), *argv])
    return code, json.loads(buffer.getvalue())


def submitted(project, unit_id: str) -> None:
    """Drive a unit to awaiting_review, the way a real round does."""

    for target in ("ready", "running", "awaiting_review"):
        gcl(project, "set", unit_id, target)


class TestVerdictsMustBeJustified:
    def test_completed_cannot_be_recorded_by_hand(self, project):
        submitted(project, "IU-MIGRATION")
        code, payload = gcl(project, "set", "IU-MIGRATION", "completed")
        assert code == 1
        assert "not a transition you record by hand" in payload["error"]

    @pytest.mark.parametrize("state", ["repair_required", "human_required"])
    def test_neither_can_the_other_verdict_states(self, project, state):
        submitted(project, "IU-MIGRATION")
        code, payload = gcl(project, "set", "IU-MIGRATION", state)
        assert code == 1 and "manager verdict" in payload["error"]

    def test_a_pass_needs_evidence(self, project):
        # A pass with no evidence is the worker's own say-so wearing a
        # manager's name.
        submitted(project, "IU-MIGRATION")
        code, payload = gcl(project, "review", "IU-MIGRATION", "--verdict", "pass")
        assert code == 1
        assert "own claim of success is not evidence" in payload["error"]

    def test_a_repair_needs_a_defect(self, project):
        submitted(project, "IU-MIGRATION")
        code, payload = gcl(
            project, "review", "IU-MIGRATION", "--verdict", "repair_required", "--repair", "redo it"
        )
        assert code == 1 and "at least one --defect" in payload["error"]

    def test_a_repair_needs_an_instruction(self, project):
        submitted(project, "IU-MIGRATION")
        code, payload = gcl(
            project,
            "review",
            "IU-MIGRATION",
            "--verdict",
            "repair_required",
            "--defect",
            "the down path leaves a stray index",
        )
        assert code == 1
        assert "a complaint, not a review" in payload["error"]

    def test_an_escalation_needs_the_question_and_the_attempts(self, project):
        submitted(project, "IU-MIGRATION")
        code, payload = gcl(
            project, "review", "IU-MIGRATION", "--verdict", "human_required", "--attempted", "twice"
        )
        assert code == 1 and "--question" in payload["error"]

        code, payload = gcl(
            project,
            "review",
            "IU-MIGRATION",
            "--verdict",
            "human_required",
            "--question",
            "which schema wins?",
        )
        assert code == 1
        assert "does not repeat what already failed" in payload["error"]

    def test_a_review_only_applies_to_a_submitted_unit(self, project):
        code, payload = gcl(
            project, "review", "IU-MIGRATION", "--verdict", "pass", "--evidence", "tests pass"
        )
        assert code == 1
        assert "A worker submits its report first" in payload["error"]


class TestAPassingReview:
    def test_it_completes_the_unit_and_records_the_evidence(self, project):
        submitted(project, "IU-MIGRATION")
        code, payload = gcl(
            project,
            "review",
            "IU-MIGRATION",
            "--verdict",
            "pass",
            "--evidence",
            "make migrate-test: 3 passed",
        )
        assert code == 0
        assert payload["status"] == "completed"
        assert payload["review"]["evidence"] == ["make migrate-test: 3 passed"]

    def test_it_names_what_it_just_unblocked(self, project):
        submitted(project, "IU-MIGRATION")
        _, payload = gcl(
            project, "review", "IU-MIGRATION", "--verdict", "pass", "--evidence", "3 passed"
        )
        assert payload["now_eligible"] == ["IU-STORE"]

    def test_every_completion_carries_a_review_record(self, project):
        submitted(project, "IU-MIGRATION")
        gcl(project, "review", "IU-MIGRATION", "--verdict", "pass", "--evidence", "3 passed")
        state = RunState.load(project)
        assert state.unverified_completions() == []
        assert state.reviews("IU-MIGRATION")[0]["verdict"] == "pass"


class TestBlastRadius:
    def test_an_escalation_reports_what_is_blocked_and_what_continues(self, project):
        # An isolated failure must not stop work that does not depend on it, and
        # the only honest way to say so is to compute it.
        submitted(project, "IU-MIGRATION")
        gcl(project, "review", "IU-MIGRATION", "--verdict", "pass", "--evidence", "3 passed")
        submitted(project, "IU-STORE")
        _, payload = gcl(
            project,
            "review",
            "IU-STORE",
            "--verdict",
            "human_required",
            "--question",
            "should revocation cascade?",
            "--attempted",
            "read the schema; no cascade column exists",
        )
        assert payload["blocked"] == ["IU-ENDPOINT"]
        assert payload["still_runnable"] == ["IU-SCHEMA"]

    def test_blocked_is_transitive(self, example_text):
        plan = plan_module.parse(example_text)
        assert graph_module.blocked_by(plan, "IU-MIGRATION") == ["IU-ENDPOINT", "IU-STORE"]

    def test_a_leaf_blocks_nothing(self, example_text):
        plan = plan_module.parse(example_text)
        assert graph_module.blocked_by(plan, "IU-ENDPOINT") == []

    def test_an_unknown_unit_is_refused(self, example_text):
        plan = plan_module.parse(example_text)
        with pytest.raises(Exception, match="unknown unit"):
            graph_module.blocked_by(plan, "IU-GHOST")


class TestRecovery:
    def test_a_completion_with_no_review_is_surfaced(self, project):
        state = RunState.load(project)
        state.sync(["IU-MIGRATION"], plan_id="P-x", plan_hash="h")
        state.nodes["IU-MIGRATION"] = {"status": "completed", "attempts": 1}
        state.save()
        _, payload = gcl(project, "recover")
        assert payload["completed_without_a_passing_review"] == ["IU-MIGRATION"]
        assert "not done" in payload["next"]

    def test_nothing_is_changed_without_apply(self, project):
        state = RunState.load(project)
        state.sync(["IU-MIGRATION"], plan_id="P-x", plan_hash="h")
        state.nodes["IU-MIGRATION"] = {"status": "completed", "attempts": 1}
        state.save()
        gcl(project, "recover")
        assert RunState.load(project).status("IU-MIGRATION") == "completed"

    def test_apply_reopens_it_without_losing_the_attempt_count(self, project):
        state = RunState.load(project)
        state.sync(["IU-MIGRATION"], plan_id="P-x", plan_hash="h")
        state.nodes["IU-MIGRATION"] = {"status": "completed", "attempts": 2}
        state.save()
        gcl(project, "recover", "--apply")
        reloaded = RunState.load(project)
        assert reloaded.status("IU-MIGRATION") == "failed"
        assert reloaded.attempts("IU-MIGRATION") == 2

    def test_an_in_flight_unit_is_not_inferred_to_have_finished(self, project):
        submitted(project, "IU-MIGRATION")
        _, payload = gcl(project, "recover")
        assert payload["in_flight_when_the_session_ended"] == ["IU-MIGRATION"]

    def test_a_plan_edited_since_the_state_was_written_is_flagged(self, project):
        gcl(project, "status")
        text = (project / "PLAN.md").read_text(encoding="utf-8")
        (project / "PLAN.md").write_text(
            text.replace("command_timeout_seconds: 120", "command_timeout_seconds: 150", 1),
            encoding="utf-8",
        )
        _, payload = gcl(project, "recover")
        assert payload["plan_changed_since_the_state_was_written"] is True

    def test_prose_edited_since_the_state_was_written_is_not_flagged(self, project):
        # The hash covers unit contracts, so reformatting the plan does not read
        # as a change the run has to reconcile.
        gcl(project, "status")
        text = (project / "PLAN.md").read_text(encoding="utf-8")
        (project / "PLAN.md").write_text(text.replace("Operators can", "An operator can", 1))
        _, payload = gcl(project, "recover")
        assert payload["plan_changed_since_the_state_was_written"] is False

    def test_a_clean_run_has_nothing_to_reconcile(self, project):
        _, payload = gcl(project, "recover")
        assert payload["completed_without_a_passing_review"] == []
        assert payload["next"] == "Nothing to reconcile."


def test_the_state_object_refuses_an_unknown_verdict(tmp_path):
    state = RunState.load(tmp_path)
    state.sync(["IU-A"], plan_id="P", plan_hash="h")
    state.transition("IU-A", "ready")
    state.transition("IU-A", "running")
    state.transition("IU-A", "awaiting_review")
    with pytest.raises(StateError, match="unknown verdict"):
        state.review("IU-A", "looks_fine")
