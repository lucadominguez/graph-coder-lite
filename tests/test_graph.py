"""The three questions prose cannot answer: acyclic, dispatchable, write-safe."""

from __future__ import annotations

import pytest

from gcl import graph as graph_module
from gcl import plan as plan_module
from gcl.errors import ContractError


def parse(text):
    return plan_module.parse(text)


def test_topological_order_respects_dependencies(example_text):
    order = graph_module.topological_order(parse(example_text))
    assert order.index("IU-MIGRATION") < order.index("IU-STORE")
    assert order.index("IU-STORE") < order.index("IU-ENDPOINT")
    assert order.index("IU-SCHEMA") < order.index("IU-ENDPOINT")


def test_a_cycle_names_its_members(mutate, unit_of):
    def edit(meta):
        unit_of(meta, "IU-MIGRATION")["dependencies"] = ["IU-ENDPOINT"]

    with pytest.raises(ContractError, match="cycle"):
        graph_module.topological_order(parse(mutate(edit)))


def test_two_concurrent_units_writing_one_file_is_a_defect(mutate, unit_of):
    # IU-MIGRATION and IU-SCHEMA have no dependency between them, so nothing
    # orders their writes. Two workers in one write scope is the conflict the
    # graph exists to prevent, and it is invisible by eye past a few units.
    def edit(meta):
        unit_of(meta, "IU-SCHEMA")["write_scope"].append("migrations/002_token_revocation.sql")

    defects = graph_module.structural_defects(parse(mutate(edit)))
    assert any("can run at the same time and both write" in defect for defect in defects)


def test_a_shared_write_scope_is_fine_when_a_dependency_orders_it(mutate, unit_of):
    # IU-STORE depends on IU-MIGRATION, so they never run together.
    def edit(meta):
        unit_of(meta, "IU-STORE")["write_scope"].append("migrations/002_token_revocation.sql")
        unit_of(meta, "IU-STORE")["forbidden_scope"].remove("migrations/001_initial.sql")

    assert graph_module.structural_defects(parse(mutate(edit))) == []


def test_a_directory_write_scope_conflicts_with_a_file_inside_it(mutate, unit_of):
    def edit(meta):
        unit_of(meta, "IU-SCHEMA")["write_scope"] = ["migrations/"]
        unit_of(meta, "IU-SCHEMA")["forbidden_scope"] = [".env", ".git/", "src/store/"]

    defects = graph_module.structural_defects(parse(mutate(edit)))
    assert any("both write" in defect for defect in defects)


def test_a_dependent_that_cannot_read_its_dependency_is_a_defect(mutate, unit_of):
    def edit(meta):
        unit_of(meta, "IU-STORE")["read_scope"] = ["src/store/tokens.py", "src/store/models.py"]

    defects = graph_module.structural_defects(parse(mutate(edit)))
    assert any("covers none of that unit's artifacts" in defect for defect in defects)


class TestFrontier:
    def test_only_units_with_no_dependencies_start(self, example_text):
        plan = parse(example_text)
        states = dict.fromkeys(plan.unit_ids, "pending")
        assert graph_module.frontier(plan, states) == ["IU-MIGRATION", "IU-SCHEMA"]

    def test_a_running_dependency_does_not_release_its_dependent(self, example_text):
        plan = parse(example_text)
        states = dict.fromkeys(plan.unit_ids, "pending")
        states["IU-MIGRATION"] = "running"
        assert "IU-STORE" not in graph_module.frontier(plan, states)

    def test_awaiting_review_does_not_release_it_either(self, example_text):
        # A worker that says it is done is not done. Only a passing review makes
        # dependents eligible.
        plan = parse(example_text)
        states = dict.fromkeys(plan.unit_ids, "pending")
        states["IU-MIGRATION"] = "awaiting_review"
        assert "IU-STORE" not in graph_module.frontier(plan, states)

    def test_a_completed_dependency_does(self, example_text):
        plan = parse(example_text)
        states = dict.fromkeys(plan.unit_ids, "pending")
        states["IU-MIGRATION"] = "completed"
        assert "IU-STORE" in graph_module.frontier(plan, states)


def test_overflow_is_queued_not_dropped(mutate):
    plan = parse(mutate(lambda meta: meta["bounds"].update(max_active_workers=1)))
    states = dict.fromkeys(plan.unit_ids, "pending")
    spawn, queued = graph_module.dispatch_round(plan, states)
    assert spawn == ["IU-MIGRATION"]
    assert queued == ["IU-SCHEMA"]


def test_active_workers_reduce_the_round(mutate):
    plan = parse(mutate(lambda meta: meta["bounds"].update(max_active_workers=2)))
    states = dict.fromkeys(plan.unit_ids, "pending")
    states["IU-MIGRATION"] = "running"
    spawn, _ = graph_module.dispatch_round(plan, states)
    assert spawn == ["IU-SCHEMA"]


class TestPreflight:
    def test_a_placeholder_route_blocks_dispatch(self, example_text):
        plan = parse(example_text)
        flight = graph_module.preflight(plan)
        assert flight["ready_to_dispatch"] is False
        assert flight["unrouted_units"] == sorted(plan.unit_ids)

    def test_an_unapproved_plan_blocks_dispatch(self, mutate):
        def edit(meta):
            meta["approved"] = True
            for unit in meta["units"]:
                unit["route"] = {"primary": "some-model", "fallback": "other-model"}

        plan = parse(mutate(edit))
        assert graph_module.preflight(plan)["ready_to_dispatch"] is True

        def unapproved(meta):
            meta["approved"] = False
            for unit in meta["units"]:
                unit["route"] = {"primary": "some-model", "fallback": "other-model"}

        flight = graph_module.preflight(parse(mutate(unapproved)))
        assert flight["ready_to_dispatch"] is False
        assert any("not approved" in warning for warning in flight["warnings"])
