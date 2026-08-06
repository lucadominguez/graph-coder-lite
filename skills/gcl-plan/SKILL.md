---
name: gcl-plan
description: Author the one Graph Coder Lite plan file, with units complete enough that a fresh cheap agent can execute each one from its packet alone.
---
# GCL Plan

Bounded authority: author and mutate the plan. The Director decides when it is
ready, gets approval, and starts execution. This skill never spawns workers and
never writes application code.

There is exactly one plan file. Never create a competing plan, a summary plan, or
a parallel contract document. Never shorten it for presentation: if it is long,
it is long.

The plan file is also the graph. Units declare their own dependencies, manager,
scopes, and route, so nothing is compiled into a second artifact that can drift.

## Structure

YAML frontmatter carries the machine-checked contract: `bounds`, `budget`,
`requirements`, `acceptance`, `managers`, and `units`. The body carries six
sections, in order:

```text
1. Goal and Requirements     what and why, plus explicit non-goals
2. Grounding                 repository facts, with the baseline failure set
3. Decisions and Evidence    each decision, its reason, and its source
4. Units                     how the units divide the work and why
5. Verification and Done     what makes the whole change finished
6. Risks and Recovery        what fails, what it blocks, what keeps running
```

The plan `gcl init` writes is a complete working example that passes
`gcl check`. Start from it rather than from a blank file.

Refinement is monotonic in substance. Later work adds specificity, evidence,
constraints, and tests. Deleting or weakening an acceptance criterion, a scope, or
a unit needs a recorded reason and voids approval. Rewording does not.

## The budget is a circuit breaker, not an intention

Every plan declares one. `gcl check` refuses a plan without it, because a run
with no budget cannot be stopped when it starts costing more than the work is
worth.

```yaml
budget:
  frontier_tokens: 250000        # what the Director may spend planning and directing
  worker_tokens: 1500000         # what all workers together may spend implementing
  control_plane_share_max: 0.35  # the largest share of the run overhead may be
  protected:
    provider: anthropic          # budgeted in its own tokens, never traded for price
    tokens: 300000               # 0 bars the provider from this run entirely
    models: [in-house-7b]        # optional, for families the built-in list misses
```

A run once spent about a fifth of a weekly frontier allowance producing a
browser-local notes app. The code was fine. What failed is that the design goal,
spend premium reasoning once and let cheap models execute, was written as
guidance, and nothing recorded what was being spent, so nothing could notice.

Two things follow, and both are why the numbers above are shaped the way they
are.

- **Dollars are not the scarce resource.** A subscription route has no marginal
  dollar price, which is exactly why a router scoring dollars spends it freely.
  A weekly quota is finite and running out costs the user their week, not a few
  cents. Name that provider under `protected` and give it its own allowance.
  `gcl route set` then refuses to put it on a worker route, because workers are
  the many and the many are what exhaust an allowance. It matches the provider's
  model families, not just its name: a route says `claude-sonnet-5`, never
  `anthropic`. Name anything it would miss under `protected.models`.
- **The control plane is overhead, not work.** Directing, reviewing, and
  monitoring produce no artifact. `control_plane_share_max` is the point past
  which the run has stopped being worth its own supervision.

Size the numbers against this change, not against a round figure: estimate from
the unit count, the size of each unit's read scope, and the routes. Say in
section 5 or 6 what the estimate rests on, so the user is approving a number
with a basis. Every breach stops dispatch, so a budget set carelessly low is a
run that halts, and one set carelessly high is no budget at all.

## The unit contract

Nineteen fields. A unit missing any of them is not ready, and `gcl check` says so.

