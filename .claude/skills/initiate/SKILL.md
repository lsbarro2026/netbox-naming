---
description: Find this repo's numbered artifact series (ADRs, RFCs, migrations) and register them for `seq`
argument-hint: (none) | <path-to-a-numbered-directory>
disable-model-invocation: true
---

Set this repo up for **numbered sequences** — the `seq` command group hands out collision-free
numbers for ADRs, RFCs, migrations and the like, but only for series listed in the `sequences` map
of `.claude/todo-config.json`. This command finds what the repo already has, registers what I pick,
and proves it works. If I passed a `<path>`, skip detection and register **that** directory.

Registering only records **where entries live**. It must never renumber, move, rewrite or reformat
an existing entry — a series that predates this command keeps every filename it has.

Run this in the **primary worktree**, not inside a `/plan-todo` worktree: the config is read from
the main tree. Run `todo-lock.py` from the repo root — `cd` back if you moved; a worktree-isolated
session refuses `$(git rev-parse …)`.

1. **Detect.** Scans the files git knows about (so `.gitignore` prunes it) for directories whose
   filenames share a numbered shape:

   ```
   python3 .claude/todo-lock.py seq detect                 # no argument: scan the repo
   python3 .claude/todo-lock.py seq detect --path <path>   # I named a directory: just that one
   ```

   One TSV line per series — `<name> <dir> <pattern> <count> <example> <new|registered>`. Anything
   already in the config is listed first, marked `registered`; the rest are `new` guesses inferred
   from filenames. `NONE …` (exit 1) means the repo has neither: go to step 6.

2. **Offer them to me.** Render the `new` candidates as a short numbered list and ask which to
   register — `none` is a valid answer, and stops here without writing anything:

   ```
   Found 2 candidate numbered series:
     1. docs/adr/       4 files matching {n:04d}-{slug}.md    -> adr
     2. db/migrations/  3 files matching {n:04d}_{slug}.sql   -> migration
   Register which? [1,2,none]
   ```

   The name is the key I'll type in `seq new <name>` / `seq list <name>` — offer to change it if I
   want a different one. Report anything marked `registered` as already set up and don't re-offer
   it. With `--path` there's one candidate; still confirm the name and pattern before writing.

3. **Settle each accepted sequence's settings before writing anything.**

   **Map an existing metadata convention; don't impose one.** `seq` reads `summary`, `scope`
   (path globs), `tags`, `amends` and `supersedes` from front-matter or `Field: value` lines. Read
   the first ~20 lines of two or three entries (`head -n 20 <file>`). If they already carry
   front-matter or field lines that mean the same thing under other names (`covers:` for scope,
   say), map just the keys that differ with `--field scope=covers` (one flag per key) in step 4.
   Report any keys that have no counterpart and leave them alone. Never add fields to existing
   entries. Use `--status-field <field>` only if the entries track status under something other
   than `Status`, and `--template <path>` only if the repo already has a template file for the
   series.

   **Offer an index — but only if the series already has one.** Look for a hand-maintained index
   beside the entries (a `README.md` / `index.md` in the series directory, or a table elsewhere that
   lists every entry). If there is one, tell me it's the one file in a numbered series that parallel
   worktrees *do* conflict on — every entry appends a row at the same end — and offer to let `land`
   own it, regenerating the rows on `main` the way it already owns the version and CHANGELOG. If I
   accept, pass `--index-file <path-to-the-index>` in step 4, and `--row "<row template>"` read off
   the existing rows so regenerated rows look like the ones already there. The tokens are:
   - `{n}`: the raw number.
   - `{npad}`: the number as `pattern` renders it, e.g. `0089`.
   - `{path}`: the entry path relative to the index file.
   - `{file}`: the basename.
   - `{title}`, `{status}`, `{summary}`, `{scope}`, `{amends}`, `{superseded_by}`.

   Omit `--row` to accept the default, `| [{npad}]({path}) | {title} | {status} |`. If the series
   has **no** index, don't invent one: skip it and say so.

4. **Register it — merged into `.claude/todo-config.json`, never overwriting it.** That file may
   already hold `hot_files`, `version_source`, `update_check` or other sequences. `seq register`
   adds this one entry and keeps every other key, the key order and the file's indent. It refuses a
   name already registered differently. `--commit` commits only the config, under the git mutex.
   Once per sequence I accepted:

   ```
   python3 .claude/todo-lock.py seq register <name> --dir <dir> --pattern "<pattern>" [--field <key>=<name> …] [--index-file <path> --row "<row>"] --commit
   ```

   Then show me the resulting file so I can see the other keys survived. With an index, fill it:

   ```
   python3 .claude/todo-lock.py seq index <name>
   ```

   That adds the `<!-- BEGIN todo-lock: <name> index -->` … `<!-- END … -->` markers and fills them
   with a row per entry on disk. **Show me the result and delete the old hand-written rows it now
   duplicates** — the command deliberately leaves them, since only I can tell prose from a stale row.
   Everything outside the markers is untouched, so the file's heading and prose survive.

5. **Confirm it works.** The registered sequence must see the pre-existing entries immediately:

   ```
   python3 .claude/todo-lock.py seq list           # the configured sequences
   python3 .claude/todo-lock.py seq list <name>    # every entry on disk, with status + title
   ```

   If `seq list <name>` prints nothing while the directory has files, the `pattern` doesn't match
   them — fix the pattern (compare against the `<example>` column from step 1), don't rename files.

6. **Nothing found? Offer to bootstrap one.** `/initiate` should be useful on day one of a repo,
   not only on one that already has a series. Ask whether to create a sequence from scratch and
   what kind — defaulting to ADRs at `docs/adr` with `{n:04d}-{slug}.md`. If I accept:

   - Register it first (step 4's `seq register … --commit`) — `seq new` requires the sequence to
     exist.
   - Then create entry `0001`; `seq new` makes the directory itself and reserves the number under
     the claim-state flock:

     ```
     python3 .claude/todo-lock.py seq new adr --title "Record architecture decisions" <<'EOF'
     We need to record the architectural decisions made on this project, so the reasoning
     behind them survives the people who made them.
     EOF
     ```

   - The default template renders `Status: Proposed`; for this entry set it to `Accepted` — it
     records a decision already in force. Fill in its `## Decision` and `## Consequences`
     (we will use ADRs, as described by Michael Nygard; one file per decision, numbered).

7. **Commit the rest.** Step 4's `--commit` already committed the config. Two cases leave files
   uncommitted: an index filled in step 4 and a bootstrapped entry. For those, commit exactly those
   paths, under the git mutex (no push; that's `/sync`):

   ```
   python3 .claude/todo-lock.py git-mutex -- git commit -q -m "Add <name> index and first entry" -- <index-file> <entry-file>
   ```

   With neither, there is nothing left to commit.

Finish with one line per registered sequence — name, directory, pattern, and how many existing
entries `seq list` can now see — plus a pointer that `seq new <name> --title "…"` is how new ones
get made from here.
