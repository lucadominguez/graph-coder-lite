"""The readiness gate. Every check here refuses something a real run shipped."""

from __future__ import annotations

import pytest

from gcl import plan as plan_module
from gcl.errors import PlanError


def defects(text: str) -> list[str]:
    return plan_module.readiness_defects(plan_module.parse(text))


def test_the_example_plan_is_ready(example_text):
    assert defects(example_text) == []


def test_a_plan_without_frontmatter_says_what_is_missing():
    with pytest.raises(PlanError, match="frontmatter"):
        plan_module.parse("# just a heading\n")


def test_a_scalar_where_a_list_belongs_is_rejected(mutate, unit_of):
    text = mutate(lambda meta: unit_of(meta, "IU-STORE").update(read_scope="src/store/tokens.py"))
    with pytest.raises(PlanError, match="must be a list"):
        plan_module.parse(text)


def test_a_unit_with_no_manager_cannot_pass(mutate, unit_of):
    # The original wrote this check as `(unit.manager_id,)`. A one-tuple is
    # always truthy, so it could not fail, and a unit reached execution with
    # nobody assigned to review it.
    text = mutate(lambda meta: unit_of(meta, "IU-STORE").update(manager_id=""))
    assert any("no manager_id" in defect for defect in defects(text))


def test_a_unit_naming_an_undeclared_manager_is_caught(mutate, unit_of):
    text = mutate(lambda meta: unit_of(meta, "IU-STORE").update(manager_id="M-GHOST"))
    assert any("undeclared manager M-GHOST" in defect for defect in defects(text))


def test_a_missing_output_contract_is_a_defect(mutate, unit_of):
    text = mutate(lambda meta: unit_of(meta, "IU-STORE").update(output_contract=[]))
    assert any("missing output contract" in defect for defect in defects(text))


@pytest.mark.parametrize(
    "key", ["checkpoint_every", "writes_incrementally", "command_timeout_seconds"]
)
def test_every_progress_contract_field_is_required(mutate, unit_of, key):
    def edit(meta):
        unit_of(meta, "IU-STORE")["progress_contract"].pop(key)

    assert any(f"progress contract is missing {key}" in d for d in defects(mutate(edit)))


@pytest.mark.parametrize("value", [0, -5, "120"])
def test_a_command_timeout_must_be_a_positive_integer(mutate, unit_of, value):
    def edit(meta):
        unit_of(meta, "IU-STORE")["progress_contract"]["command_timeout_seconds"] = value

    assert any("command_timeout_seconds must be" in d for d in defects(mutate(edit)))


def test_a_boolean_timeout_is_not_an_integer(mutate, unit_of):
    # True is an int in Python. Without the bool guard, `command_timeout_seconds:
    # true` would pass as a positive integer and bound nothing.
    def edit(meta):
        unit_of(meta, "IU-STORE")["progress_contract"]["command_timeout_seconds"] = True

    assert any("command_timeout_seconds must be an integer" in d for d in defects(mutate(edit)))


def test_a_unit_with_no_green_command_proves_nothing(mutate, unit_of):
    text = mutate(lambda meta: unit_of(meta, "IU-STORE")["commands"].update(green=[]))
    assert any("no green command" in defect for defect in defects(text))


def test_review_is_not_an_allowed_kind(mutate, unit_of):
    # A review is a manager's verdict, never a node. A `review` kind would need a
    # reviewer agent, which is the role this design removes.
    text = mutate(lambda meta: unit_of(meta, "IU-STORE").update(kind="review"))
    assert any("kind `review`" in defect for defect in defects(text))


def test_an_unknown_dependency_is_caught(mutate, unit_of):
    text = mutate(lambda meta: unit_of(meta, "IU-STORE").update(dependencies=["IU-GHOST"]))
    assert any("unknown units: ['IU-GHOST']" in defect for defect in defects(text))


def test_a_self_dependency_is_caught(mutate, unit_of):
    text = mutate(lambda meta: unit_of(meta, "IU-STORE").update(dependencies=["IU-STORE"]))
    assert any("depends on itself" in defect for defect in defects(text))


def test_an_acceptance_criterion_with_no_unit_is_caught(mutate):
    def edit(meta):
        meta["acceptance"].append({"id": "AC-ORPHAN", "description": "nothing satisfies this"})

    assert any("no unit that satisfies" in d for d in defects(mutate(edit)))


def test_a_path_in_both_write_and_forbidden_scope_is_incoherent(mutate, unit_of):
    text = mutate(
        lambda meta: unit_of(meta, "IU-STORE").update(forbidden_scope=["src/store/tokens.py"])
    )
    assert any("write_scope and forbidden_scope" in defect for defect in defects(text))


def test_a_path_in_both_read_and_forbidden_scope_is_incoherent(mutate, unit_of):
    text = mutate(lambda meta: unit_of(meta, "IU-STORE").update(forbidden_scope=["src/store/"]))
    assert any("read_scope and forbidden_scope" in defect for defect in defects(text))


def test_a_draft_plan_is_not_ready(mutate):
    text = mutate(lambda meta: meta.update(readiness="draft"))
    assert any("not `ready`" in defect for defect in defects(text))


def test_bounds_must_be_explicit(mutate):
    text = mutate(lambda meta: meta["bounds"].pop("cost_ceiling"))
    assert any("cost_ceiling" in defect for defect in defects(text))


def test_a_missing_body_section_is_a_defect(example_text):
    truncated = example_text.replace("## 6. Risks and Recovery", "## Risks and Recovery")
    assert any("missing sections" in defect for defect in defects(truncated))


class TestScopeComparison:
    @pytest.mark.parametrize(
        ("left", "right"),
        [
            ("src/store.py", "src/store.py"),
            ("src/", "src/store.py"),
            ("src/*", "src/store.py"),
            ("src/store.py", "SRC/Store.py"),  # one file on Windows
            ("src\\store.py", "src/store.py"),
            ("./src/store.py", "src/store.py"),
        ],
    )
    def test_these_name_the_same_file(self, left, right):
        assert plan_module.scopes_overlap(left, right)

    @pytest.mark.parametrize(
        ("left", "right"),
        [
            ("src/store.py", "src/store_v2.py"),  # prefix, but not a parent
            ("src/store", "src/storefront/a.py"),
            ("src/a.py", "tests/a.py"),
            ("", "src/a.py"),
        ],
    )
    def test_these_do_not(self, left, right):
        assert not plan_module.scopes_overlap(left, right)


def test_approval_hash_ignores_prose_but_not_contracts(example_text, mutate, unit_of):
    original = plan_module.approval_hash(plan_module.parse(example_text))
    reworded = example_text.replace(
        "Operators can currently issue API tokens", "Operators can issue API tokens today"
    )
    assert plan_module.approval_hash(plan_module.parse(reworded)) == original

    rescoped = mutate(lambda meta: unit_of(meta, "IU-STORE")["write_scope"].append("src/api/x.py"))
    assert plan_module.approval_hash(plan_module.parse(rescoped)) != original
