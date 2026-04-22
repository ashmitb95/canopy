# Canopy — Agent Guidelines

## For AI Agents Working on This Codebase

### Before You Start

1. Read `CLAUDE.md` for architecture and conventions.
2. Read `../canopy-implementation.md` for the full implementation spec — it tells you what to build next.
3. Read `../canopy-research.md` for technology decisions and rationale.

### Module Boundaries

**Do not break these boundaries:**

- `git/repo.py` is the **only** file that calls `subprocess.run(["git", ...])`. If you need a new git operation, add it there.
- `git/multi.py` calls `git/repo.py` functions across multiple repos. Cross-repo logic goes here.
- `features/coordinator.py` manages feature lane lifecycle. It calls `git/multi.py` for the actual git work.
- `workspace/workspace.py` holds the `Workspace` class. It reads git state via `git/repo.py` but does not do cross-repo coordination.
- `cli/main.py` is a thin layer that parses args and calls the modules above. Keep business logic out of the CLI.

### Adding a New CLI Command

1. Add the command function in `cli/main.py` following the `cmd_*` pattern.
2. Add argparse config in `main()`.
3. Always support `--json` output via `_print_json()`.
4. The human-readable output should be concise, indented with 2 spaces, and use `─` for separators.

### Adding a New Git Operation

1. Add the function to `git/repo.py` using `_run()` or `_run_ok()`.
2. Write a test in `tests/test_repo.py` using the `git_repo` fixture.
3. Be careful with `_run_ok()` — it returns empty string on failure, which is correct for query operations but dangerous for writes.

### Testing Conventions

- All tests use real temporary Git repos, not mocks. This catches real git behavior differences.
- Fixtures are in `tests/conftest.py`. Reuse them.
- Test file naming: `test_<module>.py`.
- Run tests from the `canopy/` directory: `pytest tests/ -v`.

### JSON Output Contract

Every `--json` command outputs a single JSON object to stdout. The Tauri app depends on this. The schema for each command:

- `canopy status --json` → `WorkspaceStatus` (see `workspace.py:Workspace.to_dict()`)
- `canopy feature list --json` → `list[FeatureLane.to_dict()]`
- `canopy feature status <name> --json` → `FeatureLane.to_dict()`
- `canopy feature diff <name> --json` → diff dict with `repos`, `summary`, `type_overlaps`

If you change these shapes, the Tauri app (Phase 1+) will break.

### What NOT to Build

This is explicitly scoped. Do not add:

- Interactive rebase UI
- Stash management
- Submodule handling
- Merge conflict resolution
- GitHub/GitLab integration
- CI/CD status
- Code review features
- File browser/editor

If users need these, they should use Fork or the Git CLI directly.

### Phase Awareness

Check `../canopy-implementation.md` for what phase the project is in. Don't build ahead of the current phase unless asked. The phases are:

- Phase 0 (done): CLI core
- Phase 1: Tauri app shell + dashboard
- Phase 2: Diff views + commit tree
- Phase 3: Intelligence layer
