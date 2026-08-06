---
name: graph-coder-lite
description: Use when a software change should be planned once and then implemented by parallel subagents under a single review gate, with bounded scopes, routed models, and durable state.
---
# Graph Coder Lite

Invocation is `/graph-coder-lite`. Run it from the root session, which holds the
Director role for the whole run.

Four phases. Plan once with real effort, dispatch the work to cheap parallel
workers with exact contracts, review each result once, ship.

```text
1. GROUND     mode, repository facts, and what the user actually wants
2. PLAN       one plan file: decisions, units, managers, routes
3. APPROVE    render it in full, bind approval to the unit contracts
4. EXECUTE    dispatch, review, escalate, finish
```

The plan file is the graph. Units declare their own dependencies, manager,
scopes, and route, so there is no second artifact to compile and nothing that can
drift out of sync with the plan the user approved.

## Authority model

Three roles, and the boundaries between them are the product.

| Role | May do | May never do |
| --- | --- | --- |
| Director | Spawn every worker, route, advise, review, record | Edit implementation files during execution; implement a unit instead of spawning it |
| Manager | Advise its children, supply bounded context, review submissions, delegate repair, escalate | Edit files; run a repair itself; mark work complete without evidence |
| Worker | Implement its unit, run its commands, request context, submit a report | Read or write outside its scope; review its own work |

Managers are control-plane agents. A manager review is a state transition and an
artifact, not a task in the graph. There are no reviewer agents and no review
nodes: a worker's own manager owns its review, and that is the only review in the
system.

Advice, context requests, and escalations are events, not dependency edges, so
the graph stays acyclic however much a branch negotiates.

The Director never becomes the implementer of last resort. When a branch cannot
proceed after bounded advice, retry, and fallback, it becomes `human_required`.

## 1. GROUND

Establish the mode first, from durable state rather than memory: **new** (no plan
yet), **resume** (a plan exists, execution partly done, `gcl status` rebuilds the
frontier), or **revise** (the goal changed, so mutate the plan and re-approve).

Then, in one pass:

- Read the code the change will touch: entry points, interfaces, existing tests,
  conventions.
- Run the build, typecheck, lint, and test commands and record the **pre-existing
  failure baseline**. Without it you cannot tell a new failure from an old one.
- Settle what the user alone can decide: intent, scope, non-goals, priorities,
  and anything irreversible. Ask only what the repository cannot answer, and
  inspect before asking.

Record facts apart from assumptions. A fact cites a file, symbol, or command
result. An assumption becomes a bounded `explore` unit or a question for the user.

Answer only the technical questions that block a decision. A question that
changes nothing in the plan is not worth researching. Pin every version-sensitive
answer to a version or a retrieval date, and prefer the primary source over
anything describing it.

## 2. PLAN

Invoke `gcl-plan`. It produces one file with six sections and a set of units that
each carry a complete contract.

The bar is that a fresh agent with no chat history can execute a unit from its
packet alone. That is what makes cheap workers viable, and it is the entire
reason planning gets the expensive model.

Run `gcl check` until it returns no defects. It refuses a plan whose units are
missing contract fields, whose dependencies name nothing, whose acceptance is
uncovered, or whose concurrent units would write the same file.

Then route. Every unit needs a real model, not the `local` placeholder:

```text
Director   the frontier model, pinned, never silently downgraded
Manager    capable enough to review and advise over its whole branch
Worker     the cheapest model that will pass first time
```

Cheapest-that-passes, not cheapest. A worker that fails twice and escalates costs
more than a capable one that passes once, because a failed attempt pays for its
context twice and its output twice, plus a review it did not need.

```text
gcl route set --model <model> --fallback <model> --evidence <where it came from>
```

Record where the choice came from. A model list from the harness is a weaker
basis than a measured one, and the user is approving a cost estimate built on it.

## 3. APPROVE

Render the complete plan to the user: all six sections, every unit with its full
contract, the routes, and every unresolved risk.

A summary is not an approval view. If the plan is long, say so and render it
anyway.

