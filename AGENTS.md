# Canopy — Agent Guidelines

## For AI Agents Working on This Codebase

### Before You Start

1. Read `CLAUDE.md` for architecture and conventions.
2. Run `pytest tests/ -v` to verify the baseline (159 tests, ~2s).

### Module Boundaries

**Do not break these boundaries:**

- `git/repo.py` is the **only** file that calls `subprocess.run(["git", ...])`. If you need a new git operation, add it there.
- `git/multi.py` calls `git/repo.py` functions across multiple repos. Cross-repo logic goes here.
- `features/coordinator.py` manages feature lane lifecycle. It calls `git/multi.py` for the actual git work, and `git/repo.py` for worktree operations.
- `workspace/workspace.py` holds the `Workspace` class. It reads git state via `git/repo.py` but does not do cross-repo coordination.
- `workspace/context.py` detects where canopy is running from. It reads filesystem paths and calls `git/repo.py` for branch info.
- `cli/main.py` is a thin layer that parses args and calls the modules above. Keep business logic out of the CLI.
- `mcp/server.py` wraps the same modules as the CLI. Every tool calls the same functions — the MCP server should never have its own logic.
- `mcp/client.py` is the MCP client — it spawns external MCP servers and calls their tools. All external integrations go through this.
- `integrations/linear.py` fetches Linear issue data via `mcp/client.py`. It never calls the Linear API directly.
- `integrations/github.py` finds PRs for a branch and fetches unresolved review comments via `mcp/client.py`. It never calls the GitHub API directly.
- `integrations/precommit.py` detects and runs pre-commit hooks. It checks for `.pre-commit-config.yaml` (framework) and `.git/hooks/pre-commit` (raw git hooks). It does not go through MCP — it runs hooks locally via subprocess.

### Adding a New CLI Command

1. Add the command function in `cli/main.py` following the `cmd_*` pattern.
2. Add argparse config in `main()`.
3. Always support `--json` output via `_print_json()`.
4. The human-readable output should be concise, indented with 2 spaces, and use `─` for separators.
5. If the command is useful for AI agents, add a matching tool in `mcp/server.py`.

### Adding a New MCP Tool

1. Add a `@mcp.tool()` function in `mcp/server.py`.
2. Use `_get_workspace()` to load the workspace.
3. Call existing module functions — don't put logic in the server.
4. Return dicts/lists (FastMCP handles JSON serialization).
5. Write clear docstrings — they become the tool descriptions AI agents see.

### Adding a New Git Operation

1. Add the function to `git/repo.py` using `_run()` or `_run_ok()`.
2. Write a test in `tests/test_repo.py` or `tests/test_new_commands.py`.
3. Be careful with `_run_ok()` — it returns empty string on failure, which is correct for query operations but dangerous for writes.

### Testing Conventions

- All tests use real temporary Git repos, not mocks. This catches real git behavior differences.
- Fixtures are in `tests/conftest.py`. Reuse them.
- Test file naming: `test_<module>.py` or `test_<feature_area>.py`.
- Run tests from the `canopy/` directory: `pytest tests/ -v`.
- Worktree tests should clean up with `git worktree remove` when done.

### JSON Output Contract

Every `--json` command and MCP tool returns structured data. Key shapes:

- `workspace_status` → `WorkspaceStatus` (see `workspace.py:Workspace.to_dict()`)
- `feature_list` → `list[FeatureLane.to_dict()]`
- `feature_status` → `FeatureLane.to_dict()` (includes `repo_states` with `worktree_path`)
- `feature_diff` → dict with `repos`, `summary`, `type_overlaps`
- `workspace_context` → `CanopyContext.to_dict()` (context_type, feature, repo_names, repo_paths)
- `worktree_info` → `{features: {name: {repos: {name: {path, branch, dirty, ahead, behind}}}}, repos: {name: {main_path, worktrees: [...]}}}`
- `worktree_create` → `FeatureLane.to_dict()` + `worktree_paths` (optional `linear_issue`, `linear_title`, `linear_url`)
- `review_status` → `{feature, repos: [{name, branch, pr: {number, url, state, title}, has_unresolved_comments}], precommit: {available, passed, errors}}`
- `review_comments` → `{feature, repos: [{name, pr_number, comments: [{path, line, body, author, resolved}]}]}`
- `review_prep` → `{feature, ready, blockers: [str], repos: [{name, merge_readiness, pr_status, unresolved_comment_count, precommit_passed}]}`

### Integration Conventions

- **All integrations go through MCP.** Canopy never calls external APIs directly. It spawns the relevant MCP server via `mcp/client.py` and calls tools.
- **MCP server configs live in `.canopy/mcps.json`.** Each key is a server name (e.g. `"linear"`) with `command`, `args`, and `env`.
- **Graceful degradation.** If an MCP server isn't configured, the feature still works — just without enrichment (e.g. Linear issue title won't be fetched, but the issue ID is still stored).

### Adding a New Integration

1. Add a module in `integrations/` (e.g. `integrations/github.py`).
2. Use `mcp.client.get_mcp_config()` to check if the server is configured.
3. Use `mcp.client.call_tool()` to call the server's tools.
4. Handle `McpClientError` gracefully — never fail the whole operation because an integration is down.
5. Store any linked metadata in `features.json` via `FeatureLane` fields.
6. Write tests that mock the MCP call but test the data flow end-to-end.

### IDE Launcher Conventions

- `canopy code/cursor` generates `.code-workspace` files in `.canopy/` for multi-root workspaces.
- `canopy fork` opens each repo separately (Fork doesn't support multi-root).
- On macOS, `fork` CLI is preferred; fallback is `open -a Fork`.
- These commands use `FeatureCoordinator.resolve_paths()` to find the right directories.

### Context Detection

`workspace/context.py` detects four context types based on cwd:

1. `feature_dir` — inside `.canopy/worktrees/<feature>/` (all repos in scope)
2. `repo_worktree` — inside `.canopy/worktrees/<feature>/<repo>/` (single repo)
3. `repo` — inside a normal workspace repo (feature = current branch if non-default)
4. `workspace_root` — at the canopy.toml level (all repos in scope)

`canopy stage` uses this to know which repos to commit to without explicit arguments.
