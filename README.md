<p align="center">
  <img src="https://raw.githubusercontent.com/lucadominguez/graph-coder/main/assets/banner-lite.png" alt="Graph Coder Lite" width="900">
</p>

# Graph Coder Lite

Lite is the [Graph Coder](https://github.com/lucadominguez/graph-coder) method
with a smaller toolset: four phases, three skills, and one plan file. A Director
plans the work, workers implement bounded units, and managers review the results.
The `gcl` CLI checks the plan and keeps the run's state in JSON.

```text
1. GROUND     establish the repository facts and what the user wants
2. PLAN       write decisions, units, managers and routes in PLAN.md
3. APPROVE    show the full plan and record approval of its contracts
4. EXECUTE    dispatch units, review results and handle blocked work
```

Use Lite if you want mechanical checks without Full's compiled graph, routing
pipeline and SQLite ledger. Use [Nano](https://github.com/lucadominguez/graph-coder-nano)
if you want only the skill instructions and can supervise the checks yourself.

## Install and try it

You need Git and Python 3.11 or later. On Linux or macOS:

```sh
git clone https://github.com/lucadominguez/graph-coder-lite.git
cd graph-coder-lite
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
gcl init
gcl check
```

This creates and checks an example `PLAN.md`; it does not start any agents.
Replace the example with a plan for your own project before using it for work.

Install the skills into your harness. For JCode:

```sh
bash scripts/install.sh --dest ~/.jcode/skills
```

On Windows, open PowerShell in the cloned repository:

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\gcl --help
powershell -File scripts/install.ps1 -Dest "$env:USERPROFILE\.jcode\skills"
```

Activate the environment or use the executable's full path when running `gcl`.
Start a new harness session if it loads skills only at startup, then ask it to
use `/graph-coder-lite`.

Before dispatch, set actual worker and fallback model IDs accepted by your
harness. The values below are placeholders to replace, not recommended routes:

```sh
gcl route set --model 'your-worker-model' --fallback 'your-fallback-model'
gcl check
# Show the entire plan to the user and obtain approval before this command.
gcl approve --rendered
gcl emit
# Inspect the JSON: dispatch only when preflight.ready_to_dispatch is true.
```

`gcl emit` produces packets, not running agents. The Director sends those packets
to the harness and records the resulting work and reviews.

## What the CLI checks

**The plan is the graph.** Units declare their dependencies, manager, scopes and
route in one file. There is no separate compiled graph to keep in sync. JSON
state records execution; it does not replace the approved plan.

`gcl check` reports missing contract fields, unknown dependencies and uncovered
acceptance criteria. It also checks for concurrent write-scope collisions,
including parent-directory overlaps and case-insensitive path matches, and for
paths that appear in both read and forbidden scope.

`gcl emit` builds a packet with the objective, file boundaries, procedure,
acceptance criteria, output contract, validation commands, progress expectations,
stop conditions and report template. The Director should send it unchanged.
Its preflight flags unapproved plans and placeholder routes. **The Director must
stop unless `preflight.ready_to_dispatch` is `true`.** `gcl emit` can return
`ok: true` and preview packets even when that flag is false; neither a zero exit
code nor the presence of packets authorizes dispatch. Budget breaches, by contrast,
stop packet emission.

A worker's report is not a completion verdict. Its manager checks the artifacts
and records the outcome through `gcl review`, the only CLI path to `completed`.
The command requires evidence for a pass, a defect and instruction for repair,
and a question plus an account of previous attempts for escalation. These checks
require a structured record; they cannot establish that an agent's evidence is
truthful. The manager still has to inspect the work.

## Budgets and usage

A plan declares spending limits. Record model turns with `gcl usage record`;
`gcl usage status` reports the totals, and budget breaches block `gcl emit`.
The CLI does not automatically collect usage from your model provider or harness.
Missing usage records mean the budget checks have an incomplete picture.

For example:

```yaml
budget:
  frontier_tokens: 250000        # Director planning and direction
  worker_tokens: 1500000         # all workers combined
  control_plane_share_max: 0.35  # maximum share spent on supervision
  protected:
    provider: anthropic          # a separately protected token allowance
    tokens: 300000               # 0 bars the provider from the run
    models: [in-house-7b]        # optional additional model families to protect
```

These numbers illustrate the format; they are not measured requirements or
expected savings. Choose limits that fit your project and account.

A subscription can have no per-request price and still have a limited quota.
The protected-provider setting accounts for that separately. `gcl route set`
requires `--allow-protected` to put a protected model on a worker route. Built-in
model-family matching identifies common provider models; use `protected.models`
for additional names it does not recognize.

The control-plane limit counts supervision as overhead. It can stop a run whose
planning, direction and review are consuming too much of its recorded usage.

```sh
gcl usage record --role worker --provider openai --model gpt-x \
                 --input 12000 --output 3000 --unit IU-STORE
gcl usage status
```

Use the actual provider, model, unit and token counts from your run. A budget
breach prevents new packet emission; it does not cancel requests already running
in an external harness.

## Writing a useful unit contract

A unit needs more than a file path and a request to implement something. Two
fields deserve particular attention:

```yaml
output_contract:
  - Every record carries title, price, and url, all non-empty.
  - At least 20 records and no more than 200 from one catalogue page.
progress_contract:
  checkpoint_every: each detail page
  writes_incrementally: true
  command_timeout_seconds: 300
```

The output contract describes the contents, not just the existence of a file.
Otherwise, a scraper that produces an empty file can satisfy the literal task
while being useless to the user.

The progress contract helps distinguish work from a stall. Use status and
transcripts where the harness exposes them, together with checkpoints and file
changes. Save batches as they finish so an interruption does not lose the whole
result. Command timeouts also make blocked work easier to diagnose.

[`example-plan.md`](src/gcl/templates/example-plan.md) contains a complete unit
and passes `gcl check`.

## Commands

```text
gcl init                                  write a starting plan
gcl check                                 report defects in the plan
gcl status                                show states, ready units and blockers
gcl emit [--unit ID]                       emit packets after preflight
gcl set <unit> <state> [--note ...]         record a transition, never a verdict
gcl verify <unit>                          gather evidence for a review
gcl review <unit> --verdict <v> ...         record pass, repair or escalation
gcl route set --model M [--fallback F] [--unit ID] [--evidence E]
gcl usage record --role R --provider P --model M --input N --output N [--unit ID]
gcl usage status                          compare recorded spend with the budget
gcl approve --rendered                     bind approval to the unit contracts
gcl recover [--apply]                      reconcile an interrupted session
```

## Differences from Full

| Change | Trade-off |
| --- | --- |
| No cold-rehearsal phase | Less work before dispatch, but packet defects may be found later during implementation or review. |
| Concept and research work folded into GROUND and PLAN | Fewer handoffs; the Director must still resolve consequential questions before dispatch. |
| No compiled graph artifact | Dependencies come from the plan, with fewer separate files to reconcile. |
| Explicit model routes instead of benchmark scoring | You choose the models. Preflight checks the routes and budget, not their suitability for the task. |
| JSON state instead of a SQLite ledger | Simpler local storage. `gcl recover` helps reconcile work after an interruption. |

Lite keeps the Director/Manager/Worker boundaries, manager review, output and
progress contracts, bounded escalation, and checks for concurrent write-scope
overlap. Removing rehearsal is a trade-off, not evidence that review catches
every defect rehearsal would have found. Live agent adherence and end-to-end
cost savings have not been evaluated.

## Development

```sh
python -m pip install -e ".[dev]"
python -m pytest -q
python -m ruff check src tests
```

MIT licensed. See [NOTICE](NOTICE) for provenance.
