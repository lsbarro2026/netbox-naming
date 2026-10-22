---
description: Mark a human Admin task done — delete it and unblock its [BLOCKED: <id>] dependents
argument-hint: <admin task id or description of what you finished>
disable-model-invocation: true
---

I've completed a human/administrative task; record it so the AI removes it and frees anything it
was blocking:

$ARGUMENTS

Admin tasks live under `## Admin` in the store — human-only work (publish a package, create a repo,
flip a repo setting, buy/sign something) that `/plan-todo` never claims. `.claude/todo-lock.py` is
the only interface; don't read the whole `TODO.local.md`. Run this in the **primary worktree**. Run
`todo-lock.py` from the repo root — `cd` back if you moved; a worktree-isolated session refuses
`$(git rev-parse …)`.

1. **Identify the task.** If I gave an ID, use it. Otherwise list the human tasks and match mine:

   ```
   python3 .claude/todo-lock.py summary --status admin
   ```

   If it's ambiguous, show me the candidates and ask which one — don't guess.

2. **Confirm before deleting.** Read just that task and note what it unblocks:

   ```
   python3 .claude/todo-lock.py show <id>
   ```

3. **Complete it and commit.** This deletes the Admin task **and** strips `[BLOCKED: <id>]` from
   every Open item that referenced it (making them claimable). `--commit` commits only the store,
   under the git mutex, with a plain `Complete admin task <id>: <title>` subject:

   ```
   python3 .claude/todo-lock.py admin-done <id> --commit
   ```

   Note the `unblocked: …` line it prints. Do not push (that's `/sync`).

Then tell me: which task was removed, and which items it unblocked (they can now be picked up with
`/plan-todo`). If completing this task also implies follow-up work, mention it — but don't invent
new items unless I ask.
