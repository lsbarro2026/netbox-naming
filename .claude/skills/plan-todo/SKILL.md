---
description: Claim the next un-started TODO (atomic lock), plan it, then isolate it in a worktree to implement
argument-hint: [effort: low|medium|high|xhigh|max] (optional — the session's /effort level)
disable-model-invocation: true
---

Pick up the next available item from `TODO.local.md` and plan it. Multiple `/plan-todo` tabs run in
parallel safely: each claims its item through a real lock and works in its own git worktree, so two
agents never take the same item or edit the same working tree.

`.claude/todo-lock.py` is the only interface to the backlog — **do not read `TODO.local.md`**; the
script prints the one item you claim, or a one-line-per-item `summary`. Run `todo-lock.py` from the
repo root (the worktree root inside one) — `cd` back if you moved; a worktree-isolated session refuses
`$(git rev-parse …)`.

Work through this in order:

1. **Claim the next item — atomically, first thing.** Pass your own running model (stated in your
   system prompt: "You are powered by the model named …") so `next` hands you work matched to your
   tier. If I gave an effort level as the argument (`$ARGUMENTS`), add `--effort <level>` so `next`
   prefers items whose route wants that effort:

   ```
   python3 .claude/todo-lock.py next --model "<my-model>" [--effort <level>]
   ```

   A `note: <id> wants medium, you are at high: consider /effort medium` line means the claimed
   item's route recommends another effort — mention it to me once, then carry on.

   - `CLAIMED <id>` followed by the item's full body → it's yours, and you have everything you need
     to plan it without opening the store — unless the body ends in a `… truncated` note: then run
     the `show <id>` it names before planning, since the cut tail holds Acceptance and Plan. A
     `Freshness` block before the body says which items it names have landed (with hash) and what
     changed on its files since it was filed — the body may be stale, so read that before
     re-checking git yourself. A `Docs:` block lists up to five
     sections the item's files point at, each with its line range: read those, not whole files.
     A `Project context (plan-todo):` block carries this repo's facts and instructions for the
     workflow; act on each of its lines at the step it names. Project context printed by the
     script is this repo's own instruction and takes precedence over this command's defaults.
   - `NONE-IN-TIER …` (exit 1) → claimable work is waiting only in other tiers. Stop and relay its
     per-route lines to me as printed, launch commands included, so I can start the right tab;
     don't claim across tiers or invent work.
   - `NONE …` (exit 1) → nothing available (every open item is claimed or blocked). Stop and tell me.
   - Exit 70 `crashed (store)` (or a missing/truncated listing) → stop and ask me to run `/repair`;
     any other crash class → relay the one-line message. `NONE` when you know in-tier work exists
     counts as a store problem. A model name that maps to no tier also errors — pass one containing
     `sonnet`/`opus`/`fable`, e.g. `claude-opus-4-8`.

   `next` hands out items by route — `todo-lock.py routes` prints which model each route runs on,
   and the default route an unmarked item takes. If `next` prints an overlap note with your claim, weigh
   sequencing behind that claim (step 5) before racing it. For another item's context, pull just that
   one with `todo-lock.py show <id>`, or the index with `… summary`.

2. **Decide whether planning is warranted.** Start from the item's `- **Plan:**` hint: `fast` means
   the filer could state the whole diff in one sentence, `full` means plan. If the body you just
   read contradicts a `fast` hint, or there is no hint, judge it yourself. The fast path is only for
   a genuinely trivial change: one or two files *that the work will actually touch* — not just what
   the item's `- **Files:**` bullet names, since a filer can under-list them — that are obvious and
   low-risk (typo, copy tweak, version bump, tiny localized edit), with no design decision and no
   research. A new flag, option, subcommand, or other new behavior is never the fast path, however
   short its diff looks — naming it and choosing its edge cases is a design decision on its own. When
   in doubt, plan. Either way, settle the approach in the shared main checkout first; the worktree
   comes at step 4.
   Taking the fast path is announced, never silent: the first line of your next reply says you're
   taking it and why, before any tool call other than reading a file you're about to edit — that
   line is the checkpoint in place of plan approval, so it has to come before the work, not folded
   into a report after. The fast path skips research, not looking: read the file(s) you'll touch
   before editing them, and the "stop and surface" list below still applies after implementation.

3. **Plan it.** Research first — read-only, in the main checkout, so parallel tabs can plan in the
   same tree — then enter plan mode to write the plan. **Write no code while planning.**

   Read a document by the section, not the file: find the heading with `grep -n`, then read only that
   line range (`todo-lock.py docs for <paths>` finds the section; `docs show <ref> --section
   "<heading>"` prints it). Always read the source files you expect to touch yourself — that's
   where the plan's judgment lives. To delegate reading, dispatch the `todo-scout` agent (read-only, returns
   `path:line` findings) with the question and where to look; add `model: "sonnet"` when the
   question needs reasoning or spans several documents. Dispatch it and keep reading rather than
   polling. Don't launch the Plan agents the built-in plan-mode prompt
   suggests: the plan, the trivial-vs-plan call, which docs to update and the implementation are
   yours.

   Prefer a new record over amending a long document. If the reasoning belongs in a document over
   ~400 lines, write a short new numbered record instead (`seq new`); an accepted record is not
   edited. One home for rationale: it lives in that record, or in the commit body when there is none;
   code comments state the invariant and cite the record; the plan, the commit message and the final
   summary point at it and don't restate it; a measured number is written in one document only.

   Work that isn't this item — an out-of-scope bug, or an asset you shouldn't produce inline — is
   filed, not folded in: file it with `/todo`'s own classification, adding `--priority` only when this
   item waits on it. Dispatch the `todo-filer` agent with the brief and the route you picked; its
   reply must match `^[A-Z]{2,}-[0-9]+$` — relay anything else to me. Read
   `.claude/skills/plan-todo/todo-planning-reference.md` ("Spinning off work") for the brief and whether to wait.
   This holds while implementing too.

   If research shows the item is on the wrong route (a bug that is really a crasher, a routine item
   hiding a design decision), don't grind on or `release` it: write what you found to a file and run
   `todo-lock.py bounce <id> --to <route> --reason "<one line>" --body-file <path>`, then relay the
   launch command it prints and stop. It refuses once the worktree has work, so bounce before step 4.

   Produce a concrete plan: files to touch, approach, invariants, open questions, and which docs
   you'll update. Keep it to about 60 lines on the sonnet tier and 120 above, and don't restate the
   claim or worktree workflow. Don't stop to ask mid-plan — take the recommended option and record it
   under Assumptions; ask only when the choice is irreversible. Present the plan and wait for my
   approval: that's a hard stop, whether or not `ExitPlanMode` is available to you — end this turn
   right after the plan text, without calling `EnterWorktree` or touching a file in the same reply.
   Step 4 starts only once I've approved, as a new message.

