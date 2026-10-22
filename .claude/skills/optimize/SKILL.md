---
description: Audit why this project's TODO workflow is slow or expensive, and propose overlay or config fixes (applies nothing without approval)
argument-hint: (optional) "no sessions" to skip reading local session transcripts
disable-model-invocation: true
---

Find out why work in this repo feels slow or expensive, using the script's own data, and propose
fixes. `.claude/todo-lock.py` is the only interface to the backlog — **never read or hand-edit
`TODO.local.md`**. Run this in the primary worktree (your normal main tab), not inside a
`/plan-todo` worktree. Run `todo-lock.py` from the repo root — `cd` back if you moved; a
worktree-isolated session refuses `$(git rev-parse …)`.

Ground rules, for the whole command:

- **Read-only until I approve each change.** Report first; write nothing while auditing.
- **You write only two things, and only through the script:** the project overlay
  (`todo-lock.py context set <command> --body-file <path> --commit`) and `.claude/todo-config.json`
  (`todo-lock.py config set|unset <key> … --commit`). Never edit a shipped file —
  `.claude/todo-lock.py`, the `.claude/skills/<command>/` files it installed (`SKILL.md`,
  `todo-*.md`), `.claude/agents/todo-*.md` — since `/update` overwrites them. Anything else (settings.json permissions
  or hooks, splitting a document, CLAUDE.md edits) is proposed as a diff for me to apply, marked
  **outside /optimize's write scope**.
- **Nothing leaves the machine.** Use no web tools and send no item titles or bodies anywhere; the
  audit prints ids and sizes only, and so does your report.
- **Don't change behaviour from one project's data** beyond this repo's overlay and config.

1. **Check the overlay exists.** Run `python3 .claude/todo-lock.py context plan-todo --full`. If it
   fails as an unknown command (an install older than the project overlay), stop and tell me to run
   `/update` first — every fix this command proposes goes through the overlay or config.

2. **Gather the evidence — one call.** Run `python3 .claude/todo-lock.py audit --sessions` (plain
   `audit` if I passed "no sessions"). Each `FINDING <check> <subject>: <evidence>` line is a lead;
   `INPUTS` is the state as it stands (config keys, overlay files, store, telemetry,
   worktree_setup, session token totals). `todo-lock.py stats` adds per-route detail if a `route`
   or `declared-files` finding needs it. Don't open transcripts yourself; the audit has read them.

3. **Look only where a finding points,** by section, never whole files:
   - `long-doc` → `todo-lock.py docs show <path> --outline`; judge whether it is a current-state
     document amended in place (dated amendment sections, "update:" notes) or a reference that is
     long by nature.
   - `hook-candidate` → read the named CLAUDE.md line; a rule is a hook candidate only if it names a
     deterministic action at a deterministic moment (format before commit, never run X). Most
     matches are prose — drop those silently.
   - `phantom-overlap` → `todo-lock.py files` shows how both items declare the path.
   - Duplicated rationale is not in the audit: for each flagged long doc, `grep -n` two or three of
     its distinctive phrases across the repo's other docs and CLAUDE.md, and report a hit only when
     the same reasoning appears in both.
   - `no-verify` with a `verify-in-memory` finding → the memory note names the recipe to move into
     config; read that note only.
   - Cold builds: when `verify` is configured but `worktree_setup` is unset, ask me whether a fresh
     worktree's first build is slow — the audit can't time it.

4. **Report.** Findings first, most costly first, each with its evidence (the audit line, and what
   you read). Then numbered proposals, each one exactly one of:
   - a `config set` / `config unset` command with its JSON value — e.g. `doc_dirs` for a phantom
     overlap, `verify.commands` for a missing or memory-only recipe, `worktree_setup` for cold
     builds, `routing` for a route that bounces or over-serves;
   - an overlay change: the full new text of `.claude/local-todo/<command>.md` (first line
     `schema: 1`, at most 1,200 bytes, merged with what `context <command> --full` printed), for a
     project instruction an agent keeps missing — e.g. "don't open `<archive>`";
   - a diff outside the write scope, marked so, for me to apply: a DOC-10 split (a short
     current-state document plus an archive of the dated amendments that the overlay tells agents
     not to open), a settings.json allow rule or hook, a CLAUDE.md trim.
   With no findings, say so in one line and stop.

5. **Apply what I approve, one change at a time,** with `--commit` so each lands on main as its own
   commit; relay each `OK …` line. Skip anything I decline. Suggest re-running `/optimize` or
   `todo-lock.py stats --since <today>` after a few items, since a change is judged by re-measuring
   — cost savings that lower quality aren't savings.
