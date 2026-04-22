# Canopy — Claude Code Context

## What This Project Is

Canopy is a workspace-first development orchestrator — a CLI (and eventually Tauri desktop app) that coordinates Git across multiple repositories as a single logical unit. It introduces "feature lanes" that map to real Git branches spanning multiple repos.

## Architecture

```
src/canopy/
├── cli/main.py              # argparse entry point, all commands
├── workspace/
│   ├── config.py            # canopy.toml parser (RepoConfig, WorkspaceConfig)
│   ├── discovery.py         # auto-detect repos, generate toml
│   └── workspace.py         # Workspace class, RepoState dataclass
├── git/
│   ├── repo.py              # ALL git subprocess calls go here (single-repo)
│   └── multi.py             # cross-repo operations (calls repo.py)
└── features/
    └── coordinator.py       # FeatureLane, FeatureCoordinator (lifecycle mgmt)
```

## Key Conventions

- **git.repo is the only module that shells out to git.** Everything else calls git.repo functions. This makes the git layer replaceable (e.g., with git2-rs in the Tauri backend).
- **All CLI commands support `--json`.** This is the contract between the CLI and the future Tauri app.
- **Feature lanes use real Git branches.** No virtual branches, no proprietary abstractions. A feature lane named "auth-flow" creates actual `auth-flow` branches.
- **Feature metadata lives in `.canopy/features.json`** in the workspace root. Simple JSON, not a database.
- **canopy.toml is the workspace definition.** It's the source of truth for which repos are in the workspace.

## Build & Test

```bash
pip install -e ".[dev]"
pytest tests/ -v          # 50 tests, ~0.6s
```

## Test Fixtures

Tests use real temporary Git repos created in pytest fixtures (see `tests/conftest.py`):
- `workspace_dir` — bare workspace with api/ and ui/ repos on main
- `workspace_with_feature` — workspace with `auth-flow` branches and commits in both repos
- `canopy_toml` — workspace with a canopy.toml already written

## Important Implementation Details

- **Python 3.10+ compat:** Uses `tomli` on 3.10, `tomllib` on 3.11+. See config.py import.
- **Porcelain parsing:** `git status --porcelain` output has significant leading spaces. The parser in `repo.py` uses raw stdout (not `.strip()`) to preserve them.
- **Feature discovery:** `Workspace.active_features()` detects branches that exist in 2+ repos, even if they weren't explicitly created via `canopy feature create`.
- **Overlap detection:** `git.multi.find_type_overlaps()` matches files by basename (without extension) across repos to find potential shared type conflicts.

## Roadmap

- Phase 0 (done): CLI core
- Phase 1: Tauri v2 + Svelte app shell, feature dashboard, file watcher
- Phase 2: Diff views with hunk staging, basic commit tree
- Phase 3: Worktree intelligence (absorbed from ../worktree-graph codebase)

## Related Docs

- `../canopy-research.md` — Technical research (gitoxide vs git2-rs, GitButler lessons, IPC patterns)
- `../canopy-implementation.md` — Module-level implementation spec per phase
- `../canopy-architecture.docx` — Architecture overview document
