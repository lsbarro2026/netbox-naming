---
description: Quick view of claimable TODO items grouped by which model tier picks them up
model: haiku
effort: low
disable-model-invocation: true
---

Show which backlog items are actually claimable right now, grouped by model tier, so I can tell
which `/plan-todo` tab (sonnet/opus/fable) should pick up what — without eyeballing the flat
`summary` list or burning a speculative `next --model` claim.

Run `todo-lock.py` from the repo root — `cd` back if you moved; a worktree-isolated session refuses
`$(git rev-parse …)`.

Run (read-only, no git mutex needed):

```
python3 .claude/todo-lock.py summary-by-model
python3 .claude/todo-lock.py summary-by-route
```

The second prints, per route with waiting work, the count, the first ids and the exact command that
launches a tab for it (`claude --model … --effort … "/plan-todo …"`). Print it as-is after the tier
groups (skip its repeated `== in_progress ==` section).

Print the output as-is, organized by tier. If a tier section is empty it's simply omitted — say so
if I ask why a tier is missing. Don't interpret or filter further; this is a glance, not an
analysis.

The output ends with a trailing `== in_progress ==` section (omitted when nothing is claimed)
listing items already being worked, each with its worktree (`wt=`) if one has been attached —
visibility into what's claimed, alongside what's still available. This section doesn't change
what counts as "claimable" in the tier groups above it.
