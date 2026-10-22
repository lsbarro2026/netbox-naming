---
description: Sync the TODO backlog across machines — commit local TODO edits, then pull + push
argument-hint: (no args)
disable-model-invocation: true
---

Exchange the committed work list with the remote so another machine can `/sync` and pick up from the
same place. This commits your pending `TODO.local.md` edits, pulls anything new from `origin`, and
pushes — running `/sync` **is** your go-ahead to commit *and* push.

Scope: the **commit** step only touches `TODO.local.md` (like `/todo`). The **pull/push** move the
whole committed history both ways, so `/todo` and `/finish` work from either machine rides along
too. The per-machine claim lock (`.claude/todo-lock.py`'s JSON in `.git`) is intentionally **not**
synced — claims and worktrees are local to each machine.

Run this in the **primary worktree** (your normal main tab), not inside a `/plan-todo` worktree. Run
`todo-lock.py` from the repo root — `cd` back if you moved; a worktree-isolated session refuses
`$(git rev-parse …)`.

1. **Preflight — confirm the remote is what you expect.** `git remote get-url origin` should be the
   repo you intend to sync the backlog through. If your project keeps private files out of a separate
   public remote, make sure this push targets **only** the private/backlog remote — never let backlog
   or other private files reach a public one. If `origin` isn't the remote you meant, **stop** and
   tell me.

2. **Commit + pull + push, under the git mutex** (so a parallel `/finish` merge or `/todo` commit on
   this machine can't race refs). Merge-based pull (`--no-rebase`) so it never rewrites the `--no-ff`
   merge commits `/finish` creates:

   ```
   python3 .claude/todo-lock.py git-mutex -- sh -c '
     set -e
     if ! git diff --quiet HEAD -- TODO.local.md; then
       git commit -q -m "Sync TODO list" -- TODO.local.md
       echo "committed local TODO.local.md edits"
     else
       echo "TODO.local.md already matches HEAD — nothing to commit"
     fi
     git pull --no-rebase --no-edit
     git push
   '
   ```

3. **Handle the outcomes:**
   - **Clean success** → report what happened: whether a commit was made, how many commits were
     pulled, and that the push landed (`git log --oneline -3`, and `git status -sb` should show
     `## main...origin/main` with nothing ahead/behind). If commits were pulled, run
     `python3 .claude/todo-lock.py list`: a claim flagged `GONE` or `CHANGED` means the pull removed
     or rewrote an item a tab here is working on — **warn me by id**. Don't release it yourself.
   - **Merge conflict in `TODO.local.md`** (both machines edited the same lines) → the pull left
     conflict markers. **Do not guess** — show me the conflicted section and let me resolve it, then
     finish with `git add TODO.local.md && git commit --no-edit && git push` (re-run under the mutex).
   - **Pull refused because the tree is dirty** (uncommitted non-TODO files the merge would touch) →
     stop and tell me which files; I'll commit or stash them, then re-run `/sync`.
   - **Push rejected (non-fast-forward)** → someone pushed after your pull; just re-run `/sync`.

Then give me a one-line summary: committed? pulled N? pushed? — so I know the other machine can now
`/sync` into the same state.
