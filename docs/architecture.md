# Architecture

```
src/canopy/
├── cli/
│   ├── main.py                # argparse CLI — thin layer, no business logic
│   ├── ui.py                  # rich terminal output (theme, spinners, colors)
│   └── render.py              # structured-error renderer (BlockerError → multi-line CLI)
├── workspace/
│   ├── config.py              # canopy.toml parser (RepoConfig, WorkspaceConfig)
│   ├── discovery.py           # auto-detect repos + worktrees, generate toml
│   ├── context.py             # context detection from cwd
│   └── workspace.py           # Workspace class, RepoState dataclass
├── git/
│   ├── repo.py                # ALL git subprocess calls (single-repo only)
│   ├── multi.py               # cross-repo operations (calls repo.py)
│   ├── hooks.py               # install/uninstall post-checkout hook + state file reader
│   └── templates/
│       └── post-checkout.py   # hook script template (CANOPY_REPO + CANOPY_WORKSPACE_ROOT subbed in)
├── features/
│   └── coordinator.py         # FeatureLane + lifecycle (status, switch, diff, done, review_*)
├── actions/                   # Wave 2: action layer — completion-driven recipes over primitives
│   ├── errors.py              # ActionError / BlockerError / FailedError / FixAction
│   ├── aliases.py             # universal alias resolver (feature, repo#n, repo:branch, URL)
│   ├── drift.py               # detect_drift + assert_aligned (cached path)
│   ├── realign.py             # bring all repos to feature branch (handles dirty trees + auto-stash)
│   ├── triage.py              # cross-repo PR enumeration + priority tiers
│   ├── reads.py               # linear_get_issue / github_get_pr / github_get_branch / github_get_pr_comments
│   ├── stash.py               # feature-tagged stash save/list/pop
│   ├── review_filter.py       # temporal classifier (actionable vs likely_resolved threads)
│   ├── feature_state.py       # 8-state machine + next_actions (dashboard backend, live git)
│   └── preflight_state.py     # .canopy/state/preflight.json read/write + freshness check
├── agent/
│   └── runner.py              # canopy_run — directory-safe shell exec (no path management)
├── agent_setup/               # ships the using-canopy skill + sets up MCP per workspace
│   ├── __init__.py            # install_skill / install_mcp / setup_agent / check_status
│   └── skill.md               # the skill content (canonical source; copies to ~/.claude/skills/)
├── integrations/
│   ├── linear.py              # Linear issue fetching (via mcp/client.py)
│   ├── github.py              # GitHub PR + review comments (MCP or gh CLI fallback)
│   └── precommit.py           # detect + run pre-commit hooks (framework or git hooks)
└── mcp/
    ├── server.py              # MCP server — 43 tools, stdio transport
    └── client.py              # MCP client — stdio + HTTP+OAuth transports
```

## Key boundaries

- **`git/repo.py` is the only module that calls `subprocess.run(["git", ...])`.** Everything else goes through it. The git layer stays replaceable and testable.
- **`mcp/server.py` and `cli/main.py` are thin wrappers.** Business logic lives in `actions/`, `features/coordinator.py`, `git/multi.py`, and `workspace/`. Adding a CLI command + MCP tool is mostly registering an existing function in two places.
- **All external integrations go through `mcp/client.py` (or `gh` CLI fallback).** No direct API calls anywhere in the codebase.
- **Actions wrap primitives.** An `actions/*.py` function composes `git/`, `integrations/`, and `workspace/` calls into a verified workflow. Actions return structured `BlockerError` / dict; never `print()`. The CLI / MCP layers do their own rendering.
- **The agent context contract.** Every action that takes multi-repo state takes semantic inputs (`feature`, `repo`, alias). Path resolution lives inside `workspace/` and `actions/aliases.py`. See [concepts.md](concepts.md#2-the-agent-context-contract).
- **State persistence is split.** Cached state (`.canopy/state/heads.json`, `.canopy/state/preflight.json`) is for fast paths (drift, state machine warm-up). Live git is the source of truth for write actions and `feature_state`. OAuth tokens cache in `~/.canopy/mcp-tokens/` (per-user, not per-workspace).

## Module dependency direction

```
   cli/  ←→  mcp/server.py             (sibling adapters)
        ↓
   actions/   ←   agent_setup/         (setup writes to ~ and the workspace)
        ↓
   features/, integrations/
        ↓
   git/, workspace/, mcp/client.py
```

Always top-down. `actions/` depends on `git/`, `integrations/`, `features/`, `workspace/` — never the reverse. Tests can stub any layer below by patching at the import boundary.
