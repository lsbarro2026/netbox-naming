# Writing an item body for the model that runs it

`/todo` loads this file for every item it files or extends. Read the common part, then only the
section for the model the item's route runs on (`todo-lock.py routes` prints each route's model).

The body you're about to write is a **prompt**. A `/plan-todo` tab claims this item later, is handed
that body verbatim, and works from it — usually without reopening the request that produced it. So
the body's job is to be complete and to say where the work stops.

## Common to every route

**Ship a complete spec up front.** Write the body so the later tab needs nothing else: what changes
and where, every file involved, the invariants it must not break, the gotchas you found while
investigating, and what "done" looks like. A terse pointer the agent has to reconstruct — "fix the
import wizard" — wastes the model on rediscovery, and it rediscovers *differently* than you did.
Prefer:

- real repo-relative paths, naming the symbol rather than a bare line number (`parse_config()` in
  `src/config.py`) — line numbers drift while the item waits;
- the constraint stated, not implied ("the `- **Files:**` bullet is machine-read by `next`" beats
  "be careful with the format");
- acceptance criteria as observable outcomes — the command that should pass, the output that should
  appear — not as a description of effort;
- only what you verified: every path, symbol and claim comes from something you opened, a guess is
  marked **`(assumed)`**, and a suggested fix is phrased as a hypothesis ("likely because …"). A
  wrong premise stated as fact costs the implementer more than no premise at all.