```yaml
unit_id: IU-STORE
title: string
objective: one measurable outcome
kind: explore | implement | verify | integrate | repair | release
dependencies: [IU-id]
acceptance_ids: [AC-id]
read_scope: [path]           # the worker may read nothing else
write_scope: [path]          # the worker may write nothing else
forbidden_scope: [path]      # not merely unwritable: not to be looked at
procedure: [step]
commands:
  red: [command that fails before the work]
  green: [command that passes after it]
expected_artifacts: [path]
output_contract: [checkable assertion about the artifact's contents]
progress_contract:
  checkpoint_every: string
  writes_incrementally: bool
  command_timeout_seconds: int
manager_id: M-id
risk: low | medium | high | critical
route:
  primary: model
  fallback: model
attempt_limit: int
stop_conditions: [condition]
```

Write every unit so a weaker fresh executor can complete it with no chat history.
That is the whole point: detailed contracts are what make cheap workers viable.

`kind` has no `review` member. A review is a manager's verdict and an artifact,
never a unit. `verify` is legitimate only when the agent performs a concrete
validation action, such as running compatibility tests or inspecting a generated
artifact; it is not the reviewer role returning under a different label.

### The output contract is a gate, not a description

`expected_artifacts` names the file. `output_contract` says what has to be inside
it, as assertions someone else can check without trusting the worker.

A unit that says "scrape the listings and submit a report" is satisfied by a
scraper that returns nothing: the code ran, the file exists, and no criterion
described the contents. State the fields that must be present, that the result
must be non-empty, and the bounds a plausible result falls within.

```yaml
output_contract:
  - Every record carries title, price, and url, all non-empty.
  - At least 20 records and no more than 200 from one catalogue page.
  - No two records share a url.
```

Prefer an assertion a command can decide.

### The progress contract is what makes a stall detectable

A worker's transcript cannot be read while it runs, so the plan has to say in
advance what progress will look like on disk. Without it, an agent 900 items into
a long job and an agent wedged in a dead loop are the same observation: nothing
new written.

- `checkpoint_every` names the cadence in the unit's own terms: "each detail
  page", "every 25 records", "single pass". The Director's stall math reads this,
  so silence from a single-pass unit is expected and silence from a per-page unit
  is a stall.
- `writes_incrementally` decides whether output accumulates on disk or lands once
  at the end. Anything long or iterative writes as it goes, so a death at item 900
  does not lose 900 items.
- `command_timeout_seconds` bounds any single command. A worker inside a long
  blocking call cannot answer a message, cannot report to its manager, and cannot
  be told apart from a hung one, so the whole review pattern quietly stops
  working. Bound the command instead of hoping it returns.

Long work gets batches with a checkpoint between them, never one command that
either finishes or does not.

## Splitting units

Split where a unit can be independently owned and verified. Avoid both oversized
units carrying hidden context and coordination-heavy oversplitting.

Two units that can run at the same time must not write the same file. `gcl check`
computes this from the dependency graph and refuses the plan otherwise, including
nested-directory and case-insensitive overlap, because on Windows `SRC/Store.py`
and `src/store.py` are one file.

## Managers

One manager per meaningful branch or failure domain, never one per worker. A
manager owns a coherent subtree whose shared context fits inside its limits. If a
manager's branch needs context it cannot hold, the branch is drawn wrong.

Every unit names a `manager_id`. That manager owns its review. Never specify a
reviewer agent, a review unit, or a second-opinion pass.

## Before declaring the plan ready

`gcl check` enforces the mechanical part. You own the rest:

- every requirement maps to at least one unit, and every unit to at least one
  requirement;
- every acceptance criterion is observable by a command or an inspectable
  artifact;
- every command is runnable on the target platform as written;
- every load-bearing claim cites a file, symbol, command result, or dated source;
- every risk has a mitigation or an explicit acceptance;
- the baseline failure set is recorded, so new failures are distinguishable;
- the budget is sized against this change, and what it rests on is written down.

Unknowns become bounded `explore` units or questions for the user. Never invent a
file, an API, or a test result. Never assert a command passes without its output.

## Stop and escalate on

Product ambiguity only the user can settle; an undocumented external API; a
destructive migration without authorization; unbounded scope; acceptance that
cannot be verified; a unit that cannot be independently owned and verified; or a
unit that would need write access outside its scope to succeed.
