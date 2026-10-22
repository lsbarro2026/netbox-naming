---
description: Reorder the TODO backlog, chain items that collide over a file or depend on another item's outcome, and merge items that are duplicates or trivial enough to batch, so /plan-todo picks conflict-free work first
argument-hint: (optional) ordering guidance, e.g. "security first"
disable-model-invocation: true
---

Reorganize the `## Open` backlog so the next `/plan-todo` tab always claims work that is ready to be
worked on its own: items making large edits to the same file get chained, an item that can't be
planned sensibly until another lands gets gated behind it, duplicates (or two trivial items in one
file) get merged, and the rest are ordered by priority. `.claude/todo-lock.py` is the only interface
— **never read or hand-edit `TODO.local.md`**. Run this in the primary worktree (your normal main
tab), not inside a `/plan-todo` worktree. Run `todo-lock.py` from the repo root — `cd` back if you
moved; a worktree-isolated session refuses `$(git rev-parse …)`.

Optional steer from the user (weight it when ordering; ignore if empty):

$ARGUMENTS

Stay cheap: two script calls carry the usual pass — `files` to see the overlap signal, `reorder
--commit` to apply and commit the plan. Don't read item bodies wholesale. Merging (step 3) and revising a route (step 4) are
occasional.

1. **Get the compact overlap table** — one line per Open item (`id · status · declared files ·
   title`), from each item's `- **Files:**` bullet:

   ```
   python3 .claude/todo-lock.py files
   ```

   Exit 70 `crashed (store)` (or a missing/truncated listing) → stop and ask the user to run
   `/repair`; any other crash class → relay the one-line message. Paths marked `[doc: …]` are
   documentation, whose overlap is informational — don't chain on them alone. The `status` column
   is what you must respect: `admin` (never ordered), `in_progress` (claimed — heading frozen;
   `reorder` won't re-block it), `blocked`, `priority`, `open`. Only when an item's file list
   reads `?` or is too
   vague to judge overlap, spend a `show <id>` on that item (or offload a batch to an `Explore`
   subagent on `model: "haiku"`).

2. **Decide the plan — this judgment stays with you.** Two independent knobs:

   - **`order`** — the file order of Open items, which is the claim order `next` uses for
     non-priority items (a `[PRIORITY]` item still jumps ahead). List ids in the sequence you want
     them worked; omitted ids keep their relative order after the listed ones. Order by importance /
     the user's steer, and put a chain's head before its dependents.

   - **`blocks`** — the complete Open-item→Open-item dependency graph, `{id: [blocker-ids]}`. A block
     gates claiming: `/plan-todo` won't hand out a blocked item until its blocker is `/finish`ed. Two
     different things earn an edge, both in the same dict:

     **(a) Same-file collisions.** Large edits to the same file → chain them: if FOO-1, FOO-2, FOO-3
     all substantially rewrite `shared.js`, gate them in series — `{"FOO-2": ["FOO-1"], "FOO-3":
     ["FOO-2"]}` — so each builds on the last with no merge conflict. Small or incidental overlaps →
     leave them to race; `/finish` resolves those merges on the branch, and over-blocking serializes
     work that could run in parallel. Disjoint files stay unchained for this reason — still check (b).

     **(b) Planning dependencies — one item's outcome decides how another should be built.** Use it
     wherever working an item out of order produces the wrong work, not merely a merge conflict: a
     chosen approach, a new interface, a schema, a design decision the other has to target. The test:

     > **Would this item be planned or built differently if whoever claims it could see the other
     > item's finished result?** If yes, block it behind that item. If the result would merely be
     > interesting context — or the two just share a topic, a subsystem, or a word in their titles —
     > leave them unchained.

     - **Block:** FOO-3 designs the new config schema; FOO-7 adds a feature that reads config and
       should target it. Claimed first, FOO-7 is built against the old schema → `{"FOO-7":
       ["FOO-3"]}`, though they share no file.
     - **Don't block:** FOO-4 and FOO-9 each add a subcommand to the same CLI. Related, but neither
       one's result changes how the other is written → unchained.

     A block costs real parallelism, and topical relatedness is everywhere: chain on "seeing the
     result changes the plan", not "these sound related". The table won't hand you (b) — read it off
     the titles (an item that designs / introduces / replaces / decides something near one that uses
     it), and spend a `show <id>` only on a pair whose titles flag it.

   `blocks` is authoritative for Open-item gates: an Open-item blocker you don't re-list is cleared.
   So pass the entire intended graph — **both kinds of edge in one dict, one `reorder` call**; a
   second call meant to "add" edges wipes the first call's. The script refuses a cyclic plan and
   writes nothing, so don't hand-verify acyclicity. Never put in `blocks`: human `[BLOCKED:
   <ADMIN-ID>]` gates (kept automatically) or `in_progress` items (left untouched, with a note).

3. **Merge — only if two rows are the same work, or two or three trivial items share one file, and
   only with the user's OK.** A merge deletes an item and is irreversible, so propose it and wait;
   when unsure, don't. Read `.claude/skills/reorder/todo-reorder-reference.md` ("Merging items") for the criteria,
   the `merge` call and how to set the survivor's route. Merge before you reorder — a merged-away
   id is unknown to the plan.

4. **Reassess a route — only where your plan moved an item onto a route with a different model**
   (`todo-lock.py routes` prints each route's model): sequencing shrank it, or the real scope
   surfaced. Most passes change nothing. Read `.claude/skills/reorder/todo-reorder-reference.md` ("Reassessing a
   route") for the one-call `set-effort <id> <route>`. Reversible — don't ask first; report it.

5. **Apply the order + chains, and commit** — one call, JSON plan on stdin, applied atomically
   under the store lock (it rejects unknown ids, self-blocks, Admin-task blockers, cycles, and any
   stray note wedged between items, writing nothing if the plan is bad). `--commit` commits only
   `TODO.local.md` under the git mutex, taking steps 3–4's uncommitted edits with it. Its plain
   default subject is `Reorder TODO backlog`. If you merged, name the merge with `-m`, e.g.
   `-m "Reorder TODO backlog; merge FOO-9 into FOO-4"`. Don't push (that's `/sync`):

   ```
   python3 .claude/todo-lock.py reorder --commit <<'EOF'
   {"order": ["BAZ-1", "FOO-1", "FOO-2", "FOO-3", "BAR-1"],
    "blocks": {"FOO-2": ["FOO-1"], "FOO-3": ["FOO-2"], "BAR-1": ["BAZ-1"]}}
   EOF
   ```

   Here FOO-2/FOO-3 chain behind the big `shared.js` rewrite, and BAR-1 is gated on BAZ-1 because
   BAZ-1 decides the interface BAR-1 builds against (JSON takes no comments — keep the reasoning for
   your report). It prints the new order and which headings gained/lost block markers, then `OK
   committed <sha>`. If it errors, nothing was written or committed: fix the plan and re-run.

6. **Sanity-check** with `python3 .claude/todo-lock.py summary`: chain heads `open`/`priority`,
   dependents `blocked`, any merged-away id gone.

Then briefly tell the user the new claim order and, for each chain, which reason put it there — a
shared file (name it) or a planning dependency (name what the blocker decides). Add the overlaps you
deliberately left to race, any route you changed and the model it moved to, and — if you
merged — which id survived, which is gone, and whether it was a duplicate or a trivial batch.
