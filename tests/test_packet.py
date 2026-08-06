"""The packet is the whole contract a worker sees. What it omits, nobody enforces."""

from __future__ import annotations

from gcl import packet as packet_module
from gcl import plan as plan_module


def build(text: str, unit_id: str) -> str:
    plan = plan_module.parse(text)
    return packet_module.build(plan, plan.unit(unit_id))


def test_the_worker_is_told_who_reviews_it(example_text):
    content = build(example_text, "IU-STORE")
    assert "Submit your report to manager M-STORAGE" in content
    assert "you do not mark yourself complete" in content


def test_a_unit_with_no_manager_tells_the_worker_to_stop(mutate, unit_of):
    content = build(
        mutate(lambda meta: unit_of(meta, "IU-STORE").update(manager_id="")), "IU-STORE"
    )
    assert "not a licence to self-approve" in content


def test_every_output_contract_assertion_reaches_the_worker(example_text):
    content = build(example_text, "IU-STORE")
    assert "revoke_token and is_revoked are importable" in content
    assert "exactly one audit row" in content
    assert "empty or malformed is a failure, not a completion" in content


def test_a_unit_with_no_output_contract_says_so_rather_than_inventing_one(mutate, unit_of):
    content = build(
        mutate(lambda meta: unit_of(meta, "IU-STORE").update(output_contract=[])), "IU-STORE"
    )
    assert "Escalate rather than inventing one" in content


class TestProgressProtocol:
    def test_an_incremental_unit_is_told_not_to_buffer(self, example_text):
        content = build(example_text, "IU-STORE")
        assert "each function, then each test" in content
        assert "Do not hold results in memory and write once at the end" in content

    def test_a_single_pass_unit_gets_the_opposite_instruction(self, example_text):
        # Judging both by one rule gives false alarms on one and blindness on the
        # other, which is why the cadence is declared per unit.
        content = build(example_text, "IU-MIGRATION")
        assert "writes its output once, in a single pass" in content
        assert "Do not hold results in memory" not in content

    def test_the_command_timeout_reaches_the_worker_with_its_reason(self, example_text):
        content = build(example_text, "IU-ENDPOINT")
        assert "No single command may run longer than 300 seconds" in content
        assert "cannot answer a message, cannot report" in content

    def test_the_progress_log_is_the_only_permitted_scope_exception(self, example_text):
        content = build(example_text, "IU-STORE")
        assert ".gcl/progress/IU-STORE.log" in content
        assert "the only path outside that scope you may touch" in content


def test_scopes_are_stated_as_hard_bounds(example_text):
    content = build(example_text, "IU-STORE")
    assert "you may read nothing else" in content
    assert "you may write nothing else" in content
    assert "Forbidden, even if reading it would help" in content


def test_acceptance_arrives_with_its_description_not_just_an_id(example_text):
    content = build(example_text, "IU-STORE")
    assert "AC-DOUBLE-REVOKE: Revoking an already revoked token" in content


def test_red_commands_carry_the_already_passing_warning(example_text):
    content = build(example_text, "IU-STORE")
    assert "They should fail now" in content
    assert "you stop and report" in content


def test_the_report_template_forbids_unevidenced_claims(example_text):
    content = build(example_text, "IU-STORE")
    assert "Do not claim a command passed without its output" in content


def test_the_worker_is_told_to_ask_rather_than_widen_its_own_scope(example_text):
    content = build(example_text, "IU-STORE")
    assert "Do not widen your own scope" in content


class TestEmit:
    def test_every_spawn_is_visible(self, example_text):
        plan = plan_module.parse(example_text)
        for entry in packet_module.emit(plan, list(plan.units)):
            # A headless worker does the work and never appears in the roster, so
            # the Director cannot see it start, stall, or finish.
            assert entry["spawn_mode"] == "visible"

    def test_the_fallback_model_rides_beside_the_model(self, mutate):
        def edit(meta):
            for unit in meta["units"]:
                unit["route"] = {"primary": "fast-model", "fallback": "other-model"}

        plan = plan_module.parse(mutate(edit))
        entry = packet_module.emit(plan, [plan.unit("IU-STORE")])[0]
        assert entry["model"] == "fast-model"
        # A fallback retry is the same spawn with this substituted, so it needs
        # no lookup and no judgment while a run is in flight.
        assert entry["fallback_model"] == "other-model"

    def test_a_missing_fallback_is_null_rather_than_guessed(self, mutate):
        def edit(meta):
            for unit in meta["units"]:
                unit["route"] = {"primary": "fast-model"}

        plan = plan_module.parse(mutate(edit))
        entry = packet_module.emit(plan, [plan.unit("IU-STORE")])[0]
        assert entry["fallback_model"] is None

    def test_metadata_carries_what_the_director_monitors_on(self, example_text):
        plan = plan_module.parse(example_text)
        entry = packet_module.emit(plan, [plan.unit("IU-STORE")])[0]
        assert entry["metadata"]["review_owner"] == "M-STORAGE"
        assert entry["metadata"]["checkpoint_every"] == "each function, then each test"
        assert entry["metadata"]["command_timeout_seconds"] == 180
        assert entry["metadata"]["write_scopes"] == [
            "src/store/tokens.py",
            "tests/test_token_store.py",
        ]
