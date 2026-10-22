---
description: Split one or more detailed feature requests into segments and file a researched, planned chain per segment (preview first; don't do the work)
argument-hint: <one or more detailed feature descriptions>
disable-model-invocation: true
---

File a researched, planned backlog for the feature request(s) below — not single items. Each
segment of the work gets its own chain: `Research` → `Plan` when research is warranted, otherwise
just `Plan`. The Plan item files the implementation items later; you don't.

<request>
$ARGUMENTS
</request>

The backlog lives in `TODO.local.md`, but `.claude/todo-lock.py` is the only interface — **do not read
or hand-edit the store**. Run this in the primary worktree (your normal main tab), not inside a
`/plan-todo` worktree. Run `todo-lock.py` from the repo root — `cd` back if you moved; a
worktree-isolated session refuses `$(git rev-parse …)`. **Do not do the work**, and write nothing
before step 5's approval.

Everything `/todo` says about investigating, writing only what you verified, routing and body
shape applies to every item filed here. Where this command cites a `/todo` file, read the section
named, not the whole file. The detail this command needs only at filing time — the overview
template, the item bodies, the exact commands — is in
`.claude/skills/todo-expanded/todo-expanded-reference.md`, read at step 6.

1. **Investigate — just enough to segment.** For each part of the request: which files and symbols
   it would touch, which existing pattern (if any) it would follow, and what the current
   implementation looks like at the point it would change. Read a document by the section, not the
   file: find the heading with `grep -n`, then read only that line range.

   Offload source exploration when you'd open 3+ files, or any single one over ~400 lines. Dispatch
   the `todo-scout` agent (read-only, returns `path:line` findings) with the question and where to
   look; add `model: "sonnet"` when the question needs reasoning or spans several documents. One
   scout per segment-sized question, dispatched together, is the usual shape. Keep the judgment
   here: the segmentation, the research calls and the wording are yours.

2. **Segment.** Split the request into segments, each **complete in itself**: a cohesive cluster of
   files and one landable result, so the agent working it stays in those files and becomes the
   expert on that slice rather than being pulled into another's. Prefer disjoint `**Files:**`
   between segments — two segments that edit the same file will be deferred against each other by
   `next`, and usually want to be one segment.

   Decide each boundary with `/todo`'s split/keep signals, applied to segments rather than items:
   `.claude/skills/todo/todo-filing-reference.md` ("One item or several"). A piece nobody would land
   alone is a step inside a segment, not a segment. One segment is a fine answer when the request
   really is one slice; it then gets no Acceptance item (step 6).

   Name each segment with a short kebab-case slug (`search-index`, `results-ui`), and the feature
   as a whole with one too: plan docs go under `docs/plan/<feature>/<segment>/`.

   For each pair of segments, decide whether one must wait for the other. Add a cross-segment gate
   only when the dependent would be **built differently after seeing the other's result** —
   `/todo`'s `--blocked-by` test. Otherwise record what they must agree on (shared types, API
   shapes, DOM or CSS hooks, file formats) as a **contract** in the overview, and leave them
   parallel.

3. **Check for duplicates.** Rank candidates for the feature and for each segment:

   ```
   python3 .claude/todo-lock.py similar "<feature or segment keywords>" --context todo
   ```

   Read the `Project context (todo):` block it prints and act on it — it is this repo's own
   instruction. Exit 70 `crashed (store)` → stop and ask me to run `/repair`. An existing item
   that already covers a segment takes it out of the batch: name that item in the preview instead
   of filing a near-duplicate. If any segment names a hot path the project context lists, run
   `python3 .claude/todo-lock.py files` and handle a hit per
   `.claude/skills/todo/todo-filing-reference.md` ("Overlap with work already in the backlog").

4. **Decide research per segment.** Research is warranted when the segment needs any of:

   - an unfamiliar library, API, protocol or browser feature;
   - best practices that matter here — performance, accessibility, SEO, security;
   - a choice between several viable approaches;
   - doubt about whether the current implementation can carry the feature at all.

   It isn't warranted when the work follows a pattern the repo already has (name the pattern's
   file). Write a one-line reason either way — it goes in the preview and in the item body.

5. **Preview — always, before anything is written.** Show me:

   - the feature slug and the overview path, `docs/plan/<feature>/overview.md`;
   - one row per segment: slug, what it covers (one line), its files, research yes/no with the
     reason, its chain (`Research → Plan` or `Plan`), and any cross-segment gate with its reason;
   - the contracts between segments, one line each;
   - the Acceptance item, when there are two or more segments;
   - any segment dropped as covered by an existing item, with that item's id.

   Then read `python3 .claude/todo-lock.py config show` and look at `doc_dirs`. Ask me with one
   `AskUserQuestion` call:

   - **Segments:** Approve / Adjust (I'll say what to change). On Adjust, revise and preview again.
   - **Only when `doc_dirs` doesn't already list `docs`:** offer to run `config set doc_dirs
     '<existing entries plus "docs">' --commit`, explaining why: without it, `next` treats the plan
     docs each segment writes as ordinary source, so parallel segments that touch their own docs
     count as hard overlaps and get deferred against each other. Plan docs go under `docs/plan/`
     either way; run the change only on my OK.

   File nothing until I approve the segments.

6. **File it.** Read `.claude/skills/todo-expanded/todo-expanded-reference.md` — the whole file;
   every section applies at this step — and `.claude/skills/todo/todo-prompting-guide.md` (the
   common part and the section for each route's model). Then follow the reference's *Filing
   sequence* in order. In outline:

   1. The main working tree must be clean (`git status --porcelain` prints nothing). Every commit
      below refuses a dirty tree with `DIRTY`; if it isn't clean, stop and tell me what's there.
   2. The `doc_dirs` change, if I approved it — with `--commit`, so the config isn't left dirty.
   3. **Ids:** one `python3 .claude/todo-lock.py next-id <FAMILY>` (it only peeks, so number up
      from it yourself). One family for the whole batch — `FEAT` unless I named another.
   4. **Overview:** write `docs/plan/<feature>/overview.md` from the reference's template, naming
      the ids, then commit that one file. It goes in first because the items point at it, and an
      item can be claimed — and its worktree cut from `HEAD` — as soon as the store commit lands.
   5. **Items:** one `add-bulk --commit --file <path>` for the whole batch. Each segment's Plan is
      `"blocked_by"` its Research item; a cross-segment gate is a `"blocked_by"` too. **Never
      `--chain`** — it would serialize every segment into one line. No implementation items: each
      Plan item files its own.
   6. **Acceptance** (two or more segments only): one item that checks the original request end to
      end and files bugs for the gaps. It's in the same batch, `"blocked_by"` the first segment's
      Plan item, then `block <ACC> --blocked-by <every other Plan id> --commit` adds the rest.
   7. `python3 .claude/todo-lock.py doctor` — no dangling, self-blocking or cyclic gates.

   **Route each item** with `/todo`'s four questions and route table (`.claude/skills/todo/SKILL.md`,
   step 3): a Research or Plan item is open by definition, so it lands on `judgment`, or
   `frontier` when the open decision is the architecture itself. Pass it as the item's `"route"`.
   Titles stay under ~70 characters: `<segment>: Research <topic>`, `<segment>: Plan <topic>`,
   `<feature>: Acceptance`.

   If any step reports `DIRTY`, nothing was written by that step — say so, never commit around it.
   A failure partway through is handled as the reference's *When a step fails* says.

7. **Confirm** briefly: the overview path and its commit, each segment's ids in chain order, the
   Acceptance id and its gates, and any segment left to an existing item.
