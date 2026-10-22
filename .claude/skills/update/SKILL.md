---
description: Update claude-todo itself — check for a newer release and install it into this repo
argument-hint: (none) | --check | --ref <tag|branch>
disable-model-invocation: true
---

Update the **claude-todo tooling** (`.claude/todo-lock.py`, the slash commands under
`.claude/skills/` and the `todo-*` agents) in this repo to the latest published release. This does not touch the backlog: `TODO.local.md`, your claims, and
your worktrees all survive an update untouched.

Run this in the **primary worktree**, not inside a `/plan-todo` worktree. Run `todo-lock.py` from
the repo root — `cd` back if you moved; a worktree-isolated session refuses `$(git rev-parse …)`.

1. **See where we stand** (cheap, no network beyond one `git ls-remote`):

   ```
   python3 .claude/todo-lock.py version
   python3 .claude/todo-lock.py check-update --refresh
   ```

   - `UP-TO-DATE …` → say so and stop; there's nothing to install.
   - `CHECK-FAILED …` → relay the reason (offline, or git can't authenticate to the source remote)
     and stop. Don't work around it by hand-copying files.
   - `UPDATE-AVAILABLE <version>` → continue.
   - `SOURCE-UNCONFIRMED <new> (trusted: <old>)` → the committed install stamp names a different
     update source than this machine has used. Nothing was fetched. Show me both URLs and stop.
     **Never pass `--accept-source` yourself**; if I confirm, re-run with it.
   - `MOVED-TAG …` → a release tag points somewhere other than where it did. Relay it and stop.
     There is no override: the source may be compromised.

   If I passed `--check`, stop here and just report the result.

2. **Install it.** Pass `--ref` straight through if I gave one (e.g. `--ref main` to track the
   development branch instead of the latest release tag — a branch can't be signature-checked, so
   that also needs my explicit `--allow-unsigned`):

   ```
   python3 .claude/todo-lock.py update --commit
   ```

   This fetches the release into a temp dir, verifies its signature, and runs its `install.sh` against this repo, so it is
   exactly a fresh install — the installer never overwrites `TODO.local.md` or
   `.claude/settings.json`. `--commit` then commits exactly the files the install manages (and any
   it removed) plus the version stamp, under the git mutex — nothing else in the tree.

   Before installing, it prints `Verified <tag> → commit <sha> (signed by …)`. Include the sha
   in your summary.

3. **Handle the outcomes:**
   - **`UNVERIFIED — …`** → the release's signature can't be checked against this install's
     `.claude/todo-release-signers`. Possible causes: an unsigned or foreign-signed tag, a branch
     `--ref`, or no key installed. Nothing was installed. Relay the reason and stop.
     **Never add `--allow-unsigned` yourself**; only I decide that.
   - **`SOURCE-UNCONFIRMED` / `MOVED-TAG`** → as in step 1.
   - **`ERROR — uncommitted local changes to files this update overwrites`** → show me the listed
     files. They're local edits to the tool or a slash command that a reinstall would discard. Ask
     whether to commit them, stash them, or overwrite with `update --force`. **Don't pick for me.**
   - **Items in progress** (the command notes them) → fine; their worktrees are untouched and the
     new commands apply on the next run. Mention it, don't block on it.
   - **`UPDATED <old> → <new>`** → relay the "What changed" CHANGELOG section it printed, in your
     own words if it's long. This is the part I actually want.
   - **`warning: <path> is now shadowed by claude-todo's /<name> skill`** → a command of mine in
     `.claude/commands/` has a shipped skill's name, so `/<name>` now runs the skill. Name it and
     suggest renaming it. A **`note: … left from an older claude-todo install`** names a leftover
     command file: mention it; deleting it is my call.
   - **`warning: overwriting .claude/skills/<name>/…` or `.claude/agents/…`** → a file of mine had
     the same name as a new shipped one. Name it; its committed version is in git history.
   - **`removed <path>`** → a file the previous release shipped and this one dropped. Mention it.

4. **The commit.** `COMMITTED <hash> Update claude-todo to …` → done. **`ERROR — the update is
   installed but its commit failed`** → show me the reason and stop; don't commit by hand with
   `git add -A`.

Finish with one line: old version → new version, and whether the commit landed. If anything in
step 3 needs a decision from me, stop there and ask instead of guessing.
