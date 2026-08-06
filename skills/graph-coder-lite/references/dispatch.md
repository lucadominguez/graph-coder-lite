# Dispatch

How phase 4 actually puts work into subagents. Every rule here corresponds to a
way a real run has already failed, so none of it is theory.

The rule it serves: **every unit runs in its own spawned subagent, and the
Director never implements one itself.**

## Preflight

`gcl emit` returns a `preflight` block. Read it before spawning anything.

```json
"preflight": {
  "ready_to_dispatch": false,
  "dispatchable_units": 2,
  "unrouted_units": ["IU-MIGRATION", "IU-SCHEMA"],
  "approved": false,
  "warnings": ["2 units carry a placeholder route ..."]
}
```

`ready_to_dispatch: false` means the graph will run, but not the run that was
approved. Fix what the warnings name and re-emit. Do not dispatch past it.

Then check the swarm for stale state, and clean it **narrowly**. Plan nodes from
an earlier session survive and merge into yours: one run emitted a 3-node graph
and got a 55-node plan. If the harness reports more nodes than your plan has,
that is what happened.

```text
swarm list                  see what exists before removing anything
remove the stale nodes      by id, the ones that are not in your plan
swarm cleanup --force       last resort only, after confirming no unrelated agent runs
```

**Never open with `swarm cleanup --force`.** An earlier version of this file told
you to, and a run followed it and stopped every worker on the machine, including
agents belonging to unrelated projects. It is global, it does not scope to your
graph, and other people's work is not yours to kill. If you cannot scope the
removal and unrelated agents are live, leave the swarm alone and spawn per unit,
which does not depend on a clean plan registry. Say that you did so and why.

## Spawning

One subagent per ready unit, one round per frontier. Take the emitted entry's
`content` as the prompt and its `id` as the label.

```text
swarm spawn --label "IU-STORE" --prompt "<content, verbatim>" \
  --working_dir "<project root>" --spawn_mode visible --model "<model>"
```

Issue every ready unit's spawn **in a single message** so the round is genuinely
parallel. Nothing about `swarm spawn` requires the agent to join the swarm; a
spawned worker does its job either way, so do not chase swarm membership as if it
were a precondition.

`spawn_mode: visible` is not optional. A worker spawned inline or headless does
the work and never appears in `swarm list`, so you cannot see it start, stall, or
finish, and the status roster becomes fiction.

**Batch registration is brittle.** JCode's `run_plan` has failed on stale plan
pollution and on `Only the coordinator can assign tasks.` If you try it and it
errors, drop straight to per-unit spawns rather than debugging it. The per-unit
route produces the same agents with the same packets.

**Any other harness with a subagent tool**, Claude Code included: one subagent
call per emitted entry. Prompt is its `content`, model is its `model`.

**No subagent tool at all.** Then this harness cannot run the graph. Say so and
stop. Do not silently degrade into implementing the plan yourself, which produces
a plausible diff with none of the isolation, review, or cost properties the plan
was approved on.

## Parallel rounds and linear chains

Spawn width is set by the dependency graph, not by preference.

```text
independent units    spawn together, in one message, up to max_active_workers
linear chain         spawn one, verify, review, then spawn the next
```

`IU-STORE -> IU-ENDPOINT` cannot be spawned at once: the second worker needs the
first one's artifacts to exist before it starts. The reverse mistake costs just
as much, though: serializing units that share no dependency edge because watching
one at a time felt easier. `gcl status` recomputes the frontier after each round
of verdicts. Spawn everything in it.

## While a worker runs, watch two things at once

The filesystem and the swarm answer different questions, and neither answers the
other's.

```text
filesystem      is it done?     write scope changed, artifacts exist
swarm status    is it alive?    running, rate-limited, errored, dead
```

Polling only the filesystem is the trap. A worker blocked on a `429` produces no
files, and so does a worker that is thinking hard. They are identical from a
directory listing. One real run polled for a file for two minutes while the
worker sat rate-limited the whole time, because `swarm status` was never checked.

