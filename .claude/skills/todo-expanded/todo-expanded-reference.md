# `/todo-expanded` — reference material, loaded at filing time

`.claude/skills/todo-expanded/SKILL.md` sends you here at step 6, once I've approved the preview.
Every section applies to that step. Placeholders: `<feature>` and `<segment>` are the kebab-case
slugs from the preview, `<FEAT-n>` the ids you numbered from `next-id`.

## Filing sequence

Run these from the repo root of the **main checkout**, in this order:

```
git status --porcelain                                    # must print nothing
python3 .claude/todo-lock.py config set doc_dirs '["docs"]' --commit   # only on my OK; merge existing entries
python3 .claude/todo-lock.py next-id FEAT                 # e.g. FEAT-20; number the batch up from it
# write docs/plan/<feature>/overview.md (template below), then commit just that file:
python3 .claude/todo-lock.py git-mutex -- git add -- docs/plan/<feature>/overview.md
python3 .claude/todo-lock.py git-mutex -- git commit -q -m "Add plan overview: <feature>" -- docs/plan/<feature>/overview.md
python3 .claude/todo-lock.py add-bulk --commit --file <scratch>/batch.json
python3 .claude/todo-lock.py block <ACC-id> --blocked-by <other Plan ids…> --commit   # 2+ segments only
python3 .claude/todo-lock.py doctor
```

Why this order and these tools:

- **The overview commits first, on its own.** Every `--commit` refuses (`DIRTY`) while the main
  tree has a change outside the store — an uncommitted `overview.md` included. And the moment the
  store commit lands, another tab can claim a Research item and cut its worktree from `HEAD`; the
  overview has to be there already. Commit it with the two `git-mutex` calls above, which serialize
  against a parallel `/finish`. The store is never committed with a shell `git` — only through the
  script's `--commit`.
- **Write the batch JSON outside the working tree** (your scratchpad, or the system temp dir) — a
  file inside it is an untracked change, and `add-bulk --commit` would refuse with `DIRTY`. Write it
  with the Write tool; inline JSON in a shell command can be refused.
- **Number ids explicitly.** `next-id` only peeks at the counter; the ids aren't taken until
  `add-bulk` writes them. Give every item its own `"id"`, because a `"blocked_by"` that points
  forward within the batch needs one, and so does the overview, which names them before they exist.
