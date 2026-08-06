# Graph Coder Lite

Plan once with real effort. Dispatch the work to cheap parallel subagents with
exact contracts. Review each result once. Ship.

This is [Graph Coder](https://github.com/lucadominguez/graph-coder) with the
ceremony removed. Ten phases became four, eight skills became three, and the
plan, the graph, the routes, and the ledger became one file. What survived is
the part that was paid for in failed runs.

```text
1. GROUND     mode, repository facts, and what the user actually wants
2. PLAN       one plan file: decisions, units, managers, routes
3. APPROVE    render it in full, bind approval to the unit contracts
4. EXECUTE    dispatch, review, escalate, finish
```

## Quickstart

```sh
pip install -e ".[dev]"
gcl init                                  # writes PLAN.md
gcl check                                 # every defect in one pass
gcl route set --model <model> --fallback <model>
gcl approve --rendered                    # after showing the user the whole plan
gcl emit                                  # packets for the ready units
```

Then install the skills into your harness and run `/graph-coder-lite`.

```powershell
powershell -File scripts/install.ps1 -Dest "$env:USERPROFILE\.jcode\skills"
```

```sh
./scripts/install.sh --dest ~/.jcode/skills
```

## What it does

**The plan file is the graph.** Units declare their own dependencies, manager,
scopes, and route. There is no second artifact to compile, so nothing can drift
away from the plan the user approved.

**`gcl check` refuses what prose cannot.** A unit missing a contract field. A
dependency that names nothing. An acceptance criterion no unit satisfies. Two
units that can run at the same time and write the same file, including through a
parent directory and including `SRC/Store.py` versus `src/store.py`, which are
one file on Windows. A path in both read scope and forbidden scope.

**`gcl emit` builds the packet.** Objective, scopes as hard bounds, procedure,
acceptance with descriptions, the output contract, red and green commands, the
progress protocol, stop conditions, and a report template. Send it verbatim.

**One review, and it is the only gate.** A worker submits a report; its manager
checks the artifact's contents against the output contract. `completed` exists
only through `gcl review`, which refuses a pass with no evidence, a repair with
no defect and instruction, and an escalation with no question or account of what
was already tried. So every completion carries the evidence that justified it,
by construction rather than by convention.

**The preflight will not let you dispatch the wrong run.** It blocks on a
placeholder route, which means the workers would run on whatever default the
harness supplies, and on a plan that was never approved.

**The budget is a circuit breaker, not an intention.** Every plan declares one,
every model turn is recorded against it, and a breach makes `gcl emit` emit
nothing rather than warn. See below.

## The budget

A run once spent about a fifth of a weekly frontier allowance producing a
browser-local notes app. The code was fine. What failed is that the design goal,
spend premium reasoning once and let cheap models execute, was written as
guidance, and nothing recorded what was being spent, so nothing could notice.

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

**Dollars are not the scarce resource.** A subscription route has no marginal
dollar price, which is exactly why a router that scores dollars spends it
freely. A weekly quota is finite, and running out of it costs the user their
week rather than a few cents. The protected provider is budgeted in its own
units, and `gcl route set` refuses to put it on a worker route without
`--allow-protected`: workers are the many, and the many exhaust an allowance. It
matches the provider's model families rather than its name, because a route says
`claude-sonnet-5` and never says `anthropic`.

**The control plane is overhead, not work.** Directing, reviewing, and
monitoring produce no artifact. When they pass `control_plane_share_max` of
everything spent, the run has stopped being worth its own supervision.

```sh
gcl usage record --role worker --provider openai --model gpt-x \
                 --input 12000 --output 3000 --unit IU-STORE
gcl usage status          # spend by role, provider, and unit, against the caps
```

Every breach is a hard stop, because a warning is what the run that motivated
this already had.

## The unit contract

Nineteen fields, all load-bearing. Three of them are the ones people skip:

```yaml
output_contract:      # what is inside the artifact, not that it exists
  - Every record carries title, price, and url, all non-empty.
  - At least 20 records and no more than 200 from one catalogue page.
progress_contract:
  checkpoint_every: each detail page       # so silence can be read correctly
  writes_incrementally: true               # so a death at item 900 loses nothing
  command_timeout_seconds: 300             # so a blocked worker is not a hung one
```

A unit that says "scrape the listings and submit a report" is satisfied by a
scraper that returns nothing: the code ran, the file exists, and no criterion
described the contents. And because a running worker's transcript cannot be read,
an agent 900 items in and an agent wedged in a dead loop produce the same
observation unless the plan said in advance what progress would look like.

`src/gcl/templates/example-plan.md` is a complete plan that passes `gcl check`.

## Commands

```text
gcl init                                  write a starting plan
gcl check                                 every defect in the plan, in one pass
gcl status                                states, frontier, what blocks what
gcl emit [--unit ID]                      packets for the ready units + preflight
gcl set <unit> <state> [--note ...]       record a transition, never a verdict
gcl verify <unit>                         gather the evidence a review rests on
gcl review <unit> --verdict <v> ...       the only path to completed
gcl route set --model M [--fallback F] [--unit ID] [--evidence E]
gcl usage record --role R --provider P --model M --input N --output N [--unit ID]
gcl usage status                          spend against the budget, and whether to stop
gcl approve --rendered                    bind approval to the unit contracts
gcl recover [--apply]                     reconcile after an interrupted session
```

## What was removed, and why it was safe

| Removed | Why |
| --- | --- |
| Cold rehearsal, and the double pass for high-risk units | A whole phase of agents reading packets to predict problems. The manager review catches the same defects against real artifacts. |
| Separate concept and research phases | Both were question-asking with heavy schemas around them. Folded into GROUND and PLAN as bounded steps. |
| The compiled graph artifact | Derived from the units instead, so it cannot drift. |
| The benchmark-scoring router | What mattered in real runs was refusing to dispatch an unrouted node, not the scoring math. That check stayed, and cost control moved to the budget, which measures what was actually spent instead of predicting it. |
| The SQLite ledger | One JSON state file rebuilds the frontier after a reload, and `gcl recover` reopens anything that cannot be shown to have finished. |

What stayed: the three-role authority model, the single manager review gate, the
full dispatch mechanics, the output and progress contracts, the bounded
escalation ladder, write-scope disjointness, and evidence-based completion.

## Development

```sh
pip install -e ".[dev]"
python -m pytest -q
python -m ruff check src tests
```

MIT licensed. See `NOTICE` for provenance.
