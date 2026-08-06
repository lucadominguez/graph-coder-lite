"""The state machine exists for one transition it refuses."""

from __future__ import annotations

import pytest

from gcl.errors import StateError
from gcl.state import RunState


@pytest.fixture
def state(tmp_path) -> RunState:
    run = RunState.load(tmp_path)
    run.sync(["IU-A", "IU-B"], plan_id="P-x", plan_hash="sha256:x")
    return run


def test_a_worker_cannot_complete_itself(state):
    state.transition("IU-A", "ready")
    state.transition("IU-A", "running")
    with pytest.raises(StateError) as error:
        state.transition("IU-A", "completed")
    assert "only a manager's passing review completes it" in str(error.value)


def test_the_legal_path_to_completion_runs_through_review(state):
    for target in ("ready", "running", "awaiting_review", "completed"):
        state.transition("IU-A", target)
    assert state.status("IU-A") == "completed"


def test_completed_is_terminal(state):
    for target in ("ready", "running", "awaiting_review", "completed"):
        state.transition("IU-A", target)
    with pytest.raises(StateError, match="terminal"):
        state.transition("IU-A", "running")


def test_a_repair_goes_back_through_running_and_review(state):
    for target in ("ready", "running", "awaiting_review", "repair_required", "running"):
        state.transition("IU-A", target)
    assert state.attempts("IU-A") == 2
    state.transition("IU-A", "awaiting_review")
    state.transition("IU-A", "completed")


def test_an_unknown_state_lists_the_valid_ones(state):
    with pytest.raises(StateError, match="valid states are"):
        state.transition("IU-A", "done")


def test_attempts_count_only_dispatches(state):
    state.transition("IU-A", "ready")
    assert state.attempts("IU-A") == 0
    state.transition("IU-A", "running")
    assert state.attempts("IU-A") == 1


def test_state_survives_a_reload(tmp_path):
    run = RunState.load(tmp_path)
    run.sync(["IU-A"], plan_id="P-x", plan_hash="sha256:x")
    run.transition("IU-A", "ready")
    run.transition("IU-A", "running")
    run.save()

    # Rebuild from the file, never from memory.
    reloaded = RunState.load(tmp_path)
    assert reloaded.status("IU-A") == "running"
    assert reloaded.attempts("IU-A") == 1


def test_sync_keeps_existing_progress_and_adds_new_units(state):
    state.transition("IU-A", "ready")
    state.sync(["IU-A", "IU-B", "IU-C"], plan_id="P-x", plan_hash="sha256:y")
    assert state.status("IU-A") == "ready"
    assert state.status("IU-C") == "pending"


def test_a_unit_the_plan_dropped_is_marked_superseded_not_deleted(state):
    state.transition("IU-B", "ready")
    state.sync(["IU-A"], plan_id="P-x", plan_hash="sha256:y")
    assert state.status("IU-B") == "superseded"


def test_every_transition_leaves_an_event(state):
    state.transition("IU-A", "ready", note="frontier")
    assert state.events[-1]["kind"] == "state"
    assert state.events[-1]["to"] == "ready"
    assert state.events[-1]["note"] == "frontier"


class TestUsageSurvivesTheRun:
    def test_a_turn_is_recorded_with_what_it_cost(self, state):
        state.record_usage(
            role="worker",
            provider="OpenAI",
            model="gpt-x",
            input_tokens=10,
            output_tokens=4,
            unit="IU-A",
        )
        assert state.usage[-1]["provider"] == "openai"  # normalized, so totals add up
        assert state.usage[-1]["input_tokens"] == 10

    def test_it_reloads_from_the_file_like_everything_else(self, tmp_path):
        run = RunState.load(tmp_path)
        run.sync(["IU-A"], plan_id="P-x", plan_hash="sha256:x")
        run.record_usage(
            role="director", provider="openai", model="gpt-x", input_tokens=1, output_tokens=2
        )
        run.save()
        assert len(RunState.load(tmp_path).usage) == 1

    def test_a_role_the_budget_does_not_know_is_refused(self, state):
        with pytest.raises(StateError, match="unknown role"):
            state.record_usage(
                role="intern", provider="openai", model="gpt-x", input_tokens=1, output_tokens=1
            )

    @pytest.mark.parametrize("bad", [-1, 1.5, True, "900"])
    def test_tokens_must_be_a_non_negative_integer(self, state, bad):
        with pytest.raises(StateError, match="non-negative integer"):
            state.record_usage(
                role="worker", provider="openai", model="gpt-x", input_tokens=bad, output_tokens=0
            )
