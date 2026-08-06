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

YAML frontmatter carries the machine-checked contract: `bounds`, `requirements`,
`acceptance`, `managers`, and `units`. The body carries six sections, in order:

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
- the baseline failure set is recorded, so new failures are distinguishable.

Unknowns become bounded `explore` units or questions for the user. Never invent a
file, an API, or a test result. Never assert a command passes without its output.

## Stop and escalate on

Product ambiguity only the user can settle; an undocumented external API; a
destructive migration without authorization; unbounded scope; acceptance that
cannot be verified; a unit that cannot be independently owned and verified; or a
unit that would need write access outside its scope to succeed.
