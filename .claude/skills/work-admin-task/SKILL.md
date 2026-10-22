---
description: Walk me through a human Admin task, check it's really done, then complete it
argument-hint: <admin task id, e.g. ADMIN-3>
disable-model-invocation: true
---

Walk me through this human/administrative task, then close it out:

$ARGUMENTS

Admin tasks live under `## Admin` in the store — human-only work (publish a package, create a repo,
flip a repo setting, buy/sign something) that `/plan-todo` never claims. `.claude/todo-lock.py` is
the only interface; don't read the whole `TODO.local.md`. Run this in the **primary worktree**. Run
`todo-lock.py` from the repo root — `cd` back if you moved; a worktree-isolated session refuses
`$(git rev-parse …)`. **I perform every step myself.** You instruct and verify, running only
read-only commands; never run a step's mutating command (setting `git config`, editing or committing
a file) on my behalf.

1. **Resolve the task.** Upper-case my id first — ids match case-sensitively, so `bug-18` finds
   nothing — and accept any family (`ADMIN-3`, but older Admin tasks such as `BUG-18` too). Then:

   ```
   python3 .claude/todo-lock.py summary --status admin
   ```

   No id, or one that isn't in that list: show me the list, say the id isn't an Admin task
   (`admin-done` would refuse it), and ask which one — don't guess.

2. **Read it:** `python3 .claude/todo-lock.py show <ID>`. If its heading carries `[BLOCKED: <x>]`,
   stop and tell me it waits on `<x>`, which has to land first.

3. **Build the checklist.** The steps come from `**What:**`, the conditions from `**Acceptance:**`.
   Give each condition its check: a read-only command where a local one can prove it (`git config
   <key>`, `test -f <path>`, `git log -1 -- <path>`, `grep`), or my explicit confirmation where none
   can (an external account, a purchase, a repo setting on a host). With no `**Acceptance:**`
   bullet, derive the conditions from What and have me confirm the list before we start.

4. **Guide, then verify.** One step at a time: tell me what to do, wait until I say it's done, then
   run its checks and report each pass or fail. On a failed check, say what's off and keep the step
   open — don't move on, and don't complete the task.

5. **Complete it** once every condition is verified or confirmed — no further prompt. This deletes
   the task, strips `[BLOCKED: <ID>]` from its dependents, and commits only the store under the git
   mutex:

   ```
   python3 .claude/todo-lock.py admin-done <ID> --commit
   ```

   Tell me which task was removed and the `unblocked: …` line it printed; those items can now be
   picked up with `/plan-todo`. Do not push (that's `/sync`).

If I stop partway, don't complete the task: list the conditions still open, so I can rerun
`/work-admin-task <ID>` later.
