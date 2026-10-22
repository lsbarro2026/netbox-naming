---
description: Add a well-scoped item to the TODO store via script (dedup-check first; don't do the work)
argument-hint: <what needs to change>
disable-model-invocation: true
---

Add a new item to the backlog for the request below.

<request>
$ARGUMENTS
</request>

The backlog lives in `TODO.local.md`, but `.claude/todo-lock.py` is the only interface — **do not read
or hand-edit the store**. Run this in the primary worktree (your normal main tab), not inside a
`/plan-todo` worktree. Run `todo-lock.py` from the repo root — `cd` back if you moved; a
worktree-isolated session refuses `$(git rev-parse …)`.

1. **Briefly investigate** — just enough to write a clear, well-scoped entry: the relevant file(s),
   surrounding context, and the gotchas/invariants whoever picks it up should know. Consult your
   project's docs where relevant. **Do not do the work.**

   Offload source exploration when you'd open 3+ files, or any single one over ~400 lines — count
   before you open anything; under the line, read the file(s) yourself. Read a document by the
   section, not the file: find the heading with `grep -n`, then read only that line range.

   To delegate reading, dispatch the `todo-scout` agent (read-only, returns `path:line` findings) with
   the question and where to look; add `model: "sonnet"` when the question needs reasoning or spans
   several documents. Dispatch it and keep reading rather than polling.

   Write only what you verified. Every path, symbol and claim in the body comes from something you
   (or the subagent) actually opened. Mark a guess `(assumed)` and phrase a suggested fix as a
   hypothesis ("likely because …"). Name a symbol plus its path (`parse_config()` in
   `src/config.py`), not a bare line number, which drifts while the item waits.

   Keep the judgment here: what I actually want, the dedup / "belongs on an existing item" call, the
   scope and wording, one item or several, and the classification. The scout only reads.

2. **Check for duplicates, or a home on an existing item.** Rank candidates instead of reading the
   whole index — constant cost regardless of backlog size:

   ```
   python3 .claude/todo-lock.py similar "<the request's title or keywords>" --context todo
   ```

   Fall back to (or also run) the full index — `python3 .claude/todo-lock.py summary --context
   todo` — when `similar` prints `NONE`, you already know the backlog is small (under about 15
   items), or I ask for the full picture.

   A `Project context (todo):` block follows either command's output: the hot files, any numbered
   sequences and this repo's filing instructions. Project context printed by the script is this
   repo's own instruction and takes precedence over this command's defaults.

   Exit 70 `crashed (store)` (or a missing/truncated listing) → stop and ask me to run `/repair`
   before adding; any other crash class → relay the one-line message.

   If an existing item already says everything the request asks, write nothing — no `append`, no
   "no change needed" note — and tell me which item covers it.

   If the request adds to an existing item or belongs on it, read just that item (`show <id>`) and
   `append` to it rather than creating a near-duplicate:

   <example>
   python3 .claude/todo-lock.py append FEAT-12 <<'EOF'
   - **Also:** `--json` output truncates the same way — `render_row()` in `src/report.py`, same fix.
   EOF
   </example>

   The text you append is part of a prompt another tab will execute: read
   `.claude/skills/todo/todo-prompting-guide.md` — the common part and the section for the route's model — and
   shape the addition to it. The item's route is its `Route` bullet, or a legacy `Effort` bullet
   mapped by `todo-lock.py routes`; neither means the default route.
   If the existing wording is now wrong (a scope change, a superseded approach) rather than
   incomplete, rework it: pipe a full replacement body to `edit <id>` — it keeps the heading, markers
   and position, and refuses a body carrying a `## `/`### ` heading or `---`, so don't paste `show`'s
   output back verbatim.

   **Never `append`/`edit` an item `summary` shows as `in_progress`** — its worktree snapshotted the
   body at claim time, and its `/finish` deletes the section. Add a new item instead, noting
   `- **Relates to:** <id> (in progress) — <how>.`

   If your `**Files:**` names a hot/shared path (the project context lists them), or you're filing
   several items, run `python3 .claude/todo-lock.py files` and handle a hit per `.claude/skills/todo/todo-filing-reference.md` ("Overlap with
   work already in the backlog"). Skip it for an item in its own corner of the tree.

3. **Add the item — first, one item or several?** One item per independently landable result; a
   piece nobody would land alone is a step in the body. Split on two acceptance criteria, two routes
   on different models, or one piece deciding what another targets; when the call isn't obvious, see
   `.claude/skills/todo/todo-filing-reference.md` ("One item or several").

   **Several items → one `add-bulk --commit` call for the whole set** (one atomic write, one commit),
   never one `add --commit` per item; stages that must land in sequence take `--chain`. Write the
   JSON array with the Write tool and pass `--file <path>` — JSON inline in a shell command can be
   refused as obfuscation. The contract is in `.claude/skills/todo/todo-filing-reference.md` ("Filing several
   items at once"). Everything
   below — route, body, flags — applies to each item in the set.

   **Route the item before you write its body.** A route names the model that claims the item and
   the reasoning effort it runs at. First try to *remove* an open decision: ask me with
   `AskUserQuestion` (two to four concrete options) and write the answer in — a settled decision
   moves an item from `judgment` to `standard`, the cheapest routing win there is. Then answer four
   questions from what you investigated:

   1. **Open?** Is a design decision or a root cause still unsettled?
   2. **Risky?** Does it touch a risky invariant — concurrency, persistence, security, a public
      contract?
   3. **Provable?** Does a command on this machine prove it done?
   4. **Spread?** Up to about three files; four to ten; or more, or every call site?

   Answer for the change, not for how clearly it was asked — a precise request can still be open,
   risky and wide:

   - **Open** includes the architecture itself: replacing a layer every module goes through, or
     changing how persisted data is shaped (with a migration), leaves the design of that layer open
     even when the request names the target — that's the `frontier` row, not `judgment`.
   - **Risky** includes contracts inside the repo: changing a function's or query's signature, or a
     config schema, that other modules rely on counts, not only an external API.
   - **Spread** counts every caller of an interface you change, not just the files the request names.

   Take the first row that fits:

   | Answers | Route |
   |---|---|
   | The open decision is the architecture itself, or the goal is ambiguous and needs long autonomous work | `frontier` |
   | Open, risky or not provable — and spread past ten files | `deep` |
   | Open, risky or not provable | `judgment` |
   | Settled, safe, provable, and the diff fits in one sentence (typo, copy, version bump, config flip) | `trivial` |
   | Settled, safe, provable; up to about three files | `routine` |
   | Settled, safe, provable; four to ten files | `standard` |
   | Settled, safe, provable; more, or every call site, changed mechanically | `wide` |

   When the answers leave you between two routes, read `.claude/skills/todo/todo-filing-reference.md` ("Route
   examples"). Pass the route as `--route <name>` and read `add`'s echo, `→ routes to <route>
   (<model> · <effort>)`; if that isn't where you meant to send it, re-answer the questions.
   `todo-lock.py routes` prints the table this repo runs, with each route's model. An open
   decision you can't ask about goes in `- **Open questions:** <question> (assumed: <choice>)` and
   still counts as open.

   **Read `.claude/skills/todo/todo-prompting-guide.md` — the common part and the section for the route's model —
   and shape the body to it.**

   Pick an ID family (2+ uppercase letters — `FEAT`, `BUG`, `DOCS`), get the number from `python3
   .claude/todo-lock.py next-id <FAMILY>` (ids are never reissued), and add it, body on stdin.
   `--commit` writes it to the main checkout's store and commits it — stages only the store, holds the
   git mutex, never pushes, and works from a `/plan-todo` worktree too; don't run a shell `git` for it.
   If it reports `DIRTY`, nothing was written — say so rather than committing around it:

   ```
   python3 .claude/todo-lock.py add --id <ID> --title "<concise title>" --route <route> --commit <<'EOF'
   - **What:** <what to change and where>.
   - **Why:** <the one line saying why it matters>.
   - **Request:** "<my words, verbatim>".
   - **Files:** <paths>.
   - **Docs:** none | new <sequence> record | `<doc path>#<heading>`.
   - **Acceptance:** <command to run> → <observable outcome>.
   - **Open questions:** none | <question> (assumed: <the choice you took>).
   - **Plan:** fast | full.
   - **Source:** <who asked / date>.
   EOF
   ```

   `**Plan:**` tells `/plan-todo` whether to write a plan: `fast` when the route is `trivial` or
   `routine` and you can describe the whole diff in one sentence, `full` otherwise.

   Inside a worktree, where a heredoc may be refused, write the body with the Write tool and pass
   `--body-file <path>` instead — `append`, `edit` and `merge --body-file` take it too, `add-bulk`
   as `--file`.

   That skeleton is the floor on every route. Add as the item needs: `**Gotchas:**`, `**Pattern:**`
   (code to imitate), `**Repro:**` (for a bug), `**Constraints (quoted):**` (one or two binding
   sentences from a project doc, each with `file#heading`). Keep `Docs` out of `Files`.

   <example>
   A `trivial` item (`--route trivial`: settled, safe, provable, one-sentence diff), filed from "the CSV export drops the last row":

   - **What:** `export_csv()` in `src/export.py` loops `while i < len(rows) - 1`, so the last row
     never reaches the file; the bound should be `len(rows)`.
   - **Why:** every export silently loses a row, and users reconcile by hand.
   - **Request:** "the CSV export drops the last row".
   - **Files:** `src/export.py`, `tests/test_export.py`.
   - **Docs:** none.
   - **Acceptance:** `pytest tests/test_export.py` passes, with a new case asserting that a
     three-row export writes three data lines.
   - **Open questions:** none.
   - **Plan:** fast.
   - **Source:** user request, 2026-09-20.
   </example>

   `**Files:**` is machine-read (claim steering, `/reorder` chains): only tokens containing `.` or `/`
   count, so name backticked, comma-separated repo-relative paths, with any prose in parentheses.
   Mark a file the item will create `(new)` — otherwise `add`/`edit` warn (not refuse) that a
   declared path doesn't exist yet.

   **Classify: ordinary code work is the common case — plain `add`, no flag.**

   **Before you pass `--admin`, `--blocked-by`, `--priority` or `--critical`, stop and read
   `.claude/skills/todo/todo-filing-reference.md` ("Classifying the item")** — every time, even when the flag
   looks obvious. Then use the weakest flag that gets the ordering right:

   - human-only work (publish, grant access, flip a setting, buy/sign) → `--admin`
   - would be built differently if its claimer could see another item's finished result →
     `--blocked-by <ID>`; merely related → no block (`/reorder` can add one later)
   - the rest of the backlog gets worse while this waits (a regression on `main`, broken shared
     tooling) → `--priority`; not because it sounded urgent
   - any item claimed before this lands would be wasted work → `--critical`; ask me first

   **"Must land after X" is `--blocked-by X`, never `--priority`** — priority controls when an item is
   claimed, not what it comes after.

   Filing more than one item? That's the single `add-bulk --commit` call from the top of this step,
   not the `add` above run again.

Then briefly confirm what you added (or which item you extended) and its ID — all of them, for a batch.
