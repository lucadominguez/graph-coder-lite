"""The resource budget, as an invariant rather than an intention.

A run once spent about a fifth of a weekly frontier-model allowance producing a
browser-local notes app. Nothing was wrong with the code it produced. What went
wrong is that the design goal, spend premium reasoning once and let cheap models
execute, was written as guidance and never enforced, and nothing recorded what
was actually being spent, so nothing could notice.

Two ideas do the work here.

**Dollars are not the scarce resource.** A subscription route has no marginal
dollar price, which is exactly why a router that scores dollars will spend it
freely. Weekly quota is finite, and running out of it costs the user their whole
week rather than a few cents. A protected provider is therefore budgeted in its
own units and never traded against price.

**Control plane is overhead, not work.** Directing, reviewing, and monitoring
produce no artifact. When they cost more than the implementation they are
supervising, the run has stopped being worth its own supervision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: Roles whose spend supervises work rather than producing it.
CONTROL_ROLES = frozenset({"director", "manager"})
ROLES = frozenset({"director", "manager", "worker"})

REQUIRED_KEYS = ("frontier_tokens", "worker_tokens", "control_plane_share_max")

#: How each provider's models are named when the provider is not. A route almost
#: never says `anthropic`; it says `claude-sonnet-5`. Matching the provider's own
#: name alone reads as a working guard and stops nothing, which is how the first
#: version of this check passed its tests and let the protected model through.
PROVIDER_ALIASES: dict[str, tuple[str, ...]] = {
    "anthropic": ("claude", "opus", "sonnet", "haiku"),
    "openai": ("gpt", "chatgpt", "codex", "o1", "o3", "o4"),
    "google": ("gemini", "gemma"),
    "meta": ("llama",),
    "mistral": ("mistral", "mixtral", "codestral"),
    "deepseek": ("deepseek",),
    "xai": ("grok",),
    "qwen": ("qwen",),
    "cohere": ("command",),
}


@dataclass(frozen=True)
class Usage:
    """What one model turn actually cost."""

    role: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    unit: str = ""

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "provider": self.provider,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "unit": self.unit,
        }


@dataclass
class Ledger:
    """Observed spend, totalled the ways a decision actually needs it."""

    by_role: dict[str, int] = field(default_factory=dict)
    by_provider: dict[str, int] = field(default_factory=dict)
    by_unit: dict[str, int] = field(default_factory=dict)
    total: int = 0

    @classmethod
    def from_events(cls, events: list[dict[str, Any]]) -> Ledger:
        ledger = cls()
        for raw in events:
            tokens = int(raw.get("input_tokens", 0)) + int(raw.get("output_tokens", 0))
            role = str(raw.get("role", "worker"))
            provider = str(raw.get("provider", "unknown"))
            ledger.by_role[role] = ledger.by_role.get(role, 0) + tokens
            ledger.by_provider[provider] = ledger.by_provider.get(provider, 0) + tokens
            if raw.get("unit"):
                unit = str(raw["unit"])
                ledger.by_unit[unit] = ledger.by_unit.get(unit, 0) + tokens
            ledger.total += tokens
        return ledger

    @property
    def control_plane(self) -> int:
        return sum(tokens for role, tokens in self.by_role.items() if role in CONTROL_ROLES)

    @property
    def worker(self) -> int:
        return self.by_role.get("worker", 0)

    @property
    def control_plane_share(self) -> float:
        """Overhead as a fraction of everything spent.

        Undefined rather than zero before anything is spent: a run that has not
        started is not efficient, it is empty.
        """

        return self.control_plane / self.total if self.total else 0.0


def defects(budget: dict[str, Any]) -> list[str]:
    """Reasons a budget cannot be enforced as written."""

    problems: list[str] = []
    if not budget:
        problems.append(
            "plan declares no `budget`. A run with no budget cannot be stopped when it "
            "starts costing more than the work is worth."
        )
        return problems

    for key in REQUIRED_KEYS:
        value = budget.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            problems.append(f"budget.{key} must be a positive number")

    share = budget.get("control_plane_share_max")
    if isinstance(share, (int, float)) and not isinstance(share, bool) and not 0 < share <= 1:
        problems.append(
            "budget.control_plane_share_max is a fraction between 0 and 1, such as 0.25 "
            "for a quarter of the run's tokens"
        )

    protected = budget.get("protected")
    if protected is not None:
        if not isinstance(protected, dict):
            problems.append("budget.protected must be a mapping with `provider` and `tokens`")
        else:
            if not protected.get("provider"):
                problems.append("budget.protected needs a `provider` to protect")
            tokens = protected.get("tokens")
            if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 0:
                problems.append(
                    "budget.protected.tokens must be a non-negative integer. Zero is "
                    "meaningful: it bars the provider from this run entirely."
                )
            models = protected.get("models")
            if models is not None and (
                not isinstance(models, list) or not all(isinstance(name, str) for name in models)
            ):
                problems.append(
                    "budget.protected.models is a list of model strings that spend this "
                    "provider's allowance, for families the built-in list does not know"
                )
    return problems


def protected_provider(budget: dict[str, Any]) -> str:
    protected = budget.get("protected") or {}
    return str(protected.get("provider", "")).strip().lower()


def protected_allowance(budget: dict[str, Any]) -> int:
    protected = budget.get("protected") or {}
    return int(protected.get("tokens", 0))


def _tokens(route: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", route.strip().lower()) if token}


def names_protected(route: str, budget: dict[str, Any]) -> bool:
    """Would this route spend the protected provider's allowance?

    A heuristic, and deliberately one that errs toward refusing: the provider's
    own name, its known model families, and any model string the plan names
    under `protected.models`. `--allow-protected` is the way past it, so a false
    positive costs one flag and a false negative costs the allowance.
    """

    provider = protected_provider(budget)
    if not provider or not route:
        return False
    protected = budget.get("protected") or {}
    declared = {str(name).strip().lower() for name in protected.get("models") or []}
    needles = {provider, *PROVIDER_ALIASES.get(provider, ()), *declared}
    candidate = route.strip().lower()
    if candidate in declared:
        return True
    tokens = _tokens(candidate)
    if tokens & needles:
        return True
    # `gpt4` and `claude3` do not tokenize to a bare family name.
    return any(token.startswith(needle) for token in tokens for needle in needles)


def assess(budget: dict[str, Any], ledger: Ledger) -> dict[str, Any]:
    """Compare observed spend against the budget, and say whether to stop.

    Every breach here is a hard stop rather than a warning. A warning is what the
    postmortem run had, and it kept going.
    """

    breaches: list[str] = []
    frontier_cap = float(budget.get("frontier_tokens", 0) or 0)
    worker_cap = float(budget.get("worker_tokens", 0) or 0)
    share_cap = float(budget.get("control_plane_share_max", 1) or 1)

    frontier = ledger.by_role.get("director", 0)
    if frontier_cap and frontier > frontier_cap:
        breaches.append(
            f"the Director has spent {frontier:,} tokens against a budget of "
            f"{int(frontier_cap):,}. Planning is done; further frontier turns are the "
            "cost this design exists to avoid."
        )
    if worker_cap and ledger.worker > worker_cap:
        breaches.append(
            f"workers have spent {ledger.worker:,} tokens against a budget of {int(worker_cap):,}"
        )

    # Only meaningful once real work has happened. Early in a run the Director is
    # the only thing that has spent anything, and a 100% share is expected.
    if ledger.worker and ledger.control_plane_share > share_cap:
        breaches.append(
            f"control plane is {ledger.control_plane_share:.0%} of all tokens spent, over "
            f"the {share_cap:.0%} cap. Directing and reviewing now cost more than the "
            "share of this run they were meant to supervise."
        )

    provider = protected_provider(budget)
    protected_spent = ledger.by_provider.get(provider, 0) if provider else 0
    if provider:
        allowance = protected_allowance(budget)
        if protected_spent > allowance:
            breaches.append(
                f"{provider} is the protected provider and has spent {protected_spent:,} "
                f"tokens against an allowance of {allowance:,}. This is the resource the "
                "run was told not to consume."
            )

    return {
        "stop": bool(breaches),
        "breaches": breaches,
        "spent": {
            "total": ledger.total,
            "by_role": dict(sorted(ledger.by_role.items())),
            "by_provider": dict(sorted(ledger.by_provider.items())),
        },
        "control_plane_share": round(ledger.control_plane_share, 4),
        "control_plane_share_max": share_cap,
        "frontier_remaining": max(int(frontier_cap - frontier), 0) if frontier_cap else None,
        "worker_remaining": max(int(worker_cap - ledger.worker), 0) if worker_cap else None,
        "protected": (
            {
                "provider": provider,
                "spent": protected_spent,
                "allowance": protected_allowance(budget),
                "remaining": max(protected_allowance(budget) - protected_spent, 0),
            }
            if provider
            else None
        ),
    }
