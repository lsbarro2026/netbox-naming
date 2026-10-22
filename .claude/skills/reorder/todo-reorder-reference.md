# `/reorder` — reference material, loaded on demand

`.claude/skills/reorder/SKILL.md` points here, each time gated on a condition stated before the
pointer. Read only the section you were sent to; the others are unrelated.

## Merging items

You're here because two or more rows look like one piece of work. Two different findings earn a
merge, and both use the same call. This is the one place worth spending `show <id>` on every body
involved: you need them to write the combined body.

**Propose before you apply — both kinds.** A reorder is reversible; a merge is not — it deletes an
item, and its id is never reissued. Tell the user which items, which id you'd keep, which of the two
reasons below applies, and why, then wait. When you're unsure, don't merge: chaining and leaving two
items alone are both reversible; this isn't.

### (a) Duplicates and split halves — the same work described twice

Chaining those is the wrong answer: whoever claims the second one finds the work already done. Fold
one into the other.

- **Merge:** FOO-2 "config parser silently drops unknown keys" and FOO-6 "typo in a config file should
  be reported, not ignored" — one bug, filed from two directions. One body, one fix.
- **Don't merge:** FOO-2 and FOO-8 both substantially rewrite `src/config.py`, but one fixes key
  validation and the other adds an env-var override. Two real jobs that merely can't run at once → a
  `blocks` chain, which is the reversible answer.

### (b) Trivial batches — two or three tiny items in one place, cheaper worked as one

Every item pays a fixed claim → plan → worktree → commit → `land` → teardown cycle that dwarfs the
actual work on a `trivial` item, so two of them in the same file cost less as one item than as two. This
is a narrow licence, not a general "small items should be combined" — all four limits hold:

1. **Each item is trivial on its own** — routed `trivial`, obvious and low-risk. An item carrying a
   design decision is never batched, however small its diff looks.
2. **Same file, or the same tight subsystem**, so one worktree genuinely does both in barely more than
   one pass. Two trivial items in unrelated corners of the tree are not a batch: merging them buys one
   shared commit and gives up the parallelism of two tabs claiming them at once.
3. **At most three items, and the combined work stays on a route with the same model** — moving to
   a larger model pays the saved overhead straight back in model cost. Two `routine` items whose
   batch would need `judgment` leave the sonnet tabs for the opus tabs; keep them separate.
4. **The propose-and-wait gate above still stands.** A batch deletes an item like any other merge.

- **Merge:** BAR-4 "`--dry-run` help text has a typo" (`trivial`) and BAR-5 "`--force` help text
  says 'over-write'" (`trivial`), both in `install.sh`'s usage block → one `trivial` item, one pass
  over one file.
- **Don't merge:** BAR-4 (`trivial`, `install.sh` help text) and BAR-9 "bump the copyright year in
  `LICENSE`" (`trivial`). Both trivial, but they share no file and no subsystem.

Same file alone decides nothing: large same-file items chain, trivial same-file items may batch, and a
large item never batches with anything.

### The call

```
python3 .claude/todo-lock.py merge <survivor> <absorbed> --effort <route> --body <<'EOF'
- **What:** …the combined body you just wrote…
- **Files:** …the union of both file lists…
EOF
```

`--effort <route>` writes the survivor's one `- **Route:**` bullet. Pass the later of the two
routes for (a), or the route the combined work needs for (b). Don't write the bullet into the body.
Leave the merge uncommitted: step 5's `reorder --commit` commits it with the new order.

The first id survives, keeping its id, file position and gates: `[PRIORITY]` if either item had it,
the union of both `[BLOCKED: …]` markers, and anything blocked on the absorbed item retargeted onto the
survivor (its work moved rather than finished, so dependents stay gated). Without `--body` the two
bodies are concatenated — Files bullets joined, the route set to the later of the two in table
order (unless `--effort` sets it) — fine for two halves of a
task, usually messy for a true duplicate, and wrong for a batch. `--title <T>` retitles the survivor.
It refuses an `in_progress` item, refuses to merge across `## Admin` and `## Open`, and writes nothing
on any error.

**The route is where a batch differs from a duplicate — write it yourself.** The default is the
later of the two: right for a duplicate, possibly wrong for a batch (two `trivial` items together may
be `routine` work). So a batch must pass `--effort` with the route the combined work needs, from
`/todo`'s four route questions — checked against limit 3 before you propose it, not after.

Merge before you reorder: the `reorder` plan rejects unknown ids, and a merged-away id is unknown.
Re-run `files` after merging if you want the refreshed table.

## Reassessing a route

You're here because the plan you just built left an item on a route whose model no longer fits it.
This is not a re-audit of the backlog. The two cases that come up:

- **Sequencing shrank it.** You chained FOO-7 behind FOO-3, and FOO-3 settles the open design
  question — what's left of FOO-7 is settled and provable: `judgment` becomes `standard`.
- **The real scope surfaced.** The `files` table shows an item touching far more than its title
  implied, or a merge fused two halves into one item bigger than either.

Answer `/todo`'s four route questions again for the item as it now stands. Only a change of model is
worth an edit: `routine` → `standard` changes nothing here; `standard` → `judgment` moves the item
from the sonnet tabs to the opus tabs. `todo-lock.py routes` prints each route's model, and
`summary-by-model` shows every claimable item's current route in one call. This is reversible —
don't ask first, just report what you changed.

One call replaces the item's routing bullet, a legacy Effort bullet included, and leaves the rest of
the body alone:

```
python3 .claude/todo-lock.py set-effort <id> <route>
```

It prints the `→ routes to …` line to report. If the `files` table showed a stale `Files` bullet,
`set-files <id> <paths…>` replaces it the same way. Leave both uncommitted: step 5's
`reorder --commit` commits them with the new order. Skip `in_progress` items: their bodies are
snapshotted in a worktree, so both commands refuse them.