```text
gcl approve --rendered
```

That binds approval to a hash of the unit contracts. Reformatting the prose does
not void it; changing a scope, command, acceptance id, or route does, and then
you go back to the user.

## 4. EXECUTE

**Execution means spawning subagents.** Every unit runs inside its own freshly
spawned agent. Not a section of your reply. Not a file you edit because by now
you know what the code should say. If this phase ends and you never called your
harness's subagent tool, the run failed, however good the diff looks.

You spawn, route, review, advise, and record. You do not implement. If you are
about to open an implementation file during this phase, stop: you have skipped
dispatch.

The mechanism, including the harness-specific calls and every way a real run has
failed, is in `references/dispatch.md`. In outline:

```text
gcl status              the frontier: units whose dependencies all passed review
gcl emit                one packet per ready unit, plus a preflight block
                        stop unless preflight.ready_to_dispatch is true
spawn                   one subagent per ready unit, whole round in one message
gcl set <unit> running  record it before relying on it
```

Send each packet **verbatim**. Paraphrasing is how a scope leaks and how a worker
ends up reviewing itself.

Spawn width comes from the dependency graph, not from preference. Independent
units go together, up to `max_active_workers`. A linear chain goes one at a time
by necessity: a worker handed a repository that does not yet contain what its
packet described fails for a reason the plan never predicted.

Then run one loop until the graph is finished or genuinely blocked:

```text
worker submits a report        -> awaiting_review
manager reviews against the unit contract
  pass                         -> completed, dependents become eligible
  repair_required              -> bounded repair by a worker, never by the manager
  human_required               -> isolate this branch, continue every other
```

Only a passing review moves a unit to `completed`, and only that makes dependents
eligible. A worker that says it is done is not done.

That is structural, not a convention. `gcl set` refuses all three verdict states;
they exist only through `gcl review`, which will not record a pass without
evidence, a repair without both a defect and an instruction, or an escalation
without the question and what was already tried.

```text
gcl review <unit> --verdict pass --evidence "<real command output>"
gcl review <unit> --verdict repair_required --defect "..." --repair "..."
gcl review <unit> --verdict human_required --question "..." --attempted "..."
```

An escalation reports its own blast radius: the transitive dependents that are
now blocked, and every independent unit that keeps running.

The escalation ladder is bounded and nothing may lengthen it:

```text
worker attempt -> manager advice -> same-worker repair -> fallback-worker repair
  -> Director advice -> human_required
```

`human_required` blocks that unit's dependents and nothing else. Independent
units keep running. Say what is blocked, what continues, what was already tried,
and the exact decision the user has to make.

## Each of these is a failed execution, whatever the diff looks like

- implementing units yourself in the root session;
- spawning one subagent for the whole plan instead of one per unit;
- spawning subagents to research, then writing the code yourself;
- dispatching ready units one at a time when several were ready together;
- spawning a dependent unit before its predecessor's artifacts exist;
- spawning headless, so no worker is visible or monitorable;
- dispatching packets that still carry a placeholder route;
- moving a unit to `completed` on the worker's own say-so.

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
gcl approve --rendered                    bind approval to the unit contracts
gcl recover [--apply]                     reconcile after an interrupted session
```

Do not invent commands. Everything the run needs is above.

## Evidence rules

Every load-bearing claim cites a file, symbol, command result, or dated source.
Completion requires a passing review with acceptance results and real command
output. Never infer completion from a worker's summary, and never convert missing
evidence into an inferred pass. A green build is not evidence that a surface
works: look at the thing itself.

Secrets are read from the environment at request time. Never ask for a plaintext
key in chat, a command, the plan, or a tracked file.

## Stop and escalate on

A harness with no way to spawn subagents; product ambiguity only the user can
settle; a plan that cannot pass `gcl check`; a unit whose acceptance cannot be
verified; no model available that meets a unit's needs; a request to approve
without rendering the full plan; a material change after approval; a destructive
operation without authorization; secret exposure; or an exhausted escalation
ladder.
