---
description: Detect the project's toolchain and set agents up for it — verify commands, worktree setup, permissions, hooks, shell notes
argument-hint: (none)
disable-model-invocation: true
---

Set this repo up so agents stop rediscovering its toolchain every session. The script detects;
you run what it found, and write only what I confirm.

**Write only what Claude can't guess and would get wrong:** the real commands with their flags,
non-default conventions, environment quirks. Never standard language conventions, tutorials, or
file-by-file descriptions — those cost context on every turn and change nothing.

Run this in the **primary worktree**, not inside a `/plan-todo` worktree: everything it writes
lives in the main checkout. Run `todo-lock.py` from the repo root — `cd` back if you moved; a
worktree-isolated session refuses `$(git rev-parse …)`. Every writer below merges and prints `OK
<file> unchanged` when there is nothing new, so running `/stack` again is safe. Where a step takes
a body, write it with the Write tool to a scratch file outside the repo and pass its path.

1. **Detect.**

   ```
   python3 .claude/todo-lock.py stack detect
   ```

   One TSV line each: `platform`, `language <lang> <pm> <dir>`, `monorepo <why>`, candidates
   `<kind> <command> [<exts>] <source>` (kinds test, lint, build, format, setup — CI workflow
   lines first, they're what the project really runs), `include <path>`, `protect <dir>/`,
   `caveat <name>`, and `configured <what's already set up>`. A line ending `= configured` is
   already recorded — skip it. `NONE …` (exit 1) → tell me there's no toolchain to set up and stop.

   Show me a compact summary: languages, then each unconfigured candidate with its source.

2. **Run every candidate before recording it.** One at a time, from the repo root, with a Bash
   timeout (10 minutes at most). Record a command only if it ran: it passed, or it failed on the
   project's own tests or lint findings rather than on a missing tool or bad flag. Tell me which
   is which. A test that fails and then passes on a rerun is a `flaky` candidate. Don't run `format`
   (it rewrites files) or `setup` here; those are tried in steps 5 and 4.

3. **Verify commands.** Propose the block — `test`, and `lint`/`build` where found; a single-test
   form as `test_one` with `{target}` when the runner takes one (`go test ./... -run {target}`,
   `pytest {target}`); `notes` for environment quirks the runs revealed (a service that must be up,
   an env var). On my yes:

   ```
   python3 .claude/todo-lock.py stack config verify --json-file <path> --commit
   ```

   A refusal naming `--replace` means a command of that name already exists with another recipe:
   show me both and pass `--replace` only if I pick the new one.

4. **Worktree setup.** Each item starts in a fresh worktree. Propose `worktree_setup` from the
   `setup` lines (joined with `&&`), plus anything the verified commands needed that a fresh
   checkout lacks. Run it once in a scratch `git worktree` if I ask; otherwise say it's untested.
   On my yes: `stack config worktree_setup --value "<line>" --commit`. For `include` paths, propose
   them for `.worktreeinclude` (Claude Code copies those gitignored files into every worktree), one
   path per line: `stack block .worktreeinclude --body-file <path> --commit`.

5. **Permissions and hooks** — one `stack settings … --commit` call with what I accept:
   - `--allow "Bash(<command>)"` for each verified command, so they run without a prompt.
   - `--deny "Edit(<dir>/**)"` for each `protect` directory I confirm is generated or migration
     history that is never hand-edited.
   - `--store-guard`: denies Read/Edit/Write of `TODO.local.md` (the script is the only interface).
     Mention that it must be switched off while `/repair` runs.
   - `--format-hook "<format command>" --ext <exts>` from a `format` line, so every edit is
     formatted. Only if the formatter ran cleanly on one file just now (try it on a file you then
     restore with `git checkout -- <file>` if it changed anything).

6. **Notes for `/plan-todo`** — the project overlay, printed with every claim. Propose short lines
   for the platform, then write them with:

   ```
   python3 .claude/todo-lock.py context set plan-todo --section stack --body-file <path> --commit
   ```

   - Shell hygiene, for this `platform`: under `shell=zsh`, quote globs (`--include='*.go'`; an
     unmatched glob is an error); with `sed=bsd`, `sed` has no `\b` and `-i` needs an argument —
     prefer the Read and Edit tools over `sed -n` and `sed -i`; no `/tmp` backups inside a worktree.
   - `caveat python-editable`: the project is installed in editable mode from the main checkout, so
     a bare test run in a worktree imports main's code, not the item's. Add a line saying how to
     point the run at the worktree for this project (e.g. `PYTHONPATH=. python3 -m pytest`, or run
     through `uv run`/the verify command, which runs from the worktree root) — check it works.
   - Any other stack-specific worktree caveat the runs revealed (a dev server bound to the main
     tree, a build cache path). The overlay is capped at 1,200 bytes; keep each line to one fact.

7. **CLAUDE.md** — a short block, between markers, for sessions outside the TODO workflow: the
   verified commands (one line each) and quirks from step 6 that apply to any session. Nothing the
   repo's own files already say. Show it to me, then:

   ```
   python3 .claude/todo-lock.py stack block CLAUDE.md --body-file <path> --commit
   ```

Finish with one line per thing written (file, what, committed sha) and one line for anything
skipped and why. A run that found everything `= configured` writes nothing and says so.