- **`"blocked_by"` takes one id per item.** An item that needs two gates (the Acceptance item, or a
  segment's first item that waits on two other segments) gets one in the batch and the rest from
  `block <id> --blocked-by <B2> [B3 …] --commit` straight after. Put the first gate in the batch, so
  the item is never claimable between the two commits.
- **No `--chain`.** It links every item to the one before it, which would serialize all the
  segments into one line. Chain within a segment with per-item `"blocked_by"`.

A two-segment batch — `search-index` with research, `results-ui` without — with `next-id` at
`FEAT-20`:

```json
[
  {"id": "FEAT-20", "title": "search-index: Research incremental indexing",
   "route": "judgment", "body": "<Research body>"},
  {"id": "FEAT-21", "title": "search-index: Plan incremental indexing",
   "route": "judgment", "blocked_by": "FEAT-20", "body": "<Plan body>"},
  {"id": "FEAT-22", "title": "results-ui: Plan result list and filters",
   "route": "judgment", "body": "<Plan body>"},
  {"id": "FEAT-23", "title": "site-search: Acceptance",
   "route": "judgment", "blocked_by": "FEAT-21", "body": "<Acceptance body>"}
]
```

followed by `block FEAT-23 --blocked-by FEAT-22 --commit`. A cross-segment gate goes on the
dependent segment's **first** item (its Research item, or its Plan item when it has none), pointing
at the other segment's Plan item.

## When a step fails

- **`DIRTY`** anywhere: that step wrote nothing. Tell me what's dirty; never commit around it.
- **The overview commit fails:** stop before `add-bulk` — nothing is in the store yet.
- **`add-bulk` fails:** it validates the whole batch first, so nothing was written. Fix the JSON
  and re-run it. The overview commit stands; that's harmless, but say so in the confirmation.
- **`block` fails** (a cycle, a typo'd id): the Acceptance item is still gated on the first Plan
  item, so nothing can claim it early. Report it and the command that would add the rest.
- **`doctor` reports a dangling or cyclic gate:** report it as printed; don't hand-edit the store.

## `overview.md` template

The segment-level map every item in the batch reads first. Keep it to what the segments must
share, not a plan for each — that's each Plan item's job.

```markdown
# <Feature title> — plan overview

Filed by `/todo-expanded` on <date>. Each segment's research and plan live in
`docs/plan/<feature>/<segment>/`. These docs stay after the work lands; they're never deleted.

## Request

<the original request, verbatim>

## Segments

| Segment | Covers | Files | Chain | Research |
|---|---|---|---|---|
| `<segment>` | <one line> | `<paths>` | <FEAT-20> → <FEAT-21> | yes — <reason> |
| `<segment>` | <one line> | `<paths>` | <FEAT-22> | no — follows `<pattern file>` |

Acceptance: <FEAT-23>, gated on every segment's Plan item, then on each segment's last
implementation item.

## Contracts

What the segments must agree on. A segment changes a contract only by stopping and raising it
(see below), never on its own.

- **<name>** — <shape: type, API signature, DOM hook, CSS class, file format>. Produced by
  `<segment>`, consumed by `<segment>`.

## Dependency order

<Which segment waits on which, and why it would be built differently otherwise. "None — the
segments run in parallel" is a fine answer.>

## Re-segmentation

If research or planning shows this split is wrong — segments should merge or split, a new one is
needed, or a contract above must change — the item that finds it writes it up in its own doc and
stops for the user before filing anything. It does not re-cut other segments itself.
```

## Item bodies

These are prompts for later `/plan-todo` tabs: shape each per
`.claude/skills/todo/todo-prompting-guide.md`. Every body keeps `/todo`'s skeleton (`**What:**`,
`**Why:**`, `**Request:**`, `**Files:**`, `**Docs:**`, `**Acceptance:**`, `**Open questions:**`,
`**Plan:**`, `**Source:**`). Fill the angle brackets from what you investigated — real paths and
symbols, with `(assumed)` on anything you didn't open. `**Request:**` quotes the part of my request
the segment covers; the overview holds the whole. `**Files:**` lists only what the item **writes**,
so a Research or Plan item names its doc, and the source it studies goes in `**What:**`.

### Research item

```
- **What:** Research segment `<segment>` of `<feature>` before it is planned. (1) Survey the
  current implementation: <paths + symbols from investigation>, and how it would have to change to
  carry <the segment's goal>. (2) Research externally — WebSearch/WebFetch, citing every source with
  its URL and date — the technical side (<the unfamiliar library/API/feature>) and the code best
  practices that matter here (<performance / accessibility / SEO / security, as applicable>).
  (3) Write `docs/plan/<feature>/<segment>/research.md` with these sections: Question · Current
  implementation · Findings (cited) · Options · **Verdict: Extend / Refactor-then-extend /
  Replace**, with the evidence for it · Risks · Open questions for the plan.
- **Why:** research is warranted because <the one-line reason from the preview>.
- **Request:** "<the part of the request this segment covers>".
- **Files:** `docs/plan/<feature>/<segment>/research.md` (new).
- **Docs:** `docs/plan/<feature>/overview.md` (segment map and contracts — read first).
- **Acceptance:** research.md has every section above; the verdict names one of the three options
  and cites the evidence; every external claim carries a URL and date.
- **Re-segmentation stop:** if the research shows the segmentation is wrong (segments should merge
  or split, a new one is needed, or a contract in overview.md must change), write it up in
  research.md and stop and surface it to the user before filing anything. Don't re-cut other
  segments.
- **Out of scope:** any code change; plan.md (the Plan item, <FEAT-21>, writes it); filing items.
  Docs-only deliverable — not a release.
- **Open questions:** none.
- **Plan:** full.
- **Source:** /todo-expanded, <date>.
```

### Plan item

```
- **What:** Plan segment `<segment>` of `<feature>`. Read `docs/plan/<feature>/<segment>/research.md`
  [segment without research: open plan.md with a short current-state survey of <paths + symbols>
  and give the Extend / Refactor-then-extend / Replace verdict yourself, with a reason]. Confirm the
  verdict or override it with a reason. Write `docs/plan/<feature>/<segment>/plan.md` with: Status
  (Draft → Approved → Implemented) · Decision · Design · Contracts (pointing at overview.md, not
  restating it) · Test strategy · Implementation breakdown (one entry per implementation item:
  scope, files, route, acceptance) · Deviations (empty). Your `/plan-todo` plan-mode plan is an
  outline of plan.md with the verdict up front, so my approval of it is the sign-off on extend vs
  replace; set Status to Approved when I approve.
- **ADR:** a Replace verdict, or any architecture decision, also gets an ADR — only if
  `python3 .claude/todo-lock.py seq list` shows an `adr` sequence: reserve it with `seq reserve adr
  --claim <this id>` (`.claude/skills/plan-todo/todo-planning-reference.md`, "Reserving a sequence
  number"). Without one, the decision lives in plan.md's Decision section.
- **Filing the implementation items** (from this item's worktree, after plan.md is written): one
  `python3 .claude/todo-lock.py add-bulk --chain --commit --file <path>` call, the JSON written
  with the Write tool. The first item is `"blocked_by"` this Plan item (legal while it's in
  progress; the gate clears when it lands). Route each item honestly with `/todo`'s table, and give
  each `- **Docs:** docs/plan/<feature>/<segment>/plan.md#<its breakdown section>`. Each
  implementation body says: plan.md is binding; any departure is recorded under its Deviations
  section; the last item sets Status to Implemented; the plan docs stay in place and are never
  deleted or archived.
- **Re-gate Acceptance** [2+ segments only]: after filing them, run `python3 .claude/todo-lock.py
  block <ACC-id> --blocked-by <last implementation id> --commit`, before `/finish`. `block` refuses
  a claimed item, but <ACC-id> can't be claimed: it's gated on this Plan item until this lands.
- **Why:** <one line: what this segment delivers, and why it's planned before it's built>.
- **Request:** "<the part of the request this segment covers>".
- **Files:** `docs/plan/<feature>/<segment>/plan.md` (new).
- **Docs:** `docs/plan/<feature>/overview.md`, `docs/plan/<feature>/<segment>/research.md`.
- **Acceptance:** plan.md has every section above with Status Approved; `todo-lock.py summary`
  shows the implementation chain, its first item gated on this one; [2+ segments]
  `todo-lock.py show <ACC-id>` shows it blocked on the chain's last item.
- **Re-segmentation stop:** if planning shows the segmentation is wrong (segments should merge or
  split, a new one is needed, or a contract in overview.md must change), write it up in plan.md and
  stop and surface it to the user before filing anything. Don't re-cut other segments.
- **Out of scope:** writing the implementation itself; other segments' docs and items.
- **Open questions:** none.
- **Plan:** full.
- **Source:** /todo-expanded, <date>.
```

### Acceptance item

Only when there are two or more segments.

```
- **What:** Check `<feature>` end to end against the original request in
  `docs/plan/<feature>/overview.md` ("Request"), once every segment has landed. Turn each clause of
  the request into an observable check; run the test suite, then exercise the feature in the
  running app. Write the results to `docs/plan/<feature>/acceptance.md`: each check, pass/fail, and
  the evidence. File every gap as its own bug through `/plan-todo`'s spin-off protocol
  (`.claude/skills/plan-todo/todo-planning-reference.md`, "Spinning off work"), not fixed inline.
- **Why:** each segment was verified against its own plan; this checks that together they deliver
  what was asked.
- **Request:** "<the request's headline sentence>".
- **Files:** `docs/plan/<feature>/acceptance.md` (new).
- **Docs:** `docs/plan/<feature>/overview.md`, every `docs/plan/<feature>/*/plan.md`.
- **Gate:** blocked on every segment's Plan item at filing; each Plan item re-gates this onto its
  last implementation item, so it's claimable only once all of them have landed.
- **Acceptance:** acceptance.md lists one check per request clause with its result; every failing
  check has a filed bug id next to it.
- **Out of scope:** fixing the gaps it finds; changing any plan.md.
- **Open questions:** none.
- **Plan:** full.
- **Source:** /todo-expanded, <date>.
```
