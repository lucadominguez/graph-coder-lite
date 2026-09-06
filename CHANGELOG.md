# Changelog

All notable changes to Graph Coder Lite.

## [Unreleased]

### Added

- Plans declare `budget`: Director tokens, combined worker tokens, maximum
  supervision share and optional protected-provider quotas. `gcl check` rejects
  a missing budget.
- `gcl usage record` stores usage by role, provider, model and unit;
  `gcl usage status` compares recorded totals with the limits. Usage must be
  supplied by the Director or harness, not automatically collected by the CLI.
- `gcl emit` returns no packets when recorded spending breaches a limit. The user
  can reduce scope, explicitly raise the budget, or stop. It does not cancel
  provider requests already in flight.
- Protected models need `--allow-protected` before assignment to worker routes.
  Matching covers model families as well as provider names;
  `budget.protected.models` adds names the built-in aliases do not recognize.

### Fixed

- Verdict states are reachable only through `gcl review`, not `gcl set`. A pass
  requires evidence, repair requires a defect and instruction, and escalation
  requires a question and previous attempts.
- `human_required` reports blocked transitive dependents and independent units
  that can continue.
- `gcl recover --apply` reopens interrupted work and completions lacking review
  evidence, preserving attempt counts. Plan drift is checked before state sync
  replaces the stored hash.
- Worker packets retain durable progress requirements without claiming live
  transcripts are unavailable in every harness. A regression test checks this.
- Skill checks now protect monitoring and usage requirements rather than
  requiring the wording of historical anecdotes.

### Documentation

- Reworked the introduction, installation steps and unit-contract explanation.
- Made manual usage accounting, structured-review limits and the lack of an
  automatic worker launcher explicit.
- Described removal of rehearsal as a trade-off, not proof that later review
  catches all the same defects. No end-to-end savings benchmark is claimed.

## [0.1.0] - 2026-08-06

First release. A smaller workflow derived from Graph Coder at commit `43b15b9`,
with fewer phases and a JSON state store.

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
  Packet problems may surface later in implementation or manager review; the
  two checks have not been shown to catch identical defects.
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

These operational requirements remain in Lite:

- The three-role authority model, and a manager review as the only path to
  `completed`. The state machine has no `running -> completed` transition, so a
  worker cannot complete itself.
- `output_contract`: what has to be inside the artifact. A unit gated only by
  acceptance prose is satisfied by a scraper that returns nothing.
- `progress_contract`: `checkpoint_every`, `writes_incrementally`, and
  `command_timeout_seconds`. Transcript access depends on the harness. Without
  a declared cadence a long job and a dead loop can look identical on disk, and a
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
