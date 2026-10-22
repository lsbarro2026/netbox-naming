# `/plan-todo` and `/finish` — reference material, loaded on demand

`.claude/skills/plan-todo/SKILL.md` and `.claude/skills/finish/SKILL.md` point here, each time
gated on a condition stated before the pointer. Read only the section you were sent to; the others
are unrelated.

## Reserving a sequence number

You're here because the repo configures `sequences` in `.claude/todo-config.json` (ADRs, RFCs,
migrations — `todo-lock.py seq list` with no name shows them) and this item will add an entry to one.
Get the number while planning, before you write a single reference to it. Unlike the version number,
it does not wait for `/finish`: reserve it against your claim, from the main checkout, and it's fixed
for the rest of the item:

```
python3 .claude/todo-lock.py seq reserve <name> --claim <id>   # prints e.g. `adr-89  0089`
```

The second field is the number as the sequence's filename pattern renders it — use that form in prose
and paths, don't re-derive the padding. `--claim <id>` makes the reservation ride your claim (freed by
`release`/`land`) even though the worktree doesn't exist yet. Then, in the worktree, write the entry
with that exact number — `seq new` is the write path, and `--number` uses what you reserved instead of
taking a fresh one:

```
python3 .claude/todo-lock.py seq new <name> --number <n> --title "…" <<'EOF'
…body…
EOF
```

Where a heredoc is refused (inside a worktree), write the body with the Write tool and pass
`--body-file <path>` instead — the same flag `add`, `append`, `edit` and `merge` take.

Don't hand-edit a sequence index or generated table row on your branch: `land` regenerates them from
their source files on `main`, and two branches appending to the same table is the conflict it exists to remove.

## Release bookkeeping

You're here because the repo opts into release bookkeeping: `.claude/todo-config.json` has a
`version_source`, and usually a `changelog` (see the CONFIG section in `todo-lock.py`). Without
`version_source` there is none — `reserve-version` errors by design and `land` only removes the TODO
item. A non-release change (tooling, docs-only, process) skips all of this regardless.

**While planning**, record only the SemVer tier — **major** = breaking, **minor** = new
feature/enhancement, **patch** = bug fix — and "version bump + CHANGELOG entry (deferred to
`/finish`)" as a planned step. Don't read the current version or compute the next one: a number picked
now can go stale or collide with a parallel release that lands first.

**At `/finish`**, get the number from the tool — never pick it by hand. Write the `CHANGELOG.md`
entry heading on this branch as `## {VERSION}` and pass the tier to the one-call finish:

```
python3 .claude/todo-lock.py finish <id> -m "<subject>" --tier <major|minor|patch>
```

It reserves the number (atomic under the claim flock, idempotent per claim, so a retry gets the same
one), replaces the placeholder, and commits it with the rest; a placeholder without `--tier` is
refused. `reserve-version <id> --tier …` still prints the number on its own. Don't edit the version
source itself — `land` writes it on `main` after the merge (max-wins, so out-of-order landings never
roll it back), so release branches never touch that line and two parallel releases can't conflict on
it. An abandoned reservation never burns a version: releasing the claim reclaims it.

## Spinning off work

You're here because, while planning or implementing item **X**, you noticed work that isn't X: an
out-of-scope bug, or a missing asset you shouldn't produce inline (a new icon). Handle it by filing,
not by multitasking.

- **File every out-of-scope bug, without asking.** Filing is a safe, non-destructive `add`, so nothing
  you notice gets silently dropped. A bug inside X's scope you just fix, and don't file.
- **Filing goes through the `todo-filer` agent**, to save your context: dispatch it with the
  description (what it is, `file:line`, why it's separate), its route, and whether to add
  `--priority` (only when X waits on it). You pick the route, not the filer: you hold the context,
  so answer `/todo`'s four route questions yourself and name the route in the brief. The filer runs
  a short filing path of its own, ending in `add --route <route> --commit`, and replies with the
  new item's id alone; a reply that doesn't match `^[A-Z]{2,}-[0-9]+$` (it says `FAILED: …`) goes
  to the user. A one-line triviality you may file directly. Dispatch and carry on; the id arrives
  on its own.
- **`--commit` is what makes this work from a worktree.** It writes the item to the main checkout's
  store and commits it there under the git mutex, so it lands on `main`, claimable by other tabs and
  never riding your branch — no `cd` to the shared checkout and no shell `git`, both refused in a
  worktree-isolated session:

  ```
  python3 .claude/todo-lock.py add --id <ID> --title "…" --route <route> --commit <<'EOF'
  - **What:** …
  EOF
  ```

  If it reports `DIRTY`, the main checkout holds someone else's uncommitted work and nothing was
  written — surface that to the user rather than working around it.

### Deciding whether to wait for a spun-off item

Filing captures the work; waiting is a separate decision about whether you can proceed without it.

- **X is independent of B → don't wait** (the default). An unrelated bug, or an asset you can stand
  in with a placeholder (drop a pseudo-icon now and say in B's body that B replaces it): file B and
  keep working. B lands on `main` via another tab, and `land`'s main→branch fold pulls it in. Prefer a
  placeholder over waiting whenever a stand-in is viable.
- **X genuinely can't proceed without B → wait.** B is a bug that must be fixed for your work to be
  correct, or an asset you truly need and can't stub. File B with `--priority`, then run `python3
  .claude/todo-lock.py wait <B> &` (background Bash — the harness re-triggers you when it exits; or a
  long foreground `timeout`). On `DONE`, `git merge main` into the worktree to pull B in, then resume
  X. **Deadlock caveat:** a priority item is only picked up by *another* free `/plan-todo` tab — if
  this is the only tab, tell the user "filed B (`<id>`), waiting — start another /plan-todo tab to
  pick it up" so the wait isn't blocking forever unseen (`wait` also heartbeats).
- **X is hopelessly entangled with B →** don't hold a stalled worktree. Mark X `[BLOCKED: B]`
  (`todo-lock.py block X --blocked-by B`), `todo-lock.py release X`, tear down the worktree, and
  stop — a fresh tab reclaims X from clean `main` after B lands.

## One-time: authorize worktree isolation

**Worktree isolation must be authorized in your repo (one-time setup).** `/plan-todo` and `/finish`
use `EnterWorktree`, which needs a project sign-off plus a base-ref setting. If this repo isn't set
up yet, do that first (see the package README) — the two pieces are:

- `.claude/settings.json` sets the base ref to the local HEAD, so worktrees branch from the local
  `main` tip (which includes just-committed items and `/finish` merge-backs), not `origin/main`:

  ```json
  { "worktree": { "baseRef": "head" } }
  ```

- The repo's `CLAUDE.md` carries a line authorizing worktree use for claimed TODO items, e.g.:

  > **Worktree isolation (authorized here).** `/plan-todo` works in a git worktree per item (via
  > `EnterWorktree`). Using a worktree for a claimed TODO item is expected, not something to ask
  > about each time.

  That instruction is the sign-off `EnterWorktree` requires.