**Say where this item stops.** Don't paste a generic scope paragraph into the body — `next` prints
the claiming route's scope boundary when it hands the item out. Write only what is specific to this
item: an `**Out of scope:**` bullet naming the adjacent things it does not touch (the neighbouring
module you noticed, the refactor that would be nice but isn't this). One such line is worth more
than a paragraph of description.

**Written deliverables** (the docs `/finish` has the agent update): "Match the length of written
documents to what the task needs: cover the substance, but do not pad with filler sections,
redundant summaries, or boilerplate."

**Review passes:** if the item asks the agent to review or audit something, ask for *everything* and
filter separately. Never write "only report high-severity issues" or "be conservative" — the model
follows that literally and under-reports.

### The format contract still binds

The shaping in this file wraps the body's existing contract; it never displaces or rewords it.

- **`- **Files:** …` stays a machine-read list of real paths.** `next` parses it to steer parallel
  tabs toward conflict-free work and to seed the claim's file list, and `/reorder` chains on it.
  Only tokens containing a `.` or `/` count, so keep concrete repo-relative paths there and put
  explanatory prose in parentheses around them. Scope prose belongs in its own bullet, not inside
  this one.
- **Never hand-write the `- **Route:**` (or legacy `- **Effort:**`) bullet.** `add` writes it from
  `--route`, `merge` from `--effort`, and `set-effort <id> <route>` changes it.
- Keep `/todo`'s base skeleton — `**What:**`, `**Why:**`, `**Request:**`, `**Files:**`,
  `**Docs:**`, `**Acceptance:**`, `**Open questions:**`, `**Plan:**`, `**Source:**` — and add
  `**Invariants:**`, `**Out of scope:**`, `**Gotchas:**`, `**Pattern:**`, `**Repro:**` and
  `**Constraints (quoted):**` as the item needs.

## Sonnet routes

Sonnet follows instructions literally: it does not generalise an instruction from one case to
another, and it does not infer requests you didn't make. So state the scope of every instruction —
"rename it at every call site in `src/` and `tests/`", not "rename it (e.g. in `src/app.py`)". Name
each case the change covers rather than one example, and give Acceptance one observable outcome per
behaviour, so nothing left unstated is left undone.

## Opus routes

Opus runs a long way on a thin spec and, left unbounded, tends to run *further* than asked — the
`**Out of scope:**` bullet matters most here.

- **No verification scaffolding.** Never write "add a final verification step", "double-check your
  work", "re-read the diff" or "use a subagent to verify": Opus already self-verifies, and these buy
  no quality and cost real tokens. The acceptance outcome is the specification to aim at.
- **Cap delegation if you mention it at all.** An unqualified mention of subagents invites a fleet.
  If the item genuinely warrants delegation, cap it in the same breath: "Delegate only for large,
  genuinely independent, parallelizable tracks; don't delegate what you can finish in a handful of
  tool calls; don't use subagents to verify your own work; prefer one agent over several." Otherwise
  don't raise the subject.

## Fable routes

Fable finishes long tasks with little methodology, and tends to deliver more than asked: nearby
fixes, extended behaviour, extra committed test files. Name what to leave out — the adjacent bug
that is a follow-up, the behaviour the item doesn't extend — and say which tests the change warrants
(or that none beyond the existing suite do). Don't add lines that hold back its progress updates:
Fable already writes fewer of them, and its guide says to remove such instructions.

## Worked examples

A bug, routed `judgment`:

<example>
- **What:** `parse_config()` in `src/config.py` silently drops unknown keys, so a typo in a user's
  config file surfaces as a missing-feature bug hours later. Make it collect unknown keys and raise
  `ConfigError` listing all of them at once (not the first), with the offending file and line.
- **Why:** three support reports this quarter traced back to a misspelled key that parsed cleanly.
- **Request:** "a typo in my config just gets ignored — it should tell me".
- **Repro:** put `retires = 3` (for `retries`) in `examples/app.toml` and run `app --config
  examples/app.toml`; it starts with retries at the default and prints nothing.
- **Files:** `src/config.py` (the parser), `src/errors.py` (`ConfigError` lives here),
  `tests/test_config.py` (parser tests).
- **Docs:** none — the behaviour is already documented as strict in `docs/config.md#unknown-keys`.
- **Invariants:** `parse_config()` is called during startup before logging is configured — it must
  not log, only raise. The `strict=False` caller in `src/cli.py` (`main()`) must keep its current
  permissive behaviour; thread the flag rather than changing the default.
- **Acceptance:** a config with two unknown keys raises one `ConfigError` naming both; the
  `strict=False` path still returns a parsed config; `pytest tests/test_config.py` passes.
- **Open questions:** none.
- **Out of scope:** the schema-validation rewrite discussed in `docs/config.md` — this item only
  changes unknown-key handling. Don't touch the YAML loader.
- **Plan:** full.
- **Source:** user request, 2026-07-31.
</example>

A refactor whose deliverable is partly documentation, routed `judgment`:

<example>
- **What:** the retry logic is duplicated in `fetch_page()` (`src/http.py`) and `fetch_batch()`
  (`src/batch.py`), which have drifted — the second lost jitter. Extract one `with_retries()` helper
  into `src/retry.py` and call it from both.
- **Why:** the two copies already disagree, so a fix to one silently leaves the other wrong.
- **Request:** "please dedupe the retry code before we add a third caller".
- **Pattern:** `with_timeout()` in `src/timeout.py` — same decorator shape, same keyword-only
  options; imitate it rather than inventing a new signature.
- **Files:** `src/retry.py` (new), `src/http.py`, `src/batch.py`, `tests/test_retry.py` (new).
- **Docs:** update `docs/reliability.md#retries`, which still describes two separate policies.
- **Constraints (quoted):** "Backoff is capped at 30s and always jittered; unjittered retries have
  caused thundering-herd outages twice" (`docs/reliability.md#retries`).
- **Invariants:** `fetch_page()`'s public signature is used by plugins and must not change. Jitter
  is required on both paths — restoring it in `fetch_batch()` is the point, not a side effect
  (assumed: the batch path was meant to jitter; the commit that dropped it has no rationale).
- **Acceptance:** `pytest tests/` passes with a new test asserting both callers jitter and cap at
  30s; `rg "sleep\(" src/http.py src/batch.py` returns nothing.
- **Open questions:** whether `fetch_batch()` should keep its lower max-attempts (assumed: yes —
  preserve each caller's current attempt count, change only where the backoff comes from).
- **Out of scope:** the connection-pool rewrite in `src/http.py`; the CLI's own retry flag.
- **Plan:** full.
- **Source:** user request, 2026-08-04.
</example>

Note what the examples do *not* contain: no "verify your work at the end", no subagent instructions,
no generic scope paragraph, no padding.
