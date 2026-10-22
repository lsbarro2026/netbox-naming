#!/usr/bin/env python3
# Built from src/todo-lock/ by tools/build.py in the claude-todo repo — edit the fragments there, not this file.
"""TODO store + claim lock for a repo's backlog. The **only** interface to `TODO.local.md`.

Agents must not read `TODO.local.md` directly — that (potentially long) file is the store, and reading it
whole is pure wasted tokens. Everything goes through this script, which prints only what's asked
for: one item, or a one-line-per-item summary. `help <subcommand>` prints just that entry (this
whole docstring, printed by a bare `help`/`--help`, is ~8k tokens). Two layers:

The store has two sections: `## Admin` (human tasks — never auto-claimed) and `## Open` (work
agents pick up). A blocked Open item links to its gate via `[BLOCKED: <id>]` — the gate is an Admin
task (cleared by admin-done) or another Open item (cleared when that item is `remove`d at /finish).

STORE (reads/writes the markdown file — each `### <ID> — <title>` section is one item):
  todo-lock.py summary [--status <s>] [--context <command>]
                                        one line per item: <id> <status> <title>  (cheap)
                                        status ∈ admin | blocked | in_progress | critical | priority | open
                                        --status lists only items of that status (no grep needed)
                                        --context appends that command's project context (see
                                        PROJECT CONTEXT) — how /todo reads it in the same call
  todo-lock.py similar "<keywords or title>" [--context <command>]
                                        constant-cost duplicate check: stdlib token-overlap ranking
                                        over each item's title, `- **What:**` bullet and declared
                                        `- **Files:**` paths (lowercased, stop-words dropped, path
                                        tokens weighted higher) against the query. Prints the top few
                                        candidates as `summary` lines with a trailing `score=<n>`, or
                                        `NONE …` (exit 1) when nothing scores or the query has no
                                        usable keywords. --context is the same one-call convenience
                                        as `summary --context`. Use `summary` instead for the full
                                        picture on a small backlog or by request.
  todo-lock.py summary-by-model         read-only glance at what's claimable right now, grouped by
                                        the model each item's route names (same routing `next
                                        --model` claims by), one `<id> <status> <route> <title>`
                                        line per item, trailed by an `== in_progress ==`
                                        section listing claimed items with their worktree. Claims
                                        nothing — used by /summary.
  todo-lock.py summary-by-route         read-only: for each route with claimable work, the count,
                                        the first three ids and the exact command that launches a
                                        tab for it (`claude --model M --effort E "/plan-todo E"`),
                                        then the same `== in_progress ==` section. Used by /summary.
  todo-lock.py run [--route <name>] [-n <count>] [--dry-run] [--permission-mode <mode>]
                                        start headless `claude -p "/plan-todo <effort>"` workers,
                                        one per claimable item up to -n (default 1) per route, on
                                        the fast-path routes only (trivial, routine: nobody can
                                        approve a plan); --route narrows to one, and a planning
                                        route is refused with its tab command. Each worker gets the
                                        route's model and effort, CLAUDE_TODO_ROUTE=<route> (which
                                        `next` filters on) and an unattended-worker system prompt,
                                        runs from the main checkout and logs to
                                        <git-common-dir>/claude-todo-run/<route>-<stamp>-<n>.log;
                                        one `started … pid … → <log>` line each. Prints the
                                        permission mode first (default auto). --dry-run prints each
                                        command and touches nothing. Never claims; nothing to run
                                        → `NONE …`, exit 1
  todo-lock.py routes                print the routing table (see ROUTING below): each route's
                                        model, recommended reasoning effort and legacy Effort band,
                                        the default route, each model's match strings and the
                                        unknown-model policy — built-in or from config. Read-only.
  todo-lock.py show <id> [--brief]      print just that item's section (its full body) — the GET
                                        half of the single-item get/set pair (SET is `edit`).
                                        --brief: heading, status, route, declared files and the
                                        first sentence of What (~80 tokens) — enough to judge an
                                        overlap without the whole body
  todo-lock.py files                    one line per Open item: <id> <status> <files> <title>,
                                        where <files> is the item's `- **Files:** …` bullet. Lets
                                        /reorder reason about file overlap without reading bodies.
                                        Documentation paths (under a `doc_dirs` directory, or in the
                                        item's `- **Docs:**` bullet) are marked `[doc: …]`
  todo-lock.py refs <id>                tracked files that name <id> as a whole word, one `path:line:
                                        text` per hit (first 20, then "N more"); never the store or
                                        CHANGELOG.md. Finds forward references — "that is GUI-35's to
                                        decide" in a doc or code comment — before the item finishes.
                                        No hits: `NO REFERENCES …`, exit 0
  todo-lock.py add --id <ID> --title <T> [--admin] [--priority] [--critical] [--blocked-by <BLOCKER-ID>] [--route <ROUTE> | --effort <PCT|TIER>] [--no-inherit] [--body-file <PATH>] [--commit [-m <MSG>]]  body on stdin
                                        --no-inherit: skip the `inherit_bullets` copy from the claimed
                                        item (see CONFIG); a no-op where the key is unset
                                        --body-file: read the body from a file instead of stdin
                                        (`-` is stdin; the file wins over piped stdin). Every
                                        body-taking writer — add, append, edit, merge, seq new —
                                        takes it, and add-bulk takes `--file`; the result is
                                        identical to the same text on stdin. Use it where a heredoc
                                        is refused (inside a worktree): write the body with the
                                        Write tool, pass its path
                                        --priority: claimed by `next` before any non-priority item
                                        --critical: a hard gate, stronger than --priority. While an
                                        unblocked --critical item exists (claimed or not) and hasn't
                                        been finished/removed, `next` refuses every OTHER caller —
                                        even a matching-tier item that would otherwise be claimable —
                                        until this item is claimed and finished (see `next`'s
                                        BLOCKED-BY-CRITICAL outcome). Can't combine with --admin,
                                        --blocked-by, or --priority (redundant — critical already
                                        outranks it)
                                        --blocked-by: gate on an Admin task OR another Open item (the
                                        blocker must exist; a cycle is refused); the dependent is
                                        skipped by `next` until the blocker is completed (admin-done)
                                        or finished (remove), which strips the marker. Allowed on an
                                        Admin task, and together with --priority (which takes effect
                                        once the gate clears)
                                        --route: the named route (see ROUTING / `routes`), written
                                        as a `- **Route:** <name>` body bullet that `next --model`
                                        filters on. Can't combine with --effort
                                        --effort: legacy level of effort as a 0–100 percentage (or
                                        a tier name sonnet|opus|fable, mapped to a representative
                                        %), written as a `- **Effort:** NN%` bullet and routed
                                        through the route bands (≤50 sonnet, ≤90 opus, ≤100 fable
                                        with the built-in table). Omit both ⇒ the default route
                                        (judgment, opus). Every Open add prints
                                        `→ routes to <route> (<model> · <effort>)`
                                        --commit: write the item to the MAIN worktree's store and
                                        COMMIT it there (`Add TODO: <title>`, `-m` to override),
                                        under the git mutex. This is how a tab working in a
                                        worktree spins off out-of-scope work: the item lands on
                                        `main`, claimable by another tab, never riding the caller's
                                        branch — and the commit runs inside this script, so a
                                        worktree-isolated session isn't refused for naming `git`.
                                        Only TODO.local.md is staged; the main tree must be clean
                                        apart from it, or the add is refused with nothing written.
                                        Never pushes. Without --commit, the caller's own store is
                                        written and no git runs, exactly as before
                                        Body and title rules (every writer — add, add-bulk, append,
                                        edit, merge): a body may not hold a `## `/`### `/`---` line
                                        outside a code fence, or leave a ``` / ~~~ fence open; a
                                        title is one line with no [BLOCKED/[CRITICAL]/[PRIORITY]
                                        text (the flags set markers). Refused, nothing written.
                                        Markers are read only right after `<ID> — `. Advisory
                                        only, never refused (add, add-bulk, append, edit): a
                                        `warn: <id> — …` line on stderr for a body over ~3KB, a
                                        title over ~70 characters, or a declared `**Files:**` path
                                        missing from the tree and not marked `(new)`
  todo-lock.py add-bulk [--chain] [--family <FAMILY>] [--no-inherit] [--file <PATH>] [--commit [-m <MSG>]]   JSON array of items on stdin (or in --file)
                                        add MANY items in ONE atomic store write — the batch form
                                        of `add`, for a single request that decomposes into several
                                        items. stdin is a JSON array of objects {"id"?, "title",
                                        "body", "admin"?, "priority"?, "blocked_by"?, "effort"?, "route"?,
                                        "inherit"? (false: skip `inherit_bullets`; --no-inherit
                                        does that for the whole batch)} —
                                        JSON because bodies are multi-line markdown and any
                                        delimiter would collide with body content. Per-item fields
                                        mean exactly what `add`'s flags do.
                                        --family <F> numbers every item that omits "id" as <F>-<n>
                                        off the same monotonic counter `next-id` uses (an explicit
                                        "id" always wins over it).
                                        --chain blocks each item on the one before it, so
                                        /plan-todo hands the batch out in the declared order; a
                                        per-item "priority"/"admin" is refused in that mode (a
                                        blocked item is never auto-claimed, so only the first item
                                        of a chain could ever be either). An item's own
                                        "blocked_by" is kept alongside the chain link.
                                        The WHOLE batch is validated before anything is written —
                                        one bad item writes nothing, exits non-zero and leaves the
                                        store byte-identical. Final file order matches input order.
                                        Prints one `OK added <id>` line per item, each Open one
                                        followed by its `→ <id> routes to …` line.
                                        --commit works as it does on `add`, with the whole batch in
                                        ONE commit (`Add TODOs: …`) — never one per item.
  <writer> … --commit [-m <MSG>]        every other store writer — append, edit, merge, block,
                                        reorder, repair, admin-done, set-effort, set-files — takes
                                        `--commit` too, sharing `add`'s implementation: the MAIN
                                        tree's store is written and committed there (only the
                                        store is staged; a default plain subject, `-m` to
                                        override), under the git mutex, with the same DIRTY
                                        refusal. Works from a linked worktree, where the same
                                        command without it is refused. A run that leaves the store
                                        unchanged commits nothing (`note: … nothing to commit`);
                                        a failed run is never committed, even if it wrote (repair
                                        with MANUAL issues left) — resolve and re-run.
  todo-lock.py append <id> [--body-file <PATH>]
                                        append text (read from stdin) to an existing item;
                                        refuses if <id> is currently claimed (in progress), or
                                        text that breaks the body rules (see `add`)
  todo-lock.py edit <id> [--body-file <PATH>]
                                        replace an item's whole BODY (read from stdin) in place —
                                        the SET half of the get/set pair (GET is `show`). Keeps the
                                        `### <id> — title` heading (so [PRIORITY]/[BLOCKED] markers
                                        and the item's file position survive); only the body swaps.
                                        Refuses if <id> is claimed (like `append`), and refuses a
                                        body that would alter the store's item set (e.g. a pasted-
                                        back `### …` heading), writing nothing
  todo-lock.py merge <survivor> <absorbed> [--title <T>] [--body | --body-file <PATH>] [--effort <ROUTE|PCT|TIER>]
                                        fold <absorbed> into <survivor>: one item survives (keeping
                                        its id, file position and dependents), the other is REMOVED
                                        and its id never reissued. For two items that turn out to be
                                        duplicates or split halves of one task — /reorder proposes
                                        it. Body = the survivor's + a `- **Merged in:** <id> — …`
                                        provenance bullet + the absorbed body, with the two
                                        `**Files:**` bullets joined into one (so the overlap signal
                                        stays visible — only the first is ever read) and
                                        `**Effort:**` reconciled to the MAX of the two, an
                                        undeclared effort counting as the default route's band —
                                        or, once either names a `**Route:**`, one Route bullet
                                        holding the later of the two routes in table order.
                                        Heading: [PRIORITY] if either was, [BLOCKED: …] markers
                                        unioned, priority dropped if any blocker survives (as
                                        `block` does). Items blocked on <absorbed> are RETARGETED
                                        onto <survivor> — the work moved rather than finished, so
                                        they are NOT unblocked the way `remove` unblocks. Refuses
                                        if either id is claimed (same reason `edit` does) or if the
                                        two sit in different sections. --title retitles the
                                        survivor; --body reads the merged body from stdin (or
                                        --body-file from a file) instead of concatenating (guarded
                                        like `edit`), which is how to merge two duplicates into one
                                        clean body. --effort sets the survivor's routing bullet
                                        exactly as `set-effort` does, overriding both the computed
                                        route and any Route/Effort bullet a --body carries
  todo-lock.py set-effort <id> <ROUTE|PCT|TIER>
                                        set one item's routing bullet without a `show`→`edit`
                                        round trip: a route name (checked first) writes
                                        `- **Route:** <name>`, a 0–100 percentage or tier name a
                                        legacy `- **Effort:** NN%`; every other Route/Effort bullet
                                        goes. Prints the `→ routes to …` line. Refuses a claimed
                                        item (like `edit`)
  todo-lock.py set-files <id> <paths...>
                                        replace one item's `- **Files:**` bullet (wrapped
                                        continuation lines included) with `` `a`, `b` ``, or add one
                                        if it has none. The item's declared files, which `next`
                                        seeds a claim from — a claim's own list is `lock`'s.
                                        Refuses a claimed item
  todo-lock.py block <id> --blocked-by <B1> [B2 …]
                                        mark an already-existing item blocked on one or more
                                        existing items (Admin or Open). Repeated single-id markers
                                        ([BLOCKED: A] [BLOCKED: B]); idempotent; drops a [CRITICAL]
                                        marker but keeps [PRIORITY]. Refuses a claimed item
                                        (like `edit`/`append`). `next` lazily
                                        clears each marker once its blocker no longer exists.
                                        Refuses an edge that would make the [BLOCKED] graph cyclic
                                        (the check `add`/`add-bulk`/`reorder` already apply — a
                                        cycle deadlocks `next`), writing nothing.
  todo-lock.py remove <id>              delete an item's section AND unblock its [BLOCKED: <id>]
                                        dependents (called by /finish — a finished item unblocks
                                        anything it gated, mirroring admin-done)
  todo-lock.py admin-done <id>          complete an Admin task: delete it AND unblock its
                                        [BLOCKED: <id>] dependents (called by /admin-task)
  todo-lock.py reorder                  reorder the ## Open section AND set its complete
                                        Open-item→Open-item dependency chain from a JSON plan on
                                        stdin — {"order": [ids…], "blocks": {id: [blocker-ids…]}}
                                        (called by /reorder). `order` sets file order (⇒ the
                                        non-priority claim order in `next`); `blocks` is
                                        authoritative for Open-item gates (each item's Open blockers
                                        become exactly blocks[id]; unmentioned items lose theirs),
                                        while human `[BLOCKED: <ADMIN>]` gates and claimed items are
                                        always preserved. Rejects unknown ids, self-blocks, cycles.
  todo-lock.py next-id <FAMILY>         print the next <FAMILY>-<n> (e.g. next-id TASK -> TASK-4).
                                        A monotonic per-family counter: a number is never reissued
                                        after its item is removed, so a given id names ONE todo for
                                        the life of the repo (the counter lives in the machine-local
                                        claim state; a clone without one seeds it once per family
                                        from git history — store headings and commit subjects)
  todo-lock.py doctor                   read-only: report formatting that hides items from the parser,
                                        plus [BLOCKED] gates no writer would have created (dangling,
                                        self-blocking, or cyclic) — those need a human, not `repair`.
                                        Also prints `INFO:` lines (exit code unaffected) for store ids
                                        that files under a `sequences` dir (ADRs…) name — run `refs`
                                        — and `WARN:` lines (likewise) for a sequence number two
                                        entry files share, or for a `.claude/local-todo/` overlay
                                        file with an unknown name, over the cap or without its
                                        `schema: 1` line
  todo-lock.py repair                fix safe formatting problems in place; report what still needs a human

CLAIM LOCK (who is working on what — a JSON file in the git **common dir**, shared across
worktrees, never committed; every mutation guarded by an `fcntl.flock` on its `.lock` sidecar, so
parallel tabs can't double-claim; written atomically by temp file + rename — as is the store — with
the previous save kept as `.bak`). This replaced the old `🚧`/`**Files (locked):**` markers that used to live in the
committed file and caused the collisions + token waste.
  todo-lock.py next [--model <name>] [--effort <level>] [--route <name>]
                                        claim the next open, unclaimed, non-blocked item AND print
                                        its body. An unblocked [CRITICAL] item (see `add --critical`)
                                        is preferred ahead of even [PRIORITY] ones; otherwise prefers
                                        (within each priority group) an item whose `**Files:**` don't
                                        overlap an active claim's, so parallel tabs pick
                                        conflict-free work first (overlap defers, never starves), and
                                        seeds the claim's file list from that bullet (and its
                                        `docs` from a `**Docs:**` bullet; an overlap on documentation
                                        only — `doc_dirs` or `**Docs:**` paths — is noted, never
                                        deferred). A `route note (<model>): …` line follows the
                                        claim once: the scope boundary for the claiming route's
                                        model (none for a model without one). When tracked
                                        files already name the claimed id, a line follows the claim:
                                        `N references to this id: run refs <id>`. A `Freshness`
                                        block (<=10 lines, absent when empty) then says, for each id
                                        the body names, whether it is `landed <hash>`, `removed
                                        <hash>`, `claimed` or `open`, and lists up to five commits
                                        on the item's declared files since it was filed. A `Docs:`
                                        block (<=5 pointers, absent when docs aren't configured or
                                        nothing matches) follows: `docs for` on those files. Then
                                        the `Project context (plan-todo):` block, when it has
                                        anything to say (see PROJECT CONTEXT).
                                        Self-heals stale [BLOCKED: <id>] markers as it scans: a
                                        blocker that no longer exists is stripped, and an item whose
                                        blockers have all cleared becomes claimable.
                                        A body over 120 lines is truncated with a note
                                        naming the cut bullets and a `show <id>`
                                        pointer to the rest.
                                        --model restricts to items whose route's model is the
                                        caller's (strict, no fall-back to other models; see
                                        ROUTING). Four outcomes: `CLAIMED <id>` + body (claimed);
                                        `BLOCKED-BY-CRITICAL <id> …` — an unblocked, unfinished
                                        critical item exists and this call isn't claiming it (whether
                                        because it's already claimed by someone else or its tier
                                        doesn't match); nothing else is claimed regardless of tier,
                                        exit 1; `NONE-IN-TIER …` + per-route counts of claimable
                                        items waiting in OTHER tiers, each with its first three ids
                                        and launch command (as `summary-by-route`; relay to the
                                        user — nothing claimed, exit 1); `NONE …` (backlog empty of
                                        open work, exit 1). Without --model, no tier filtering
                                        (unchanged legacy behaviour).
                                        --effort (low|medium|high|xhigh|max, the session's level)
                                        is soft: after priority and overlap, prefer an item whose
                                        route wants exactly that effort, then the nearest level (a
                                        tie to the lower); when they differ a line follows the
                                        claim: `note: <id> wants medium, you are at high: consider
                                        /effort medium`. Never filters; without it, order is
                                        effort-blind. Any outcome may add a `note: stale claim(s)`
                                        line (see `reclaim`); a stale holder of the critical item
                                        is named, with the `release` command that frees it.
                                        --route <name> (default $CLAUDE_TODO_ROUTE, which `run`
                                        sets) is strict like --model: only that route's items are
                                        claimed, the rest are reported as NONE-IN-TIER.
  todo-lock.py attach [<id>] [files...] | attach <id> <wt> [br]
                                        record the item's worktree path + branch (after
                                        EnterWorktree). Run as `attach <id>` from inside the
                                        worktree — wt/br default to `git rev-parse
                                        --show-toplevel` / `--abbrev-ref HEAD` in the current
                                        directory; <id> defaults to the one in a `todo+<ID>`
                                        worktree's directory name. Files, when given, then set
                                        the claim's file list and print overlaps exactly as
                                        `lock <id> <files>` does (validated first; a bad one
                                        records nothing). Pass an absolute <wt> (and <br>) when
                                        attaching a path you're not currently in (e.g. a
                                        recovery case). With
                                        `worktree_setup` in CONFIG, also runs that command once
                                        from the worktree root and prints one `setup ok|FAILED`
                                        line (log under the git common dir); a failure never
                                        fails `attach`, and a second `attach` skips a setup that
                                        already succeeded for that worktree.
  todo-lock.py resume [<id>]            reprint a held claim after a context compaction: <id>
                                        defaults to the one in a `todo+<ID>` worktree's directory
                                        name (as `attach` infers it). Prints the worktree path,
                                        branch, locked files, any reserved project version or
                                        sequence number(s), the configured verify command (as
                                        `next`'s `verify:` line), then the item's heading and body
                                        (capped like `next`, with a `show <id>` pointer).
                                        Falls back to the claim's recorded heading if the item is
                                        no longer in the store. Outside a `todo+<ID>` worktree with
                                        no <id>, prints the same one-line hint as `attach`. `ERROR
                                        — <id> is not claimed` if it isn't.
  todo-lock.py lock <id> <files...> [--add|--remove]
                                        record the files this item will touch (advisory/visibility):
                                        replaces the list, or --add/--remove edits it; a bare
                                        `lock <id>` is an error (exit 2). Paths are stored
                                        repo-relative; `dir/` covers everything beneath it, a glob
                                        what it matches, a slashless name matches by basename.
                                        Warns on overlap with another active claim — loudly for
                                        hot/shared files (render engine, shared docs); an overlap on
                                        documentation paths only is an informational `note:`
  todo-lock.py touch <paths...> | --hook
                                        record paths just edited on the claim of the current
                                        worktree, as `touched` (kept apart from the declared
                                        list; a path the claim's files/docs already cover is
                                        skipped), and print any new overlap as `lock` does.
                                        Reporting only: exit 0 even outside a claim's worktree
                                        (a note, nothing recorded). --hook reads a PostToolUse
                                        hook payload on stdin (file_path/notebook_path, cwd), is
                                        silent unless a new path overlaps another claim, and then
                                        prints the `additionalContext` JSON (README: optional
                                        hook). Every script call from an attached worktree also
                                        records what it changed since the branch point (git diff
                                        + untracked), noting a new collision on stderr.
  todo-lock.py conflicts <id> [files..] print other claims that also touch any of <files>, matched
                                        as `lock` matches (hot/shared files flagged HOT-FILE
                                        CONFLICT; documentation-only overlap prints DOC-OVERLAP and
                                        still exits 0)
  todo-lock.py preflight [<id>]         preview `land`'s merge conflicts early: a dry-run three-way
                                        merge (`git merge-tree --write-tree`) of the claim's branch
                                        against the integration branch, then pairwise against every
                                        other attached claim's branch. One `CONFLICT <side> <path>`
                                        line per conflicting path (<side> is the other claim's id,
                                        or the integration branch's name) and exit 1, else `CLEAN`
                                        and exit 0. <id> defaults to the claim of the current
                                        worktree. Commits only — a `note:` says when the worktree
                                        has uncommitted changes. Moves no ref, index or worktree.
                                        Needs git 2.38+; on older git it says so and exits 0
  todo-lock.py reserve-version <id> [--tier major|minor|patch]
                                        atomically hand out the next collision-free project version
                                        for this claim (default patch); idempotent per claim. Called
                                        by /finish so parallel finishes never pick the same number.
                                        OPT-IN: errors unless `version_source` is set in
                                        `.claude/todo-config.json` (see CONFIG below).
  todo-lock.py release <id>             drop a claim + reclaim its reserved version (land does this
                                        itself on success; release covers abandoning a claim)
  todo-lock.py bounce <id> --to <route> --reason "<text>" [--body-file PATH]
                                        planning shows the item was filed on the wrong route: append
                                        a dated `Planning notes` bullet (the reason, plus any notes
                                        from --body-file or stdin) to the item, set its Route, commit
                                        the store on main (like `add --commit`), and release the
                                        claim, so the item is claimable on `--to` with the findings
                                        in its body. Prints the launch command for that route.
                                        Refused, nothing written, when the claim's worktree has
                                        commits or uncommitted changes — bounce before implementing.
  todo-lock.py reclaim --stale [--dry-run]
                                        drop every claim that looks abandoned (prints each with its
                                        reason); never touches a worktree or branch. Stale means:
                                        its recorded worktree is gone, its owner pid (CLAUDE_PID,
                                        same host only) has exited, or it's been idle longer than
                                        `stale_claim_hours` (CONFIG). A claim missing those fields
                                        is never stale by pid or idle time. `next`, `summary` and
                                        `list` flag stale claims; nothing frees one automatically
  todo-lock.py list                     show every active claim, flagged `STALE: <why>`, `GONE`
                                        (item no longer in the store) or `CHANGED` (item text
                                        changed since claimed — e.g. by a pull), plus
                                        `touched=+<path>…` for edits outside the declared files
                                        (see `touch`). Any call run from a claim's worktree
                                        refreshes its last-seen stamp
  todo-lock.py wait <id> [--interval N] [--heartbeat N] [--timeout N]
                                        block until <id> leaves the MAIN store, then exit 0 — the
                                        signal a spun-off prerequisite "completed" (removed by
                                        /finish's land, or by remove/cancel). A /plan-todo tab that
                                        files a --priority TODO it can't proceed without waits on
                                        it (run as a background Bash command / long foreground
                                        `timeout`). Errors up front if <id> doesn't exist; polls
                                        lock-free with a heartbeat + timeout safety net. NOTE: a
                                        --priority item is only picked up by ANOTHER free tab —
                                        a solo waiting tab blocks until one runs.
  todo-lock.py stats [--since YYYY-MM-DD] [--json]
                                        aggregate the per-item telemetry: items per outcome and
                                        per route, median claim→land hours, declared-files recall
                                        and precision (declared vs touched, dir/glob aware), fold
                                        conflict rate, land retries, bounce and release rate.
                                        `land`, `release`, `reclaim` and `bounce` each append one
                                        JSON line per item to claude-todo-metrics.jsonl in the git
                                        common dir (machine-local, never committed): id, family,
                                        route, effort, model, claim/attach/end times, the files
                                        declared, locked and touched (counts and paths), fold
                                        conflict, overlap note at claim, retries and the outcome
                                        — never a title or body. A write failure never fails the
                                        command. `"metrics": false` in CONFIG turns writing off.
                                        --json prints the aggregate as an object

SEQUENCES (opt-in): numbered artifact registries (ADRs, RFCs, migrations) — a collision-free
number handout plus a cheap query interface, one file per entry so parallel worktrees produce
different filenames and the merge at /finish is conflict-free by construction. (The one part that
isn't — a shared index table every entry appends a row to — is handled by giving the sequence an
`index`, which `land` then regenerates on main; see `seq index` below.) Every subcommand except
`detect` errors unless `sequences` is configured in `.claude/todo-config.json` (see CONFIG below);
`/initiate` is the command that writes that config.
  todo-lock.py seq new <name> --title <T> [--number N] [--body-file <PATH>]
                                        body on stdin. Reserve the next number, render the entry
                                        (config `template`, else a built-in default) and write it
                                        into the CURRENT worktree; print `<name>-<n>  <path>`.
                                        Template tokens: {n} {title} {body}. The primary write path.
                                        --number N uses a number `reserve` already handed out
                                        (reserve while planning, write in the worktree) instead of
                                        taking a fresh one, and records N as reserved if it wasn't;
                                        it errors if N is on disk, committed on a local branch, or
                                        reserved by another claim/worktree.
  todo-lock.py seq reserve <name> [--claim <id>]
                                        the atomic number handout alone, for callers with their
                                        own file format; prefer `seq new` otherwise. Prints the id
                                        AND the number as `pattern` renders it — `adr-89  0089` —
                                        so no caller re-implements the padding. Reserve EARLY (at
                                        plan time) so every reference written afterwards names the
                                        right number. Next = highest of
                                        (files on disk in the main tree + this worktree, files
                                        committed on any local branch, active
                                        reservations) + 1, under the claim-state flock — parallel
                                        worktrees can never be handed the same number. Inside a
                                        claimed item's worktree the reservation rides the claim
                                        (freed by `release`/`land`) — and --claim <id> says which
                                        claim when you reserve BEFORE the worktree exists, i.e.
                                        while planning; otherwise it's keyed to this worktree
                                        and dropped once the file reaches the main tree or the
                                        worktree is gone. An abandoned number is reissued; a
                                        number whose file is in the main tree never is.
  todo-lock.py seq list [<name>] [--status S] [--active] [--brief] [--scope <path>] [--tag T]
                    [--grep RE]
                                        one line per entry on disk: `<name>-<n> <status> <path>
                                        <title>`, unioned over the main tree and the current
                                        worktree (so unlanded entries show). Metadata — status,
                                        summary, scope, tags, amends, supersedes — is read from a
                                        leading `---` front-matter block, else the body's first
                                        `Field: value` line or `## Field` heading (names mapped by
                                        config `fields`; status `-` if absent). --status filters
                                        case-insensitively; --active hides superseded and
                                        deprecated entries; --brief prints `<name>-<n> <status>
                                        <summary or title>` instead; --scope keeps entries whose
                                        `scope` globs cover the path; --tag and --grep (regex over
                                        the entry) filter too. Filters combine. With no <name>,
                                        list the configured sequences instead.
  todo-lock.py seq supersede <name> <n> --by <m>
                                        set entry n's status to `Superseded by <name>-<m>`, in
                                        this checkout, rewriting only the status value (front-
                                        matter key, field line or line under the heading). `land`
                                        does the same on main for every landed entry declaring
                                        `supersedes`, so recording the field is usually enough.
                                        Exit 1 if n has no status, or is already superseded by
                                        another entry.
  todo-lock.py seq show <name> <n>      print that entry's full body — the GET that replaces
                                        grepping the directory (worktree copy wins over main's).
  todo-lock.py seq index [<name>]       regenerate the sequence's index file (config `index`) from
                                        the entries on disk, in number order, between its
                                        `<!-- BEGIN todo-lock: <name> index -->` markers — creating
                                        the file, or adding the markers to an existing one, if
                                        needed. Rarely run by hand: `land` does this on main for
                                        every indexed sequence, which is what keeps the shared
                                        index table out of the merge-conflict path. Use it to
                                        bootstrap the markers (`/initiate` does) or to repair an
                                        index that drifted. No <name> does every indexed sequence.
  todo-lock.py seq detect [--path <dir>] [--limit N]
                                        find numbered series a repo ALREADY has, for /initiate to
                                        offer registering: one TSV line per series, `<name> <dir>
                                        <pattern> <count> <example> <new|registered>`. Configured
                                        sequences come first, read from the config however few
                                        entries they hold (so a known series is never re-offered
                                        or re-bootstrapped); after them, guesses — directories git
                                        knows about (so .gitignore prunes them) whose filenames
                                        share a `NNNN-slug.ext` shape, best-populated first, with
                                        `pattern` inferred from what's there. --path <dir> reports
                                        just that directory, heuristics off. `NONE …` + exit 1
                                        when neither turns anything up (the cue to bootstrap a
                                        sequence). Works with no `sequences` configured — it's
                                        what precedes the config existing (as does `register`).
  todo-lock.py seq register <name> --dir <d> --pattern <p> [--index-file <f> [--row <r>]] [--status-field <s>] [--template <t>] [--field KEY=NAME …] [--commit [-m <MSG>]]
                                        add `sequences.<name>` to the main tree's
                                        .claude/todo-config.json (created if absent): every other
                                        key, the key order and the file's indent survive, trailing
                                        newline kept. --field maps a metadata field (status,
                                        summary, scope, tags, amends, supersedes) to the entries'
                                        own name; --index-file/--row set `index`. An identical
                                        entry is a no-op; a different one under the same name is
                                        refused, writing nothing. --commit commits ONLY the config
                                        on main (`Register <name> numbered sequence`), under the
                                        git mutex, with `add --commit`'s DIRTY refusal.

TABLES (opt-in via config `tables`): a README's package or module table that every item appends a
row to conflicts like a sequence index, so `land` regenerates each declared table on main after the
merge, in the same amend — one row per file its `source` glob matches, in path order, written only
between `<!-- BEGIN todo-lock: <name> table -->` and `<!-- END todo-lock: <name> table -->`. A
missing file or marker pair warns and changes nothing. Don't hand-edit those rows on a branch.
  todo-lock.py tables render [<name>]   preview: per table `<name> <file> N row(s), current|would
                                        change`, then the rows. Writes nothing. Exit 1 when a
                                        table's file or marker pair is missing, 2 when `tables`
                                        is unset or malformed.

CODEMAP (opt-in via config `codemap`): a map of each large source file's top-level definitions and
their line ranges, so an agent reads one range instead of the whole file. One `### <path>` heading
per file `source` matches (at least `min_lines` long), in path order, written only between
`<!-- BEGIN todo-lock: codemap -->` and `<!-- END todo-lock: codemap -->` in `file`. Python is
parsed with `ast` (defs, classes, and each class's methods as `Class.method`, from the first
decorator); brace languages (JS/TS, Java, Kotlin, Scala, C/C++/C#, Go, Rust, Swift, PHP) by a
best-effort brace-depth scan, with one level of members inside a class/struct/impl/namespace. No
semantic summaries; the output depends only on file contents. `land` regenerates it on main in the
bookkeeping amend (a missing file or marker pair warns), so don't commit it on a branch.
  todo-lock.py codemap render           preview: `codemap <file> N file(s), current|would change`,
                                        then the block. Writes nothing. Exit 1 when the file or
                                        marker pair is missing.
  todo-lock.py codemap check            exit 0 when the map matches the sources, 1 when stale
                                        (naming each source file whose section differs), 2 when
                                        `codemap` is unset/malformed or the marker block is
                                        missing. The release or CI gate: wire it as a `verify`
                                        command.
  todo-lock.py codemap write            regenerate the block in the current checkout, creating
                                        the file (or appending the marker pair) on first run.

DOCS (opt-in, read-only): look documentation up by path, so an agent reads one section instead of
the whole file. Candidates are active sequence entries (their `scope`), the `docs` registry, and —
for body search only — markdown under `doc_dirs` (see CONFIG). With none configured, every
subcommand prints a one-line hint and exit 2.
  todo-lock.py docs for <paths...> | --id <ID>
                                        at most five pointers, one per line: `<ref>  §<heading>
                                        <file>:<a>-<b>  <summary>`. --id <ID> uses the item's
                                        `**Files:**` bullet plus its claim's locked files. A scope
                                        glob covering a path ranks first (the narrower glob, then
                                        more paths covered, then a sequence entry over a registry
                                        doc); a doc whose text names a path or its basename fills
                                        the rest. The section is the first whose text names a
                                        queried path, else the whole doc. `NONE …` + exit 1 when
                                        nothing matches.
  todo-lock.py docs show <ref> [--section "<heading>" | --outline]
                                        <ref> is a repo path or a sequence ref (`adr-22`). Bare:
                                        the whole file. --section prints only that section (exact
                                        heading, case-insensitive, else a unique substring; exit 1
                                        listing the candidates when ambiguous). --outline prints
                                        each heading with its line range.
  todo-lock.py docs touched [--id <ID>]
                                        pointers (as `docs for`) for the documents whose `scope`
                                        covers a path this branch changed — uncommitted edits
                                        included, or --id <ID>'s recorded branch (commits only). A
                                        body-only name match never counts here. `NONE …` + exit 1
                                        when the branch has no changes, or none are scoped.
  todo-lock.py docs stale               registry docs (`scope` set) with commits on their scope
                                        newer than the doc's own last commit: `<file>  <n> newer
                                        commit(s) on scope, latest <hash> <subject>`. Sequence
                                        entries are never listed — an accepted record isn't edited.
                                        `NONE …` + exit 1 when none are behind.

PROJECT CONTEXT (update-safe customisation): `.claude/local-todo/<command>.md` (`plan-todo.md`,
`finish.md`, `todo.md`) holds short project instructions for that command: first line `schema: 1`,
at most 1,200 bytes. `install.sh` and `update` never touch the directory, and it is read only from
the main checkout's committed HEAD, never a working copy. `next`, `summary --context todo` and
`context finish --id <ID>` print it under a `Project context (<command>):` heading, after the
config facts that apply to this repo; with nothing to say, no heading.
  todo-lock.py context <command> [--id <ID>] [--full]
                                        print that block: sequences (when configured), release
                                        bookkeeping (when `version_source` is set), worktree
                                        isolation (only when not set up), verify commands, hot
                                        files — each only for the commands that act on it — then
                                        the overlay. Capped at about 1,500 bytes with a pointer to
                                        --full. --id adds the item's route. `none` when empty.
  todo-lock.py context set <command> [--body-file P] [--commit [-m MSG]]
                                        write the overlay from stdin (or --body-file); refused,
                                        exit 2, unless it names a known command, starts `schema:
                                        1` and fits the cap. --commit writes and commits only that
                                        file on the main checkout, under the git mutex (required
                                        from a worktree); without it the overlay is read only once
                                        committed. `doctor` warns about a bad overlay file.
                                        --section <name> sets only the text between `<!-- BEGIN
                                        claude-todo: <name> -->` and its END marker (appended if
                                        absent), keeping the rest of the file; markers never print.

TOOLCHAIN SETUP (`/stack`): detect the project's toolchain and record what agents can't guess.
Every writer targets the main checkout's own files, never the shipped payload, and merges: a
re-run with the same input prints `OK <file> unchanged`. Writers are refused from a linked
worktree without --commit; --commit [-m MSG] commits only that file, under the git mutex.
  todo-lock.py stack detect             read-only report, one TSV line each: `platform`, then
                                        `language <lang> <pm> <dir>` per manifest (depth <= 3),
                                        `monorepo <why>`, then candidates `<kind> <command>
                                        [<exts>] <source>` for test/lint/build/format/setup —
                                        CI workflow `run:`/`script:` lines first (source
                                        `ci:<file>:<line>`), then package.json scripts, Makefile
                                        targets and language defaults; `format` carries `{file}`
                                        and its extensions, `setup` is the lockfile's install
                                        line. Then `include <path>` (gitignored `.env*` files for
                                        .worktreeinclude), `protect <dir>/` (migration/generated
                                        dirs), `caveat python-editable`, and `configured <what
                                        /stack already set up>`; a candidate already recorded ends
                                        `= configured`. `NONE …` + exit 1 for an empty repo.
  todo-lock.py stack config verify --json-file P [--replace]
                                        merge a verify block into `.claude/todo-config.json`:
                                        commands added per name (a different recipe under an
                                        existing name refused, exit 2, without --replace), flaky
                                        and notes unioned; key order and indent kept.
  todo-lock.py stack config worktree_setup --value "<shell line>" [--replace]
                                        set `worktree_setup`; a different existing value is
                                        refused without --replace.
  todo-lock.py stack block <file> [--body-file P]
                                        set the `claude-todo: stack` marked block in CLAUDE.md,
                                        .claude/CLAUDE.md or .worktreeinclude (appended if absent);
                                        nothing outside the markers changes.
  todo-lock.py stack settings [--allow RULE]... [--deny RULE]... [--store-guard]
                      [--format-hook "<cmd with {file}>" --ext .a,.b]
                                        merge into `.claude/settings.json`: permission rules
                                        appended if absent; --store-guard adds the README's
                                        PreToolUse hook denying Read/Edit/Write of TODO.local.md;
                                        --format-hook adds a PostToolUse hook running the
                                        formatter on an edited file with one of the extensions
                                        (output swallowed, never blocks). A hook already present
                                        is not added twice.

AUDIT (read-only evidence for `/optimize`, plus the config setter it proposes changes through):
  todo-lock.py audit [--sessions] [--json]
                                        one `FINDING <check> <subject>: <evidence>` line per
                                        finding (`NO FINDINGS` when none), then an `INPUTS` block:
                                        config keys, overlay files, store size, telemetry,
                                        worktree_setup. Checks: long-doc (a tracked .md over 400
                                        lines amended in place by 2+ commits; not the store,
                                        payload or sequence entries), claude-md (over 200 lines),
                                        hook-candidate (CLAUDE.md lines like "always run …"),
                                        no-verify, phantom-overlap (two items or claims whose only
                                        overlap is a hard one on documentation), big-body (over
                                        4 KB), declared-files (recall or precision under 0.6),
                                        route (bounce+release over 25%, or an opus/fable route
                                        landing tiny items fast), permissions (no allow rule for
                                        the script or a verify command). --sessions adds Claude
                                        Code's local transcripts for this repo (`$CLAUDE_CONFIG_DIR`
                                        or ~/.claude, `projects/<slug>*`, newest 50): token totals,
                                        repeat-failure (a shell command failing 3+ times) and
                                        verify-in-memory (a build/test recipe only in memory
                                        notes); absent transcripts are one INPUTS line. Never
                                        prints an item's title or body
  todo-lock.py config show | set <key[.sub…]> <json> | unset <key[.sub…]> [--commit [-m MSG]]
                                        print, or change one key of, .claude/todo-config.json:
                                        the top level must be a CONFIG key and the value JSON
                                        (`config set doc_dirs '["docs"]'`); every other key, the
                                        order and the indent survive; a `routing` edit that would
                                        not load is refused. From a worktree it needs --commit,
                                        which writes and commits only that file on main under the
                                        git mutex

INFRA:
  todo-lock.py main-tree                print the primary worktree path (for merge-back)
  todo-lock.py land <id>                the whole /finish merge-back, atomically under the git mutex:
                                        require a clean main tree, a primary checkout on the
                                        integration branch (`base_branch` in CONFIG, else
                                        init.defaultBranch / origin/HEAD / main / master — the
                                        first that exists), and an item worktree with nothing
                                        uncommitted (exit 5 UNCOMMITTED: a merge would not carry
                                        it and /finish's worktree removal discards it;
                                        --allow-dirty lands anyway, abandoning it); fold the base
                                        INTO the branch's
                                        worktree (a genuine conflict exits 4 for the caller to
                                        resolve there and retry — never on the base); with a
                                        `verify` config, when the base's changes since the branch
                                        point share a directory with the branch's, run its `test`
                                        in the worktree, still under the mutex (exit 6
                                        VERIFY-FAILED: base untouched, fold kept on the branch;
                                        --no-verify skips it); merge --no-ff
                                        into the base (conflict-free by construction; refused, exit
                                        1 DUPLICATE, if it would leave two sequence entries on one
                                        number); then amend the
                                        deterministic bookkeeping into the merge commit — TODO item
                                        removal + dependent unblocking, and — WHEN configured via
                                        `.claude/todo-config.json` (see CONFIG) — the reserved
                                        version (max-wins, so out-of-order landings never roll it
                                        back), CHANGELOG SemVer order, and any sequence index
                                        (regenerated from the entries on disk); then release the claim.
                                        Mutating those shared files only here, serially on main, is
                                        what keeps parallel finishes conflict-free. With no config,
                                        `land` does only the TODO-item removal + unblocking.
                                        Last, an `undeclared:` line lists what the branch changed
                                        (or the claim `touched`) that its declared files never
                                        covered, each with any active claim it collides with —
                                        a report, never a refusal.
                                        A branch main already contains — an item that filed its
                                        whole output with `add --commit`, which writes to the MAIN
                                        checkout, never gains a commit of its own — has nothing to
                                        merge: that's detected up front (git proves it) and lands
                                        as bookkeeping only. A branch with real work that main
                                        passed is not an ancestor, so it still exits 3 STALE.
  todo-lock.py land <id> --in-place     RECOVERY, not a second workflow: for a claim with no branch
                                        because the work was done in the main checkout instead of
                                        the worktree /plan-todo step 4 creates. Runs the same
                                        bookkeeping on main with NO merge step, once main is clean
                                        (so the work is provably committed), then releases the
                                        claim. Refused if a worktree for the item still exists —
                                        that work is unmerged, so `attach` it and land normally.
                                        Plain `land` on such a claim prints both recipes.
  todo-lock.py finish [<id>] -m <subject> [--body-file F] [--tier major|minor|patch]
                      [--include-untracked [paths...]] [--no-verify]
                                        /finish's commit + land in one call, from the item's
                                        attached worktree (<id> defaults as for `attach`). With
                                        --tier (needs `version_source`), reserves the version as
                                        `reserve-version` does and replaces every `{VERSION}` in
                                        the configured changelog on the branch; a placeholder
                                        without --tier is refused. Stages tracked changes (`git
                                        add -u`) plus the untracked files --include-untracked
                                        names (bare: all), prints what it staged (capped at 20),
                                        commits with exactly the given message — the script adds
                                        no trailer — and runs `land` (--no-verify passed on).
                                        Refuses before changing anything: untracked files it was
                                        not told to include (exit 5, listed), nothing to commit,
                                        a merge in progress, not the claim's worktree. `OK
                                        landed …` is followed by `next: ExitWorktree …`; on any
                                        other land outcome it exits with land's code and the
                                        retry is `land <id>`. Never removes the worktree.
  todo-lock.py git-mutex -- <cmd...>    run <cmd> holding a repo-wide git mutex (serialize commits/merges)
  todo-lock.py verify [name] [--only <target>] [--list]
                                        run a configured build/test/lint command (`verify` in
                                        CONFIG) from the current worktree root and BLOCK until it
                                        exits — no background waiter, no polling. Full output goes
                                        to <git-common-dir>/claude-todo-verify/<worktree>--<name>.log
                                        (overwritten per run); prints one `PASS verify <name> (Ns)
                                        — log: <path>` line, or `FAIL …` plus up to 30 failing /
                                        error lines (else the last 15 lines) and exits 1; a timeout
                                        kills the process group and FAILs. <name> defaults to
                                        `test`, else the only command. --only fills the command's
                                        `{target}` placeholder (shell-quoted). A failure whose
                                        test-naming lines all name `flaky` entries is retried once
                                        and reported as a flaky retry. --list prints the commands,
                                        flaky names and notes. With no `verify` config: one-line
                                        hint, exit 2. `next` names the configured commands.
  todo-lock.py hooks show               list the configured lifecycle hooks (`hooks` in CONFIG)
                                        and any shape problem. With none: one line, exit 0.
  todo-lock.py hooks run <event> --id <ID> [--dry-run] [--force]
                                        fire one hook by hand — the retry for a FAILED one. A hook
                                        fires on its own when `next` claims an item (claim), `land`
                                        lands one (land), `remove`/`admin-done` drop one (remove),
                                        or `add`/`add-bulk` file one (add): from the main checkout,
                                        after the command's locks are released, printing `hook
                                        <event> ok|FAILED … — log: <path>`; never fatal, the
                                        command keeps its exit code. Env: CLAUDE_TODO_EVENT,
                                        _ITEM_ID, _ITEM_TITLE, _ITEM_BODY_FILE (a snapshot of the
                                        section under <git-common-dir>/claude-todo-hooks/, kept
                                        after the item is gone), _MAIN_TREE, _WORKTREE, _BRANCH,
                                        _MERGE_SHA (land only); unknown values are empty. Each fire
                                        is recorded in claude-todo-hooks/<ID>.json; an event that
                                        already ran ok refuses (exit 1) without --force. --dry-run
                                        prints the command and env and runs nothing.

SELF-UPDATE (the claude-todo package itself — unrelated to the host project's version above):
  todo-lock.py version                  what's installed here, where it came from, and the last
                                        known upstream release
  todo-lock.py check-update [--refresh] [--quiet] [--accept-source]
                                        is a newer release out? Reads the highest `v<x.y.z>` tag on
                                        the source remote via `git ls-remote` (any git host, public
                                        or private, using git's own auth — no token, no API).
                                        Prints UPDATE-AVAILABLE / UP-TO-DATE / CHECK-FAILED, or
                                        MOVED-TAG when a release tag points somewhere new, or
                                        SOURCE-UNCONFIRMED (nothing fetched) when the stamp's
                                        source differs from the one this machine trusts —
                                        --accept-source trusts it. The result is cached for a day
                                        in the git common dir. `next`,
                                        `summary` and `summary-by-model` print a one-line notice
                                        from that cache and refresh it in the background at most
                                        once a day — disable with CLAUDE_TODO_NO_UPDATE_CHECK=1 or
                                        `"update_check": false` in `.claude/todo-config.json`
  todo-lock.py update [--check] [--ref TAG|BRANCH] [--source GIT-URL] [--force] [--commit]
                      [--accept-source] [--allow-unsigned] [--full-notes]
                                        install the latest release into this repo: fetch the
                                        winning tag, check it matches what `ls-remote` reported
                                        and hasn't moved, verify its SSH signature against the
                                        installed `.claude/todo-release-signers`, print the
                                        commit, and run THAT checkout's install.sh against
                                        the main worktree (so an update is exactly a fresh install
                                        — TODO.local.md and settings.json are never clobbered).
                                        Refuses a moved tag, an unconfirmed stamp source
                                        (--accept-source) and anything it can't verify — a
                                        branch, an unsigned tag, no signers file
                                        (--allow-unsigned).
                                        Refuses if a file in the install's manifest (the `managed`
                                        list in .claude/todo-version.json: the tool, the skill
                                        directories, the agents) has uncommitted local edits, or if
                                        run inside the claude-todo package repo itself — where
                                        `.claude/` IS the shipped payload, so `git pull` is the
                                        update path (--force overrides either). Prints a capped
                                        summary of the new CHANGELOG sections — headings plus each
                                        bullet's first line; --full-notes prints them unabridged.
                                        --commit commits exactly the old and new manifests plus the
                                        stamp, under the git mutex.
                                        Called by /update

CONFIG (optional): `.claude/todo-config.json` in the repo root re-enables the version/CHANGELOG
bookkeeping (all fields optional):
  {
    "version_source": "path/to/__init__.py",  // rel to repo root; enables `reserve-version` +
                                               //   land's version write. The bumped source of
                                               //   truth must hold a `__version__ = "x.y.z"` line.
    "version_pattern": "<regex>",              // optional override of the __version__ line pattern
    "base_branch":     "master",               // the branch `land` merges into. Default: the first
                                               //   of init.defaultBranch, origin/HEAD, main,
                                               //   master that exists as a local branch.
    "changelog":       "path/to/CHANGELOG.md", // rel to repo root; enables land's SemVer re-sort
    "hot_files":       ["extra.py"],           // extra advisory hot files (basename match)
    "hot_dirs":        ["some_dir"],           // extra advisory hot dirs (path-component match)
    "doc_dirs":        ["docs"],               // documentation dirs (path-component match): an
                                               //   overlap on one is informational — never defers
                                               //   an item in `next`, never a HOT-FILE warning. A
                                               //   path that is also hot stays hot
    "docs": [                                  // docs `docs for` points at (see DOCS): `path` a
      {"path": "docs/arch/*.md",               //   file or glob, `scope` the globs it covers
       "scope": ["src/net/**"],                //   (string or list), `summary` optional
       "summary": "Networking architecture"}
    ],
    "update_check":    false,                  // opt OUT of the passive "newer release" notice
    "stale_claim_hours": 24,                   // idle time after which a claim is flagged
                                               //   stale (default 24; 0 turns the idle rule off)
    "metrics":         false,                  // opt OUT of per-item telemetry (see `stats`)
    "worktree_setup":  "cp -R \"$CLAUDE_TODO_MAIN_TREE/.build-cache\" .",
                                               // shell line `attach` runs once, from the new
                                               //   worktree root, with CLAUDE_TODO_MAIN_TREE set to
                                               //   the main checkout (build cache, tool configs,
                                               //   dependencies). Committed config only, never item
                                               //   text; a failure is reported, not fatal
    "hooks": {                                 // lifecycle hooks (see `hooks`): event -> shell
      "claim": "python3 tools/sync.py",        //   line, run with /bin/sh from the main checkout
      "land":  "python3 tools/sync.py"         //   after the event (claim, land, remove, add),
    },                                         //   every lock released. Item facts arrive only as
                                               //   CLAUDE_TODO_* env vars + a body file, never in
                                               //   the command; a failure is reported, not fatal
    "inherit_bullets": ["Source"],             // bullet labels `add`/`add-bulk` copy, from a
                                               //   worktree attached to a claimed item, into every
                                               //   new item that lacks them (never overwritten);
                                               //   prints `inherited Source from <ID>`. On when set;
                                               //   `--no-inherit` / "inherit": false opt out
    "routing": {                               // override the route table (see ROUTING)
      "routes": {                              //   merged per route, key by key, over the
        "judgment": {"model": "sonnet"},       //     built-ins; a new name needs model + effort;
        "wide": null                           //     null removes a route
      },                                       //   keys: model, effort (low|medium|high|xhigh|
                                               //     max), band (0–100 legacy %, or null)
      "default": "judgment",                   //   route for an item with no Route/Effort bullet
      "unknown_model": "error",                //   `next --model` name matching no model: "error"
                                               //     (default) or a model to treat it as
      "match": {"opus": ["opus", "big-proxy"]} //   substrings that identify a model (default: its
    },                                         //     own name)
    "verify": {                                // the project's check commands (see `verify`)
      "commands": {                            //   name -> shell line, run with /bin/sh from the
        "test": "make test",                   //     worktree root, or {"run": …, "timeout": N}
        "test_one": {"run": "pytest {target}", "timeout": 120}
      },                                       //   {target} is filled by `verify <name> --only`
      "timeout": 1800,                         //   default seconds per command (default 1800)
      "flaky": ["test_network_retry"],         //   tests whose lone failure earns one retry
      "notes": ["needs Docker running"]        //   environment quirks; `verify --list` prints them
    },
    "sequences": {                             // numbered artifact registries (see SEQUENCES)
      "adr": {                                 //   sequence name, as passed to `seq <cmd> <name>`
        "dir": "docs/adr",                     //   entry directory, rel to repo root (required)
        "pattern": "{n:04d}-{slug}.md",        //   filename: {n[:spec]} number, {slug} from
                                               //     --title (required)
        "template": "docs/adr/_template.md",   //   optional; else a built-in default is rendered
        "status_field": "Status",              //   optional (default "Status"); what `seq list`
                                               //     reads for the <status> column
        "fields": {"scope": "covers"},         //   optional; the names the entries use for
                                               //     status/summary/scope/tags/amends/supersedes
                                               //     (default: those names, any case)
        "index": {                             //   optional; the series' shared index table, which
                                               //     `land` regenerates on main (see SEQUENCES)
          "file": "docs/adr/README.md",        //     rel to repo root (required within `index`)
          "row": "| [{npad}]({path}) | {title} | {status} |"
                                               //     optional row template; tokens {n} (raw),
                                               //     {npad} (as `pattern` renders it), {path}
                                               //     (rel to the index file), {file}, {title},
                                               //     {status}, {summary}, {scope}, {amends},
                                               //     {superseded_by}. Default is the row shown.
        }
      }
    },
    "tables": [                                // generated tables `land` regenerates (see TABLES)
      {"name": "packages",                     //   marker name (unique)
       "file": "README.md",                    //   the file holding the markers, rel to repo root
       "source": "packages/*/README.md",       //   glob or list of globs (`**` recurses); one row
                                               //     per file, path order, never `file` itself
       "row": "| [{dir}]({path}) | {heading} | {description} |"}
    ],                                         //   tokens: {path} (rel to `file`), {file}, {stem},
                                               //     {dir} (parent dir name), {heading} (first
                                               //     heading, else stem); any other {word} is that
                                               //     front-matter field, empty if absent. `|` in a
                                               //     value is escaped
    "codemap": {                               // the source code map (see CODEMAP)
      "file": "docs/code-map.md",              //   the file holding the markers (required)
      "source": ["src/**/*.py", "lib/*.ts"],   //   glob or list of globs (required, `**` recurses)
      "min_lines": 400                         //   optional; skip shorter files (default 0)
    }
  }
With no config, version/CHANGELOG steps are inert and `reserve-version` errors (and with no
`sequences`, every `seq` subcommand but `detect` errors — run `/initiate` to write the map) — the
claim lock, worktree merge-back, gating, and routing all work unchanged. A malformed `routing`
key is refused up front (exit 2) by every command that routes.

ROUTING: a route names the model that claims an item and the reasoning effort recommended for it —
the model buys judgment, effort buys diligence. Built-in table (`routes` prints the effective one):
  trivial  sonnet·low     ≤15%    routine  sonnet·medium  ≤35%    standard  sonnet·high  ≤50%
  wide     sonnet·xhigh   —       judgment opus·medium    ≤70%    deep      opus·high    ≤90%
  frontier fable·medium   ≤100%   (default route: judgment)
An item's route is its `- **Route:** <name>` bullet, else its legacy `- **Effort:** NN%` mapped
through the bands (upper-inclusive: first band ≥ NN, so 50 → standard/sonnet, 51 → judgment/opus),
else the default. A route with no band (`wide`) is reachable only by name. `doctor` reports a
Route bullet naming no route, and an unreadable Effort bullet.

STORE: every command reads and writes the MAIN checkout's TODO.local.md, even when run from a
linked worktree (whose own copy is never touched). From a worktree, store-writing commands refuse
(exit 2, nothing written) unless run with `--commit`, which writes and commits on main in one step
(`remove` has no `--commit`: `land` owns it).

Testing: set CLAUDE_TODO_FILE to point `summary`/`show`/`add`/… at a scratch copy.

EXIT CODES: 0 ok · 1 nothing to hand out (`NONE…`) · 2 usage / unusable git · 3 `land` STALE ·
4 `land` merge conflict · 5 `land` UNCOMMITTED / `finish` UNTRACKED · 6 `land` VERIFY-FAILED · 70 the command crashed.
A crash prints one line naming its class — `store` (TODO.local.md; the only class /repair fixes), `state` (the claims file in the git common
dir), `git`, `environment` (not in a git repo, permissions, disk), or `write` (a store write that
would have changed the item set was refused; the file is unchanged) — and no traceback unless
CLAUDE_TODO_DEBUG=1.
"""
import sys

if sys.version_info < (3, 8):
    sys.exit("todo-lock.py needs Python 3.8 or newer (this is "
             f"{sys.version_info[0]}.{sys.version_info[1]}) — run it with a newer python3.")

import os
import re
import time
import json
import fcntl
import shlex
import shutil
import glob
import fnmatch
import socket
import hashlib
import argparse
import posixpath
import tempfile
import contextlib
import subprocess
import traceback
from collections import namedtuple
from datetime import datetime

ID_RE = re.compile(r"\b([A-Z]{2,}-\d+)\b")
# A blocked Open item links to the item that must clear first: `[BLOCKED: <id>] …` (an Admin task
# or another Open item).
BLOCK_LINK_RE = re.compile(r"\[BLOCKED:\s*([A-Z]{2,}-\d+)\]")
# A priority Open item is claimed by `next` ahead of every non-priority item.
PRIORITY_MARK = "[PRIORITY]"
# A critical Open item hard-gates the whole queue: while one is unblocked and unfinished, `next`
# refuses every claim that isn't for it — see cmd_next. Outranks [PRIORITY] (never both at once).
CRITICAL_MARK = "[CRITICAL]"


class _ArgParser(argparse.ArgumentParser):
    """This script's usage-error style (TOOL-28): one line, no usage dump. argparse's default
    `error()` prints the full `usage: …` block (often several lines) to stderr before the message;
    every subcommand parser uses this instead, so a bad flag costs one `ERROR — …` line on stdout,
    like every other error here."""
    def error(self, message):
        parts = self.prog.split(" ")
        topic = parts[1] if len(parts) > 1 else None
        hint = f" (see `help {topic}`)" if topic else ""
        print(f"ERROR — {self.prog}: {message}{hint}")
        raise SystemExit(2)


# `help <name>` (TOOL-28): one subcommand's (or reference heading's) slice of the module docstring,
# in place of the ~8k-token whole thing every "see X in --help" pointer used to mean. Ports
# tools/docmap.py's parse_usage_docs span algorithm (kept separate: tools/ is repo-local, never
# shipped) rather than importing it.
_HELP_CMD_RE = re.compile(r"^  todo-lock\.py (\S+)")
_HELP_HEADING_RE = re.compile(r"^([A-Z][A-Z ]*?)\s*[:(]")


def _command_spans(lines):
    """{name: (start, end)} 1-indexed inclusive line spans, one per subcommand's usage-doc block —
    a command GROUP (`seq new`, `seq reserve`, …) merges into one span under its shared first
    name, keeping the first block's start (mirrors tools/docmap.py's parse_usage_docs)."""
    hits = [(i + 1, m.group(1)) for i, ln in enumerate(lines) if (m := _HELP_CMD_RE.match(ln))]
    spans = {}
    for k, (start, name) in enumerate(hits):
        limit = hits[k + 1][0] - 1 if k + 1 < len(hits) else len(lines)
        end = start
        for n in range(start + 1, limit + 1):
            if _HELP_HEADING_RE.match(lines[n - 1]):
                break
            end = n
        while end > start and not lines[end - 1].strip():
            end -= 1
        if name in spans:
            spans[name] = (spans[name][0], end)
        else:
            spans[name] = (start, end)
    return spans


def _heading_spans(lines):
    """{topic: (start, end)} for each single-ALL-CAPS-WORD reference heading (`CONFIG`,
    `SEQUENCES`, …), through the line before the next heading. A multi-word heading (`CLAIM LOCK`,
    `PROJECT CONTEXT`, …) is skipped — nothing points a "see X in --help" reader at one of those.
    First occurrence wins on a repeated word (only `STORE` repeats, as an unrelated one-line
    invariant later on — the real section is the first one)."""
    heads = [i + 1 for i, ln in enumerate(lines) if _HELP_HEADING_RE.match(ln)]
    spans = {}
    for k, start in enumerate(heads):
        end = heads[k + 1] - 1 if k + 1 < len(heads) else len(lines)
        while end > start and not lines[end - 1].strip():
            end -= 1
        word = _HELP_HEADING_RE.match(lines[start - 1]).group(1)
        if " " not in word and word.lower() not in spans:
            spans[word.lower()] = (start, end)
    return spans


def _usage_spans():
    """Subcommand spans with single-word reference-heading spans overlaid — a heading wins a name a
    subcommand also uses (`config`: the ~95-line JSON schema lives nowhere near the `config`
    subcommand's own short usage doc, so the heading is what "see CONFIG in --help" means;
    `codemap`/`docs`/`audit` collide too, but their subcommand span already covers nearly the whole
    heading span either way)."""
    lines = __doc__.splitlines()
    spans = _command_spans(lines)
    spans.update(_heading_spans(lines))
    return spans


def cmd_help(argv):
    """Print one subcommand's (or reference heading's) slice of the module docstring. No argument:
    the whole thing, same as `--help`/bare `help`."""
    if not argv:
        print(__doc__)
        return 0
    name = argv[0]
    spans = _usage_spans()
    key = name if name in spans else name.lower()
    if key not in spans:
        print(f"ERROR — no such subcommand or topic {name!r}. Run `todo-lock.py help` for the "
              "full list.")
        return 2
    start, end = spans[key]
    print("\n".join(__doc__.splitlines()[start - 1:end]))
    return 0


def _git(*args):
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _common_dir():
    return _git("rev-parse", "--path-format=absolute", "--git-common-dir")


STATE_FILE = "claude-todo-state.json"


def state_path():
    return os.path.join(_common_dir(), STATE_FILE)


def main_tree():
    # The common dir is <primary-worktree>/.git; its parent is the primary worktree.
    common = _common_dir()
    return os.path.dirname(common.rstrip(os.sep)) if common.endswith(".git") else common


def main_todo_path():
    """THE store, for every subcommand: the MAIN worktree's TODO.local.md, which `land` mutates
    and `add --commit` commits. Never the current worktree's committed copy — that one only
    changes when `main` is merged into the branch, so reading it from a /plan-todo worktree showed
    stale items (and `next` could claim one that had already landed), and writing it dirtied the
    branch's copy into a store merge conflict. CLAUDE_TODO_FILE still overrides, for tests."""
    return os.environ.get("CLAUDE_TODO_FILE") or os.path.join(main_tree(), "TODO.local.md")


def _in_linked_worktree():
    """True inside a linked worktree (a /plan-todo tab), False in the primary checkout."""
    return _git("rev-parse", "--path-format=absolute", "--git-dir") != _common_dir()


def _store_writable_here():
    """Whether a plain (non-`--commit`) store write may run from this checkout. From a linked
    worktree it may not: the write would land on main's store uncommitted, and a worktree-isolated
    session can't commit main — the DIRTY state `land` and `add --commit` refuse. An explicit
    CLAUDE_TODO_FILE isn't main's store, so it's always writable."""
    return bool(os.environ.get("CLAUDE_TODO_FILE")) or not _in_linked_worktree()


# Subcommands that write the store. From a linked worktree they're refused before dispatch (see
# _store_write_refusal) unless they carry `--commit`, which commits on main itself. `bounce` also
# writes the store but is deliberately absent: it always commits on main itself, so it has no
# dirty-main state to refuse. `remove` has no `--commit`: `land` owns it.
STORE_WRITERS = {"add", "add-bulk", "append", "edit", "merge", "block", "remove", "admin-done",
                 "reorder", "repair", "set-effort", "set-files"}
# `add`/`add-bulk` handle `--commit` themselves; the rest go through `_run_committed` at dispatch.
STORE_COMMITTERS = {"append", "edit", "merge", "block", "reorder", "repair", "admin-done",
                    "set-effort", "set-files"}
COMMIT_WRITERS = {"add", "add-bulk"} | STORE_COMMITTERS


def _store_write_refusal(cmd, argv):
    """None if `cmd` may run here, else the refusal message (nothing has been written)."""
    if cmd not in STORE_WRITERS or (cmd in COMMIT_WRITERS and "--commit" in argv):
        return None
    if _store_writable_here():
        return None
    head = (f"REFUSED — `{cmd}` writes the store, which lives in the main checkout "
            f"({main_tree()}); from this worktree the edit would be left uncommitted there, which "
            "`land` rejects as DIRTY. Nothing was written.")
    if cmd in COMMIT_WRITERS:
        return head + f" Re-run as `{cmd} … --commit` — it writes and commits on main in one step."
    return head + " Run it from the main checkout instead."


_CONFIG_CACHE = {}


def _config():
    """The optional `.claude/todo-config.json` in the main tree, parsed once and cached. Returns
    `{}` when the file is absent or unreadable — every field is opt-in, so a missing config leaves
    the version/CHANGELOG bookkeeping inert and the rest of the tool fully generic. See CONFIG in
    the module docstring for the recognized keys."""
    if "data" not in _CONFIG_CACHE:
        path = os.path.join(main_tree(), ".claude", "todo-config.json")
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            _CONFIG_CACHE["data"] = data if isinstance(data, dict) else {}
        except (FileNotFoundError, ValueError, OSError):
            _CONFIG_CACHE["data"] = {}
    return _CONFIG_CACHE["data"]


_BASE_BRANCH_CACHE = {}


def base_branch():
    """The integration branch `land` merges into — what used to be the hard-coded `main`.

    Resolution, first hit wins: the config's `base_branch`, then `init.defaultBranch`, then what
    `origin/HEAD` points at, then `main`, then `master`. Everything after the config must also
    EXIST as a local branch: `init.defaultBranch` records what `git init` would name a new repo's
    first branch on this machine, not what this repo actually uses, so on a `master` repo cloned
    to a machine configured for `main` the unverified answer is wrong. An explicit config value is
    taken verbatim — a typo there should surface as the loud "primary checkout is not on it"
    refusal in `cmd_land`, not be silently papered over by a fallback.

    Cached per process: `land` asks repeatedly and the answer cannot change mid-command."""
    if "name" not in _BASE_BRANCH_CACHE:
        _BASE_BRANCH_CACHE["name"] = _resolve_base_branch()
    return _BASE_BRANCH_CACHE["name"]


def _resolve_base_branch():
    configured = (_config().get("base_branch") or "").strip()
    if configured:
        return configured
    tree = main_tree()

    def out(*args):
        return subprocess.run(["git", "-C", tree, *args],
                              capture_output=True, text=True).stdout.strip()

    candidates = []
    default = out("config", "--get", "init.defaultBranch")
    if default:
        candidates.append(default)
    origin_head = out("symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if origin_head.startswith("origin/"):
        candidates.append(origin_head[len("origin/"):])
    candidates += ["main", "master"]
    for name in candidates:
        if subprocess.run(["git", "-C", tree, "show-ref", "--verify", "--quiet",
                           f"refs/heads/{name}"], capture_output=True).returncode == 0:
            return name
    return "main"


# @fragment 10_store_core.py
# ---------------------------------------------------------------------------
# Store layer — parse, validate and atomically write the markdown backlog; the StoreLock
# ---------------------------------------------------------------------------

SECTIONS = {"## Admin": "admin", "## Open": "open"}

# A code-fence line: 3+ backticks or 3+ tildes, then an info string (openers) or nothing (closers).
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")


def _fence_step(fence, line):
    """Advance the fence state over one line: `(fence, is_fence_line)`. `fence` is None outside a
    code block, else the opening run (e.g. "````" or "~~~"). CommonMark's delimiter rules (BUG-7):
    a block closes only on the SAME character repeated at least as many times with nothing after
    it, so a ``` line inside a ```` block, or inside a ~~~ block, is content; a backtick opener's
    info string can't contain a backtick. One deviation: any indent is accepted, since we don't
    track list nesting and fences inside list items must keep working. Every store scan (the
    parser, the body validator, doctor/repair) goes through here so they agree on what's fenced."""
    m = FENCE_RE.match(line)
    if not m:
        return fence, False
    run, rest = m.group(1), m.group(2)
    if fence is None:
        if run[0] == "`" and "`" in rest:
            return None, False                        # inline code, not an opener
        return run, True
    if run[0] == fence[0] and len(run) >= len(fence) and not rest.strip():
        return None, True
    return fence, False                               # content inside the open block


# Status markers live in ONE place: the run right after a heading's `<ID> — ` lead (BUG-7). Text
# that looks like a marker later in the title is title text — it never blocks, gates or orders.
MARKER_TOKEN_RE = re.compile(r"\[BLOCKED[^\]]*(?:\]|$)|\[CRITICAL\]|\[PRIORITY\]")


def _split_heading(item_id, heading):
    """Split a heading (the text after `### `) into its parts: `{lead, blockers, bad, critical,
    priority, title}`. `lead` is the id plus its dash, `blockers` the `[BLOCKED: <id>]` ids in
    order, `bad` any malformed `[BLOCKED…]` token (kept so the item stays blocked and doctor can
    flag it), and `title` whatever follows the leading marker run. `_compose_heading` inverts it."""
    m = re.match(rf"^(\s*{re.escape(item_id)}\b\s*(?:[—–-]\s*)?)(.*)$", heading) if item_id else None
    lead, rest = (m.group(1), m.group(2)) if m else ("", heading)
    parts = {"lead": lead, "blockers": [], "bad": [], "critical": False, "priority": False}
    rest = rest.lstrip()
    while True:
        t = MARKER_TOKEN_RE.match(rest)
        if not t:
            break
        tok = t.group(0)
        if tok == CRITICAL_MARK:
            parts["critical"] = True
        elif tok == PRIORITY_MARK:
            parts["priority"] = True
        else:
            b = BLOCK_LINK_RE.fullmatch(tok)
            if b:
                if b.group(1) not in parts["blockers"]:
                    parts["blockers"].append(b.group(1))
            else:
                parts["bad"].append(tok)
        rest = rest[t.end():].lstrip()
    parts["title"] = rest.strip()
    return parts


def _compose_heading(parts):
    """The heading text for `_split_heading`'s parts, markers in the canonical order `add`, `block`
    and `reorder` write: every `[BLOCKED: …]`, then [CRITICAL] or [PRIORITY]."""
    markers = "".join(f"[BLOCKED: {b}] " for b in parts["blockers"])
    markers += "".join(f"{b} " for b in parts["bad"])
    if parts["critical"]:
        markers += f"{CRITICAL_MARK} "
    elif parts["priority"]:
        markers += f"{PRIORITY_MARK} "
    return (parts["lead"] + markers + parts["title"]).strip()


def _set_heading(lines, it, parts):
    """Rewrite `it`'s `### ` line in `lines` from `_split_heading` parts and return the heading
    text. One line in, one line out, so every other item's indices stay valid within a locked pass."""
    heading = _compose_heading(parts)
    lines[it["start"]] = "### " + heading
    return heading


# Advisory (never-refuse) thresholds for `_write_warnings` (TOOL-32) — round decimal numbers,
# matching OVERLAY_MAX_BYTES/CONTEXT_MAX_BYTES's style, not binary KB.
# No title or body length is a refusal, deliberately (TOOL-46). The body is the claimer's whole
# spec, so a hard cap would push filers toward terse pointers and cost the work quality; size is
# steered at filing time by the BODY_WARN_BYTES warning instead. A title is only a label, so its
# warning stays a warning too. NEXT_BODY_MAX_LINES is the one cut, a guard against a pathological
# paste in the `next`/`resume` printout: its note must name what it dropped and point at a command
# that prints the rest (`_print_claim_body`).
BODY_WARN_BYTES = 3000
TITLE_WARN_CHARS = 70
NEXT_BODY_MAX_LINES = 120


def validate_body(body):
    """None if `body` (a list of lines) is safe to splice into an item, else the reason it isn't.
    Unsafe means it would restructure the store: a boundary line parse_items acts on — a `## `
    section header, a `### ` item heading, a `---` rule — outside a code fence, or a fence left
    open, which would hide every later item from the parser (BUG-7). Shared by every body writer:
    add, add-bulk, append, edit and merge."""
    fence = opened = None
    for n, line in enumerate(body, 1):
        was = fence
        fence, is_fence = _fence_step(fence, line)
        if is_fence:
            if was is None:
                opened = n
            continue
        if fence is not None:
            continue
        if line.startswith("## ") or line.startswith("### ") or line.strip() == "---":
            return (f"line {n} ({line.strip()!r}) is a `## `/`### `/`---` store boundary — put an "
                    "example heading or rule inside a code fence")
    if fence is not None:
        return (f"the {fence} code fence opened on line {opened} is never closed — it would hide "
                "every later item")
    return None


def validate_title(title):
    """None if `title` is safe as an item title, else the reason it isn't: empty, more than one
    line (a newline would inject a second heading), or carrying marker text, which the flags own."""
    if not title.strip():
        return "is empty"
    if "\n" in title or "\r" in title:
        return "contains a line break — a title is one line"
    for mark, flag in (("[BLOCKED", "--blocked-by"), (CRITICAL_MARK, "--critical"),
                       (PRIORITY_MARK, "--priority")):
        if mark in title:
            return (f"contains marker text {mark!r} — set markers with {flag}, or reword the "
                    "title (e.g. 'the BLOCKED marker')")
    return None


def _title_length_warning(title):
    """None, or an advisory (never a refusal) that `title` is over TITLE_WARN_CHARS — long titles
    flow into commit subjects and every `summary` line (TOOL-32, PE-6)."""
    n = len(title)
    if n > TITLE_WARN_CHARS:
        return (f"title is {n} characters (over ~{TITLE_WARN_CHARS}) — long titles flow into "
                "commit subjects and every `summary` line")
    return None


def _body_size_warning(body_lines):
    """None, or an advisory that `body_lines` is over BODY_WARN_BYTES (TOOL-32, TOK-6)."""
    n = len("\n".join(body_lines).encode("utf-8"))
    if n > BODY_WARN_BYTES:
        return (f"body is {n} bytes (over ~{BODY_WARN_BYTES // 1000}KB) — move background to a "
                "doc and link it")
    return None


def _trailing_note_end(lines, start, end):
    """Return where an item's body ends, excluding a trailing **section-intro blockquote**.

    A section/family provenance note (`> Source: …`) that introduces the *next* item is written
    as a standalone `> …` run, separated from the item above it by a blank line and sitting just
    before the next boundary (`### `/`## `/`---`). It is not that item's body, so it must fall
    outside every item — otherwise `remove` deletes it along with the item (STORE-1). If such a
    trailing note is present, return the index where it (and its blank-line separator) begins;
    otherwise return `end` unchanged. A `>` block glued directly to the item's content (no blank
    separator) is genuine body and is left in place."""
    j = end
    while j > start and lines[j - 1].strip() == "":
        j -= 1                                        # skip trailing blank lines before the boundary
    k = j
    while k > start and lines[k - 1].lstrip().startswith(">"):
        k -= 1                                        # walk back over the blockquote run
    if k == j:
        return end                                    # no trailing blockquote
    m = k
    while m > start and lines[m - 1].strip() == "":
        m -= 1                                        # skip the blank-line separator above it
    if m == k:
        return end                                    # blockquote glued to item content — it's body, keep it
    if m <= start + 1:
        return end                                    # nothing but the heading above the note — leave it attached
    return m                                          # trim: item ends at its last real content line


def parse_items(lines):
    """Return one dict per `### <ID> — …` item under a recognised section (`## Admin`, `## Open`):
      {id, heading, section, blocked, start, end, body}
    `section` is 'admin' (human tasks — never auto-claimed) or 'open'. `body` is lines[start:end]
    (the `###` line through the line before the next section boundary). A boundary is the next
    `### ` heading, a `---` rule, or a `## ` heading — boundaries inside fenced code blocks
    (``` or ~~~, per `_fence_step`) are ignored. A trailing **section-intro blockquote** (a
    standalone `> …` note that introduces the next item) is excluded from the body so `remove`
    can't delete it — see `_trailing_note_end`. `blocked`/`priority`/`critical`/`blockers` are read
    from the heading's leading marker run only (`_split_heading`)."""
    items = []
    cur = None
    section = None
    fence = None

    def close(end):
        if cur is not None:
            end = _trailing_note_end(lines, cur["start"], end)
            cur["end"] = end
            cur["body"] = lines[cur["start"]:end]
            if cur["id"]:
                items.append(cur)

    for i, line in enumerate(lines):
        stripped = line.strip()
        fence, is_fence = _fence_step(fence, line)
        if is_fence or fence is not None:
            continue
        if line.startswith("## "):
            close(i)
            cur = None
            section = SECTIONS.get(stripped)
            continue
        if section is None:
            continue
        if line.startswith("### "):
            close(i)
            heading = line[4:].strip()
            idm = ID_RE.search(heading)
            parts = _split_heading(idm.group(1) if idm else None, heading)
            cur = {
                "id": idm.group(1) if idm else None,
                "heading": heading,
                "section": section,
                "blockers": parts["blockers"],
                "blocked": bool(parts["blockers"] or parts["bad"]),
                "priority": parts["priority"],
                "critical": parts["critical"],
                "start": i,
            }
            continue
        if stripped == "---":
            close(i)
            cur = None
    close(len(lines))
    return items


def read_lines(path=None):
    with open(path or main_todo_path(), encoding="utf-8") as f:
        return f.read().split("\n")


def _atomic_write(path, text):
    """Replace `path` with `text` all-or-nothing: write a temp file in the same directory, fsync
    it, then `os.replace` it over the target (BUG-3). A kill or full disk mid-write leaves the
    previous file intact — never truncated. A symlink is resolved first so it stays a symlink, and
    the target's mode is kept (a new file gets what `open(…, "w")` would give it)."""
    path = os.path.realpath(path)
    d = os.path.dirname(path)
    try:
        mode = os.stat(path).st_mode & 0o7777
    except FileNotFoundError:
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask
    fd, tmp = tempfile.mkstemp(dir=d, prefix="." + os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    try:  # make the rename itself durable; best effort (not every platform can fsync a dir)
        dfd = os.open(d, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


def write_lines(lines, path=None):
    text = "\n".join(lines)
    if not text.endswith("\n"):
        text += "\n"  # keep the file newline-terminated
    _atomic_write(path or main_todo_path(), text)


class StoreWriteRefused(Exception):
    """A store write whose result would not parse to the ids the writer meant to leave (BUG-7).
    Its own crash class (`write`), never `store`: the file is unchanged, so /repair has nothing to
    fix — it is a writer bug, or a store already hand-damaged in a way doctor reports."""


def _ids(lines):
    return sorted(it["id"] for it in parse_items(lines))


def write_store(lines, expect, path=None):
    """`write_lines` for TODO.local.md, checked (BUG-7): refuse unless `lines` parses to exactly
    the ids in `expect` (duplicates counted), then after the atomic write re-read the file and
    restore the previous text if it doesn't. Every store mutator except `repair` (restructuring is
    its job) writes through here. Validators catch the known causes first; this is the net."""
    want = sorted(expect)
    got = _ids(lines)
    if got != want:
        raise StoreWriteRefused(_id_drift(want, got))
    path = path or main_todo_path()
    with open(path, encoding="utf-8") as f:
        previous = f.read()
    write_lines(lines, path)
    got = _ids(read_lines(path))
    if got != want:
        _atomic_write(path, previous)
        raise StoreWriteRefused(_id_drift(want, got) + " (after the write; the previous content "
                                "was restored)")


def _id_drift(want, got):
    from collections import Counter
    lost, extra = Counter(want) - Counter(got), Counter(got) - Counter(want)
    return ("the write would leave the store with the wrong items"
            + (f" — missing {', '.join(sorted(lost))}" if lost else "")
            + (f" — unexpected or duplicate {', '.join(sorted(extra))}" if extra else ""))


class StoreLock:
    """flock guarding store-file mutations (add/append/remove) across parallel tabs."""

    def __enter__(self):
        self._fd = os.open(state_path() + ".store", os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(self._fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self._fd, fcntl.LOCK_UN)
        os.close(self._fd)


def find_item(items, item_id):
    for it in items:
        if it["id"] == item_id:
            return it
    return None


def _status(it, claimed):
    if it["section"] == "admin":
        return "admin"
    if it["blocked"]:
        return "blocked"
    if it["id"] in claimed:
        return "in_progress"
    if it["critical"]:
        return "critical"
    return "priority" if it["priority"] else "open"


# @fragment 11_store_read.py
# ---------------------------------------------------------------------------
# Store reads and routing — summary, show, files, refs, the route table,
# `run`, freshness, and the per-family id counter
# ---------------------------------------------------------------------------

STATUSES = ("admin", "blocked", "in_progress", "critical", "priority", "open")


def cmd_summary(argv):
    ap = _ArgParser(prog="todo-lock.py summary", add_help=False)
    ap.add_argument("--status", choices=STATUSES)
    ap.add_argument("--context", choices=OVERLAY_COMMANDS)
    opts = ap.parse_args(argv)
    with State() as st:
        claimed = set(st.claims)
        stale = _stale_claims(st.claims)
    items = parse_items(read_lines())
    if not items:
        print("(no items)")
    for it in items:
        status = _status(it, claimed)
        if opts.status and status != opts.status:
            continue
        print(f"{it['id']}\t{status}\t{it['heading']}")
    # A trailing note, not a status value: the 3-column lines and --status stay as callers parse them.
    if stale:
        print(_stale_note(stale))
    # Opt-in by flag, not by default: /reorder, /admin-task and the filer parse this output too.
    for line in _context_block(opts.context) if opts.context else ():
        print(line)
    maybe_update_notice()
    return 0


_SIMILAR_MAX = 8


def cmd_similar(argv):
    """Constant-cost duplicate check (TOOL-33/PE-10): rank every item against a free-text query by
    stdlib token overlap (`_item_similarity_tokens`) instead of printing the whole `summary` index.
    Read-only, same status column as `summary` so a claimed near-duplicate still reads in_progress."""
    ap = argparse.ArgumentParser(prog="todo-lock.py similar", add_help=False)
    ap.add_argument("query", nargs="+")
    ap.add_argument("--context", choices=OVERLAY_COMMANDS)
    opts = ap.parse_args(argv)
    query_tokens = _query_tokens(" ".join(opts.query))
    if not query_tokens:
        print("NONE — query has no usable keywords")
        return 1
    with State() as st:
        claimed = set(st.claims)
    items = parse_items(read_lines())
    scored = []
    for it in items:
        weights = _item_similarity_tokens(it)
        score = sum(weights.get(tok, 0) for tok in query_tokens)
        if score > 0:
            scored.append((score, it))
    if not scored:
        print("NONE — no similar items found")
        return 1
    scored.sort(key=lambda pair: pair[0], reverse=True)  # stable: ties keep store order
    for score, it in scored[:_SIMILAR_MAX]:
        print(f"{it['id']}\t{_status(it, claimed)}\t{it['heading']}\tscore={score}")
    for line in _context_block(opts.context) if opts.context else ():
        print(line)
    maybe_update_notice()
    return 0


def cmd_summary_by_model(_argv):
    """Read-only glance at what's actually claimable right now (unblocked, unclaimed Open items —
    status open/priority/critical), grouped by the model each item's route names (`_item_route`, in
    `_model_order`) — the same routing next --model uses to claim, so this view can't drift from
    it. Each line carries the route name. Trailed by an in_progress section (claimed items, not tier-grouped) so a glance also
    shows what's already being worked — that section is purely additive and never changes what
    counts as claimable."""
    with State() as st:
        claims = dict(st.claims)
    claimed = set(claims)
    items = parse_items(read_lines())
    claimable = [it for it in items if _status(it, claimed) in ("open", "priority", "critical")]
    in_progress = [it for it in items if _status(it, claimed) == "in_progress"]
    if not claimable and not in_progress:
        print("(no claimable items)")
        maybe_update_notice()
        return 0
    if not claimable:
        print("(no claimable items)")
    else:
        by_model = {name: [] for name in _model_order()}
        for it in claimable:
            by_model[_item_route(it["body"]).model].append(it)
        for model, group in by_model.items():
            if not group:
                continue
            # critical first, then priority, stable otherwise
            group.sort(key=lambda it: (not it["critical"], not it["priority"]))
            print(f"== {model} ==")
            for it in group:
                print(f"{it['id']}\t{_status(it, claimed)}\t{_item_route(it['body']).name}"
                      f"\t{it['heading']}")
    _print_in_progress(in_progress, claims)
    maybe_update_notice()
    return 0


def _print_in_progress(in_progress, claims):
    """The trailing `== in_progress ==` section of the summary-by-* views: each claimed item with
    its worktree, flagged when the claim looks stale. Nothing when no item is claimed."""
    if not in_progress:
        return
    print("== in_progress ==")
    for it in in_progress:
        wt = claims.get(it["id"], {}).get("worktree")
        reason = _stale_reason(claims.get(it["id"], {}))
        flag = f"\tSTALE: {reason}" if reason else ""
        print(f"{it['id']}\twt={wt}\t{it['heading']}{flag}")


def cmd_summary_by_route(_argv):
    """Read-only: for each route with claimable work (same set as summary-by-model), the count, the
    first three ids in claim order and the command that launches a tab for it; then the same
    in_progress section."""
    with State() as st:
        claims = dict(st.claims)
    claimed = set(claims)
    items = parse_items(read_lines())
    claimable = [it for it in items if _status(it, claimed) in ("open", "priority", "critical")]
    claimable.sort(key=lambda it: (not it["critical"], not it["priority"]))
    in_progress = [it for it in items if _status(it, claimed) == "in_progress"]
    if not claimable:
        print("(no claimable items)")
    for line in _route_lines(claimable):
        print(line)
    _print_in_progress(in_progress, claims)
    maybe_update_notice()
    return 0


def cmd_show(argv):
    ap = _ArgParser(prog="todo-lock.py show", add_help=False)
    ap.add_argument("id")
    ap.add_argument("--brief", action="store_true",
                    help="heading, status, route, declared files and the first sentence of What — "
                         "about 80 tokens, enough to judge an overlap without the whole body "
                         "(TOOL-28)")
    opts = ap.parse_args(argv)
    it = find_item(parse_items(read_lines()), opts.id)
    if it is None:
        print(f"NONE — no item {opts.id} in the backlog")
        return 1
    if not opts.brief:
        print("\n".join(it["body"]).rstrip())
        return 0
    with State() as st:
        status = _status(it, set(st.claims))
    route = _item_route(it["body"])
    files = _item_files(it["body"]) or "(none declared)"
    print(it["heading"])
    print(f"status: {status}  route: {_route_label(route)}  files: {files}")
    what = _item_what_sentence(it["body"])
    if what:
        print(f"What: {what}")
    return 0


FILES_BULLET_RE = re.compile(r"^\s*[-*]\s*\*\*Files?(?:\s*\(locked\))?:\*\*\s*(.+?)\.?\s*$", re.I)


def _item_files(body):
    """The one-line file list an item declares in its `- **Files:** …` bullet (the /todo
    convention), whitespace-collapsed; '' if the item names none. Lets `files` surface the
    overlap signal /reorder chains on without pulling every full body into context."""
    for line in body:
        m = FILES_BULLET_RE.match(line)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()
    return ""


def _split_declared_files(decl):
    """Split a `- **Files:** …` bullet's text into individual path tokens. The bullet is free
    prose (comma-separated, often backticked, sometimes with parenthetical notes), so strip
    punctuation/backticks and keep only tokens `_looks_like_path` accepts — good enough for the
    advisory overlap signal, never a hard gate. Tokens come back as written; `_norm_path` makes
    them comparable."""
    files = []
    for tok in re.split(r"[,\s()]+", decl or ""):
        tok = tok.strip("`'\";:").rstrip(".")
        if _looks_like_path(tok):
            files.append(tok)
    return files


WHAT_BULLET_RE = re.compile(r"^\s*[-*]\s*\*\*What:\*\*\s*(.+?)\.?\s*$", re.I)


def _item_what(body):
    """The one-line text of an item's `- **What:** …` bullet, or ''. Read like `_item_files`; feeds
    `similar`'s token-overlap score, not a hard gate."""
    for line in body:
        m = WHAT_BULLET_RE.match(line)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()
    return ""


_NEW_NOTE_RE = re.compile(r"\(\s*new\s*\)", re.I)


def _split_declared_files_with_new(decl):
    """Like `_split_declared_files`, but (path, is_new) pairs: `is_new` is set when the path's own
    comma-separated segment carries a `(new)` note — the /todo convention (also `(moved)`/
    `(removed)`, ignored here) for a file the item will create rather than one that should already
    exist."""
    out = []
    for seg in re.split(r",\s*", decl or ""):
        is_new = bool(_NEW_NOTE_RE.search(seg))
        for tok in _split_declared_files(seg):
            out.append((tok, is_new))
    return out


def _missing_declared_files(body_lines):
    """Declared `**Files:**` paths absent from the main tree (or current worktree — `_in_tree`)
    and not marked `(new)` — advisory only, like every other declared-files check
    (`_split_declared_files`'s docstring). A glob is never flagged: `_bad_paths` treats one as
    path-shaped without checking what it matches, and there is no good literal existence check
    for a pattern."""
    return [p for p, is_new in _split_declared_files_with_new(_item_files(body_lines))
            if not is_new and not _is_glob(p) and not _in_tree(p)]


def _write_warnings(title, body_lines):
    """Advisory (never-refuse) messages for a write command's title/body/declared-files (TOOL-32):
    an overlong title, an oversized body, or a declared file missing from the tree and not marked
    `(new)`. `title` is None where the command doesn't set one (`append`, `edit`) — skipped there."""
    out = []
    if title is not None:
        w = _title_length_warning(title)
        if w:
            out.append(w)
    w = _body_size_warning(body_lines)
    if w:
        out.append(w)
    missing = _missing_declared_files(body_lines)
    if missing:
        out.append("declared file(s) not found and not marked `(new)`: "
                   + ", ".join(f"`{p}`" for p in missing))
    return out


def _print_warnings(item_id, warnings):
    """Print each of `_write_warnings`' messages to stderr, `warn: <id> — <message>` — stderr so
    callers parsing stdout are unaffected."""
    for w in warnings:
        print(f"warn: {item_id} — {w}", file=sys.stderr)


DOCS_BULLET_RE = re.compile(r"^\s*[-*]\s*\*\*Docs?:\*\*\s*(.+?)\.?\s*$", re.I)


def _item_docs(body):
    """The one-line text of an item's `- **Docs:** …` bullet (its documentation deliverable), or ''.
    Paths named here are soft for overlap — see `_is_soft`."""
    for line in body:
        m = DOCS_BULLET_RE.match(line)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()
    return ""


def _split_declared_docs(decl):
    """Path tokens of a `**Docs:**` bullet, read like `_split_declared_files` after dropping a
    `#anchor` (`docs/x.md#y` names `docs/x.md`); `none` and other prose yield nothing."""
    return _split_declared_files(re.sub(r"#[^\s,`)]*", "", decl or ""))


WHAT_BULLET_RE = re.compile(r"^\s*[-*]\s*\*\*What:\*\*\s*(.+)$", re.I)


def _item_what_sentence(body):
    """The first sentence of an item's `- **What:** …` bullet, whitespace-collapsed — the short
    blurb `show --brief` prints instead of a whole body. '' if the item names no What bullet."""
    for line in body:
        m = WHAT_BULLET_RE.match(line)
        if m:
            text = re.sub(r"\s+", " ", m.group(1)).strip()
            end = text.find(". ")
            return text[:end + 1] if end != -1 else text
    return ""


# `similar`'s token-overlap ranking (TOOL-33/PE-10): stdlib only, no index to keep in sync — every
# call re-scans the store, same as `summary`. Common English words that would otherwise swamp the
# score without distinguishing anything.
_STOPWORDS = frozenset("""
    a an the and or but of to in on for with is are was were this that these those it its be been
    being as at by from into than then so not no do does did has have had will would can could
    should shall may might must item items add change fix update make new one two also into
""".split())
_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text):
    """Lowercased word tokens from free text, stop-words and single characters dropped."""
    return [w for w in _WORD_RE.findall((text or "").lower()) if len(w) > 1 and w not in _STOPWORDS]


def _path_tokens(paths):
    """Path strings broken into their lowercase components (split on path separators and dots),
    stop-words dropped — how a declared file becomes matchable keywords, e.g. `src/todo_lock.py`
    -> {src, todo, lock, py}."""
    toks = []
    for p in paths:
        toks.extend(w for w in re.split(r"[\\/._-]+", p.lower()) if w and w not in _STOPWORDS)
    return toks


def _query_tokens(text):
    """Tokens `similar` matches a query against: `_tokenize`'s ordinary words, plus path-derived
    tokens for any whitespace-separated word that itself looks like a file path (`_looks_like_path`)
    — so a query naming `src/export.py` earns the same path weighting a declared Files bullet does.
    (`_path_tokens` alone would mis-tokenize a query passed as one multi-word argv string, since it
    only splits on path characters, not spaces.)"""
    tokens = set(_tokenize(text))
    for word in (text or "").split():
        tok = word.strip("`'\";:,()").rstrip(".")
        if _looks_like_path(tok):
            tokens.update(_path_tokens([tok]))
    return tokens


def _item_similarity_tokens(it):
    """`{token: weight}` for one item's title, `- **What:**` bullet and declared `- **Files:**`
    paths — what `similar` scores a query against. Path-derived tokens outweigh prose ones (a
    query naming a file should out-rank one that merely shares common words); a token earned from
    more than one field keeps its highest weight rather than stacking."""
    weights = {}
    title = _split_heading(it["id"], it["heading"])["title"]
    for tok in _tokenize(title) + _tokenize(_item_what(it["body"])):
        weights[tok] = max(weights.get(tok, 0), 1)
    for tok in _path_tokens(_split_declared_files(_item_files(it["body"]))):
        weights[tok] = max(weights.get(tok, 0), 3)
    return weights


# Prose a `**Files:**` bullet carries that has a dot in it but names no file ("(e.g. exports)").
_PROSE_ABBREVS = {"e.g", "i.e", "etc", "cf", "vs", "n.b", "a.k.a", "approx"}
_PATH_CHARS_RE = re.compile(r"[\w.@+~/\\*?\[\]-]+")


def _looks_like_path(tok):
    """Whether a token plausibly names a file, directory or glob: path characters only, and a slash,
    a glob character, or a dotted name whose extension isn't all digits (`v2.0`, `1.2` are prose).
    Deliberately still rejects a bare dotless word — `lock` accepts one only if it exists."""
    if not tok or "://" in tok or tok.lower() in _PROSE_ABBREVS or not _PATH_CHARS_RE.fullmatch(tok):
        return False
    if "/" in tok or "\\" in tok or _is_glob(tok):
        return True
    _stem, dot, ext = tok.rpartition(".")
    return bool(dot) and bool(ext) and not ext.isdigit()


# Routing — which model claims an item, and at what reasoning effort. A ROUTE names both: the model
# buys judgment (pick it by the hardest single decision in the item), the effort level buys
# diligence (how much there is to check, how well mistakes hide) — docs/improvement-review-
# 2026-09-20.md §4. An item names its route in a `- **Route:** <name>` bullet; a legacy item's
# `- **Effort:** NN%` bullet maps onto a route through its BAND; an item with neither takes the
# default route. `next --model` claims only items whose route's model is the caller's.
#
# Bands are UPPER-INCLUSIVE — the first band (ascending) the percentage doesn't exceed — so 0 folds
# into the lowest route and each shared endpoint belongs to the LOWER route. The built-in bands
# reproduce the old three tiers exactly (sonnet [0,50] opus (50,90] fable (90,100]), which is what
# keeps a store of legacy percentages routing as it always has. A route with no band (`wide`) is
# reachable only by name. Table order doubles as the "bigger" order `merge` keeps.
Route = namedtuple("Route", "name model effort band")
BUILTIN_ROUTES = [
    Route("trivial", "sonnet", "low", 15),
    Route("routine", "sonnet", "medium", 35),
    Route("standard", "sonnet", "high", 50),
    Route("wide", "sonnet", "xhigh", None),
    Route("judgment", "opus", "medium", 70),
    Route("deep", "opus", "high", 90),
    Route("frontier", "fable", "medium", 100),
]
# Unclassified items take `judgment` (opus): legacy items predate both bullets and were planned for
# the Opus tabs, so they keep going there with no backfill.
BUILTIN_DEFAULT_ROUTE = "judgment"
# The scope boundary `next` prints once per claim, keyed by the claiming route's model — each
# family's prompting guide wants a different one, and printing it here keeps it out of every stored
# body. Keep each under ~80 tokens. A model with no entry (a config-added one) gets no note.
ROUTE_NOTES = {
    "sonnet": "The item's Files and Acceptance are its whole scope. Apply each instruction to "
              "every case it covers, not only the one it names, and don't infer requests it "
              "doesn't make. Make routine judgment calls yourself; if a better approach turns up, "
              "say so in a sentence and continue as asked.",
    "opus": "Deliver this item at this scope. Make routine judgment calls yourself; if a better "
            "approach turns up, say so in a sentence and continue as asked. Finish the whole item, "
            "and stop short of changes clearly beyond it.",
    "fable": "Keep changes and tests to what this item asks for. A pre-existing bug or behaviour "
             "it doesn't mention is a follow-up for your summary, not this change. Where it's "
             "ambiguous, implement the reading its wording most directly supports and state it. "
             "Commit tests only where the item asks or the repo keeps them; implement every asked "
             "behaviour completely.",
}
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
ROUTE_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
# Representative percentage for the legacy named-tier spelling `add --effort sonnet|opus|fable` (a
# percentage inside each built-in band, so it round-trips to the same model). `--route` supersedes it.
TIER_REPR = {"sonnet": 35, "opus": 70, "fable": 95}
EFFORT_BULLET_RE = re.compile(r"^\s*[-*]\s*\*\*Effort:\*\*\s*(\d{1,3})\s*%?\s*$", re.I)
ROUTE_BULLET_RE = re.compile(r"^\s*[-*]\s*\*\*Route:\*\*\s*`?([A-Za-z0-9_-]+)`?\s*$", re.I)
ROUTE_LOOSE_RE = re.compile(r"^\s*[-*]\s*\*\*Route:\*\*", re.I)


class RoutingConfigError(Exception):
    """`routing` in `.claude/todo-config.json` is malformed. `main` prints it as a plain ERROR
    (exit 2) — deliberately not a crash class: /repair can't fix a config file."""


_ROUTING_CACHE = {}


def _routing():
    """The effective routing table: the built-ins with the config's `routing` key merged over them,
    validated, built once and cached. A dict: `routes` (ordered Routes), `by_name`, `default` (a
    Route), `unknown_model` ("error" or a model), `match` ({model: [substring, …]}, in table order)
    and `source` ("built-in" or "config"). Raises RoutingConfigError on a bad config."""
    if "data" not in _ROUTING_CACHE:
        _ROUTING_CACHE["data"] = _build_routing(_config().get("routing"))
    return _ROUTING_CACHE["data"]


def _build_routing(cfg):
    if cfg is None:
        cfg = {}
    if not isinstance(cfg, dict):
        raise RoutingConfigError("must be an object")
    unknown = set(cfg) - {"routes", "default", "unknown_model", "match"}
    if unknown:
        raise RoutingConfigError(f"unknown key(s) {', '.join(sorted(unknown))} "
                                 "(want routes, default, unknown_model, match)")
    # Per-route, key-by-key merge over the built-ins: a new name is appended, null removes one.
    table = {r.name: r._asdict() for r in BUILTIN_ROUTES}
    order = [r.name for r in BUILTIN_ROUTES]
    overrides = cfg.get("routes") or {}
    if not isinstance(overrides, dict):
        raise RoutingConfigError("`routes` must be an object of route name → settings")
    for name, spec in overrides.items():
        if not ROUTE_NAME_RE.fullmatch(name):
            raise RoutingConfigError(f"route name {name!r} must be lowercase letters, digits, - or _")
        if spec is None:
            table.pop(name, None)
            if name in order:
                order.remove(name)
            continue
        if not isinstance(spec, dict):
            raise RoutingConfigError(f"route {name!r} must be an object (or null to remove it)")
        bad = set(spec) - {"model", "effort", "band"}
        if bad:
            raise RoutingConfigError(f"route {name!r}: unknown key(s) {', '.join(sorted(bad))} "
                                     "(want model, effort, band)")
        if name not in table:
            missing = {"model", "effort"} - set(spec)
            if missing:
                raise RoutingConfigError(f"new route {name!r} needs {' and '.join(sorted(missing))}")
            table[name] = {"name": name, "model": None, "effort": None, "band": None}
            order.append(name)
        table[name].update(spec)
    routes = []
    for name in order:
        model, effort, band = table[name]["model"], table[name]["effort"], table[name]["band"]
        if not isinstance(model, str) or not ROUTE_NAME_RE.fullmatch(model):
            raise RoutingConfigError(f"route {name!r}: model {model!r} must be a lowercase name "
                                     "such as sonnet, opus or fable")
        if effort not in EFFORT_LEVELS:
            raise RoutingConfigError(f"route {name!r}: effort {effort!r} must be one of "
                                     f"{'|'.join(EFFORT_LEVELS)}")
        if band is not None and (isinstance(band, bool) or not isinstance(band, int)
                                 or not 0 <= band <= 100):
            raise RoutingConfigError(f"route {name!r}: band {band!r} must be a 0–100 integer "
                                     "(the upper bound of its legacy Effort %) or null")
        routes.append(Route(name, model, effort, band))
    if not any(r.band is not None for r in routes):
        raise RoutingConfigError("at least one route needs a band, so legacy Effort % items route")
    by_name = {r.name: r for r in routes}
    default = cfg.get("default", BUILTIN_DEFAULT_ROUTE)
    if default not in by_name:
        raise RoutingConfigError(f"default route {default!r} is not in the table "
                                 f"({'|'.join(by_name)})")
    models = list(dict.fromkeys(r.model for r in routes))
    match = {m: [m] for m in models}
    extra = cfg.get("match") or {}
    if not isinstance(extra, dict):
        raise RoutingConfigError("`match` must be an object of model → [substring, …]")
    for model, subs in extra.items():
        if model not in match:
            raise RoutingConfigError(f"match: {model!r} is no route's model ({'|'.join(models)})")
        if (not isinstance(subs, list) or not subs
                or not all(isinstance(x, str) and x.strip() for x in subs)):
            raise RoutingConfigError(f"match: {model!r} needs a non-empty list of strings")
        match[model] = [x.strip().lower() for x in subs]
    policy = cfg.get("unknown_model", "error")
    if policy != "error" and policy not in match:
        raise RoutingConfigError(f"unknown_model {policy!r} must be \"error\" or a model "
                                 f"({'|'.join(models)})")
    return {"routes": routes, "by_name": by_name, "default": by_name[default],
            "unknown_model": policy, "match": match, "source": "config" if cfg else "built-in"}


def _model_order():
    """The models in the order they first appear in the routing table (sonnet, opus, fable)."""
    return list(_routing()["match"])


def _route_label(route):
    """`<route> (<model> · <effort>)` — how `add` names the route it chose."""
    return f"{route.name} ({route.model} · {route.effort})"


def _route_echo(body, item_id=None):
    """The line `add`/`add-bulk` print after filing, so the filer sees where the item will go:
    `→ routes to judgment (opus · medium)`, marked `[default]` when nothing in the body chose it."""
    chosen = (_item_route_name(body) in _routing()["by_name"]) or _item_effort(body) is not None
    who = f"{item_id} " if item_id else ""
    return f"→ {who}routes to {_route_label(_item_route(body))}{'' if chosen else ' [default]'}"


def _item_effort(body):
    """The 0–100 level-of-effort percentage an item declares in its `- **Effort:** NN%` bullet,
    or None if it names none (a legacy item). Parsed like `_item_files` — first match wins."""
    for line in body:
        m = EFFORT_BULLET_RE.match(line)
        if m:
            v = int(m.group(1))
            if 0 <= v <= 100:
                return v
    return None


def _item_route_name(body):
    """The route name an item's `- **Route:** <name>` bullet declares (lowercased), or None.
    First match wins, like `_item_effort`. Not checked against the table — `_item_route` does that."""
    for line in body:
        m = ROUTE_BULLET_RE.match(line)
        if m:
            return m.group(1).lower()
    return None


EFFORT_LOOSE_RE = re.compile(r"^\s*[-*]\s*\*\*Effort:\*\*", re.I)


def _routing_problem(body):
    """A one-line description of a routing bullet that doesn't route, or None: a Route bullet
    naming no route in the table or unreadable, or (with no Route bullet) an Effort bullet
    `_item_effort` can't read (`high`, `50 percent`, `150%`). Any of these silently sends the item
    to the default route instead of the one it was meant for."""
    by_name = _routing()["by_name"]
    name = _item_route_name(body)
    if name is not None:
        if name in by_name:
            return None
        return f"unknown route {name!r} in its Route bullet (routes: {'|'.join(by_name)})"
    for line in body:
        if ROUTE_LOOSE_RE.match(line):
            return f"unreadable Route bullet {line.strip()!r} (want `- **Route:** <name>`)"
    if _item_effort(body) is not None:
        return None
    for line in body:
        if EFFORT_LOOSE_RE.match(line):
            return f"unreadable Effort bullet {line.strip()!r} (want `- **Effort:** NN%`, 0–100)"
    return None


def _route_for_pct(pct):
    """The route a 0–100 legacy effort percentage maps to (upper-inclusive bands, ascending)."""
    banded = sorted((r for r in _routing()["routes"] if r.band is not None), key=lambda r: r.band)
    for r in banded:
        if pct <= r.band:
            return r
    return banded[-1]  # a configured top band below 100: clamp to the highest banded route


def _item_route(body):
    """The Route an item goes to: its Route bullet when that names a known route, else its Effort
    percentage's band, else the default route."""
    rt = _routing()
    name = _item_route_name(body)
    if name in rt["by_name"]:
        return rt["by_name"][name]
    e = _item_effort(body)
    return rt["default"] if e is None else _route_for_pct(e)


def _parse_route(raw):
    """`(Route, None)` for a known route name (any case), else `(None, message)` phrased to follow
    whatever the caller names the field — shared by `add --route` and `add-bulk`'s "route"."""
    by_name = _routing()["by_name"]
    route = by_name.get(str(raw).strip().lower())
    if route:
        return route, None
    return None, f"must be a route name ({'|'.join(by_name)}; see `routes`), not {raw!r}"


def _model_for_name(model):
    """Map a model name/ID to a routing-table model by substring match on each model's `match`
    strings, so full IDs like 'claude-opus-4-8' / 'claude-sonnet-5' resolve. A name matching none
    follows `unknown_model`: None under "error" (the default), else that model."""
    rt = _routing()
    m = (model or "").lower()
    for name, subs in rt["match"].items():
        if any(s in m for s in subs):
            return name
    return None if rt["unknown_model"] == "error" else rt["unknown_model"]


def _effort_distance(it, effort):
    """`next --effort`'s sort key for an item: (steps between its route's effort and the session's,
    the route's own effort level) — exact match first, then nearest, a tie to the lower effort.
    A constant without --effort, so the claim order is exactly the effort-blind one."""
    if effort is None:
        return (0, 0)
    wants = EFFORT_LEVELS.index(_item_route(it["body"]).effort)
    return (abs(wants - EFFORT_LEVELS.index(effort)), wants)


def _launch_command(route):
    """The command that starts a tab for this route: its model and effort, and `/plan-todo` told
    the same effort so `next` can prefer items that want it."""
    return f'claude --model {route.model} --effort {route.effort} "/plan-todo {route.effort}"'


def _route_lines(items):
    """Per-route glance at `items` (claimable, in claim order), routes in table order, empty ones
    omitted: `<route>  <model>·<effort>  <n> item(s): <first three ids> …` then its launch
    command. Shared by `summary-by-route` and `next`'s NONE-IN-TIER."""
    by_route = {r.name: [] for r in _routing()["routes"]}
    for it in items:
        by_route[_item_route(it["body"]).name].append(it["id"])
    out = []
    for r in _routing()["routes"]:
        ids = by_route[r.name]
        if not ids:
            continue
        more = " …" if len(ids) > 3 else ""
        out.append(f"  {r.name:<10} {r.model + '·' + r.effort:<14} {len(ids):>2} item(s): "
                   f"{' '.join(ids[:3])}{more}")
        out.append(f"    → {_launch_command(r)}")
    return out


def cmd_routes(_argv):
    """Print the effective routing table — route, model, effort, legacy band — then each model's
    match strings and the unknown-model policy. Read-only."""
    rt = _routing()
    print(f"routing table ({rt['source']}); default route: {rt['default'].name}")
    for r in rt["routes"]:
        band = "—" if r.band is None else f"≤{r.band}%"
        mark = "  [default]" if r is rt["default"] else ""
        print(f"  {r.name:<10} {r.model:<8} {r.effort:<7} {band}{mark}")
    for model, subs in rt["match"].items():
        print(f"model {model}: matches {', '.join(repr(s) for s in subs)}")
    policy = rt["unknown_model"]
    print("unknown model: " + ("error" if policy == "error" else f"treated as {policy}"))
    return 0


# The routes `run` starts headless workers for. Only fast-path ones: an unattended `claude -p`
# session has nobody to approve a plan, so a route whose items plan before they build gets a tab.
RUN_ROUTES = ("trivial", "routine")
RUN_LOG_DIR = "claude-todo-run"
RUN_DEFAULT_PERMISSION_MODE = "auto"
# Appended to each worker's system prompt. The route filter itself rides CLAUDE_TODO_ROUTE, which
# `next` reads, so a worker that drops a flag still can't claim another route's item.
RUN_UNATTENDED = (
    "You are an unattended /plan-todo worker started by `todo-lock.py run`; nobody is watching "
    "this session. Take the fast path: do not enter plan mode and do not ask questions. If the "
    "claimed item needs a plan, a decision from the owner, or anything on the stop-and-surface "
    "list in /plan-todo, stop, leave the claim in place and say why in your final message. "
    "Otherwise implement, verify and /finish as normal.")


def _run_command(route, permission_mode):
    """(env additions, argv) for one headless worker on `route`."""
    return ({"CLAUDE_TODO_ROUTE": route.name},
            ["claude", "-p", f"/plan-todo {route.effort}", "--model", route.model,
             "--effort", route.effort, "--permission-mode", permission_mode,
             "--append-system-prompt", RUN_UNATTENDED])


def cmd_run(argv):
    """Start headless `/plan-todo` workers for each fast-path route with claimable work (or the one
    named), at most `-n` per route and never more than it has items. `--dry-run` prints the
    commands and touches nothing. Never claims: each worker claims through `next`."""
    ap = _ArgParser(prog="todo-lock.py run", add_help=False)
    ap.add_argument("--route", default=None)
    ap.add_argument("-n", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--permission-mode", default=RUN_DEFAULT_PERMISSION_MODE)
    opts = ap.parse_args(argv)
    if opts.n < 1:
        print("ERROR — -n must be at least 1")
        return 2
    routes = {r.name: r for r in _routing()["routes"]}
    if opts.route is not None:
        if opts.route not in routes:
            print(f"ERROR — --route {opts.route!r} must be one of {'|'.join(routes)} (see `routes`)")
            return 2
        if opts.route not in RUN_ROUTES:
            print(f"ERROR — {opts.route} plans before it builds, and a headless worker can't get a "
                  f"plan approved; start a tab: {_launch_command(routes[opts.route])}")
            return 2
    wanted = [opts.route] if opts.route else [n for n in RUN_ROUTES if n in routes]
    with State() as st:
        claimed = set(st.claims)
    items = parse_items(read_lines())
    critical = next((it for it in items if it["section"] == "open" and it["critical"]
                     and not it["blocked"]), None)
    if critical is not None and _item_route(critical["body"]).name not in wanted:
        print(f"BLOCKED-BY-CRITICAL {critical['id']} — it gates the whole queue and isn't on "
              f"{'/'.join(wanted)}, so every worker would be refused; nothing started")
        return 1
    counts = {n: 0 for n in wanted}
    for it in items:
        name = _item_route(it["body"]).name
        if name in counts and _status(it, claimed) in ("open", "priority", "critical"):
            counts[name] += 1
    workers = [(n, *_run_command(routes[n], opts.permission_mode))
               for n in wanted for _ in range(min(opts.n, counts[n]))]
    if not workers:
        print(f"NONE — no claimable work on {'/'.join(wanted)}")
        return 1
    print(f"permission mode: {opts.permission_mode} (--permission-mode to change)")
    if opts.dry_run:
        for i, (name, env, cmd) in enumerate(workers, 1):
            prefix = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
            print(f"{name} #{i}: {prefix} {shlex.join(cmd)}")
        return 0
    if shutil.which("claude") is None:
        print("ERROR — `claude` is not on PATH; nothing started")
        return 2
    cwd = main_tree()
    log_dir = os.path.join(_common_dir(), RUN_LOG_DIR)
    os.makedirs(log_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    for i, (name, env, cmd) in enumerate(workers, 1):
        log = os.path.join(log_dir, f"{name}-{stamp}-{i}.log")
        with open(log, "ab") as fh:
            proc = subprocess.Popen(cmd, cwd=cwd, env={**os.environ, **env},
                                    stdin=subprocess.DEVNULL, stdout=fh,
                                    stderr=subprocess.STDOUT, start_new_session=True)
        print(f"started {name} #{i} pid {proc.pid} → {log}")
    return 0


FILES_TITLE_MAX = 60  # cmd_files truncates its trailing title column to this (TOOL-28)


def cmd_files(_argv):
    with State() as st:
        claimed = set(st.claims)
    opens = [it for it in parse_items(read_lines()) if it["section"] == "open"]
    if not opens:
        print("(no open items)")
        return 0
    for it in opens:
        # Doc paths (soft for overlap — `_is_soft`) are marked, so a reader chaining on shared files
        # can tell an informational doc overlap from a real one. Still one tab-separated field.
        entries = _claim_entries(_split_declared_files(_item_files(it["body"])),
                                 _split_declared_docs(_item_docs(it["body"])))
        # Parsed path tokens (TOOL-28), not the raw `- **Files:** …` prose — shorter, and it's what
        # the overlap matcher actually compares.
        files = [path for path, _, soft in entries if not soft]
        docs = [path for path, _, soft in entries if soft]
        mark = f" [doc: {', '.join(docs)}]" if docs else ""
        title = it["heading"]
        if len(title) > FILES_TITLE_MAX:
            title = title[:FILES_TITLE_MAX - 1] + "…"
        print(f"{it['id']}\t{_status(it, claimed)}\t{', '.join(files) if files else '?'}{mark}"
              f"\t{title}")
    return 0


REFS_CAP = 20  # lines `refs` prints, and ids/locations `doctor` lists, before saying "N more"
_GREP_HIT_RE = re.compile(r"^(.*?):(\d+):(.*)$")


def _grep_ids(ids, paths=None, timeout=None):
    """Tracked-file lines naming any of `ids` as a whole word, as [(path, lineno, text)]. Never the
    store or CHANGELOG — an id lives there by design, and those hits are what a bare repo-wide grep
    drowns in. No match gives []; a git failure or timeout raises (see `_grep_ids_quiet`)."""
    if not ids:
        return []
    top = _git("rev-parse", "--show-toplevel")
    excludes = [":(exclude,glob)**/TODO.local.md", ":(exclude,glob)**/CHANGELOG.md"]
    override = os.environ.get("CLAUDE_TODO_FILE")  # a store override isn't named TODO.local.md
    if override:
        rel = os.path.relpath(os.path.realpath(override), os.path.realpath(top))
        if not rel.startswith(".."):
            excludes.append(f":(exclude){rel}")
    args = ["git", "-C", top, "grep", "-n", "-w", "-I", "-F", "--no-color"]
    for ident in ids:
        args += ["-e", ident]
    args += ["--", *(paths or ["."]), *excludes]
    p = subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=timeout)
    if p.returncode > 1:  # 1 is git grep's "no match"
        raise subprocess.CalledProcessError(p.returncode, args, p.stdout, p.stderr)
    hits = []
    for line in p.stdout.splitlines():
        m = _GREP_HIT_RE.match(line)
        if m:
            text = m.group(3).strip()
            hits.append((m.group(1), int(m.group(2)), text if len(text) <= 160 else text[:157] + "..."))
    return hits


def _grep_ids_quiet(ids, paths=None, timeout=None):
    """`_grep_ids` for output that only decorates a command (`next`'s hint, `doctor`'s info): a
    grep that fails or times out costs the decoration, never the command."""
    try:
        return _grep_ids(ids, paths, timeout)
    except (subprocess.SubprocessError, OSError):
        return []


def cmd_refs(argv):
    if len(argv) != 1:
        print("ERROR — usage: todo-lock.py refs <id>")
        return 2
    item_id = argv[0]
    hits = _grep_ids([item_id])
    if not hits:
        print(f"NO REFERENCES to {item_id} in tracked files")
        return 0
    for path, lineno, text in hits[:REFS_CAP]:
        print(f"{path}:{lineno}: {text}")
    if len(hits) > REFS_CAP:
        print(f"… {len(hits) - REFS_CAP} more (`git grep -n -w {item_id}` for all)")
    return 0


# `next`'s freshness block (see `_freshness_lines`): at most 1 header + FRESHNESS_IDS id lines +
# FRESHNESS_COMMITS commit lines, ids mentioned in the body are examined up to FRESHNESS_EXAMINE
# (a `UTF-8` in prose costs a lookup like any other), and every git call shares one time budget.
FRESHNESS_IDS = 4
FRESHNESS_COMMITS = 5
FRESHNESS_EXAMINE = 12
FRESHNESS_BUDGET_S = 3
_FRESHNESS_STATE_RANK = {"landed": 0, "removed": 0, "claimed": 1, "open": 2}


def _freshness_lines(item, items, claimed, budget=FRESHNESS_BUDGET_S):
    """The lines `next` prints after a claim so the agent doesn't rediscover what changed while the
    item waited: the state of every item id the body names, and the newest commits on its declared
    files since it was filed. [] when there is nothing to say. Advisory like `_grep_ids_quiet`: a
    git failure or the time budget costs the block (or the half not yet computed), never the claim.

    An id in the store is `claimed` or `open` with no git call. An id that has left it is looked up
    once by the newest commit that changed the count of its `### <id> ` heading — its removal. That
    is `landed` when the commit's subject names the id (land's merge and `Land <id>:` subjects do),
    else `removed` (`remove`, `merge`, `admin-done`: gone, not necessarily done). An id git has never
    seen in the store (a review label, `UTF-8`) is left out. The same query for the claimed item
    itself finds the commit that filed it, which bounds the second half. `-m --first-parent` is
    what lets pickaxe see the removal: `land` amends it into a `--no-ff` merge, which a plain
    `git log -S` skips."""
    lines = []
    try:
        deadline = time.monotonic() + budget
        tree, base = main_tree(), base_branch()
        rel = os.path.relpath(os.path.realpath(main_todo_path()), os.path.realpath(tree))
        history = not rel.startswith("..")  # a CLAUDE_TODO_FILE outside the repo has none
        open_ids = {it["id"] for it in items}

        def log(*args):
            left = deadline - time.monotonic()
            if left <= 0:
                raise subprocess.TimeoutExpired("git log", budget)
            return subprocess.run(["git", "-C", tree, "log", *args], capture_output=True,
                                  text=True, errors="replace", timeout=left, check=True).stdout

        def heading_commit(ident):
            out = log("-1", "-m", "--first-parent", f"-S### {ident} ", "--format=%h%x09%s",
                      base, "--", rel).strip()
            h, _, subject = out.partition("\t")
            return (h, subject) if h else None

        states, commits, filed = [], [], None
        mentioned = []
        for ident in ID_RE.findall("\n".join(item["body"])):
            if ident != item["id"] and ident not in mentioned:
                mentioned.append(ident)
        try:
            for ident in mentioned[:FRESHNESS_EXAMINE]:
                if ident in open_ids:
                    states.append((ident, "claimed" if ident in claimed else "open"))
                elif history:
                    gone = heading_commit(ident)
                    if gone:
                        word = "landed" if re.search(rf"\b{re.escape(ident)}\b", gone[1]) else "removed"
                        states.append((ident, f"{word} {gone[0]}"))
            # Absolute, parent-relative and magic pathspecs make git refuse the whole query.
            files = [f for f in _split_declared_files(_item_files(item["body"]))
                     if not f.startswith((":", "/", ".."))]
            filed = heading_commit(item["id"]) if history and files else None
            if filed:
                out = log(f"-{FRESHNESS_COMMITS}", "--no-merges", "--format=%h%x09%s",
                          f"{filed[0]}..{base}", "--", *files)
                for row in out.splitlines():
                    h, _, subject = row.partition("\t")
                    commits.append(f"commit {h} " + (subject if len(subject) <= 72
                                                     else subject[:69] + "..."))
        except (subprocess.SubprocessError, OSError):
            pass  # keep whatever was gathered before the failure
        states.sort(key=lambda s: _FRESHNESS_STATE_RANK[s[1].split()[0]])  # stable: body order kept
        more = len(states) - FRESHNESS_IDS
        if states or commits:
            notes = ([f"item filed in {filed[0]}"] if filed else []) + \
                    ([f"+{more} more ids"] if more > 0 else [])
            lines.append("Freshness" + (f" ({'; '.join(notes)})" if notes else "") + ":")
            lines += [f"  {ident} {state}" for ident, state in states[:FRESHNESS_IDS]]
            lines += [f"  {c}" for c in commits]
    except (subprocess.SubprocessError, OSError):
        return []
    return lines


def _family_numbers(items, family):
    """The `<family>-<n>` numbers currently present in the store. `next-id` and `add-bulk --family`
    both floor their handout on this (plus the persisted high-water mark), so the two agree on what
    the next free number is."""
    pat = re.compile(rf"^{re.escape(family)}-(\d+)$")
    return [int(m.group(1)) for it in items for m in [pat.match(it["id"])] if m]


def _history_floor(family):
    """The highest `<family>-<n>` git history shows as used: store headings added or removed, plus
    ids named in any commit subject. 0 when there is no history, the store was never committed, or
    git fails — the floor is best-effort and must never break `next-id`."""
    fam = re.escape(family)
    heading = re.compile(rf"^[+-]### {fam}-(\d+) ")
    subject = re.compile(rf"\b{fam}-(\d+)\b")
    nums = [0]
    try:
        root = main_tree()
        patch = subprocess.run(
            ["git", "log", "--all", "-p", f"-G^### {family}-", "--format=", "--", "TODO.local.md"],
            cwd=root, capture_output=True, text=True, check=True).stdout
        subjects = subprocess.run(
            ["git", "log", "--all", "--format=%s"],
            cwd=root, capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, OSError):
        return 0
    for line in patch.splitlines():
        m = heading.match(line)
        if m:
            nums.append(int(m.group(1)))
    nums += [int(n) for n in subject.findall(subjects)]
    return max(nums)


def _family_ceiling(st, family, nums):
    """The highest number already used for `family`: the persisted high-water mark, the numbers now
    in the store (`nums`), and — scanned once per family per clone — git history. A fresh clone has
    no mark, so without the scan it would reissue ids removed long ago. The scan result is folded
    into the mark and the family recorded in `history_scanned`, so later calls cost nothing. (A
    separate marker, not "no mark yet": `add TOOL-5` bumps the mark without ever scanning.)"""
    if family not in st.history_scanned:
        st.next_id[family] = max(st.next_id.get(family, 0), _history_floor(family))
        st.history_scanned.append(family)
        st.save()
    return max([st.next_id.get(family, 0), *nums])


def cmd_next_id(argv):
    family = argv[0]
    nums = _family_numbers(parse_items(read_lines()), family)
    # Monotonic per family: floor the next number on the persisted high-water mark, not just the
    # numbers currently in the file, so a removed id (finished + `remove`d) is never reissued — one
    # TASK-1, ever. `add` advances the hwm on real use; `next-id` only reads it, so a number a human
    # printed but never `add`ed doesn't burn (mirrors reserve-version). The hwm lives in the
    # machine-local claim-state JSON, so a clone that lacks it seeds it once from git history
    # (`_family_ceiling`); beyond that it does not coordinate id assignment across machines.
    with State() as st:
        ceiling = _family_ceiling(st, family, nums)
    print(f"{family}-{ceiling + 1}")
    return 0


# @fragment 12_store_write.py
# ---------------------------------------------------------------------------
# Store writes — add, add-bulk, the git mutex, and the --commit path
# ---------------------------------------------------------------------------

ADMIN_HEADER = [
    "## Admin",
    "",
    "> Human tasks — things only a person can do (publish, grant access, flip a repo setting).",
    "> `/plan-todo` never claims these; `summary` still lists them. Mark one done with"
    " `/admin-task`, which deletes it and unblocks any `[BLOCKED: <id>]` items that referenced it.",
]


def _insert_admin_section(lines):
    """Ensure a `## Admin` section exists (creating it above `## Open`) and return
    (lines, admin_end) where admin_end is the index to insert a new admin item before."""
    admin_idx = open_idx = None
    for i, l in enumerate(lines):
        if l.strip() == "## Admin":
            admin_idx = i
        elif l.strip() == "## Open":
            open_idx = i
    if admin_idx is None:
        at = open_idx if open_idx is not None else 0
        lines = lines[:at] + ADMIN_HEADER + ["", ""] + lines[at:]
        return lines, at + len(ADMIN_HEADER) + 1
    end = len(lines)
    for i in range(admin_idx + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    while end > admin_idx + 1 and lines[end - 1] == "":
        end -= 1
    return lines, end


def _open_top(lines):
    """Index of the first line inside `## Open` after its header/blank(s), or None if there is
    no `## Open` section. New priority items are inserted here so they lead the section."""
    for i, l in enumerate(lines):
        if l.strip() == "## Open":
            j = i + 1
            while j < len(lines) and lines[j] == "":
                j += 1
            return j
    return None


def _parse_effort(raw):
    """Parse a level-of-effort value — a 0–100 percentage (`70`, `"70"`, `"70%"`) or a tier name
    (sonnet|opus|fable, mapped to its representative percentage). Returns `(pct, None)` on success
    and `(None, message)` on failure, the message phrased to follow whatever the caller names the
    field. Shared so `add`'s `--effort` string and `add-bulk`'s JSON string-or-number accept
    exactly the same spellings."""
    text = str(raw).strip().rstrip("%").lower()
    if text in TIER_REPR:
        return TIER_REPR[text], None
    if text.isdigit() and 0 <= int(text) <= 100:
        return int(text), None
    return None, (f"must be a 0–100 percentage or a tier name ({'|'.join(TIER_REPR)}), "
                  f"not {raw!r}")


def _render_item(item_id, title, body, priority=False, critical=False, blockers=(), effort_pct=None,
                 route=None):
    """The lines of one `### <id> — …` item section, ready to splice into the store. Shared by
    `add` and `add-bulk`, so a batch-written item is byte-identical to a singly-added one.
    `critical` is `add`-only (add-bulk has no `--critical` flag) — the default keeps add-bulk's
    call site unchanged.

    No `---`/`> Source:` separator: `remove` only deletes the `### …` section, so a separator would
    be orphaned when the item is finished. Provenance goes in the body (a `- **Source:** …` bullet
    the skill supplies), so it travels with the item. The effort is machine-read (like the
    `**Files:**` bullet), so it goes in a canonical body bullet rather than the heading — which
    already carries the `[BLOCKED: …]`/`[CRITICAL]`/`[PRIORITY]` markers (written in that order, as
    `block` and `reorder` write them; blocked never co-occurs with critical, since a blocked item
    is never auto-claimed, and critical/priority are mutually exclusive — `add` rejects combining
    them. A blocked item may be priority: the marker takes effect once the gate clears)."""
    markers = "".join(f"[BLOCKED: {b}] " for b in blockers)
    if critical:
        markers += f"{CRITICAL_MARK} "
    elif priority:
        markers += f"{PRIORITY_MARK} "
    body_lines = body.split("\n") if body else []
    if effort_pct is not None:
        body_lines.append(f"- **Effort:** {effort_pct}%")
    if route is not None:
        body_lines.append(f"- **Route:** {route}")
    return [f"### {item_id} — {markers}{title}"] + body_lines


def _bump_next_id(st, item_id):
    """Advance the id's family high-water mark on this real use, so `next-id` never reissues the
    number after the item is removed (monotonic per family). Only grows — never reset on removal,
    which is the whole point. The id has already matched ID_RE, so the rsplit is safe."""
    family, num = item_id.rsplit("-", 1)
    st.next_id[family] = max(st.next_id.get(family, 0), int(num))


# `--commit` — file an item on main from anywhere, without a shell `git`. (Not a `# ---` banner:
# this is a sub-part of the store layer, and docmap.py reads any `# ---` line as a new section.)
# A /plan-todo tab spins off out-of-scope work by filing it against the MAIN checkout, so the new
# item lands on `main` and another tab can claim it immediately. Writing the file is easy; the
# COMMIT was the wall. From a worktree-isolated session the harness refuses `cd <main-tree> && git
# commit` ("changes directory to the shared checkout") and equally refuses the `git-mutex -- git
# commit` recipe ("names git more than once"), so the store was left modified-but-uncommitted on
# main — exactly the state `land` rejects with DIRTY, and unrecoverable without a human. Driving
# the commit from inside the script leaves the harness one `python3 todo-lock.py …` call with
# nothing to veto.


def _mutex_acquire():
    """Take the git mutex, returning its fd. Waits indefinitely, but never silently: after
    CLAUDE_TODO_MUTEX_WAIT seconds (default 30) it prints, to stderr and then every interval, who
    probably holds it — so a hung credential prompt under `/sync` is diagnosable rather than an
    unexplained hang. The holder stamps its pid/command into the (otherwise empty) mutex file."""
    try:
        interval = float(os.environ.get("CLAUDE_TODO_MUTEX_WAIT", "30"))
    except ValueError:
        interval = 30.0
    fd = os.open(state_path() + ".gitmutex", os.O_RDWR | os.O_CREAT, 0o644)
    start = time.monotonic()
    next_note = start + interval
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            pass
        now = time.monotonic()
        if now >= next_note:
            try:
                holder = os.pread(fd, 512, 0).decode("utf-8", "replace").strip()
            except OSError:
                holder = ""
            print(f"… still waiting for the git mutex after {now - start:.0f}s; held by "
                  f"{holder or 'an unknown process (no holder recorded)'} — if that is a hung "
                  "git/credential prompt, kill it.", file=sys.stderr)
            next_note = now + interval
        time.sleep(0.2)
    try:
        os.ftruncate(fd, 0)
        os.pwrite(fd, f"pid {os.getpid()}: todo-lock.py {' '.join(sys.argv[1:3])}".encode(), 0)
    except OSError:
        pass
    return fd


def _mutex_release(fd):
    try:
        os.ftruncate(fd, 0)
    except OSError:
        pass
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


class GitMutex:
    """The repo-wide git mutex `git-mutex` and `land` take, as a context manager — serializing
    index-touching git ops across worktrees so a `--commit` can't race a parallel /finish.

    LOCK ORDER: GitMutex OUTERMOST, then State(), then StoreLock(). `land` nests the other way
    (mutex, then StoreLock via _land_remove_todo) and deliberately closes its State() block before
    opening the mutex — so no path holds State/StoreLock while reaching for the mutex, and there is
    no cycle. Take the mutex before the store locks here and it stays that way."""

    def __enter__(self):
        self._fd = _mutex_acquire()
        return self

    def __exit__(self, *exc):
        _mutex_release(self._fd)


def _commit_target():
    """Where a `--commit` add writes and commits: (main-tree path, store path, store path relative
    to the main tree, error message). `--commit` retargets the store to the MAIN worktree's copy,
    which is the whole point: the item must land on `main`, claimable by another tab, never riding
    the caller's branch. A CLAUDE_TODO_FILE override outside the main tree has no valid pathspec,
    so it's refused rather than guessed at."""
    maintree = main_tree()
    store = main_todo_path()
    rel = os.path.relpath(store, maintree)
    if rel.startswith(".." + os.sep) or os.path.isabs(rel):
        return None, None, None, (f"--commit needs the store inside the main worktree, but "
                                  f"{store} is outside {maintree} (CLAUDE_TODO_FILE override?)")
    return maintree, store, rel, None


def _commit_precheck(maintree, rel):
    """Refuse a `--commit` when the main tree is dirty with anything OTHER than the store — those
    changes are someone else's, and the commit must never sweep them up. (The commit below is a
    pathspec commit, which already can't stage them; this catches the situation early, before
    anything is written, and says so.) A dirty store file is NOT refused: that's precisely the
    stuck state this flag exists to undo, and it's the file we're about to rewrite anyway — the
    caller just reports that it rode along. Returns (ok, message)."""
    out = subprocess.run(
        ["git", "-C", maintree, "status", "--porcelain", "--"],
        capture_output=True, text=True,
    ).stdout
    others, store_dirty = [], False
    for line in out.split("\n"):
        if not line.strip():
            continue
        path = line[3:].split(" -> ")[-1].strip().strip('"')
        if os.path.normpath(path) == os.path.normpath(rel):
            store_dirty = True
        else:
            others.append(line.rstrip())
    if others:
        return False, ("DIRTY — the main working tree has uncommitted changes outside "
                       f"{rel}; commit or stash them, then retry (nothing was written):\n"
                       + "\n".join(others))
    return True, (f"note: {rel} already had uncommitted changes on main; they are included in "
                  "this commit" if store_dirty else "")


def _commit_store(maintree, rel, message):
    """Commit ONLY the store, in the MAIN tree. A pathspec commit takes that path's working-tree
    content and nothing else, so unrelated staged changes structurally cannot ride along. `-C`
    means no `cd`; never a push. Returns (short-sha, None) or (None, error message)."""
    # `add` first only so an as-yet-untracked store (a fresh install whose TODO.local.md was never
    # committed) has something to commit — a pathspec commit alone rejects an unknown path. It
    # stages this one path, which the pathspec commit below would take from the working tree
    # anyway, so it widens nothing.
    staged = subprocess.run(
        ["git", "-C", maintree, "add", "--", rel], capture_output=True, text=True,
    )
    if staged.returncode != 0:
        return None, ((staged.stderr or staged.stdout).strip()
                      or f"git add exited {staged.returncode}")
    done = subprocess.run(
        ["git", "-C", maintree, "commit", "-q", "-m", message, "--", rel],
        capture_output=True, text=True,
    )
    if done.returncode != 0:
        return None, ((done.stderr or done.stdout).strip()
                      or f"git commit exited {done.returncode}")
    sha = subprocess.run(
        ["git", "-C", maintree, "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()
    return sha, None


COMMIT_SUBJECT_MAX = 72


def _commit_message(titles, override=None):
    """The commit subject, following the repo convention: a plain description, no AI-agent
    references, no trailers. One item reads `Add TODO: <title>`; a batch is ONE commit listing what
    it covers, truncated to a sane subject length rather than running to a paragraph."""
    if override:
        return override
    if len(titles) == 1:
        return f"Add TODO: {titles[0]}"
    subject = "Add TODOs: " + "; ".join(titles)
    if len(subject) > COMMIT_SUBJECT_MAX:
        kept = []
        for t in titles:
            trial = "Add TODOs: " + "; ".join(kept + [t]) + "; …"
            if kept and len(trial) > COMMIT_SUBJECT_MAX:
                break
            kept.append(t)
        subject = "Add TODOs: " + "; ".join(kept) + ("; …" if len(kept) < len(titles) else "")
    return subject


def _add_commit_flags(ap):
    """The `--commit`/`--message` pair, identical on `add` and `add-bulk`."""
    ap.add_argument("--commit", action="store_true",
                    help="write the item to the MAIN worktree's store and commit it there, under "
                         "the git mutex — so it lands on `main` and another tab can claim it")
    ap.add_argument("-m", "--message", default=None, metavar="MSG",
                    help="commit subject override (default `Add TODO: <title>`, or "
                         "`Add TODOs: …` for a batch)")


def _body_file_flag(ap):
    """`--body-file`, the file alternative to a body on stdin (see `_read_payload`)."""
    ap.add_argument("--body-file", default=None, metavar="PATH",
                    help="read the body from this file instead of stdin (`-` is stdin) — what to "
                         "use where a heredoc is refused, e.g. inside a worktree")


def _read_payload(path=None):
    """What a body-taking subcommand reads: the file at `path`, else stdin (`-` also means stdin).
    Returns `(text, source, err)` — `source` names the origin for the caller's empty-input message,
    `err` is set when the file can't be read. The text is raw, so a caller strips exactly as it
    did for stdin and the two inputs give the same result. The file wins over piped stdin, which
    is then never read."""
    if path is None or path == "-":
        return sys.stdin.read(), "stdin", None
    try:
        with open(path, encoding="utf-8") as f:
            return f.read(), path, None
    except (OSError, UnicodeDecodeError) as e:
        return None, path, f"cannot read {path}: {e}"


def _no_inherit_flag(ap):
    """`--no-inherit`, the opt-out of `inherit_bullets` (FEAT-15); a no-op where the key is unset."""
    ap.add_argument("--no-inherit", action="store_true",
                    help="don't copy the claimed item's `inherit_bullets` into the new item(s); "
                         "accepted, and inert, when `inherit_bullets` isn't configured")


def cmd_add(argv):
    ap = _ArgParser(prog="todo-lock.py add", add_help=False)
    ap.add_argument("--id", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--admin", action="store_true", help="add under ## Admin (a human task)")
    ap.add_argument("--priority", action="store_true",
                    help="claim this Open item ahead of every non-priority item")
    ap.add_argument("--critical", action="store_true",
                    help="hard-gate the whole queue behind this Open item — stronger than "
                         "--priority; see the module docstring's `next` outcomes")
    ap.add_argument("--blocked-by", default=None, metavar="BLOCKER-ID",
                    help="mark this Open item blocked on an Admin task or another Open item")
    ap.add_argument("--effort", default=None, metavar="PCT|TIER",
                    help="level of effort: a 0–100 percentage, or a tier name "
                         "(sonnet|opus|fable) mapped to a representative percentage")
    ap.add_argument("--route", default=None, metavar="ROUTE",
                    help="the named route to file under (see `routes`); written as a "
                         "`- **Route:** <name>` bullet. Can't combine with --effort")
    _no_inherit_flag(ap)
    _body_file_flag(ap)
    _add_commit_flags(ap)
    opts = ap.parse_args(argv)
    if not ID_RE.fullmatch(opts.id):
        print(f"ERROR — id {opts.id!r} must match <LETTERS>-<number> (e.g. TASK-4)")
        return 2
    if opts.priority and opts.admin:
        print("ERROR — --priority is for Open items, not Admin tasks (Admin tasks are never claimed)")
        return 2
    if opts.critical and opts.admin:
        print("ERROR — --critical is for Open items, not Admin tasks (Admin tasks are never claimed)")
        return 2
    if opts.critical and opts.blocked_by:
        print("ERROR — a blocked item can't be critical; it isn't claimable until it's unblocked")
        return 2
    if opts.critical and opts.priority:
        print("ERROR — --critical already outranks --priority; combining them is redundant")
        return 2
    if opts.blocked_by:
        if not ID_RE.fullmatch(opts.blocked_by):
            print(f"ERROR — --blocked-by {opts.blocked_by!r} must be an item id (e.g. FMT-0 or ADMIN-1)")
            return 2
        if opts.blocked_by == opts.id:
            print("ERROR — an item can't block itself")
            return 2
    effort_pct = None
    if opts.effort is not None:
        effort_pct, err = _parse_effort(opts.effort)
        if err:
            print(f"ERROR — --effort {err}")
            return 2
    route = None
    if opts.route is not None:
        if opts.effort is not None:
            print("ERROR — --route and --effort both set the route; pass one")
            return 2
        route, err = _parse_route(opts.route)
        if err:
            print(f"ERROR — --route {err}")
            return 2
    problem = validate_title(opts.title)
    if problem:
        print(f"ERROR — --title {problem}. Nothing was written.")
        return 2
    body, _, err = _read_payload(opts.body_file)
    if err:
        print(f"ERROR — {err}. Nothing was written.")
        return 2
    body = body.strip("\n")
    parent, bullets = _inherit_parent(opts.no_inherit)
    body, inherited = _inherit_into(body, bullets)
    problem = validate_body(body.split("\n"))
    if problem:
        print(f"ERROR — the body's {problem}. Nothing was written.")
        return 2
    maintree = store = rel = None
    if opts.commit:
        maintree, store, rel, err = _commit_target()
        if err:
            print(f"ERROR — {err}")
            return 2
    block = _render_item(opts.id, opts.title, body,
                         priority=opts.priority, critical=opts.critical,
                         blockers=[opts.blocked_by] if opts.blocked_by else [],
                         effort_pct=effort_pct, route=route.name if route else None)
    # --commit wraps everything in the git mutex (outermost — see GitMutex on the lock order), so
    # the write and its commit are one section no parallel /finish `land` can interleave with.
    # Without it, `store` is None and every store call falls back to the caller's own tree exactly
    # as before.
    note = sha = None
    with GitMutex() if opts.commit else contextlib.nullcontext():
        if opts.commit:
            ok, note = _commit_precheck(maintree, rel)
            if not ok:
                print(note)
                return 2
        # State outer, StoreLock inner (the established order — see cmd_next/cmd_append): the store
        # write and the per-family high-water-mark bump must land together under one atomic section.
        with State() as st, StoreLock():
            lines = read_lines(store)
            items = parse_items(lines)
            if find_item(items, opts.id):
                print(f"ERROR — {opts.id} already exists (use `append {opts.id}` to extend it)")
                return 2
            if opts.blocked_by:
                if find_item(items, opts.blocked_by) is None:
                    print(f"ERROR — --blocked-by {opts.blocked_by} references no existing item "
                          "(a marker that matches nothing would be silently stripped by `next`)")
                    return 2
                # Same rule `block`/`add-bulk`/`reorder` apply: a cycle deadlocks `next`.
                deps = {i["id"]: set(i["blockers"]) for i in items}
                deps[opts.id] = {opts.blocked_by}
                cyc = _detect_cycle(deps)
                if cyc:
                    print(f"ERROR — blocking {opts.id} on {opts.blocked_by} would make the "
                          "[BLOCKED] graph cyclic: " + " -> ".join(cyc))
                    return 2
            top = _open_top(lines) if (opts.priority or opts.critical) else None
            if opts.admin:
                lines, at = _insert_admin_section(lines)
                lines = lines[:at] + ["", *block] + lines[at:]
            elif top is not None:
                # Lead the ## Open section so summary order matches claim order (next also sorts
                # priority-first, so this is really cosmetic — but a consistent view helps).
                lines = lines[:top] + [*block, ""] + lines[top:]
            else:
                while lines and lines[-1] == "":
                    lines.pop()
                lines = lines + ["", *block, ""]
            write_store(lines, [i["id"] for i in items] + [opts.id], store)
            _bump_next_id(st, opts.id)
            st.save()
            _hook_queue("add", opts.id, block, worktree="", branch="")
        if opts.commit:
            sha, err = _commit_store(maintree, rel, _commit_message([opts.title], opts.message))
            if err:
                print(f"ERROR — added {opts.id} to {rel} on main, but the commit FAILED: {err}")
                print(f"The main tree is left dirty (which `land` rejects) — commit {rel} there by "
                      "hand, or fix the cause and retry.")
                return 1
    tag = " (admin)" if opts.admin else (" (critical)" if opts.critical
                                        else (" (priority)" if opts.priority else ""))
    print(f"OK added {opts.id}{tag}" + (f" to {rel} on main" if opts.commit else ""))
    if inherited:
        print(f"inherited {', '.join(inherited)} from {parent}")
    if not opts.admin:
        print(_route_echo(block[1:]))
    if note:
        print(note)
    if sha:
        print(f"OK committed {sha} on main ({rel})")
    _print_warnings(opts.id, _write_warnings(opts.title, body.split("\n")))
    return 0


BULK_KEYS = {"id", "title", "body", "admin", "priority", "blocked_by", "effort", "route", "inherit"}
# A bare id family for --family: the `[A-Z]{2,}` half of ID_RE, with no number.
FAMILY_RE = re.compile(r"^[A-Z]{2,}$")


def cmd_add_bulk(argv):
    """Add many items in ONE atomic store write — the batch form of `add`, for a request that
    decomposes into several items. Items arrive as a JSON array on stdin (JSON because bodies are
    multi-line markdown, where any delimiter format would collide with body content).

    Three things make this more than a loop over `cmd_add`:
      - **One lock section for the batch.** `State()` outer, `StoreLock()` inner (the established
        order — see cmd_add/cmd_next/cmd_append), taken once. A loop would take the pair N times,
        letting another tab interleave its own add mid-batch.
      - **Validate everything, then write once.** An invalid or duplicate id, a bad effort, a cycle
        — any of them aborts non-zero with TODO.local.md byte-identical, because the single
        `write_lines` is the last thing that happens.
      - **Group-wise splicing, so file order matches input order.** Inserting priority items one at
        a time would *reverse* consecutive ones (each new one leads `## Open`); one splice per
        section does not.
    """
    ap = _ArgParser(prog="todo-lock.py add-bulk", add_help=False)
    ap.add_argument("--chain", action="store_true",
                    help="block each item on the one before it, so the declared order is the "
                         "order /plan-todo hands them out")
    ap.add_argument("--family", default=None, metavar="FAMILY",
                    help="id family for items that omit \"id\", numbered off the same monotonic "
                         "counter `next-id` uses")
    ap.add_argument("--file", default=None, metavar="PATH",
                    help="read the JSON array from this file instead of stdin (`-` is stdin) — "
                         "what to use where a heredoc is refused, e.g. inside a worktree")
    _no_inherit_flag(ap)
    _add_commit_flags(ap)
    opts = ap.parse_args(argv)
    if opts.family is not None and not FAMILY_RE.fullmatch(opts.family):
        print(f"ERROR — --family {opts.family!r} must be a bare id family — 2+ uppercase letters, "
              "no number (e.g. FEAT)")
        return 2
    raw, source, err = _read_payload(opts.file)
    if err:
        print(f"ERROR — {err}. Nothing was written.")
        return 2
    raw = raw.strip()
    if not raw:
        print(f'ERROR — {source} is empty; add-bulk reads a JSON array of items, on stdin or from '
              '--file: [{"title": "…", "body": "- **What:** …"}, …]')
        return 2
    try:
        batch = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"ERROR — {source} is not valid JSON: {e}")
        return 2
    if not isinstance(batch, list) or not batch:
        print("ERROR — stdin must be a non-empty JSON ARRAY of item objects")
        return 2

    # -- validate everything checkable without the store, for every item, before taking a lock --
    specs = []
    for n, obj in enumerate(batch, 1):
        where = f"item {n}"
        if not isinstance(obj, dict):
            print(f"ERROR — {where} is not a JSON object")
            return 2
        unknown = sorted(set(obj) - BULK_KEYS)
        if unknown:
            print(f"ERROR — {where} has unknown field(s) {', '.join(unknown)} — allowed: "
                  f"{', '.join(sorted(BULK_KEYS))}")
            return 2
        title = obj.get("title")
        if not isinstance(title, str) or not title.strip():
            print(f'ERROR — {where} needs a non-empty "title"')
            return 2
        problem = validate_title(title)
        if problem:
            print(f'ERROR — {where}: "title" {problem}')
            return 2
        body = obj.get("body")
        if not isinstance(body, str):
            print(f'ERROR — {where} needs a "body" string (use "" for an item with no body)')
            return 2
        # Here an unsafe body would swallow every item spliced in after it, since the whole batch
        # lands in one write.
        problem = validate_body(body.strip("\n").split("\n"))
        if problem:
            print(f"ERROR — {where}'s body: {problem} (and would swallow the items after it)")
            return 2
        item_id = obj.get("id")
        if item_id is not None:
            if not isinstance(item_id, str) or not ID_RE.fullmatch(item_id):
                print(f"ERROR — {where}: id {item_id!r} must match <LETTERS>-<number> "
                      "(e.g. TASK-4)")
                return 2
        elif opts.family is None:
            print(f'ERROR — {where} has no "id", and no --family to number it from')
            return 2
        admin, priority = obj.get("admin", False), obj.get("priority", False)
        for field, val in (("admin", admin), ("priority", priority)):
            if not isinstance(val, bool):
                print(f'ERROR — {where}: "{field}" must be true or false, not {val!r}')
                return 2
        inherit = obj.get("inherit", True)
        if not isinstance(inherit, bool):
            print(f'ERROR — {where}: "inherit" must be true or false, not {inherit!r}')
            return 2
        blocked_by = obj.get("blocked_by")
        if blocked_by is not None and not (isinstance(blocked_by, str)
                                           and ID_RE.fullmatch(blocked_by)):
            print(f'ERROR — {where}: "blocked_by" {blocked_by!r} must be an item id '
                  "(e.g. FMT-0 or ADMIN-1)")
            return 2
        # The one combination `add` still refuses, for the same reason.
        if priority and admin:
            print(f'ERROR — {where}: "priority" is for Open items, not Admin tasks '
                  "(Admin tasks are never claimed)")
            return 2
        # Decided up front rather than left to fail deep in the loop: every item after the first
        # is blocked on its predecessor, and a blocked item is never auto-claimed — so in a chain
        # only the FIRST item could ever be priority (and an Admin task is never claimed at all).
        if opts.chain and (priority or admin):
            print(f'ERROR — {where}: --chain can\'t combine with "priority"/"admin" — a chained '
                  "item is blocked on the one before it, and a blocked item is never auto-claimed. "
                  "Chain the ordinary items and add any priority/admin item separately.")
            return 2
        effort_pct = None
        if obj.get("effort") is not None:
            effort_pct, err = _parse_effort(obj["effort"])
            if err:
                print(f'ERROR — {where}: "effort" {err}')
                return 2
        route = None
        if obj.get("route") is not None:
            if effort_pct is not None:
                print(f'ERROR — {where}: "route" and "effort" both set the route; pass one')
                return 2
            route, err = _parse_route(obj["route"])
            if err:
                print(f'ERROR — {where}: "route" {err}')
                return 2
        specs.append({"id": item_id, "title": title, "body": body.strip("\n"), "admin": admin,
                      "priority": priority, "blocked_by": blocked_by, "effort": effort_pct,
                      "route": route.name if route else None, "inherit": inherit})

    # Inheritance happens here, before any write, so a batch the store then rejects was never
    # changed by it. The parent is resolved once for the whole batch.
    parent, bullets = _inherit_parent(opts.no_inherit)
    for n, s in enumerate(specs, 1):
        s["inherited"], s["parent"] = [], parent
        if s["inherit"] and bullets:
            s["body"], s["inherited"] = _inherit_into(s["body"], bullets)
            problem = validate_body(s["body"].split("\n"))
            if problem:
                print(f"ERROR — item {n}'s body: {problem} (and would swallow the items after it)")
                return 2
    return _add_bulk_store(specs, opts)


def _add_bulk_write(specs, opts, store):
    """The batch's single store write: resolve --family numbers, reject duplicates and cycles, then
    splice every item in one `write_lines`. Split out of `cmd_add_bulk` so `--commit` can wrap it in
    the git mutex without this block changing shape. Mutates `specs` in place (ids, blockers) and
    returns 0, or prints and returns 2 with the store byte-identical."""
    # One State()+StoreLock() section around the whole batch.
    with State() as st, StoreLock():
        lines = read_lines(store)
        items = parse_items(lines)
        existing = {it["id"] for it in items}
        if opts.family:
            # Same ceiling `next-id` hands out from (persisted high-water mark + the numbers in the
            # store), raised by any id this batch spells out for that family — so an auto-assigned
            # number can't collide with one of its own batch-mates.
            explicit = [s["id"] for s in specs if s["id"]]
            nums = _family_numbers(items, opts.family) + _family_numbers(
                [{"id": i} for i in explicit], opts.family)
            nxt = _family_ceiling(st, opts.family, nums)
            for s in specs:
                if not s["id"]:
                    nxt += 1
                    s["id"] = f"{opts.family}-{nxt}"
        # Duplicates against the store (as `add` checks) AND within the batch (which `add` never
        # has to): two items sharing an id would collapse into one unparseable pair of sections.
        seen = set()
        for s in specs:
            if s["id"] in seen:
                print(f"ERROR — {s['id']} appears twice in the batch")
                return 2
            seen.add(s["id"])
            if s["id"] in existing:
                print(f"ERROR — {s['id']} already exists (use `append {s['id']}` to extend it)")
                return 2
        # --chain gates each item on the one before it; an item's own "blocked_by" rides alongside
        # (the heading takes repeated `[BLOCKED: …]` markers, as `block` writes them). A blocker
        # must exist — in the store or elsewhere in this batch, so a forward reference inside the
        # batch is fine. A cycle is not: every item in one would wait on another that never clears.
        for i, s in enumerate(specs):
            s["blockers"] = [specs[i - 1]["id"]] if (opts.chain and i) else []
            if s["blocked_by"] and s["blocked_by"] not in s["blockers"]:
                s["blockers"].append(s["blocked_by"])
            if s["id"] in s["blockers"]:
                print(f"ERROR — {s['id']} can't block itself")
                return 2
            for b in s["blockers"]:
                if b not in existing and b not in seen:
                    print(f"ERROR — {s['id']}: blocker {b} references no existing item or item "
                          "in this batch (a marker that matches nothing would be silently "
                          "stripped by `next`)")
                    return 2
        cyc = _detect_cycle({s["id"]: {b for b in s["blockers"] if b in seen} for s in specs})
        if cyc:
            print("ERROR — the batch's block graph is cyclic: " + " -> ".join(cyc))
            return 2

        # Render, then splice group-wise — one splice per section, each carrying its items in
        # input order (see the docstring: per-item inserts would reverse consecutive priority
        # items). Each splice shape is `add`'s, generalised from one block to N.
        block = {s["id"]: _render_item(s["id"], s["title"], s["body"], priority=s["priority"],
                                       blockers=s["blockers"], effort_pct=s["effort"],
                                       route=s["route"])
                 for s in specs}
        for s in specs:
            s["rendered"] = block[s["id"]]  # the success report echoes each item's route from it
        admin_bs = [block[s["id"]] for s in specs if s["admin"]]
        prio_bs = [block[s["id"]] for s in specs if s["priority"]]
        plain_bs = [block[s["id"]] for s in specs if not s["admin"] and not s["priority"]]
        if admin_bs:
            lines, at = _insert_admin_section(lines)
            lines = lines[:at] + [ln for b in admin_bs for ln in ("", *b)] + lines[at:]
        if prio_bs:
            top = _open_top(lines)  # recomputed — the Admin splice above may have moved it
            if top is None:
                # No `## Open` section to lead; fall back to appending, as `add` does. Rebuilt from
                # `specs` rather than concatenated, so the appended items keep their declared order.
                plain_bs = [block[s["id"]] for s in specs if not s["admin"]]
            else:
                lines = lines[:top] + [ln for b in prio_bs for ln in (*b, "")] + lines[top:]
        if plain_bs:
            while lines and lines[-1] == "":
                lines.pop()
            lines = lines + [ln for b in plain_bs for ln in ("", *b)] + [""]
        write_store(lines, [it["id"] for it in items] + [s["id"] for s in specs], store)
        for s in specs:
            _bump_next_id(st, s["id"])  # every id written, or `next-id` reissues it after a remove
        st.save()
    return 0


def _add_bulk_store(specs, opts):
    """Write the validated batch, and under `--commit` do it in the MAIN tree inside the git mutex,
    finishing with ONE commit for the whole batch (never one per item — the set is already a single
    atomic store write, and one commit is what the repo convention asks for)."""
    maintree = store = rel = None
    if opts.commit:
        maintree, store, rel, err = _commit_target()
        if err:
            print(f"ERROR — {err}")
            return 2
    note = sha = None
    with GitMutex() if opts.commit else contextlib.nullcontext():
        if opts.commit:
            ok, note = _commit_precheck(maintree, rel)
            if not ok:
                print(note)
                return 2
        rc = _add_bulk_write(specs, opts, store)
        if rc:
            return rc
        if opts.commit:
            sha, err = _commit_store(maintree, rel,
                                     _commit_message([s["title"] for s in specs], opts.message))
            if err:
                print(f"ERROR — added {len(specs)} item(s) to {rel} on main, but the commit "
                      f"FAILED: {err}")
                print(f"The main tree is left dirty (which `land` rejects) — commit {rel} there by "
                      "hand, or fix the cause and retry.")
                return 1
    for s in specs:
        tag = " (admin)" if s["admin"] else (" (priority)" if s["priority"] else "")
        print(f"OK added {s['id']}{tag}" + (f" to {rel} on main" if opts.commit else ""))
        if s["inherited"]:
            print(f"inherited {', '.join(s['inherited'])} from {s['parent']}")
        if not s["admin"]:
            print(_route_echo(s["rendered"][1:], s["id"]))
        _print_warnings(s["id"], _write_warnings(s["title"], s["body"].split("\n")))
        _hook_queue("add", s["id"], s["rendered"], worktree="", branch="")
    if note:
        print(note)
    if sha:
        print(f"OK committed {sha} on main ({rel}) — one commit for the batch")
    return 0


def _committed_subject(cmd, ids, titles):
    """The default `--commit` subject for a STORE_COMMITTERS command — plain, like `add`'s.
    `titles` is {id: title} read BEFORE the command ran, so an item it deletes still has one."""
    first = ids[0] if ids else "?"
    title = titles.get(first, "")
    named = f"{first}: {title}" if title else first
    if cmd == "reorder":
        return "Reorder TODO backlog"
    if cmd == "repair":
        return "Repair TODO.local.md formatting"
    if cmd == "admin-done":
        return f"Complete admin task {named}"
    if cmd == "merge" and len(ids) >= 2:
        return f"Merge TODO {ids[1]} into {named}"
    if cmd == "block":
        return f"Block TODO {first} on {', '.join(ids[1:])}"
    verb = {"append": "Append to TODO", "edit": "Edit TODO", "set-effort": "Set route of TODO",
            "set-files": "Set files of TODO"}.get(cmd, f"Update TODO ({cmd})")
    return f"{verb} {named}"


def _run_committed(cmd, argv):
    """`<cmd> … --commit [-m MSG]` for every store writer but `add`/`add-bulk` (which carry their own):
    run the command against the MAIN tree's store and commit ONLY the store there, with the same
    helpers, mutex and DIRTY precheck `add --commit` uses (see the `--commit` note above
    `_mutex_acquire`). GitMutex is outermost, so the command's own State/StoreLock nest inside it.
    A run that leaves the store clean commits nothing; a failing run is never committed."""
    ap = _ArgParser(prog=f"todo-lock.py {cmd}", add_help=False, allow_abbrev=False)
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("-m", "--message", default=None)
    opts, rest = ap.parse_known_args(argv)
    maintree, store, rel, err = _commit_target()
    if err:
        print(f"ERROR — {err}")
        return 2
    with GitMutex():
        ok, note = _commit_precheck(maintree, rel)
        if not ok:
            print(note)
            return 2
        items = parse_items(read_lines(store)) if os.path.exists(store) else []
        titles = {it["id"]: _plain_title(it) for it in items}
        rc = COMMANDS[cmd](rest)
        dirty = subprocess.run(["git", "-C", maintree, "status", "--porcelain", "--", rel],
                               capture_output=True, text=True).stdout.strip()
        if rc != 0:
            if dirty:
                print(f"note: {rel} was left uncommitted on main — `{cmd}` did not succeed; "
                      f"resolve what it reports and re-run with --commit")
            return rc
        if not dirty:
            print(f"note: {rel} unchanged — nothing to commit")
            return 0
        ids = [t for t in rest if ID_RE.fullmatch(t)]
        sha, err = _commit_store(maintree, rel,
                                 opts.message or _committed_subject(cmd, ids, titles))
        if err:
            print(f"ERROR — `{cmd}` wrote {rel} on main, but the commit FAILED: {err}")
            print(f"The main tree is left dirty (which `land` rejects) — commit {rel} there by "
                  "hand, or fix the cause and retry.")
            return 1
    if note:
        print(note)
    print(f"OK committed {sha} on main ({rel})")
    return 0


# @fragment 13_store_edit.py
# ---------------------------------------------------------------------------
# Store edits — append, edit, set-effort/set-files, block, remove, merge, admin-done, reorder
# ---------------------------------------------------------------------------

def _id_and_body_file(prog, argv):
    """`<id> [--body-file PATH]`, the whole argument list of `append` and `edit`."""
    ap = _ArgParser(prog=f"todo-lock.py {prog}", add_help=False)
    ap.add_argument("id")
    _body_file_flag(ap)
    opts = ap.parse_args(argv)
    return opts.id, opts.body_file


def cmd_append(argv):
    item_id, body_file = _id_and_body_file("append", argv)
    text, source, err = _read_payload(body_file)
    if err:
        print(f"ERROR — {err}. Nothing was written.")
        return 2
    text = text.strip("\n")
    if not text:
        print(f"ERROR — nothing on {source} to append")
        return 2
    problem = validate_body(text.split("\n"))
    if problem:
        print(f"ERROR — the appended text's {problem}. Nothing was written.")
        return 2
    # Hold the claim lock across the whole check-and-append (mirrors cmd_next's check-and-claim)
    # so a concurrent `next` can't claim item_id in the gap between the check and the write.
    with State() as st:
        claim = st.claims.get(item_id)
        if claim is not None:
            wt = claim.get("worktree") or "(not yet attached to a worktree)"
            print(
                f"ERROR — {item_id} is claimed (in progress) in worktree {wt} — "
                "/plan-todo snapshots the item body at claim time, so an append here would never "
                "reach that worktree and would be silently discarded when its /finish removes the "
                "item. Add a new item that references it instead."
            )
            return 2
        with StoreLock():
            lines = read_lines()
            items = parse_items(lines)
            it = find_item(items, item_id)
            if it is None:
                print(f"ERROR — no item {item_id} to append to")
                return 2
            insert_at = it["end"]
            # Drop a trailing blank inside the section so appended lines sit flush.
            while insert_at > it["start"] + 1 and lines[insert_at - 1] == "":
                insert_at -= 1
            new = lines[:insert_at] + text.split("\n") + [""] + lines[insert_at:]
            write_store(new, [i["id"] for i in items])
    print(f"OK appended to {item_id}")
    _print_warnings(item_id, _write_warnings(None, it["body"][1:] + text.split("\n")))
    return 0


def cmd_edit(argv):
    """Replace an item's whole body in place, from stdin or `--body-file` — the SET to `show`'s
    GET. The `### <id> — title` heading (and thus its [PRIORITY]/[BLOCKED] markers and file
    position) is preserved; only the body between this heading and the next boundary is swapped.
    Guarded like `append`: refused if the item is claimed (its body is snapshotted in a worktree).
    A body that would change the store's item set — e.g. someone pastes `show`'s output back,
    re-injecting the `### <id>` heading — is refused via a fence-aware re-parse, so `edit` can
    never split or duplicate an item."""
    item_id, body_file = _id_and_body_file("edit", argv)
    text, source, err = _read_payload(body_file)
    if err:
        print(f"ERROR — {err}. Nothing was written.")
        return 2
    text = text.strip("\n")
    if not text:
        print(f"ERROR — nothing on {source}; `edit` replaces an item's body, so it needs the new body")
        return 2
    # Claim lock outside the store lock (mirrors cmd_append) so a concurrent `next` can't claim
    # item_id between the check and the write.
    with State() as st:
        claim = st.claims.get(item_id)
        if claim is not None:
            wt = claim.get("worktree") or "(not yet attached to a worktree)"
            print(
                f"ERROR — {item_id} is claimed (in progress) in worktree {wt} — "
                "/plan-todo snapshots the item body at claim time, so an edit here would never "
                "reach that worktree and would be silently discarded when its /finish removes the "
                "item. Add a new item that references it instead."
            )
            return 2
        with StoreLock():
            lines = read_lines()
            items = parse_items(lines)
            it = find_item(items, item_id)
            if it is None:
                print(f"ERROR — no item {item_id} to edit")
                return 2
            # Keep everything up to and including the heading; keep the boundary onward (it["end"]
            # already excludes a trailing section-intro blockquote, so a following item's `> …` note
            # is preserved). One clean blank separator: none if `after` already opens with a blank
            # (a trailing note / EOF gap), else one.
            body = text.split("\n")
            # Corruption guard. The splice only inserts `body` between the preserved heading and the
            # preserved tail, so the *only* way the new content can restructure the store is a
            # boundary line inside the body itself, or a fence it leaves open (`validate_body`).
            # Refuse such a body, writing nothing — the likeliest cause is pasting `show`'s output
            # (which leads with the `### <id>` heading) back in; `edit` sets only the body.
            problem = validate_body(body)
            if problem:
                hint = (f" (did you paste {item_id}'s heading back in? `edit` sets only the body; "
                        "the heading is preserved automatically)" if body[0].startswith("### ")
                        else "")
                print(f"ERROR — the new body would restructure the store: {problem}{hint}. "
                      "Nothing was written.")
                return 2
            before = lines[:it["start"] + 1]
            after = lines[it["end"]:]
            sep = [] if (after and after[0].strip() == "") else [""]
            write_store(before + body + sep + after, [i["id"] for i in items])
    print(f"OK edited {item_id}")
    _print_warnings(item_id, _write_warnings(None, body))
    return 0


def _parse_route_or_effort(raw):
    """`set-effort`/`merge --effort`'s value: a route name (checked first), else a legacy 0–100
    percentage or tier name. Returns (Route|None, pct|None, error|None)."""
    route, _ = _parse_route(raw)
    if route:
        return route, None, None
    pct, err = _parse_effort(raw)
    if err:
        names = "|".join(_routing()["by_name"])
        return None, None, f"must be a route name ({names}), a 0–100 percentage or a tier name, not {raw!r}"
    return None, pct, None


def _put_bullet(body, drop, new_line):
    """`body` with every line matching one of the `drop` patterns removed and `new_line` written
    where the first of them was — or, if none was there, after the last non-blank line, so the
    item's trailing blank separator stays where it is."""
    out, at = [], None
    for line in body:
        if any(p.match(line) for p in drop):
            if at is None:
                at = len(out)
            continue
        out.append(line)
    if at is None:
        at = len(out)
        while at > 0 and out[at - 1].strip() == "":
            at -= 1
    return out[:at] + [new_line] + out[at:]


def _set_route_bullet(body, route=None, pct=None):
    """Give `body` exactly one routing bullet — `- **Route:** <name>` for a route, else
    `- **Effort:** NN%` — replacing every Route/Effort bullet (a Route bullet outranks Effort, so
    leaving one of either behind would route the item somewhere else). What `set-effort` and
    `merge --effort` write, so no prompt ever hand-writes the bullet."""
    line = f"- **Route:** {route.name}" if route else f"- **Effort:** {pct}%"
    return _put_bullet(body, (ROUTE_LOOSE_RE, EFFORT_LOOSE_RE), line)


def _rewrite_item_body(item_id, action, transform):
    """Apply `transform(body_lines) -> body_lines` to one Open or Admin item's body (the lines under
    its heading) and write it back — guarded like `edit`: refused for a claimed item, and for a
    result `validate_body` rejects. Returns (rc, new_body)."""
    with State() as st:
        claim = st.claims.get(item_id)
        if claim is not None:
            wt = claim.get("worktree") or "(not yet attached to a worktree)"
            print(f"ERROR — {item_id} is claimed (in progress) in worktree {wt} — /plan-todo "
                  f"snapshots the item body at claim time, so {action} here would never reach that "
                  "worktree. Nothing was written.")
            return 2, None
        with StoreLock():
            lines = read_lines()
            items = parse_items(lines)
            it = find_item(items, item_id)
            if it is None:
                print(f"ERROR — no item {item_id} ({action})")
                return 2, None
            body = transform(lines[it["start"] + 1:it["end"]])
            problem = validate_body(body)
            if problem:
                print(f"ERROR — the new body would restructure the store: {problem}. "
                      "Nothing was written.")
                return 2, None
            write_store(lines[:it["start"] + 1] + body + lines[it["end"]:],
                        [i["id"] for i in items])
    return 0, body


def cmd_set_effort(argv):
    """Set one item's route (or legacy Effort %) without a `show`→`edit` round trip of its body."""
    ap = _ArgParser(prog="todo-lock.py set-effort", add_help=False)
    ap.add_argument("id")
    ap.add_argument("value", metavar="ROUTE|PCT|TIER")
    opts = ap.parse_args(argv)
    route, pct, err = _parse_route_or_effort(opts.value)
    if err:
        print(f"ERROR — {err}")
        return 2
    rc, body = _rewrite_item_body(opts.id, "a route change",
                                  lambda b: _set_route_bullet(b, route, pct))
    if rc:
        return rc
    print(f"OK set {opts.id} to " + (f"route {route.name}" if route else f"effort {pct}%"))
    print(_route_echo(body))
    return 0


def _is_continuation(line):
    """An indented non-blank line that isn't a new bullet — a wrapped bullet's second line."""
    return line[:1] in (" ", "\t") and line.strip() != "" and not re.match(r"^\s*[-*]\s", line)


def cmd_set_files(argv):
    """Replace one item's `- **Files:**` bullet (the list `next` seeds a claim from and /reorder
    chains on) without a `show`→`edit` round trip. The claim's own file list is `lock`'s."""
    ap = _ArgParser(prog="todo-lock.py set-files", add_help=False)
    ap.add_argument("id")
    ap.add_argument("paths", nargs="+")
    opts = ap.parse_args(argv)
    line = "- **Files:** " + ", ".join(f"`{p}`" for p in opts.paths)

    def transform(body):
        out, i = [], 0
        while i < len(body):
            if FILES_BULLET_RE.match(body[i]) and line not in out:
                out.append(line)
                i += 1
                while i < len(body) and _is_continuation(body[i]):
                    i += 1       # a wrapped bullet's tail goes with it
                continue
            out.append(body[i])
            i += 1
        return out if line in out else _put_bullet(out, (), line)

    rc, _ = _rewrite_item_body(opts.id, "a files change", transform)
    if rc:
        return rc
    print(f"OK set {opts.id} files: " + ", ".join(opts.paths))
    return 0


def _unblock_dependents(lines, items, blocker_id, exclude=None):
    """Strip `[BLOCKED: <blocker_id>]` off every item that depends on `blocker_id`, editing
    `lines` in place, and return the list of unblocked item ids. Heading edits don't change line
    count, so a caller can excise the blocker's own section afterward with unchanged indices.
    `exclude` is the blocker item itself, skipped so its own heading is left untouched. Only the
    leading marker run changes (`_split_heading`), never marker-like text in the title.

    Shared by `admin-done` (a human task completes) and `remove` (an Open item is finished): in
    both cases anything the id gated becomes claimable — this is the item-on-item ordering gate."""
    unblocked = []
    for it in items:
        if it is exclude or blocker_id not in it["blockers"]:
            continue
        parts = _split_heading(it["id"], it["heading"])
        parts["blockers"].remove(blocker_id)
        _set_heading(lines, it, parts)
        unblocked.append(it["id"])
    return unblocked


def _excise_start(lines, it):
    """Where cutting `it`'s section should start: its heading, or one line above to absorb a
    preceding blank, so a removal doesn't leave a double gap."""
    start = it["start"]
    return start - 1 if start > 0 and lines[start - 1] == "" else start


def _excise_item(lines, items, it, path=None):
    """Delete `it` from the store (`path`, default the main checkout's) and clear every gate it held
    — what `remove`, `admin-done` and `land` all mean by "this item is done". Dependents are
    unblocked first: heading edits don't shift indices, so `it`'s span is still valid for the cut.
    Returns the unblocked ids."""
    unblocked = _unblock_dependents(lines, items, it["id"], exclude=it)
    write_store(lines[:_excise_start(lines, it)] + lines[it["end"]:],
                [i["id"] for i in items if i is not it], path)
    return unblocked


def _retarget_dependents(lines, items, old_id, new_id, exclude=()):
    """Repoint every `[BLOCKED: <old_id>]` gate at `new_id`, editing `lines` in place, and return
    the ids whose heading changed. `exclude` is a set of ids to skip (the two items being merged).

    The `merge` counterpart to `_unblock_dependents`, and deliberately the opposite of it: `remove`
    clears a gate because the blocker's work is *finished*, but a merged-away item's work moved into
    the survivor, so its dependents must stay gated — on the survivor. Heading edits preserve the
    line count (same idiom as `_unblock_dependents`), so a caller can excise the absorbed section
    afterward with unchanged indices. A dependent already blocked on `new_id` just loses the now
    duplicate marker."""
    moved = []
    for it in items:
        if it["id"] in exclude or old_id not in it["blockers"]:
            continue
        parts = _split_heading(it["id"], it["heading"])
        bs = [b for b in parts["blockers"] if b != old_id]
        if new_id not in bs:
            bs.insert(0, new_id)
        parts["blockers"] = bs
        _set_heading(lines, it, parts)
        moved.append(it["id"])
    return moved


def _strip_cleared_blockers(item, existing_ids):
    """Return `item`'s heading with every `[BLOCKED: <id>]` marker whose id is NOT in
    `existing_ids` removed, keeping markers for still-existing blockers. The result is one line
    (line count preserved — callers rely on this to keep indices valid within a locked pass), and
    is the text after `### `."""
    parts = _split_heading(item["id"], item["heading"])
    parts["blockers"] = [b for b in parts["blockers"] if b in existing_ids]
    return _compose_heading(parts)


def cmd_block(argv):
    ap = _ArgParser(prog="todo-lock.py block", add_help=False)
    ap.add_argument("id")
    ap.add_argument("--blocked-by", nargs="+", required=True, metavar="BLOCKER-ID",
                    help="one or more existing item ids that must clear before this item is claimed")
    opts = ap.parse_args(argv)
    if not ID_RE.fullmatch(opts.id):
        print(f"ERROR — id {opts.id!r} must match <LETTERS>-<number> (e.g. TASK-4)")
        return 2
    # Dedupe blockers, preserving order, and validate each in isolation before touching the store.
    blockers, seen = [], set()
    for b in opts.blocked_by:
        if not ID_RE.fullmatch(b):
            print(f"ERROR — --blocked-by {b!r} must be an item id (e.g. FMT-0 or ADMIN-1)")
            return 2
        if b == opts.id:
            print("ERROR — an item can't block itself")
            return 2
        if b not in seen:
            seen.add(b)
            blockers.append(b)
    # State outer, StoreLock inner (as cmd_append): the claim check and the heading write must be
    # atomic against a concurrent `next` claiming this item.
    with State() as st, StoreLock():
        lines = read_lines()
        items = parse_items(lines)
        it = find_item(items, opts.id)
        if it is None:
            print(f"ERROR — no item {opts.id} to block")
            return 2
        claim = st.claims.get(opts.id)
        if claim is not None:
            wt = claim.get("worktree") or "(not yet attached to a worktree)"
            print(f"ERROR — {opts.id} is claimed (in progress) in worktree {wt} — a claim "
                  "snapshots the item at claim time, so a gate added here would never reach that "
                  "worktree. Block a new item on it instead.")
            return 2
        for b in blockers:
            if find_item(items, b) is None:
                print(f"ERROR — blocker {b} references no existing item")
                return 2
        # Cycles deadlock `next` — every item in one waits on another that never clears — so `add`,
        # `add-bulk` and `reorder` all refuse to write one. `block` is the fourth writer of a
        # [BLOCKED] marker and must apply the same rule, through the same helper, or it becomes the
        # one way to create the graph the others reject. Built from the store's current markers, then
        # re-run with the edges this call would add (adding a marker that's already there is a no-op
        # on the graph, so this stays idempotent).
        deps = {i["id"]: set(i["blockers"]) for i in items}
        pre_existing = _detect_cycle(deps)
        deps.setdefault(opts.id, set()).update(blockers)
        cyc = _detect_cycle(deps)
        if cyc:
            # Distinguish the two, or a store that's already cyclic makes every later `block` look
            # like the call that broke it.
            if pre_existing:
                print("ERROR — the store's [BLOCKED] graph is ALREADY cyclic: "
                      + " -> ".join(pre_existing))
            else:
                print(f"ERROR — blocking {opts.id} on {', '.join(blockers)} would make the "
                      "[BLOCKED] graph cyclic: " + " -> ".join(cyc))
            print("Nothing was written. `/reorder` sets the whole Open-item chain in one call — "
                  "re-cut it there.")
            return 2
        already = set(it["blockers"])
        missing = [b for b in blockers if b not in already]
        # Markers live in the leading run after the `<ID> — ` lead, never before the item's own ID —
        # otherwise ID_RE.search would read the first blocker's id as the item's id. New gates go
        # ahead of the existing ones.
        parts = _split_heading(it["id"], it["heading"])
        # A blocked item is never auto-claimed, so critical (a hard gate on the queue) is
        # contradictory (add rejects the combination). Drop it. [PRIORITY] is kept: it only
        # orders claims, and takes effect once the gate clears.
        stripped_critical = parts["critical"]
        parts["critical"] = False
        parts["blockers"] = missing + parts["blockers"]
        if missing or stripped_critical:
            _set_heading(lines, it, parts)
            write_store(lines, [i["id"] for i in items])
    print(f"OK blocked {opts.id} on {', '.join(missing)}" if missing
          else f"OK {opts.id} already blocked on {', '.join(blockers)} (no new marker)")
    dup = [b for b in blockers if b in already]
    if missing and dup:
        print(f"note: already blocked on {', '.join(dup)}")
    if stripped_critical:
        print("note: dropped [CRITICAL] — a blocked item is never auto-claimed")
    return 0


def cmd_remove(argv):
    item_id = argv[0]
    with StoreLock():
        lines = read_lines()
        items = parse_items(lines)
        it = find_item(items, item_id)
        if it is None:
            print(f"NONE — {item_id} not in the backlog (already removed?)")
            return 1
        unblocked = _excise_item(lines, items, it)
        _hook_queue("remove", item_id, it["body"])
    print(f"OK removed {item_id}")
    if unblocked:
        print("unblocked: " + ", ".join(unblocked))
    return 0


def _swap_bullet(body, pattern, new_line):
    """Return (lines, found): `body` with the FIRST line matching `pattern` replaced by `new_line`
    (dropped when `new_line` is None), the rest untouched. First-match-wins mirrors how
    `_item_files`/`_item_effort` read these bullets, so what the readers see is what gets swapped."""
    out, found = [], False
    for line in body:
        if not found and pattern.match(line):
            found = True
            if new_line is not None:
                out.append(new_line)
            continue
        out.append(line)
    return out, found


def _trim_blanks(body, lead=True):
    """`body` without trailing blank lines (and without leading ones unless `lead=False`) — the two
    halves of a merge are joined flush, so neither half's edge whitespace becomes a gap in the
    middle of the combined item. The surviving half keeps its leading blank: that's the line under
    its `### …` heading, which every other item in the store has too."""
    lo, hi = 0, len(body)
    while lead and lo < hi and body[lo].strip() == "":
        lo += 1
    while hi > lo and body[hi - 1].strip() == "":
        hi -= 1
    return body[lo:hi]


def _plain_title(item):
    """An item's title with its `<ID> — ` lead and its [CRITICAL]/[PRIORITY]/[BLOCKED] markers
    stripped — the human half of the heading, for provenance and messages."""
    return _split_heading(item["id"], item["heading"])["title"]


def cmd_merge(argv):
    """Fold `absorbed` into `survivor`: one combined item survives under the survivor's id, file
    position and dependents; the absorbed section is removed. Its id is never reissued — `next-id`'s
    per-family high-water mark only ever grows — so a merged-away id names that one todo forever,
    same as a finished one. Which is also why the survivor is one of the two inputs and never a
    freshly minted id: the surviving item keeps a real history, not a third number.

    The reconciliation rules (one Files bullet, effort = max, markers unioned, dependents retargeted
    rather than unblocked) are spelled out in the usage block — this is /reorder's lever for two
    items that turn out to be duplicates or split halves of one task. Guarded like `edit`: refused
    if either id is claimed (a claim snapshots the body in a worktree, and that /finish deletes the
    whole section, so a merge into it would be silently discarded), and the assembled body is
    refused if it carries a store boundary line, so `parse_items` can always re-read the result."""
    ap = _ArgParser(prog="todo-lock.py merge", add_help=False)
    ap.add_argument("survivor")
    ap.add_argument("absorbed")
    ap.add_argument("--title", default=None, metavar="T",
                    help="retitle the surviving item (markers are re-applied on top)")
    ap.add_argument("--body", action="store_true",
                    help="read the merged body from stdin instead of concatenating the two")
    ap.add_argument("--effort", default=None, metavar="ROUTE|PCT|TIER",
                    help="the survivor's route (or legacy Effort %%), replacing whatever routing "
                         "bullet the merge would otherwise leave")
    _body_file_flag(ap)
    opts = ap.parse_args(argv)
    surv, absorbed = opts.survivor, opts.absorbed
    set_route = set_pct = None
    if opts.effort is not None:
        set_route, set_pct, err = _parse_route_or_effort(opts.effort)
        if err:
            print(f"ERROR — --effort {err}")
            return 2
    for label, iid in (("survivor", surv), ("absorbed", absorbed)):
        if not ID_RE.fullmatch(iid):
            print(f"ERROR — {label} id {iid!r} must match <LETTERS>-<number> (e.g. TASK-4)")
            return 2
    if surv == absorbed:
        print(f"ERROR — {surv} can't be merged into itself; pass the survivor first, then the item "
              "to fold into it")
        return 2
    if opts.title is not None:
        problem = validate_title(opts.title)
        if problem:
            print(f"ERROR — --title {problem}. Nothing was written.")
            return 2
    given_body = None
    if opts.body or opts.body_file is not None:
        given_body, source, err = _read_payload(opts.body_file)
        if err:
            print(f"ERROR — {err}. Nothing was written.")
            return 2
        given_body = given_body.strip("\n")
        if not given_body:
            print(f"ERROR — the merged body was to come from {source}, but it was empty")
            return 2

    notes = []
    # Claim lock outside the store lock (the established order — see cmd_append/cmd_edit) so a
    # concurrent `next` can't claim either id between the check and the write.
    with State() as st, StoreLock():
        for iid in (surv, absorbed):
            claim = st.claims.get(iid)
            if claim is not None:
                wt = claim.get("worktree") or "(not yet attached to a worktree)"
                print(
                    f"ERROR — {iid} is claimed (in progress) in worktree {wt} — /plan-todo "
                    "snapshots the item body at claim time, so a merge here would never reach that "
                    "worktree, and its /finish deletes the whole section. Wait for it to land (or "
                    "`release` the claim) before merging. Nothing was written."
                )
                return 2
        lines = read_lines()
        items = parse_items(lines)
        it_s = find_item(items, surv)
        it_a = find_item(items, absorbed)
        for label, iid, it in (("survivor", surv, it_s), ("absorbed", absorbed, it_a)):
            if it is None:
                print(f"ERROR — no item {iid} to merge ({label})")
                return 2
        if it_s["section"] != it_a["section"]:
            where = {"admin": "## Admin", "open": "## Open"}
            print(f"ERROR — {surv} is in {where[it_s['section']]} and {absorbed} is in "
                  f"{where[it_a['section']]}; Admin tasks are human work and Open items are agent "
                  "work, so merging across the two would lose that distinction. Nothing was written.")
            return 2

        s_body, a_body = it_s["body"][1:], it_a["body"][1:]   # body[0] is the `### …` heading line

        # -- body --------------------------------------------------------------------------
        if given_body is not None:
            body = given_body.split("\n")
        else:
            # Effort: the max of the two, where an item that declares none counts as its default
            # tier's representative percentage — otherwise folding opus-default work into a 30%
            # sonnet item would leave the survivor routed to sonnet. Both undeclared ⇒ still
            # undeclared (the default already IS that answer), so no bullet appears from nowhere.
            e_s, e_a = _item_effort(s_body), _item_effort(a_body)
            merged_effort = None
            # Route: once either side names a known route, the survivor carries ONE Route bullet —
            # the later of the two resolved routes in table order (the "bigger" route) — and every
            # Effort bullet goes, being superseded (a Route bullet outranks Effort when routing).
            by_name = _routing()["by_name"]
            merged_route = None
            if _item_route_name(s_body) in by_name or _item_route_name(a_body) in by_name:
                rank = list(by_name)
                rt_s, rt_a = _item_route(s_body), _item_route(a_body)
                merged_route = max(rt_s, rt_a, key=lambda r: rank.index(r.name))
            elif e_s is not None or e_a is not None:
                # An unmarked side counts as the default route's band (70 built in), as before.
                default = _routing()["default"].band
                if default is None:
                    default = max(r.band for r in _routing()["routes"] if r.band is not None)
                merged_effort = max(default if e_s is None else e_s,
                                    default if e_a is None else e_a)
            # Files: the bullet is advisory prose, not a structured list (`_split_declared_files`
            # only keeps path-like tokens), so join the raw texts rather than parsing them. It has
            # to end up as ONE bullet: `_item_files` reads the first match only, so a second one
            # would hide half the overlap signal /reorder chains on.
            f_s, f_a = _item_files(s_body), _item_files(a_body)
            merged_files = f_s
            if f_a and f_a not in f_s:
                merged_files = f"{f_s}; {f_a}" if f_s else f_a

            body = _trim_blanks(s_body, lead=False)
            tail = _trim_blanks(a_body)
            if merged_effort is not None:
                line = f"- **Effort:** {merged_effort}%"
                body, in_s = _swap_bullet(body, EFFORT_BULLET_RE, line if e_s is not None else None)
                # Only the survivor's bullet is rewritten in place; if it had none, the absorbed
                # item's bullet keeps its position in the appended half and carries the new value.
                tail, _ = _swap_bullet(tail, EFFORT_BULLET_RE, None if in_s else line)
                if merged_effort != e_s:
                    notes.append(f"effort → {merged_effort}% (max of "
                                 f"{e_s if e_s is not None else 'unset'}/"
                                 f"{e_a if e_a is not None else 'unset'})")
            if merged_route is not None:
                superseded = (ROUTE_LOOSE_RE, EFFORT_LOOSE_RE)
                body = [ln for ln in body if not any(p.match(ln) for p in superseded)]
                tail = [ln for ln in tail if not any(p.match(ln) for p in superseded)]
                body.append(f"- **Route:** {merged_route.name}")
                if _item_route_name(s_body) != merged_route.name:
                    notes.append(f"route → {merged_route.name} (later of {rt_s.name}/{rt_a.name})")
            if merged_files != f_s or f_a:
                body, in_s = _swap_bullet(body, FILES_BULLET_RE,
                                          f"- **Files:** {merged_files}" if f_s else None)
                if in_s:
                    tail, _ = _swap_bullet(tail, FILES_BULLET_RE, None)
                if merged_files != f_s and merged_files != f_a:
                    notes.append("files bullets joined into one")
            body = body + [f"- **Merged in:** {absorbed} — {_plain_title(it_a)}"] + tail
        if opts.effort is not None:
            # Overrides both the computed route above and any bullet a --body carried.
            notes = [n for n in notes if not n.startswith(("route →", "effort →"))]
            body = _set_route_bullet(body, set_route, set_pct)
            notes.append("route → " + (set_route.name if set_route else f"effort {set_pct}%")
                         + " (--effort)")

        # The same corruption guard `edit` applies, for the same reason: the splice below inserts
        # `body` between a preserved heading and a preserved tail, so a boundary line inside the
        # body is the one way the result could restructure the store. Both halves came OUT of the
        # store, so this only fires on a hand-written --body (or a fence left unbalanced).
        problem = validate_body(body)
        if problem:
            print(f"ERROR — the merged body would restructure the store: {problem} (the {surv} "
                  "heading is preserved automatically; don't paste it back). Nothing was written.")
            return 2

        # -- heading -----------------------------------------------------------------------
        parts = _split_heading(surv, it_s["heading"])
        if opts.title is not None:
            parts["title"] = opts.title.strip()
        # Union the gates, in the survivor's order. A marker naming either merged id is dropped:
        # blocking on the item you just absorbed (or on yourself) is vacuous after the merge.
        blockers = []
        for b in it_s["blockers"] + it_a["blockers"]:
            if b not in blockers and b not in (surv, absorbed):
                blockers.append(b)
        critical = it_s["critical"] or it_a["critical"]   # urgency survives from either side
        priority = it_s["priority"] or it_a["priority"]
        if critical and priority:
            priority = False   # critical already outranks priority — same rule `add` enforces
            notes.append("dropped [PRIORITY] — [CRITICAL] already outranks it")
        if blockers:
            # the store invariant `block` enforces: never both blocked and critical. [PRIORITY]
            # survives — it takes effect once the gate clears.
            if critical:
                critical = False
                notes.append("dropped [CRITICAL] — a blocked item is never auto-claimed")
        parts.update(blockers=blockers, critical=critical, priority=priority)

        # -- write: dependents first (heading edits preserve line count), then the two splices,
        #    applied in descending file order so the earlier one's indices stay valid -----------
        moved = _retarget_dependents(lines, items, absorbed, surv, exclude={surv, absorbed})
        new_heading = _set_heading(lines, it_s, parts)
        a_start = _excise_start(lines, it_a)               # absorb one blank, as `remove` does
        if it_a["start"] > it_s["start"]:
            # Don't reach back into the survivor's body — when the absorbed item sits directly
            # below it, the blank line above its heading is the survivor's own trailing blank,
            # already replaced by the splice.
            a_start = max(a_start, it_s["end"])
            lines = lines[:a_start] + lines[it_a["end"]:]
            before, after = lines[:it_s["start"] + 1], lines[it_s["end"]:]
        else:
            before, after = lines[:it_s["start"] + 1], lines[it_s["end"]:]
            before = before[:a_start] + before[it_a["end"]:]
        sep = [] if (after and after[0].strip() == "") else [""]
        write_store(before + body + sep + after, [i["id"] for i in items if i is not it_a])

    print(f"OK merged {absorbed} into {surv}")
    if new_heading != it_s["heading"]:
        print(f"heading: {new_heading}")
    if moved:
        print(f"retargeted onto {surv}: " + ", ".join(moved) + " (were blocked on "
              f"{absorbed} — the work moved, so they stay gated)")
    for note in notes:
        print(f"note: {note}")
    print(f"note: {absorbed} is gone for good — its number is never reissued")
    return 0


def cmd_admin_done(argv):
    admin_id = argv[0]
    with StoreLock():
        lines = read_lines()
        items = parse_items(lines)
        target = find_item(items, admin_id)
        if target is None:
            print(f"NONE — no item {admin_id} in the backlog")
            return 1
        if target["section"] != "admin":
            print(f"ERROR — {admin_id} is a {target['section']} item, not an Admin task")
            return 2
        unblocked = _excise_item(lines, items, target)
        _hook_queue("remove", admin_id, target["body"])
    print(f"OK completed admin task {admin_id}")
    print("unblocked: " + (", ".join(unblocked) if unblocked else "(none referenced it)"))
    return 0


def _detect_cycle(deps):
    """`deps` maps id -> set of blocker ids (id is *blocked by* each blocker). Return a cycle as an
    id list (`A -> B -> A`) if the "blocked by" graph has one, else None. A cycle would deadlock
    `next` — every item in it waits on another that never clears — so reorder refuses to write one."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {}

    def visit(n, stack):
        color[n] = GRAY
        for m in deps.get(n, ()):
            c = color.get(m, WHITE)
            if c == GRAY:
                return stack[stack.index(m):] + [m]
            if c == WHITE:
                r = visit(m, stack + [m])
                if r:
                    return r
        color[n] = BLACK
        return None

    for n in list(deps):
        if color.get(n, WHITE) == WHITE:
            r = visit(n, [n])
            if r:
                return r
    return None


def _open_section_span(lines):
    """(start, end) line indices of the `## Open` section body — start is the `## Open` header
    line, end is the next `## ` header (or EOF). (None, None) if there is no Open section."""
    start = None
    for i, l in enumerate(lines):
        if l.strip() == "## Open":
            start = i
            break
    if start is None:
        return None, None
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    return start, end


def _lis_indices(seq):
    """Indices of `seq` forming one longest strictly-increasing subsequence — an O(n²) DP, fine at
    backlog size. Used to tell which items in a reorder actually MOVED (needed a new neighbor)
    from ones merely shifted a slot by something else moving past them: with `seq` the OLD index
    of each id in the NEW order, an id at an LIS position already sat in the right place relative
    to every other LIS id, so it didn't move; everything else did (TOOL-28)."""
    n = len(seq)
    if n == 0:
        return set()
    length = [1] * n
    prev = [-1] * n
    for i in range(n):
        for j in range(i):
            if seq[j] < seq[i] and length[j] + 1 > length[i]:
                length[i] = length[j] + 1
                prev[i] = j
    best = max(range(n), key=lambda i: length[i])
    out = set()
    while best != -1:
        out.add(best)
        best = prev[best]
    return out


def cmd_reorder(_argv):
    """Reorder the ## Open section and set its complete Open-item dependency chain from a JSON plan
    on stdin: {"order": [ids…], "blocks": {id: [open-blocker-ids…]}}.

    - `order` sets the file order of Open items — and since `next` claims non-priority items in file
      order, that *is* the claim order. Ids omitted keep their current relative order after the
      listed ones, so a partial `order` just floats a few items to the front.
    - `blocks` is authoritative for Open-item→Open-item gates: each item's Open-item blockers become
      exactly blocks[id] (an unmentioned item's Open-item blockers are cleared). Human
      `[BLOCKED: <ADMIN>]` gates are always preserved, and a claimed (in_progress) item's heading is
      never touched (its body is already snapshotted in a worktree). This is what lets /reorder chain
      three big edits to one file A→B→C so /plan-todo hands them out one at a time, conflict-free.

    Applied atomically under the store lock; rejects unknown ids, self-blocks, Admin blockers, and
    cycles. Free-floating `---` rules and section-intro `> …` notes between Open items are carried
    along with the item they introduce (so a moved group keeps its intro note); only genuine stray
    prose that belongs to no item is refused, since reordering would drop it."""
    raw = sys.stdin.read().strip()
    if not raw:
        print('ERROR — reorder needs a JSON plan on stdin: {"order": [...], "blocks": {"ID": ["BLOCKER"]}}')
        return 2
    try:
        plan = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"ERROR — plan is not valid JSON: {e}")
        return 2
    order = plan.get("order") or []
    blocks = plan.get("blocks") or {}
    if not isinstance(order, list) or not all(isinstance(x, str) for x in order):
        print('ERROR — "order" must be a list of item ids')
        return 2
    if not isinstance(blocks, dict):
        print('ERROR — "blocks" must be an object mapping id -> [blocker ids]')
        return 2

    changed, skipped_claimed, final = [], [], []
    with State() as st, StoreLock():
        claimed = set(st.claims)
        lines = read_lines()
        items = parse_items(lines)
        open_items = [it for it in items if it["section"] == "open"]
        before_order = [it["id"] for it in open_items]  # pre-reorder file order, for `moved:` below
        open_ids = {it["id"] for it in open_items}
        all_ids = {it["id"] for it in items}
        admin_ids = {it["id"] for it in items if it["section"] == "admin"}

        if not open_items:
            print("(no Open items to reorder)")
            return 0

        # -- validate order (subset of Open ids, no repeats) --
        seen = set()
        for oid in order:
            if oid not in open_ids:
                print(f"ERROR — order lists {oid!r}, which is not an Open item")
                return 2
            if oid in seen:
                print(f"ERROR — order lists {oid!r} more than once")
                return 2
            seen.add(oid)

        # -- validate blocks & build each item's desired Open-item blocker list --
        desired = {}
        for tid, blist in blocks.items():
            if tid not in open_ids:
                print(f"ERROR — blocks target {tid!r} is not an Open item")
                return 2
            if not isinstance(blist, list) or not all(isinstance(b, str) for b in blist):
                print(f"ERROR — blocks[{tid!r}] must be a list of blocker ids")
                return 2
            clean, s = [], set()
            for b in blist:
                if b == tid:
                    print(f"ERROR — {tid} can't block itself")
                    return 2
                if b not in all_ids:
                    print(f"ERROR — blocker {b!r} (for {tid}) references no existing item")
                    return 2
                if b in admin_ids:
                    print(f"ERROR — {b} is an Admin task; human gates are set at /todo time and "
                          "reorder preserves them automatically — list only Open-item blockers here")
                    return 2
                if b not in s:
                    s.add(b)
                    clean.append(b)
            desired[tid] = clean

        # -- cycle check over the resulting Open-item graph (claimed items keep their current
        #    Open-item blockers since we won't rewrite their headings) --
        graph = {}
        for it in open_items:
            if it["id"] in claimed:
                graph[it["id"]] = {b for b in it["blockers"] if b in open_ids}
            else:
                graph[it["id"]] = set(desired.get(it["id"], []))
        cyc = _detect_cycle(graph)
        if cyc:
            print("ERROR — block plan is cyclic: " + " -> ".join(cyc))
            return 2

        # -- rewrite headings in place (line count preserved so indices stay valid) --
        for it in open_items:
            iid = it["id"]
            if iid in claimed:
                if iid in desired:
                    skipped_claimed.append(iid)
                continue
            parts = _split_heading(iid, it["heading"])
            parts["blockers"] = ([b for b in parts["blockers"] if b in admin_ids]
                                 + desired.get(iid, []))
            if parts["blockers"]:
                # a blocked item is never auto-claimed, so a hard gate on the queue makes no sense;
                # [PRIORITY] only orders claims and takes effect once the gate clears
                parts["critical"] = False
            if _compose_heading(parts) != it["heading"]:
                _set_heading(lines, it, parts)
                changed.append(iid)

        # -- reorder the item sections within ## Open (headings just edited, so re-parse) --
        open_start, open_end = _open_section_span(lines)
        open_items = [it for it in parse_items(lines)
                      if it["section"] == "open" and open_start <= it["start"] < open_end]
        by_id = {it["id"]: it for it in open_items}
        first_start, last_end = open_items[0]["start"], open_items[-1]["end"]

        # Free-floating material between Open items — `---` rules and section-intro `> …` notes
        # that `parse_items` deliberately keeps out of every item body (so `remove` can't delete
        # a group's shared context, STORE-1). Rather than refuse, carry each gap along with the
        # item it introduces (the file-order item just below it) so the note travels to that
        # item's new position and nothing is lost. Only genuine stray prose — a non-blank line
        # that is neither a `---` rule nor a `>` note, which can't be attributed to any item — is
        # still refused, since reordering really would drop it.
        leading = {}
        for idx in range(1, len(open_items)):
            base = open_items[idx - 1]["end"]
            gap = lines[base:open_items[idx]["start"]]
            bad = [n for n, g in enumerate(gap)
                   if g.strip() != "" and g.strip() != "---" and not g.lstrip().startswith(">")]
            if bad:
                off = base + bad[0]
                print(f"ERROR — line {off + 1} sits between Open items and belongs to none "
                      f"({lines[off].strip()!r}); reorder won't risk losing it — run /repair or move it")
                return 2
            block = list(gap)
            while block and block[0].strip() == "":
                block.pop(0)
            while block and block[-1].strip() == "":
                block.pop()
            if block:
                leading[open_items[idx]["id"]] = block

        final = list(order) + [it["id"] for it in open_items if it["id"] not in set(order)]
        prefix = lines[open_start:first_start]
        while prefix and prefix[-1].strip() == "":
            prefix.pop()
        suffix = lines[last_end:open_end]
        while suffix and suffix[0].strip() == "":
            suffix.pop(0)
        rebuilt = list(prefix)
        for iid in final:
            it = by_id[iid]
            body = lines[it["start"]:it["end"]]
            while body and body[-1].strip() == "":
                body.pop()
            note = leading.get(iid)
            if note:
                rebuilt.append("")
                rebuilt.extend(note)
            rebuilt.append("")
            rebuilt.extend(body)
        rebuilt.append("")
        rebuilt.extend(suffix)
        write_store(lines[:open_start] + rebuilt + lines[open_end:], [i["id"] for i in items])

    print("OK reordered ## Open")
    # Only what actually moved (TOOL-28) — echoing the whole new order named every unrelated item
    # too. "Moved" is relative order, not raw position: promoting one item shifts everyone else's
    # index by a slot without changing their order among themselves — the LIS complement.
    old_index = {iid: i for i, iid in enumerate(before_order)}
    lis = _lis_indices([old_index[iid] for iid in final])
    moved = [iid for i, iid in enumerate(final) if i not in lis]
    if moved:
        print("moved: " + ", ".join(moved))
    if changed:
        print("block markers updated on: " + ", ".join(changed))
    if skipped_claimed:
        print("left claimed items untouched (blocks ignored): " + ", ".join(skipped_claimed))
    return 0


# @fragment 20_doctor.py
# ---------------------------------------------------------------------------
# Doctor / repair — keep the store parseable so `next`/`show`/`summary` can't
# silently drop an item. parse_items ignores anything outside a recognised
# section, any `### ` heading without an <ID>, and anything hidden inside an
# unbalanced ``` fence; those are the failures we detect and (where safe) fix.
# ---------------------------------------------------------------------------

SECTION_CANON = {"admin": "## Admin", "open": "## Open"}
# A line *meant* to be a section header (any hash level / spacing / case). The
# trailing `$` keeps it from matching an item heading like `### ADMIN-1 — …`.
SECTION_LINE_RE = re.compile(r"^\s*#{1,4}\s*(admin|open)\s*$", re.I)
# A line *meant* to be an item heading: hashes, then an ID-like token right away.
HEADING_LINE_RE = re.compile(r"^\s*(#{2,4})\s*([A-Za-z]{2,}-\d+)\s*(.*)$")


def _canon_section(line):
    m = SECTION_LINE_RE.match(line)
    return SECTION_CANON[m.group(1).lower()] if m else None


def _canon_heading(line):
    """Canonical `### <ID> — <title>` for a line intended as an item heading, else None.
    Fixes hash count/spacing, uppercases the ID (parse requires `[A-Z]{2,}-\\d+`), and
    normalises the ID→title separator to ` — `. Returns None for non-heading lines, so
    prose and `## Admin`/`## Open` are left alone."""
    m = HEADING_LINE_RE.match(line)
    if not m:
        return None
    ident = m.group(2).upper()
    rest = re.sub(r"^\s*[—–-]\s*", "", m.group(3).strip())  # drop any leading dash form
    return f"### {ident}" + (f" — {rest}" if rest else "")


def _strip_orphans(lines):
    """Return (new_lines, removed) — drop clearly-orphaned non-heading text that belongs to no
    item, so a botched hand-edit self-heals instead of only being flagged.

    parse_items attaches every non-heading line to the *preceding* item's body, so the only
    lines that belong to no item at all sit in one of two 'orphan zones': before the first
    `## ` section, or after a `## ` header but before that section's first `### ` item. In those
    zones this strips a leftover run of prose/bullets/dangling comments.

    Conservative by design — it never deletes a real item. Preserved: blank lines, any
    `#`-prefixed heading, any `>` blockquote (the store's only legitimate preamble form, matching
    `_trailing_note_end`), and `---` rules. A stray `### ` heading inside an orphan zone ends
    stripping for that zone — that heading *and its body* could be a mis-sectioned real item, so
    it is left for the MANUAL path (`_manual_issues` flags it). Fence-aware: content inside a
    ``` block is untouched. Run on already-canonicalised lines so headings are `## `/`### `."""
    removed, out = [], []
    fence = None
    orphan_zone = True   # before the first `## `; re-armed after each `## ` until its first item
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        fence, is_fence = _fence_step(fence, line)
        if is_fence or fence is not None:
            out.append(line)
            continue
        if line.startswith("## "):
            orphan_zone = True                      # entering a section's pre-item zone
            out.append(line)
            continue
        if line.startswith("### "):
            orphan_zone = False                     # item body begins — stop stripping this zone
            out.append(line)
            continue
        if orphan_zone and stripped and not stripped.startswith(("#", ">", "---")):
            removed.append(f"orphaned line {i} dropped: {line.strip()!r}")
            continue
        out.append(line)
    return out, removed


def _repair_lines(lines):
    """Return (new_lines, applied) — the safe, unambiguous fixes only. Fence-aware so it never
    rewrites headings that are really example text inside a ``` block. Canonicalises section/item
    headings and trailing whitespace, then strips clearly-orphaned stray text (see
    `_strip_orphans`); ambiguous cases (e.g. an orphaned `### ` heading with a body) are left for
    the MANUAL path rather than deleted."""
    applied, out = [], []
    fence = None
    trimmed = 0
    for line in lines:  # read_lines() opens in text mode, so CRLF is already normalised to LF
        stripped_tail = line.rstrip()
        if stripped_tail != line:
            line = stripped_tail
            trimmed += 1
        fence, is_fence = _fence_step(fence, line)
        if is_fence:
            out.append(line)
            continue
        if fence is None:
            sec = _canon_section(line)
            if sec is not None and sec != line:
                applied.append(f"section header {line!r} → {sec!r}")
                out.append(sec)
                continue
            head = _canon_heading(line)
            if head is not None and head != line:
                applied.append(f"item heading {line!r} → {head!r}")
                out.append(head)
                continue
        out.append(line)
    if trimmed:
        applied.insert(0, f"trimmed trailing whitespace on {trimmed} line(s)")
    out, orphan_removed = _strip_orphans(out)       # headings now canonical, so the zone scan is reliable
    applied.extend(orphan_removed)
    return out, applied


def _manual_issues(lines):
    """Problems repair can't safely fix on its own — the AI/user must resolve them.
    Run on already-repaired lines so it doesn't re-flag what repair just corrected."""
    issues = []
    fence = fence_line = None
    section = None
    seen_sections = {}
    ids = {}
    admin_ids = set()
    blocked = []  # (line_no, target_id)
    for i, line in enumerate(lines, 1):
        s = line.strip()
        was = fence
        fence, is_fence = _fence_step(fence, line)
        if is_fence and was is None:
            fence_line = i
        if is_fence or fence is not None:
            continue
        if line.startswith("## "):
            key = SECTIONS.get(s)
            if key:
                seen_sections.setdefault(key, []).append(i)
            section = key
            continue
        if line.startswith("### "):
            heading = line[4:].strip()
            m = ID_RE.search(heading)
            if section is None:
                issues.append(f"line {i}: item heading outside any ## section (orphan): {heading!r}")
            if not m:
                issues.append(f"line {i}: item heading has no <ID> token: {heading!r}")
                continue
            ids.setdefault(m.group(1), []).append(i)
            if section == "admin":
                admin_ids.add(m.group(1))
            # Every marker, not just the first: a heading takes repeated `[BLOCKED: …]` markers
            # (that's how `block` and `add-bulk --chain` write multiple gates), and a dangling
            # second one is exactly as fatal to the item as a dangling first one.
            # Only the leading marker run counts — the same rule the parser applies.
            parts = _split_heading(m.group(1), heading)
            blocked.extend((i, b, m.group(1)) for b in parts["blockers"])
            if parts["bad"]:
                issues.append(f"line {i}: [BLOCKED …] without a resolvable <ID>: {heading!r}")
    if fence is not None:
        issues.append(f"unbalanced ``` fence (the {fence} fence opened on line {fence_line} is "
                      "never closed) — headings after the open fence are hidden from the parser")
    for key, locs in seen_sections.items():
        if len(locs) > 1:
            issues.append(f"duplicate '{SECTION_CANON[key]}' header at lines {locs}")
    for ident, locs in ids.items():
        if len(locs) > 1:
            issues.append(f"duplicate id {ident} at lines {locs}")
    # A blocker may be an Admin task or another Open item (item-on-item ordering); it's dangling
    # only if it matches no item at all, and nonsensical if an item blocks itself.
    all_ids = set(ids)
    for line_no, target, owner in blocked:
        if target == owner:
            issues.append(f"line {line_no}: [BLOCKED: {target}] blocks the item on itself")
        elif target not in all_ids:
            issues.append(f"line {line_no}: [BLOCKED: {target}] references no existing item (dangling)")
    # A cycle passes every check above — each blocker resolves, none is a self-block — yet deadlocks
    # `next` just as thoroughly. The writers (`add`, `add-bulk`, `block`, `reorder`) each refuse to
    # create one, so reaching here means the store was hand-edited; report it as MANUAL, since the
    # fix is a judgment call about which edge to drop, not a formatting repair.
    deps = {}
    for _, target, owner in blocked:
        if target != owner:  # self-blocks are reported above; they'd swamp the cycle message here
            deps.setdefault(owner, set()).add(target)
    cyc = _detect_cycle(deps)
    if cyc:
        issues.append("cyclic [BLOCKED] chain: " + " -> ".join(cyc) + " — every item in it waits "
                      "on another that never clears; re-cut the chain with /reorder")
    # A malformed Route/Effort bullet doesn't break parsing, but it silently re-routes the item to
    # the default route — report it so the author can fix the bullet.
    for it in parse_items(lines):
        if it["section"] == "open":
            problem = _routing_problem(it["body"])
            if problem:
                issues.append(f"{it['id']}: {problem} — routes to the default "
                              f"({_routing()['default'].name}) route until fixed")
    return issues


def _doc_ref_notes(lines):
    """Informational only: one note per store item id that a file under a registered docs
    directory (a configured `sequences` dir — the only docs registry there is) names. A sentence
    like "that is GUI-35's to decide" in an ADR is a documentation obligation nobody declared;
    `refs <id>` lists the lines."""
    dirs = [c["dir"] for c in _sequences().values() if isinstance(c, dict) and c.get("dir")]
    ids = {it["id"] for it in parse_items(lines)}
    if not dirs or not ids:
        return []
    found = {}
    for path, lineno, text in _grep_ids_quiet(sorted(ids), paths=dirs, timeout=10):
        for ident in set(ID_RE.findall(text)) & ids:
            found.setdefault(ident, []).append(f"{path}:{lineno}")
    notes = []
    for ident in sorted(found)[:REFS_CAP]:
        locs = found[ident]
        more = f" (+{len(locs) - 3} more)" if len(locs) > 3 else ""
        notes.append(f"{ident} is named in a registered docs dir: {', '.join(locs[:3])}{more}")
    if len(found) > REFS_CAP:
        notes.append(f"… and {len(found) - REFS_CAP} more ids")
    return notes


def _inherit_notes():
    """`doctor`'s WARN lines for a malformed `inherit_bullets` config; none when the key is absent."""
    return [f"{p} in .claude/todo-config.json (see `help config`)"
            for p in _inherit_problems(_config().get("inherit_bullets"))]


def cmd_doctor(_argv):
    lines = read_lines()
    repaired, fixable = _repair_lines(lines)
    manual = _manual_issues(repaired)
    info = _doc_ref_notes(repaired)
    # Not a store problem, so it never changes the exit code — that one sends callers to /repair.
    warn = _seq_duplicate_notes() + _overlay_notes() + _hooks_notes() + _inherit_notes()
    if not fixable and not manual:
        print("OK — TODO.local.md is well-formed")
        for n in info:
            print(f"INFO:    {n}")
        for w in warn:
            print(f"WARN:    {w}")
        return 0
    for f in fixable:
        print(f"FIXABLE: {f}")
    for m in manual:
        print(f"MANUAL:  {m}")
    for n in info:
        print(f"INFO:    {n}")
    for w in warn:
        print(f"WARN:    {w}")
    print("\nRun /repair — it applies the FIXABLE items; resolve any MANUAL ones with the user.")
    return 1


def cmd_repair(_argv):
    with StoreLock():
        lines = read_lines()
        repaired, applied = _repair_lines(lines)
        if applied:
            write_lines(repaired)
        manual = _manual_issues(repaired)
    if applied:
        print("Applied:")
        for a in applied:
            print(f"  - {a}")
    else:
        print("No auto-fixable formatting problems found.")
    if manual:
        print("\nStill needs a human (repair won't guess these):")
        for m in manual:
            print(f"  - {m}")
        print("\nFix each MANUAL item, then re-run `doctor` to confirm the store parses.")
        return 1
    print("\nStore is well-formed — every item is reachable by the parser.")
    return 0


# @fragment 30_claims.py
# ---------------------------------------------------------------------------
# Claim-lock layer — the flock-guarded JSON of who is working on what
# ---------------------------------------------------------------------------

class StateCorrupt(Exception):
    """The claims file exists but isn't a JSON object — a `state` crash, never a /repair case."""


def _state_bak_has_data(bak):
    """True when the `.bak` parses and still holds something a fresh state would lose."""
    try:
        with open(bak, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and any(data.get(k) for k in ("claims", "version", "next_id"))


class State:
    """The claims file, held under an exclusive flock for the duration of a `with` block.

    The flock is on the `.lock` SIDECAR, not the state file: `save()` replaces the state file by
    rename (BUG-3), which would leave a flock on its old inode guarding nothing. `save()` also
    keeps the previous good contents as `.bak`, one save behind."""

    def __init__(self):
        self._lock = None
        self._raw = ""
        self.data = None

    def __enter__(self):
        path = state_path()
        self._lock = os.open(path + ".lock", os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX)
            try:
                with open(path, encoding="utf-8") as f:
                    self._raw = f.read()
            except FileNotFoundError:
                self._raw = ""
            self.data = self._parse(path)
        except BaseException:
            self.__exit__()
            raise
        self.data.setdefault("claims", {})
        self.data.setdefault("version", {})  # {"hwm": "x.y.z"} — high-water mark of numbers handed out
        self.data.setdefault("next_id", {})  # {"FLOW": 7, …} — highest per-family number ever issued
        self.data.setdefault("history_scanned", [])  # families whose git history seeded next_id
        # {"adr": {"worktrees": {path: [n, …]}}} — sequence numbers reserved OUTSIDE a claimed
        # item, keyed by worktree (claim-keyed reservations live on the claim dict itself, so
        # release/land discard them with the claim).
        self.data.setdefault("seq", {})
        return self

    def _parse(self, path):
        if not self._raw.strip():
            if os.path.exists(path) and _state_bak_has_data(path + ".bak"):
                print(f"WARNING — the claims file {path} is EMPTY but {path}.bak still holds claims "
                      f"/ id counters; carrying on as fresh. To get them back, restore it now:\n"
                      f"  cp '{path}.bak' '{path}'", file=sys.stderr)
            return {"claims": {}}
        try:
            data = json.loads(self._raw)
        except json.JSONDecodeError as e:
            raise StateCorrupt(f"not valid JSON ({e.msg})") from e
        if not isinstance(data, dict):
            raise StateCorrupt(f"top level is {type(data).__name__}, not an object")
        return data

    def save(self):
        path = state_path()
        # Back up the contents read at __enter__ (parsed fine, or we'd have raised) — never an
        # empty read, so a good .bak survives a zero-length state file.
        if self._raw.strip():
            _atomic_write(path + ".bak", self._raw)
        text = json.dumps(self.data, indent=2) + "\n"
        _atomic_write(path, text)
        self._raw = text

    def __exit__(self, *exc):
        if self._lock is None:
            return
        try:
            fcntl.flock(self._lock, fcntl.LOCK_UN)
        finally:
            os.close(self._lock)
            self._lock = None

    @property
    def claims(self):
        return self.data["claims"]

    @property
    def version(self):
        return self.data["version"]

    @property
    def next_id(self):
        return self.data["next_id"]

    @property
    def history_scanned(self):
        return self.data["history_scanned"]

    @property
    def seq(self):
        return self.data["seq"]


def _now():
    return datetime.now().isoformat(timespec="seconds")


# Stale-claim detection (BUG-5). A claim is only ever FLAGGED stale — never released by anything but
# an explicit `release` / `reclaim --stale` — so every rule below must err towards "alive": a field
# that's missing (a claim from before these fields existed) or unparsable makes its rule not fire.
DEFAULT_STALE_CLAIM_HOURS = 24


def _owner_fields():
    """Who holds a claim, stamped on it by `next`/`attach`/`lock` and refreshed by `_touch_claim`.

    The pid is `CLAUDE_PID` — the long-lived Claude Code session process — never this process or
    its parent: every script call is a fresh python under a throwaway shell, so both are dead the
    moment the call returns. Outside Claude Code there's no durable owner pid to record, so it's
    None and only the worktree/TTL rules apply."""
    try:
        pid = int(os.environ.get("CLAUDE_PID", ""))
    except ValueError:
        pid = None
    return {
        "pid": pid,
        "host": socket.gethostname(),
        "session": os.environ.get("CLAUDE_CODE_SESSION_ID") or None,
        "last_seen": _now(),
    }


def _body_sha(body_lines):
    """Fingerprint of an item's text when claimed — `list` compares it to flag a CHANGED item."""
    return hashlib.sha1("\n".join(body_lines).rstrip().encode("utf-8")).hexdigest()


def _stale_claim_hours():
    try:
        return float(_config().get("stale_claim_hours", DEFAULT_STALE_CLAIM_HOURS))
    except (TypeError, ValueError):
        return float(DEFAULT_STALE_CLAIM_HOURS)


def _pid_dead(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False  # PermissionError: alive, someone else's
    return False


def _stale_reason(claim):
    """Why this claim looks abandoned, or None when it looks live (or liveness is unknown)."""
    wt = claim.get("worktree")
    if wt and not os.path.isdir(wt):
        return f"worktree gone ({wt})"
    pid = claim.get("pid")
    # A pid only means something on the machine that recorded it.
    if isinstance(pid, int) and pid > 0 and claim.get("host") == socket.gethostname() \
            and _pid_dead(pid):
        return f"owner pid {pid} exited"
    ttl = _stale_claim_hours()
    seen = claim.get("last_seen")
    if ttl > 0 and isinstance(seen, str):
        try:
            idle = (datetime.now() - datetime.fromisoformat(seen)).total_seconds() / 3600
        except ValueError:
            return None
        if idle > ttl:
            return f"idle {int(idle)}h (last seen {seen})"
    return None


def _stale_claims(claims):
    """{id: reason} for every claim that looks abandoned."""
    return {cid: r for cid, c in claims.items() if (r := _stale_reason(c))}


def _stale_note(stale):
    """The one-line pointer `next` and `summary` print when any claim looks abandoned."""
    held = ", ".join(f"{cid} ({r})" for cid, r in stale.items())
    return (f"note: stale claim(s): {held} — free with `todo-lock.py reclaim --stale` "
            "(nothing is released automatically)")


def _touch_claim():
    """Heartbeat: a script call from inside a claim's worktree refreshes that claim's owner fields,
    so `last_seen` tracks a tab that is still working. Best-effort by design — it runs before every
    command, so any failure here (not a repo, a corrupt claims file) is swallowed and left for the
    command itself to report through its classified crash.

    It also keeps the claim's file list live (TOOL-22): everything the worktree changed since its
    branch point is recorded as `touched`. A newly recorded path that collides with another claim
    gets one stderr line — stdout stays the command's own."""
    try:
        if not _in_linked_worktree():
            return
        with State() as st:
            cid = _claim_for_here(st)
            if cid is None:
                return
            st.claims[cid].update(_owner_fields())
            new = _record_touched(st, cid, _touched_since_branch_point())
            st.save()
            hits = _overlaps(st.claims, cid, new) if new else []
        for other, f, kind in hits:
            if kind in ("hot", "hard"):
                print(f"note: {cid} now touches {f}, also claimed by {other}"
                      + (" (HOT-FILE)" if kind == "hot" else ""), file=sys.stderr)
    except Exception:  # noqa: BLE001 — see docstring
        return


def _claim_for_here(st):
    """The id of the claim whose recorded worktree is the current checkout, else None."""
    here = os.path.realpath(_git("rev-parse", "--show-toplevel"))
    for cid, claim in st.claims.items():
        wt = claim.get("worktree")
        if wt and os.path.realpath(wt) == here:
            return cid
    return None


def _inherit_problems(value):
    """What is wrong with an `inherit_bullets` config value, as a list of plain lines ([] when it is
    fine or absent)."""
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        return ["`inherit_bullets` must be a list of non-empty bullet labels, e.g. [\"Source\"]"]
    return []


def _inherit_labels():
    """The bullet labels `add`/`add-bulk` copy from the claimed item; [] when the key is absent or
    malformed (`doctor` reports the latter)."""
    value = _config().get("inherit_bullets")
    return [v.strip() for v in value] if value and not _inherit_problems(value) else []


def _top_bullet(lines, label):
    """The top-level `- **<label>:** …` bullet in `lines` with its indented continuation lines, or
    None. Fenced lines never count, so a bullet quoted in a code block is not one."""
    head = re.compile(r"- \*\*" + re.escape(label) + r":\*\*")
    fence = None
    for i, line in enumerate(lines):
        fence, is_fence = _fence_step(fence, line)
        if is_fence or fence is not None or not head.match(line):
            continue
        end = i + 1
        while end < len(lines) and lines[end][:1] in (" ", "\t") and lines[end].strip():
            end += 1
        return lines[i:end]
    return None


def _inherit_parent(no_inherit):
    """`(parent_id, {label: bullet lines})` for a new item filed from a worktree attached to a
    claimed item, else `(None, {})`. Cheap checks first, so a repo without `inherit_bullets` never
    takes a lock here. The claim is resolved in its own short `State()`, released before the
    caller's write section opens (it is not reentrant)."""
    labels = _inherit_labels()
    if no_inherit or not labels or not _in_linked_worktree():
        return None, {}
    with State() as st:
        cid = _claim_for_here(st)
    parent = find_item(parse_items(read_lines()), cid) if cid else None
    if parent is None:
        return None, {}
    found = {lb: _top_bullet(parent["body"], lb) for lb in labels}
    return cid, {lb: b for lb, b in found.items() if b}


def _inherit_into(body, bullets):
    """`body` with each bullet it lacks appended, and the labels added. A label already present as
    a top-level bullet is left alone."""
    lines = body.split("\n") if body else []
    added = []
    for label, bullet in bullets.items():
        if _top_bullet(lines, label) is None:
            lines += bullet
            added.append(label)
    return "\n".join(lines), added


def _touched_since_branch_point():
    """Repo-relative paths the current worktree changed since it left the base: committed, staged,
    unstaged, and untracked-but-not-ignored. `land`'s own bookkeeping files are left out — every
    land writes them. Empty when git can't say (no base, detached state), and while a merge is in
    progress: mid-fold, the working tree holds the base's incoming changes but the merge-base is
    still the old branch point, so the diff would claim the base's files as this item's edits."""
    try:
        if subprocess.run(["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"],
                          capture_output=True).returncode == 0:
            return []
        mb = _git("merge-base", "HEAD", base_branch())
        paths = set(_git("diff", "--name-only", mb).splitlines())
        top = _git("rev-parse", "--show-toplevel")  # ls-files is cwd-relative; diff is not
        paths |= set(_git("-C", top, "ls-files", "--others", "--exclude-standard").splitlines())
    except (subprocess.CalledProcessError, OSError):
        return []
    managed = _land_managed_paths()
    return sorted(p for p in paths if p and os.path.normpath(p) not in managed)


def _claim_held(claim):
    """Every path a claim holds for overlap purposes: its declared `files` plus what it `touched`."""
    return [*(claim.get("files") or []), *(claim.get("touched") or [])]


def _uncovered(paths, claim):
    """Canonical `paths` that none of the claim's declared `files`/`docs` covers (`_paths_overlap`)."""
    declared = [_path_key(f) for f in [*(claim.get("files") or []), *(claim.get("docs") or [])]]
    return [p for p in _dedupe_paths(paths)
            if not any(_paths_overlap(_path_key(p), d) for d in declared)]


def _record_touched(st, cid, paths):
    """Add the edited `paths` no declared entry covers to the claim's `touched` list; returns the
    ones that are new. Paths outside the trees (still absolute once normalised) and under `.git/`
    are not item work and are dropped. Kept apart from `files` so declared vs touched can be told
    apart at `land` (and by telemetry)."""
    claim = st.claims[cid]
    inside = [p for p in (_norm_path(t) for t in paths if t.strip())
              if not os.path.isabs(p) and not p.startswith(("../", ".git/"))]
    have = {_path_key(t) for t in claim.get("touched") or []}
    new = [p for p in _uncovered(inside, claim) if _path_key(p) not in have]
    if new:
        claim["touched"] = _dedupe_paths([*(claim.get("touched") or []), *new])
    return new


# Per-item telemetry (TOOL-34): one JSON line per claim that ends — landed, released or bounced —
# appended beside the claim state, machine-local, never committed. Paths and counts only: never a
# title, heading or body. Best-effort by contract: a metrics failure never changes a command's
# output or exit code. Written only by a caller holding State(), so appends are serialized.
METRICS_FILE = "claude-todo-metrics.jsonl"
METRICS_SCHEMA = 1


def metrics_path():
    return os.path.join(_common_dir(), METRICS_FILE)


def _metrics_enabled():
    return _config().get("metrics", True) is not False


def _metrics_files(paths):
    paths = _dedupe_paths(paths or [])
    return {"n": len(paths), "paths": paths}


def _metrics_record(item_id, claim, outcome, touched=None):
    """The record for `claim` ending with `outcome`. `touched` is the merge diff when there is one;
    the claim's own `touched` list is always folded in. Claims from before these fields existed
    record null for them."""
    attempts = claim.get("land_attempts") or 0
    return {
        "v": METRICS_SCHEMA,
        "id": item_id,
        "family": item_id.rsplit("-", 1)[0],
        "outcome": outcome,
        "route": claim.get("route"),
        "effort": claim.get("effort"),
        "model": claim.get("model"),
        "claimed_at": claim.get("claimed_at"),
        "attached_at": claim.get("attached_at"),
        "ended_at": _now(),
        "files_declared": _metrics_files(claim.get("declared")),
        "files_locked": _metrics_files(claim.get("files")),
        "files_touched": _metrics_files([*(touched or []), *(claim.get("touched") or [])]),
        "fold_conflict": bool(claim.get("fold_conflict")),
        "overlap_note": claim.get("overlap_note"),
        "land_retries": max(attempts - 1, 0),
    }


def _metrics_note(item_id, claim, outcome, touched=None):
    """Append the record for a claim about to be dropped. The caller holds State()."""
    try:
        if claim is None or not _metrics_enabled():
            return
        line = json.dumps(_metrics_record(item_id, claim, outcome, touched), sort_keys=True) + "\n"
        fd = os.open(metrics_path(), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except Exception:  # noqa: BLE001 — telemetry never fails the command it rides on
        return


# @fragment 40_version_next.py
# ---------------------------------------------------------------------------
# Project version assignment, then claiming — the version helpers, `next`, `attach`.
# Version handout runs inside the State() flock (see cmd_reserve_version), so two
# parallel /finish runs serialize and can never pick the same number.
# ---------------------------------------------------------------------------

# The project's semver source of truth is OPT-IN: `version_source` in `.claude/todo-config.json`
# names a file (relative to the repo root) holding a `__version__ = "x.y.z"` line, and the base for
# the next number is that *committed* version in the main tree. With no config the whole version
# machinery stays inert (`reserve-version` errors; `land` skips the version/CHANGELOG steps).
DEFAULT_VERSION_RE = re.compile(
    r"""^__version__\s*=\s*['"](\d+)\.(\d+)\.(\d+)['"]""", re.M
)
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _version_source_rel():
    """Repo-root-relative path to the version source of truth, or None when unconfigured."""
    return _config().get("version_source")


def _version_configured():
    return bool(_version_source_rel())


def _version_source_re():
    """Compiled regex locating the `x.y.z` in the version source — the config's `version_pattern`
    override, or the default `__version__ = "x.y.z"` pattern. The pattern must expose the three
    version components as capture groups 1–3."""
    pat = _config().get("version_pattern")
    return re.compile(pat, re.M) if pat else DEFAULT_VERSION_RE


def _parse_version(s):
    m = VERSION_RE.match(s.strip())
    if not m:
        raise ValueError(f"malformed version {s!r} (want x.y.z)")
    return tuple(int(g) for g in m.groups())


def _fmt_version(t):
    return "%d.%d.%d" % t


def _bump(base, tier):
    x, y, z = base
    if tier == "major":
        return (x + 1, 0, 0)
    if tier == "minor":
        return (x, y + 1, 0)
    if tier == "patch":
        return (x, y, z + 1)
    raise ValueError(f"unknown tier {tier!r}")


def _committed_version():
    """The committed project version from the configured `version_source` file's `__version__`, as
    an (x,y,z) tuple. This is the floor for any newly reserved number, so a serial (non-parallel)
    finish that bumped the version without this tool can't be handed a lower number."""
    rel = _version_source_rel()
    if not rel:
        raise ValueError(
            "version bumping is not configured — set `version_source` in "
            "`.claude/todo-config.json` (see `help config`)"
        )
    path = os.path.join(main_tree(), rel)
    with open(path, encoding="utf-8") as f:
        m = _version_source_re().search(f.read())
    if not m:
        raise ValueError(f"no `__version__ = \"x.y.z\"` line in {path}")
    return tuple(int(g) for g in m.groups())


def _print_claim_body(item_id, body_lines):
    """Print a claimed item's body for `next` and `resume`, cut at NEXT_BODY_MAX_LINES. A cut
    names the `- **Label:**` bullets it dropped and points at `show <id>`, which prints the whole
    body — the tail holds Acceptance and Plan, so the claimer must not plan without it (TOOL-46)."""
    if len(body_lines) <= NEXT_BODY_MAX_LINES:
        print("\n".join(body_lines).rstrip())
        return
    print("\n".join(body_lines[:NEXT_BODY_MAX_LINES]).rstrip())
    labels = [m.group(1) for line in body_lines[NEXT_BODY_MAX_LINES:]
              for m in [re.match(r"- \*\*([^*:]+):\*\*", line)] if m]
    cut = f" (cut: {', '.join(labels)})" if labels else ""
    print(f"  … truncated at {NEXT_BODY_MAX_LINES} of {len(body_lines)} lines{cut} — run "
          f"`show {item_id}` for the rest before planning")


def cmd_next(argv):
    ap = _ArgParser(prog="todo-lock.py next", add_help=False)
    ap.add_argument("--model", default=None,
                    help="restrict to items whose route names this model (sonnet|opus|fable by "
                         "default, matched as a substring of the model name/ID; see `routes`)")
    ap.add_argument("--effort", default=None,
                    help="the session's reasoning effort: prefer items whose route wants it, then "
                         "the nearest level (soft — never filters)")
    ap.add_argument("--route", default=os.environ.get("CLAUDE_TODO_ROUTE") or None,
                    help="restrict to items on this route (strict); defaults to $CLAUDE_TODO_ROUTE, "
                         "which `run` sets on the workers it starts")
    opts = ap.parse_args(argv)
    if opts.effort is not None and opts.effort not in EFFORT_LEVELS:
        print(f"ERROR — --effort {opts.effort!r} must be one of {'|'.join(EFFORT_LEVELS)}")
        return 2
    route_names = [r.name for r in _routing()["routes"]]
    if opts.route is not None and opts.route not in route_names:
        print(f"ERROR — --route {opts.route!r} must be one of {'|'.join(route_names)} (see `routes`)")
        return 2
    caller_tier = None
    if opts.model:
        caller_tier = _model_for_name(opts.model)
        if caller_tier is None:
            print(f"ERROR — could not map model {opts.model!r} to a routing model "
                  f"({'|'.join(_model_order())}); pass one whose name contains one, or set "
                  "`routing.unknown_model`/`routing.match` in .claude/todo-config.json")
            return 2
    # Nest StoreLock inside State (same order as cmd_append) because the lazy unblock re-check
    # below may *write* the store — a read-modify-write that must be atomic against a concurrent
    # add/remove/append, not just against parallel claims.
    with State() as st, StoreLock():
        lines = read_lines()
        items = parse_items(lines)
        all_ids = {it["id"] for it in items}
        dirty = False
        chosen = None
        # The first (file-order) unblocked [CRITICAL] item still in the store — a hard gate on the
        # whole queue (see cmd_add's --critical). Found up front, over the raw file-order `items`,
        # not the claim-preference `sorted(...)` below: "first by file order" is the tie-break the
        # item's invariants specify when more than one [CRITICAL] item exists. Gates regardless of
        # whether it's already claimed (its work isn't finished yet either way), so this doesn't
        # consult st.claims.
        active_critical = next(
            (it for it in items if it["section"] == "open" and it["critical"] and not it["blocked"]),
            None,
        )
        # Paths already spoken for by active claims (files and docs), classified through
        # `_overlap_kind` — the same matcher and classifier `lock` and `conflicts` use.
        busy = [(cid, _claim_entries(_claim_held(c), c.get("docs") or []))
                for cid, c in st.claims.items()]

        def _claim_overlap(it):
            """(claim-id, path, kind) of the overlap between this item's declared files and docs
            and an active claim, else None: the first `hot`/`hard` one, else the first `soft` one.
            Advisory: steers claim order, never blocks a claim — and only `hot`/`hard` steer it, a
            `soft` (documentation) overlap is reported and never defers an item.

            Deliberately compares against ACTIVE CLAIMS only, never against other Open items. Two
            unclaimed items naming the same file have nothing to collide with yet and may never be
            claimed at once, so gating on that would defer work for a conflict that doesn't exist.
            Open-vs-Open overlap is surfaced where it can be acted on with the whole graph in view:
            `files` (the table /reorder and /todo read) and a `[BLOCKED: …]` gate. Don't widen this
            to `items` — see `.claude/skills/todo/todo-filing-reference.md` ("Overlap with work
            already in the backlog")."""
            soft = None
            for entry in _claim_entries(_split_declared_files(_item_files(it["body"])),
                                        _split_declared_docs(_item_docs(it["body"]))):
                for cid, theirs in busy:
                    kind = _overlap_kind(entry, theirs)
                    if kind == "soft":
                        soft = soft or (cid, entry[0], kind)
                    elif kind:
                        return (cid, entry[0], kind)
            return soft

        overlap = {it["id"]: _claim_overlap(it) for it in items}
        defers = {iid: hit is not None and hit[2] != "soft" for iid, hit in overlap.items()}
        # Claimable items whose effort tier isn't the caller's — kept in claim order for the
        # NONE-IN-TIER report (so the AI can tell the user what's waiting and for which model).
        waiting = []
        # [CRITICAL] items are claimed ahead of [PRIORITY] ones, which are claimed ahead of
        # everything else; within each group, items whose declared files DON'T overlap an active
        # claim come first (fewer merge conflicts at /finish), and ties keep file order (sorted is
        # stable). If everything overlaps, the first item is still claimed — overlap only defers,
        # it never starves. With --effort, a last key prefers the route whose effort is nearest the
        # session's (exact first; a tie goes to the lower effort) — below priority and overlap, and
        # only reordering: the model gate below stays strict.
        for it in sorted(items, key=lambda it: (not it["critical"], not it["priority"],
                                                 defers[it["id"]],
                                                 _effort_distance(it, opts.effort))):
            # Admin (human) tasks and already-claimed items are never auto-claimed.
            if it["section"] == "admin" or it["id"] in st.claims:
                continue
            if it["blocked"]:
                blockers = it["blockers"]
                if not blockers:
                    # `[BLOCKED` present but no parseable id — malformed. Never claim a garbage
                    # heading; leave it for /repair, exactly as before.
                    continue
                remaining = [b for b in blockers if b in all_ids]
                if len(remaining) != len(blockers):
                    # A blocker that no longer resolves to an item (finished, admin-done, or
                    # dangling) is stale — strip its marker. Line count is preserved so indices
                    # stay valid across the pass.
                    it["heading"] = _strip_cleared_blockers(it, all_ids)
                    lines[it["start"]] = "### " + it["heading"]
                    if it["body"]:
                        it["body"][0] = lines[it["start"]]
                    dirty = True
                if remaining:
                    continue  # still gated by a valid blocker
                # every blocker cleared → this item is now claimable (a [PRIORITY] marker it
                # carries takes effect from here — the sort key above already reads it)
            # Tier gate is the LAST skip, applied only after the blocked self-heal above so stale
            # markers are still cleaned regardless of who claims. Strict per-band: a model never
            # claims another tier's work; an out-of-tier-but-otherwise-claimable item is recorded
            # for the NONE-IN-TIER report instead.
            if caller_tier and _item_route(it["body"]).model != caller_tier:
                waiting.append(it)
                continue
            # --route narrows further, just as strictly: a `run` worker started for a fast-path
            # route must never fall through to a same-model route that plans first (see cmd_run).
            if opts.route and _item_route(it["body"]).name != opts.route:
                waiting.append(it)
                continue
            chosen = it
            break
        # The heal above always applies in memory, so the claim decision is right; it's persisted
        # only where a plain store write is allowed (not from a linked worktree — see
        # _store_writable_here), else the next main-checkout `next` strips the marker.
        if dirty and _store_writable_here():
            write_store(lines, [i["id"] for i in items])
        # Reported, never acted on: `next` must not free a claim on its own judgement.
        stale = _stale_claims(st.claims)
        # The hard gate: if an unblocked, unfinished [CRITICAL] item exists and this call isn't
        # claiming exactly that item — whether because it's already claimed by someone else (the
        # loop's `it["id"] in st.claims: continue` skipped it and fell through to something else),
        # its tier doesn't match the caller's (it landed in `waiting` and the loop fell through), or
        # nothing at all was claimable — refuse instead of claiming the fallback item or reporting
        # NONE/NONE-IN-TIER. This is checked *after* the loop (so stale-blocker self-heal above
        # still runs every call) and *before* any claim is committed.
        if active_critical is not None and (chosen is None or chosen["id"] != active_critical["id"]):
            crit = active_critical["id"]
            state = "already claimed" if crit in st.claims else "not yet claimed"
            if crit in stale:
                state += f" — holder looks STALE: {stale[crit]}"
            print(f"BLOCKED-BY-CRITICAL {crit} ({state}) — an unblocked critical "
                  "item gates the whole queue until it's claimed and finished; nothing else can be "
                  f"claimed in the meantime (`todo-lock.py show {crit}` for details)")
            if crit in stale:
                print(f"If that claim's tab is gone, free it with `todo-lock.py release {crit}` "
                      "(its worktree and branch are left in place), then re-run `next`.")
            maybe_update_notice()
            return 1
        if chosen is not None:
            # Seed the claim's files from the item's declared `**Files:**` bullet so other tabs
            # see the overlap immediately, before this tab refines the list with `lock`.
            seeded = _dedupe_paths(_split_declared_files(_item_files(chosen["body"])))
            # The `**Docs:**` bullet's paths ride along separately: soft for overlap (`_is_soft`),
            # and untouched by `lock <id> <files…>`, which replaces only `files`.
            seeded_docs = _dedupe_paths(_split_declared_docs(_item_docs(chosen["body"])))
            route = _item_route(chosen["body"])
            hit = overlap[chosen["id"]]
            st.claims[chosen["id"]] = {
                "status": "in_progress",
                "heading": chosen["heading"],
                "files": seeded,
                **({"docs": seeded_docs} if seeded_docs else {}),
                "worktree": None,
                "branch": None,
                "claimed_at": _now(),
                "body_sha": _body_sha(chosen["body"]),
                # Telemetry inputs (TOOL-34): facts only known at claim time. `declared` keeps the
                # Files bullet as filed, since `lock` replaces `files`.
                "declared": seeded,
                "model": opts.model,
                "route": route.name,
                "effort": route.effort,
                "overlap_note": bool(hit),
                **_owner_fields(),
            }
            st.save()
            _hook_queue("claim", chosen["id"], chosen["body"], worktree="", branch="")
            print(f"CLAIMED {chosen['id']}")
            problem = _routing_problem(chosen["body"])
            if problem:
                print(f"⚠ {problem} — routed to the default ({_routing()['default'].name}) "
                      "route; `doctor` reports it")
            if route.model in ROUTE_NOTES:
                print(f"route note ({route.model}): {ROUTE_NOTES[route.model]}")
            wants = route.effort
            if opts.effort and wants != opts.effort:
                print(f"note: {chosen['id']} wants {wants}, you are at {opts.effort}: "
                      f"consider /effort {wants}")
            if hit and hit[2] == "soft":
                heading = _claim_heading(hit[0], st.claims)
                print(f"note: declared docs overlap active claim {hit[0]} ({hit[1]})"
                      + (f" — {heading}" if heading else "") +
                      " — informational, docs merge cleanly; nothing was deferred for it.")
            elif hit:
                cid, f, kind = hit
                heading = _claim_heading(cid, st.claims)
                label = "⚠ HOT-FILE" if kind == "hot" else "note:"
                print(f"{label} declared files overlap active claim {cid} ({f})"
                      + (f" — {heading}" if heading else "") +
                      " — every non-overlapping item was blocked/claimed. Consider sequencing "
                      f"behind [BLOCKED: {cid}] instead of racing it. `show --brief {cid}` for more.")
            if not seeded:
                print(f"note: {chosen['id']} declares no files — other tabs' overlap checks can't "
                      f"see it until you run `lock {chosen['id']} <files…>`.")
            if stale:
                print(_stale_note(stale))
            # Held under State+StoreLock, so bound it: a slow grep costs the hint, not the claim.
            refs = _grep_ids_quiet([chosen["id"]], timeout=5)
            if refs:
                n = len(refs)
                print(f"{n} reference{'s' if n != 1 else ''} to this id: run `refs {chosen['id']}`")
            hint = _verify_hint()
            if hint:
                print(hint)
            # Also under the locks, so also bounded (FRESHNESS_BUDGET_S): decoration, not the claim.
            for line in _freshness_lines(chosen, items, set(st.claims)):
                print(line)
            for line in _docs_next_lines(seeded):
                print(line)
            for line in _context_block("plan-todo", with_verify=False):
                print(line)
            print()
            _print_claim_body(chosen["id"], chosen["body"])
            maybe_update_notice()
            return 0
        if (caller_tier or opts.route) and waiting:
            # Nothing in the caller's tier, but claimable work is waiting in other tiers. Print the
            # per-route counts and launch commands the AI relays to the user, distinct from the
            # plain NONE below (which means the backlog is genuinely empty of open work).
            wanted = " ".join(filter(None, [caller_tier and f"model tier {caller_tier!r}",
                                            opts.route and f"route {opts.route!r}"]))
            print(f"NONE-IN-TIER — no open item matches {wanted}; "
                  f"{len(waiting)} claimable item(s) waiting in other tiers:")
            for line in _route_lines(waiting):
                print(line)
            if stale:
                print(_stale_note(stale))
            maybe_update_notice()
            return 1
    print("NONE — no open, unclaimed, non-blocked item available")
    if stale:
        print(_stale_note(stale))
    maybe_update_notice()
    return 1


def _id_from_worktree_dir():
    """The item id in the current worktree's directory name (`…/todo+<ID>`, as /plan-todo's
    EnterWorktree names it), else None. Boundary-aware like _item_worktree_on_disk."""
    name = os.path.basename(_git("rev-parse", "--show-toplevel").rstrip("/"))
    m = re.search(r"(?:^|[^A-Za-z0-9])([A-Z]{2,}-\d+)$", name)
    return m.group(1) if m else None


def _resolve_id(argv, cmd):
    """(item id, remaining argv, error message or None): argv[0] when it is an id, else the id
    inferred from the worktree's directory name, so `attach` and `finish` need none from inside
    the item's worktree."""
    if argv and re.fullmatch(r"[A-Z]{2,}-\d+", argv[0]):
        return argv[0], argv[1:], None
    inferred = _id_from_worktree_dir()
    if inferred:
        return inferred, argv, None
    here = _git("rev-parse", "--show-toplevel")
    return None, argv, (f"ERROR — `{cmd}` names no item id and none can be inferred: {here} is "
                        "not a `todo+<ID>` worktree. Pass the id.")


def _bad_paths(files):
    """The tokens `lock` refuses as not-a-path: neither path-shaped nor present in a tree."""
    return [f for f in files if not _looks_like_path(f) and not _in_tree(f)]


def cmd_attach(argv):
    item_id, rest, err = _resolve_id(argv, "attach")
    if err:
        print(err)
        return 2
    # `attach <id> <wt> [br]` (recovery: attaching a path you're not in) — a worktree path is
    # absolute (or empty, recording none); a declared file never is. Otherwise the rest are the
    # claim's files, as `lock`.
    files = [] if rest and (not rest[0] or os.path.isabs(rest[0])) else rest
    bad = _bad_paths(files)
    if bad:
        print(f"ERROR — not a path: {', '.join(bad)} (want a repo-relative file, a `dir/`, or a "
              "glob; a dotless name must exist). Nothing recorded.")
        return 2
    # wt/br default to a `git` read in the CURRENT process cwd — i.e. the caller is expected to
    # run this from inside the item's own worktree, same assumption the refusal message below
    # already made. That keeps the common call a plain `attach <id>` with no command substitution
    # (the form `$(git rev-parse ...)` needs, which a worktree-isolated session refuses to run).
    worktree = rest[0] if rest and not files else _git("rev-parse", "--show-toplevel")
    branch = rest[1] if len(rest) > 1 and not files else _git("rev-parse", "--abbrev-ref", "HEAD")
    if os.path.realpath(worktree) == os.path.realpath(main_tree()):
        print(f"ERROR — refusing to attach {item_id}: the worktree path is the main checkout "
              f"({worktree}). This usually means `attach` ran after cd-ing back to the main "
              "tree instead of from inside the item's own worktree — recording it would make "
              "`land` merge main into itself as a silent no-op. Re-run `attach` from the "
              "actual worktree.")
        return 1
    with State() as st:
        if item_id not in st.claims:
            print(f"ERROR — {item_id} is not claimed")
            return 1
        st.claims[item_id]["worktree"] = worktree
        st.claims[item_id]["branch"] = branch
        st.claims[item_id].setdefault("attached_at", _now())
        st.claims[item_id].update(_owner_fields())
        st.save()
    # Printed relative to the repo root (TOOL-28) — the claim itself still stores the absolute
    # path `land`/`_worktree_setup`/etc. need. `worktree` can be '' (recording none, the
    # no-worktree recovery case) — `os.path.relpath` raises on an empty path, so guard it.
    shown = os.path.relpath(worktree, main_tree()) if worktree else "(none)"
    print(f"OK attached {item_id} -> {shown} ({branch})")
    _worktree_setup(item_id, worktree)
    if files:
        return cmd_lock([item_id, *files])
    return 0


def _worktree_setup(item_id, worktree):
    """Run the `worktree_setup` config command once for this claim's worktree, then print one line.

    The command is committed config, never item text, so it runs through the same `/bin/sh` path as
    `verify` (`_verify_run`), from the worktree root, with CLAUDE_TODO_MAIN_TREE naming the main
    checkout so it can clone a build cache or copy tool configs from there. Output goes to a log
    under the git common dir. Idempotent: a successful run is recorded on the claim (keyed by
    worktree path) and a later `attach` skips it; a failed run is not, so it retries once the command
    is fixed. Reported, never fatal — `attach` has already succeeded and exits 0 regardless."""
    if "worktree_setup" not in _config():
        return
    run = _config()["worktree_setup"]
    if not isinstance(run, str) or not run.strip():
        print("note: worktree_setup ignored (not a command string)")
        return
    with State() as st:
        done = st.claims.get(item_id, {}).get("setup") or {}
    if done.get("worktree") == worktree and done.get("rc") == 0:
        return
    log_dir = os.path.join(_common_dir(), VERIFY_LOG_DIR)
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{os.path.basename(worktree)}--worktree_setup")
    log_path = os.path.join(log_dir, slug + ".log")
    try:
        os.makedirs(log_dir, exist_ok=True)
        rc, secs, timed_out = _verify_run(
            run, worktree, log_path, VERIFY_DEFAULT_TIMEOUT,
            env={**os.environ, "CLAUDE_TODO_MAIN_TREE": main_tree()})
    except OSError as e:
        print(f"setup FAILED ({e.__class__.__name__}: {e}) — attach itself succeeded")
        return
    if rc == 0:
        with State() as st:
            if item_id in st.claims:
                st.claims[item_id]["setup"] = {"worktree": worktree, "rc": 0, "at": _now()}
                st.save()
        print(f"setup ok ({secs:.1f}s) — log: {log_path}")
        return
    why = f"timed out after {VERIFY_DEFAULT_TIMEOUT:g}s" if timed_out else f"exit {rc}"
    print(f"setup FAILED ({secs:.1f}s, {why}) — log: {log_path}; attach itself succeeded")


def cmd_resume(argv):
    item_id, rest, err = _resolve_id(argv, "resume")
    if err:
        print(err)
        return 2
    if rest:
        print(f"ERROR — `resume` takes no arguments besides the id ({item_id})")
        return 2
    with State() as st:
        claim = st.claims.get(item_id)
        if claim is None:
            print(f"ERROR — {item_id} is not claimed")
            return 1
        claim = dict(claim)
    print(f"RESUME {item_id}")
    print(f"worktree: {claim.get('worktree') or '(none)'}")
    print(f"branch: {claim.get('branch') or '(none)'}")
    print(f"files: {', '.join(claim.get('files') or []) or '(none)'}")
    if claim.get("version"):
        print(f"version: {claim['version']} ({claim.get('tier', 'patch')})")
    seq = claim.get("seq") or {}
    if seq:
        print("seq: " + ", ".join(f"{name}={nums}" for name, nums in seq.items()))
    hint = _verify_hint()
    if hint:
        print(hint)
    print()
    it = find_item(parse_items(read_lines()), item_id)
    if it is None:
        print(f"note: {item_id} is no longer in the store (GONE) — showing the claim's recorded "
              "heading only")
        print(claim.get("heading") or "(no heading recorded)")
        return 0
    _print_claim_body(item_id, it["body"])
    return 0


# @fragment 41_overlap.py
# ---------------------------------------------------------------------------
# Overlap — the one path matcher, hot/soft files, and the commands built on
# it: lock, touch, conflicts, preflight
# ---------------------------------------------------------------------------

# Files where a same-file edit across two open items is most likely and most costly. The universal
# defaults are the shared store + changelog; a host repo adds its own via `.claude/todo-config.json`
# (`hot_files` matched by basename, `hot_dirs` matched by directory component, both after
# `_norm_path`). An overlap on one of these is escalated from an advisory note to a loud warning.
DEFAULT_HOT_FILES = {"TODO.local.md", "CHANGELOG.md"}
DEFAULT_HOT_DIRS = set()


def _is_hot(path):
    """Whether a path is hot: its basename is in `hot_files`, or one of its directory components is
    in `hot_dirs`. Normalised first, and compared casefolded where the filesystem is case-insensitive
    (so `./CHANGELOG.md` and `changelog.md` stay hot there)."""
    fold = str.casefold if _fs_case_insensitive() else str
    hot_files = {fold(f) for f in DEFAULT_HOT_FILES | set(_config().get("hot_files") or [])}
    hot_dirs = {fold(d) for d in DEFAULT_HOT_DIRS | set(_config().get("hot_dirs") or [])}
    parts = fold(_norm_path(path)).rstrip("/").split("/")
    return parts[-1] in hot_files or bool(hot_dirs.intersection(parts))


def _is_soft(path, docs=()):
    """Whether an overlap on this path is informational only: one of its directory components is in
    `doc_dirs` (config, matched like `hot_dirs`), or it is covered by `docs` — the paths an item's
    `**Docs:**` bullet declared, a file or a `dir/`. Documentation merges cleanly in git, so it
    never defers an item. A hot path is never soft, whatever `doc_dirs` says."""
    if _is_hot(path):
        return False
    fold = str.casefold if _fs_case_insensitive() else str
    doc_dirs = {fold(d) for d in _config().get("doc_dirs") or []}
    key = _path_key(path)
    if doc_dirs.intersection(key.rstrip("/").split("/")):
        return True
    return any(key == d or (d.endswith("/") and key.startswith(d))
               for d in map(_path_key, docs))


# -- The overlap matcher -----------------------------------------------------------------------
# Every computed overlap check — `next`'s claim preference, `lock`, `conflicts` — goes through
# `_path_key` + `_paths_overlap`. Paths are stored as `_norm_path` gives them (repo-relative posix,
# readable case) and casefolded only when compared. Advisory throughout: a match defers or warns,
# never blocks, so the matcher leans towards reporting an overlap when it can't be sure.

_CASE_CACHE = {}
_ROOTS_CACHE = {}


def _is_glob(tok):
    return any(c in tok for c in "*?[")


def _fs_case_insensitive():
    """Whether the main checkout's filesystem ignores case (macOS and Windows defaults): probed once,
    by asking whether the git common dir also resolves under a swapped-case spelling."""
    if "v" not in _CASE_CACHE:
        common = _common_dir().rstrip(os.sep)
        head, tail = os.path.split(common)
        alt = os.path.join(head, tail.swapcase())
        try:
            _CASE_CACHE["v"] = alt != common and os.path.samefile(common, alt)
        except OSError:
            _CASE_CACHE["v"] = False
    return _CASE_CACHE["v"]


def _path_roots():
    """The trees a path may be relative to: the main checkout, then the current checkout (a
    worktree's own root, when a tab passes an absolute path into its worktree). Real paths."""
    if "v" not in _ROOTS_CACHE:
        roots = [os.path.realpath(main_tree())]
        try:
            here = os.path.realpath(_git("rev-parse", "--show-toplevel"))
            if here not in roots:
                roots.append(here)
        except (subprocess.CalledProcessError, OSError):
            pass
        _ROOTS_CACHE["v"] = roots
    return _ROOTS_CACHE["v"]


def _norm_path(tok):
    """A path token in canonical form: posix separators, relative to the main tree or the current
    worktree when absolute (left absolute if under neither), `./` and `..` folded, and a trailing
    `/` kept — or added when the token names an existing directory — as the directory marker."""
    p = tok.strip().replace("\\", "/")
    is_dir = p.endswith("/")
    if os.path.isabs(p):
        real = os.path.realpath(p)
        # Deepest root first: a worktree lives under the main tree (`.claude/worktrees/…`), and a
        # path in it is relative to the worktree, not `.claude/worktrees/<name>/…` of main.
        for root in sorted(_path_roots(), key=len, reverse=True):
            rel = os.path.relpath(real, root)
            if rel != ".." and not rel.startswith(".." + os.sep):
                real = rel
                break
        p = real.replace(os.sep, "/")
    p = posixpath.normpath(p)
    if p == ".":
        return "./"
    if not is_dir and not _is_glob(p) and not os.path.isabs(p):
        is_dir = any(os.path.isdir(os.path.join(root, p)) for root in _path_roots())
    return p + "/" if is_dir else p


def _path_key(tok):
    """The comparison key for a path token: `_norm_path`, casefolded on a case-insensitive FS."""
    p = _norm_path(tok)
    return p.casefold() if _fs_case_insensitive() else p


def _dedupe_paths(tokens):
    """Normalised, sorted, and one entry per comparison key (the first spelling wins)."""
    seen = {}
    for tok in tokens:
        seen.setdefault(_path_key(tok), _norm_path(tok))
    return sorted(seen.values())


def _glob_dir(pat):
    """The literal directory prefix of a glob (`docs/adr/*.md` → `docs/adr/`; `*.md` → '')."""
    literal = re.split(r"[*?\[]", pat, maxsplit=1)[0]
    head, slash, _ = literal.rpartition("/")
    return head + slash


def _paths_overlap(a, b):
    """Whether two comparison keys (`_path_key`) may name the same file. A trailing `/` is a
    directory, which overlaps everything beneath it; a glob overlaps what it matches; a token with
    no slash could live anywhere, so it matches by basename — the only case that falls back to it."""
    if a == b:
        return True
    ga, gb = _is_glob(a), _is_glob(b)
    if ga and gb:
        # Two patterns: overlap when their literal directories nest (conservative).
        da, db = _glob_dir(a), _glob_dir(b)
        return da.startswith(db) or db.startswith(da)
    if ga or gb:
        pat, other = (a, b) if ga else (b, a)
        if other.endswith("/"):
            d = _glob_dir(pat)
            return d.startswith(other) or other.startswith(d)
        if "/" not in pat:
            return fnmatch.fnmatchcase(posixpath.basename(other), pat)
        return fnmatch.fnmatchcase(other, pat)
    if (a.endswith("/") and b.startswith(a)) or (b.endswith("/") and a.startswith(b)):
        return True
    if a.endswith("/") or b.endswith("/"):
        return False
    if "/" not in a or "/" not in b:
        return posixpath.basename(a) == posixpath.basename(b)
    return False


def _claim_entries(files, docs=()):
    """(normalised path, comparison key, soft?) for every path a claim or an item holds — its
    `files` plus its `docs` — one entry per key. Normalised here, so a state file written before
    paths were canonical still matches."""
    seen = {}
    for f in [*files, *docs]:
        key = _path_key(f)
        if key not in seen:
            seen[key] = (_norm_path(f), key, _is_soft(f, docs))
    return sorted(seen.values())


def _overlap_kind(entry, theirs):
    """How one of my `_claim_entries` overlaps another holder's entries: None for no overlap, else
    `hot` (`_is_hot`), `soft` (mine and every path it hits are soft — documentation, informational)
    or `hard`. The one place overlap is classified, so `next`, `lock` and `conflicts` agree."""
    path, key, soft = entry
    hit = [t_soft for _, t_key, t_soft in theirs if _paths_overlap(key, t_key)]
    if not hit:
        return None
    if _is_hot(path):
        return "hot"
    return "soft" if soft and all(hit) else "hard"


def _overlaps(claims, me, files, docs=()):
    """(cid, file, kind) for every active claim other than `me` whose paths overlap one of `files`
    or `docs` (`_paths_overlap`); `kind` is `_overlap_kind`'s."""
    mine = _claim_entries(files, docs)
    hits = []
    for cid, claim in claims.items():
        if cid == me:
            continue
        theirs = _claim_entries(_claim_held(claim), claim.get("docs") or [])
        for entry in mine:
            kind = _overlap_kind(entry, theirs)
            if kind:
                hits.append((cid, entry[0], kind))
    return hits


def _in_tree(tok):
    """Whether a token names something that exists in the main tree or the current worktree."""
    p = _norm_path(tok)
    if os.path.isabs(p):
        return os.path.exists(p)
    return any(os.path.exists(os.path.join(root, p)) for root in _path_roots())


def cmd_lock(argv):
    ap = _ArgParser(prog="todo-lock.py lock", add_help=False)
    ap.add_argument("id")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--add", action="store_true", help="add <files> to the claim's list")
    mode.add_argument("--remove", action="store_true", help="drop <files> from the claim's list")
    ap.add_argument("files", nargs="*")
    opts = ap.parse_intermixed_args(argv)
    item_id = opts.id
    if not opts.files:
        # A bare `lock <id>` used to clear the list silently, hiding the claim from every overlap
        # check; emptying it now has to be spelled out with --remove.
        print(f"ERROR — `lock {item_id}` names no files; nothing changed. Pass the files it touches "
              "(replaces the list), or `--add <files…>` / `--remove <files…>` to edit it.")
        return 2
    bad = _bad_paths(opts.files)
    if bad:
        print(f"ERROR — not a path: {', '.join(bad)} (want a repo-relative file, a `dir/`, or a "
              "glob; a dotless name must exist). Nothing changed.")
        return 2
    with State() as st:
        if item_id not in st.claims:
            print(f"ERROR — {item_id} is not claimed")
            return 1
        current = st.claims[item_id].get("files") or []
        docs = st.claims[item_id].get("docs") or []
        if opts.add:
            files = _dedupe_paths(current + opts.files)
        elif opts.remove:
            gone = {_path_key(f) for f in opts.files}
            files = _dedupe_paths(f for f in current if _path_key(f) not in gone)
            # `docs` (seeded from the item's `**Docs:**` bullet) is a separate list that a
            # replacing `lock` leaves alone; removing a path drops it from there too.
            docs = [f for f in docs if _path_key(f) not in gone]
        else:
            files = _dedupe_paths(opts.files)
        st.claims[item_id]["files"] = files
        if docs:
            st.claims[item_id]["docs"] = docs
        else:
            st.claims[item_id].pop("docs", None)
        # A touched path the list now declares is declared, no longer touched-only; one --remove
        # names is dropped outright (the next heartbeat re-records it if the diff still has it).
        touched = _uncovered(st.claims[item_id].get("touched") or [], st.claims[item_id])
        if opts.remove:
            touched = [f for f in touched if _path_key(f) not in gone]
        if touched:
            st.claims[item_id]["touched"] = touched
        else:
            st.claims[item_id].pop("touched", None)
        st.claims[item_id].update(_owner_fields())
        st.save()
        hits = _overlaps(st.claims, item_id, files, docs)
        claims = dict(st.claims)  # snapshot for _print_overlaps' title lookup, after `with` closes
    print(f"OK locked {item_id}: {', '.join(files) if files else '(none)'}")
    if not files:
        print(f"⚠ {item_id} now declares no files — other tabs' overlap checks can't see it.")
    # Recording always succeeds (exit 0 — the worktree still isolates the edit). The value here is
    # the loud, actionable warning, not a hard gate: hot-file overlaps are escalated so a parallel
    # tab notices before two items diverge on the render engine or a shared doc.
    _print_overlaps(hits, claims)
    return 0


def _claim_heading(cid, claims):
    """The recorded title of another active claim, or '' — lets an overlap note name what it's
    overlapping with instead of costing the reader a separate `show`/`list` (TOOL-28)."""
    return (claims or {}).get(cid, {}).get("heading", "")


def _print_overlaps(hits, claims=None):
    """The overlap report `lock`/`attach` print for `_overlaps` hits — with `claims`, each note
    also names the other claim's title (`touch` stays title-less: its callers have already closed
    State by the time they get `hits`, and its PostToolUse-hook path must stay cheap)."""
    hot = [(cid, f) for cid, f, kind in hits if kind == "hot"]
    for cid, f in hot:
        heading = _claim_heading(cid, claims)
        print(f"⚠ HOT-FILE CONFLICT: {f} also claimed by {cid}" + (f" — {heading}" if heading else ""))
    for cid, f, kind in hits:
        heading = _claim_heading(cid, claims)
        suffix = f" — {heading}" if heading else ""
        if kind == "hard":
            print(f"note: overlap on {f} with {cid}{suffix}")
        elif kind == "soft":
            print(f"note: doc overlap on {f} with {cid} (informational — docs merge cleanly){suffix}")
    if hot:
        print("Coordinate before editing a hot file: sequence behind a [BLOCKED: <id>] dependency, "
              "or proceed knowing /finish resolves the merge on your branch (never on main)."
              + (f" `show --brief {hot[0][0]}` for more." if claims else ""))
    elif hits and claims:
        print(f"`show --brief {hits[0][0]}` for more.")


def cmd_touch(argv):
    """Record paths just edited on the current worktree's claim (TOOL-22). Reporting only: it never
    fails an edit, so anything but a usage error exits 0 — including `--hook`, which runs after
    every Edit/Write and must stay silent unless it has an overlap to tell the agent about."""
    ap = _ArgParser(prog="todo-lock.py touch", add_help=False)
    ap.add_argument("--hook", action="store_true",
                    help="read a PostToolUse hook payload on stdin instead of paths")
    ap.add_argument("paths", nargs="*")
    opts = ap.parse_args(argv)
    if opts.hook:
        try:
            return _touch_hook(json.load(sys.stdin))
        except Exception:  # noqa: BLE001 — a hook never fails the edit it follows
            return 0
    if not opts.paths:
        print("ERROR — usage: todo-lock.py touch <paths…> | --hook")
        return 2
    cid, new, hits = _touch_record(opts.paths)
    if cid is None:
        print("note: not in an attached claim's worktree; nothing recorded")
        return 0
    if new:
        print(f"OK touched {cid}: {', '.join('+' + p for p in new)}")
    _print_overlaps(hits)
    return 0


def _touch_record(paths):
    """(claim id, newly touched paths, their overlaps) for the claim of the current worktree;
    (None, [], []) outside one."""
    if not _in_linked_worktree():
        return None, [], []
    with State() as st:
        cid = _claim_for_here(st)
        if cid is None:
            return None, [], []
        new = _record_touched(st, cid, paths)
        if new:
            st.save()
        return cid, new, _overlaps(st.claims, cid, new) if new else []


def _touch_hook(payload):
    """`touch --hook`: the edited file from a PostToolUse payload, recorded from the payload's `cwd`
    (the session's worktree — the hook command itself may run elsewhere). A new hot/hard overlap
    goes back to the agent as `additionalContext`; otherwise nothing is printed."""
    tool_input = payload.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(path, str) or not path:
        return 0
    if payload.get("cwd"):
        os.chdir(payload["cwd"])
        _ROOTS_CACHE.clear()
    cid, _new, hits = _touch_record([path])
    lines = [f"{f} is also claimed by {other}" + (" (hot file)" if kind == "hot" else "")
             for other, f, kind in hits if kind in ("hot", "hard")]
    if lines:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": f"todo-lock: {cid} now touches undeclared paths that overlap "
                                 f"another claim: {'; '.join(lines)}. Recorded on the claim; "
                                 "consider `lock --add` and coordinating before going further.",
        }}))
    return 0


def cmd_conflicts(argv):
    me, files = argv[0], argv[1:]
    with State() as st:
        hits = _overlaps(st.claims, me, files, (st.claims.get(me) or {}).get("docs") or [])
    for cid, f, kind in hits:
        label = {"hot": "HOT-FILE CONFLICT", "soft": "DOC-OVERLAP"}.get(kind, "CONFLICT")
        print(f"{label} {cid} {f}")
    if not any(kind != "soft" for _, _, kind in hits):
        # Doc-only overlap is informational (`_is_soft`), so it doesn't fail the check.
        print("NO CONFLICTS")
        return 0
    return 1


def _git_at_least(major, minor):
    """(ok, `git --version` text) — whether the git on PATH is at least major.minor."""
    out = subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.strip()
    m = re.search(r"(\d+)\.(\d+)", out)
    return (not m or (int(m.group(1)), int(m.group(2))) >= (major, minor)), out


def cmd_preflight(argv):
    """Dry-run `land`'s merges before `land` does: the claim's branch against the integration
    branch, then against each other attached claim's branch, via `git merge-tree --write-tree`.
    Read-only — merge-tree may write loose objects, never a ref, the index or a worktree."""
    ap = _ArgParser(prog="todo-lock.py preflight",
                                 description="Preview merge conflicts before `land`.")
    ap.add_argument("id", nargs="?")
    opts = ap.parse_args(argv)
    ok, version = _git_at_least(2, 38)
    if not ok:
        print(f"preflight needs git 2.38 or newer for `merge-tree --write-tree` (found "
              f"{version}) — skipped; conflicts will still surface at `land`.")
        return 0
    base = base_branch()
    with State() as st:
        item_id = opts.id or (_claim_for_here(st) if _in_linked_worktree() else None)
        claims = {cid: dict(c) for cid, c in st.claims.items()}
    if item_id is None:
        print("ERROR — no <id> given and this checkout is not an attached claim's worktree.")
        return 1
    claim = claims.get(item_id)
    if claim is None:
        print(f"ERROR — {item_id} is not claimed")
        return 1
    mine, worktree = claim.get("branch"), claim.get("worktree")
    if not mine or mine == base:
        print(f"ERROR — {item_id} has no recorded worktree branch, so there is nothing to "
              "preview. Record it from inside the item's worktree first:")
        print(f"  python3 .claude/todo-lock.py attach {item_id}")
        return 1
    maintree = main_tree()

    def branch_exists(name):
        return subprocess.run(["git", "-C", maintree, "rev-parse", "--verify", "--quiet",
                               f"refs/heads/{name}"], capture_output=True).returncode == 0

    if not branch_exists(mine):
        print(f"ERROR — {item_id}'s branch {mine} no longer exists.")
        return 1
    if worktree and os.path.isdir(worktree) and subprocess.run(
            ["git", "-C", worktree, "status", "--porcelain"],
            capture_output=True, text=True).stdout.strip():
        print(f"note: {worktree} has uncommitted changes — merge-tree sees commits only; commit "
              "them for a full preview")
    sides = [(base, base)]
    for cid, c in sorted(claims.items()):
        other = c.get("branch")
        if cid == item_id or not other or other in (base, mine):
            continue
        if not branch_exists(other):
            print(f"note: {cid}'s branch {other} no longer exists — skipped")
            continue
        sides.append((cid, other))
    found = False
    for label, other in sides:
        # Refs were verified above: git also exits 1 for an unmergeable name, not just a conflict.
        r = subprocess.run(["git", "-C", maintree, "merge-tree", "--write-tree", "--name-only",
                            "--no-messages", other, mine], capture_output=True, text=True)
        if r.returncode not in (0, 1):
            print(f"ERROR — git merge-tree failed against {label}: "
                  f"{(r.stderr or r.stdout).strip()}")
            return 1
        if r.returncode == 1:
            # First line is the result tree's id; the rest name the conflicted paths.
            for path in dict.fromkeys(ln for ln in r.stdout.splitlines()[1:] if ln.strip()):
                print(f"CONFLICT {label} {path}")
                found = True
    if found:
        return 1
    print(f"CLEAN (checked against {base} and {len(sides) - 1} other branch(es))")
    return 0


# @fragment 42_claim_cmds.py
# ---------------------------------------------------------------------------
# Claim lifecycle — reserve-version, release, bounce, list, reclaim,
# stats, wait, main-tree
# ---------------------------------------------------------------------------

def _reset_hwm(st):
    """Recompute the version high-water mark from ground truth: the committed project version
    and the highest number still reserved by an active claim. Called after a claim is dropped so
    an abandoned reservation doesn't permanently burn a number (design-question (b))."""
    if not _version_configured():
        # No version source ⇒ no claim ever carries a reserved number; nothing to recompute.
        st.version.pop("hwm", None)
        return
    floor = _committed_version()
    reserved = [_parse_version(c["version"]) for c in st.claims.values() if c.get("version")]
    base = max([floor, *reserved])
    if not reserved:
        st.version.pop("hwm", None)  # nothing outstanding — collapse back to the committed version
    else:
        st.version["hwm"] = _fmt_version(base)


def cmd_reserve_version(argv):
    ap = _ArgParser(prog="todo-lock.py reserve-version", add_help=False)
    ap.add_argument("id")
    ap.add_argument("--tier", choices=("major", "minor", "patch"), default="patch")
    opts = ap.parse_args(argv)
    if not _version_configured():
        print("version bumping is not configured — set `version_source` in "
              "`.claude/todo-config.json` to enable `reserve-version` (see `help config`). "
              "With no version source, /finish lands without touching any version file.")
        return 2
    ver = _reserve_version(opts.id, opts.tier)
    if ver is None:
        print(f"ERROR — {opts.id} is not claimed")
        return 1
    print(ver)
    return 0


def _reserve_version(item_id, tier):
    """The claim's reserved version, handing out the next one under the State() flock if it has
    none yet; None when `item_id` is not claimed. Shared by `reserve-version` and `finish`."""
    with State() as st:
        claim = st.claims.get(item_id)
        if claim is None:
            return None
        if claim.get("version"):
            # Idempotent: a claim gets exactly one number, so re-running /finish's reserve step
            # (or a retry) reprints it without burning a second number.
            return claim["version"]
        hwm = _parse_version(st.version["hwm"]) if st.version.get("hwm") else None
        base = _committed_version()
        if hwm is not None:
            base = max(base, hwm)
        new = _fmt_version(_bump(base, tier))
        st.version["hwm"] = new
        claim["version"] = new
        claim["tier"] = tier
        st.save()
    return new


def cmd_release(argv):
    item_id = argv[0]
    with State() as st:
        _metrics_note(item_id, st.claims.get(item_id), "released")
        existed = st.claims.pop(item_id, None) is not None
        _reset_hwm(st)
        st.save()
    print(f"OK released {item_id}" if existed else f"OK {item_id} was not claimed")
    return 0


def _bounce_worktree_work(maintree, item_id, claim):
    """What a bounce would strand: a one-line description of the work in the claim's worktree (commits
    its branch has that the integration branch lacks, uncommitted changes), or None when there is
    none. The worktree is the claim's, else the one `_item_worktree_on_disk` finds for a tab that
    built one and never ran `attach`. A branch or worktree that is gone holds nothing to strand."""
    worktree = claim.get("worktree")
    if not (worktree and os.path.isdir(worktree)):
        worktree = _item_worktree_on_disk(maintree, item_id)
    if not (worktree and os.path.isdir(worktree)):
        return None
    branch = claim.get("branch") or _git("-C", worktree, "rev-parse", "--abbrev-ref", "HEAD")
    found = []
    ahead = subprocess.run(
        ["git", "-C", maintree, "rev-list", "--count", f"{base_branch()}..{branch}"],
        capture_output=True, text=True,
    ).stdout.strip()
    if ahead.isdigit() and int(ahead) > 0:
        found.append(f"{ahead} commit(s) on `{branch}` not on `{base_branch()}`")
    dirty = subprocess.run(
        ["git", "-C", worktree, "status", "--porcelain"], capture_output=True, text=True,
    ).stdout.strip()
    if dirty:
        found.append("uncommitted changes")
    return f"{worktree} has " + " and ".join(found) if found else None


def cmd_bounce(argv):
    """Re-route a claimed item whose planning showed it was filed on the wrong route, instead of
    grinding on or `release`-ing and losing what planning found: append a dated `Planning notes`
    bullet (the reason, plus optional notes from `--body-file` or stdin) to the item in the MAIN
    store, set its Route, commit the store on main like `add --commit`, and drop the claim.

    It is the claim holder's own edit, so `append`/`edit`'s claimed-item guard doesn't apply —
    their reason (a worktree's snapshot of the body would go stale) is moot once the claim is
    released here. What it refuses instead is a worktree that has work: releasing over that would
    strand it, so bounce is for the planning stage, before anything is implemented."""
    ap = _ArgParser(prog="todo-lock.py bounce", add_help=False)
    ap.add_argument("id")
    ap.add_argument("--to", required=True, metavar="ROUTE",
                    help="the named route to re-file the item under (see `routes`)")
    ap.add_argument("--reason", required=True, help="one line: why the item was on the wrong route")
    _body_file_flag(ap)
    opts = ap.parse_args(argv)
    if not ID_RE.fullmatch(opts.id):
        print(f"ERROR — id {opts.id!r} must match <LETTERS>-<number> (e.g. TASK-4)")
        return 2
    route, err = _parse_route(opts.to)
    if err:
        print(f"ERROR — --to {err}")
        return 2
    reason = opts.reason.strip()
    if not reason or "\n" in reason or "\r" in reason:
        print("ERROR — --reason must be one non-empty line")
        return 2
    notes = ""
    if opts.body_file or not sys.stdin.isatty():
        notes, _, err = _read_payload(opts.body_file)
        if err:
            print(f"ERROR — {err}. Nothing was written.")
            return 2
    notes = notes.strip("\n").split("\n") if notes.strip() else []
    problem = validate_body(notes)
    if problem:
        print(f"ERROR — the notes' {problem}. Nothing was written.")
        return 2
    maintree, store, rel, err = _commit_target()
    if err:
        print(f"ERROR — {err}")
        return 2
    with GitMutex():
        ok, note = _commit_precheck(maintree, rel)
        if not ok:
            print(note)
            return 2
        # State outer, StoreLock inner, as in cmd_add: the store write and the claim drop are one
        # atomic section, so a concurrent `next` never sees the item claimed on the old route or
        # unclaimed on a store that lacks the notes.
        with State() as st, StoreLock():
            claim = st.claims.get(opts.id)
            if claim is None:
                print(f"ERROR — {opts.id} is not claimed; bounce re-routes the claim you hold "
                      "(use `edit` on an unclaimed item)")
                return 2
            lines = read_lines(store)
            items = parse_items(lines)
            it = find_item(items, opts.id)
            if it is None:
                print(f"ERROR — no item {opts.id} in the store to bounce")
                return 2
            old = _item_route(it["body"])
            if old.name == route.name:
                print(f"ERROR — {opts.id} already routes to {route.name}; nothing to bounce. "
                      "`release` it if you just want to drop the claim")
                return 2
            stranded = _bounce_worktree_work(maintree, opts.id, claim)
            if stranded:
                print(f"REFUSED — {stranded}; bouncing would release {opts.id} over work that "
                      "nothing would carry. Nothing was written. Finish the item, or move that "
                      "work aside first.")
                return 1
            # Routing bullets are read first-match-wins, so the old Effort/Route bullets go and the
            # new Route bullet closes the item, where `_render_item` puts it.
            content = [ln for ln in it["body"][1:]
                       if not (ROUTE_LOOSE_RE.match(ln) or EFFORT_LOOSE_RE.match(ln))]
            trail = 0
            while content and content[-1].strip() == "":
                content.pop()
                trail += 1
            content += [f"- **Planning notes:** {_now()[:10]} — bounced {old.name} → {route.name}: "
                        f"{reason}"]
            content += [f"  {ln}" if ln.strip() else "" for ln in notes]
            content += [f"- **Route:** {route.name}"]
            new = lines[:it["start"]] + [it["body"][0], *content] + [""] * trail + lines[it["end"]:]
            write_store(new, [i["id"] for i in items], store)
            _metrics_note(opts.id, claim, "bounced")
            st.claims.pop(opts.id)
            _reset_hwm(st)
            st.save()
        subject = f"Bounce {opts.id} to {route.name}: {reason}"
        if len(subject) > COMMIT_SUBJECT_MAX:
            subject = subject[:COMMIT_SUBJECT_MAX - 1].rstrip() + "…"
        sha, err = _commit_store(maintree, rel, subject)
        if err:
            print(f"ERROR — bounced {opts.id} in {rel} on main, but the commit FAILED: {err}")
            print(f"The claim is released and the main tree is left dirty (which `land` rejects) "
                  f"— commit {rel} there by hand, or fix the cause.")
            return 1
    print(f"OK bounced {opts.id} {old.name} → {route.name}")
    print(_route_echo(content, opts.id))
    print(f"  to work it: {_launch_command(route)}")
    if note:
        print(note)
    print(f"OK committed {sha} on main ({rel})")
    if _in_linked_worktree():
        print("note: the claim is released — leave this worktree (ExitWorktree, action remove).")
    return 0


def cmd_list(_argv):
    with State() as st:
        claims = dict(st.claims)
    if not claims:
        print("(no active claims)")
        return 0
    # The store, to flag a claim whose item was removed or rewritten underneath it (e.g. by a
    # `/sync` pull). Unreadable store → no such flags; `list` still reports the claims.
    try:
        items = {it["id"]: it for it in parse_items(read_lines())}
    except OSError:
        items = None
    for cid, c in claims.items():
        files = ", ".join(c.get("files") or []) or "(none)"
        ver = f"  ver={c['version']}" if c.get("version") else ""
        flags = ""
        reason = _stale_reason(c)
        if reason:
            flags += f"  STALE: {reason}"
        if items is not None:
            if cid not in items:
                flags += "  GONE: no longer in the store"
            elif c.get("body_sha") and c["body_sha"] != _body_sha(items[cid]["body"]):
                flags += "  CHANGED: item text changed since claimed"
        touched = (f"  touched={', '.join('+' + t for t in c['touched'])}"
                   if c.get("touched") else "")
        print(f"{cid}  [{c.get('status')}]{ver}  wt={c.get('worktree')}  files={files}{touched}"
              f"{flags}")
    return 0


def cmd_reclaim(argv):
    ap = _ArgParser(prog="todo-lock.py reclaim", add_help=False)
    ap.add_argument("--stale", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    opts = ap.parse_args(argv)
    if not opts.stale:
        print("ERROR — reclaim needs --stale (it frees only claims that look abandoned; "
              "use `release <id>` to drop a specific claim)")
        return 2
    with State() as st:
        stale = _stale_claims(st.claims)
        freed = {cid: st.claims[cid] for cid in stale}
        if stale and not opts.dry_run:
            for cid in stale:
                _metrics_note(cid, st.claims[cid], "released")
                st.claims.pop(cid)
            _reset_hwm(st)
            st.save()
    if not stale:
        print("(no stale claims)")
        return 0
    verb = "WOULD RECLAIM" if opts.dry_run else "RECLAIMED"
    for cid, reason in stale.items():
        c = freed[cid]
        kept = f"; worktree {c['worktree']} / branch {c.get('branch')} left in place" \
            if c.get("worktree") else ""
        print(f"{verb} {cid} ({reason}){kept}")
    return 0


def _rate(num, den):
    return round(num / den, 3) if den else None


def _median(xs):
    xs = sorted(xs)
    if not xs:
        return None
    mid = len(xs) // 2
    return xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2


def _hours_between(a, b):
    try:
        return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 3600
    except (TypeError, ValueError):
        return None


def _metrics_stats(records):
    """The `stats` aggregate over telemetry records (see `_metrics_record`)."""
    outcomes = {"landed": 0, "released": 0, "bounced": 0}
    routes = {}
    landed = [r for r in records if r.get("outcome") == "landed"]
    for r in records:
        outcomes[r.get("outcome")] = outcomes.get(r.get("outcome"), 0) + 1
        row = routes.setdefault(r.get("route") or "(unknown)", {"items": 0, "landed": 0})
        row["items"] += 1
        row["landed"] += r.get("outcome") == "landed"
    hours = [h for r in landed
             if (h := _hours_between(r.get("claimed_at"), r.get("ended_at"))) is not None]
    # Declared-files accuracy, micro-averaged over landed items. Matched with `_paths_overlap`, so
    # a declared `dir/` or glob covers the files under it.
    covered = touched_n = used = declared_n = 0
    for r in landed:
        dk = [_path_key(p) for p in (r.get("files_declared") or {}).get("paths") or []]
        tk = [_path_key(p) for p in (r.get("files_touched") or {}).get("paths") or []]
        touched_n += len(tk)
        declared_n += len(dk)
        covered += sum(any(_paths_overlap(t, d) for d in dk) for t in tk)
        used += sum(any(_paths_overlap(t, d) for t in tk) for d in dk)
    median = _median(hours)
    return {
        "records": len(records),
        "outcomes": outcomes,
        "routes": dict(sorted(routes.items())),
        "median_claim_to_land_hours": round(median, 2) if median is not None else None,
        "declared_files": {"recall": _rate(covered, touched_n),
                           "precision": _rate(used, declared_n)},
        "fold_conflict_rate": _rate(sum(bool(r.get("fold_conflict")) for r in landed), len(landed)),
        "land_retries": sum(r.get("land_retries") or 0 for r in landed),
        "bounce_rate": _rate(outcomes["bounced"], len(records)),
        "release_rate": _rate(outcomes["released"], len(records)),
    }


def _read_metrics(since=None):
    """(records, unreadable line count) from the telemetry log, those ending on or after `since`
    (YYYY-MM-DD) when given. A missing log is no records."""
    records, skipped = [], 0
    try:
        with open(metrics_path(), encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    skipped += 1
                    continue
                if not isinstance(rec, dict):
                    skipped += 1
                elif not since or str(rec.get("ended_at") or "")[:10] >= since:
                    records.append(rec)
    except FileNotFoundError:
        pass
    return records, skipped


def cmd_stats(argv):
    """Aggregate the per-item telemetry (`_metrics_note`) — see the usage docs."""
    ap = _ArgParser(prog="todo-lock.py stats", add_help=False)
    ap.add_argument("--since", metavar="YYYY-MM-DD")
    ap.add_argument("--json", action="store_true")
    opts = ap.parse_args(argv)
    if opts.since:
        try:
            datetime.strptime(opts.since, "%Y-%m-%d")
        except ValueError:
            print(f"ERROR — --since {opts.since!r} is not a YYYY-MM-DD date")
            return 2
    path = metrics_path()
    records, skipped = _read_metrics(opts.since)
    agg = _metrics_stats(records)
    agg.update({"since": opts.since, "skipped_lines": skipped, "enabled": _metrics_enabled(),
                "source": path})
    if opts.json:
        print(json.dumps(agg, indent=2))
        return 0
    if not agg["enabled"]:
        print("note: telemetry is off (`\"metrics\": false` in .claude/todo-config.json) — no new "
              "records are written")
    if not records:
        print(f"stats: no records{f' since {opts.since}' if opts.since else ' yet'} ({path})")
        return 0
    o = agg["outcomes"]
    fmt = lambda v, suffix="": "n/a" if v is None else f"{v}{suffix}"  # noqa: E731
    print(f"stats: {agg['records']} item(s){f' since {opts.since}' if opts.since else ''} — "
          f"landed {o['landed']}, released {o['released']}, bounced {o['bounced']}")
    for name, row in agg["routes"].items():
        print(f"  route {name:<12} {row['items']:>4} item(s), {row['landed']} landed")
    df = agg["declared_files"]
    print(f"  median claim→land: {fmt(agg['median_claim_to_land_hours'], 'h')}")
    print(f"  declared files: recall {fmt(df['recall'])}, precision {fmt(df['precision'])}")
    print(f"  fold conflicts: {fmt(agg['fold_conflict_rate'])} of landed "
          f"({agg['land_retries']} land retries); bounce rate {fmt(agg['bounce_rate'])}, "
          f"release rate {fmt(agg['release_rate'])}")
    if skipped:
        print(f"  note: skipped {skipped} unreadable line(s) in {path}")
    return 0


def cmd_wait(argv):
    """Block until <id> leaves the MAIN store, then exit 0 — the signal a spun-off item
    "completed". A `/plan-todo` tab that files a prerequisite TODO and can't proceed without it
    runs this (as a background Bash command, so the harness re-triggers the agent when it exits,
    or a long foreground `timeout`) to wait for another tab to finish it.

    "Completed" == removed from TODO.local.md: /finish's `_land_remove_todo` excises a landed item,
    but a `remove`/cancellation disappears it the same way — `wait` treats ANY disappearance as the
    trigger. It watches `main_todo_path()` (the primary worktree's store, which `land` mutates), not
    the caller's worktree copy. Errors out up front if <id> doesn't currently exist (typo / nothing
    to wait on). Polls lock-free on an interval with a generous timeout safety net, printing a
    periodic heartbeat so a stalled wait (e.g. no other tab is running to pick the item up) stays
    visible."""
    ap = _ArgParser(prog="todo-lock.py wait", add_help=False)
    ap.add_argument("id")
    ap.add_argument("--interval", type=float, default=15.0, help="poll period, seconds")
    ap.add_argument("--heartbeat", type=float, default=120.0, help="heartbeat period, seconds")
    ap.add_argument("--timeout", type=float, default=7200.0, help="give-up safety net, seconds")
    opts = ap.parse_args(argv)
    path = main_todo_path()

    def present():
        return find_item(parse_items(read_lines(path)), opts.id) is not None

    if not present():
        print(f"NONE — no item {opts.id} in the backlog; nothing to wait on")
        return 1
    print(f"WAITING {opts.id} — polling every {opts.interval:g}s (timeout {opts.timeout:g}s). "
          f"A --priority item is only picked up by ANOTHER /plan-todo tab; start one if none is running.")
    start = time.monotonic()
    next_beat = start + opts.heartbeat
    while True:
        time.sleep(opts.interval)
        # Two consecutive absent reads confirm removal — cheap lock-free guard against catching
        # land's write_lines() mid-truncate (a torn read could momentarily show the item gone).
        if not present() and not present():
            print(f"DONE {opts.id} left the store after {time.monotonic() - start:.0f}s — "
                  f"`git merge main` into your worktree to pull it in.")
            return 0
        now = time.monotonic()
        if now >= next_beat:
            print(f"… still waiting on {opts.id} ({now - start:.0f}s elapsed)")
            next_beat = now + opts.heartbeat
        if now - start >= opts.timeout:
            print(f"TIMEOUT {opts.id} still present after {opts.timeout:g}s — "
                  f"check that a /plan-todo tab is finishing it.")
            return 1


def cmd_main_tree(_argv):
    print(main_tree())
    return 0


# @fragment 43_land.py
# ---------------------------------------------------------------------------
# Land — the only mutation of the base branch: bookkeeping, the guards ahead
# of the merge, land itself, and finish
# ---------------------------------------------------------------------------

CHANGELOG_HEAD_RE = re.compile(r"^## (\d+)\.(\d+)\.(\d+)\b")


def _changelog_rel():
    """Repo-root-relative path to the CHANGELOG re-sorted at land, or None when unconfigured."""
    return _config().get("changelog")


def _land_remove_todo(maintree, item_id):
    """Excise the landed item from the MAIN tree's store and unblock its dependents — the same
    edit `remove` makes, but applied post-merge on main (serial under the git mutex) instead of
    on the branch. Removals therefore never ride a branch, so two parallel finishes can't
    merge-conflict on TODO.local.md. Returns (removed, unblocked-ids, item) — `item` the parsed
    section that was cut (None when already gone), kept for the `land` hook's body snapshot."""
    path = os.path.join(maintree, "TODO.local.md")
    with StoreLock():
        lines = read_lines(path)
        items = parse_items(lines)
        it = find_item(items, item_id)
        if it is None:
            return False, [], None  # already gone (e.g. an older-style branch removed it) — fine
        return True, _excise_item(lines, items, it, path), it


def _land_write_version(maintree, reserved):
    """Write the claim's reserved version into the main tree's `__version__` — post-merge, so a
    release branch never edits that line and two parallel releases can't conflict on it. Landing
    order is decoupled from reservation order: an earlier-reserved number landing later must not
    roll main back, so the higher of (committed, reserved) wins. Returns the version written, or
    None if main is already at/above it."""
    path = os.path.join(maintree, _version_source_rel())
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = _version_source_re().search(text)
    if not m:
        raise ValueError(f"no `__version__ = \"x.y.z\"` line in {path}")
    committed = tuple(int(g) for g in m.groups())
    target = max(committed, _parse_version(reserved))
    if target == committed:
        return None
    _atomic_write(path, text[:m.start()] + f'__version__ = "{_fmt_version(target)}"' + text[m.end():])
    return _fmt_version(target)


def _land_sort_changelog(maintree):
    """Re-sort CHANGELOG.md's `## x.y.z` entries into descending SemVer order. The union merge
    driver keeps both parallel releases' entries but can leave the top two swapped; this makes
    the glance-and-reorder step deterministic. Conservative: if any entry heading doesn't parse
    or versions repeat, leave the file untouched. Returns True if the file was rewritten."""
    path = os.path.join(maintree, _changelog_rel())
    lines = read_lines(path)
    starts, in_fence = [], False
    for i, line in enumerate(lines):
        if line.strip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence and line.startswith("## "):
            starts.append(i)
    if len(starts) < 2:
        return False
    versions = []
    for i in starts:
        m = CHANGELOG_HEAD_RE.match(lines[i])
        if not m:
            return False
        versions.append(tuple(int(g) for g in m.groups()))
    if len(set(versions)) != len(versions):
        return False
    if versions == sorted(versions, reverse=True):
        return False
    chunks = [lines[a:b] for a, b in zip(starts, starts[1:] + [len(lines)])]
    ordered = [c for _, c in sorted(zip(versions, chunks), key=lambda p: p[0], reverse=True)]
    write_lines(lines[:starts[0]] + [l for c in ordered for l in c], path)
    return True


def _land_bookkeeping(maintree, item_id, reserved):
    """The deterministic post-landing bookkeeping, applied to the MAIN tree's files: the TODO-item
    removal (+ dependent unblocking) and — WHEN configured (see CONFIG) — the reserved version, the
    CHANGELOG entry order, superseded sequence entries, any sequence index, any generated
    table (`tables`), and the code map (`codemap`). Writes files only;
    the git work stays with the
    caller, because the two landing paths commit differently — the merge path amends the merge
    commit it just made, the `--in-place` recovery path has no merge commit and makes a fresh one.
    Returns (staged, removed, unblocked, written, indexes, item), `staged` being the repo-relative
    paths actually changed and `item` the removed section (see `_land_remove_todo`)."""
    staged = []
    removed, unblocked, item = _land_remove_todo(maintree, item_id)
    if removed:
        staged.append("TODO.local.md")
    # Version + CHANGELOG bookkeeping is opt-in (see CONFIG). With no `version_source`
    # configured, `reserved` is always empty and this block is skipped entirely — land
    # then does only the TODO-item removal + unblocking above.
    written = None
    if reserved and _version_configured():
        written = _land_write_version(maintree, reserved)
        if written:
            staged.append(_version_source_rel())
        if _changelog_rel() and _land_sort_changelog(maintree):
            staged.append(_changelog_rel())
    # A landed entry that declares `supersedes` flips its targets' status here, before the
    # index is regenerated so the index shows the flip. Prints its own NOTE/WARN lines.
    staged.extend(_seq_apply_supersedes(maintree))
    # Sequence indexes, same rationale: a table every entry appends a row to is the one
    # part of a numbered series that is NOT conflict-free by construction, so it's
    # regenerated here — on main, serially, from the entries the merge just brought in.
    # Opt-in per sequence; a sequence with no `index` is skipped, and a missing index
    # warns rather than raising (never half-land over it).
    indexes = []
    for name, scfg in _seq_indexed():
        rel = _seq_write_index(maintree, name, scfg)
        if rel:
            staged.append(rel)
            indexes.append(f"{name} -> {rel}")
    # Config-declared tables (`tables`) are the same conflict shape, regenerated the same way.
    for name, rel in _tables_land(maintree):
        staged.append(rel)
        indexes.append(f"{name} table -> {rel}")
    # The code map (`codemap`) goes stale on every edit to a mapped file, so it too is only ever
    # regenerated here, on main — a branch that committed it would conflict with every other.
    for rel in _codemap_land(maintree):
        staged.append(rel)
        indexes.append(f"codemap -> {rel}")
    return staged, removed, unblocked, written, indexes, item


def _land_commit_message(item_id, removed, written, indexes):
    """Subject for a no-merge landing path's bookkeeping commit — a plain description of what
    changed, following the repo convention (no agent references, no trailers). The merge path needs
    no equivalent: it amends the merge commit, which already has a message."""
    parts = []
    if removed:
        parts.append("remove the TODO item")
    if written:
        parts.append(f"set the version to {written}")
    if indexes:
        parts.append("regenerate the generated tables")
    return f"Land {item_id}: " + (", ".join(parts) or "bookkeeping")


def _land_bookkeeping_commit(maintree, item_id, reserved):
    """Run `_land_bookkeeping` on main and commit the result as a FRESH commit — shared by the two
    landing paths that do no merge (`--in-place`, and the auto-detected branch-with-no-commits-of-
    its-own case), because neither has a merge commit to amend and main's tip is not reliably this
    item's work. The merge path amends instead, which is the only difference between them.
    Returns (sha, removed, unblocked, written, indexes, item, head); `sha` is None when bookkeeping
    changed nothing, `head` is the base's full tip afterwards (the `land` hook's MERGE_SHA). The
    caller supplies the git mutex and handles failures."""
    staged, removed, unblocked, written, indexes, item = _land_bookkeeping(maintree, item_id,
                                                                            reserved)
    sha = None
    if staged:
        subprocess.run(["git", "-C", maintree, "add", "--", *staged], check=True)
        subprocess.run(
            ["git", "-C", maintree, "commit", "-q", "-m",
             _land_commit_message(item_id, removed, written, indexes)],
            check=True, capture_output=True,
        )
        sha = subprocess.run(
            ["git", "-C", maintree, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True,
        ).stdout.strip()
    head = subprocess.run(["git", "-C", maintree, "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    return sha, removed, unblocked, written, indexes, item, head


def _land_bookkeeping_only(item_id, reserved, maintree, what, why):
    """`_land_bookkeeping_commit` for the two no-merge paths, or None after a WARN when it failed
    part-way. `what` names the bookkeeping in the warning; `why` says why nothing was merged."""
    try:
        return _land_bookkeeping_commit(maintree, item_id, reserved)
    except Exception as exc:
        print(f"WARN — {item_id}'s {what} failed part-way: {exc.__class__.__name__}: {exc}")
        print(f"Nothing was merged ({why}), but the main tree may be left dirty with partial edits "
              f"— review `git -C {maintree} status`, commit what's correct, then "
              f"`todo-lock.py release {item_id}`.")
        return None


def _land_report(item_id, removed, unblocked, reserved, written, indexes):
    """The todo / version / index lines of every successful `land`, whichever path it took."""
    print(f"  todo: {f'removed {item_id}' if removed else 'not in store (already removed)'}"
          + (f"; unblocked {', '.join(unblocked)}" if unblocked else ""))
    if reserved:
        print(f"  version: {written or f'already ≥ {reserved} (no write)'}")
    if indexes:
        print(f"  index: regenerated {'; '.join(indexes)}")


def _land_release(item_id, lead, reserved, result):
    """Drop the claim of a no-merge landing — its work is already on the base branch, exactly as
    after the merge path — and print the report `lead` heads. `result` is the bookkeeping tuple."""
    sha, removed, unblocked, written, indexes, item, head = result
    with State() as st:
        _metrics_note(item_id, st.claims.get(item_id), "landed")
        claim = st.claims.pop(item_id, None) or {}
        _reset_hwm(st)
        st.save()
    _land_hook(item_id, item, claim, head)
    print(lead)
    _land_report(item_id, removed, unblocked, reserved, written, indexes)
    print(f"  commit: {sha or 'none (bookkeeping changed nothing)'}")
    print(f"  claim: released {item_id}")
    return 0


def _land_hook(item_id, item, claim, head):
    """Queue the `land` hook (fired by `main` once every lock is released). An item already gone
    from the store still fires, its snapshot just the claim's heading."""
    section = item["body"] if item else ([f"### {claim['heading']}"] if claim.get("heading") else [])
    _hook_queue("land", item_id, section, worktree=claim.get("worktree") or "",
                branch=claim.get("branch") or "", merge_sha=head)


def _item_worktree_on_disk(maintree, item_id):
    """A registered git worktree whose directory looks like this item's (`…/todo+<id>`), or None.
    A claim can lack a `branch` for two very different reasons: the tab worked in the main checkout
    (nothing to merge), or it built a worktree and never ran `attach` (work sitting on an orphan
    branch). Only the first is safe to land in place, and this is what tells them apart. Matching is
    boundary-aware so a worktree for `FOO-60` is not read as one for `FOO-6`."""
    out = subprocess.run(
        ["git", "-C", maintree, "worktree", "list", "--porcelain"],
        capture_output=True, text=True,
    ).stdout
    pat = re.compile(rf"(^|[^A-Za-z0-9]){re.escape(item_id)}$")
    for line in out.splitlines():
        if not line.startswith("worktree "):
            continue
        path = line[len("worktree "):].strip()
        if os.path.realpath(path) == os.path.realpath(maintree):
            continue
        if pat.search(os.path.basename(path.rstrip("/"))):
            return path
    return None


def _primary_checkout_off_base(maintree, item_id):
    """The refusal message when the primary checkout is NOT on the integration branch, or None.

    `land` merges into, and writes its bookkeeping on, whatever the primary checkout has checked
    out. With that tree parked on some other branch the merge and the TODO removal land there
    while the integration branch keeps listing the item — and the claim is released regardless, so
    the item goes back on offer with its work stranded. Caller holds the git mutex."""
    base = base_branch()
    head = subprocess.run(
        ["git", "-C", maintree, "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()
    if head == base:
        return None
    return (f"ERROR — the primary checkout ({maintree}) is on `{head}`, not the integration "
            f"branch `{base}`, so landing {item_id} would merge and write its bookkeeping on "
            f"`{head}`. Check out `{base}` there and retry `land`. (If `{base}` is not this "
            "repo's integration branch, set `base_branch` in `.claude/todo-config.json`.)")


def _land_worktree_ready(item_id, branch, worktree, allow_dirty):
    """Verify the item's worktree before anything is merged: its HEAD is the branch `land` is about
    to merge, and it holds no uncommitted work. Returns (message, exit_code) on refusal, else
    (None, None) — with `allow_dirty`, a WARN string and None for a dirty tree waved through.

    Why this has to happen here: `land` only ever checked the MAIN tree for dirtiness, and
    `/finish` step 6 then removes the worktree with `discard_changes: true`. A tracked edit or a
    new untracked file left in the worktree therefore landed as `OK`, the item was removed and the
    claim released, with the work on no branch at all. `status --porcelain` is the right test —
    it lists untracked files (the usual loss: a new file never `git add`ed) and omits ignored ones.

    The HEAD check guards the mirror case: a worktree switched to some other branch since `attach`
    means the recorded branch is not what holds the work, so merging it carries the wrong tree."""
    if not (worktree and os.path.isdir(worktree)):
        return None, None
    head = subprocess.run(
        ["git", "-C", worktree, "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()
    if head != branch:
        return (f"ERROR — {item_id}'s worktree ({worktree}) is on `{head}`, but the claim records "
                f"`{branch}`, so merging `{branch}` would not carry what is in that tree. If the "
                "work is on the branch the worktree is actually on, re-record it — run from "
                f"inside the worktree:\n"
                f"  python3 .claude/todo-lock.py attach {item_id}\n"
                f"  python3 .claude/todo-lock.py land {item_id}"), 1
    dirty = subprocess.run(
        ["git", "-C", worktree, "status", "--porcelain"],
        capture_output=True, text=True,
    ).stdout.strip()
    if not dirty:
        return None, None
    if allow_dirty:
        return (f"WARN — --allow-dirty: {item_id}'s worktree has uncommitted changes that will NOT "
                f"be landed and are lost when the worktree is removed:\n{dirty}"), None
    return (f"UNCOMMITTED — {item_id}'s worktree ({worktree}) has uncommitted changes, which no "
            "merge would carry and which are discarded when the worktree is removed. Commit them "
            f"there — that also gives the branch its real work — and retry `land {item_id}`; pass "
            "--allow-dirty only if you mean to abandon them:\n" + dirty), 5


def _land_in_place(item_id, reserved, maintree):
    """RECOVERY path for a claim with no branch to merge — the tab worked directly in the main
    checkout instead of the worktree /plan-todo step 4 creates. It runs the SAME bookkeeping as the
    merge path, on main, with no merge step, so the tool still owns the TODO removal, the version,
    the CHANGELOG order and any sequence index instead of the caller re-deriving them by hand from
    this script's source (which is what used to happen, expensively and unverified).

    This is not a second supported workflow: the worktree is the norm, and `--in-place` is the
    caller explicitly asserting there is genuinely no branch to merge — `land` must never infer
    that, since the same missing `branch` also describes an unattached worktree full of unmerged
    work. (A *recorded* branch that git proves is already contained in main is a different case,
    and not an inference — plain `land` handles it; see `_land_no_unique_commits`.)"""
    stray = _item_worktree_on_disk(maintree, item_id)
    if stray:
        print(f"ERROR — refusing --in-place: a worktree for {item_id} is still registered at "
              f"{stray}, so its work is probably on a branch that never reached the integration "
              "branch. Landing in "
              "place would release the claim over unmerged work. Record it and use the normal "
              "path instead:")
        print(f"  python3 .claude/todo-lock.py attach {item_id} {stray} <branch-name>")
        print(f"  python3 .claude/todo-lock.py land {item_id}")
        return 1
    with GitMutex():
        # The bookkeeping commit lands on whatever the primary checkout has checked out, so it
        # carries the same integration-branch requirement as the merge path.
        off_base = _primary_checkout_off_base(maintree, item_id)
        if off_base:
            print(off_base)
            return 1
        # Same guarantee as the merge path: never write bookkeeping over someone else's
        # uncommitted work. It doubles as the check that makes "the item's work is already
        # committed on the integration branch" a verified fact rather than an assumption.
        dirty = subprocess.run(
            ["git", "-C", maintree, "status", "--porcelain"],
            capture_output=True, text=True,
        ).stdout.strip()
        if dirty:
            print("DIRTY — the main working tree has uncommitted changes; commit the item's work "
                  "there (or stash what isn't yours), then retry `land --in-place`:")
            print(dirty)
            return 2
        result = _land_bookkeeping_only(item_id, reserved, maintree, "in-place bookkeeping",
                                        "there was no branch to merge")
        if result is None:
            return 1
    return _land_release(item_id, f"OK landed {item_id} in place on {base_branch()} (recovery "
                         "path — no worktree; /plan-todo step 4's worktree is the norm)",
                         reserved, result)


def _land_no_unique_commits(item_id, branch, reserved, maintree):
    """The claim HAS a branch, but git says the integration branch already contains every commit on
    it — so there is nothing to merge and only the bookkeeping is left. The normal way to get here
    is an item whose whole output went there directly: `add --admin --commit` from inside the
    worktree writes and commits in the MAIN checkout by design, so the branch never gains a commit
    of its own. Landing then used to dead-end (the fold fast-forwarded the branch to the base tip,
    the --no-ff merge was a no-op, and `land` reported the claim data as wrong), with no sanctioned
    way out.

    Unlike `--in-place` this needs no assertion from the caller: `merge-base --is-ancestor branch
    <base>` PROVES the branch holds nothing unmerged, where a missing `branch` proves nothing
    either way. `cmd_land` has already proven the tree itself carries nothing unmerged either —
    `_land_worktree_ready` ran before the routing, so the worktree is clean and on `branch` — which
    is what keeps the claim from being released over work that never reached the base branch.

    The caller must already hold the git mutex (lock order: GitMutex → State → StoreLock)."""
    base = base_branch()
    result = _land_bookkeeping_only(item_id, reserved, maintree, "bookkeeping",
                                    "the branch had no commits of its own")
    if result is None:
        return 1
    return _land_release(item_id, f"OK landed {item_id} ({branch}) on {base} — the branch had no "
                         f"commits of its own, so its work had already reached {base} directly "
                         "(e.g. `add --commit`): bookkeeping only, nothing to merge",
                         reserved, result)


def _land_managed_paths():
    """Repo-relative paths `land`'s own bookkeeping writes on the base. Every land touches them, so
    they never count as overlap for the post-fold verify."""
    paths = {"TODO.local.md", _version_source_rel(), _changelog_rel()}
    with contextlib.suppress(Exception):
        paths.update(_seq_index_cfg(cfg)["file"] for _name, cfg in _seq_indexed())
    with contextlib.suppress(Exception):
        paths.update(t["file"] for t in _tables_config()[0])
    with contextlib.suppress(Exception):
        paths.add((_codemap_config()[0] or {}).get("file"))
    return {os.path.normpath(p) for p in paths if isinstance(p, str) and p}


def _land_verify(item_id, branch, base, worktree, maintree, skip):
    """TOOL-13: after the fold, run the configured `test` in the worktree when the base's changes
    since the branch point share a directory with the branch's. Returns None to go on merging,
    or an exit code (6 VERIFY-FAILED). Runs under the git mutex, so the base can't move under it.

    The branch point is the parent of the oldest first-parent commit the base lacks — where the
    branch was cut, not the post-fold merge-base (the base tip), so a retry after VERIFY-FAILED
    still sees the foreign changes and re-runs the test."""
    try:
        cfg = _verify_cfg()
    except Exception:
        cfg = None
    if not cfg:
        return None
    commands, _default, flaky, _notes = cfg
    why = ("--no-verify" if skip else "no worktree recorded" if not worktree
           else "no `test` verify command" if "test" not in commands
           else "`test` needs a {target}" if "{target}" in commands["test"][0] else None)
    if why is None:
        own = subprocess.run(
            ["git", "-C", maintree, "rev-list", "--first-parent", branch, f"^{base}"],
            capture_output=True, text=True,
        ).stdout.split()
        if not own:
            return None

        def changed(*args):
            return set(subprocess.run(
                ["git", "-C", maintree, *args], capture_output=True, text=True,
            ).stdout.split("\n")) - {""}

        managed = _land_managed_paths()
        dirs = lambda paths: {os.path.dirname(p) for p in paths if os.path.normpath(p) not in managed}
        # Branch side: every file its own commits touched, not the net diff — a fix that reverts
        # the clash still has to be tested against what the base brought in.
        overlap = (dirs(changed("diff", "--name-only", f"{own[-1]}^", base))
                   & dirs(changed("log", "--first-parent", "--no-merges", "--format=",
                                  "--name-only", branch, f"^{base}")))
        if not overlap:
            why = "no overlap with what " + base + " changed since the branch point"
    if why:
        print(f"  verify: skipped ({why})")
        return None
    run, timeout = commands["test"]
    print(f"  verify: running `test` in {worktree} while holding the git mutex — other lands wait "
          f"(timeout {timeout:g}s; shared directories: "
          f"{', '.join(sorted(d or '.' for d in overlap))})")
    if _verify_execute("test", run, timeout, flaky, worktree) == 0:
        return None
    print(f"VERIFY-FAILED — `test` failed on {branch} after folding {base} into it; {base} was not "
          "touched and the fold commit stays on the branch. Fix it in the worktree, commit, and "
          f"re-run `land {item_id}` (`--no-verify` lands untested).")
    return 6


def cmd_land(argv):
    """Atomically land a claim's branch on the integration branch — the whole /finish merge-back in
    one call. Under the git mutex it: requires a clean main tree, a primary checkout actually on
    the integration branch, and a worktree with nothing uncommitted (exit 5 — what no merge would
    carry, /finish then discards with the worktree); folds the base INTO the branch (in its
    worktree) so any genuine conflict surfaces there, never on the base — a conflict stops here
    (exit 4) for the caller to resolve and retest; when a `verify` config exists and the base's
    changes share a directory with the branch's, runs its `test` on the folded tree (exit 6
    VERIFY-FAILED, base untouched; see _land_verify); then merges --no-ff into the base, conflict-free
    by construction. Post-merge it amends the deterministic bookkeeping into the merge commit —
    TODO item removal (+ unblocking dependents), and — WHEN configured (see CONFIG) — the reserved
    version, the CHANGELOG entry order, and any sequence index; precisely the files that used to
    conflict when edited on parallel branches; mutating them only here, serially on the base,
    removes those conflict classes entirely. Finally the claim is released.

    Which branch is the base is resolved by `base_branch()` (config, else discovery) — never the
    literal `main`, and never merely whatever the primary checkout happens to be sitting on.

    A branch git proves the base already contains carries nothing to merge — that is not an error,
    and it is detected before the fold (which would erase the evidence); see
    _land_no_unique_commits. `--in-place` is the recovery path for a claim with no branch at all —
    see _land_in_place."""
    ap = _ArgParser(
        prog="todo-lock.py land",
        description="Merge a claim's branch back into the integration branch and run the landing "
                    "bookkeeping.",
    )
    ap.add_argument("id")
    ap.add_argument("--in-place", action="store_true",
                    help="RECOVERY: the claim has no branch because the work was done in the main "
                         "checkout instead of a worktree — run the same bookkeeping there with "
                         "no merge step")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="land even though the item's worktree has uncommitted changes, abandoning "
                         "them (they are on no branch, and /finish removes the worktree)")
    ap.add_argument("--no-verify", action="store_true",
                    help="skip the configured `test` run after folding the base into the branch")
    opts = ap.parse_args(argv)
    item_id = opts.id
    base = base_branch()
    with State() as st:
        claim = st.claims.get(item_id)
        if claim is None:
            print(f"ERROR — {item_id} is not claimed")
            return 1
        branch, worktree = claim.get("branch"), claim.get("worktree")
        reserved = claim.get("version")
        claim["land_attempts"] = (claim.get("land_attempts") or 0) + 1  # telemetry: retries
        st.save()
    maintree = main_tree()
    if opts.in_place:
        if branch and branch != base:
            print(f"ERROR — {item_id} has a recorded branch ({branch}), so its work still has to "
                  "be merged and --in-place would skip that. Use the normal path — which also "
                  f"covers a branch that turns out to hold nothing {base} doesn't already have (it "
                  "runs the same bookkeeping, without a merge):")
            print(f"  python3 .claude/todo-lock.py land {item_id}")
            return 1
        return _land_in_place(item_id, reserved, maintree)
    if not branch:
        print(f"ERROR — {item_id} has no recorded branch, so there is nothing to merge back.")
        print("If you DID work in a worktree and just never attached it, record it and use the "
              "normal path:")
        print(f"  python3 .claude/todo-lock.py attach {item_id} <worktree-path> <branch-name>")
        print(f"  python3 .claude/todo-lock.py land {item_id}")
        print("If you worked directly in the main checkout — a RECOVERY case; /plan-todo step 4's "
              f"worktree is the norm — commit that work on {base} first, then land the bookkeeping "
              "in place (no merge step):")
        print(f"  git -C {maintree} status --porcelain      # must print nothing")
        print(f"  python3 .claude/todo-lock.py land {item_id} --in-place")
        return 1
    if branch == base:
        print(f"ERROR — {item_id}'s claim has branch=='{base}', the integration branch (attach "
              "likely ran from the main checkout instead of the item's worktree). Landing would "
              "merge that branch into itself as a silent no-op. If the work is on a worktree "
              "branch, re-run `attach` from that "
              f"worktree and retry `land {item_id}`. If it was done in the main checkout — a "
              "RECOVERY case; /plan-todo step 4's worktree is the norm — commit it there, then:")
        print(f"  python3 .claude/todo-lock.py land {item_id} --in-place")
        return 1
    fd = _mutex_acquire()
    try:
        # 0. the claim was read before the mutex (which may have been a long wait); a `release`
        #    (or re-attach) in that window must stop the land, not be overwritten by it. Mutex
        #    then State — the documented lock order.
        with State() as st:
            now_claim = st.claims.get(item_id)
        if (now_claim is None or now_claim.get("branch") != branch
                or now_claim.get("worktree") != worktree
                or now_claim.get("version") != reserved):
            print(f"ERROR — the claim on {item_id} was released or changed while `land` waited "
                  "for the git mutex, so nothing was merged. Check `todo-lock.py list`, re-claim "
                  "or re-attach if needed, and retry.")
            return 1
        # 1. the main tree must be clean — never merge into a dirty tree (that's where clobbers
        #    hide) — and actually on the branch this land is about to write.
        dirty = subprocess.run(
            ["git", "-C", maintree, "status", "--porcelain"],
            capture_output=True, text=True,
        ).stdout.strip()
        if dirty:
            print("DIRTY — the main working tree has uncommitted changes; commit or stash them, "
                  "then retry `land`:")
            print(dirty)
            return 2
        off_base = _primary_checkout_off_base(maintree, item_id)
        if off_base:
            print(off_base)
            return 1
        # 1b. and the item's own worktree must hold nothing a merge would leave behind. Before
        #     the routing below, so it covers the no-unique-commits path too, and before anything
        #     is merged, so a refusal costs nothing.
        note, code = _land_worktree_ready(item_id, branch, worktree, opts.allow_dirty)
        if note:
            print(note)
        if code is not None:
            return code
        # 2. does the branch actually carry anything? A claim legitimately reaches here with a
        #    branch the base already contains — an item that filed its whole output with
        #    `add --commit` from inside the worktree committed it to the MAIN checkout, never to
        #    the branch. This has to be settled BEFORE the fold below: the fold fast-forwards such
        #    a branch onto the base tip, after which "nothing to merge" and "claim data is corrupt"
        #    look identical. Direction is what tells them apart — branch ⊆ base means nothing is
        #    pending, whereas a branch with real work that the base passed is NOT an ancestor and
        #    still surfaces as STALE at step 3.
        if subprocess.run(
            ["git", "-C", maintree, "merge-base", "--is-ancestor", branch, base],
            capture_output=True,
        ).returncode == 0:
            return _land_no_unique_commits(item_id, branch, reserved, maintree)
        # 3. fold the base into the branch, in its worktree, still under the mutex — so no other
        #    land can advance the base between this fold and the merge below (no STALE retry loop).
        #    A conflict is resolved by the caller in the isolated worktree, never on the base.
        if worktree:
            fold = subprocess.run(
                ["git", "-C", worktree, "merge", "--no-edit", base],
                capture_output=True, text=True,
            )
            if fold.returncode != 0:
                conflicts = subprocess.run(
                    ["git", "-C", worktree, "diff", "--name-only", "--diff-filter=U"],
                    capture_output=True, text=True,
                ).stdout.strip()
                if conflicts:
                    with State() as st:  # telemetry; mutex → State is the documented order
                        if item_id in st.claims:
                            st.claims[item_id]["fold_conflict"] = True
                            st.save()
                    print(f"CONFLICT — folding {base} into {branch} conflicts; resolve in the "
                          "worktree with semantic care (reconcile both sides, re-run the tests), "
                          "commit the merge, then retry `land`:")
                    print(conflicts)
                    return 4
                print(f"ERROR — `git merge {base}` failed in {worktree} without conflicts (with "
                      "--allow-dirty, uncommitted changes there can block the fold — commit or "
                      "drop them, then retry `land`):")
                print((fold.stderr or fold.stdout).strip())
                return 1
        # 4. the branch must now contain the base tip, so the merge can't conflict. Without a
        #    recorded worktree (no fold possible) this is where a moved base surfaces as STALE.
        anc = subprocess.run(["git", "-C", maintree, "merge-base", "--is-ancestor", base, branch])
        if anc.returncode != 0:
            print(f"STALE — {base} advanced past {branch}; run `git merge --no-edit {base}` on "
                  "your branch, re-resolve/retest, then retry `land`.")
            return 3
        # 4b. the branch now holds the post-merge tree. Two entry files on one number merge
        #     without a conflict (different filenames), so git can't catch it — check here,
        #     before the base is touched (BUG-8).
        dup = _seq_land_duplicates(maintree, base, branch)
        if dup:
            print(dup)
            return 1
        # 4c. a clean fold is not a tested one: when the base's changes share a directory with the
        #     branch's, run the configured `test` on the folded tree before the base is touched.
        code = _land_verify(item_id, branch, base, worktree, maintree, opts.no_verify)
        if code is not None:
            return code
        # 4d. what the branch changed that its claim never declared (TOOL-22) — reported after the
        #     land, never a gate. Net branch diff (the fold made the base its merge-base) plus the
        #     claim's recorded `touched`.
        branch_diff = _branch_diff_paths(branch, base, maintree)
        undeclared = _land_undeclared(now_claim, branch_diff)
        # 5. clean, guaranteed-conflict-free merge into the base branch.
        pre_head = subprocess.run(
            ["git", "-C", maintree, "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        # Captured (TOOL-28): uncaptured, git's own diffstat prints straight to the terminal —
        # up to 31 lines observed. `merged_summary` below replaces it with one line.
        merge = subprocess.run(["git", "-C", maintree, "merge", "--no-ff", "--no-edit", branch],
                                capture_output=True, text=True)
        if merge.returncode != 0:
            # Shouldn't happen (branch contains the base) — but never force it; leave it clean.
            subprocess.run(["git", "-C", maintree, "merge", "--abort"])
            print(f"ERROR — merge into {base} failed unexpectedly and was aborted ({base} left "
                  "clean). Resolve manually and tell the user.")
            return 1
        post_head = subprocess.run(
            ["git", "-C", maintree, "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        if post_head == pre_head:
            # No new commit was created ("Already up to date") despite the ancestor check passing —
            # the claim's branch/worktree data is almost certainly wrong (e.g. a claim recorded
            # against the base by some path the guards above don't catch). The one legitimate way
            # to be here — a branch the base already contains — was routed away at step 2, so this
            # is now a genuine backstop. The base is provably untouched, so it's safe to bail with
            # no cleanup.
            print(f"ERROR — merging {branch} into {base} created no new commit (git reported "
                  f"'Already up to date'), so {item_id}'s actual changes were never merged. The "
                  f"claim's branch/worktree data is likely wrong. {base} was left untouched (no "
                  "bookkeeping was written), so it's safe to fix the claim — check `todo-lock.py "
                  "list`, re-`attach` from the correct worktree — and retry `land`.")
            return 1
        # 6. deterministic bookkeeping, amended into the merge commit while the mutex still holds.
        try:
            staged, removed, unblocked, written, indexes, item = _land_bookkeeping(
                maintree, item_id, reserved)
            if staged:
                subprocess.run(["git", "-C", maintree, "add", "--", *staged], check=True)
                subprocess.run(
                    ["git", "-C", maintree, "commit", "--amend", "--no-edit"],
                    check=True, capture_output=True,
                )
            # After the amend, still under the mutex: `post_head` above is the pre-amend commit.
            landed_head = subprocess.run(["git", "-C", maintree, "rev-parse", "HEAD"],
                                         capture_output=True, text=True).stdout.strip()
        except Exception as exc:
            print(f"WARN — landed {item_id} ({branch}) on {base}, but post-merge bookkeeping "
                  f"failed: {exc.__class__.__name__}: {exc}")
            print(f"Finish by hand on {base}: `todo-lock.py remove <id>`, set the version source to "
                  "the reserved number if this was a configured release, commit — then "
                  "`todo-lock.py release <id>`.")
            return 1
        # One-line stand-in for the diffstat `merge`'s own (now-captured) output would have printed
        # — read here, still under the mutex, so a concurrent `land` can't move `base` first.
        merged_summary = _land_merged_summary(maintree, pre_head)
    finally:
        _mutex_release(fd)
    # 7. the work is on the base — drop the claim (frees the id and reclaims the version reservation
    #    high-water mark against the now-updated committed version).
    with State() as st:
        cur = st.claims.get(item_id)
        if cur is not None and cur.get("branch") == branch:
            _metrics_note(item_id, cur, "landed", touched=branch_diff)
            st.claims.pop(item_id, None)
            _reset_hwm(st)
            st.save()
        else:
            print(f"WARN — the claim on {item_id} changed after the merge; left it as is.")
    _land_hook(item_id, item, now_claim, landed_head)
    print(f"OK landed {item_id} ({branch}) on {base}")
    print(f"  {merged_summary}")
    _land_report(item_id, removed, unblocked, reserved, written, indexes)
    print(f"  claim: released {item_id}")
    if undeclared:
        with State() as st:
            hits = _overlaps(st.claims, item_id, undeclared)
        print(f"  undeclared: {', '.join(undeclared)} (touched, never locked)")
        for cid, f, kind in hits:
            if kind != "soft":
                print(f"    {f} also claimed by {cid}" + (" — HOT-FILE" if kind == "hot" else ""))
    return 0


_SHORTSTAT_RE = re.compile(
    r"(\d+) files? changed(?:, (\d+) insertions?\(\+\))?(?:, (\d+) deletions?\(-\))?")


def _land_merged_summary(maintree, pre_head):
    """`merged <short-sha>, N files, +X -Y` for what `land` just put on `base` (from `pre_head`
    through the current HEAD, i.e. after the bookkeeping amend) — the one line that replaces
    `merge`'s own uncaptured diffstat (TOOL-28). Best-effort: a git failure still returns a line,
    naming just the sha with '?' counts, since a report is never worth failing an otherwise-done
    land over."""
    post_head = subprocess.run(
        ["git", "-C", maintree, "rev-parse", "HEAD"], capture_output=True, text=True,
    ).stdout.strip()
    short = subprocess.run(
        ["git", "-C", maintree, "rev-parse", "--short", post_head or "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip() or "?"
    stat = subprocess.run(
        ["git", "-C", maintree, "diff", "--shortstat", pre_head, post_head or "HEAD"],
        capture_output=True, text=True,
    ).stdout
    m = _SHORTSTAT_RE.search(stat)
    if not m:
        return f"merged {short}, ? files"
    files, ins, dels = int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0)
    return f"merged {short}, {files} files, +{ins} -{dels}"


def _branch_diff_paths(branch, base, maintree):
    """Paths the branch changed since its merge-base with `base`, minus `land`'s own bookkeeping
    files. Best-effort: [] if git can't say."""
    try:
        diff = subprocess.run(
            ["git", "-C", maintree, "diff", "--name-only", f"{base}...{branch}"],
            capture_output=True, text=True, check=True,
        ).stdout.splitlines()
        managed = _land_managed_paths()
        return [p for p in diff if p and os.path.normpath(p) not in managed]
    except Exception:  # noqa: BLE001 — reporting only; never fails a land
        return []


def _land_undeclared(claim, diff):
    """Paths the branch changed (`diff`), or the claim recorded as `touched`, that its declared
    `files` and `docs` don't cover. Best-effort: [] on any failure."""
    try:
        return _uncovered([*diff, *(claim.get("touched") or [])], claim)
    except Exception:  # noqa: BLE001 — reporting only; never fails a land
        return []


VERSION_PLACEHOLDER = "{VERSION}"
FINISH_STATUS_CAP = 20


def cmd_finish(argv):
    """/finish's commit and land in one call, run from the item's worktree (TOOL-31): fill a
    `{VERSION}` changelog placeholder from a reserved version, stage the tracked changes plus the
    untracked files it was told to include, commit on the branch, then `land`. Every refusal comes
    before anything is reserved, written or staged; success is reported only on `land`'s OK. It
    never removes the worktree — it prints the step that does."""
    item_id, rest, err = _resolve_id(argv, "finish")
    if err:
        print(err)
        return 2
    ap = _ArgParser(prog="todo-lock.py finish", add_help=False)
    ap.add_argument("-m", dest="subject", required=True)
    ap.add_argument("--body-file")
    ap.add_argument("--tier", choices=("major", "minor", "patch"))
    ap.add_argument("--include-untracked", nargs="*", metavar="PATH")
    ap.add_argument("--no-verify", action="store_true")
    opts = ap.parse_args(rest)
    if not opts.subject.strip():
        print("ERROR — `finish -m` needs a commit subject.")
        return 2
    body = ""
    if opts.body_file:
        with open(opts.body_file, encoding="utf-8") as fh:
            body = fh.read().strip()

    here = _git("rev-parse", "--show-toplevel")
    with State() as st:
        claim = st.claims.get(item_id)
    if claim is None:
        print(f"ERROR — {item_id} is not claimed")
        return 1
    if os.path.realpath(here) == os.path.realpath(main_tree()):
        print(f"ERROR — `finish` commits on the item's branch, so it runs from {item_id}'s "
              "worktree, not the main checkout.")
        return 1
    if not claim.get("worktree") or os.path.realpath(claim["worktree"]) != os.path.realpath(here):
        print(f"ERROR — {item_id} is not attached to this worktree ({here}). Record it first:\n"
              f"  python3 .claude/todo-lock.py attach {item_id}")
        return 1
    if subprocess.run(["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"], cwd=here,
                      capture_output=True).returncode == 0:
        print(f"ERROR — a merge is in progress in this worktree. Resolve it, `git add` the "
              f"resolved files and `git commit`, then re-run `land {item_id}` (not `finish`).")
        return 1

    changelog = _changelog_rel()
    cl_path = os.path.join(here, changelog) if changelog else None
    cl_text = None
    if cl_path and os.path.exists(cl_path):
        with open(cl_path, encoding="utf-8") as fh:
            cl_text = fh.read()
    if opts.tier and not _version_configured():
        print("ERROR — --tier needs release bookkeeping: `version_source` is not set in "
              "`.claude/todo-config.json` (see `help config`). Drop --tier; nothing changed.")
        return 2
    if not opts.tier and cl_text and VERSION_PLACEHOLDER in cl_text:
        print(f"ERROR — {changelog} holds a {VERSION_PLACEHOLDER} placeholder but no --tier was "
              "given, so it would be committed unfilled. Pass --tier major|minor|patch, or "
              "remove the placeholder. Nothing changed.")
        return 2

    untracked = [p for p in subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"], cwd=here,
        capture_output=True, text=True, check=True).stdout.splitlines() if p]
    if opts.body_file:
        # The message file is input to this call, not work: never staged, never a refusal.
        body_rel = os.path.relpath(os.path.realpath(opts.body_file), os.path.realpath(here))
        untracked = [u for u in untracked if u != body_rel]
    if opts.include_untracked is None:
        include = []
    elif not opts.include_untracked:
        include = untracked  # bare flag: take them all
    else:
        wanted = [_norm_path(p).rstrip("/") for p in opts.include_untracked]
        include = [u for u in untracked if any(u == w or u.startswith(w + "/") for w in wanted)]
    left = [u for u in untracked if u not in include]
    if left:
        shown = left[:FINISH_STATUS_CAP]
        more = f"\n  … {len(left) - len(shown)} more" if len(left) > len(shown) else ""
        print(f"UNTRACKED — {item_id}'s worktree has untracked files `finish` was not told to "
              "include; nothing was staged. Pass `--include-untracked` (all of them) or "
              "`--include-untracked <paths…>`, or delete / ignore them:\n"
              + "\n".join(f"  {u}" for u in shown) + more)
        return 5

    if opts.tier:
        ver = _reserve_version(item_id, opts.tier)
        print(f"version: reserved {ver} ({opts.tier})")
        if cl_text and VERSION_PLACEHOLDER in cl_text:
            _atomic_write(cl_path, cl_text.replace(VERSION_PLACEHOLDER, ver))
            print(f"  {changelog}: {VERSION_PLACEHOLDER} -> {ver}")
        elif changelog and not (cl_text and ver in cl_text):
            print(f"note: {changelog} has no {VERSION_PLACEHOLDER} placeholder and doesn't name "
                  f"{ver} — the release has no changelog entry.")

    subprocess.run(["git", "add", "-u", ":/"], cwd=here, check=True, capture_output=True)
    if include:
        subprocess.run(["git", "add", "--", *include], cwd=here, check=True,
                       capture_output=True)
    staged = subprocess.run(["git", "diff", "--cached", "--name-status"], cwd=here,
                            capture_output=True, text=True, check=True).stdout.splitlines()
    if not staged:
        print(f"ERROR — nothing to commit in {item_id}'s worktree. If the work is already "
              f"committed on the branch, land it with `land {item_id}`.")
        return 1
    shown = staged[:FINISH_STATUS_CAP]
    print(f"staging {len(staged)} path(s):")
    for line in shown:
        print(f"  {line}")
    if len(staged) > len(shown):
        print(f"  … {len(staged) - len(shown)} more")

    # The message is exactly what the caller wrote: the script adds no trailer of its own.
    message = opts.subject.strip() + (f"\n\n{body}" if body else "") + "\n"
    commit = subprocess.run(["git", "commit", "-q", "-F", "-"], cwd=here, input=message,
                            capture_output=True, text=True)
    if commit.returncode != 0:
        print(f"ERROR — `git commit` failed (exit {commit.returncode}); the changes stay staged "
              f"and nothing was landed:\n{(commit.stdout + commit.stderr).strip()}")
        return 1
    sha = _git("rev-parse", "--short", "HEAD")
    print(f"OK committed {sha} on {claim.get('branch') or 'the branch'}")

    rc = cmd_land([item_id, *(["--no-verify"] if opts.no_verify else [])])
    if rc != 0:
        print(f"note: the commit is on the branch; after following the recovery above, re-run "
              f"`land {item_id}` (not `finish`, which would need new changes to commit).")
        return rc
    print('next: ExitWorktree with action: "remove", discard_changes: true')
    return 0


# @fragment 44_verify.py
# ---------------------------------------------------------------------------
# git-mutex and verify — the configured check commands, run blocking
# ---------------------------------------------------------------------------

def cmd_git_mutex(argv):
    # Serialize index-touching git ops (commits, merge-backs) across worktrees so parallel
    # /finish and /todo runs don't race .git/index.lock.
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        print("ERROR — git-mutex needs a command after --")
        return 2
    fd = _mutex_acquire()
    try:
        return subprocess.run(argv).returncode
    finally:
        _mutex_release(fd)


VERIFY_DEFAULT_TIMEOUT = 1800
VERIFY_MAX_LINES = 30
VERIFY_TAIL_LINES = 15
VERIFY_LINE_CLIP = 200
VERIFY_LOG_DIR = "claude-todo-verify"
# A line that reports a failure, in the spellings common test runners, compilers and linters use.
VERIFY_FAIL_RE = re.compile(
    r"\bFAIL(?:ED|URE|S)?\b|\bERROR\b|\berror\b|\bfailed\b|\bfailures?\b|Traceback|panic:"
    r"|AssertionError|Exception\b|✗|✘")
VERIFY_TEST_TOKEN_RE = re.compile(r"\w*[Tt]est\w*")
# An aggregate count line (`FAILED (failures=2)`, `3 failed, 10 passed`, a bare `FAIL`) names no
# test, so it neither blocks nor proves a flaky-only failure.
VERIFY_SUMMARY_RE = re.compile(
    r"^\W*(?:FAIL(?:ED)?|ERROR)\W*(?:\(.*\))?\s*$|^\W*=*\s*\d+ (?:failed|errors?)\b"
    r"|\bfailures=\d+|^Ran \d+ tests?|^make(?:\[\d+\])?: \*\*\*|exit status \d+\s*$")


def _verify_cfg():
    """The `verify` config block as (commands, timeout, flaky, notes), or None when no command is
    configured. `commands` maps name -> (run string, timeout seconds)."""
    block = _config().get("verify")
    if not isinstance(block, dict) or not isinstance(block.get("commands"), dict):
        return None
    default = block.get("timeout", VERIFY_DEFAULT_TIMEOUT)
    commands = {}
    for name, spec in block["commands"].items():
        run, timeout = (spec, default) if isinstance(spec, str) else (
            (spec.get("run"), spec.get("timeout", default)) if isinstance(spec, dict) else (None, 0))
        if isinstance(run, str) and run.strip() and isinstance(timeout, (int, float)) and timeout > 0:
            commands[name] = (run, timeout)
    if not commands:
        return None
    strs = lambda v: [s for s in v if isinstance(s, str) and s] if isinstance(v, list) else []
    return commands, default, strs(block.get("flaky")), strs(block.get("notes"))


def _verify_hint():
    """`next`'s one line naming the configured verify commands, or None. Never raises: a malformed
    block must not cost the claim it decorates."""
    try:
        cfg = _verify_cfg()
    except Exception:
        return None
    if not cfg:
        return None
    commands, _default, _flaky, notes = cfg
    names = ", ".join(n + (" <target>" if "{target}" in run else "")
                      for n, (run, _t) in commands.items())
    return (f"verify: {names} — run `todo-lock.py verify [name]`"
            + (" · notes: `verify --list`" if notes else ""))


def _verify_failure_lines(lines):
    return [ln for ln in lines if VERIFY_FAIL_RE.search(ln)]


def _verify_flaky_only(fail_lines, flaky):
    """The flaky names a failure is entirely made of, or [] to not retry. A failure line that
    names a flaky entry counts for it; one that names some other test (a `test…`/`Test…` token,
    as `FAIL: test_x`, `--- FAIL: TestX`, `tests/a.py::test_x` do) vetoes the retry; a line naming
    no test (`AssertionError: …`, `FAILED (failures=1)`) is neutral. Heuristic by design: it only
    ever buys one extra run, never hides a failure the retry repeats."""
    if not flaky:
        return []
    hit = []
    for ln in fail_lines:
        names = [f for f in flaky if f in ln]
        if names:
            hit += [f for f in names if f not in hit]
        elif not VERIFY_SUMMARY_RE.search(ln) and VERIFY_TEST_TOKEN_RE.search(ln):
            return []
    return hit


def _verify_run(run, cwd, log_path, timeout, env=None):
    """Run one command to completion, output streamed to `log_path`. Returns (rc, seconds,
    timed_out). rc is None on a timeout. `env` replaces the child's environment when given."""
    start = time.monotonic()
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        # The only shell=True in the script, on purpose: `run` comes from the committed
        # `.claude/todo-config.json` (never from item text), and the recipe is a shell line
        # (pipes, `&&`, env assignments). /bin/sh, not $SHELL: the config is shared by every
        # collaborator, and $SHELL may be fish. `--only`'s target is shlex-quoted before this.
        proc = subprocess.Popen(run, shell=True, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            rc = proc.wait(timeout=timeout)
            return rc, time.monotonic() - start, False
        except subprocess.TimeoutExpired:
            # Kill the whole process group: the shell's children (the test runner) outlive it.
            for sig, grace in ((15, 5), (9, None)):
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(proc.pid, sig)
                try:
                    proc.wait(timeout=grace)
                    break
                except subprocess.TimeoutExpired:
                    continue
            log.write(f"\n[todo-lock.py verify: killed after {timeout:g}s timeout]\n")
            return None, time.monotonic() - start, True


def cmd_verify(argv):
    """Run a configured verify command from the current worktree root, BLOCKING until it exits;
    the full output goes to a log under the git common dir and only the verdict is printed: one
    PASS line, or FAIL + up to VERIFY_MAX_LINES failure lines + the log path. A failure made only
    of `flaky` tests is retried once. This is what replaces background waiters and sleep polls on
    half-written logs: the caller gets nothing until there is a result."""
    ap = _ArgParser(prog="todo-lock.py verify", add_help=False)
    ap.add_argument("name", nargs="?")
    ap.add_argument("--only")
    ap.add_argument("--list", action="store_true")
    opts = ap.parse_args(argv)
    cfg = _verify_cfg()
    if not cfg:
        print('ERROR — no verify commands configured; add "verify": {"commands": {"test": "…"}} '
              "to .claude/todo-config.json (see `help config`).")
        return 2
    commands, _default, flaky, notes = cfg
    if opts.list:
        for n, (run, t) in commands.items():
            print(f"{n}\t{run}\t(timeout {t:g}s)")
        if flaky:
            print(f"flaky: {', '.join(flaky)}")
        for note in notes:
            print(f"note: {note}")
        return 0
    name = opts.name or ("test" if "test" in commands else
                         next(iter(commands)) if len(commands) == 1 else None)
    if name not in commands:
        what = f"unknown verify command {opts.name!r}" if opts.name else "several verify commands"
        print(f"ERROR — {what}; pick one of: {', '.join(commands)}")
        return 2
    run, timeout = commands[name]
    if "{target}" in run:
        if opts.only is None:
            print(f"ERROR — `{name}` needs a target: verify {name} --only <target>")
            return 2
        run = run.replace("{target}", shlex.quote(opts.only))
    elif opts.only is not None:
        print(f"ERROR — `{name}` has no {{target}} placeholder, so --only can't narrow it")
        return 2
    return _verify_execute(name, run, timeout, flaky, _git("rev-parse", "--show-toplevel"))


def _verify_execute(name, run, timeout, flaky, root):
    """Run one resolved verify command in `root` and print its verdict (PASS line, or FAIL + the
    failure lines + log path), retrying once a failure made only of `flaky` tests. Returns 0 or 1.
    Shared by `verify` and `land`'s post-fold check, so both report identically."""
    log_dir = os.path.join(_common_dir(), VERIFY_LOG_DIR)
    os.makedirs(log_dir, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{os.path.basename(root)}--{name}")
    log_path = os.path.join(log_dir, slug + ".log")

    rc, secs, timed_out = _verify_run(run, root, log_path, timeout)
    retried, total = [], secs
    if rc != 0 and not timed_out:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            retried = _verify_flaky_only(_verify_failure_lines(f.read().splitlines()), flaky)
        if retried:
            rc, secs, timed_out = _verify_run(run, root, log_path, timeout)
            total += secs
    flaky_s = f" — flaky retry: {', '.join(retried)}" if retried else ""
    if rc == 0:
        print(f"PASS verify {name} ({total:.1f}s){flaky_s} — log: {log_path}")
        return 0
    why = f"timed out after {timeout:g}s" if timed_out else f"exit {rc}"
    also = " (flaky retry also failed)" if retried else ""
    print(f"FAIL verify {name} ({total:.1f}s, {why}){also} — log: {log_path}")
    with open(log_path, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    shown = _verify_failure_lines(lines) or [ln for ln in lines if ln.strip()][-VERIFY_TAIL_LINES:]
    for ln in shown[:VERIFY_MAX_LINES]:
        print("  " + (ln if len(ln) <= VERIFY_LINE_CLIP else ln[:VERIFY_LINE_CLIP] + "…"))
    if len(shown) > VERIFY_MAX_LINES:
        print(f"  … {len(shown) - VERIFY_MAX_LINES} more — see the log")
    return 1


# @fragment 45_hooks.py
# ---------------------------------------------------------------------------
# hooks — optional config commands fired on claim, land, remove and add
# ---------------------------------------------------------------------------

HOOK_EVENTS = ("claim", "land", "remove", "add")
HOOKS_DIR = "claude-todo-hooks"
# Events recorded while the command runs, fired by `_hooks_flush` from `main` once it returns.
_HOOK_QUEUE = []


def _hooks_problems(value):
    """What is wrong with a `hooks` config value, as a list of plain lines ([] when it is fine)."""
    if value is None:
        return []
    if not isinstance(value, dict):
        return ["`hooks` must be an object mapping an event to a shell line"]
    out = []
    for event, run in value.items():
        if event not in HOOK_EVENTS:
            out.append(f"hooks.{event}: unknown event (one of {', '.join(HOOK_EVENTS)})")
        elif not isinstance(run, str) or not run.strip():
            out.append(f"hooks.{event}: not a command string")
    return out


def _hook_cmd(event):
    """The configured shell line for `event`, or None — absent, malformed, or no `hooks` key."""
    hooks = _config().get("hooks")
    run = hooks.get(event) if isinstance(hooks, dict) else None
    return run if isinstance(run, str) and run.strip() else None


def _hook_queue(event, item_id, section, worktree=None, branch=None, merge_sha=""):
    """Record that `event` happened to `item_id`. A list append and nothing else — safe under any
    lock; the hook itself runs from `_hooks_flush` after the command has released them all.
    `section` is the item's heading + body lines (None when unknown). `worktree`/`branch` None
    means "look the claim up at fire time"."""
    if _hook_cmd(event) is None:
        return
    _HOOK_QUEUE.append((event, item_id, list(section or []), worktree, branch, merge_sha))


def _hooks_flush(trigger):
    """Fire every queued hook. Called by `main` after the command returns, so no GitMutex, State or
    StoreLock is held. Never raises: a hook problem is one printed line, never a crash class, and
    `trigger`'s exit code stands."""
    while _HOOK_QUEUE:
        event, item_id, section, worktree, branch, merge_sha = _HOOK_QUEUE.pop(0)
        try:
            _run_hook(event, item_id, section, worktree, branch, merge_sha, trigger=trigger)
        except Exception as exc:  # noqa: BLE001 — reported, never fatal
            print(f"hook {event} FAILED ({exc.__class__.__name__}: {exc}) — "
                  f"{trigger} itself succeeded")


def _hooks_dir():
    return os.path.join(_common_dir(), HOOKS_DIR)


def _hook_ledger_path(item_id):
    return os.path.join(_hooks_dir(), re.sub(r"[^A-Za-z0-9._-]+", "_", item_id) + ".json")


def _hook_ledger(item_id):
    try:
        with open(_hook_ledger_path(item_id), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _hook_body_path(item_id, event):
    return os.path.join(_hooks_dir(), re.sub(r"[^A-Za-z0-9._-]+", "_", f"{item_id}--{event}") + ".md")


def _hook_title(item_id, section):
    head = section[0] if section else ""
    return _split_heading(item_id, head[4:])["title"] if head.startswith("### ") else ""


def _hook_env(event, item_id, title, body_file, worktree, branch, merge_sha):
    """The hook's CLAUDE_TODO_* variables. Item text reaches the hook only here and in the body
    file — never in the command string, which is committed config alone."""
    return {
        "CLAUDE_TODO_EVENT": event,
        "CLAUDE_TODO_ITEM_ID": item_id,
        "CLAUDE_TODO_ITEM_TITLE": title,
        "CLAUDE_TODO_ITEM_BODY_FILE": body_file,
        "CLAUDE_TODO_MAIN_TREE": main_tree(),
        "CLAUDE_TODO_WORKTREE": worktree or "",
        "CLAUDE_TODO_BRANCH": branch or "",
        "CLAUDE_TODO_MERGE_SHA": (merge_sha or "") if event == "land" else "",
    }


def _hook_timeout():
    try:
        return float(os.environ.get("CLAUDE_TODO_HOOK_TIMEOUT") or VERIFY_DEFAULT_TIMEOUT)
    except ValueError:
        return VERIFY_DEFAULT_TIMEOUT


def _run_hook(event, item_id, section, worktree, branch, merge_sha, trigger=None, title=None):
    """Run `hooks.<event>` once for `item_id` and print one line. Same execution model as
    `_worktree_setup`: `/bin/sh` through `_verify_run`, stdin closed, a log under the git common
    dir — but from the main checkout, since at `claim` no worktree exists yet. The body snapshot
    and the ledger entry are written first, so `hooks run` can retry after the item and its claim
    are gone. Returns the hook's rc (None on a timeout or an OSError)."""
    run = _hook_cmd(event)
    if run is None:
        return None
    if worktree is None or branch is None:
        with State() as st:
            claim = st.claims.get(item_id) or {}
        worktree = claim.get("worktree") if worktree is None else worktree
        branch = claim.get("branch") if branch is None else branch
    if title is None:
        title = _hook_title(item_id, section)
    os.makedirs(_hooks_dir(), exist_ok=True)
    body_file = _hook_body_path(item_id, event)
    if section or not os.path.exists(body_file):
        _atomic_write(body_file, "\n".join(section).rstrip("\n") + "\n" if section else "")
    env = _hook_env(event, item_id, title, body_file, worktree, branch, merge_sha)
    log_dir = os.path.join(_common_dir(), VERIFY_LOG_DIR)
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, re.sub(r"[^A-Za-z0-9._-]+", "_", f"{item_id}--{event}") + ".log")
    timeout = _hook_timeout()
    after = f"; {trigger} itself succeeded" if trigger else ""
    try:
        rc, secs, timed_out = _verify_run(run, main_tree(), log_path, timeout,
                                          env={**os.environ, **env})
    except OSError as e:
        rc, secs, timed_out = None, 0.0, False
        print(f"hook {event} FAILED ({e.__class__.__name__}: {e}){after}")
    else:
        if rc == 0:
            print(f"hook {event} ok ({secs:.1f}s) — log: {log_path}")
        else:
            why = f"timed out after {timeout:g}s" if timed_out else f"exit {rc}"
            print(f"hook {event} FAILED ({secs:.1f}s, {why}) — log: {log_path}{after}")
    ledger = _hook_ledger(item_id)
    ledger[event] = {"rc": rc, "at": _now(), "title": title, "worktree": worktree or "",
                     "branch": branch or "", "merge_sha": env["CLAUDE_TODO_MERGE_SHA"]}
    _atomic_write(_hook_ledger_path(item_id), json.dumps(ledger, indent=2) + "\n")
    return rc


def _hooks_notes():
    """`doctor`'s WARN lines for a malformed `hooks` config; none when the key is absent."""
    return [f"{p} in .claude/todo-config.json (see `help config`)"
            for p in _hooks_problems(_config().get("hooks"))]


def cmd_hooks(argv):
    """`hooks show` lists the configured lifecycle hooks; `hooks run <event> --id <ID>` fires one by
    hand — the retry for a failed hook, or a dry run that prints what it would get."""
    if not argv or argv[0] == "show":
        hooks = _config().get("hooks")
        shown = [(e, r) for e, r in hooks.items()] if isinstance(hooks, dict) else []
        if not shown and not _hooks_problems(hooks):
            print("no hooks configured — add \"hooks\": {\"claim\": \"<shell line>\", …} to "
                  ".claude/todo-config.json (see `help config`)")
            return 0
        for event, run in shown:
            print(f"{event}\t{run}")
        for p in _hooks_problems(hooks):
            print(f"WARN: {p}")
        return 0
    if argv[0] != "run":
        print("ERROR — usage: todo-lock.py hooks show | hooks run <event> --id <ID> [--dry-run] "
              "[--force]")
        return 2
    ap = _ArgParser(prog="todo-lock.py hooks run", add_help=False)
    ap.add_argument("event", choices=HOOK_EVENTS)
    ap.add_argument("--id", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    opts = ap.parse_args(argv[1:])
    run = _hook_cmd(opts.event)
    if run is None:
        print(f"ERROR — hooks.{opts.event} is not configured (see `hooks show`)")
        return 1
    item_id, event = opts.id, opts.event
    prior = _hook_ledger(item_id).get(event)
    with State() as st:
        claim = dict(st.claims.get(item_id) or {})
    live = find_item(parse_items(read_lines()), item_id) if os.path.exists(main_todo_path()) else None
    if prior is None and live is None and not claim:
        print(f"ERROR — {item_id} is not in the backlog, not claimed, and has no recorded "
              f"`{event}` hook to retry")
        return 1
    if prior and prior.get("rc") == 0 and not opts.force and not opts.dry_run:
        print(f"hook {event} for {item_id} already ran ok at {prior.get('at')}; --force re-fires")
        return 1
    prior = prior or {}
    section = live["body"] if live else []
    title = _hook_title(item_id, section) if live else prior.get("title", "")
    worktree = claim.get("worktree") if claim else prior.get("worktree", "")
    branch = claim.get("branch") if claim else prior.get("branch", "")
    merge_sha = prior.get("merge_sha", "")
    if opts.dry_run:
        print(f"would run: {run}")
        print(f"cwd: {main_tree()}")
        env = _hook_env(event, item_id, title, _hook_body_path(item_id, event), worktree, branch,
                        merge_sha)
        for k, v in env.items():
            print(f"{k}={v}")
        return 0
    rc = _run_hook(event, item_id, section, worktree or "", branch or "", merge_sha, title=title)
    return 0 if rc == 0 else 1
# @fragment 50_sequences.py
# ---------------------------------------------------------------------------
# Numbered-sequence registry — collision-free numbers for ADR/RFC/migration-style
# artifacts, opt-in via `sequences` in .claude/todo-config.json. One file per
# entry, so two worktrees writing different numbers produce different filenames
# and the merge at /finish is conflict-free by construction. The handout mirrors
# reserve-version: next = max(files on disk, files on any local branch, active
# reservations) + 1, computed under the State() flock. The branch scan is what
# makes pruning a reservation safe: once its file is committed anywhere, the
# floor covers it, so a dropped reservation can only free an uncommitted number.
# ---------------------------------------------------------------------------


def _sequences():
    """The optional `sequences` config map: {name: {dir, pattern, template?, status_field?}}."""
    seqs = _config().get("sequences")
    return seqs if isinstance(seqs, dict) else {}


def _seq_cfg(name):
    """The named sequence's config dict, or a printed error + None (caller returns 2)."""
    cfg = _sequences().get(name)
    if not isinstance(cfg, dict):
        print(f"ERROR — no sequence {name!r} configured in `.claude/todo-config.json` "
              f"(configured: {', '.join(sorted(_sequences())) or '(none)'})")
        return None
    if not cfg.get("dir") or not cfg.get("pattern"):
        print(f"ERROR — sequence {name!r} in `.claude/todo-config.json` needs both "
              "`dir` and `pattern`")
        return None
    return cfg


def _seq_pattern_re(cfg):
    """The filename pattern compiled to a regex capturing the entry number as group `n` —
    `{n}`/`{n:04d}` matches any digit run (zero-padded or not), `{slug}` matches anything."""
    pat = re.escape(cfg["pattern"])
    pat = re.sub(r"\\\{n(?::.*?)?\\\}", r"(?P<n>\\d+)", pat, count=1)
    pat = re.sub(r"\\\{slug\\\}", r".*", pat)
    return re.compile(r"^" + pat + r"$")


def _seq_filename(cfg, n, slug):
    try:
        return cfg["pattern"].format(n=n, slug=slug)
    except (KeyError, IndexError, ValueError) as exc:
        print(f"ERROR — bad `pattern` {cfg['pattern']!r} in `.claude/todo-config.json` "
              f"(want {{n[:spec]}} and {{slug}} placeholders): {exc}")
        return None


def _seq_render_n(cfg, n):
    """`n` formatted the way the filename pattern renders it — `{n:04d}` gives `0089`, a bare
    `{n}` gives `89`. What a caller has to reproduce by hand otherwise, which is how a `reserve`
    that printed only the raw number led to hand-rendered padding at the call site."""
    m = re.search(r"\{n(?::([^}]*))?\}", cfg.get("pattern") or "")
    if not m:
        return str(n)
    try:
        return format(n, m.group(1) or "")
    except (ValueError, TypeError):
        return str(n)


def _slug(title):
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s or "untitled"


def _seq_worktree():
    """Realpath of the current checkout's top level (the tree entry files are written into)."""
    return os.path.realpath(_git("rev-parse", "--show-toplevel"))


def _seq_scan_names(names, cfg):
    """{n: [filename, …]} for every pattern-matching name, filenames sorted."""
    rx = _seq_pattern_re(cfg)
    out = {}
    for fn in sorted(names):
        m = rx.match(fn)
        if m:
            out.setdefault(int(m.group("n")), []).append(fn)
    return out


def _seq_duplicates(names, cfg):
    """{n: [filename, …]} for every number more than one name holds — what doctor and land report,
    since every other reader keeps just one file per number."""
    return {n: fns for n, fns in _seq_scan_names(names, cfg).items() if len(fns) > 1}


def _seq_listdir(root, cfg):
    try:
        return os.listdir(os.path.join(root, cfg["dir"]))
    except OSError:
        return []  # directory absent (no entries yet) — floor 0, list empty


def _seq_scan_dir(root, cfg):
    """{n: absolute path} for every pattern-matching entry under root/cfg[dir]. Two files on one
    number keep the last in sort order; `_seq_duplicates` is what notices them."""
    d = os.path.join(root, cfg["dir"])
    return {n: os.path.join(d, fns[-1])
            for n, fns in _seq_scan_names(_seq_listdir(root, cfg), cfg).items()}


def _seq_tree_names(rev, cfg, cwd=None):
    """Basenames directly under cfg[dir] in commit `rev` ([] when the dir isn't there)."""
    d = cfg["dir"].strip("/")
    r = subprocess.run(["git", "-C", cwd or main_tree(), "ls-tree", "--name-only", "--full-tree",
                        rev, "--", d + "/"], capture_output=True, text=True)
    if r.returncode != 0:
        return []
    return [os.path.basename(p) for p in r.stdout.splitlines() if p]


def _seq_branch_entries(cfg):
    """{n: [branch, …]} for every entry committed on some local branch. What floors the handout
    past a number whose worktree or claim is gone but whose branch still holds the file. Local
    refs only — numbers are per machine. One ls-tree per distinct branch tip."""
    r = subprocess.run(["git", "-C", main_tree(), "for-each-ref",
                        "--format=%(objectname) %(refname:short)", "refs/heads"],
                       capture_output=True, text=True)
    tips = {}
    for ln in r.stdout.splitlines() if r.returncode == 0 else []:
        sha, _, ref = ln.partition(" ")
        tips.setdefault(sha, []).append(ref)
    out = {}
    for sha, refs in tips.items():
        for n in _seq_scan_names(_seq_tree_names(sha, cfg), cfg):
            out.setdefault(n, []).extend(refs)
    return out


def _seq_entries(cfg):
    """Entries on disk, unioned over the main tree and the current worktree (worktree wins on
    the same number — it may hold an unlanded edit of a landed entry). {n: absolute path}"""
    entries = dict(_seq_scan_dir(main_tree(), cfg))
    wt = _seq_worktree()
    if wt != os.path.realpath(main_tree()):
        entries.update(_seq_scan_dir(wt, cfg))
    return entries


def _seq_outstanding(st, name, cfg):
    """Every number currently reserved but not necessarily on disk yet: numbers riding active
    claims plus worktree-keyed ones. Prunes worktree-keyed reservations whose worktree is gone
    or whose number has reached the main tree — recomputing from ground truth here is what lets
    an abandoned number be reissued instead of leaving a permanent hole (mirrors _reset_hwm).
    Pruning a gone worktree is safe only because `_seq_reserve` also floors on every local
    branch: a number committed anywhere stays covered after its reservation goes (BUG-8)."""
    nums = []
    for c in st.claims.values():
        nums.extend((c.get("seq") or {}).get(name) or [])
    on_main = _seq_scan_dir(main_tree(), cfg)
    wts = (st.seq.get(name) or {}).get("worktrees") or {}
    for path in list(wts):
        kept = [n for n in wts[path] if n not in on_main] if os.path.isdir(path) else []
        if kept:
            wts[path] = kept
            nums.extend(kept)
        else:
            del wts[path]
    if wts:
        st.seq[name] = {"worktrees": wts}
    else:
        st.seq.pop(name, None)
    return nums


def _seq_reserve(st, name, cfg, claim_id=None):
    """Hand out the next number and record the reservation — on the enclosing claim when the
    caller is inside a claimed item's worktree, or on `claim_id` when named explicitly (so
    release/land free it with the claim), else keyed to this worktree. `claim_id` is what lets a
    reservation be taken at PLAN time, from the main checkout, before the item has a worktree to
    be inside of. Caller holds the State() flock and saves."""
    outstanding = _seq_outstanding(st, name, cfg)
    floor = max([*_seq_entries(cfg), *_seq_branch_entries(cfg)], default=0)
    n = max([floor, *outstanding]) + 1
    _seq_record(st, name, n, claim_id)
    return n


def _seq_record(st, name, n, claim_id=None):
    """Record `n` as reserved — on `claim_id`, else on the claim whose worktree this is, else keyed
    to this worktree. A no-op when that holder already has it. Caller holds the flock and saves."""
    wt = _seq_worktree()
    if claim_id is not None:
        claim = st.claims.get(claim_id)
    else:
        claim = next((c for c in st.claims.values()
                      if c.get("worktree") and os.path.realpath(c["worktree"]) == wt), None)
    if claim is not None:
        held = claim.setdefault("seq", {}).setdefault(name, [])
    else:
        held = st.seq.setdefault(name, {}).setdefault("worktrees", {}).setdefault(wt, [])
    if n not in held:
        held.append(n)


def _seq_number_unavailable(st, name, cfg, n):
    """Why `seq new --number <n>` can't use `n` — an error string, or None when it's free to use.
    Free means: no entry file holds it, and no OTHER claim or worktree reserved it. A number this
    claim reserved itself is the expected case (`seq reserve` at plan time, `seq new --number` in
    the worktree), so it passes. Read raw — this must not prune reservations the way
    `_seq_outstanding` does, since it isn't handing out a number."""
    existing = _seq_entries(cfg).get(n)
    if existing is not None:
        return (f"ERROR — {name}-{n} already exists at {existing}; not overwriting "
                f"(drop --number to reserve a fresh one)")
    branches = _seq_branch_entries(cfg).get(n)
    if branches:
        return (f"ERROR — {name}-{n} is already committed on branch {', '.join(branches)}; using "
                f"it would collide when that lands (drop --number to reserve a fresh one)")
    wt = _seq_worktree()
    for cid, c in st.claims.items():
        if n in ((c.get("seq") or {}).get(name) or []) and not (
                c.get("worktree") and os.path.realpath(c["worktree"]) == wt):
            return (f"ERROR — {name}-{n} is reserved by claim {cid}; using it would collide "
                    f"(drop --number to reserve a fresh one)")
    for path, nums in ((st.seq.get(name) or {}).get("worktrees") or {}).items():
        if n in nums and os.path.realpath(path) != wt:
            return (f"ERROR — {name}-{n} is reserved by the worktree {path}; using it would "
                    f"collide (drop --number to reserve a fresh one)")
    return None


def _seq_wellformed():
    return [(name, cfg) for name, cfg in sorted(_sequences().items())
            if isinstance(cfg, dict) and cfg.get("dir") and cfg.get("pattern")]


def _seq_duplicate_notes():
    """One line per number two entry files share in the main tree — for `doctor`."""
    notes = []
    for name, cfg in _seq_wellformed():
        for n, fns in sorted(_seq_duplicates(_seq_listdir(main_tree(), cfg), cfg).items()):
            notes.append(f"{name}-{n} is held by {len(fns)} files in {cfg['dir']}: "
                         f"{', '.join(fns)} — renumber all but one by hand")
    return notes


def _seq_land_duplicates(maintree, base, branch):
    """What merging `branch` into `base` would newly leave on one number: a `land` refusal message,
    or None. Duplicates `base` already holds don't count — they'd block every land forever."""
    found = []
    for name, cfg in _seq_wellformed():
        before = _seq_duplicates(_seq_tree_names(base, cfg, maintree), cfg)
        after = _seq_duplicates(_seq_tree_names(branch, cfg, maintree), cfg)
        for n, fns in sorted(after.items()):
            if before.get(n) != fns:
                found.append(f"  {name}-{n}: {', '.join(os.path.join(cfg['dir'], f) for f in fns)}")
    if not found:
        return None
    return "\n".join([
        f"DUPLICATE — merging {branch} into {base} would leave two entries on one number, so "
        "nothing was merged:", *found,
        "Renumber this branch's entry in its worktree (`todo-lock.py seq reserve <name>` hands out "
        "a free number; rename the file and fix references to it), commit, then retry `land`."])


# Entry metadata. Every field is optional and read the same way: a leading `---` front-matter
# block first, then the body's first `<Field>: value` / `**<Field>:** value` line or `## <Field>`
# heading. The names the entries actually use map through the sequence's `fields` config, so a
# series with its own convention (`covers:` for scope) is read as-is, never rewritten. Reading
# never writes; the only writer is `_seq_set_status`, and it touches the status value alone.
SEQ_META_FIELDS = ("status", "summary", "scope", "tags", "amends", "supersedes")
SEQ_LIST_FIELDS = ("scope", "tags", "supersedes")
SEQ_INACTIVE = ("superseded", "deprecated")      # what `seq list --active` hides
SEQ_NOT_IN_FORCE = ("rejected", "withdrawn")     # a declarer in these states supersedes nothing


def _seq_field_names(cfg):
    """{canonical field: the name the entries write it under} — `fields` config, `status_field`
    winning for status, else the canonical name itself (matched case-insensitively)."""
    fields = cfg.get("fields") if isinstance(cfg.get("fields"), dict) else {}
    out = {f: str(fields.get(f) or f) for f in SEQ_META_FIELDS}
    if cfg.get("status_field"):
        out["status"] = str(cfg["status_field"])
    return out


def _seq_front_matter(lines):
    """({key lowercased: (line index, value)}, body start) for a leading `---` … `---` block, value
    a string or — for `[a, b]` or `- item` lines under an empty key — a list. ({}, 0) when there
    is no block (or it never closes). A minimal reader, not YAML: stdlib only."""
    if not lines or lines[0].strip() != "---":
        return {}, 0
    out, key = {}, None
    for i, ln in enumerate(lines[1:], 1):
        if ln.strip() in ("---", "..."):
            return out, i + 1
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*?)\s*$", ln)
        if m:
            key, val = m.group(1).lower(), m.group(2)
            if val.startswith("[") and val.endswith("]"):
                val = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
            elif not val:
                val = []
            else:
                val = val.strip("'\"")
            out[key] = (i, val)
            continue
        m = re.match(r"^\s*-\s+(.*?)\s*$", ln)
        if m and key is not None and isinstance(out[key][1], list):
            out[key][1].append(m.group(1).strip("'\""))
    return {}, 0


def _seq_body_field(lines, field, start=0):
    """(line index, prefix) of `field`'s value in the body — the first `<field>: value` /
    `**<field>:** value` line, or the first non-empty line under a `#… <field>` heading — or None.
    A match with an empty value (an unfilled template line) is skipped, as is a heading whose
    section is empty. The value is `lines[i][len(prefix):]`."""
    esc = re.escape(field)
    field_rx = re.compile(r"^(\s*\**%s\**\s*:\s*\**\s*)(\S.*)$" % esc, re.I)
    head_rx = re.compile(r"^\s*#+\s*%s\s*$" % esc, re.I)
    for i in range(start, len(lines)):
        m = field_rx.match(lines[i])
        if m and m.group(2).strip():
            return i, m.group(1)
        if head_rx.match(lines[i]):
            j = next((j for j in range(i + 1, len(lines)) if lines[j].strip()), None)
            if j is not None and not lines[j].lstrip().startswith("#"):
                return j, lines[j][:len(lines[j]) - len(lines[j].lstrip())]
    return None


def _seq_entry_meta(path, cfg):
    """An entry's metadata: {title, status, summary, amends: str; scope, tags, supersedes: [str];
    text}. Tolerant — a missing title is the filename stem, a missing status '-', the rest empty."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        text = ""
    lines = text.splitlines()
    fm, start = _seq_front_matter(lines)
    title = next((ln[2:].strip() for ln in lines[start:] if ln.startswith("# ")), None)
    meta = {"title": title or os.path.splitext(os.path.basename(path))[0], "text": text}
    for canon, field in _seq_field_names(cfg).items():
        val = fm.get(field.lower(), (None, None))[1]
        if not val:
            hit = _seq_body_field(lines, field, start)
            val = lines[hit[0]][len(hit[1]):].strip() if hit else None
        if canon in SEQ_LIST_FIELDS:
            items = val if isinstance(val, list) else [val] if val else []
            meta[canon] = [p.strip() for it in items for p in str(it).split(",") if p.strip()]
        else:
            meta[canon] = (", ".join(val) if isinstance(val, list) else val) or ""
    meta["status"] = meta["status"] or "-"
    return meta


def _seq_ref_number(name, ref):
    """The entry number a reference names — `adr-0012`, `ADR 12`, `0012`, `0012-slug.md`,
    `docs/adr/0012-slug.md`, `adr-0017#decision-5` — or None, including for another sequence's
    prefix (`rfc-3` read in `adr`)."""
    ref = posixpath.basename(ref.split("#", 1)[0].strip())
    m = re.match(r"^(?:([A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z][A-Za-z0-9]*)*)[-_ ]*)?(\d+)", ref)
    if not m or (m.group(1) and m.group(1).lower() != name.lower()):
        return None
    return int(m.group(2))


def _seq_status_is(status, prefixes):
    return status.strip().lower().startswith(prefixes)


def _seq_meta_all(name, cfg, entries):
    """{n: meta} for `entries` ({n: path}), each meta also carrying `superseded_by` ([ref]): the
    entries whose `supersedes` names it (unless the declarer was rejected or withdrawn), else what
    a `Superseded by <ref>` status says."""
    metas = {n: _seq_entry_meta(p, cfg) for n, p in entries.items()}
    for meta in metas.values():
        meta["superseded_by"] = []
    for n, meta in sorted(metas.items()):
        if _seq_status_is(meta["status"], SEQ_NOT_IN_FORCE):
            continue
        for ref in meta["supersedes"]:
            t = _seq_ref_number(name, ref)
            if t in metas and t != n:
                metas[t]["superseded_by"].append(f"{name}-{n}")
    for meta in metas.values():
        m = re.match(r"^superseded\s+by\s+(.+)$", meta["status"].strip(), re.I)
        if not meta["superseded_by"] and m:
            meta["superseded_by"] = [m.group(1).strip()]
    return metas


def _seq_set_status(path, cfg, value):
    """Rewrite just the status VALUE of the entry at `path` to `value`, in whatever form it is
    written (front-matter key, field line keeping its `**…:**` prefix, or the line under the
    heading) — the one write any `seq` path makes to an existing entry. Returns 'changed',
    'unchanged', or 'missing' (no status to rewrite; nothing written)."""
    field = _seq_field_names(cfg)["status"]
    lines = read_lines(path)
    fm, start = _seq_front_matter(lines)
    fm_hit = fm.get(field.lower())
    body_hit = None if fm_hit and fm_hit[1] else _seq_body_field(lines, field, start)
    if body_hit is not None:
        i, prefix = body_hit
    elif fm_hit is not None:
        i = fm_hit[0]
        prefix = re.match(r"^\s*[\w-]+\s*:\s*", lines[i]).group(0)
    else:
        return "missing"
    cr = "\r" if lines[i].endswith("\r") else ""
    new = f"{prefix}{value}{cr}"
    if lines[i] == new:
        return "unchanged"
    lines[i] = new
    write_lines(lines, path)
    return "changed"


def _seq_apply_supersedes(root):
    """`land`'s mechanical half of `seq supersede`: every entry under `root` that declares
    `supersedes` flips each target it names whose status doesn't already read superseded. A full,
    idempotent scan like the index regeneration (so it also heals a flip that was missed). Returns
    the repo-relative paths it changed; a target with no status line warns, never raises."""
    changed = []
    for name, cfg in _seq_wellformed():
        entries = _seq_scan_dir(root, cfg)
        for n, meta in sorted(_seq_meta_all(name, cfg, entries).items()):
            if _seq_status_is(meta["status"], SEQ_NOT_IN_FORCE):
                continue
            for ref in meta["supersedes"]:
                t = _seq_ref_number(name, ref)
                if t is None or t == n or t not in entries:
                    continue
                if _seq_status_is(_seq_entry_meta(entries[t], cfg)["status"], ("superseded",)):
                    continue
                result = _seq_set_status(entries[t], cfg, f"Superseded by {name}-{n}")
                rel = os.path.relpath(entries[t], root)
                if result == "changed":
                    changed.append(rel)
                    print(f"NOTE — marked {name}-{t} superseded by {name}-{n} ({rel})")
                elif result == "missing":
                    print(f"WARN — {name}-{n} supersedes {name}-{t}, but {rel} has no status "
                          "line to flip; left as is")
    return changed


# The optional index file. (Not a `# ---` banner: that convention marks a top-level section, and
# tools/docmap.py parses it.)
#
# One file per entry makes the ENTRIES conflict-free, but a series in practice also has a
# hand-maintained index (`docs/adr/README.md`) — a table every entry appends one row to, at the
# same end. Two worktrees appending there conflict every time. So `land` owns the index the same
# way it already owns the version + CHANGELOG: written serially on main, under the git mutex,
# amended into the merge commit. The block is REGENERATED from the entries on disk rather than
# appended to, which makes it idempotent, self-healing, and always in number order regardless of
# which order entries landed. Entirely opt-in: no `index` key, nothing happens.

DEFAULT_INDEX_ROW = "| [{npad}]({path}) | {title} | {status} |"
DEFAULT_INDEX_HEADER = ["| # | Title | Status |", "|---|---|---|"]


def _seq_index_cfg(cfg):
    """The sequence's `index` config ({file, row?}), or None when it has none."""
    idx = cfg.get("index")
    if not isinstance(idx, dict) or not idx.get("file"):
        return None
    return idx


def _seq_indexed():
    """[(name, cfg)] for every well-formed sequence that configures an index — what `land`
    regenerates. Malformed entries are skipped rather than raised on: land runs this after the
    merge is on main, where a bad config key must not become a failed bookkeeping amend."""
    return [(name, cfg) for name, cfg in _seq_wellformed() if _seq_index_cfg(cfg)]


def _seq_index_markers(name):
    """The comment pair delimiting the generated rows. HTML comments so they're invisible in
    rendered markdown, and named per sequence so two series can share one index file."""
    return (f"<!-- BEGIN todo-lock: {name} index -->",
            f"<!-- END todo-lock: {name} index -->")


def _seq_index_rows(root, name, cfg):
    """One rendered row per entry on disk under `root`, ascending by number."""
    idx = _seq_index_cfg(cfg)
    row_tpl = idx.get("row") or DEFAULT_INDEX_ROW
    index_dir = os.path.dirname(os.path.join(root, idx["file"])) or root
    esc = (lambda s: s.replace("|", "\\|")) if "|" in row_tpl else (lambda s: s)
    entries = _seq_scan_dir(root, cfg)
    rows = []
    for n, meta in sorted(_seq_meta_all(name, cfg, entries).items()):
        path = entries[n]
        values = {"npad": _seq_render_n(cfg, n), "n": str(n),
                  "path": os.path.relpath(path, index_dir), "file": os.path.basename(path),
                  "title": esc(meta["title"]), "status": esc(meta["status"]),
                  "summary": esc(meta["summary"]), "scope": esc(", ".join(meta["scope"])),
                  "amends": esc(meta["amends"]),
                  "superseded_by": esc(", ".join(meta["superseded_by"]))}
        # One pass over the template's own tokens, not str.format or chained replaces — a stray
        # brace in the template must not crash the land that renders it, and a value read off an
        # entry (a title containing `{status}`) is never itself substituted.
        rows.append(re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), m.group(0)), row_tpl))
    return rows


def _seq_write_index(root, name, cfg):
    """Regenerate the marked row block in the sequence's index file under `root`. Returns the
    index path (relative to `root`, for staging) when the file changed, else None.

    A missing file or a missing marker block is NOT an exception — it warns and returns None.
    `land` calls this after the merge is already on main, so an unconfigured or hand-mangled index
    must degrade to "index not updated", never to a half-landed main."""
    idx = _seq_index_cfg(cfg)
    if idx is None:
        return None
    rel = idx["file"]
    begin, end = _seq_index_markers(name)
    try:
        lines = read_lines(os.path.join(root, rel))
    except OSError:
        print(f"WARN — the {name} index {rel} is missing; index not updated "
              f"(`todo-lock.py seq index {name}` creates it)")
        return None
    a = next((i for i, ln in enumerate(lines) if ln.strip() == begin), None)
    b = next((i for i, ln in enumerate(lines) if ln.strip() == end), None)
    if a is None or b is None or b < a:
        print(f"WARN — the {name} index {rel} has no `{begin}` … `{end}` block; index not "
              f"updated (`todo-lock.py seq index {name}` adds one)")
        return None
    rows = _seq_index_rows(root, name, cfg)
    if lines[a + 1:b] == rows:
        return None
    write_lines(lines[:a + 1] + rows + lines[b:], os.path.join(root, rel))
    return rel


def _seq_index_bootstrap(root, name, cfg):
    """Give the index file a marker block for `_seq_write_index` to fill: create the file (title +
    table header + empty block) when absent, or append a block when the file exists without one.
    Never reorders or rewrites what's already there — an index that predates this key keeps its
    prose, and its old hand-written rows are the user's to delete. Returns a note, or None if the
    block was already present."""
    idx = _seq_index_cfg(cfg)
    rel = idx["file"]
    path = os.path.join(root, rel)
    begin, end = _seq_index_markers(name)
    custom_row = bool(idx.get("row"))
    try:
        lines = read_lines(path)
    except OSError:
        header = [] if custom_row else DEFAULT_INDEX_HEADER
        os.makedirs(os.path.dirname(path) or root, exist_ok=True)
        write_lines([f"# {name} index", ""] + header + [begin, end, ""], path)
        return f"created {rel}"
    if any(ln.strip() == begin for ln in lines):
        return None
    while lines and not lines[-1].strip():
        lines.pop()
    tail = [begin, end, ""] if custom_row else ["", *DEFAULT_INDEX_HEADER, begin, end, ""]
    write_lines(lines + tail, path)
    return (f"added the row block to {rel} — delete any hand-written rows above it that it "
            "now duplicates")


def _seq_default_template(cfg):
    """The built-in entry template: empty metadata front-matter (under the names `fields` maps
    to), then the Nygard sections. Unfilled keys read as absent."""
    names = _seq_field_names(cfg)
    front = "".join(f"{names[f]}:\n" for f in SEQ_META_FIELDS if f != "status")
    return (f"---\n{front}---\n\n# {{title}}\n\n## {names['status']}\n\nProposed\n\n"
            "## Context\n\n{body}\n\n## Decision\n\n## Consequences\n")


def _seq_cmd_new(argv):
    ap = _ArgParser(prog="todo-lock.py seq new", add_help=False)
    ap.add_argument("name")
    ap.add_argument("--title", required=True)
    ap.add_argument("--number", type=int, default=None)
    _body_file_flag(ap)
    opts = ap.parse_args(argv)
    cfg = _seq_cfg(opts.name)
    if cfg is None:
        return 2
    if opts.body_file is None and sys.stdin.isatty():
        body = ""   # a body is optional here: no flag and nothing piped means an empty one
    else:
        body, _, read_err = _read_payload(opts.body_file)
        if read_err:
            print(f"ERROR — {read_err}. Nothing was written.")
            return 2
        body = body.strip()
    if cfg.get("template"):
        # Resolved in the current worktree (the tree being written to), falling back to the
        # main tree for a worktree cut before the template was committed.
        for root in (_seq_worktree(), main_tree()):
            tpath = os.path.join(root, cfg["template"])
            if os.path.isfile(tpath):
                with open(tpath, encoding="utf-8") as f:
                    template = f.read()
                break
        else:
            print(f"ERROR — sequence {opts.name!r}'s template {cfg['template']!r} not found")
            return 2
    else:
        template = _seq_default_template(cfg)
    with State() as st:
        if opts.number is None:
            n = _seq_reserve(st, opts.name, cfg)
            st.save()
        else:
            err = _seq_number_unavailable(st, opts.name, cfg, opts.number)
            if err:
                print(err)
                return 1
            n = opts.number
            # Record it, under the same flock as the check: an unrecorded N is what let another
            # worktree be handed it too (BUG-8).
            _seq_record(st, opts.name, n)
            st.save()
    fn = _seq_filename(cfg, n, _slug(opts.title))
    if fn is None:
        return 2
    # Literal token replacement, not str.format — stray braces in a template must not crash.
    text = (template.replace("{n}", str(n)).replace("{title}", opts.title)
            .replace("{body}", body))
    if body and "{body}" not in template:
        text = text.rstrip("\n") + "\n\n" + body + "\n"
    wt = _seq_worktree()
    dest = os.path.join(wt, cfg["dir"], fn)
    if os.path.exists(dest):
        print(f"ERROR — {dest} already exists; not overwriting (the reserved number "
              f"{n} stays reserved)")
        return 1
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(text if text.endswith("\n") else text + "\n")
    print(f"{opts.name}-{n}  {os.path.relpath(dest, wt)}")
    return 0


def _seq_cmd_reserve(argv):
    ap = _ArgParser(prog="todo-lock.py seq reserve", add_help=False)
    ap.add_argument("name")
    ap.add_argument("--claim", default=None)
    opts = ap.parse_args(argv)
    cfg = _seq_cfg(opts.name)
    if cfg is None:
        return 2
    with State() as st:
        if opts.claim is not None and opts.claim not in st.claims:
            print(f"ERROR — {opts.claim} is not claimed; reserve --claim must name a live claim "
                  "(see `todo-lock.py list`)")
            return 1
        n = _seq_reserve(st, opts.name, cfg, claim_id=opts.claim)
        st.save()
    # Second field: the number as the configured `pattern` renders it, so a caller writing its own
    # file doesn't re-implement the padding. The first field is unchanged for existing parsers.
    print(f"{opts.name}-{n}  {_seq_render_n(cfg, n)}")
    return 0


def _seq_cmd_list(argv):
    ap = _ArgParser(prog="todo-lock.py seq list", add_help=False)
    ap.add_argument("name", nargs="?")
    ap.add_argument("--status", default=None)
    ap.add_argument("--active", action="store_true")
    ap.add_argument("--brief", action="store_true")
    ap.add_argument("--scope", default=None)
    ap.add_argument("--tag", default=None)
    ap.add_argument("--grep", default=None)
    opts = ap.parse_args(argv)
    if opts.name is None:
        for name in sorted(_sequences()):
            cfg = _sequences()[name]
            if isinstance(cfg, dict):
                print(f"{name}\t{cfg.get('dir')}\t{cfg.get('pattern')}")
        return 0
    cfg = _seq_cfg(opts.name)
    if cfg is None:
        return 2
    try:
        grep = re.compile(opts.grep, re.I) if opts.grep is not None else None
    except re.error as exc:
        print(f"ERROR — bad --grep pattern {opts.grep!r}: {exc}")
        return 2
    wt = _seq_worktree()
    entries = _seq_entries(cfg)
    for n, meta in sorted(_seq_meta_all(opts.name, cfg, entries).items()):
        status, path = meta["status"], entries[n]
        if opts.status and status.lower() != opts.status.lower():
            continue
        if opts.active and (_seq_status_is(status, SEQ_INACTIVE) or meta["superseded_by"]):
            continue
        if opts.scope is not None and not _seq_scope_matches(meta["scope"], opts.scope):
            continue
        if opts.tag is not None and opts.tag.lower() not in (t.lower() for t in meta["tags"]):
            continue
        if grep is not None and not grep.search(meta["text"]):
            continue
        if opts.brief:
            print(f"{opts.name}-{n}\t{status}\t{meta['summary'] or meta['title']}")
            continue
        root = wt if os.path.realpath(path).startswith(wt + os.sep) else main_tree()
        print(f"{opts.name}-{n}\t{status}\t{os.path.relpath(path, root)}\t{meta['title']}")
    return 0


def _seq_scope_matches(globs, path):
    """Whether any of an entry's `scope` globs covers `path` (repo-relative). A glob matches what
    fnmatch matches (`*` crosses `/`, so `dir/**` is everything beneath `dir`); a glob-free scope
    is a directory prefix; a `dir/**` scope also covers `dir` itself; and a queried directory
    (trailing `/`) covers the scopes that lie beneath it."""
    def norm(p):
        p = p.strip().replace(os.sep, "/")
        return p[2:] if p.startswith("./") else p
    query = norm(path)
    is_dir = query.endswith("/")
    q = query.rstrip("/")
    for g in (norm(g) for g in globs if g.strip()):
        if fnmatch.fnmatchcase(q, g) or q == g.rstrip("*").rstrip("/"):
            return True
        if not _is_glob(g) and q.startswith(g.rstrip("/") + "/"):
            return True
        if is_dir and (_glob_dir(g) if _is_glob(g) else g).startswith(q + "/"):
            return True
    return False


def _seq_cmd_index(argv):
    ap = _ArgParser(prog="todo-lock.py seq index", add_help=False)
    ap.add_argument("name", nargs="?")
    opts = ap.parse_args(argv)
    if opts.name is not None:
        cfg = _seq_cfg(opts.name)
        if cfg is None:
            return 2
        if _seq_index_cfg(cfg) is None:
            print(f"NONE — sequence {opts.name!r} has no `index` configured "
                  "(see `help config`)")
            return 1
        targets = [(opts.name, cfg)]
    else:
        targets = _seq_indexed()
        if not targets:
            print("NONE — no configured sequence has an `index` (see `help config`)")
            return 1
    root = _seq_worktree()
    rc = 0
    for name, cfg in targets:
        note = _seq_index_bootstrap(root, name, cfg)
        rel = _seq_write_index(root, name, cfg)
        rows = len(_seq_index_rows(root, name, cfg))
        target = rel or _seq_index_cfg(cfg)["file"]
        state = "updated" if rel else "already current"
        print(f"{name}\t{target}\t{rows} row(s) {state}" + (f" ({note})" if note else ""))
    return rc


def _seq_cmd_show(argv):
    ap = _ArgParser(prog="todo-lock.py seq show", add_help=False)
    ap.add_argument("name")
    ap.add_argument("n", type=int)
    opts = ap.parse_args(argv)
    cfg = _seq_cfg(opts.name)
    if cfg is None:
        return 2
    path = _seq_entries(cfg).get(opts.n)
    if path is None:
        print(f"NONE — no entry {opts.name}-{opts.n} on disk (main tree or this worktree)")
        return 1
    with open(path, encoding="utf-8") as f:
        sys.stdout.write(f.read())
    return 0


def _seq_cmd_supersede(argv):
    ap = _ArgParser(prog="todo-lock.py seq supersede", add_help=False)
    ap.add_argument("name")
    ap.add_argument("n", type=int)
    ap.add_argument("--by", type=int, required=True)
    opts = ap.parse_args(argv)
    cfg = _seq_cfg(opts.name)
    if cfg is None:
        return 2
    if opts.n == opts.by:
        print(f"ERROR — {opts.name}-{opts.n} cannot supersede itself")
        return 2
    entries = _seq_entries(cfg)
    for k in (opts.n, opts.by):
        if k not in entries:
            print(f"NONE — no entry {opts.name}-{k} on disk (main tree or this worktree)")
            return 1
    # Written in THIS checkout, like `seq new`: a landed entry is edited in the worktree's copy and
    # reaches main with the branch, never behind the branch's back.
    wt = _seq_worktree()
    path = entries[opts.n]
    if not os.path.realpath(path).startswith(wt + os.sep):
        path = os.path.join(wt, os.path.relpath(path, main_tree()))
        if not os.path.isfile(path):
            print(f"ERROR — {opts.name}-{opts.n} is not in this checkout yet (only in the main "
                  f"tree's working copy); commit it there first")
            return 1
    rel = os.path.relpath(path, wt)
    value = f"Superseded by {opts.name}-{opts.by}"
    status = _seq_entry_meta(path, cfg)["status"]
    if status != value and _seq_status_is(status, ("superseded",)):
        print(f"NOTE — {opts.name}-{opts.n} already reads `{status}`; left as is ({rel})")
        return 1
    result = _seq_set_status(path, cfg, value)
    if result == "missing":
        field = _seq_field_names(cfg)["status"]
        print(f"ERROR — {rel} has no `{field}` line or heading to flip; nothing was written")
        return 1
    print(f"{opts.name}-{opts.n}\t{value}\t{rel}" + ("" if result == "changed" else "\t(already)"))
    return 0


# Detection — the /initiate half: what numbered series does this repo ALREADY have? (Not a `# ---`
# banner: that convention marks a top-level section, and tools/docmap.py parses it.)
#
# A numbered entry's filename: leading digit run, an optional `-`/`_` separator, a slug, an
# extension. `.` is deliberately NOT a separator, so `0001.md` reads as number + extension rather
# than number + slug "md".
_SEQ_NUMBERED_RE = re.compile(r"^(?P<n>\d+)(?P<sep>[-_])?(?P<rest>.*?)(?P<ext>\.[A-Za-z0-9]+)?$")


def _seq_repo_files(root):
    """Every tracked or untracked-but-not-ignored file, repo-relative. git (rather than os.walk)
    does the pruning, so `.gitignore` keeps `node_modules/`, `dist/` and `.claude/worktrees/` out
    for free, while a day-one repo whose entries aren't committed yet is still seen."""
    out = _git("-C", root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    return [p for p in out.split("\0") if p]


def _seq_shape_pattern(nums, rests, sep, ext):
    """The `pattern` a group of matching filenames implies. Zero-padding is inferred from the
    group as a whole (all numbers the same width and at least one leading zero), so a series that
    has run past its padding (0001 … 1000) still reads as padded."""
    widths = {len(s) for s in nums}
    width = widths.pop() if len(widths) == 1 else 0
    padded = width > 1 and any(s.startswith("0") for s in nums)
    num_tok = ("{n:0%dd}" % width) if padded else "{n}"
    slug_tok = f"{sep or ''}{{slug}}" if any(rests) else ""
    return f"{num_tok}{slug_tok}{ext or ''}"


def _seq_suggest_name(d, taken):
    """A config key for the sequence found in directory `d` — its basename, de-pluralised
    (`docs/adr` -> adr, `db/migrations` -> migration). Disambiguated by parent on a collision, so
    two directories never propose the same name."""
    base = re.sub(r"[^a-z0-9]+", "-", os.path.basename(d).lower()).strip("-") or "seq"
    if base.endswith("s") and not base.endswith("ss"):
        base = base[:-1]
    name, parent = base, os.path.basename(os.path.dirname(d))
    if name in taken and parent:
        name = f"{re.sub(r'[^a-z0-9]+', '-', parent.lower()).strip('-')}-{base}"
    i = 2
    while name in taken:
        name, i = f"{base}-{i}", i + 1
    return name


def _seq_candidates(root, only_dir=None, skip_dirs=()):
    """[(dir, pattern, count, example)] — directories whose files share a numbered-entry shape.

    Files are grouped by (directory, separator, extension); the shape with the most files wins per
    directory. The filters below are heuristics against false positives, and are dropped for an
    explicit `only_dir` — naming a directory is the user asserting it IS a series.
    """
    groups = {}
    for rel in _seq_repo_files(root):
        d = os.path.dirname(rel) or "."
        if (only_dir is not None and d != only_dir) or os.path.normpath(d) in skip_dirs:
            continue
        m = _SEQ_NUMBERED_RE.match(os.path.basename(rel))
        if not m:
            continue
        groups.setdefault((d, m.group("sep"), m.group("ext")), []).append(m)
    best = {}
    for (d, sep, ext), ms in groups.items():
        nums = [m.group("n") for m in ms]
        rests = [m.group("rest") for m in ms]
        if only_dir is None:
            distinct = len(set(int(s) for s in nums))
            # Two entries minimum, mostly-distinct numbers, and mostly non-numeric slugs. Both
            # ratios reject date-stamped names (`_posts/2024-01-01-hello.md`): the year repeats as
            # the "number", and the rest of the date lands in the slug.
            if (len(ms) < 2 or distinct < 2 or distinct * 2 < len(ms)
                    or sum(1 for r in rests if r[:1].isdigit()) * 2 > len(ms)):
                continue
        example = min(m.group(0) for m in ms)
        cand = (d, _seq_shape_pattern(nums, rests, sep, ext), len(ms), example)
        if d not in best or len(ms) > best[d][2]:
            best[d] = cand
    return sorted(best.values(), key=lambda c: (-c[2], c[0]))


def _seq_cmd_detect(argv):
    ap = _ArgParser(prog="todo-lock.py seq detect", add_help=False)
    ap.add_argument("--path", default=None)
    ap.add_argument("--limit", type=int, default=20)
    opts = ap.parse_args(argv)
    root = _seq_worktree()
    only_dir = None
    if opts.path is not None:
        p = opts.path if os.path.isabs(opts.path) else os.path.join(os.getcwd(), opts.path)
        only_dir = os.path.relpath(os.path.realpath(p), root).replace(os.sep, "/")
        if only_dir.startswith(".."):
            print(f"ERROR — {opts.path} is outside this checkout ({root})")
            return 2
    # An already-registered sequence is a fact, not a guess: report it from the config (its own
    # dir and pattern, however few files it has) rather than re-deriving it from disk. That's what
    # keeps /initiate from re-offering a series, or from proposing to bootstrap one that exists
    # because a young sequence holds too few entries for the heuristics to fire.
    rows, taken, seen = [], set(), set()
    for name, cfg in sorted(_sequences().items()):
        if not (isinstance(cfg, dict) and cfg.get("dir") and cfg.get("pattern")):
            continue
        taken.add(name)
        seen.add(os.path.normpath(cfg["dir"]))
        if only_dir is not None and os.path.normpath(cfg["dir"]) != os.path.normpath(only_dir):
            continue
        entries = _seq_scan_dir(root, cfg)
        example = os.path.basename(entries[min(entries)]) if entries else "-"
        rows.append((name, cfg["dir"], cfg["pattern"], len(entries), example, "registered"))
    for d, pattern, count, example in _seq_candidates(root, only_dir, seen):
        name = _seq_suggest_name(d, taken)
        taken.add(name)
        rows.append((name, d, pattern, count, example, "new"))
    if not rows:
        where = f"in {only_dir}" if only_dir else "in this repo"
        print(f"NONE — no numbered series found {where}")
        return 1
    # Registered first (known), then the candidates best-populated first.
    rows.sort(key=lambda r: (r[5] != "registered", -r[3], r[1]))
    shown = rows[:opts.limit] if opts.limit > 0 else rows
    for row in shown:
        print("\t".join(str(c) for c in row))
    if len(rows) > len(shown):
        print(f"… {len(rows) - len(shown)} more candidate(s) not shown (--limit {opts.limit})")
    return 0


CONFIG_REL = os.path.join(".claude", "todo-config.json")


def _json_indent(text):
    """The indent unit an existing JSON file uses (a tab, or N spaces), default two spaces."""
    m = re.search(r"\n([ \t]+)\S", text)
    if not m:
        return 2
    return "\t" if m.group(1).startswith("\t") else len(m.group(1))


def _config_update(mutate, commit=False, message=""):
    """Apply `mutate(cfg)` to the main tree's config and write it back — every other key, the key
    order and the file's indent survive. `mutate` edits the dict in place and returns ("write",
    None), ("same", what) for a no-op, or ("error", why) to refuse. With `commit`, the write and a
    commit of only that file happen on main under the git mutex. Returns (rc, sha, note): rc is
    None when the file was written, else the exit code, the reason already printed."""
    maintree = main_tree()
    path = os.path.join(maintree, CONFIG_REL)
    note = sha = None
    with GitMutex() if commit else contextlib.nullcontext():
        if commit:
            ok, note = _commit_precheck(maintree, CONFIG_REL)
            if not ok:
                print(note)
                return 2, None, None
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except FileNotFoundError:
            text = ""
        try:
            cfg = json.loads(text) if text.strip() else {}
        except ValueError as e:
            print(f"ERROR — {CONFIG_REL} is not valid JSON ({e}); fix it by hand first. "
                  "Nothing was written.")
            return 2, None, None
        if not isinstance(cfg, dict):
            print(f"ERROR — {CONFIG_REL} must hold a JSON object. Nothing was written.")
            return 2, None, None
        status, what = mutate(cfg)
        if status == "same":
            print(f"OK {what} — {CONFIG_REL} unchanged")
            return 0, None, None
        if status == "error":
            print(f"ERROR — {what}. Nothing was written.")
            return 2, None, None
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _atomic_write(path, json.dumps(cfg, indent=_json_indent(text), ensure_ascii=False) + "\n")
        _CONFIG_CACHE.clear()
        if commit:
            sha, err = _commit_store(maintree, CONFIG_REL, message)
            if err:
                print(f"ERROR — {CONFIG_REL} is written on main, but the commit FAILED: {err}")
                print(f"The main tree is left dirty (which `land` rejects) — commit {CONFIG_REL} "
                      "there by hand, or fix the cause and retry.")
                return 1, None, None
    return None, sha, note


def _seq_cmd_register(argv):
    """Merge one `sequences.<name>` entry into the main tree's config — every other key, the key
    order and the file's indent survive; nothing else is rewritten. Replaces the inline Python
    /initiate used. Idempotent for an identical entry, refused for a conflicting one."""
    ap = _ArgParser(prog="todo-lock.py seq register", add_help=False,
                                 allow_abbrev=False)
    ap.add_argument("name")
    ap.add_argument("--dir", required=True)
    ap.add_argument("--pattern", required=True)
    ap.add_argument("--index-file", default=None)
    ap.add_argument("--row", default=None)
    ap.add_argument("--status-field", default=None)
    ap.add_argument("--template", default=None)
    ap.add_argument("--field", action="append", default=[], metavar="KEY=NAME")
    _add_commit_flags(ap)
    opts = ap.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", opts.name):
        print(f"ERROR — sequence name {opts.name!r} must be letters, digits, `-` or `_`")
        return 2
    if os.path.isabs(opts.dir) or ".." in opts.dir.split("/"):
        print(f"ERROR — --dir {opts.dir!r} must be a path relative to the repo root")
        return 2
    if (len(re.findall(r"\{n(?::[^}]*)?\}", opts.pattern)) != 1 or opts.pattern.count("{slug}") != 1
            or _seq_filename({"pattern": opts.pattern}, 1, "x") is None):
        print(f"ERROR — --pattern {opts.pattern!r} needs exactly one {{n}} (or {{n:04d}}) and one "
              "{slug} placeholder")
        return 2
    if opts.row is not None and opts.index_file is None:
        print("ERROR — --row needs --index-file (the index the row template renders into)")
        return 2
    entry = {"dir": opts.dir.rstrip("/"), "pattern": opts.pattern}
    if opts.status_field:
        entry["status_field"] = opts.status_field
    if opts.template:
        entry["template"] = opts.template
    if opts.field:
        fields = {}
        for f in opts.field:
            key, sep, val = f.partition("=")
            if not sep or key not in SEQ_META_FIELDS or not val.strip():
                print(f"ERROR — --field {f!r} must be KEY=NAME with KEY one of "
                      f"{'|'.join(SEQ_META_FIELDS)}")
                return 2
            fields[key] = val.strip()
        entry["fields"] = fields
    if opts.index_file:
        entry["index"] = {"file": opts.index_file}
        if opts.row is not None:
            entry["index"]["row"] = opts.row

    def register(cfg):
        seqs = cfg.setdefault("sequences", {})
        if not isinstance(seqs, dict):
            return "error", f"`sequences` in {CONFIG_REL} is not an object"
        if opts.name in seqs:
            if seqs[opts.name] == entry:
                return "same", f"{opts.name} already registered"
            return "error", (f"sequence {opts.name!r} is already registered with different "
                             f"settings ({json.dumps(seqs[opts.name], ensure_ascii=False)}); edit "
                             f"{CONFIG_REL} by hand to change it")
        seqs[opts.name] = entry
        return "write", None

    rc, sha, note = _config_update(register, opts.commit,
                                   opts.message or f"Register {opts.name} numbered sequence")
    if rc is not None:
        return rc
    print(f"OK registered sequence {opts.name}: {entry['dir']}/{entry['pattern']}")
    if note:
        print(note)
    if sha:
        print(f"OK committed {sha} on main ({CONFIG_REL})")
    return 0


def cmd_seq(argv):
    subs = {"new": _seq_cmd_new, "reserve": _seq_cmd_reserve, "list": _seq_cmd_list,
            "show": _seq_cmd_show, "index": _seq_cmd_index, "detect": _seq_cmd_detect,
            "supersede": _seq_cmd_supersede, "register": _seq_cmd_register}
    if not argv or argv[0] not in subs:
        print("ERROR — usage: todo-lock.py seq new|reserve|list|show|supersede|index|detect|"
              "register … (see `help sequences`)")
        return 2
    # `detect` and `register` are the steps /initiate runs BEFORE any sequence exists, so they're
    # exempt from the configured-check every other subcommand takes — gating them would make the
    # command that writes the config require the config.
    if argv[0] not in ("detect", "register") and not _sequences():
        print("numbered sequences are not configured — add a `sequences` map to "
              "`.claude/todo-config.json` to enable the `seq` commands (see `help config`)")
        return 2
    return subs[argv[0]](argv[1:])


# @fragment 60_tables.py
# ---------------------------------------------------------------------------
# Generated tables — the sequence-index treatment for any table declared in config
# (`tables`): a README's package or module table that every item appends a row to
# conflicts the same way, so `land` regenerates its marked row block on main, from
# the source files on disk, in the bookkeeping amend. `tables render` previews.
# Only the text between a table's markers is ever rewritten; opt-in, no config
# key means nothing happens.
# ---------------------------------------------------------------------------

TABLE_KEYS = ("name", "file", "source", "row")


def _tables_config():
    """(well-formed tables, problems) from config `tables`. A table needs a string `name`, `file`
    and `row`, and a `source` glob (string or list of strings); a repeated `name` is a problem too,
    since the name is what tells two marker blocks apart."""
    raw = _config().get("tables")
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        return [], ["`tables` must be a list of {name, file, source, row}"]
    good, problems, seen = [], [], set()
    for i, t in enumerate(raw):
        if not isinstance(t, dict):
            problems.append(f"tables[{i}] is not an object")
            continue
        src = t.get("source")
        srcs = [src] if isinstance(src, str) else src
        missing = [k for k in TABLE_KEYS if k != "source" and not (
            isinstance(t.get(k), str) and t[k].strip())]
        if not (isinstance(srcs, list) and srcs and all(isinstance(s, str) and s for s in srcs)):
            missing.append("source")
        if missing:
            problems.append(f"tables[{i}] needs {', '.join(missing)}")
            continue
        if t["name"] in seen:
            problems.append(f"tables[{i}] repeats the name {t['name']!r}")
            continue
        seen.add(t["name"])
        good.append(dict(t, source=srcs))
    return good, problems


def _table_markers(name):
    """The comment pair around a table's generated rows — the seq index shape, `table` suffix."""
    return (f"<!-- BEGIN todo-lock: {name} table -->",
            f"<!-- END todo-lock: {name} table -->")


def _table_sources(root, t):
    """Repo-relative paths of the regular files `source` matches under `root`, sorted, never the
    table's own file."""
    own = os.path.normpath(t["file"])
    found = set()
    for pat in t["source"]:
        for p in glob.glob(os.path.join(root, pat), recursive=True):
            rel = os.path.normpath(os.path.relpath(p, root))
            if os.path.isfile(p) and rel != own:
                found.add(rel)
    return sorted(found)


def _table_rows(root, t):
    """One rendered row per source file. Tokens: {path} (relative to the table file), {file},
    {stem}, {dir} (parent directory name), {heading} (first heading, else the stem), and any other
    {word} is that front-matter field — empty when the file lacks it. Every value has `|` escaped."""
    table_dir = os.path.dirname(os.path.join(root, t["file"])) or root
    rows = []
    for rel in _table_sources(root, t):
        path = os.path.join(root, rel)
        try:
            lines = read_lines(path)
        except (OSError, UnicodeDecodeError):
            lines = []
        fm, start = _seq_front_matter(lines)
        stem = os.path.splitext(os.path.basename(rel))[0]
        heading = next((m.group(2) for m in map(DOC_HEADING_RE.match, lines[start:]) if m), stem)
        values = {k: (", ".join(v) if isinstance(v, list) else v) for k, (_i, v) in fm.items()}
        values.update({"path": os.path.relpath(path, table_dir), "file": os.path.basename(rel),
                       "stem": stem, "dir": os.path.basename(os.path.dirname(rel)),
                       "heading": heading})
        # One pass over the template's own tokens, as `_seq_index_rows` does: a value containing
        # `{x}` is never itself substituted, and a stray brace can't crash the land rendering it.
        rows.append(re.sub(r"\{(\w+)\}",
                           lambda m: str(values.get(m.group(1).lower(), "")).replace("|", "\\|"),
                           t["row"]))
    return rows


def _marked_block(root, rel, begin, end, missing):
    """(lines, begin index, end index) of the `begin`/`end` marker pair in `rel` under `root`, or an
    error string: `missing` when the file is gone, a no-block message when a marker is. Shared by
    `tables` and `codemap`, the two writers that own one marked block of a file."""
    try:
        lines = read_lines(os.path.join(root, rel))
    except OSError:
        return missing
    a = next((i for i, ln in enumerate(lines) if ln.strip() == begin), None)
    b = next((i for i, ln in enumerate(lines) if ln.strip() == end), None)
    if a is None or b is None or b < a:
        return f"{rel} has no `{begin}` … `{end}` block"
    return lines, a, b


def _table_block(root, t):
    """(lines, begin index, end index) of the table file under `root`, or an error string when the
    file or its marker pair is missing."""
    begin, end = _table_markers(t["name"])
    return _marked_block(root, t["file"], begin, end,
                         f"the {t['name']} table's file {t['file']} is missing")


def _table_write(root, t):
    """Regenerate the table's marked rows under `root`. Returns the file (relative, for staging)
    when it changed, else None. A missing file or marker pair warns and writes nothing: `land`
    calls this after the merge is on main, where it must degrade to "table not updated", never to
    a half-landed main."""
    block = _table_block(root, t)
    if isinstance(block, str):
        print(f"WARN — {block}; table not updated")
        return None
    lines, a, b = block
    rows = _table_rows(root, t)
    if lines[a + 1:b] == rows:
        return None
    write_lines(lines[:a + 1] + rows + lines[b:], os.path.join(root, t["file"]))
    return t["file"]


def _tables_land(maintree):
    """`land`'s share: regenerate every well-formed table on main. Returns [(name, file)] changed."""
    tables, problems = _tables_config()
    for p in problems:
        print(f"WARN — {p}; skipped (see `help config`)")
    changed = []
    for t in tables:
        rel = _table_write(maintree, t)
        if rel:
            changed.append((t["name"], rel))
    return changed


def cmd_tables(argv):
    if not argv or argv[0] != "render":
        print("ERROR — usage: todo-lock.py tables render [<name>] (see `help config`)")
        return 2
    ap = _ArgParser(prog="todo-lock.py tables render", add_help=False)
    ap.add_argument("name", nargs="?")
    opts = ap.parse_args(argv[1:])
    tables, problems = _tables_config()
    for p in problems:
        print(f"ERROR — {p} (see `help config`)")
    if problems:
        return 2
    if not tables:
        print("generated tables are not configured — add a `tables` list to "
              "`.claude/todo-config.json` (see `help config`)")
        return 2
    if opts.name is not None:
        tables = [t for t in tables if t["name"] == opts.name]
        if not tables:
            print(f"ERROR — no table named {opts.name!r} in `tables`")
            return 2
    root = _seq_worktree()
    rc = 0
    for t in tables:
        rows = _table_rows(root, t)
        block = _table_block(root, t)
        if isinstance(block, str):
            state, rc = "no marker block", 1
        else:
            lines, a, b = block
            state = "current" if lines[a + 1:b] == rows else "would change"
        print(f"{t['name']}\t{t['file']}\t{len(rows)} row(s), {state}")
        for row in rows:
            print(row)
        if isinstance(block, str):
            print(f"ERROR — {block}; add the marker pair where the rows belong (nothing written)")
    return rc


# @fragment 61_codemap.py
# ---------------------------------------------------------------------------
# Code map — the target-repo version of this package's own `tools/docmap.py`: a
# generated table of each large source file's top-level definitions and their
# line ranges, so an agent opens the range it needs instead of the whole file.
# Declared in config (`codemap`), written between one marker pair in one docs
# file, regenerated by `land` on main like `tables`, and verified by `codemap
# check`. Python goes through `ast`; brace languages through a best-effort scan.
# Output depends only on the files' contents, never on time or machine, so a
# regeneration of an unchanged tree is byte-identical. Opt-in: no key, no effect.
# ---------------------------------------------------------------------------

CODEMAP_BEGIN = "<!-- BEGIN todo-lock: codemap -->"
CODEMAP_END = "<!-- END todo-lock: codemap -->"
CODEMAP_PY_EXTS = frozenset({".py", ".pyi"})
# C-family files also get `#` preprocessor lines skipped, so a brace in a macro never shifts depth.
CODEMAP_C_EXTS = frozenset({".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".cs"})
CODEMAP_BRACE_EXTS = CODEMAP_C_EXTS | {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".java",
                                       ".kt", ".kts", ".scala", ".go", ".rs", ".swift", ".php"}
_CODEMAP_MODS = (r"(?:(?:export|default|pub(?:\([^)]*\))?|public|private|protected|internal|"
                 r"static|abstract|final|sealed|async|unsafe|extern|inline|virtual|override|open|"
                 r"data|partial|readonly|declare|opaque)\s+)*")
CODEMAP_KEYWORD_RE = re.compile(
    r"^\s*" + _CODEMAP_MODS + r"(?P<kind>function\*?|class|interface|enum|struct|union|record|"
    r"trait|impl|fn|fun|func|type|namespace|object|module|mod|extension)(?![\w$])\s*(?P<rest>.*)$")
CODEMAP_ARROW_RE = re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*(?::[^=]*)?=\s*"
    r"(?:async\s+)?(?:function\b|\([^)]*\)\s*(?::[^=]*)?=>|[A-Za-z_$][\w$]*\s*=>)")
# A C-style signature: type/modifier words, then `name(`. At top level it needs at least one
# prefix word, which is what tells `int main(` from a bare call like `describe(`.
CODEMAP_CFN_RE = re.compile(
    r"^\s*(?P<prefix>(?:[\w:<>,\[\]\*&$]+[\s\*&]+)*)(?P<name>~?[A-Za-z_$][\w$]*"
    r"(?:::~?[A-Za-z_]\w*)*)\s*\(")
CODEMAP_NOT_FN = frozenset(
    "if for while switch catch return sizeof new else do try synchronized using lock foreach "
    "elif throw await case typeof delete yield with when match loop defer go select".split())
# Blocks whose direct members are listed too, as `Outer.member` — one level, as for Python classes.
CODEMAP_CONTAINERS = frozenset(
    "class interface struct record trait impl namespace object module mod extension".split())
# A definition line whose `{` hasn't arrived within this many lines was not a block definition.
CODEMAP_PENDING_LINES = 12
CODEMAP_RUST_CHAR_RE = re.compile(r"'(?:\\[^'\n]{1,10}|[^\\'\n])'")
CODEMAP_HEADING_RE = re.compile(r"^### `(.+?)` — ")


def _codemap_config():
    """(config, problem) from config `codemap`: (None, None) when unset. Needs a string `file` and
    a `source` glob (string or list of strings); `min_lines` is an optional non-negative int."""
    raw = _config().get("codemap")
    if raw is None:
        return None, None
    if not isinstance(raw, dict):
        return None, "`codemap` must be an object {file, source, min_lines?}"
    src = raw.get("source")
    srcs = [src] if isinstance(src, str) else src
    missing = [] if isinstance(raw.get("file"), str) and raw["file"].strip() else ["file"]
    if not (isinstance(srcs, list) and srcs and all(isinstance(s, str) and s for s in srcs)):
        missing.append("source")
    if missing:
        return None, f"`codemap` needs {', '.join(missing)}"
    min_lines = raw.get("min_lines", 0)
    if isinstance(min_lines, bool) or not isinstance(min_lines, int) or min_lines < 0:
        return None, "`codemap.min_lines` must be a non-negative integer"
    return {"file": raw["file"], "source": srcs, "min_lines": min_lines}, None


def _codemap_python(text):
    """([(start, end, kind, name)], problem) for a Python source: top-level defs and classes plus
    each class's own methods as `Class.method`. A range starts at the first decorator."""
    import ast
    import warnings
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")             # e.g. invalid escapes: not our business
            tree = ast.parse(text)
    except (SyntaxError, ValueError) as e:
        where = f" at line {e.lineno}" if getattr(e, "lineno", None) else ""
        return [], f"could not parse: {type(e).__name__}{where}"
    defs = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

    def row(node, name):
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        kind = ("class" if isinstance(node, ast.ClassDef)
                else "async def" if isinstance(node, ast.AsyncFunctionDef) else "def")
        return (start, node.end_lineno, kind, name)

    rows = []
    for node in tree.body:
        if isinstance(node, defs):
            rows.append(row(node, node.name))
            if isinstance(node, ast.ClassDef):
                rows.extend(row(sub, f"{node.name}.{sub.name}")
                            for sub in node.body if isinstance(sub, defs))
    return rows, None


def _codemap_blank(text, rust=False):
    """`text` split into lines with comments removed and string contents blanked, so a brace or a
    keyword inside either never counts. A `'`/`"` string ends at end of line even if unclosed. In
    Rust a `'` opens only a char literal, so a lifetime (`impl<'a> Foo<'a>`) stays code."""
    lines, buf, state, i, n = [], [], None, 0, len(text)
    while i < n:
        c = text[i]
        if c == "\n":
            if state in ("'", '"'):
                state = None
            lines.append("".join(buf))
            buf = []
        elif state == "block":
            if text.startswith("*/", i):
                state = None
                i += 1
        elif state:
            if c == "\\" and i + 1 < n and text[i + 1] != "\n":
                i += 1
            elif c == state:
                buf.append(c)
                state = None
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = (j if j >= 0 else n) - 1
        elif text.startswith("/*", i):
            state = "block"
            i += 1
        else:
            if c in "'\"`" and not (rust and c == "'" and not CODEMAP_RUST_CHAR_RE.match(text, i)):
                state = c
            buf.append(c)
        i += 1
    lines.append("".join(buf))
    return lines


def _codemap_def(line, member):
    """(kind, name) when a blanked line opens a definition, else None. `member` means the line
    sits directly inside a container block, where a method needs no return-type prefix."""
    m = CODEMAP_KEYWORD_RE.match(line)
    if m:
        kind, rest = m.group("kind").rstrip("*"), m.group("rest").lstrip("* ")
        if kind == "impl":
            head = re.split(r"\{|\bwhere\b", re.sub(r"^<[^>]*>", "", rest), maxsplit=1)[0]
            name = " ".join(head.split())
        else:
            if kind == "func":
                rest = re.sub(r"^\([^)]*\)\s*", "", rest)  # a Go method's receiver
            n = re.match(r"(?:<[^>]*>\s*)?([A-Za-z_$][\w$]*)", rest)
            name = n.group(1) if n else ""
        return (kind, name) if name else None
    m = CODEMAP_ARROW_RE.match(line)
    if m:
        return "const", m.group("name")
    m = CODEMAP_CFN_RE.match(line)
    if m and (m.group("prefix") or member):
        words = re.findall(r"[A-Za-z_]\w*", m.group("prefix"))
        if m.group("name") not in CODEMAP_NOT_FN and not CODEMAP_NOT_FN.intersection(words):
            return "function", m.group("name")
    return None


def _codemap_brace(text, c_family, rust=False):
    """[(start, end, kind, name)] for a brace-language source — best effort, by brace depth: a
    definition line at depth 0 (or directly inside a top-level container) opens a symbol at its
    next `{` and closes where depth returns; a `;` first means a declaration, dropped."""
    code = _codemap_blank(text, rust)
    rows, opened, pending, depth = [], [], None, 0   # opened: (depth, row index, container name)
    for no, line in enumerate(code, 1):
        if c_family and line.lstrip().startswith("#"):
            continue
        scope = None
        if depth == 0:
            scope = ""
        elif depth == 1 and opened and opened[-1][0] == 0 and opened[-1][2]:
            scope = opened[-1][2] + "."
        hit = _codemap_def(line, bool(scope)) if scope is not None else None
        if hit:
            kind, name = hit
            pending = (kind, scope + name, no, depth, kind in CODEMAP_CONTAINERS and not scope)
        for ch in line:
            if ch == "{":
                if pending and pending[3] == depth:
                    rows.append([pending[2], None, pending[0], pending[1]])
                    opened.append((depth, len(rows) - 1, pending[1] if pending[4] else None))
                    pending = None
                depth += 1
            elif ch == "}":
                depth = max(depth - 1, 0)
                if opened and opened[-1][0] == depth:
                    rows[opened.pop()[1]][1] = no
            elif ch == ";" and pending and pending[3] == depth:
                pending = None
        if pending and no - pending[2] >= CODEMAP_PENDING_LINES:
            pending = None
    return [(s, e if e is not None else len(code), k, n) for s, e, k, n in rows]


def _codemap_chunk(root, rel):
    """The map lines for one source file: a heading with its line count, then its symbol table
    (or a one-line note when it has none, can't be parsed, or has no parser)."""
    with open(os.path.join(root, rel), encoding="utf-8", errors="replace") as f:
        text = f.read()
    count = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    ext = os.path.splitext(rel)[1].lower()
    problem = None
    if ext in CODEMAP_PY_EXTS:
        rows, problem = _codemap_python(text)
    elif ext in CODEMAP_BRACE_EXTS:
        rows = _codemap_brace(text, ext in CODEMAP_C_EXTS, ext == ".rs")
    else:
        rows, problem = [], f"no symbol parser for {ext or 'files without an extension'}"
    out = [f"### `{rel}` — {count} line{'' if count == 1 else 's'}", ""]
    if problem or not rows:
        return out + [f"*({problem or 'no top-level definitions recognised'})*"]
    out += ["| Lines | Kind | Symbol |", "|---|---|---|"]
    for s, e, kind, name in rows:
        span = f"{s}" if s == e else f"{s}–{e}"
        out.append(f"| {span} | {kind} | `{name.replace('|', chr(92) + '|')}` |")
    return out


def _codemap_chunks(root, cfg):
    """[(rel, lines)] for every source file the config selects, in path order: what `source`
    matches (never the map file itself — `_table_sources` rules), at least `min_lines` long."""
    chunks = []
    for rel in _table_sources(root, cfg):
        if cfg["min_lines"]:
            try:
                with open(os.path.join(root, rel), "rb") as f:
                    if f.read().count(b"\n") < cfg["min_lines"]:
                        continue
            except OSError:
                continue
        chunks.append((rel, _codemap_chunk(root, rel)))
    return chunks


def _codemap_body(cfg, chunks):
    """The lines between the markers. Each chunk ends in a blank line, so a table never runs into
    the END marker."""
    if not chunks:
        floor = f" with at least {cfg['min_lines']} lines" if cfg["min_lines"] else ""
        return [f"*(no file matches `codemap.source`{floor})*", ""]
    return [ln for _rel, lines in chunks for ln in lines + [""]]


def _codemap_block(root, cfg):
    """(lines, begin index, end index) of the map file under `root`, or an error string when the
    file or its marker pair is missing."""
    return _marked_block(root, cfg["file"], CODEMAP_BEGIN, CODEMAP_END,
                         f"the code map file {cfg['file']} is missing")


def _codemap_write(root, cfg, body):
    """Rewrite the marked block under `root` with `body`. True when the file changed. A missing
    file or marker pair warns and writes nothing — `land` calls this on main after the merge,
    where it must degrade to "map not updated", never to a half-landed main."""
    block = _codemap_block(root, cfg)
    if isinstance(block, str):
        print(f"WARN — {block}; code map not updated")
        return False
    lines, a, b = block
    if lines[a + 1:b] == body:
        return False
    write_lines(lines[:a + 1] + body + lines[b:], os.path.join(root, cfg["file"]))
    return True


def _codemap_bootstrap(root, cfg):
    """`codemap write`'s first run: create the map file, or add the marker pair to the end of an
    existing one. Returns a note saying which, or None when the block was already there."""
    path = os.path.join(root, cfg["file"])
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path) or root, exist_ok=True)
        write_lines(["# Code map", "",
                     "Generated by `todo-lock.py codemap write` (and on every `land`): each large "
                     "source file's", "top-level definitions with their line ranges. Open the "
                     "range you need, not the file.", "",
                     CODEMAP_BEGIN, CODEMAP_END], path)
        return "created the file"
    if isinstance(_codemap_block(root, cfg), str):
        lines = read_lines(path)
        while lines and not lines[-1].strip():
            lines.pop()
        write_lines(lines + ["", CODEMAP_BEGIN, CODEMAP_END], path)
        return "added the markers at the end"
    return None


def _codemap_stale(current, chunks):
    """The source paths whose part of the map differs from what's on disk, including files added
    or removed since — compared chunk by chunk under each `### \\`path\\`` heading."""
    def split(lines):
        out, cur = {}, None
        for ln in lines:
            m = CODEMAP_HEADING_RE.match(ln)
            if m:
                cur = m.group(1)
                out[cur] = []
            if cur is not None:
                out[cur].append(ln)
        return {k: "\n".join(v).rstrip("\n") for k, v in out.items()}

    have = split(current)
    want = {rel: "\n".join(lines) for rel, lines in chunks}
    stale = sorted(rel for rel in set(have) | set(want) if have.get(rel) != want.get(rel))
    return stale or ["(the block's layout, not any one file)"]


def _codemap_land(maintree):
    """`land`'s share: regenerate the code map on main. Returns [file] when it changed."""
    cfg, problem = _codemap_config()
    if problem:
        print(f"WARN — {problem}; code map skipped (see `help config`)")
    if cfg is None:
        return []
    return [cfg["file"]] if _codemap_write(maintree, cfg, _codemap_body(
        cfg, _codemap_chunks(maintree, cfg))) else []


def cmd_codemap(argv):
    if len(argv) != 1 or argv[0] not in ("render", "check", "write"):
        print("ERROR — usage: todo-lock.py codemap render|check|write (see `help codemap`)")
        return 2
    sub = argv[0]
    cfg, problem = _codemap_config()
    if problem:
        print(f"ERROR — {problem} (see `help config`)")
        return 2
    if cfg is None:
        print("the code map is not configured — add a `codemap` object to "
              "`.claude/todo-config.json` (see `help config`)")
        return 2
    root = _seq_worktree()
    chunks = _codemap_chunks(root, cfg)
    body = _codemap_body(cfg, chunks)
    if sub == "write":
        note = _codemap_bootstrap(root, cfg)
        state = "updated" if _codemap_write(root, cfg, body) else "already current"
        print(f"codemap\t{cfg['file']}\t{len(chunks)} file(s) {state}"
              + (f" ({note})" if note else ""))
        return 0
    block = _codemap_block(root, cfg)
    if isinstance(block, str):
        if sub == "render":
            print(f"codemap\t{cfg['file']}\t{len(chunks)} file(s), no marker block")
            print("\n".join(body))
        print(f"ERROR — {block}; `todo-lock.py codemap write` creates it (nothing written)")
        return 1 if sub == "render" else 2
    lines, a, b = block
    current = lines[a + 1:b]
    if sub == "render":
        print(f"codemap\t{cfg['file']}\t{len(chunks)} file(s), "
              + ("current" if current == body else "would change"))
        print("\n".join(body))
        return 0
    if current == body:
        print(f"OK — {cfg['file']} matches the {len(chunks)} source file(s) it maps")
        return 0
    print(f"STALE — {cfg['file']} no longer matches these source files:")
    for rel in _codemap_stale(current, chunks):
        print(f"  {rel}")
    print("\nRegenerate it:  python3 .claude/todo-lock.py codemap write")
    return 1


# @fragment 62_docs.py
# ---------------------------------------------------------------------------
# Docs lookup — the store treatment for documentation: the script maps paths to
# a few section pointers (`docs for`) and prints one section (`docs show
# --section`), so an agent reads one section of a document instead of the whole
# file. Read-only. Candidates are active sequence entries (their `scope`), the
# `docs` registry in config, and markdown under `doc_dirs` (body search only).
# Opt-in: with none of the three configured, the group prints a hint and `next`
# prints nothing extra.
# ---------------------------------------------------------------------------

DOCS_MAX_POINTERS = 5
DOCS_SUMMARY_CHARS = 80
DOC_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)(?:\s+#+)?\s*$")


def _docs_registry():
    """The `docs` config list: [{path, scope?, summary?}], malformed entries dropped."""
    reg = _config().get("docs")
    return [d for d in reg if isinstance(d, dict) and d.get("path")] if isinstance(reg, list) else []


def _docs_configured():
    return bool(_docs_registry() or _seq_wellformed() or _config().get("doc_dirs"))


def _docs_rel(p):
    p = str(p).strip().replace("\\", "/")
    return p[2:] if p.startswith("./") else p


def _docs_scope_list(val):
    items = val if isinstance(val, list) else str(val or "").split(",")
    return [_docs_rel(s) for s in items if str(s).strip()]


def _docs_read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return ""


def _docs_candidates():
    """Every document `docs for` may point at: [{ref, rel, path, scope, summary, kind, text}], kind
    0 for a sequence entry, 1 for a registry doc, 2 for a `doc_dirs` file (body search only). One
    per file, the first kind that names it winning. Superseded and deprecated entries are left out."""
    wt, main = _seq_worktree(), os.path.realpath(main_tree())
    out, seen = [], set()

    def add(ref, path, root, scope, summary, kind, text=None):
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        if rel not in seen:
            seen.add(rel)
            out.append({"ref": ref, "rel": rel, "path": path, "scope": scope, "summary": summary,
                        "kind": kind, "text": _docs_read(path) if text is None else text})

    for name, cfg in _seq_wellformed():
        entries = _seq_entries(cfg)
        for n, meta in sorted(_seq_meta_all(name, cfg, entries).items()):
            if _seq_status_is(meta["status"], SEQ_INACTIVE) or meta["superseded_by"]:
                continue
            path = entries[n]
            root = wt if os.path.realpath(path).startswith(wt + os.sep) else main
            add(f"{name}-{n}", path, root, meta["scope"], meta["summary"], 0, meta["text"])
    doc_dirs = set(_config().get("doc_dirs") or [])
    registry = _docs_registry()
    files = _seq_repo_files(wt) if registry or doc_dirs else []
    for d in registry:
        pat = _docs_rel(d["path"])
        hits = [f for f in files if fnmatch.fnmatchcase(f, pat)] if _is_glob(pat) else [pat]
        for rel in hits:
            if os.path.isfile(os.path.join(wt, rel)):
                add(rel, os.path.join(wt, rel), wt, _docs_scope_list(d.get("scope")),
                    str(d.get("summary") or ""), 1)
    for rel in files:
        if rel.endswith(".md") and doc_dirs.intersection(rel.split("/")[:-1]):
            add(rel, os.path.join(wt, rel), wt, [], "", 2)
    return out


def _doc_headings(lines):
    """[(level, text, start, end)] for each ATX heading outside a code fence (and past any
    front-matter), 1-based inclusive lines. A section runs to the line before the next heading of
    the same or a higher level, trailing blank lines trimmed."""
    _fm, first = _seq_front_matter(lines)
    heads, fence = [], None
    for i in range(first, len(lines)):
        fence, is_fence = _fence_step(fence, lines[i])
        if is_fence or fence is not None:
            continue
        m = DOC_HEADING_RE.match(lines[i])
        if m and m.group(2):
            heads.append([len(m.group(1)), m.group(2), i + 1, len(lines)])
    for k, h in enumerate(heads):
        h[3] = next((later[2] - 1 for later in heads[k + 1:] if later[0] <= h[0]), len(lines))
        while h[3] > h[2] and not lines[h[3] - 1].strip():
            h[3] -= 1
    return [tuple(h) for h in heads]


def _docs_term_rx(paths):
    """A regex for the queried paths and their basenames (3+ chars) as whole names in prose."""
    terms = set()
    for p in paths:
        p = p.rstrip("/")
        if p and not _is_glob(p):
            terms.add(p)
            base = posixpath.basename(p)
            if len(base) >= 3:
                terms.add(base)
    if not terms:
        return None
    alt = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
    return re.compile(r"(?<![\w.-])(?:%s)(?![\w-])" % alt)


def _docs_first_prose(lines, start, end):
    """The first prose line of lines[start-1:end] after its heading — no heading, fence, table
    rule or front-matter — with a leading list marker dropped; '' if none."""
    fence = None
    for ln in lines[start:end]:
        fence, is_fence = _fence_step(fence, ln)
        s = ln.strip()
        if is_fence or fence is not None or not s or s.startswith(("#", "|", "---", "<!--")):
            continue
        return re.sub(r"^(?:[-*+]|\d+\.)\s+", "", s)
    return ""


def _docs_pointer(c, term_rx):
    """One pointer line: `<ref>  §<heading>  <file>:<a>-<b>  <summary>`. The section is the one
    whose own text (up to the next heading of any level) names a queried path most often — a
    sub-section over the top-level title when any qualifies, the earlier on a tie; else the doc's
    first heading over the whole file."""
    lines = c["text"].splitlines()
    heads = _doc_headings(lines)
    top = min((h[0] for h in heads), default=1)
    hits = []
    for k, (lvl, _text, start, _end) in enumerate(heads):
        own_end = heads[k + 1][2] - 1 if k + 1 < len(heads) else len(lines)
        n = len(term_rx.findall("\n".join(lines[start - 1:own_end]))) if term_rx else 0
        if n:
            hits.append((lvl > top, n, -k))
    pick = heads[-max(hits)[2]] if hits else None
    if pick is None:
        pick = ((1, heads[0][1], heads[0][2], len(lines)) if heads
                else (1, posixpath.basename(c["rel"]), 1, max(len(lines), 1)))
    _lvl, heading, start, end = pick
    summary = c["summary"] or _docs_first_prose(lines, start, end)
    if len(summary) > DOCS_SUMMARY_CHARS:
        summary = summary[:DOCS_SUMMARY_CHARS - 1].rstrip() + "…"
    return f"{c['ref']}  §{heading}  {c['rel']}:{start}-{end}  {summary}".rstrip()


def _docs_scope_specificity(glob):
    """How narrow a scope glob is: the length of its literal prefix (`src/net/**` beats `src/**`)."""
    return len(re.split(r"[*?\[]", glob, maxsplit=1)[0])


def _docs_pointers(paths, scope_only=False):
    """At most DOCS_MAX_POINTERS pointer lines for the documents that bear on `paths`. A scope hit
    (sequence entry or registry doc) ranks first — the narrower matching glob, then more paths
    covered, then a sequence entry over a registry doc; a body mention of a path or its basename
    fills any slots left, by mention count, unless `scope_only` (used by `docs touched`, where a
    stray name match on a changed file is noise, not a document worth a look). A queried path is
    never its own pointer."""
    qs = [q for q in (_docs_rel(p) for p in paths) if q and q != "."]
    if not qs:
        return []
    own = {q.rstrip("/") for q in qs}
    term_rx = None if scope_only else _docs_term_rx(qs)
    scored = []
    for c in _docs_candidates():
        if c["rel"] in own:
            continue
        best, covered = -1, 0
        for q in qs:
            specs = [_docs_scope_specificity(g) for g in c["scope"] if _seq_scope_matches([g], q)]
            if specs:
                covered += 1
                best = max(best, *specs)
        if covered:
            scored.append(((2, best, covered, -c["kind"]), c))
            continue
        mentions = len(term_rx.findall(c["text"])) if term_rx is not None else 0
        if mentions:
            scored.append(((1, mentions, 0, -c["kind"]), c))
    scored.sort(key=lambda s: s[0], reverse=True)
    return [_docs_pointer(c, term_rx) for _key, c in scored[:DOCS_MAX_POINTERS]]


def _docs_next_lines(paths):
    """The `Docs:` block `next` prints for a claim — nothing when docs aren't configured, nothing
    matches, or the lookup fails (decoration under the claim locks, never the claim)."""
    if not paths or not _docs_configured():
        return []
    try:
        pointers = _docs_pointers(paths)
    except Exception:  # noqa: BLE001 — a lookup failure costs the hint, never the claim
        return []
    return ["Docs:"] + ["  " + p for p in pointers] if pointers else []


def _docs_resolve(ref):
    """(absolute path, display path) for a `docs show` reference — a repo path (this checkout's
    copy first, then the main tree's) or a sequence reference (`adr-22`, `adr-0022`) — or None.
    A path outside both trees is refused."""
    wt, main = _seq_worktree(), os.path.realpath(main_tree())
    rel = _docs_rel(ref)
    for root in (wt, main):
        path = os.path.realpath(os.path.join(root, rel))
        if path.startswith(root + os.sep) and os.path.isfile(path):
            return path, os.path.relpath(path, root).replace(os.sep, "/")
    if "/" in rel:
        return None
    for name, cfg in _seq_wellformed():
        if not rel.lower().startswith(name.lower()):
            continue
        n = _seq_ref_number(name, rel)
        path = _seq_entries(cfg).get(n) if n is not None else None
        if path:
            root = wt if os.path.realpath(path).startswith(wt + os.sep) else main
            return path, os.path.relpath(path, root).replace(os.sep, "/")
    return None


def _docs_item_claim(item_id):
    """(item or None, claim dict) for a `docs … --id`, or None after printing NONE when the id is
    neither in the store nor claimed."""
    it = find_item(parse_items(read_lines()), item_id)
    with State() as st:
        claim = st.claims.get(item_id) or {}
    if it is None and not claim:
        print(f"NONE — no item {item_id} in the backlog")
        return None
    return it, claim


def _docs_cmd_for(argv):
    ap = _ArgParser(prog="todo-lock.py docs for", add_help=False)
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--id", dest="item_id")
    opts = ap.parse_args(argv)
    paths = list(opts.paths)
    if opts.item_id:
        found = _docs_item_claim(opts.item_id)
        if found is None:
            return 1
        it, claim = found
        if it is not None:
            paths += _split_declared_files(_item_files(it["body"]))
        paths += claim.get("files") or []
    if not paths:
        print("ERROR — usage: todo-lock.py docs for <paths…> | --id <ID>")
        return 2
    paths = _dedupe_paths(paths)
    pointers = _docs_pointers(paths)
    if not pointers:
        print(f"NONE — no docs point at {', '.join(paths)}")
        return 1
    for p in pointers:
        print(p)
    return 0


def _docs_cmd_show(argv):
    ap = _ArgParser(prog="todo-lock.py docs show", add_help=False)
    ap.add_argument("ref")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--section")
    mode.add_argument("--outline", action="store_true")
    opts = ap.parse_args(argv)
    hit = _docs_resolve(opts.ref)
    if hit is None:
        print(f"NONE — no document {opts.ref!r} (a repo path, or a sequence ref like adr-12)")
        return 1
    path, rel = hit
    text = _docs_read(path)
    lines = text.splitlines()
    heads = _doc_headings(lines)
    if opts.outline:
        for lvl, heading, start, end in heads:
            print(f"{'  ' * (lvl - 1)}{'#' * lvl} {heading}  {start}-{end}")
        return 0
    if opts.section is None:
        sys.stdout.write(text)
        return 0
    want = opts.section.strip().lstrip("§#").strip().casefold()
    found = [h for h in heads if h[1].casefold() == want]
    found = found or [h for h in heads if want and want in h[1].casefold()]
    if len(found) != 1:
        what = "matches several headings" if found else "matches no heading"
        print(f"NONE — section {opts.section!r} {what} in {rel}"
              + (":" if found else f"; `docs show {opts.ref} --outline` lists them"))
        for lvl, heading, start, end in found:
            print(f"  {'#' * lvl} {heading}  {start}-{end}")
        return 1
    _lvl, _heading, start, end = found[0]
    print("\n".join(lines[start - 1:end]))
    return 0


def _docs_cmd_touched(argv):
    """The `Docs:`-style pointers for the documents whose `scope` covers a path this branch
    changed: no --id, the current worktree's own uncommitted-included diff against its branch
    point (`_touched_since_branch_point`); --id <ID>, that claim's recorded branch, commits only —
    the `_land_undeclared` shape, so it works from any checkout, not just the item's own worktree."""
    ap = _ArgParser(prog="todo-lock.py docs touched", add_help=False)
    ap.add_argument("--id", dest="item_id")
    opts = ap.parse_args(argv)
    if opts.item_id:
        found = _docs_item_claim(opts.item_id)
        if found is None:
            return 1
        claim = found[1]
        branch = claim.get("branch")
        if not branch:
            print(f"NONE — {opts.item_id} has no recorded worktree branch. Record it from inside "
                  f"the item's worktree first: `todo-lock.py attach {opts.item_id}`")
            return 1
        try:
            diff = subprocess.run(
                ["git", "-C", main_tree(), "diff", "--name-only", f"{base_branch()}...{branch}"],
                capture_output=True, text=True, check=True,
            ).stdout.splitlines()
        except (subprocess.CalledProcessError, OSError):
            diff = []
        paths = _dedupe_paths([p for p in diff if p] + list(claim.get("touched") or []))
    else:
        paths = _touched_since_branch_point()
    if not paths:
        print("NONE — no changes on this branch yet")
        return 1
    pointers = _docs_pointers(paths, scope_only=True)
    if not pointers:
        print("NONE — no scoped document covers this branch's changes")
        return 1
    for p in pointers:
        print(p)
    return 0


def _docs_cmd_stale(argv):
    """Registry docs (a `docs` entry with `scope`) that have commits on their own scope newer than
    the doc's own last commit — `docs`' history-based half of DOC-8, for `/optimize` to flag when
    a documented area moved on without the doc. Sequence entries never appear: an accepted record
    is not edited, so flagging it would never be actionable."""
    ap = _ArgParser(prog="todo-lock.py docs stale", add_help=False)
    ap.parse_args(argv)
    files = _seq_repo_files(_seq_worktree())
    hits = []
    for c in _docs_candidates():
        if c["kind"] != 1 or not c["scope"]:
            continue
        try:
            doc_commit = _git("log", "-1", "--format=%H", "HEAD", "--", c["rel"])
        except subprocess.CalledProcessError:
            doc_commit = ""
        if not doc_commit:
            continue
        scoped = [f for f in files if f != c["rel"]
                  and any(_seq_scope_matches([g], f) for g in c["scope"])]
        if not scoped:
            continue
        try:
            commits = subprocess.run(
                ["git", "log", "--format=%h %s", f"{doc_commit}..HEAD", "--", *scoped],
                capture_output=True, text=True, check=True,
            ).stdout.splitlines()
        except subprocess.CalledProcessError:
            continue
        if not commits:
            continue
        latest = commits[0]
        if len(latest) > DOCS_SUMMARY_CHARS:
            latest = latest[:DOCS_SUMMARY_CHARS - 1].rstrip() + "…"
        hits.append((c["rel"], f"{c['rel']}  {len(commits)} newer commit(s) on scope, "
                                f"latest {latest}"))
    if not hits:
        print("NONE — no registered document is behind its scope")
        return 1
    for _rel, line in sorted(hits):
        print(line)
    return 0


def cmd_docs(argv):
    subs = {"for": _docs_cmd_for, "show": _docs_cmd_show, "touched": _docs_cmd_touched,
            "stale": _docs_cmd_stale}
    if not argv or argv[0] not in subs:
        print("ERROR — usage: todo-lock.py docs for|show|touched|stale … (see `help docs`)")
        return 2
    if not _docs_configured():
        print("docs lookup is not configured — add a `docs` registry, `sequences` or `doc_dirs` to "
              "`.claude/todo-config.json` to enable the `docs` commands (see `help config`)")
        return 2
    return subs[argv[0]](argv[1:])


# @fragment 70_context.py
# ---------------------------------------------------------------------------
# Project context — the facts about THIS repo a command would otherwise carry as
# "if your repo configures …" prose or learn by reading config, plus the project
# overlay: `.claude/local-todo/<command>.md`, short project instructions that
# survive `/update` (install.sh and update never touch the directory; the name
# keeps it outside older installs' `.claude/todo-*.md` update guard). Overlay
# text is instructions, so it is read only from the main checkout's committed
# HEAD, never a working copy. Folded into each command's first call (`next`,
# `summary --context todo`, `context finish --id`) so it costs no extra call.
# ---------------------------------------------------------------------------

OVERLAY_DIR = ".claude/local-todo"
OVERLAY_COMMANDS = ("plan-todo", "finish", "todo")
OVERLAY_SCHEMA = "schema: 1"
OVERLAY_MAX_BYTES = 1200
CONTEXT_MAX_BYTES = 1500
PLANNING_REF = ".claude/skills/plan-todo/todo-planning-reference.md"
WORKTREE_SIGNOFF_RE = re.compile(r"worktree[^\n]{0,160}authori[sz]|authori[sz][^\n]{0,160}worktree",
                                 re.I)


def _overlay_problems(name, text):
    """Why an overlay file is unusable, one phrase each: an unknown command name, over the size
    cap, no `schema: 1` first line, or not text. Shared by `context set` (refuses) and `doctor`
    (warns), so the two never disagree."""
    out = []
    if not (name.endswith(".md") and name[:-3] in OVERLAY_COMMANDS):
        out.append(f"unknown command file {name} (expected "
                   + ", ".join(c + ".md" for c in OVERLAY_COMMANDS) + ")")
    if text is None or "\0" in text:
        return out + ["not UTF-8 text"]
    size = len(text.encode("utf-8"))
    if size > OVERLAY_MAX_BYTES:
        out.append(f"{size} bytes, over the {OVERLAY_MAX_BYTES}-byte cap")
    if text.split("\n", 1)[0].strip() != OVERLAY_SCHEMA:
        out.append(f"first line is not `{OVERLAY_SCHEMA}`")
    return out


def _overlay_committed(cmd):
    """The overlay's text at the main checkout's HEAD, None when there is none, or "\\0" when it
    isn't UTF-8. Never the working copy: an uncommitted file is not yet the project's word."""
    r = subprocess.run(["git", "-C", main_tree(), "show", f"HEAD:{OVERLAY_DIR}/{cmd}.md"],
                       capture_output=True)
    if r.returncode != 0:
        return None
    try:
        return r.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return "\0"


def _overlay_lines(cmd):
    """The block's overlay part: a heading plus the text (schema line dropped), a one-line note when
    the committed file has no schema line or isn't text, or [] when there is no overlay."""
    text = _overlay_committed(cmd)
    if text is None:
        return []
    rel = f"{OVERLAY_DIR}/{cmd}.md"
    lines = text.split("\n")
    if "\0" in text or lines[0].strip() != OVERLAY_SCHEMA:
        return [f"  overlay {rel} ignored: first line is not `{OVERLAY_SCHEMA}` — run `doctor`"]
    # `context set --section` markers are bookkeeping, never instructions: they don't print.
    body = "\n".join(ln for ln in lines[1:] if not STACK_MARK_RE.match(ln)).strip("\n").split("\n")
    if body == [""]:
        return []
    return [f"  overlay ({rel}):"] + [("    " + ln).rstrip() for ln in body]


def _worktree_setup_missing():
    """What `/plan-todo` step 4 needs and this repo lacks, or [] when worktree isolation is set up:
    `worktree.baseRef: "head"` in the project settings, and a CLAUDE.md line (project or user)
    authorizing worktrees.
    The sign-off check is a heuristic; a miss costs a pointer line, never a refusal."""
    root = main_tree()
    missing = []
    if not any(isinstance(d.get("worktree"), dict) and d["worktree"].get("baseRef") == "head"
               for d in (_read_json(os.path.join(root, ".claude", n))
                         for n in ("settings.json", "settings.local.json"))):
        missing.append('`"worktree": {"baseRef": "head"}` in .claude/settings.json')
    signed = False
    for path in (os.path.join(root, "CLAUDE.md"), os.path.join(root, ".claude", "CLAUDE.md"),
                 os.path.join(root, "CLAUDE.local.md"),
                 os.path.join(os.path.expanduser("~"), ".claude", "CLAUDE.md")):
        try:
            with open(path, encoding="utf-8") as f:
                signed = signed or bool(WORKTREE_SIGNOFF_RE.search(f.read()))
        except (OSError, UnicodeDecodeError):
            pass
    if not signed:
        missing.append("a worktree sign-off line in CLAUDE.md")
    return missing


def _context_facts(cmd, item_id=None, with_verify=True):
    """The config-derived lines `cmd` acts on. A fact that asks nothing of this repo prints nothing,
    so an unconfigured feature costs neither prompt text nor output."""
    out = []
    if item_id:
        it = find_item(parse_items(read_lines()), item_id)
        if it:
            out.append(f"item: {item_id} routes to {_route_label(_item_route(it['body']))}")
    if cmd in ("plan-todo", "todo"):
        seqs = _seq_wellformed()
        if seqs:
            names = ", ".join(f"{n} ({c['dir']})" for n, c in seqs)
            out.append(f"sequences: {names} — " + (
                "an item that adds a numbered entry reserves its number while planning: read "
                f"{PLANNING_REF} (\"Reserving a sequence number\")" if cmd == "plan-todo" else
                "an item whose work deserves a numbered record says `**Docs:** new <sequence> "
                "record`"))
    labels = _inherit_labels() if cmd in ("plan-todo", "todo") else []
    if labels:
        out.append(f"inherit_bullets: {', '.join(labels)} — omit these bullets when filing from a "
                   "claimed item; add inherits them")
    if cmd in ("plan-todo", "finish") and _version_configured():
        out.append(f"release bookkeeping: on ({_version_source_rel()}) — " + (
            "a release item records only its SemVer tier while planning" if cmd == "plan-todo"
            else "if the change warrants a release, a `{VERSION}` changelog heading and "
                 "`finish --tier`")
            + f": read {PLANNING_REF} (\"Release bookkeeping\")")
    if cmd == "plan-todo":
        missing = _worktree_setup_missing()
        if missing:
            out.append(f"worktree isolation: not set up (no {' and no '.join(missing)}) — read "
                       f"{PLANNING_REF} (\"One-time: authorize worktree isolation\") before step 4")
    if with_verify and cmd in ("plan-todo", "finish"):
        hint = _verify_hint()
        if hint:
            out.append(hint)
    if cmd == "todo":
        hot = sorted(DEFAULT_HOT_FILES | set(_config().get("hot_files") or []))
        dirs = sorted(_config().get("hot_dirs") or [])
        out.append("hot files: " + ", ".join(hot)
                   + (f"; hot dirs: {', '.join(d + '/' for d in dirs)}" if dirs else ""))
    return out


def _context_block(cmd, item_id=None, with_verify=True, full=False):
    """`Project context (<cmd>):` with its facts and overlay, capped at CONTEXT_MAX_BYTES unless
    `full`; [] when there is nothing to say. Never raises: inside `next` it decorates a claim that
    is already saved."""
    try:
        body = ["  " + f for f in _context_facts(cmd, item_id, with_verify)] + _overlay_lines(cmd)
    except Exception:
        return []
    if not body:
        return []
    lines = [f"Project context ({cmd}):"] + body
    if full:
        return lines
    more = f"  … truncated — `context {cmd} --full` prints the rest"
    kept, size = [], len(more.encode("utf-8")) + 1
    for ln in lines:
        size += len(ln.encode("utf-8")) + 1
        if size > CONTEXT_MAX_BYTES:
            return kept + [more]
        kept.append(ln)
    return kept


def _context_cmd_set(argv):
    ap = _ArgParser(prog="todo-lock.py context set", add_help=False)
    ap.add_argument("command")
    _body_file_flag(ap)
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("-m", "--message", default=None)
    ap.add_argument("--section", default=None)
    opts = ap.parse_args(argv)
    text, _source, err = _read_payload(opts.body_file)
    if err:
        print(f"ERROR — {err}")
        return 2
    if opts.section is not None:
        if not re.fullmatch(r"[a-z0-9-]+", opts.section):
            print(f"ERROR — --section {opts.section!r} must be lowercase letters, digits or `-`")
            return 2
        rel = f"{OVERLAY_DIR}/{opts.command}.md"
        # Merge into the working copy (or HEAD's, or a fresh file), so the rest survives.
        base = (_stack_read(main_tree(), rel) or _overlay_committed(opts.command)
                or OVERLAY_SCHEMA + "\n")
        text, err = _marker_merge(base, opts.section, text, rel)
        if err:
            print(f"REFUSED — {err}. Nothing was written.")
            return 2
    text = text.strip("\n") + "\n"
    problems = _overlay_problems(opts.command + ".md", text)
    if problems:
        print("REFUSED — " + "; ".join(problems) + ". Nothing was written.")
        return 2
    if not opts.commit and _in_linked_worktree():
        print(f"REFUSED — the overlay lives in the main checkout ({main_tree()}); from this "
              "worktree it would be left uncommitted there. Re-run with --commit. Nothing was "
              "written.")
        return 2
    maintree = main_tree()
    rel = f"{OVERLAY_DIR}/{opts.command}.md"
    path = os.path.join(maintree, rel)
    if not opts.commit:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _atomic_write(path, text)
        print(f"OK wrote {rel} — read only once committed (`--commit` writes and commits)")
        return 0
    with GitMutex():
        ok, note = _commit_precheck(maintree, rel)
        if not ok:
            print(note)
            return 1
        if _overlay_committed(opts.command) == text:
            print(f"OK {rel} unchanged — nothing to commit")
            return 0
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _atomic_write(path, text)
        sha, err = _commit_store(maintree, rel,
                                 opts.message or f"Set the {opts.command} project context")
    if err:
        print(f"ERROR — {rel} is written but its commit failed: {err}")
        return 1
    print(f"OK committed {rel} ({sha})")
    if note:
        print(note)
    return 0


def _overlay_notes():
    """`doctor`'s lines for the overlay files in the main checkout — the working copy, so a bad
    file is caught before it is committed."""
    d = os.path.join(main_tree(), OVERLAY_DIR)
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return []
    out = []
    for name in names:
        path = os.path.join(d, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            text = None
        out += [f"{OVERLAY_DIR}/{name}: {p} (see `context set`)"
                for p in _overlay_problems(name, text)]
    return out


def cmd_context(argv):
    if argv and argv[0] == "set":
        return _context_cmd_set(argv[1:])
    ap = _ArgParser(prog="todo-lock.py context", add_help=False)
    ap.add_argument("command", choices=OVERLAY_COMMANDS)
    ap.add_argument("--id", default=None)
    ap.add_argument("--full", action="store_true")
    opts = ap.parse_args(argv)
    lines = _context_block(opts.command, item_id=opts.id, full=opts.full)
    print("\n".join(lines) if lines else f"Project context ({opts.command}): none")
    return 0


# @fragment 71_audit.py
# ---------------------------------------------------------------------------
# Audit — the evidence `/optimize` reasons over: what makes this project's workflow slow or
# expensive, from the script's own data (docs, CLAUDE.md, the store, claims, telemetry, and
# optionally Claude Code's local session transcripts). Read-only, and it never prints an item's
# title or body — ids and sizes only. `config set` is the setter `/optimize` proposes changes
# through, beside `context set` for the overlay.
# ---------------------------------------------------------------------------

AUDIT_DOC_LINES = 400        # a document past this, amended in place, is worth splitting
AUDIT_DOC_AMENDS = 2         # commits after the first that count as "amended in place"
AUDIT_CLAUDE_MD_LINES = 200  # CLAUDE.md is loaded into every session
AUDIT_BODY_BYTES = 4096      # an item body past this costs every claim that prints it
AUDIT_RATE = 0.25            # a route bouncing or releasing more than this is misrouting
AUDIT_MIN_RECORDS = 4        # fewer telemetry records than this say nothing about a route
AUDIT_ACCURACY = 0.6         # declared-files recall/precision below this is a finding
AUDIT_REPEAT_FAILS = 3       # the same shell command failing this often across sessions
AUDIT_SESSIONS = 50          # newest transcripts read by --sessions
AUDIT_DOC_EXTS = (".md", ".markdown", ".rst", ".txt", ".adoc")
AUDIT_HOOK_RE = re.compile(r"\b(always|never|before|after|every time|whenever)\b.{0,80}?"
                           r"\b(run|commit|format|lint|test|push|build)", re.I)
AUDIT_RECIPE_RE = re.compile(r"\b(pytest|unittest|npm (?:run )?test|yarn test|pnpm test|make \w+|"
                             r"cargo (?:test|build)|go test|gradle\w* \w+|mvn \w+|xcodebuild|"
                             r"swift (?:test|build)|tox|ruff|eslint|tsc)\b")
CONFIG_KEYS = ("version_source", "version_pattern", "base_branch", "changelog", "hot_files",
               "hot_dirs", "doc_dirs", "docs", "update_check", "stale_claim_hours", "metrics",
               "worktree_setup", "hooks", "inherit_bullets", "routing", "verify", "sequences",
               "tables", "codemap")


def _git_main(*args):
    """A git command's stdout in the main tree, '' when it fails."""
    r = subprocess.run(["git", "-C", main_tree(), *args], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def _audit_long_docs():
    """Tracked documents over AUDIT_DOC_LINES amended in place (DOC-10). Not the store, not the
    shipped payload (an update overwrites it), not a sequence entry (an accepted record)."""
    store = os.path.relpath(main_todo_path(), main_tree()).replace(os.sep, "/")
    skip_dirs = [".claude/skills/", ".claude/commands/", ".claude/agents/", OVERLAY_DIR + "/"]
    skip_dirs += [c["dir"].rstrip("/") + "/" for _n, c in _seq_wellformed()]
    out = []
    for rel in _git_main("ls-files", "-z", "--", "*.md").split("\0"):
        if (not rel or rel == store or any(rel.startswith(d) for d in skip_dirs)
                or fnmatch.fnmatchcase(rel, ".claude/todo-*.md")):
            continue
        try:
            with open(os.path.join(main_tree(), rel), encoding="utf-8", errors="replace") as f:
                n = sum(1 for _ in f)
        except OSError:
            continue
        if n <= AUDIT_DOC_LINES:
            continue
        commits = _git_main("log", "--follow", "--format=%h", "--", rel).split()
        amends = len(commits) - 1
        if amends < AUDIT_DOC_AMENDS:
            continue
        first = _git_main("show", f"{commits[-1]}:{rel}")
        grew = f", {first.count(chr(10))} → {n} lines since {commits[-1]}" if first else ""
        out.append(("long-doc", rel, f"{n} lines, amended in place by {amends} commit(s){grew}"))
    return out


def _audit_claude_md():
    out = []
    root = main_tree()
    for rel in ("CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md"):
        try:
            with open(os.path.join(root, rel), encoding="utf-8", errors="replace") as f:
                lines = f.read().split("\n")
        except OSError:
            continue
        size = sum(len(ln.encode("utf-8")) + 1 for ln in lines)
        if len(lines) > AUDIT_CLAUDE_MD_LINES:
            out.append(("claude-md", rel, f"{len(lines)} lines, {size} bytes — loaded into every "
                        f"session (over {AUDIT_CLAUDE_MD_LINES} lines)"))
        hits = [(i, ln.strip()) for i, ln in enumerate(lines, 1) if AUDIT_HOOK_RE.search(ln)]
        for i, text in hits[:5]:
            out.append(("hook-candidate", f"{rel}:{i}", text[:100]))
    return out


def _audit_verify():
    if _verify_cfg():
        return []
    return [("no-verify", CONFIG_REL, "no `verify.commands` configured — each item rediscovers "
             "the build/test recipe, and `next` prints no verify line")]


def _audit_holders():
    """{holder id: `_claim_entries`} for every Open item (its Files and Docs bullets) and active
    claim (its held files, overriding its item's bullets)."""
    holders = {}
    for it in parse_items(read_lines()):
        if it["section"] != "open":
            continue
        docs = _split_declared_docs(_item_docs(it["body"]))
        files = _split_declared_files(_item_files(it["body"]))
        if files or docs:
            holders[it["id"]] = _claim_entries(files, docs)
    with State() as st:
        claims = dict(st.claims)
    for cid, claim in claims.items():
        held = _claim_held(claim)
        if held:
            holders[cid] = _claim_entries(held, claim.get("docs") or [])
    return holders


def _audit_phantom_overlaps():
    """Pairs whose every overlap is a hard one on a documentation-looking path: the overlap defers
    `next` or warns, though documentation merges cleanly — `doc_dirs` or a Docs bullet fixes it."""
    holders = _audit_holders()
    ids = sorted(holders)
    out = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            hits = [(e[0], _overlap_kind(e, holders[b])) for e in holders[a]]
            hits = [(p, k) for p, k in hits if k]
            if not hits or any(k != "hard" or not p.lower().endswith(AUDIT_DOC_EXTS)
                               for p, k in hits):
                continue
            paths = sorted({p for p, _k in hits})
            dirs = sorted({posixpath.dirname(p) + "/" for p in paths if "/" in p})
            out.append(("phantom-overlap", f"{a}+{b}",
                        f"overlap only on {', '.join(paths)} — a hard overlap on documentation "
                        "(not under `doc_dirs`, not in a Docs bullet)"
                        + (f"; candidate doc_dirs: {', '.join(dirs)}" if dirs else "")))
    return out


def _audit_bodies():
    sizes = []
    for it in parse_items(read_lines()):
        if it["section"] == "open":
            sizes.append((len("\n".join(it["body"][1:]).encode("utf-8")), it["id"]))
    big = sorted((s for s in sizes if s[0] > AUDIT_BODY_BYTES), reverse=True)
    return [("big-body", iid, f"{n} bytes (over {AUDIT_BODY_BYTES}) — printed whole by every "
             "claim and `show`") for n, iid in big[:3]], sizes


def _audit_telemetry(records):
    out = []
    agg = _metrics_stats(records)
    landed = agg["outcomes"].get("landed", 0)
    if landed >= AUDIT_MIN_RECORDS:
        for k, v in agg["declared_files"].items():
            if v is not None and v < AUDIT_ACCURACY:
                out.append(("declared-files", k, f"{v} over {landed} landed item(s) — declared "
                            "Files miss what items touch (recall) or name what they don't "
                            "(precision), so overlap checks misfire"))
    try:
        by_name = _routing()["by_name"]
    except Exception:  # noqa: BLE001 — a bad routing config is `doctor`'s to report, not audit's
        by_name = {}
    rows = {}
    for r in records:
        rows.setdefault(r.get("route") or "(unknown)", []).append(r)
    for name, rs in sorted(rows.items()):
        if len(rs) < AUDIT_MIN_RECORDS:
            continue
        n = {o: sum(r.get("outcome") == o for r in rs) for o in ("landed", "bounced", "released")}
        if (n["bounced"] + n["released"]) / len(rs) > AUDIT_RATE:
            out.append(("route", name, f"{len(rs)} item(s): {n['bounced']} bounced, "
                        f"{n['released']} released — items reach this route that don't belong"))
        route = by_name.get(name)
        done = [r for r in rs if r.get("outcome") == "landed"]
        if route is None or route.model == "sonnet" or len(done) < AUDIT_MIN_RECORDS:
            continue
        touched = _median([(r.get("files_touched") or {}).get("n") or 0 for r in done])
        hours = _median([h for r in done if (h := _hours_between(r.get("claimed_at"),
                                                                  r.get("ended_at"))) is not None])
        if touched is not None and touched <= 2 and hours is not None and hours <= 0.5:
            out.append(("route", name, f"over-served: {len(done)} landed on {route.model}, median "
                        f"{touched} file(s) touched in {round(hours, 2)}h — a cheaper route may do"))
    return out, agg


def _allow_covers(rule, cmd):
    """Whether a permission allow rule (`Bash`, `Bash(prefix:*)`, `Bash(glob*)`, `Bash(exact)`)
    covers a shell command."""
    if rule.strip() == "Bash":
        return True
    m = re.fullmatch(r"\s*Bash\((.*)\)\s*", rule)
    if not m:
        return False
    pat = m.group(1).strip()
    if pat.endswith(":*"):
        return cmd.startswith(pat[:-2])
    if "*" in pat:
        return fnmatch.fnmatchcase(cmd, pat)
    return cmd == pat


def _claude_config_dir():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")


def _audit_permissions():
    """The script and each verify command, when no allow rule in the project or user settings
    covers it."""
    rules = []
    for path in (os.path.join(main_tree(), ".claude", "settings.json"),
                 os.path.join(main_tree(), ".claude", "settings.local.json"),
                 os.path.join(_claude_config_dir(), "settings.json")):
        perms = _read_json(path).get("permissions")
        allow = perms.get("allow") if isinstance(perms, dict) else None
        rules += [r for r in allow or [] if isinstance(r, str)]
    wanted = [("python3 .claude/todo-lock.py", "python3 .claude/todo-lock.py next")]
    cfg = _verify_cfg()
    if cfg:
        wanted += [(run.split("{target}")[0].strip()[:80], run.replace("{target}", "x"))
                   for run, _t in cfg[0].values()]
    return [("permissions", shown, "no allow rule in the project or user settings covers it — "
             "every call prompts") for shown, probe in dict(wanted).items()
            if not any(_allow_covers(r, probe) for r in rules)]


def _session_dirs():
    """This repo's Claude Code transcript directories: `<config>/projects/<slug>` for the main tree
    and its `.claude/worktrees/*` sessions, where the slug is the real path with every
    non-alphanumeric character turned into `-` (Claude Code's scheme as of 2026-09)."""
    root = os.path.join(_claude_config_dir(), "projects")
    slug = re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(main_tree()))
    try:
        names = os.listdir(root)
    except OSError:
        return root, slug, []
    return root, slug, sorted(os.path.join(root, n) for n in names
                              if n == slug or n.startswith(slug + "--claude-worktrees-"))


def _audit_sessions():
    """(findings, input lines) from the newest AUDIT_SESSIONS transcripts: token totals per session
    and shell commands that failed repeatedly; plus build/test recipes kept only in memory notes.
    Tolerant of schema drift: an unreadable line or unexpected shape is skipped."""
    root, slug, dirs = _session_dirs()
    if not dirs:
        return [], [f"sessions: none found under {root}/{slug}* (optional input)"]
    files = sorted((p for d in dirs for p in glob.glob(os.path.join(d, "*.jsonl"))),
                   key=lambda p: os.path.getmtime(p), reverse=True)[:AUDIT_SESSIONS]
    totals, fails, calls = {}, {}, 0
    for path in files:
        commands, tokens, cached = {}, 0, 0
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                        msg = rec.get("message") or {}
                        content = msg.get("content")
                        usage = msg.get("usage") if rec.get("type") == "assistant" else None
                    except (ValueError, AttributeError):
                        continue
                    if isinstance(usage, dict):
                        for k, v in usage.items():
                            if k.endswith("_tokens") and isinstance(v, int):
                                if k == "cache_read_input_tokens":
                                    cached += v
                                else:
                                    tokens += v
                    for block in content if isinstance(content, list) else []:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "tool_use" and block.get("name") == "Bash":
                            cmd = (block.get("input") or {}).get("command")
                            if isinstance(cmd, str):
                                commands[block.get("id")] = " ".join(cmd.split())
                                calls += 1
                        elif block.get("type") == "tool_result" and block.get("is_error"):
                            cmd = commands.get(block.get("tool_use_id"))
                            if cmd:
                                fails[cmd] = fails.get(cmd, 0) + 1
        except OSError:
            continue
        totals[os.path.basename(path)[:8]] = (tokens, cached)
    out = [("repeat-failure", cmd[:80], f"failed {n} times across sessions")
           for cmd, n in sorted(fails.items(), key=lambda kv: -kv[1]) if n >= AUDIT_REPEAT_FAILS][:5]
    top = sorted(totals.items(), key=lambda kv: -kv[1][0])[:3]
    med = lambda i: round(_median([t[i] for t in totals.values()]) or 0)  # noqa: E731
    inputs = [f"sessions: {len(totals)} read ({root}/{slug}*); per session median {med(0)} tokens "
              f"(input, cache writes, output) + {med(1)} cache reads; top: "
              f"{', '.join(f'{s} {t[0]}' for s, t in top) or 'n/a'}; {calls} shell call(s), "
              f"{sum(fails.values())} failed"]
    if not _verify_cfg():
        for note in sorted(glob.glob(os.path.join(root, slug, "memory", "*.md"))):
            try:
                with open(note, encoding="utf-8", errors="replace") as f:
                    m = AUDIT_RECIPE_RE.search(f.read())
            except OSError:
                continue
            if m:
                out.append(("verify-in-memory", os.path.basename(note),
                            f"names `{m.group(0)}` — a recipe only this machine's memory knows"))
    return out, inputs


def cmd_audit(argv):
    """The evidence `/optimize` reasons over — see the usage docs."""
    ap = _ArgParser(prog="todo-lock.py audit", add_help=False)
    ap.add_argument("--sessions", action="store_true")
    ap.add_argument("--json", action="store_true")
    opts = ap.parse_args(argv)
    findings = _audit_long_docs() + _audit_claude_md() + _audit_verify()
    findings += _audit_phantom_overlaps()
    big, sizes = _audit_bodies()
    records, _skipped = _read_metrics()
    tel, agg = _audit_telemetry(records)
    findings += big + tel + _audit_permissions()
    overlays = [c + ".md" for c in OVERLAY_COMMANDS if _overlay_committed(c) is not None]
    o = agg["outcomes"]
    inputs = [
        "config keys: " + (", ".join(sorted(_config())) or "none"),
        "overlay: " + (", ".join(overlays) or "none"),
        f"store: {len(sizes)} open item(s), median body "
        f"{round(_median([s for s, _i in sizes]) or 0)} bytes",
        (f"telemetry: {agg['records']} record(s) — landed {o.get('landed', 0)}, released "
         f"{o.get('released', 0)}, bounced {o.get('bounced', 0)}; overlap note at claim "
         f"{sum(bool(r.get('overlap_note')) for r in records)}; declared-files recall "
         f"{agg['declared_files']['recall']}, precision {agg['declared_files']['precision']}")
        if records else "telemetry: no records (`stats`)",
        "worktree_setup: " + ("set" if _config().get("worktree_setup") else "unset"),
        "hooks: " + (", ".join(e for e in HOOK_EVENTS if _hook_cmd(e)) or "unset"),
    ]
    if opts.sessions:
        more, lines = _audit_sessions()
        findings += more
        inputs += lines
    if opts.json:
        print(json.dumps({"findings": [dict(zip(("check", "subject", "evidence"), f))
                                       for f in findings], "inputs": inputs}, indent=2))
        return 0
    for check, subject, evidence in findings:
        print(f"FINDING {check} {subject}: {evidence}")
    if not findings:
        print("NO FINDINGS")
    print("INPUTS")
    for ln in inputs:
        print("  " + ln)
    return 0


def _config_path_parts(dotted):
    parts = dotted.split(".")
    if parts[0] not in CONFIG_KEYS or not all(parts):
        return None
    return parts


def _config_cmd_set(argv, unset=False):
    prog = "todo-lock.py config " + ("unset" if unset else "set")
    ap = _ArgParser(prog=prog, add_help=False)
    ap.add_argument("key")
    if not unset:
        ap.add_argument("value")
    _add_commit_flags(ap)
    opts = ap.parse_args(argv)
    parts = _config_path_parts(opts.key)
    if parts is None:
        print(f"ERROR — unknown config key {opts.key!r} (top level must be one of "
              f"{', '.join(CONFIG_KEYS)}; see `help config`). Nothing was written.")
        return 2
    if not unset:
        try:
            value = json.loads(opts.value)
        except ValueError as e:
            print(f"ERROR — the value must be JSON ({e}); a string is quoted: '\"text\"'. "
                  "Nothing was written.")
            return 2
    if not opts.commit and _in_linked_worktree():
        print(f"REFUSED — the config lives in the main checkout ({main_tree()}); from this "
              "worktree it would be left uncommitted there. Re-run with --commit. Nothing was "
              "written.")
        return 2

    def apply(cfg):
        node = cfg
        for p in parts[:-1]:
            if p not in node and not unset:
                node[p] = {}
            node = node.get(p)
            if not isinstance(node, dict):
                return ("same", f"{opts.key} is not set") if unset and node is None else (
                    "error", f"{p} in {opts.key} is not an object")
        last = parts[-1]
        if unset:
            if last not in node:
                return "same", f"{opts.key} is not set"
            del node[last]
        else:
            if node.get(last, object()) == value:
                return "same", f"{opts.key} already {json.dumps(value, ensure_ascii=False)}"
            node[last] = value
        if parts[0] == "routing":
            try:
                _build_routing(cfg.get("routing"))
            except RoutingConfigError as e:
                return "error", f"`routing` would be malformed: {e}"
        if parts[0] == "hooks":
            problems = _hooks_problems(cfg.get("hooks"))
            if problems:
                return "error", f"`hooks` would be malformed: {'; '.join(problems)}"
        if parts[0] == "inherit_bullets":
            problems = _inherit_problems(cfg.get("inherit_bullets"))
            if problems:
                return "error", f"`inherit_bullets` would be malformed: {'; '.join(problems)}"
        return "write", None

    verb = "Unset" if unset else "Set"
    rc, sha, note = _config_update(apply, opts.commit, opts.message or f"{verb} config {opts.key}")
    if rc is not None:
        return rc
    print(f"OK {'unset ' + opts.key if unset else f'set {opts.key} = {opts.value}'} in "
          f"{CONFIG_REL}" + ("" if opts.commit else " (uncommitted — `--commit` writes and commits)"))
    if note:
        print(note)
    if sha:
        print(f"OK committed {sha} on main ({CONFIG_REL})")
    return 0


def cmd_config(argv):
    if argv and argv[0] in ("set", "unset"):
        return _config_cmd_set(argv[1:], unset=argv[0] == "unset")
    if argv and argv[0] != "show":
        print("ERROR — usage: todo-lock.py config show|set|unset … (see `help config`)")
        return 2
    print(json.dumps(_config(), indent=2, ensure_ascii=False))
    return 0


# @fragment 72_stack.py
# ---------------------------------------------------------------------------
# Toolchain setup — what `/stack` detects and writes. `stack detect` reads the
# repo deterministically (manifests, lockfiles, CI workflows as ground truth for
# the real commands) and prints candidates; the model only runs them and writes
# prose. Every writer targets the main checkout's own files — config, settings,
# a marked block in CLAUDE.md / .worktreeinclude, the overlay — never a shipped
# file, and merges rather than rewrites, so a second run changes nothing and
# human edits outside a marked block survive.
# ---------------------------------------------------------------------------

# basename -> language, for the manifests `detect` recognises.
STACK_MANIFESTS = {
    "package.json": "javascript", "pyproject.toml": "python", "setup.py": "python",
    "requirements.txt": "python", "Pipfile": "python", "go.mod": "go", "Cargo.toml": "rust",
    "Gemfile": "ruby", "pom.xml": "java", "build.gradle": "java", "build.gradle.kts": "kotlin",
    "composer.json": "php", "mix.exs": "elixir", "Package.swift": "swift",
}
# lockfile -> (package manager, install command), in precedence order per language.
STACK_LOCKS = [
    ("pnpm-lock.yaml", "pnpm", "pnpm install --frozen-lockfile"),
    ("yarn.lock", "yarn", "yarn install --frozen-lockfile"),
    ("bun.lockb", "bun", "bun install --frozen-lockfile"),
    ("bun.lock", "bun", "bun install --frozen-lockfile"),
    ("package-lock.json", "npm", "npm ci"),
    ("uv.lock", "uv", "uv sync"),
    ("poetry.lock", "poetry", "poetry install"),
    ("pdm.lock", "pdm", "pdm install"),
    ("Pipfile.lock", "pipenv", "pipenv sync --dev"),
    ("go.sum", "go", "go mod download"),
    ("Cargo.lock", "cargo", "cargo fetch"),
    ("Gemfile.lock", "bundler", "bundle install"),
    ("composer.lock", "composer", "composer install"),
    ("mix.lock", "mix", "mix deps.get"),
]
STACK_LOCK_LANG = {"pnpm": "javascript", "yarn": "javascript", "bun": "javascript",
                   "npm": "javascript", "uv": "python", "poetry": "python", "pdm": "python",
                   "pipenv": "python", "go": "go", "cargo": "rust", "bundler": "ruby",
                   "composer": "php", "mix": "elixir"}
STACK_DEFAULT_PM = {"javascript": "npm", "python": "pip", "go": "go", "rust": "cargo",
                    "ruby": "bundler", "php": "composer", "elixir": "mix", "swift": "swiftpm"}
STACK_KINDS = ("test", "lint", "build", "format", "setup")
STACK_MAX_DEPTH = 3
# CI lines that prepare the machine rather than check the code: never a verify candidate.
STACK_SETUP_RE = re.compile(
    r"^(npm (ci|install|i)\b|yarn( install)?\s*$|yarn install|pnpm (i|install)\b|bun install|"
    r"(python3? -m )?pip3? install|poetry install|uv (sync|pip install)|pipenv (install|sync)|"
    r"pdm install|go mod (download|tidy)|go install|bundle install|composer install|cargo fetch|"
    r"cargo install|rustup|mix deps\.get|(sudo )?apt(-get)? |brew |sudo |cd \S+\s*$|echo |"
    r"export |mkdir |cp |mv |rm |curl |wget |git |chmod |source |\. )")
STACK_LINT_RE = re.compile(
    r"\b(lint|eslint|ruff check|flake8|pylint|mypy|pyright|golangci-lint|go vet|clippy|"
    r"fmt --check|fmt -- --check|--check|gofmt -l|rubocop|typecheck|type-check|tsc --noemit|"
    r"stylelint|shellcheck|vet)\b")
STACK_TEST_RE = re.compile(
    r"\b(test|tests|pytest|jest|vitest|mocha|tox|nox|unittest|rspec|phpunit|ctest)\b")
STACK_BUILD_RE = re.compile(r"\b(build|compile|tsc|webpack|assemble|package)\b")
STACK_SCRIPT_KINDS = {"test": "test", "lint": "lint", "typecheck": "lint", "type-check": "lint",
                      "check-types": "lint", "build": "build"}
STACK_MAKE_KINDS = {"test": "test", "check": "test", "lint": "lint", "build": "build"}
STACK_PROTECT = ("db/migrate", "alembic/versions", "migrations", "__generated__", "generated")
STACK_MARK_RE = re.compile(r"^\s*(<!--|#) (BEGIN|END) claude-todo: [\w-]+( -->)?\s*$")
STACK_BLOCK_FILES = ("CLAUDE.md", ".claude/CLAUDE.md", ".worktreeinclude")
SETTINGS_REL = ".claude/settings.json"
# README's "never touch the store" hook, verbatim: `stack settings --store-guard` writes exactly
# this, so a repo that copied it by hand already counts as configured.
STORE_GUARD_HOOK = (
    "python3 -c \"import json,os,sys; p=json.load(sys.stdin).get('tool_input',{})"
    ".get('file_path',''); os.path.basename(p)=='TODO.local.md' and print(json.dumps("
    "{'hookSpecificOutput':{'hookEventName':'PreToolUse','permissionDecision':'deny',"
    "'permissionDecisionReason':'Use .claude/todo-lock.py; run /repair if the store is "
    "malformed.'}}))\"")
STACK_EDIT_MATCHER = "Edit|MultiEdit|Write"


def _marker_pair(name, rel):
    """The BEGIN/END lines of a marked block: an HTML comment in markdown, `#` elsewhere
    (.worktreeinclude uses .gitignore syntax)."""
    if rel.endswith(".md"):
        return (f"<!-- BEGIN claude-todo: {name} -->", f"<!-- END claude-todo: {name} -->")
    return (f"# BEGIN claude-todo: {name}", f"# END claude-todo: {name}")


def _marker_merge(text, name, body, rel):
    """`text` with the marked block `name` set to `body`: replaced in place when present, appended
    after a blank line when absent. Nothing outside the markers changes, which is what makes a
    re-run idempotent and leaves human edits alone. Returns (new text, error)."""
    begin, end = _marker_pair(name, rel)
    block = [begin] + ([body.strip("\n")] if body.strip() else []) + [end]
    lines = (text or "").split("\n")
    starts = [i for i, ln in enumerate(lines) if ln.strip() == begin]
    ends = [i for i, ln in enumerate(lines) if ln.strip() == end]
    if len(starts) > 1 or len(ends) > 1 or len(starts) != len(ends) or (
            starts and ends[0] < starts[0]):
        return None, (f"{rel} has unbalanced or repeated `claude-todo: {name}` markers; fix them "
                      "by hand first")
    if starts:
        new = lines[:starts[0]] + "\n".join(block).split("\n") + lines[ends[0] + 1:]
        return "\n".join(new), None
    head = (text or "").rstrip("\n")
    return (head + "\n\n" if head else "") + "\n".join(block) + "\n", None


def _marker_body(text, name, rel):
    """The body of marked block `name` in `text`, or None when there is no such block."""
    begin, end = _marker_pair(name, rel)
    lines = (text or "").split("\n")
    try:
        b = [ln.strip() for ln in lines].index(begin)
        e = [ln.strip() for ln in lines].index(end, b)
    except ValueError:
        return None
    return "\n".join(lines[b + 1:e])


def _stack_read(root, rel):
    try:
        with open(os.path.join(root, rel), encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def _stack_ci_commands(root, files):
    """[(command, source)] from CI workflow files, in file and line order: GitHub Actions `run:`
    steps (inline or `|`/`>` blocks) and GitLab `script:` lists. Line-based, no YAML library —
    enough for the shapes CI files use; a step with a `${{ … }}` expression isn't runnable
    locally and is skipped."""
    ci = sorted(p for p in files if (p.startswith(".github/workflows/")
                                     and p.endswith((".yml", ".yaml"))) or p == ".gitlab-ci.yml")
    out = []
    for rel in ci:
        text = _stack_read(root, rel)
        if text is None:
            continue
        key = re.compile(r"^(\s*)(?:-\s+)?(run|script):\s*(.*?)\s*$" if rel == ".gitlab-ci.yml"
                         else r"^(\s*)(?:-\s+)?(run):\s*(.*?)\s*$")
        lines = text.split("\n")
        i = 0
        while i < len(lines):
            m = key.match(lines[i])
            i += 1
            if not m:
                continue
            indent, value = len(m.group(1)), m.group(3)
            found = []
            if value and value[0] in "|>":
                while i < len(lines) and (not lines[i].strip()
                                          or len(lines[i]) - len(lines[i].lstrip()) > indent):
                    found.append((lines[i].strip(), i + 1))
                    i += 1
            elif value:
                found.append((value, i))
            else:  # a YAML list under `script:`
                while i < len(lines) and (not lines[i].strip() or
                                          (len(lines[i]) - len(lines[i].lstrip()) >= indent
                                           and lines[i].lstrip().startswith("- "))):
                    found.append((lines[i].strip()[2:].strip(), i + 1))
                    i += 1
            joined, start = "", None
            for cmd, n in found:
                cmd = cmd.strip().strip("'\"") if not joined else cmd
                if not cmd or cmd.startswith("#"):
                    continue
                start = start or n
                if cmd.endswith("\\"):
                    joined += cmd[:-1].strip() + " "
                    continue
                cmd, joined = (joined + cmd).strip(), ""
                if "${{" not in cmd:
                    out.append((cmd, f"ci:{rel}:{start}"))
                start = None
    return out


def _stack_kind(cmd):
    """Which verify kind a CI command is, or None for a setup line or anything unrecognised."""
    c = cmd.lower()
    if STACK_SETUP_RE.match(c):
        return None
    for kind, rx in (("lint", STACK_LINT_RE), ("test", STACK_TEST_RE), ("build", STACK_BUILD_RE)):
        if rx.search(c):
            return kind
    return None


def _stack_in(d, cmd):
    return cmd if d == "." else f"cd {shlex.quote(d)} && {cmd}"


def _stack_py_prefix(pm):
    return {"uv": "uv run ", "poetry": "poetry run ", "pdm": "pdm run ",
            "pipenv": "pipenv run "}.get(pm, "")


def _stack_js_run(pm, script):
    if pm == "npm":
        return "npm test" if script == "test" else f"npm run {script}"
    return f"bun run {script}" if pm == "bun" else f"{pm} {script}"


def _stack_scan(root):
    """Everything `stack detect` reports, as a dict — see the `stack detect` usage text."""
    files = _seq_repo_files(root)
    fileset = set(files)
    dirs = {}  # manifest dir -> {basename, …}
    for rel in files:
        d, base = os.path.dirname(rel) or ".", os.path.basename(rel)
        if d != "." and (len(d.split("/")) > STACK_MAX_DEPTH or d.startswith(".claude/")):
            continue
        if base in STACK_MANIFESTS or base in {lk for lk, _pm, _i in STACK_LOCKS}:
            dirs.setdefault(d, set()).add(base)
    langs, setups = [], []
    for d in sorted(dirs, key=lambda x: (x != ".", x)):
        names = dirs[d]
        found = {}  # language -> (pm, install)
        for lk, pm, install in STACK_LOCKS:
            if lk in names and STACK_LOCK_LANG[pm] not in found:
                found[STACK_LOCK_LANG[pm]] = (pm, install)
        for base in sorted(names):
            lang = STACK_MANIFESTS.get(base)
            if lang and lang not in found:
                # A workspace member without its own lockfile uses the root's package manager.
                pm = next((p for lg, p, dd in langs if lg == lang and dd == "."),
                          STACK_DEFAULT_PM.get(lang, ""))
                if lang == "java":
                    pm = "maven" if base == "pom.xml" else "gradle"
                install = "pip install -r requirements.txt" if base == "requirements.txt" else None
                found[lang] = (pm, install)
        for lang, (pm, install) in sorted(found.items()):
            if any(STACK_MANIFESTS.get(b) == lang for b in names):  # a lockfile alone isn't one
                langs.append((lang, pm, d))
                if install:
                    setups.append((_stack_in(d, install), f"lockfile:{d}"))
    monorepo = []
    pkg = _stack_read(root, "package.json")
    if pkg:
        try:
            ws = json.loads(pkg).get("workspaces")
        except (ValueError, AttributeError):
            ws = None
        if isinstance(ws, dict):
            ws = ws.get("packages")
        if isinstance(ws, list) and ws:
            monorepo.append("package.json workspaces: " + ", ".join(str(w) for w in ws))
    for marker, label in (("pnpm-workspace.yaml", "pnpm-workspace.yaml"), ("go.work", "go.work"),
                          ("lerna.json", "lerna.json"), ("nx.json", "nx.json"),
                          ("turbo.json", "turbo.json")):
        if marker in fileset:
            monorepo.append(label)
    cargo = _stack_read(root, "Cargo.toml")
    if cargo and re.search(r"^\[workspace\]", cargo, re.M):
        monorepo.append("Cargo [workspace]")
    lang_dirs = sorted({d for _l, _p, d in langs})
    if len(lang_dirs) > 1:
        monorepo.append(f"{len(lang_dirs)} manifest dirs: " + ", ".join(lang_dirs))

    cands, covered = [], set()  # (kind, cmd, source, exts); covered: (dir, kind)

    def add(kind, cmd, source, d=".", exts=""):
        if any(c[1] == cmd for c in cands):
            return
        cands.append((kind, cmd, source, exts))
        covered.add((d, kind))

    for cmd, source in _stack_ci_commands(root, files):
        kind = _stack_kind(cmd)
        if kind:
            add(kind, cmd, source)
    by_dir = {}
    for lang, pm, d in langs:
        by_dir.setdefault(d, []).append((lang, pm))
    for d in sorted(by_dir, key=lambda x: (x != ".", x)):
        at = (lambda n: n) if d == "." else (lambda n, d=d: f"{d}/{n}")
        for lang, pm in by_dir[d]:
            if lang != "javascript":
                continue
            try:
                scripts = json.loads(_stack_read(root, at("package.json")) or "{}").get("scripts")
            except (ValueError, AttributeError):
                scripts = None
            for name, body in (scripts or {}).items():
                kind = STACK_SCRIPT_KINDS.get(name)
                if kind and isinstance(body, str) and "no test specified" not in body:
                    add(kind, _stack_in(d, _stack_js_run(pm, name)),
                        f"{at('package.json')}:scripts.{name}", d)
        make = _stack_read(root, at("Makefile"))
        if make:
            for t in re.findall(r"^([A-Za-z][\w.-]*)\s*:(?!=)", make, re.M):
                if t in STACK_MAKE_KINDS:
                    add(STACK_MAKE_KINDS[t], _stack_in(d, f"make {t}"), f"{at('Makefile')}:{t}", d)
        for lang, pm in by_dir[d]:
            for kind, cmd in _stack_defaults(root, d, lang, pm, fileset):
                if (d, kind) not in covered:
                    add(kind, _stack_in(d, cmd), f"default:{lang}", d)
            fmt = _stack_formatter(root, d, lang, pm, fileset)
            if fmt:
                add("format", _stack_in(d, fmt[0]), fmt[2], d, fmt[1])
    for cmd, source in setups:
        add("setup", cmd, source)

    ignored = _git("-C", root, "ls-files", "-z", "--others", "--ignored", "--exclude-standard",
                   "--directory").split("\0")
    include = sorted(p for p in ignored if p and not p.endswith("/")
                     and len(p.split("/")) <= STACK_MAX_DEPTH
                     and re.fullmatch(r"\.env(\..+)?", os.path.basename(p))
                     and not p.endswith((".example", ".sample", ".template")))
    protect = set()
    for rel in files:
        parts = rel.split("/")[:-1]
        for pat in STACK_PROTECT:
            pp = pat.split("/")
            for i in range(len(parts) - len(pp) + 1):
                if parts[i:i + len(pp)] == pp:
                    protect.add("/".join(parts[:i + len(pp)]) + "/")
                    break
            else:
                continue
            break
    protect = sorted(p for p in protect if not any(p != q and p.startswith(q) for q in protect))
    caveats = []
    # An editable install from the main checkout makes a worktree's test run import main's code.
    installed = (any(os.path.isdir(os.path.join(root, v)) for v in (".venv", "venv"))
                 or any(n.endswith(".egg-info") for n in _stack_listdir(root)))
    if {"pyproject.toml", "setup.py"} & fileset and installed:
        caveats.append("python-editable")
    return {"langs": langs, "monorepo": monorepo, "cands": cands, "include": include,
            "protect": protect[:10], "caveats": caveats}


def _stack_listdir(root):
    try:
        return os.listdir(root)
    except OSError:
        return []


def _stack_defaults(root, d, lang, pm, fileset):
    """[(kind, command)] a language implies when nothing more specific (CI, a script, a Makefile
    target) names that kind."""
    at = (lambda n: n) if d == "." else (lambda n: f"{d}/{n}")
    if lang == "go":
        return [("test", "go test ./..."), ("lint", "go vet ./..."), ("build", "go build ./...")]
    if lang == "rust":
        return [("test", "cargo test"), ("lint", "cargo clippy"), ("build", "cargo build")]
    if lang == "python":
        pre = _stack_py_prefix(pm)
        cfg = "\n".join(_stack_read(root, at(n)) or "" for n in
                        ("pyproject.toml", "setup.cfg", "tox.ini", "requirements.txt",
                         "requirements-dev.txt"))
        out = []
        if "pytest" in cfg or at("conftest.py") in fileset or at("pytest.ini") in fileset:
            out.append(("test", f"{pre}pytest" if pre else "python3 -m pytest"))
        elif any(p.startswith(at("tests/test_")) and p.endswith(".py") for p in fileset):
            out.append(("test", f"{pre}python3 -m unittest discover -s tests"))
        if "[tool.ruff" in cfg or at("ruff.toml") in fileset or at(".ruff.toml") in fileset:
            out.append(("lint", f"{pre}ruff check ."))
        elif "[flake8]" in cfg or at(".flake8") in fileset:
            out.append(("lint", f"{pre}flake8"))
        return out
    if lang == "ruby":
        out = []
        if any(p.startswith(at("spec/")) for p in fileset):
            out.append(("test", "bundle exec rspec"))
        if at(".rubocop.yml") in fileset:
            out.append(("lint", "bundle exec rubocop"))
        return out
    if lang in ("java", "kotlin"):
        if pm == "maven":
            return [("test", "mvn -q test")]
        tool = "./gradlew" if at("gradlew") in fileset else "gradle"
        return [("test", f"{tool} test"), ("build", f"{tool} build")]
    return []


def _stack_formatter(root, d, lang, pm, fileset):
    """(command with {file}, extensions, source) for the formatter this language is set up
    with, or None. A formatter is proposed only where the project shows it uses one (gofmt and
    rustfmt ship with their toolchains)."""
    at = (lambda n: n) if d == "." else (lambda n: f"{d}/{n}")
    if lang == "go":
        return ("gofmt -w {file}", ".go", "default:go")
    if lang == "rust":
        return ("rustfmt {file}", ".rs", "default:rust")
    if lang == "python":
        cfg = _stack_read(root, at("pyproject.toml")) or ""
        pre = _stack_py_prefix(pm)
        if "[tool.ruff" in cfg or at("ruff.toml") in fileset or at(".ruff.toml") in fileset:
            return (f"{pre}ruff format {{file}}", ".py", f"{at('pyproject.toml')}:ruff")
        if "[tool.black" in cfg:
            return (f"{pre}black -q {{file}}", ".py", f"{at('pyproject.toml')}:black")
        return None
    if lang == "javascript":
        pkg = _stack_read(root, at("package.json")) or ""
        conf = [p for p in fileset if os.path.dirname(p) == ("" if d == "." else d)
                and re.match(r"(\.prettierrc|prettier\.config\.)", os.path.basename(p))]
        if conf or re.search(r'"prettier"\s*:', pkg):
            run = {"pnpm": "pnpm exec prettier", "yarn": "yarn prettier",
                   "bun": "bunx prettier"}.get(pm, "npx prettier")
            return (f"{run} --write {{file}}", ".js,.jsx,.ts,.tsx,.mjs,.cjs,.css,.scss,.json",
                    conf[0] if conf else f"{at('package.json')}:prettier")
    return None


def _stack_settings(root):
    data = _read_json(os.path.join(root, SETTINGS_REL))
    return data if isinstance(data, dict) else {}


def _stack_hook_commands(settings):
    """Every hook command string in a settings object, for idempotency checks."""
    out = set()
    hooks = settings.get("hooks")
    for groups in (hooks.values() if isinstance(hooks, dict) else []):
        for g in (groups if isinstance(groups, list) else []):
            for h in (g.get("hooks") if isinstance(g, dict) and isinstance(g.get("hooks"), list)
                      else []):
                if isinstance(h, dict) and isinstance(h.get("command"), str):
                    out.add(h["command"])
    return out


def _stack_format_hook(cmd, exts):
    """The PostToolUse command that runs `cmd` on an edited file with one of `exts`. Built here,
    not by the model, so the same inputs give the same bytes and a re-run finds it present. The
    formatter's output is swallowed and its exit status ignored: a hook that formats must never
    block or clutter an edit."""
    tup = tuple(e if e.startswith(".") else "." + e for e in exts)
    return ("python3 -c \"import json,shlex,subprocess,sys; p=json.load(sys.stdin)"
            ".get('tool_input',{}).get('file_path',''); p.endswith(" + repr(tup) + ") and "
            "subprocess.run(" + repr(cmd) + ".replace('{file}',shlex.quote(p)),shell=True,"
            "capture_output=True)\"")


def _stack_configured(root):
    """What `/stack` already set up here, as short labels, plus the verify recipes and hook
    commands so `detect` can mark candidates already recorded."""
    labels, runs = [], set()
    cfg = _verify_cfg()
    if cfg:
        labels.append("verify(" + ",".join(cfg[0]) + ")")
        runs = {run for run, _t in cfg[0].values()}
    if _config().get("worktree_setup"):
        labels.append("worktree_setup")
    for rel in STACK_BLOCK_FILES:
        if _marker_body(_stack_read(root, rel), "stack", rel) is not None:
            labels.append(f"block({rel})")
    ov = f"{OVERLAY_DIR}/plan-todo.md"
    if _marker_body(_stack_read(root, ov), "stack", ov) is not None:
        labels.append("overlay(plan-todo)")
    settings = _stack_settings(root)
    hooks = _stack_hook_commands(settings)
    if STORE_GUARD_HOOK in hooks:
        labels.append("store-guard")
    perms = settings.get("permissions") if isinstance(settings.get("permissions"), dict) else {}
    for key in ("allow", "deny"):
        n = len(perms.get(key) or []) if isinstance(perms.get(key), list) else 0
        if n:
            labels.append(f"{key}({n})")
    return labels, runs, hooks, perms


def _stack_cmd_detect(argv):
    ap = _ArgParser(prog="todo-lock.py stack detect", add_help=False)
    ap.parse_args(argv)
    root = main_tree()
    scan = _stack_scan(root)
    if not scan["langs"] and not scan["cands"]:
        print("NONE — no manifests, lockfiles or CI workflows found")
        return 1
    labels, runs, hooks, perms = _stack_configured(root)
    shell = os.path.basename(os.environ.get("SHELL", "")) or "sh"
    plat = {"darwin": "darwin"}.get(sys.platform, "linux" if sys.platform.startswith("linux")
                                    else sys.platform)
    print("\t".join(["platform", plat, f"shell={shell}"]
                    + (["sed=bsd"] if plat == "darwin" else [])))
    for lang, pm, d in scan["langs"]:
        print(f"language\t{lang}\t{pm}\t{d}")
    for m in scan["monorepo"]:
        print(f"monorepo\t{m}")
    allowed = set(perms.get("allow") or []) if isinstance(perms.get("allow"), list) else set()
    for kind in STACK_KINDS:
        for k, cmd, source, exts in scan["cands"]:
            if k != kind:
                continue
            done = (cmd in runs if kind in ("test", "lint", "build") else
                    any(_stack_format_hook(cmd, exts.split(",")) == h for h in hooks)
                    if kind == "format" else cmd in str(_config().get("worktree_setup") or ""))
            cols = [kind, cmd] + ([exts] if kind == "format" else []) + [source]
            print("\t".join(cols + (["= configured"] if done else [])))
    for p in scan["include"]:
        print(f"include\t{p}")
    denied = set(perms.get("deny") or []) if isinstance(perms.get("deny"), list) else set()
    for p in scan["protect"]:
        print(f"protect\t{p}" + ("\t= configured" if f"Edit({p}**)" in denied else ""))
    for c in scan["caveats"]:
        print(f"caveat\t{c}")
    print("configured\t" + (", ".join(labels) if labels else "nothing yet"))
    return 0


def _stack_write(rel, render, commit, message):
    """Apply `render(old text or None) -> (new text, error)` to `rel` in the main checkout, the
    way every `/stack` writer does: refused from a linked worktree without --commit, unchanged
    content reports `unchanged` and writes nothing, --commit commits only that file under the
    git mutex. Returns an exit code."""
    if not commit and _in_linked_worktree():
        print(f"REFUSED — {rel} lives in the main checkout ({main_tree()}); from this worktree it "
              "would be left uncommitted there. Re-run with --commit. Nothing was written.")
        return 2
    maintree = main_tree()
    path = os.path.join(maintree, rel)
    note = ""
    with GitMutex() if commit else contextlib.nullcontext():
        if commit:
            ok, note = _commit_precheck(maintree, rel)
            if not ok:
                print(note)
                return 1
        old = _stack_read(maintree, rel)
        new, err = render(old)
        if err:
            print(f"ERROR — {err}. Nothing was written.")
            return 2
        dirty = commit and subprocess.run(
            ["git", "-C", maintree, "status", "--porcelain", "--", rel],
            capture_output=True, text=True).stdout.strip()
        if new == old and not dirty:
            print(f"OK {rel} unchanged")
            return 0
        if new != old:
            os.makedirs(os.path.dirname(path) or maintree, exist_ok=True)
            _atomic_write(path, new)
            _CONFIG_CACHE.clear()
        if not commit:
            print(f"OK wrote {rel}")
            return 0
        sha, err = _commit_store(maintree, rel, message)
    if err:
        print(f"ERROR — {rel} is written but its commit failed: {err}")
        return 1
    print(f"OK committed {rel} ({sha})")
    if note:
        print(note)
    return 0


def _stack_json(old, what):
    """Parse a JSON settings/config file for a merge: (object, error)."""
    try:
        data = json.loads(old) if old and old.strip() else {}
    except ValueError as e:
        return None, f"{what} is not valid JSON ({e}); fix it by hand first"
    if not isinstance(data, dict):
        return None, f"{what} must hold a JSON object"
    return data, None


def _stack_dump(data, old):
    return json.dumps(data, indent=_json_indent(old or ""), ensure_ascii=False) + "\n"


def _stack_verify_merge(cur, new, replace):
    """`cur` verify block with `new` merged in: commands added per name (a different recipe under
    an existing name is refused unless `replace`), flaky and notes unioned, timeout set.
    Returns (block, error)."""
    cur = dict(cur) if isinstance(cur, dict) else {}
    cmds = dict(cur.get("commands") or {}) if isinstance(cur.get("commands"), dict) else {}
    for name, spec in (new.get("commands") or {}).items():
        ok = (isinstance(spec, str) and spec.strip()) or (
            isinstance(spec, dict) and isinstance(spec.get("run"), str) and spec["run"].strip())
        if not ok or not re.fullmatch(r"[\w-]+", name):
            return None, f"verify command {name!r} needs a name of letters/digits/_/- and a run"
        if name in cmds and cmds[name] != spec and not replace:
            return None, (f"verify command {name!r} is already {json.dumps(cmds[name])}; pass "
                          "--replace to overwrite it")
        cmds[name] = spec
    if cmds:
        cur["commands"] = cmds
    for key in ("flaky", "notes"):
        add = [s for s in (new.get(key) or []) if isinstance(s, str) and s]
        if add:
            have = list(cur.get(key) or [])
            cur[key] = have + [s for s in add if s not in have]
    if isinstance(new.get("timeout"), (int, float)) and new["timeout"] > 0:
        cur["timeout"] = new["timeout"]
    return cur, None


def _stack_cmd_config(argv):
    ap = _ArgParser(prog="todo-lock.py stack config", add_help=False,
                                 allow_abbrev=False)
    ap.add_argument("key", choices=("verify", "worktree_setup"))
    ap.add_argument("--json-file", default=None)
    ap.add_argument("--value", default=None)
    ap.add_argument("--replace", action="store_true")
    _add_commit_flags(ap)
    opts = ap.parse_args(argv)
    if opts.key == "verify":
        if not opts.json_file:
            print("ERROR — `stack config verify` needs --json-file <path> (a verify block)")
            return 2
        text, _src, err = _read_payload(opts.json_file)
        new, err = (None, err) if err else _stack_json(text, opts.json_file)
        if err or not isinstance(new.get("commands", {}), dict):
            print(f"ERROR — {err or 'commands must be an object'}")
            return 2
    elif opts.value is None or not opts.value.strip():
        print("ERROR — `stack config worktree_setup` needs --value \"<shell line>\"")
        return 2

    def render(old):
        cfg, err = _stack_json(old, CONFIG_REL)
        if err:
            return None, err
        if opts.key == "verify":
            block, err = _stack_verify_merge(cfg.get("verify"), new, opts.replace)
            if err:
                return None, err
            if block == cfg.get("verify"):
                return old, None
            cfg["verify"] = block
        else:
            cur = cfg.get("worktree_setup")
            if cur == opts.value:
                return old, None
            if cur and not opts.replace:
                return None, (f"worktree_setup is already {json.dumps(cur)}; pass --replace to "
                              "overwrite it")
            cfg["worktree_setup"] = opts.value
        return _stack_dump(cfg, old), None
    return _stack_write(CONFIG_REL, render, opts.commit,
                        opts.message or f"Set {opts.key} in the claude-todo config")


def _stack_cmd_block(argv):
    ap = _ArgParser(prog="todo-lock.py stack block", add_help=False)
    ap.add_argument("file", choices=STACK_BLOCK_FILES)
    _body_file_flag(ap)
    _add_commit_flags(ap)
    opts = ap.parse_args(argv)
    body, _src, err = _read_payload(opts.body_file)
    if err:
        print(f"ERROR — {err}")
        return 2
    return _stack_write(opts.file, lambda old: _marker_merge(old, "stack", body, opts.file),
                        opts.commit, opts.message or f"Set the /stack block in {opts.file}")


def _stack_cmd_settings(argv):
    ap = _ArgParser(prog="todo-lock.py stack settings", add_help=False,
                                 allow_abbrev=False)
    ap.add_argument("--allow", action="append", default=[], metavar="RULE")
    ap.add_argument("--deny", action="append", default=[], metavar="RULE")
    ap.add_argument("--format-hook", default=None, metavar="CMD")
    ap.add_argument("--ext", default=None, metavar=".a,.b")
    ap.add_argument("--store-guard", action="store_true")
    _add_commit_flags(ap)
    opts = ap.parse_args(argv)
    hooks = []  # (event, command, timeout)
    if opts.format_hook is not None:
        if "{file}" not in opts.format_hook or not opts.ext:
            print("ERROR — --format-hook needs a `{file}` placeholder and --ext .a,.b")
            return 2
        if re.search(r"[\"$`\\]", opts.format_hook):
            print("ERROR — --format-hook may not contain \", $, ` or \\ (it is embedded in a "
                  "shell-quoted hook command)")
            return 2
        exts = [e.strip() for e in opts.ext.split(",") if e.strip()]
        hooks.append(("PostToolUse", _stack_format_hook(opts.format_hook, exts), 60))
    if opts.store_guard:
        hooks.append(("PreToolUse", STORE_GUARD_HOOK, None))
    if not (opts.allow or opts.deny or hooks):
        print("ERROR — nothing to write: pass --allow/--deny, --format-hook or --store-guard")
        return 2

    def render(old):
        data, err = _stack_json(old, SETTINGS_REL)
        if err:
            return None, err
        before = json.dumps(data, sort_keys=True)
        for key, rules in (("allow", opts.allow), ("deny", opts.deny)):
            if not rules:
                continue
            perms = data.setdefault("permissions", {})
            if not isinstance(perms, dict) or not isinstance(perms.setdefault(key, []), list):
                return None, f"`permissions.{key}` in {SETTINGS_REL} is not a list"
            perms[key] += [r for r in dict.fromkeys(rules) if r not in perms[key]]
        present = _stack_hook_commands(data)
        for event, command, timeout in hooks:
            if command in present:
                continue
            groups = data.setdefault("hooks", {})
            if not isinstance(groups, dict) or not isinstance(groups.setdefault(event, []), list):
                return None, f"`hooks.{event}` in {SETTINGS_REL} is not a list"
            matcher = "Read|Edit|MultiEdit|Write" if event == "PreToolUse" else STACK_EDIT_MATCHER
            hook = {"type": "command", "command": command}
            if timeout:
                hook["timeout"] = timeout
            groups[event].append({"matcher": matcher, "hooks": [hook]})
        if json.dumps(data, sort_keys=True) == before:
            return old, None
        return _stack_dump(data, old), None
    return _stack_write(SETTINGS_REL, render, opts.commit,
                        opts.message or "Set /stack permissions and hooks")


def cmd_stack(argv):
    subs = {"detect": _stack_cmd_detect, "config": _stack_cmd_config,
            "block": _stack_cmd_block, "settings": _stack_cmd_settings}
    if not argv or argv[0] not in subs:
        print("usage: todo-lock.py stack {detect|config|block|settings} … (see `help stack`)")
        return 2
    return subs[argv[0]](argv[1:])


# @fragment 80_update.py
# ---------------------------------------------------------------------------
# Self-update —"am I running the current claude-todo, and how do I get it?"
#
# The package is versioned by a `VERSION` file at its repo root and released as a `v<x.y.z>` git
# TAG. `install.sh` stamps what it installed into the target repo (`.claude/todo-version.json`), so
# an installed copy knows its own version AND where it came from. The check is `git ls-remote
# --tags <source>`: deliberately git, not the GitHub API — it works on any host (GitHub, GitLab, a
# bare repo over SSH), for public and private repos alike, reusing whatever auth the user's git
# already has (credential helper, `gh`, SSH key). No token, no HTTP client, no API rate limit.
#
# `update` then fetches the winning tag shallowly into a temp dir and runs THAT checkout's
# install.sh against this repo — so updating is exactly a fresh install, and the installer's
# never-clobber rules (TODO.local.md, settings.json) apply unchanged. It also snapshots the claim
# state (`state_path()` and its sidecars) before running the installer and fails loudly if any of
# it is gone or changed afterward — install.sh has no business touching `.git/`, but that's an
# invariant worth verifying, not just assuming.
#
# Trust (docs/update-trust-decision-2026-09-20.md): a release tag is installed only if it is
# SSH-signed by a key in the signers file the PREVIOUS install shipped, still points where this
# machine and the stamp last saw it, and the fetched objects match what `ls-remote` reported. A
# source that came from the committed stamp and differs from the one this machine trusts is never
# contacted — not even by the passive check — until the user confirms it.
# ---------------------------------------------------------------------------

# Where updates come from when the install stamp doesn't say (a hand-copied install, or a stamp
# written before this field existed). `CLAUDE_TODO_UPDATE_SOURCE` overrides everything.
DEFAULT_UPDATE_SOURCE = "https://github.com/lsbarro2026/claude-todo.git"
# How long a cached check result stays fresh. The passive notice never queries the network itself;
# it reads this cache and refreshes it in the background at most once per interval.
UPDATE_CHECK_INTERVAL = 24 * 3600
# A release tag: `v1.2.3` or `1.2.3`. Anything else on the remote (feature tags, `latest`) is
# ignored, so tagging is the explicit act that publishes an update.
VERSION_TAG_RE = re.compile(r"^refs/tags/v?(\d+)\.(\d+)\.(\d+)$")


def _script_dir():
    """The `.claude/` dir this script is running from. In a /plan-todo worktree that's the
    worktree's copy — same content as the main tree's, since both are checkouts of the same
    commit."""
    return os.path.dirname(os.path.abspath(__file__))


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _stamp():
    """The install stamp `install.sh` writes next to this script — {version, source, ref, commit,
    installed_at}. `{}` when absent (files copied by hand, or an install predating stamping)."""
    data = _read_json(os.path.join(_script_dir(), "todo-version.json"))
    if data:
        return data
    try:
        return _read_json(os.path.join(main_tree(), ".claude", "todo-version.json"))
    except Exception:
        return {}


# Files only a claude-todo *package* checkout has. Used to recognise "this is the package repo, not
# an install of it" — the package uses the workflow from its own `.claude/`, so `update` there would
# overwrite the very sources it ships (see cmd_update / install.sh's matching guard).
PACKAGE_MARKERS = ("install.sh", "release.sh", "templates/TODO.local.md")


def _package_root():
    """The root of the claude-todo package checkout this script is running from, or None in a normal
    target repo. Requires BOTH a parseable VERSION and every PACKAGE_MARKERS file, so a host project
    that happens to ship its own `install.sh` or `VERSION` isn't mistaken for the package."""
    root = os.path.dirname(_script_dir())
    if not _package_version_file():
        return None
    if all(os.path.exists(os.path.join(root, *m.split("/"))) for m in PACKAGE_MARKERS):
        return root
    return None


def _package_version_file():
    """The `VERSION` file at the root of a claude-todo *package* checkout, if this script is
    running from one (i.e. `.claude/todo-lock.py` inside the claude-todo repo itself). Absent in a
    target repo, which is exactly how `update_source` tells the two apart."""
    for root in (os.path.dirname(_script_dir()),):
        try:
            with open(os.path.join(root, "VERSION"), encoding="utf-8") as f:
                v = f.read().strip()
        except OSError:
            continue
        if VERSION_RE.match(v):
            return v
    return None


def installed_version():
    """The claude-todo version running here: the install stamp's, else the package checkout's
    VERSION, else None (unknown — an old or hand-made install)."""
    v = _stamp().get("version")
    if v and VERSION_RE.match(v):
        return v
    return _package_version_file()


def _update_source_origin():
    """(source, where it came from): 'env', 'stamp', 'package' or 'default'. Only a 'stamp' source
    can be unconfirmed — the stamp is committed, so a pull request can edit it; the others are set
    by the user on this machine."""
    env = os.environ.get("CLAUDE_TODO_UPDATE_SOURCE")
    if env:
        return env, "env"
    src = _stamp().get("source")
    if src:
        return src, "stamp"
    if _package_version_file():
        # Running inside a checkout of claude-todo itself — its own `origin` IS upstream. In an
        # installed target repo `origin` is the *user's* project, never a source of claude-todo
        # updates, so that case falls through to the published default instead.
        try:
            return _git("remote", "get-url", "origin"), "package"
        except Exception:
            pass
    return DEFAULT_UPDATE_SOURCE, "default"


def update_source():
    """The git URL to check for / pull updates from."""
    return _update_source_origin()[0]


# Machine-local record of what this checkout trusts: {source, pins: {source: {tag: tag-object
# sha}}}. Pins are trust-on-first-sight — added, never rewritten — so a tag that later points
# elsewhere is caught (docs/update-trust-decision-2026-09-20.md).
def _trust_path():
    return os.path.join(_common_dir(), "claude-todo-update-trust.json")


def _same_source(a, b):
    """Two spellings of one remote: trailing `/` and `.git` don't make a different source."""
    norm = lambda s: re.sub(r"(\.git)?/*$", "", (s or "").strip())
    return bool(a) and bool(b) and norm(a) == norm(b)


def _trusted_source():
    return _read_json(_trust_path()).get("source") or DEFAULT_UPDATE_SOURCE


def _record_trust(source=None, pins=None):
    """Trust `source` from now on and/or pin {tag: sha} under the source they were seen on.
    Existing pins are kept as they are — overwriting one would erase the evidence of a moved tag.
    Best-effort, like the cache: a failed write must not fail the command."""
    data = _read_json(_trust_path())
    if source:
        data["source"] = source
    for src, tags in (pins or {}).items():
        known = data.setdefault("pins", {}).setdefault(src, {})
        for tag, sha in tags.items():
            known.setdefault(tag, sha)
    try:
        _atomic_write(_trust_path(), json.dumps(data, indent=2, sort_keys=True) + "\n")
    except OSError:
        pass


def _unconfirmed_source():
    """(source, trusted) when the update source comes from the committed stamp and differs from
    the one this machine trusts, else None."""
    source, origin = _update_source_origin()
    trusted = _trusted_source()
    if origin == "stamp" and not _same_source(source, trusted):
        return source, trusted
    return None


def _confirm_source(source, trusted, accepted):
    """True once the user has confirmed a changed source (`--accept-source`, or a yes at a
    terminal) — and it is then trusted from now on. Non-interactive runs never prompt."""
    if not accepted and sys.stdin.isatty() and sys.stdout.isatty():
        try:
            answer = input(f"The install stamp says to update from {source}, but this machine "
                           f"trusts {trusted}. Trust the new source? [y/N] ")
        except EOFError:
            answer = ""
        accepted = answer.strip().lower() in ("y", "yes")
    if accepted:
        _record_trust(source=source)
    return accepted


def _print_unconfirmed(source, trusted):
    print(f"SOURCE-UNCONFIRMED {source} (trusted: {trusted}) — the committed install stamp names "
          "a different update source than this machine has used. Nothing was fetched. If you "
          "expected the change, re-run with --accept-source; otherwise restore the stamp's "
          "`source`.")


def _signers_file():
    """The release-signing keys the installed copy shipped (`todo-release-signers`, git's
    allowed_signers format), or None when absent or holding no key line."""
    for base in (_script_dir(), os.path.join(main_tree(), ".claude")):
        path = os.path.join(base, "todo-release-signers")
        try:
            with open(path, encoding="utf-8") as f:
                if any(l.strip() and not l.lstrip().startswith("#") for l in f):
                    return path
        except OSError:
            continue
    return None


def _git_error(stderr):
    """The one line of a failed git command worth showing. Git prints the actual cause first and
    then generic advice ('Please make sure you have the correct access rights…'), so take the first
    `fatal:` line, else the first non-empty one."""
    lines = [l.strip() for l in (stderr or "").split("\n") if l.strip()]
    for l in lines:
        if l.startswith("fatal:"):
            return l
    return lines[0] if lines else ""


def _remote_tags(source, timeout=25):
    """{tag: (tag object sha, commit sha)} for every tag on `source` — for a lightweight tag both
    are the commit. Raises RuntimeError if the remote can't be reached (offline, no auth, bad URL)."""
    try:
        out = subprocess.run(["git", "ls-remote", "--tags", "--", source],
                             capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"{exc.__class__.__name__}: {exc}")
    if out.returncode != 0:
        raise RuntimeError(_git_error(out.stderr) or f"git ls-remote exited {out.returncode}")
    tags = {}
    for line in out.stdout.splitlines():
        sha, _, ref = line.partition("\t")
        ref = ref.strip()
        if not ref.startswith("refs/tags/"):
            continue
        name = ref[len("refs/tags/"):]
        if name.endswith("^{}"):                    # the peeled commit of an annotated tag
            name = name[:-3]
            tags[name] = (tags.get(name, (sha, sha))[0], sha.strip())
        else:
            prev = tags.get(name)
            tags[name] = (sha.strip(), prev[1] if prev else sha.strip())
    return tags


def _remote_latest(source, timeout=25):
    """(version, tag, tags) — the highest `v<x.y.z>` tag on `source` (None, None when it has none)
    plus the whole `_remote_tags` map. Raises RuntimeError like `_remote_tags`."""
    tags = _remote_tags(source, timeout)
    best = None
    for name in tags:
        m = VERSION_TAG_RE.match("refs/tags/" + name)
        if m:
            tup = tuple(int(g) for g in m.groups())
            if best is None or tup > best[0]:
                best = (tup, name)
    return (None, None, tags) if best is None else (_fmt_version(best[0]), best[1], tags)


def _release_pins(tags):
    """{tag: tag object sha} for the release tags in a `_remote_tags` map."""
    return {t: shas[0] for t, shas in tags.items() if VERSION_TAG_RE.match("refs/tags/" + t)}


def _moved_tags(source, tags):
    """[(tag, was, now)] for tags on `source` that point somewhere other than where this machine
    pinned them, or — for the installed release — than the commit the install stamp recorded."""
    pins = (_read_json(_trust_path()).get("pins") or {}).get(source) or {}
    moved = []
    for tag, (obj, commit) in sorted(tags.items()):
        if pins.get(tag) and pins[tag] != obj:
            moved.append((tag, pins[tag], obj))
    st = _stamp()
    ref, was = st.get("ref"), st.get("commit")
    if ref in tags and was and _same_source(st.get("source"), source) \
            and was != tags[ref][1] and not any(m[0] == ref for m in moved):
        moved.append((ref, was, tags[ref][1]))
    return moved


def _print_moved(source, moved):
    for tag, was, now in moved:
        print(f"MOVED-TAG {tag} on {source} now points at {now[:12]}, not {was[:12]} as when this "
              "repo last saw it. A published release tag never moves, so this is refused: the "
              "source may be compromised, or the tag was rewritten by hand. Ask the maintainer.")


def _update_cache_path():
    """Machine-local, never committed — same reasoning as the claim state: an update check is a
    property of this checkout on this machine, not of the shared backlog."""
    return os.path.join(_common_dir(), "claude-todo-update-cache.json")


def _read_update_cache():
    return _read_json(_update_cache_path())


def _write_update_cache(**fields):
    """Best-effort cache write: {checked_at, latest, tag, source, error}. Never raises — a failed
    cache write must not break the command the user actually ran."""
    data = {"checked_at": time.time()}
    data.update(fields)
    try:
        _atomic_write(_update_cache_path(), json.dumps(data, indent=2) + "\n")
    except OSError:
        pass


def _update_check_enabled():
    if os.environ.get("CLAUDE_TODO_NO_UPDATE_CHECK"):
        return False
    try:
        return _config().get("update_check", True) is not False
    except Exception:
        return True


def _spawn_background_check():
    """Kick off `check-update --refresh --quiet` detached, so its result is in the cache for a
    later run. Nothing waits on it — the command in progress must never pay for a network round
    trip. The attempt is stamped into the cache FIRST so parallel tabs don't all spawn one."""
    cache = _read_update_cache()
    _write_update_cache(latest=cache.get("latest"), tag=cache.get("tag"),
                        source=cache.get("source"), error=cache.get("error"))
    try:
        subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "check-update", "--refresh", "--quiet"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True, cwd=_script_dir(),
        )
    except Exception:
        pass


def maybe_update_notice():
    """Print a one-line 'a newer claude-todo is out' note under the command's real output.

    Wired into the commands a working tab runs constantly (`next`, `summary`,
    `summary-by-model`), so the news finds the user without them ever asking. Reads only the
    cache — the refresh happens in a detached background process, at most once per
    UPDATE_CHECK_INTERVAL — and swallows every error: an update notice must never change the
    outcome of the command it trails."""
    try:
        if not _update_check_enabled():
            return
        cache = _read_update_cache()
        if time.time() - float(cache.get("checked_at") or 0) > UPDATE_CHECK_INTERVAL:
            _spawn_background_check()
        cur, latest = installed_version(), cache.get("latest")
        if not cur or not latest:
            return
        if _parse_version(latest) > _parse_version(cur):
            print(f"\nnote: claude-todo {latest} is available (you have {cur}) — run /update, or "
                  "`python3 .claude/todo-lock.py update`")
    except Exception:
        return


def cmd_version(_argv):
    """Print what's installed here, where it came from, and the last known upstream version."""
    cur = installed_version()
    st = _stamp()
    print(f"claude-todo {cur or 'unknown (no install stamp and no VERSION file)'}")
    print(f"  source:    {update_source()}")
    unconfirmed = _unconfirmed_source()
    if unconfirmed:
        print(f"  trusted:   {unconfirmed[1]} — the stamp's source is unconfirmed on this machine "
              "(`check-update --accept-source` trusts it)")
    print(f"  signing:   {_signers_file() or 'no release-signing key installed — updates cannot be verified'}")
    if st:
        print(f"  installed: {st.get('ref') or '?'} @ {(st.get('commit') or '?')[:12]}"
              f" on {st.get('installed_at') or '?'}")
    else:
        print("  installed: (no .claude/todo-version.json — copied by hand, or installed before "
              "stamping existed)")
    cache = _read_update_cache()
    if cache.get("latest"):
        when = datetime.fromtimestamp(float(cache.get("checked_at") or 0)).isoformat(timespec="minutes")
        print(f"  upstream:  {cache['latest']} (as of last check, {when})")
    if cache.get("error"):
        print(f"  last check failed: {cache['error']}")
    print("\nRun `check-update` to query the remote now, or `update` to install the latest release.")
    return 0


def cmd_check_update(argv):
    """Is a newer release out? Prints one of UPDATE-AVAILABLE / UP-TO-DATE / CHECK-FAILED."""
    ap = _ArgParser(prog="todo-lock.py check-update", add_help=False)
    ap.add_argument("--refresh", action="store_true",
                    help="query the remote now instead of reusing a cached result <24h old")
    ap.add_argument("--quiet", action="store_true",
                    help="print nothing, just refresh the cache and set the exit code "
                         "(used by the background check)")
    ap.add_argument("--accept-source", action="store_true",
                    help="trust the install stamp's source even though it differs from the one "
                         "this machine trusts")
    opts = ap.parse_args(argv)
    cur = installed_version()
    source = update_source()
    if source.startswith("-"):
        if not opts.quiet:
            print(f"CHECK-FAILED — update source {source!r} starts with '-'; refusing to pass it "
                  "to git.")
        return 1
    unconfirmed = _unconfirmed_source()
    if unconfirmed:
        # The background check lands here too, so a stamp edited in a pull request never makes
        # this machine contact the host it names.
        if opts.quiet or not _confirm_source(*unconfirmed, accepted=opts.accept_source):
            if not opts.quiet:
                _print_unconfirmed(*unconfirmed)
            return 1
    cache = _read_update_cache()
    fresh = (time.time() - float(cache.get("checked_at") or 0)) < UPDATE_CHECK_INTERVAL
    latest, tag = cache.get("latest"), cache.get("tag")
    if opts.refresh or not fresh or not latest or cache.get("source") != source:
        try:
            latest, tag, tags = _remote_latest(source)
        except RuntimeError as exc:
            # Keep the previous known-good `latest` so an offline check doesn't erase the news —
            # but only if it came from THIS source; a version learned from a different remote says
            # nothing about this one.
            same = cache.get("source") == source
            _write_update_cache(latest=cache.get("latest") if same else None,
                                tag=cache.get("tag") if same else None,
                                source=source, error=str(exc))
            if not opts.quiet:
                print(f"CHECK-FAILED — could not reach {source}: {exc}")
                print("  (offline, or the source needs git auth — see README 'Updating')")
            return 1
        moved = _moved_tags(source, tags)
        if moved:
            # No `latest` in the cache: the passive notice must not advertise a release from a
            # source that just failed this check.
            _write_update_cache(latest=None, tag=None, source=source,
                                error=f"moved release tag {moved[0][0]}")
            if not opts.quiet:
                _print_moved(source, moved)
            return 1
        _record_trust(pins={source: _release_pins(tags)})
        _write_update_cache(latest=latest, tag=tag, source=source)
    if latest is None:
        if not opts.quiet:
            print(f"CHECK-FAILED — {source} has no v<x.y.z> release tags yet, so there's nothing "
                  "to compare against (the maintainer publishes releases with release.sh)")
        return 1
    if not opts.quiet:
        if cur is None:
            print(f"UPDATE-AVAILABLE {latest} — this install has no recorded version, so it can't "
                  "be compared; `update` installs the latest release and stamps it")
        elif _parse_version(latest) > _parse_version(cur):
            print(f"UPDATE-AVAILABLE {latest} (installed {cur}) — run /update, or "
                  "`python3 .claude/todo-lock.py update`")
        else:
            print(f"UP-TO-DATE {cur} (latest release on {source} is {latest})")
    return 0


def _changelog_since(pkg_dir, cur):
    """The new release's CHANGELOG sections newer than `cur` — the 'what am I getting' half of an
    update. Sections are `## <x.y.z>` headings (an optional `[x.y.z]` link form is accepted).
    Returns [] when there's no CHANGELOG, no installed version to compare, or nothing newer."""
    try:
        with open(os.path.join(pkg_dir, "CHANGELOG.md"), encoding="utf-8") as f:
            lines = f.read().split("\n")
    except OSError:
        return []
    head_re = re.compile(r"^##\s+\[?(\d+\.\d+\.\d+)\]?")
    out, keeping = [], False
    for line in lines:
        m = head_re.match(line)
        if m:
            try:
                keeping = cur is None or _parse_version(m.group(1)) > _parse_version(cur)
            except ValueError:
                keeping = False
        if keeping:
            out.append(line)
    while out and not out[-1].strip():
        out.pop()
    return out


CHANGELOG_NOTES_MAX_LINES = 40  # `update`'s default "What changed" cap (TOOL-37)


def _format_update_notes(notes, source, ref, full=False):
    """Render `update`'s "What changed" notes. Default: section headings plus the first line of
    each bullet (a wrapped bullet's indented continuation lines are dropped), capped at
    CHANGELOG_NOTES_MAX_LINES lines, with a pointer to the unabridged text — this repo's own
    entries can run long. `--full-notes` (full=True) returns `notes` verbatim, the old behaviour."""
    if full:
        return notes
    out = [line for line in notes
           if line.startswith("##") or line.startswith("- ") or not line.strip()]
    while out and not out[-1].strip():
        out.pop()
    if len(out) > CHANGELOG_NOTES_MAX_LINES:
        out = out[:CHANGELOG_NOTES_MAX_LINES]
        while out and not out[-1].strip():
            out.pop()
    out.append("")
    out.append(f"full notes: CHANGELOG.md in {source} at {ref}")
    return out


def _managed_paths(target):
    """The manifest `install.sh` recorded in `target`'s stamp: the exact repo-relative files the
    package owns and rewrites on every install. None when the stamp has no `managed` list (an
    install predating the manifest, or none at all). Only paths under `.claude/` with no `..`
    segment are kept — the stamp is a committed file, and these paths get staged and overwritten."""
    managed = _read_json(os.path.join(target, ".claude", "todo-version.json")).get("managed")
    if not isinstance(managed, list):
        return None
    return [p for p in managed
            if isinstance(p, str) and p.startswith(".claude/") and ".." not in p.split("/")]


def _dirty_managed(target):
    """Files `update` is about to overwrite that have uncommitted edits in `target` — local
    changes to todo-lock.py, a slash command, or one of the on-demand reference files, which a
    reinstall would silently discard. Reads the install's manifest (`_managed_paths`) as literal
    paths, so a file the package doesn't own — the `.claude/local-todo/` overlay included — never
    blocks an update. Without a manifest it falls back to the pre-manifest set, with `:(glob)` so the
    `todo-*.md` pattern stays at the top level of `.claude/` instead of crossing `/`."""
    managed = _managed_paths(target)
    if managed == []:
        return []
    if managed is not None:
        cmd = ["git", "--literal-pathspecs", "-C", target, "status", "--porcelain", "--", *managed]
    else:
        cmd = ["git", "-C", target, "status", "--porcelain", "--",
               ".claude/todo-lock.py", ".claude/commands", ":(glob).claude/todo-*.md",
               ".claude/todo-release-signers"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [l[3:].strip() for l in out.stdout.splitlines() if l.strip()]


def _commit_update(target, paths, message):
    """Commit exactly `paths` (plus nothing else the user has staged) in `target`, under the git
    mutex so a parallel /finish merge can't race it. Paths that are gone and were never tracked
    are dropped first, so a manifest entry the installer removed stages as a deletion instead of
    failing `git add`. Returns (ok, one-line result)."""
    base = ["git", "--literal-pathspecs", "-C", target]
    with GitMutex():
        tracked = subprocess.run(base + ["ls-files", "-z", "--", *paths],
                                 capture_output=True, text=True)
        known = set(tracked.stdout.split("\0"))
        keep = [p for p in paths if os.path.lexists(os.path.join(target, p)) or p in known]
        for step in (["add", "-A", "--", *keep], ["commit", "-q", "-m", message, "--", *keep]):
            r = subprocess.run(base + step, capture_output=True, text=True)
            if r.returncode != 0:
                return False, _git_error(r.stderr or r.stdout) or f"git {step[0]} failed"
    head = subprocess.run(base + ["log", "-1", "--format=%h %s"], capture_output=True, text=True)
    return True, head.stdout.strip()


def _guarded_state_paths():
    """Paths under .git/ that an `update` must never touch — the claim state and its sidecars.
    install.sh has no business reaching outside <target>/.claude and <target>/TODO.local.md, but
    nothing enforces that; this is the belt-and-suspenders check `cmd_update` runs around its
    clone+install step."""
    base = state_path()
    return [base, base + ".bak", base + ".lock", base + ".store", base + ".gitmutex",
            _update_cache_path(), _trust_path(), metrics_path()]


def _snapshot_guarded_state():
    snap = {}
    for p in _guarded_state_paths():
        try:
            with open(p, "rb") as f:
                snap[p] = f.read()
        except OSError:
            snap[p] = None
    return snap


def _verify_guarded_state(before):
    """Compare a `_snapshot_guarded_state()` result taken before the installer ran against the
    current on-disk contents. Returns a list of problem strings (empty if all clear). The lock
    sidecars (.lock/.store/.gitmutex) are empty scratch files recreated on demand by flock — only
    deletion of those is worth flagging, not content, since they carry no data of their own."""
    problems = []
    for p, prior in before.items():
        if prior is None:
            continue  # didn't exist before either — nothing to lose
        try:
            with open(p, "rb") as f:
                after = f.read()
        except OSError:
            after = None
        if after is None:
            problems.append(f"{p} was deleted")
        elif p == metrics_path():
            # Append-only: a parallel `land` may add a line mid-update; anything else is damage.
            if not after.startswith(prior):
                problems.append(f"{p} was modified")
        elif after != prior and not p.endswith((".lock", ".store", ".gitmutex")):
            problems.append(f"{p} was modified")
    return problems


def cmd_update(argv):
    """Install the latest claude-todo release into this repo: resolve the newest release tag,
    shallow-fetch and verify it, and run that checkout's install.sh against the MAIN worktree (never a
    /plan-todo worktree — an update there would vanish with the worktree)."""
    ap = _ArgParser(prog="todo-lock.py update", add_help=False)
    ap.add_argument("--check", action="store_true", help="just report whether an update exists")
    ap.add_argument("--ref", default=None, metavar="TAG|BRANCH",
                    help="install this ref instead of the latest release tag (e.g. --ref main to "
                         "track the development branch)")
    ap.add_argument("--force", action="store_true",
                    help="reinstall even if already current, and overwrite local edits to the "
                         "package-owned files under .claude/")
    ap.add_argument("--source", default=None, metavar="GIT-URL",
                    help="update from this git URL instead of the recorded source")
    ap.add_argument("--commit", action="store_true",
                    help="commit the update: exactly the old and new manifests plus the stamp, "
                         "under the git mutex")
    ap.add_argument("--accept-source", action="store_true",
                    help="trust the install stamp's source even though it differs from the one "
                         "this machine trusts")
    ap.add_argument("--allow-unsigned", action="store_true",
                    help="install a ref that can't be verified against the release-signing key "
                         "(a branch, an unsigned tag, or an install with no signers file)")
    ap.add_argument("--full-notes", action="store_true",
                    help="print every changelog line for the update instead of the capped summary")
    opts = ap.parse_args(argv)
    # A value beginning with '-' would reach git as an option.
    for flag, value in (("--source", opts.source), ("--ref", opts.ref)):
        if value is not None and value.startswith("-"):
            print(f"ERROR — {flag} {value!r} starts with '-'; refusing to pass it to git. "
                  "Nothing was changed.")
            return 2
    if opts.check:
        return cmd_check_update(["--refresh"] + (["--accept-source"] if opts.accept_source else []))

    # The package repo is not an install of itself: its `.claude/todo-lock.py` + `.claude/skills`
    # are the payload install.sh ships, so installing a release over them would revert unreleased
    # development work. `git pull` is the update path there. (install.sh refuses the same case.)
    pkg_root = _package_root()
    if pkg_root and not opts.force:
        print(f"ERROR — {pkg_root} is the claude-todo package repo itself, not an install of it. "
              "An update here would overwrite the sources it ships with a published release — use "
              "`git pull` instead. Nothing was changed (--force overrides).")
        return 2

    source = opts.source or update_source()
    cur = installed_version()
    target = main_tree()
    if source.startswith("-"):
        print(f"ERROR — update source {source!r} starts with '-'; refusing to pass it to git. "
              "Nothing was changed.")
        return 2
    # An explicit --source is the user's own choice; only a source taken from the committed stamp
    # needs confirming before anything is fetched from it.
    unconfirmed = None if opts.source else _unconfirmed_source()
    if unconfirmed and not _confirm_source(*unconfirmed, accepted=opts.accept_source):
        _print_unconfirmed(*unconfirmed)
        return 2

    # 1. Decide what to install. The remote's tags are read either way: they carry the sha the
    #    fetched objects must match.
    try:
        latest, ref, tags = _remote_latest(source)
    except RuntimeError as exc:
        print(f"ERROR — could not reach {source}: {exc}")
        print("  Check your network, or that git can authenticate to that remote "
              "(see README 'Updating'). `--source <git-url>` overrides where updates come from.")
        return 1
    if opts.ref:
        ref, latest = opts.ref, None
    else:
        if latest is None:
            print(f"ERROR — {source} has no v<x.y.z> release tags to install. "
                  "Use `--ref main` to install the development branch instead.")
            return 1
        _write_update_cache(latest=latest, tag=ref, source=source)
        if cur and _parse_version(latest) <= _parse_version(cur) and not opts.force:
            print(f"UP-TO-DATE {cur} — {source} has nothing newer ({latest}). "
                  "Use --force to reinstall anyway.")
            return 0

    # 1b. Trust (docs/update-trust-decision-2026-09-20.md): the chosen tag must still point where
    #     it was first seen, and must be verifiable against the INSTALLED signers file — checked
    #     here so nothing is fetched when the answer is already no. Other moved tags only warn.
    moved = _moved_tags(source, tags)
    if any(m[0] == ref for m in moved):
        _print_moved(source, [m for m in moved if m[0] == ref])
        print("Nothing was changed.")
        return 2
    for tag, was, now in moved:
        print(f"warning: {tag} on {source} moved ({was[:12]} → {now[:12]}); not installing it")
    signers = _signers_file()
    is_tag = ref in tags
    why_unverifiable = (None if is_tag and signers else
                        f"{ref} is not a tag on {source}" if not is_tag else
                        "this install has no release-signing key (.claude/todo-release-signers)")
    if why_unverifiable and not opts.allow_unsigned:
        print(f"UNVERIFIED — {why_unverifiable}, so its signature can't be checked. Nothing was "
              "fetched. Re-run with --allow-unsigned only if you trust this source.")
        return 2

    # 2. Don't silently discard local edits to the files the installer overwrites.
    dirty = _dirty_managed(target)
    if dirty and not opts.force:
        print("ERROR — uncommitted local changes to files this update overwrites:")
        for f in dirty:
            print(f"  {f}")
        print("Commit or stash them first (or re-run with --force to overwrite). Nothing was changed.")
        return 2

    # 3. An active claim means a /plan-todo tab is mid-item against the current commands; updating
    #    under it is allowed (the item's own worktree is untouched) but worth saying out loud.
    try:
        with State() as st:
            active = list(st.claims)
    except Exception:
        active = []
    if active:
        print(f"note: {len(active)} item(s) in progress ({', '.join(active)}) — their worktrees are "
              "untouched; the new commands take effect on the next run.")

    # 4. Fetch the chosen ref shallowly and let ITS installer do the install — same code path a
    #    first-time install takes, so `update` can never drift from `install.sh`. Snapshot the
    #    claim state first: install.sh has no business touching .git/, but nothing enforces that,
    #    so verify it after rather than just assume it (see _verify_guarded_state below).
    state_before = _snapshot_guarded_state()
    # The manifest this install leaves behind: what `--commit` must also stage, since the new
    # installer deletes whatever it drops (the stamp is about to be rewritten).
    old_managed = _managed_paths(target) or []
    tmp = tempfile.mkdtemp(prefix="claude-todo-update-")
    try:
        pkg = os.path.join(tmp, "pkg")
        print(f"Fetching claude-todo {ref} from {source} …")
        # The child processes below write straight to this stdout; flush first so our own
        # (block-buffered when the caller captures output, as Claude Code does) doesn't land after
        # theirs and scramble the order.
        sys.stdout.flush()
        # Fetch exactly the ref resolved above — a tag into its own tag ref, so the tag object
        # itself arrives and can be compared and verified — rather than whatever `clone` resolves.
        refspec = f"+refs/tags/{ref}:refs/tags/{ref}" if is_tag else ref
        for step in (["init", "--quiet", pkg],
                     ["-C", pkg, "fetch", "--quiet", "--depth", "1", "--", source, refspec],
                     ["-C", pkg, "checkout", "--quiet", "--detach",
                      f"refs/tags/{ref}" if is_tag else "FETCH_HEAD"]):
            r = subprocess.run(["git", *step], capture_output=True, text=True)
            if r.returncode != 0:
                print(f"ERROR — fetching {ref} failed: {_git_error(r.stderr) or 'git failed'}")
                return 1
        commit = _git("-C", pkg, "rev-parse", "HEAD")
        if is_tag:
            # The tag must not have moved between `ls-remote` and the fetch.
            got = (_git("-C", pkg, "rev-parse", f"refs/tags/{ref}"), commit)
            if got != tags[ref]:
                _print_moved(source, [(ref, tags[ref][0], got[0])])
                print("Nothing was installed.")
                return 2
        verified = None
        if signers and is_tag:
            v = subprocess.run(["git", "-C", pkg, "-c", f"gpg.ssh.allowedSignersFile={signers}",
                                "verify-tag", "--", ref], capture_output=True, text=True)
            said = (v.stderr + v.stdout).strip()
            if v.returncode == 0:
                m = re.search(r"signature for (\S+)", said)
                verified = m.group(1) if m else "a release key"
            elif not opts.allow_unsigned:
                print(f"UNVERIFIED — {ref} from {source} is not signed by a key in {signers}: "
                      f"{_git_error(said) or 'verify-tag failed'}. Nothing was installed. Re-run "
                      "with --allow-unsigned only if you trust this source.")
                return 2
            else:
                why_unverifiable = _git_error(said) or "bad signature"
        if verified:
            print(f"Verified {ref} → commit {commit[:12]} (signed by {verified})")
        else:
            print(f"UNVERIFIED {ref} → commit {commit[:12]} — installing anyway (--allow-unsigned): "
                  f"{why_unverifiable}")
        sys.stdout.flush()
        installer = os.path.join(pkg, "install.sh")
        if not os.path.isfile(installer) or not os.path.isfile(os.path.join(pkg, ".claude", "todo-lock.py")):
            print(f"ERROR — {source}@{ref} doesn't look like a claude-todo package "
                  "(no install.sh / .claude/todo-lock.py). Nothing was changed.")
            return 1
        try:
            with open(os.path.join(pkg, "VERSION"), encoding="utf-8") as f:
                new_v = f.read().strip()
        except OSError:
            new_v = latest
        notes = _changelog_since(pkg, cur)
        sys.stdout.flush()
        # The fetch left no `origin` for install.sh to stamp, so hand it the source explicitly.
        rc = subprocess.run(["bash", installer, target],
                            env={**os.environ, "CLAUDE_TODO_UPDATE_SOURCE": source}).returncode
        if rc != 0:
            print(f"ERROR — the installer exited {rc}; check the output above. "
                  f"Your repo may be partially updated — re-run `update --force` once it's resolved.")
            return rc
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    problems = _verify_guarded_state(state_before)
    if problems:
        print("\nERROR — the update touched claim state it should never touch:")
        for p in problems:
            print(f"  {p}")
        print("Your claims/reserved versions may be lost. This is a bug in claude-todo — please "
              "report it. The package update itself completed; only the state-preservation check "
              "failed.")
        return 1

    # Installed from here, so trusted from here — and every release tag seen is pinned.
    _record_trust(source=source, pins={source: _release_pins(tags)})
    print(f"\nUPDATED {cur or 'unknown'} → {new_v or ref}")
    if notes:
        print("\nWhat changed:\n")
        print("\n".join(_format_update_notes(notes, source, ref, full=opts.full_notes)))
    if opts.commit:
        # Old manifest ∪ new manifest ∪ stamp: the files the installer wrote or removed, and
        # nothing else — never `git add -A` over a tree that may hold unrelated work.
        new_managed = _managed_paths(target) or []
        paths = list(dict.fromkeys(old_managed + new_managed + [".claude/todo-version.json"]))
        ok, result = _commit_update(target, paths,
                                    f"Update claude-todo to {new_v or ref}")
        if not ok:
            print(f"\nERROR — the update is installed but its commit failed: {result}")
            print("  Review with `git -C %s status -- .claude` and commit by hand." % target)
            return 1
        print(f"\nCOMMITTED {result}")
    else:
        print(f"\nThe update rewrote tracked files in {target}/.claude — review and commit them "
              "(`update --commit` does this for you next time):")
        print("  git -C %s status -- .claude" % target)
    print("This process is still running the old code; the new version applies to the next command.")
    return 0


# @fragment 90_main.py
# ---------------------------------------------------------------------------
# Dispatch — the COMMANDS table, crash classification, and main
# ---------------------------------------------------------------------------

COMMANDS = {
    # store
    "summary": cmd_summary,
    "similar": cmd_similar,
    "summary-by-model": cmd_summary_by_model,
    "summary-by-route": cmd_summary_by_route,
    "routes": cmd_routes,
    "run": cmd_run,
    "show": cmd_show,
    "files": cmd_files,
    "refs": cmd_refs,
    "add": cmd_add,
    "add-bulk": cmd_add_bulk,
    "append": cmd_append,
    "edit": cmd_edit,
    "merge": cmd_merge,
    "block": cmd_block,
    "remove": cmd_remove,
    "admin-done": cmd_admin_done,
    "reorder": cmd_reorder,
    "set-effort": cmd_set_effort,
    "set-files": cmd_set_files,
    "next-id": cmd_next_id,
    "doctor": cmd_doctor,
    "repair": cmd_repair,
    # claim lock
    "next": cmd_next,
    "attach": cmd_attach,
    "resume": cmd_resume,
    "lock": cmd_lock,
    "touch": cmd_touch,
    "conflicts": cmd_conflicts,
    "preflight": cmd_preflight,
    "reserve-version": cmd_reserve_version,
    "release": cmd_release,
    "bounce": cmd_bounce,
    "reclaim": cmd_reclaim,
    "stats": cmd_stats,
    "list": cmd_list,
    "wait": cmd_wait,
    # sequences
    "seq": cmd_seq,
    # tables
    "tables": cmd_tables,
    # code map
    "codemap": cmd_codemap,
    # docs
    "docs": cmd_docs,
    # project context
    "context": cmd_context,
    # audit
    "audit": cmd_audit,
    "config": cmd_config,
    # toolchain setup
    "stack": cmd_stack,
    # infra
    "main-tree": cmd_main_tree,
    "land": cmd_land,
    "finish": cmd_finish,
    "git-mutex": cmd_git_mutex,
    "verify": cmd_verify,
    "hooks": cmd_hooks,
    # self-update
    "version": cmd_version,
    "check-update": cmd_check_update,
    "update": cmd_update,
}


def _git_version_problem():
    """None when git is usable, else a plain message. `--path-format=absolute` needs git 2.31+."""
    try:
        out = subprocess.run(["git", "--version"], capture_output=True, text=True).stdout
    except OSError:
        return "git is not installed or not on PATH (todo-lock.py needs git 2.31 or newer)."
    m = re.search(r"(\d+)\.(\d+)", out)
    if m and (int(m.group(1)), int(m.group(2))) < (2, 31):
        return f"todo-lock.py needs git 2.31 or newer (found {out.strip()})."
    return None


# Commands that read the routing table. `main` loads it before dispatch, so a bad `routing` config
# is refused up front instead of surfacing after a store write (e.g. in `add`'s route echo).
ROUTING_COMMANDS = {"add", "add-bulk", "bounce", "merge", "next", "summary-by-model", "set-effort",
                    "summary-by-route", "routes", "run", "doctor", "repair", "context"}

CRASH_EXIT = 70  # distinct from `land`'s 3 (STALE) so a caller can tell a crash from a verdict


def _classify_crash(exc):
    """(class, one-line message) for an unexpected exception: store / state / git / environment.
    Only `store` points at /repair — the others aren't formatting problems in the store."""
    if isinstance(exc, subprocess.CalledProcessError):
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        if "not a git repository" in stderr:
            return "environment", "not inside a git repository — run from the repo root."
        cmd = " ".join(str(a) for a in exc.cmd[:4]) if isinstance(exc.cmd, list) else str(exc.cmd)
        return "git", f"`{cmd}` failed: {_git_error(stderr) or 'exit ' + str(exc.returncode)}"
    if isinstance(exc, StoreWriteRefused):
        return "write", (f"{exc}. TODO.local.md is unchanged — run `doctor`: damage it reports "
                         "(e.g. an unclosed fence hiding items) comes first; if it reports none, "
                         "this is a todo-lock.py bug.")
    if isinstance(exc, StateCorrupt):
        path = state_path()
        if os.path.exists(path + ".bak"):
            fix = (f"restore the previous save with `cp '{path}.bak' '{path}'` (one save older), "
                   "then `release` any id whose work is no longer in progress")
        else:
            fix = "delete it (drops every claim and the id counters), then re-claim in-flight items"
        return "state", f"the claims file {path} is corrupt ({exc}); {fix} — /repair won't help."
    if isinstance(exc, json.JSONDecodeError):
        return "state", (f"the claims file ({STATE_FILE} in the git common dir) is corrupt "
                         f"({exc.msg}); inspect or delete it (deleting drops every claim) — /repair won't help.")
    if isinstance(exc, OSError):
        return "environment", f"{exc.__class__.__name__}: {exc}"
    return "store", (f"{exc.__class__.__name__}: {exc} — if TODO.local.md looks malformed, "
                     "ask the user to run /repair.")


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "help":
        return cmd_help(argv[1:])
    cmd = argv[0]
    if cmd not in COMMANDS:
        print(f"ERROR — unknown command {cmd!r}. Run `todo-lock.py help` for the list.")
        return 2
    problem = _git_version_problem()
    if problem:
        print(f"ERROR — {problem}")
        return 2
    _touch_claim()
    try:
        refusal = _store_write_refusal(cmd, argv[1:])
        if refusal:
            print(refusal)
            return 2
        if cmd in ROUTING_COMMANDS:
            _routing()  # a bad `routing` config fails here, before the command writes anything
        if cmd in STORE_COMMITTERS and "--commit" in argv[1:]:
            return _run_committed(cmd, argv[1:])
        return COMMANDS[cmd](argv[1:])
    except RoutingConfigError as exc:
        print(f"ERROR — `routing` in .claude/todo-config.json: {exc}. Fix the config; "
              "`routes` prints the table once it loads.")
        return 2
    except Exception as exc:
        # (SystemExit from argparse is a BaseException — not caught here.)
        klass, msg = _classify_crash(exc)
        print(f"ERROR — todo-lock.py {cmd} crashed ({klass}): {msg}")
        if os.environ.get("CLAUDE_TODO_DEBUG") == "1":
            traceback.print_exc()
        return CRASH_EXIT
    finally:
        # Lifecycle hooks queued by the command fire here, after every lock and the git mutex is
        # released — the one place that is provably true. Never raises.
        _hooks_flush(cmd)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
