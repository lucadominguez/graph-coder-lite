"""The circuit breaker.

Every assertion here corresponds to a way the run that motivated this module got
past its own cost design: nothing recorded spend, dollars were the only thing
scored, overhead was never compared to the work it supervised, and every signal
that did exist was a warning.
"""

from __future__ import annotations

import pytest

from gcl import budget as budget_module
from gcl import plan as plan_module

SANE = {
    "frontier_tokens": 100,
    "worker_tokens": 1000,
    "control_plane_share_max": 0.3,
}


def ledger(*turns: tuple[str, str, int]) -> budget_module.Ledger:
    """A ledger from (role, provider, tokens) triples, split across in and out."""

    return budget_module.Ledger.from_events(
        [
            {
                "role": role,
                "provider": provider,
                "input_tokens": tokens,
                "output_tokens": 0,
                "unit": "IU-STORE",
            }
            for role, provider, tokens in turns
        ]
    )


class TestABudgetMustBeDeclarable:
    def test_no_budget_at_all_is_a_readiness_defect(self, mutate):
        text = mutate(lambda meta: meta.pop("budget"))
        defects = plan_module.readiness_defects(plan_module.parse(text))
        assert any("declares no `budget`" in defect for defect in defects)

    def test_the_example_plan_declares_one(self, example_text):
        plan = plan_module.parse(example_text)
        assert budget_module.defects(plan.budget) == []
        assert budget_module.protected_provider(plan.budget) == "anthropic"

    @pytest.mark.parametrize("key", budget_module.REQUIRED_KEYS)
    def test_every_cap_must_be_a_positive_number(self, key):
        assert any(key in defect for defect in budget_module.defects({**SANE, key: 0}))

    def test_a_share_is_a_fraction_not_a_percentage(self):
        # `control_plane_share_max: 30` reads as thirty percent and means
        # thirty times the run, which is no cap at all.
        defects = budget_module.defects({**SANE, "control_plane_share_max": 30})
        assert any("fraction between 0 and 1" in defect for defect in defects)

    def test_a_protected_block_needs_a_provider_and_a_token_count(self):
        defects = budget_module.defects({**SANE, "protected": {"tokens": 10}})
        assert any("needs a `provider`" in defect for defect in defects)
        defects = budget_module.defects({**SANE, "protected": {"provider": "anthropic"}})
        assert any("protected.tokens" in defect for defect in defects)

    def test_zero_protected_tokens_is_legal_and_means_barred(self):
        budget = {**SANE, "protected": {"provider": "anthropic", "tokens": 0}}
        assert budget_module.defects(budget) == []
        spend = budget_module.assess(budget, ledger(("worker", "anthropic", 1)))
        assert spend["stop"] is True


class TestBreachesAreStopsNotWarnings:
    def test_within_budget_nothing_stops(self):
        spend = budget_module.assess(SANE, ledger(("director", "openai", 50)))
        assert spend["stop"] is False and spend["breaches"] == []
        assert spend["frontier_remaining"] == 50

    def test_the_director_has_its_own_ceiling(self):
        spend = budget_module.assess(SANE, ledger(("director", "openai", 101)))
        assert spend["stop"] is True
        assert any("Director has spent" in breach for breach in spend["breaches"])
        assert spend["frontier_remaining"] == 0

    def test_workers_have_theirs(self):
        spend = budget_module.assess(SANE, ledger(("worker", "openai", 1001)))
        assert any("workers have spent" in breach for breach in spend["breaches"])

    def test_overhead_larger_than_the_work_it_supervises_stops_the_run(self):
        spend = budget_module.assess(
            SANE,
            ledger(("director", "openai", 40), ("manager", "openai", 40), ("worker", "openai", 20)),
        )
        assert spend["stop"] is True
        assert any("control plane is 80%" in breach for breach in spend["breaches"])

    def test_the_share_is_not_judged_before_any_work_has_happened(self):
        # Early in a run the Director is the only thing that has spent anything,
        # and a 100% control-plane share is what planning looks like.
        spend = budget_module.assess(SANE, ledger(("director", "openai", 40)))
        assert spend["stop"] is False
        assert spend["control_plane_share"] == 1.0

    def test_a_manager_counts_as_overhead_and_a_worker_does_not(self):
        book = ledger(("manager", "openai", 30), ("worker", "openai", 70))
        assert book.control_plane == 30 and book.worker == 70
        assert book.control_plane_share == pytest.approx(0.3)

    def test_every_breach_is_reported_not_only_the_first(self):
        spend = budget_module.assess(
            SANE, ledger(("director", "openai", 500), ("worker", "openai", 2000))
        )
        assert len(spend["breaches"]) == 2


