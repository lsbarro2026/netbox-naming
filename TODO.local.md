# TODO

## Admin

## Open

### FEAT-17 — /publish-internal: publish a clean snapshot to the TRIUMF GitLab
- **What:** Add a user-invoked `/publish-internal` skill that cuts the current `main` HEAD into one squashed snapshot commit with all AI tooling and references removed, and pushes it to `git@gitlab.triumf.ca:ist/net/netbox-naming.git`. Also add a short user-facing `README.md`.
  - **Remote:** `origin` is already GitHub (`https://github.com/lsbarro2026/netbox-naming.git`), so register the GitLab URL under a separate remote name, `internal` (assumed), on first run. Never touch `origin`.
  - **Snapshot shape (decided by user):** each publish adds one new commit on GitLab `main` whose parent is the current `internal/main` tip (or no parent on the first publish). Build it without a checkout: a temporary `GIT_INDEX_FILE`, `git read-tree HEAD`, `git rm --cached -r` the excluded paths, `git write-tree`, then `git commit-tree`. Author and committer are the user's normal git identity. The message is plain, e.g. `Release <version>` with the version taken from `pyproject.toml`. No `Co-Authored-By`, no "Generated with", no Claude/Anthropic text. Tag it `v<version>` (assumed) and push the commit and the tag to `internal`.
  - **Exclude from the tree:** `.claude/` (skills, agents, `todo-lock.py`, config), `CLAUDE.md`, `TODO.local.md`, `docs/plan/` (AI planning and research notes; assumed internal-only, since they mention Claude and use em-dashes).
  - **Guard, abort before pushing on any hit:** (a) any excluded path still in the tree; (b) a case-insensitive match of `claude|anthropic|co-authored-by|generated with|/plan-todo|/todo` anywhere in the tree's file contents or the commit message; (c) an em-dash (U+2014) in any published `*.md`. Print the offending path and line.
  - **`--dry-run`:** build the tree, run the guard, list the files that would publish, and push nothing.
- **Why:** the team needs the plugin on TRIUMF GitLab without AI tooling, AI attribution or AI-flavoured docs.
- **Request:** "Please establish a '/publish-internal' command that cuts the current state and releases it to a gitlab repository. The gitlab repoisitory is at: orgin: 'git@gitlab.triumf.ca:ist/net/netbox-naming.git' When you push, please make sure the push does NOT include any AI documentation or references. The user facing documentation should be concice, and clear. It should NOt include any em-dashes. There should be NO ai attribution in the push."
- **Files:** `.claude/skills/publish-internal/SKILL.md` (new), `.claude/publish-internal.py` (new), `README.md` (new), `.gitignore`.
- **Docs:** `README.md` (new): short and plain. What the plugin does, install (`pip install`), enable in `PLUGINS`, a minimal usage note, links to `COMPATIBILITY.md` and `dev/README.md`. No em-dashes, no AI mentions.
- **Pattern:** frontmatter like `.claude/skills/sync/SKILL.md` (`disable-model-invocation: true`, `argument-hint`). Running `/publish-internal` is the user's go-ahead to push, the same way `/sync` is. The skill runs the script with `--dry-run`, shows the file list, then runs it for real.
- **Gotchas:**
  - `.gitignore` has a comment mentioning `/plan-todo` worktrees, which trips guard (b). Reword it neutrally (e.g. "Throwaway git worktrees") and keep the `.claude/worktrees/` rule.
  - The templates under `netbox_naming/templates/` use `—` as the empty-cell placeholder (e.g. `name_inventory.html`, `inc/proposal_cell.html`). That is UI, not documentation, so the em-dash check covers `*.md` only. Leave the templates alone.
  - Do not create the commit with `git commit` in the main checkout. That fires the session's attribution rules and changes local `main`. `commit-tree` keeps GitHub `main` unchanged.
  - Fetch `internal` first so the parent is the real remote tip. If `internal/main` has commits that aren't ours (someone pushed directly), stop and report rather than force-push.
  - Refuse to run with a dirty tree or off `main`, because the snapshot is `HEAD`.
- **Acceptance:** `python3 .claude/publish-internal.py --dry-run` exits 0 and lists files, with no `.claude/`, `CLAUDE.md`, `TODO.local.md` or `docs/plan/` among them. Temporarily adding the word `Claude` to `README.md` makes it exit non-zero and name the file. `grep -c $'—' README.md COMPATIBILITY.md dev/README.md` prints 0 for each.
- **Out of scope:** rewriting GitHub history; removing trailers from past GitHub commits; changing the template placeholder em-dashes; CI on GitLab; publishing to PyPI.
- **Open questions:** remote name `internal` and tag `v<version>` (assumed). Whether `docs/plan/` should ever publish (assumed: no). The first real push to GitLab is outward-facing, so the implementer verifies with `--dry-run` only and leaves the first real run to the user.
- **Plan:** full.
- **Source:** user request via /todo, 2026-11-10.
- **Route:** judgment
