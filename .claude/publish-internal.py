#!/usr/bin/env python3
"""Publish a clean snapshot of HEAD to the internal GitLab remote.

Builds a tree from HEAD without the excluded paths, guards it against tooling
references, and pushes one squashed commit (parent: the remote tip) plus a
v<version> tag. --dry-run builds and guards only; it never contacts a remote.
"""

import os
import re
import subprocess
import sys
import tempfile
import tomllib

REMOTE = "internal"
URL = "git@gitlab.triumf.ca:ist/net/netbox-naming.git"
EXCLUDE = [".claude", "CLAUDE.md", "TODO.local.md", "docs/plan"]
BANNED = r"claude|anthropic|co-authored-by|generated with|/plan-todo|/todo"
EM_DASH = "—"


def git(*args, env=None, check=True):
    r = subprocess.run(["git", *args], check=False, capture_output=True, text=True, env=env)
    if check and r.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed:\n{r.stderr.strip()}")
    return r


def fail(msg):
    sys.exit(f"ABORT: {msg}")


def build_tree():
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": os.path.join(tmp, "index")}
        git("read-tree", "HEAD", env=env)
        git("rm", "--cached", "-r", "-q", "--ignore-unmatch", "--", *EXCLUDE, env=env)
        return git("write-tree", env=env).stdout.strip()


def guard(tree, message):
    """Return offending 'path:line: text' hits; empty means safe to publish."""
    files = git("ls-tree", "-r", "--name-only", tree).stdout.splitlines()
    hits = [
        f"{f}: excluded path"
        for f in files
        if any(f == e or f.startswith(e + "/") for e in EXCLUDE)
    ]
    hits += [f"{f}: banned word in path" for f in files if re.search(BANNED, f, re.IGNORECASE)]
    if re.search(BANNED, message, re.IGNORECASE):
        hits.append(f"commit message: {message}")
    # git grep exits 1 on no match; strip the leading "<tree>:" from each hit.
    for args in (["-I", "-n", "-i", "-E", BANNED, tree], ["-n", "-F", EM_DASH, tree, "--", "*.md"]):
        out = git("grep", *args, check=False).stdout
        hits += [line.split(":", 1)[1] for line in out.splitlines()]
    return files, hits


def remote_state():
    """(tip sha or None, {tag name: commit sha}) for the internal remote."""
    url = git("remote", "get-url", REMOTE, check=False)
    if url.returncode != 0:
        git("remote", "add", REMOTE, URL)
    elif url.stdout.strip() != URL:
        fail(f"remote '{REMOTE}' points at {url.stdout.strip()}, expected {URL}")
    out = git("ls-remote", REMOTE, "refs/heads/main", "refs/tags/v*").stdout
    tip, tags = None, {}
    for line in out.splitlines():
        sha, ref = line.split("\t")
        if ref == "refs/heads/main":
            tip = sha
        elif ref.startswith("refs/tags/"):
            # A peeled "^{}" line (annotated tag) overrides the tag object's sha.
            tags[ref[len("refs/tags/") :].removesuffix("^{}")] = sha
    return tip, tags


def main():
    dry = "--dry-run" in sys.argv[1:]
    if set(sys.argv[1:]) - {"--dry-run"}:
        sys.exit("usage: publish-internal.py [--dry-run]")
    os.chdir(git("rev-parse", "--show-toplevel").stdout.strip())

    with open("pyproject.toml", "rb") as f:
        version = tomllib.load(f)["project"]["version"]
    tag, message = f"v{version}", f"Release {version}"

    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    dirty = git("status", "--porcelain").stdout.strip()
    problems = ([f"on '{branch}', not main"] if branch != "main" else []) + (
        ["working tree is dirty"] if dirty else []
    )
    if problems and not dry:
        fail("; ".join(problems) + " (the snapshot is HEAD)")
    for p in problems:
        print(f"warning: {p}; a real run would refuse")

    tree = build_tree()
    files, hits = guard(tree, message)
    if hits:
        print("Guard failed, nothing pushed:", *hits, sep="\n  ", file=sys.stderr)
        sys.exit(1)

    if dry:
        print(*files, sep="\n")
        print(f"\n{len(files)} files; would push '{message}' as {tag} to {REMOTE} ({URL})")
        return

    tip, tags = remote_state()
    if tag in tags:
        fail(f"{tag} already exists on {REMOTE}; bump the version in pyproject.toml")
    if tip and tip not in tags.values():
        fail(f"{REMOTE}/main tip {tip[:12]} is not a release tag; someone pushed directly")
    parent = []
    if tip:
        git("fetch", "-q", REMOTE, "main")
        parent = ["-p", tip]
        if git("rev-parse", f"{tip}^{{tree}}").stdout.strip() == tree:
            fail(f"tree is identical to {REMOTE}/main; nothing to publish")
    sha = git("commit-tree", tree, *parent, "-m", message).stdout.strip()
    git("push", "--atomic", REMOTE, f"{sha}:refs/heads/main", f"{sha}:refs/tags/{tag}")
    print(f"Published {tag} ({sha[:12]}) to {REMOTE}/main: {len(files)} files")


if __name__ == "__main__":
    main()
