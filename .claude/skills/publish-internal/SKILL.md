---
description: Publish a clean snapshot of main to the TRIUMF GitLab (no AI tooling or attribution)
argument-hint: (no args)
disable-model-invocation: true
---

Publish the current `main` HEAD to `git@gitlab.triumf.ca:ist/net/netbox-naming.git` (remote
`internal`) as one squashed `Release <version>` commit tagged `v<version>`. Running
`/publish-internal` **is** your go-ahead to push to `internal`. Never touch `origin`, and never
create the commit yourself: `.claude/publish-internal.py` builds it with `git commit-tree`, so local
`main` and GitHub stay unchanged and no attribution trailer is added.

The script drops `.claude/`, `CLAUDE.md`, `TODO.local.md` and `docs/plan/` from the tree, then
refuses to push if any of them remain, if any file or the message matches
`claude|anthropic|co-authored-by|generated with|/plan-todo|/todo` (case-insensitive), or if a
published `*.md` contains an em-dash.

Run from the **primary checkout** on clean `main`, not inside a worktree.

1. **Dry run.** `python3 .claude/publish-internal.py --dry-run`. Show me the file count and any
   file outside `netbox_naming/`, `dev/` and the top-level docs. A guard failure prints
   `path:line: text` for each hit: stop and show me those lines. Don't edit the files to get past
   it unless I ask.
2. **Publish.** `python3 .claude/publish-internal.py`. It adds the `internal` remote on first use.
3. **Outcomes:**
   - **Published** → relay the `Published v<version> …` line.
   - **`v<version>` already exists** → the version in `pyproject.toml` (and
     `netbox_naming/__init__.py`) needs a bump. Tell me; don't bump it yourself.
   - **`internal/main` tip is not a release tag** → someone pushed to GitLab directly. Stop and
     tell me. Never force-push.
   - **Tree identical to `internal/main`** → nothing changed since the last publish. Tell me.
   - **Dirty tree or not on `main`** → stop and tell me which.
   - **SSH or permission error from GitLab** → relay it; I'll fix access.