**You cannot read a live worker's transcript.** `swarm read_context` returns busy
while the agent runs, and `session_search` returns metadata only. Plan around it
instead of retrying the call:

- Packets require a progress log and incremental writes, so the filesystem
  carries the progress the transcript will not.
- Token growth without file growth is its own signal: alive and producing, but
  nothing landing. That is a loop or an over-long preamble, not a freeze.
- If you need to know what a worker did, that is what its report and artifacts
  are for. Wait for the terminal state rather than trying to watch.

### When to stop waiting

Read the unit's `checkpoint_every` first, because it says what progress should
look like *for this unit*. A single-pass unit is not stalled when nothing
appears; a unit that promised a write per page and has written nothing for a
minute is. Judging both by the same timer gives false alarms on one and blindness
on the other.

Measure from the last observed change, not from spawn:

```text
elapsed since last change   files    tokens    read as              do
under 60s                   any      any       working              wait
60s                         none     growing   alive, unproductive  probe: swarm status
120s                        none     growing   suspected loop       surface options
120s                        none     none      suspected freeze     surface options
300s                        none     any       failed attempt       count it, escalate
```

Crossing that last bound ends the wait. Count it against the unit's attempt
limit, take the fallback model, and follow the escalation ladder. This is the one
exception to "never respawn a live worker": past its bound the worker is not
healthy, it is hung. **Stop it before spawning its replacement**, so two agents
never share a write scope.

Never sit in an unbounded wait because the rule said not to respawn. The rule
protects a working worker, not a hung one.

Keep the watchers to one per round. Overlapping wait calls resolve on top of each
other and report the same completion more than once, burying the one event that
mattered.

Classify what the health signal shows before reacting:

- **rate limited (`429`)**: transient infrastructure, never model incapability.
  Wait out a short `Retry-After` or take the fallback, which should be a
  different provider. Do not respawn on top of a live worker.
- **errored or dead**: a real attempt. Count it and follow the ladder.
- **running with no output**: keep waiting while the timer allows, then surface
  bounded cancel, continue, or fallback options.

## Verifying a worker finished

A report is not completion evidence. Confirm from the filesystem and from
commands:

1. The files in the unit's write scope exist and changed. `gcl verify <unit>`
   lists them.
2. The unit's green commands run and pass, with the real output quoted.
3. Every assertion in the output contract holds against the artifact's
   **contents**, not its existence.

That evidence is what goes to the manager. A worker's own claim that it finished
is not evidence, and neither is its absence from `swarm list`: absence means you
cannot monitor it, which is a gap to report, not a verdict either way.

## Round discipline

- Record a dispatch with `gcl set <unit> running` before relying on it.
- A worker returns a report; route it to its manager. `gcl set <unit>
  awaiting_review`.
- Recompute the frontier only after verdicts land, because only a pass makes
  dependents eligible.
- Repairs are spawns too. A bounded repair goes to a worker subagent, never to
  the manager and never to the Director.
- A fallback retry needs no lookup: each emitted entry carries `fallback_model`
  beside `model`. If the field is null, the plan declared no fallback, and that
  is an escalation rather than an invitation to pick one.

## Self-check

Before reporting execution finished, confirm all of these:

- [ ] Subagents spawned is at least the number of units.
- [ ] No implementation file was written by the root session during phase 4.
- [ ] Every spawn used `spawn_mode: visible` and a real model, never a placeholder.
- [ ] Worker health was polled alongside the filesystem, so no worker sat blocked
      on a rate limit unnoticed.
- [ ] Every completed unit has a manager verdict with acceptance results, backed
      by filesystem evidence and fresh command output.
- [ ] Every spawn used its emitted packet, not a summary of it.
- [ ] Rounds were parallel where the frontier allowed, sequential only where a
      dependency required it.

Any unchecked box means the graph was not executed. Report that instead of
reporting success.
