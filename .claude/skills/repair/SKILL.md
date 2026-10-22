---
description: Fix TODO.local.md formatting so todo-lock.py can reference every item again
argument-hint: (none)
disable-model-invocation: true
---

`TODO.local.md` has picked up formatting that stops `.claude/todo-lock.py` from seeing an item —
the parser silently drops any `### ` heading outside a `## Admin`/`## Open` section, any heading
without an `<ID>` token, and anything hidden inside an unbalanced ``` fence. Fix it via the script
(don't hand-edit the whole store file). Run this in the **primary worktree**. Run `todo-lock.py`
from the repo root — `cd` back if you moved; a worktree-isolated session refuses `$(git rev-parse …)`.

1. **Diagnose (read-only) then repair.** `repair` applies the safe, unambiguous fixes in place
   (trailing whitespace; `##Open`/case/hash-level section headers → `## Admin`/`## Open`; malformed
   or lowercase-ID item headings → canonical `### <ID> — <title>`; and strips **clearly-orphaned
   stray text** — prose/bullets/dangling comments sitting outside any item, either before the first
   `## ` section or between a `## ` header and its first `### ` item, leaving blockquote/heading
   preamble and any orphaned `### ` heading untouched) and prints anything it won't guess at:

   ```
   python3 .claude/todo-lock.py repair
   ```

   (`python3 .claude/todo-lock.py doctor` is the read-only version — same report, no changes — if
   you just want to see the state first.)

2. **Resolve the MANUAL items with the user.** `repair` exits non-zero and lists what it can't
   safely fix on its own. For each, read only the affected span (`show <id>`, or read those few
   lines) and fix it — asking the user when intent is unclear, not guessing:
   - **orphan heading (outside any `## section`)** — move it under `## Admin` (human task) or
     `## Open` (agent work); ask the user which if it isn't obvious.
   - **heading has no `<ID>` token** — give it a stable id (`next-id <FAMILY>` for the next free
     number), or delete the line if it isn't really an item.
   - **unbalanced ``` fence** — add the missing closing ```` ``` ```` (or remove a stray one); items
     after an open fence are invisible to the parser until it's balanced.
   - **duplicate id** — renumber one of them (`next-id <FAMILY>`); two items must not share an id.
   - **dangling `[BLOCKED: <id>]`** — the referenced blocker is gone. If the blocker is done,
     strip the marker (an Admin blocker should have been closed with `/admin-task`); otherwise point
     it at the correct id, creating a gate if one still applies.
   - **Admin task carries `[BLOCKED]`** — Admin tasks are never claimed, so a block marker on one is
     meaningless; strip it.

3. **Confirm it parses, and commit.** Re-run until clean:

   ```
   python3 .claude/todo-lock.py doctor    # want: "OK — TODO.local.md is well-formed"
   ```

   Then commit with one more repair run. It commits only the store, under the git mutex, and
   includes your hand fixes. Don't push (that's `/sync`):

   ```
   python3 .claude/todo-lock.py repair --commit
   ```

   A run that still reports MANUAL issues is left uncommitted. Resolve them, then re-run it.

Then tell me what was auto-fixed, what needed a judgment call and how it was resolved, and confirm
`doctor` now reports the store as well-formed.
