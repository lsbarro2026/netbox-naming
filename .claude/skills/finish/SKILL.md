---
description: Wrap up a finished task — docs, commit in the worktree, one-command land, exit
argument-hint: [review] [optional note about what was done]
---

Wrap up the task you just finished (this runs inside the item's worktree created by `/plan-todo`).
Optional note about what was done:

$ARGUMENTS

Running this command is my go-ahead to commit and merge back to `main`. Work the checklist in order;
skip a step only if it genuinely doesn't apply, and say so when you do. Run `todo-lock.py` from the
repo root (the worktree root inside one) — `cd` back if you moved; a worktree-isolated session refuses
`$(git rev-parse …)`.

First, read this repo's context for the step list below — the item's route, release bookkeeping,
verify commands and any project overlay:

```
python3 .claude/todo-lock.py context finish --id <id>
```

Project context printed by the script is this repo's own instruction and takes precedence over this
command's defaults.

Don't re-derive what this session already established: right after planning, implementing and
verifying the item here, confirm scope with a cheap `git diff --stat` and go straight to the steps.
Survey from scratch only if a compaction dropped that context, the diff spans more than ~10 files, or
you're finishing a worktree you didn't build.

1. **Documentation maintenance — same change, not a follow-up.** Treat an out-of-date doc as a bug.
   Run `python3 .claude/todo-lock.py docs touched`; each pointer it prints names a section worth a
   look (`docs show <ref> --section "<heading>"`) — read those instead of surveying. On `NONE` or
   "not configured", fall back to scoping the check yourself: the docs the plan named, plus whatever
   `grep -rn` for the added/renamed names turns up across your docs and READMEs. Read the matching
   sections only. Follow whatever documentation rules your repo's `CLAUDE.md` sets.

   Prefer a new record over amending a long document. If the reasoning belongs in a document over
   ~400 lines, write a short new numbered record instead (`seq new`); an accepted record is not
   edited. One home for rationale: it lives in that record, or in the commit body when there is none;
   code comments state the invariant and cite the record; the plan, the commit message and the final
   summary point at it and don't restate it; a measured number is written in one document only.

2. **Coding-standards pass.** No dead code, commented-out blocks, or leftover debug logging; small
   focused units; comments explain the why; no new runtime deps without asking; security and
   data-safety invariants not regressed. Prefer targeted edits over whole-file rewrites, and keep
   changes and committed tests to what the item asks for, so the diff stays reviewable.

3. **Review the changes.** `git status` and `git diff --stat` (staged and unstaged) to confirm scope;
   read full hunks only where you're unsure. Don't remove the TODO item — `land` does that on `main`.

4. **Fresh-context review (opt-in).** Skip this step unless the arguments above say `review`, or
   `.claude/todo-config.json` sets `"finish_review": true` and the item is on a `deep` or `frontier`
   route (the project context's `item:` line names it). Then
   spawn **one** fresh `general-purpose` agent, read-only. Give it only the item's Acceptance and Out
   of scope bullets (its `What` bullet if it has neither) and the diff (`git diff HEAD`, plus the path
   of any untracked file) — not your plan or reasoning. Ask it to list every gap between the diff and
   those bullets, each with a confidence and a severity, unfiltered. You filter: fix what's real and
   re-run only the checks that fix touches; note the rest in one line each in the summary. A gap that
   shows the Acceptance unmet, or one you can't judge, is a stop-and-surface case.

5. **Commit and land on `main` — one command,** from the worktree root. Write the message about what
   changed, not who changed it — **no AI references** (no "Generated with…", no `Co-Authored-By`
   naming an assistant); the script adds none. Keep the body to about 15 lines, written with the
   Write tool to a file. If something looks wrong, stop and tell me instead of committing.

   ```
   python3 .claude/todo-lock.py finish <id> -m "<subject>" --body-file <path> [--include-untracked [paths…]] [--tier <major|minor|patch>]
   ```

   It stages every tracked change plus the untracked files you name, prints what it staged, commits
   on the branch, and runs `land`: that folds `main` into your branch (so a conflict surfaces here,
   never on `main`), merges, removes the TODO item, writes any configured bookkeeping, and releases
   the claim. On a release, write the CHANGELOG heading as `## {VERSION}` and pass the planned
   `--tier`; the script reserves the number and fills it in. Don't hand-edit a sequence index or
   generated table row, or the version source, on your branch — `land` renders them on `main`.

   - `UNTRACKED` (exit 5) → nothing was staged. It lists the untracked files: include the ones that
     belong to the item (`--include-untracked <paths…>`, or bare for all), delete strays, and re-run.
   - `nothing to commit` → the work is already committed on the branch; run `land <id>`.
   - `OK landed …` → step 6 (also when it says the branch had no commits of its own).
   - Anything else is `land`'s outcome, with your commit already on the branch → follow what it
     prints, then retry with `python3 .claude/todo-lock.py land <id>`, not `finish`. On `CONFLICT`,
     reconcile both sides with semantic care — keeping "your" side can silently drop another landed
     item's work — re-run the tests, commit, and re-run `land`. On `VERIFY-FAILED` (exit 6) the fold
     broke the tests and `main` is untouched: fix it in the worktree, commit, re-run `land` —
     `--no-verify` only if I say so. **Stop and ask me** on `DIRTY` (never
     commit or stash the main checkout yourself), on an off-branch primary checkout, on `WARN`, or on
     a conflict you can't confidently reconcile.

   Push only if I explicitly ask.

6. **Remove the worktree.** Only after `OK landed …`, as its `next:` line says: `ExitWorktree` with
   `action: "remove", discard_changes: true` — a plain `remove` always refuses, citing the (already merged) commits.
   Never use `discard_changes` to force past any other outcome, where the branch may hold unmerged
   work. After a `land --in-place` recovery there is no worktree; skip this step.

Then give me a short summary: what you did, the verify command you ran and its result, which docs
you updated, what you committed, the fresh-context review's findings and what you did with them (when
it ran), that `land` merged and removed the item (+ version, on a release), that the worktree is
gone, and any deviation from the approved plan, or "none". The final summary, or a stop message
before `/finish`, runs about 10 lines at most and leads with the outcome. End by telling me to
`/clear` or open a fresh tab before the next item, since this item's context only inflates the next
one.