class TestTheProtectedProvider:
    budget = {**SANE, "protected": {"provider": "anthropic", "tokens": 100}}

    def test_it_is_counted_across_every_role_not_only_workers(self):
        spend = budget_module.assess(
            self.budget, ledger(("director", "anthropic", 60), ("manager", "anthropic", 60))
        )
        assert spend["protected"]["spent"] == 120
        assert spend["stop"] is True

    def test_it_is_reported_even_when_nothing_has_touched_it(self):
        spend = budget_module.assess(self.budget, ledger(("worker", "openai", 10)))
        assert spend["protected"] == {
            "provider": "anthropic",
            "spent": 0,
            "allowance": 100,
            "remaining": 100,
        }

    def test_a_run_with_no_protected_provider_reports_none(self):
        assert budget_module.assess(SANE, ledger(("worker", "openai", 10)))["protected"] is None


class TestRecognizingAProtectedRoute:
    """The first version of this matched the provider's own name against the
    model string. A route says `claude-sonnet-5`, never `anthropic`, so the
    check read as a working guard and stopped nothing. It was driven, not
    reasoned about, that caught it."""

    budget = {**SANE, "protected": {"provider": "anthropic", "tokens": 100}}

    @pytest.mark.parametrize(
        "route",
        ["claude-sonnet-5", "claude-opus-4-20250115", "anthropic/claude-haiku", "Claude", "opus"],
    )
    def test_a_real_model_name_is_recognized(self, route):
        assert budget_module.names_protected(route, self.budget) is True

    @pytest.mark.parametrize("route", ["gpt-5", "gemini-2.5-pro", "local", "m1", ""])
    def test_an_unprotected_route_passes(self, route):
        assert budget_module.names_protected(route, self.budget) is False

    def test_a_plan_can_name_a_family_the_built_in_list_does_not_know(self):
        budget = {**SANE, "protected": {"provider": "acme", "tokens": 0, "models": ["wile-e-9"]}}
        assert budget_module.defects(budget) == []
        assert budget_module.names_protected("wile-e-9", budget) is True
        assert budget_module.names_protected("gpt-5", budget) is False

    def test_models_must_be_a_list_of_strings(self):
        budget = {**SANE, "protected": {"provider": "acme", "tokens": 0, "models": "wile-e-9"}}
        assert any("protected.models" in defect for defect in budget_module.defects(budget))

    def test_nothing_is_protected_when_no_provider_is(self):
        assert budget_module.names_protected("claude-sonnet-5", SANE) is False


class TestTheLedger:
    def test_it_totals_the_ways_a_decision_needs(self):
        book = ledger(("worker", "openai", 10), ("worker", "anthropic", 5))
        assert book.total == 15
        assert book.by_provider == {"openai": 10, "anthropic": 5}
        assert book.by_unit == {"IU-STORE": 15}

    def test_input_and_output_are_both_spend(self):
        book = budget_module.Ledger.from_events(
            [{"role": "worker", "provider": "openai", "input_tokens": 7, "output_tokens": 3}]
        )
        assert book.total == 10

    def test_an_empty_run_is_not_efficient_it_is_empty(self):
        assert budget_module.Ledger().control_plane_share == 0.0