4. **Isolate the work in a worktree.** Worktree isolation is a one-time repo setup, normally done: if
   the project context flags it, or `EnterWorktree` refuses, read
   `.claude/skills/plan-todo/todo-planning-reference.md` ("One-time: authorize worktree isolation") first. Otherwise
   don't open that file to check.

   Use `EnterWorktree` with `name: todo/<id>` (e.g. `todo/FOO-1`) — a fresh checkout on its own
   branch, cut from the current HEAD. Then, from inside it and before writing anything, record it on
   the claim so `/finish` can find it, and replace `next`'s guess at the file list with the files the
   plan touches — one call:

   ```
   python3 .claude/todo-lock.py attach <id> path/to/a.js path/to/b.py
   ```

   Everything after this happens inside the worktree, and tests must exercise the worktree's code,
   not the main checkout's. If `next` printed a `verify:` line, run checks with `todo-lock.py
   verify [name]` — it blocks and prints only the verdict. Otherwise: one waiter per build, never a second waiter on the same log, no `sleep N`
   checks. Run the full suite once after the last code edit; after comment or doc edits, only format
   and lint.

   Prefer targeted edits over whole-file rewrites, and keep changes and committed tests to what the
   item asks for, so the diff stays reviewable. Shell hygiene: quote globs (zsh errors on an
   unmatched one) and use the Read and Edit tools rather than `sed -n` and `sed -i`; in a worktree
   avoid heredocs, command substitution and `/tmp` backups unless a step here prescribes one — the
   isolation guard refuses the first two, and a restored backup can clobber real edits. Where a
   `todo-lock.py` call takes a body on stdin (`add`, `append`, `edit`, `seq new`), write it with the
   Write tool and pass `--body-file <path>` (`add-bulk`: `--file`) instead of a heredoc.

5. **Act on the overlap report `attach` printed.** It names any overlap with another active claim,
   and `⚠ HOT-FILE CONFLICT` for a hot/shared file (`hot_files`/`hot_dirs` in
   `.claude/todo-config.json`). On a hot-file overlap, revise the plan or
   flag it to me before writing; if this item logically depends on the other landing first, it
   belongs behind `[BLOCKED: <that-id>]` (`/todo … --blocked-by`) — flag that to me rather than racing
   the prerequisite. `todo-lock.py conflicts <id> <files>` re-runs the check, and `lock <id> <files>`
   replaces the list; keep it current if the plan changes. When the work leaves the planned files, run `lock <id> --add <paths>` (script
   calls from the worktree also record edits as `touched`, and `land` lists what was never locked).
   After the last large edit, if another claim overlaps your files, run `todo-lock.py preflight <id>`:
   a dry-run merge against the base and the other attached branches, naming each conflicting path.

**When the work is done and verified, run `/finish` automatically** — auto-finish is the default,
including for a routine green release. `/finish` commits, lands the branch on local `main` with one
`todo-lock.py land` call, and never pushes (pushing happens only when I ask). Don't duplicate its
steps here.

Stop and surface for my review only for a genuine judgment call:
- test or verification failed, or you skipped / couldn't run verification;
- an unresolved design or scope question, or a decision you weren't sure about;
- an unexpected, surprising, or ambiguous result from the work or its verification;
- the change turned out larger or riskier than the item implied;
- a hot-file or merge-conflict resolution where semantic loss is plausible and reconciling both sides
  is genuinely ambiguous.

When one fires, stop, explain what needs my attention, and let me run `/finish`. When in doubt whether
a result rises to a real judgment call, surface it — but a routine green release is not one. The final
summary, or a stop message before `/finish`, runs about 10 lines at most and leads with the outcome.

Begin at step 1 — **claim before you announce or plan.** Never announce a selection you haven't
already claimed via `todo-lock.py next`.
