# Changelog

All notable changes to Graph Coder Lite.

## [Unreleased]

### Added

- **A budget that can stop the run.** Every plan now declares `budget`, and
  `gcl check` refuses one that does not: a run with no budget cannot be stopped
  when it starts costing more than the work is worth. `frontier_tokens` caps the
  Director, `worker_tokens` caps the workers together, and
  `control_plane_share_max` caps the share of the run that directing and
  reviewing may take, because a control plane that outgrows the work it
  supervises has stopped paying for itself. A run that spent about a fifth of a
  weekly frontier allowance on a browser-local notes app is what this is for:
  the design goal was written as guidance, so nothing enforced it.
- **A protected provider, budgeted in its own units.** A subscription route has
  no marginal dollar price, which is exactly why a router that scores dollars
  spends it freely, so `budget.protected` names a provider and its allowance,
  and `gcl route set` refuses to put it on a worker route without
  `--allow-protected`. Workers are the many, and the many are what exhaust a
  weekly quota. The refusal matches the provider's model families, not its name:
  the first version compared the string `anthropic` against the route, which
  passed its own tests and let `claude-sonnet-5` straight through. Driving the
  CLI is what caught it. A plan can name families the built-in list misses under
  `budget.protected.models`.
- **`gcl usage record` and `gcl usage status`.** The run that motivated all of
  this could not reconstruct its own spend afterwards, which is why it could not
  stop; a workflow that cannot measure its principal optimization target cannot
  enforce it. Turns are recorded per role, provider, model, and unit, and totted
  up the ways a decision actually needs them.
- **The breaker sits on dispatch.** A breach makes `gcl emit` return no packets
  at all rather than annotate them, and names the three ways out: simplify what
  remains, raise the budget deliberately with the user, or stop and finish by
  hand. Warnings are what the postmortem run already had, and it kept going.

### Fixed

- **A verdict could be recorded without anything justifying it.** The full Graph
  Coder enforced verdict content in `apply_manager_review`; porting the state
  machine alone dropped that, so `gcl set <unit> completed` moved a unit to done
  on nothing, and a `repair_required` could be filed with no defect and no
  instruction, which sends the worker back with nothing to act on. All three
  verdict states are now unreachable from `gcl set`. They exist only through
  `gcl review`, which refuses a pass with no evidence, a repair without both a
  defect and an instruction, and an escalation without the question and what was
  already tried. Every completion therefore carries a review record by
  construction rather than by convention.
- **An escalation could not say what it stopped.** `human_required` now computes
  the transitive dependents that are blocked and the independent units that keep
  running, and reports both, so "this blocks that branch and nothing else" is a
  computed claim rather than an estimate.
- **Nothing reconciled an interrupted session.** `gcl recover` names the two
  things that survive a crash badly: a unit left running whose worker is gone,
  and a unit marked complete by a write that landed while the review justifying
  it did not. `--apply` reopens both as failed attempts, preserving the attempt
  counts. Nothing is ever inferred to have completed.
- **The plan-drift check could not fire.** `gcl recover` compared the stored plan
  hash after `sync` had already overwritten it with the current one, so the two
  values were always equal. Found by the test written for it.

## [0.1.0] - 2026-08-06

First release. A simplification of Graph Coder at commit `43b15b9`, keeping the
rules that were paid for in failed runs and removing the phases that were not.

### The structure

- **Ten phases became four**: GROUND, PLAN, APPROVE, EXECUTE.
- **Eight skills became three**: `graph-coder-lite` (orchestrator, with the
  dispatch reference), `gcl-plan`, `gcl-review`.
- **Sixteen plan sections became six**, and the unit contract went from about
  thirty-five fields to nineteen.
- **Four artifacts became one.** The plan file is the graph. Units declare their
  own dependencies, manager, scopes, and route, so there is no compiled graph to
  drift away from the plan the user approved, and routes are written back into
  the same file.

### Removed

- **Cold rehearsal**, including the two independent passes for high-risk units.
  A whole phase of fresh agents reading packets to predict problems, when the
  manager review finds the same defects against artifacts that actually exist.
- **The separate concept and research phases**, with their third-party workflow
  selection, Product Contract normalization, question-inventory schema, and claim
  schema. Both were question-asking wrapped in ceremony; they are now bounded
  steps inside GROUND and PLAN, keeping the rules that mattered: ask only what
  the user can answer, research only what blocks a decision, pin version-sensitive
  answers to a version or date.
- **The benchmark-scoring router.** What made a real difference was refusing to
  dispatch a node still carrying a placeholder route; the scoring math never
  survived contact with an API that reports no context windows. `gcl route set`
  writes routes explicitly and records where the choice came from. The preflight
  check stayed.
- **The SQLite ledger, the recovery module, and the context-packet builder.**
  One JSON state file rebuilds the frontier after a reload.
- **The author self-audit as a separate pass**, and the Director's second review
  of manager outputs. There is now exactly one review in the system.

### Kept

Every one of these corresponds to a run that failed without it.

- The three-role authority model, and a manager review as the only path to
  `completed`. The state machine has no `running -> completed` transition, so a
  worker cannot complete itself.
- `output_contract`: what has to be inside the artifact. A unit gated only by
  acceptance prose is satisfied by a scraper that returns nothing.
- `progress_contract`: `checkpoint_every`, `writes_incrementally`, and
  `command_timeout_seconds`. A running worker's transcript cannot be read, so
  without a declared cadence a long job and a dead loop look identical, and a
  worker inside an unbounded blocking call cannot report or be told apart from a
  hung one.
- The full dispatch mechanics: narrow swarm cleanup rather than the global
  `--force` that once stopped every agent on the machine, `spawn_mode: visible`,
  the brittleness of the batch `run_plan` path, watching the filesystem and
  worker health together because a rate-limited worker writes nothing exactly
  like a thinking one, the stall table with its bound, and never respawning a
  live worker.
- Write-scope disjointness between units that can run concurrently, computed
  from the dependency graph, including parent-directory and Windows
  case-insensitive overlap.
- The bounded escalation ladder ending in `human_required`, which blocks a unit's
  dependents and nothing else.
- Approval bound to a hash of the unit contracts, so rewording does not void it
  and a scope change does.
- `manager_id` validated as a value, not as `(unit.manager_id,)`. A one-tuple is
  always truthy, which is how a unit once reached execution with nobody assigned
  to review it.

### Added

- `gcl check` reports every defect in one pass rather than failing on the first,
  so a planner fixing one field at a time does not re-run once per problem.
- A read-scope-versus-forbidden-scope check. A packet that both grants and denies
  a path is incoherent, and the worker resolves it by guessing. This caught a
  real contradiction in the shipped example plan on its first run.
- A check that a dependent can read at least one of its dependency's artifacts,
  so an edge that carries nothing is caught at plan time rather than when the
  worker arrives at a repository it cannot see.
- `gcl verify <unit>`, which gathers review evidence without deciding the verdict.
