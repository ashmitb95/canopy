# Architecture

```
src/canopy/
├── cli/
│   ├── main.py              # argparse CLI — thin layer, no business logic
│   └── ui.py                # rich terminal output (theme, spinners, colors)
├── workspace/
│   ├── config.py            # canopy.toml parser (RepoConfig, WorkspaceConfig)
│   ├── discovery.py         # auto-detect repos + worktrees, generate toml
│   ├── context.py           # context detection from cwd
│   └── workspace.py         # Workspace class, RepoState dataclass
├── git/
│   ├── repo.py              # ALL git subprocess calls (single-repo only)
│   └── multi.py             # cross-repo operations (calls repo.py)
├── features/
│   └── coordinator.py       # feature lane lifecycle, worktree creation, live scanning
├── integrations/
│   ├── linear.py            # Linear issue fetching (via mcp/client.py)
│   ├── github.py            # GitHub PR + review comments (via mcp/client.py)
│   └── precommit.py         # detect and run pre-commit hooks (framework or git hooks)
└── mcp/
    ├── server.py            # MCP server — 30 tools, stdio transport
    └── client.py            # MCP client — spawn + call external MCP servers
```

## Key boundaries

- **`git/repo.py` is the only module that calls `subprocess.run(["git", ...])`.** Everything else goes through it. This makes the git layer replaceable and testable.
- **`mcp/server.py` and `cli/main.py` are thin wrappers.** Business logic lives in `features/coordinator.py`, `git/multi.py`, and `workspace/`.
- **All external integrations go through `mcp/client.py`.** No direct API calls anywhere in the codebase.
