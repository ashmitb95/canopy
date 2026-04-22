"""
Canopy CLI — workspace-first development orchestrator.

Commands:
    init                         Auto-detect repos, generate canopy.toml
    status                       Cross-repo workspace status
    checkout <branch>            Checkout branch across repos
    commit -m <msg>              Commit staged changes across repos
    log                          Interleaved log across repos
    sync                         Pull + rebase across all repos
    feature create <name>        Create a feature lane across repos
    feature list                 List active feature lanes
    feature switch <name>        Checkout feature branch in all repos
    feature diff <name>          Aggregate diff for a feature lane
    feature status <name>        Detailed feature lane status
    branch list                  List branches across repos
    branch delete <name>         Delete a branch across repos
    branch rename <old> <new>    Rename a branch across repos
    stash save                   Stash changes across repos
    stash pop                    Pop stash across repos
    stash list                   List stashes across repos
    stash drop                   Drop stash across repos
    worktree                     Show worktree info for repos
    stage <message>              Context-aware add + commit (from worktree dir)
    code <feature|.>             Open VS Code for feature or workspace
    cursor <feature|.>           Open Cursor for feature or workspace
    fork <feature|.>             Open Fork.app for feature or workspace
    context                      Show detected canopy context (debug)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _print_json(data: dict | list) -> None:
    """Print JSON to stdout."""
    print(json.dumps(data, indent=2, default=str))


def _load_workspace():
    """Load workspace from canopy.toml in current directory tree."""
    from ..workspace.config import load_config, ConfigNotFoundError
    from ..workspace.workspace import Workspace

    try:
        config = load_config()
    except ConfigNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        print("Run `canopy init` to create a canopy.toml.", file=sys.stderr)
        sys.exit(1)

    return Workspace(config)


# ── Commands ──────────────────────────────────────────────────────────────

def cmd_init(args: argparse.Namespace) -> None:
    """Auto-detect repos and generate canopy.toml."""
    from ..workspace.discovery import discover_repos, generate_toml
    from ..workspace.config import load_config, ConfigNotFoundError

    root = Path(args.path).resolve() if args.path else Path.cwd().resolve()

    # Check if canopy.toml already exists
    toml_path = root / "canopy.toml"
    if toml_path.exists() and not args.force:
        print(f"canopy.toml already exists at {toml_path}", file=sys.stderr)
        print("Use --force to overwrite.", file=sys.stderr)
        sys.exit(1)

    repos = discover_repos(root)
    if not repos:
        print(f"No Git repositories found in {root}", file=sys.stderr)
        sys.exit(1)

    toml_content = generate_toml(root, workspace_name=args.name)

    if args.json:
        _print_json({
            "root": str(root),
            "repos": [{"name": r.name, "path": r.path, "role": r.role, "lang": r.lang} for r in repos],
            "toml": toml_content,
        })
        return

    if args.dry_run:
        print(toml_content)
        return

    toml_path.write_text(toml_content)
    print(f"Created {toml_path}")
    print(f"Found {len(repos)} repos:")
    for r in repos:
        tags = []
        if r.role:
            tags.append(r.role)
        if r.lang:
            tags.append(r.lang)
        tag_str = f" ({', '.join(tags)})" if tags else ""
        print(f"  {r.name}{tag_str}")


def cmd_status(args: argparse.Namespace) -> None:
    """Show cross-repo workspace status."""
    workspace = _load_workspace()
    workspace.refresh()

    if args.json:
        _print_json(workspace.to_dict())
        return

    print(f"\n  Workspace: {workspace.config.name}")
    print(f"  Root: {workspace.config.root}")
    print(f"  {'─' * 60}")

    for state in workspace.repos:
        indicators = []
        if state.is_dirty:
            indicators.append(f"{state.dirty_count} dirty")
        if state.ahead_of_default:
            indicators.append(f"+{state.ahead_of_default}")
        if state.behind_default:
            indicators.append(f"-{state.behind_default}")

        tag = f"  ({', '.join(indicators)})" if indicators else ""
        role = f" [{state.config.role}]" if state.config.role else ""

        print(f"\n  {state.config.name}{role}")
        print(f"    branch: {state.current_branch}{tag}")
        print(f"    head:   {state.head_sha}")

    features = workspace.active_features()
    if features:
        print(f"\n  {'─' * 60}")
        print(f"  Active features: {', '.join(features)}")

    print()


def cmd_feature_create(args: argparse.Namespace) -> None:
    """Create a feature lane across repos."""
    workspace = _load_workspace()
    from ..features.coordinator import FeatureCoordinator

    coordinator = FeatureCoordinator(workspace)
    repos = args.repos.split(",") if args.repos else None
    use_worktrees = getattr(args, "worktree", False)

    try:
        lane = coordinator.create(args.name, repos, use_worktrees=use_worktrees)
    except (ValueError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        _print_json(lane.to_dict())
        return

    if use_worktrees:
        print(f"Created feature lane with worktrees: {lane.name}")
        # Show worktree paths
        paths = coordinator.resolve_paths(lane.name)
        for repo_name, path in paths.items():
            print(f"  {repo_name}: {path}")
        print(f"\nOpen in VS Code: canopy code {lane.name}")
        print(f"Open in Cursor:  canopy cursor {lane.name}")
    else:
        print(f"Created feature lane: {lane.name}")
        print(f"  Repos: {', '.join(lane.repos)}")
        print(f"\nSwitch to it with: canopy feature switch {lane.name}")
        print(f"Or create with worktrees: canopy feature create --worktree {lane.name}")


def cmd_feature_list(args: argparse.Namespace) -> None:
    """List active feature lanes."""
    workspace = _load_workspace()
    from ..features.coordinator import FeatureCoordinator

    coordinator = FeatureCoordinator(workspace)
    lanes = coordinator.list_active()

    if args.json:
        _print_json([lane.to_dict() for lane in lanes])
        return

    if not lanes:
        print("No active feature lanes.")
        print("Create one with: canopy feature create <name>")
        return

    print(f"\n  Feature Lanes")
    print(f"  {'─' * 60}")

    for lane in lanes:
        print(f"\n  {lane.name}")
        for repo_name, state in lane.repo_states.items():
            if "error" in state:
                print(f"    {repo_name}: error — {state['error']}")
                continue
            if not state.get("has_branch"):
                print(f"    {repo_name}: no branch")
                continue
            parts = []
            if state.get("ahead"):
                parts.append(f"+{state['ahead']}")
            if state.get("behind"):
                parts.append(f"-{state['behind']}")
            if state.get("dirty"):
                parts.append("dirty")
            if state.get("changed_file_count"):
                parts.append(f"{state['changed_file_count']} files")
            info = ", ".join(parts) if parts else "up to date"
            print(f"    {repo_name}: {info}")

    print()


def cmd_feature_switch(args: argparse.Namespace) -> None:
    """Switch to a feature lane."""
    workspace = _load_workspace()
    from ..features.coordinator import FeatureCoordinator

    coordinator = FeatureCoordinator(workspace)

    try:
        results = coordinator.switch(args.name)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        _print_json({"feature": args.name, "results": results})
        return

    has_worktrees = False
    for repo, result in results.items():
        if result is True:
            print(f"  {repo}: ok")
        elif isinstance(result, str) and result.startswith("already in worktree:"):
            print(f"  {repo}: {result}")
            has_worktrees = True
        else:
            print(f"  {repo}: failed: {result}")

    if has_worktrees:
        print(f"\nSome branches live in worktrees. Open them with:")
        print(f"  canopy code {args.name}")
        print(f"  canopy cursor {args.name}")


def cmd_feature_diff(args: argparse.Namespace) -> None:
    """Show aggregate diff for a feature lane."""
    workspace = _load_workspace()
    from ..features.coordinator import FeatureCoordinator

    coordinator = FeatureCoordinator(workspace)

    try:
        diff = coordinator.diff(args.name)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        _print_json(diff)
        return

    summary = diff["summary"]
    print(f"\n  Feature: {args.name}")
    print(f"  {summary['participating_repos']}/{summary['total_repos']} repos, "
          f"{summary['total_files_changed']} files, "
          f"+{summary['total_insertions']} -{summary['total_deletions']}")
    print(f"  {'─' * 60}")

    for repo_name, data in diff["repos"].items():
        if not data.get("has_branch"):
            print(f"\n  {repo_name}: (no branch)")
            continue

        ins = data.get("insertions", 0)
        dele = data.get("deletions", 0)
        files = data.get("changed_files", [])
        print(f"\n  {repo_name} ({len(files)} files, +{ins} -{dele})")
        for f in files[:10]:
            print(f"    {f}")
        if len(files) > 10:
            print(f"    ... and {len(files) - 10} more")

    if diff.get("type_overlaps"):
        print(f"\n  {'─' * 60}")
        print(f"  Type Overlaps:")
        for o in diff["type_overlaps"]:
            repos = ", ".join(o["repos"])
            print(f"    '{o['file_pattern']}' modified in {repos}")
            for f in o["files"]:
                print(f"      {f['repo']}: {f['path']}")

    print()


def cmd_feature_status(args: argparse.Namespace) -> None:
    """Show detailed feature lane status."""
    workspace = _load_workspace()
    from ..features.coordinator import FeatureCoordinator

    coordinator = FeatureCoordinator(workspace)

    try:
        lane = coordinator.status(args.name)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        _print_json(lane.to_dict())
        return

    print(f"\n  Feature: {lane.name}")
    print(f"  Status: {lane.status}")
    if lane.created_at:
        print(f"  Created: {lane.created_at}")
    print(f"  {'─' * 60}")

    for repo_name, state in lane.repo_states.items():
        if "error" in state:
            print(f"\n  {repo_name}: error — {state['error']}")
            continue
        if not state.get("has_branch"):
            print(f"\n  {repo_name}: no branch")
            continue

        parts = []
        if state.get("ahead"):
            parts.append(f"+{state['ahead']} ahead")
        if state.get("behind"):
            parts.append(f"-{state['behind']} behind")
        if state.get("dirty"):
            parts.append("uncommitted changes")
        divergence = ", ".join(parts) if parts else "up to date"

        print(f"\n  {repo_name}")
        print(f"    divergence: {divergence}")
        files = state.get("changed_files", [])
        if files:
            print(f"    files ({len(files)}):")
            for f in files[:8]:
                print(f"      {f}")
            if len(files) > 8:
                print(f"      ... and {len(files) - 8} more")

    # Merge readiness
    readiness = coordinator.merge_readiness(lane.name)
    print(f"\n  {'─' * 60}")
    if readiness["ready"]:
        print("  Merge ready: yes")
    else:
        print("  Merge ready: no")
        for issue in readiness["issues"]:
            print(f"    - {issue}")

    print()


def cmd_sync(args: argparse.Namespace) -> None:
    """Pull + rebase across all repos."""
    workspace = _load_workspace()
    from ..git.multi import sync_all

    results = sync_all(workspace, strategy=args.strategy)

    if args.json:
        _print_json({"results": results})
        return

    for repo, result in results.items():
        icon = "ok" if result == "ok" else f"failed: {result}"
        print(f"  {repo}: {icon}")


def cmd_checkout(args: argparse.Namespace) -> None:
    """Checkout a branch across repos."""
    workspace = _load_workspace()
    from ..git.multi import checkout_all

    repos = args.repos.split(",") if args.repos else None
    results = checkout_all(workspace, args.branch, repos)

    if args.json:
        _print_json({"branch": args.branch, "results": results})
        return

    for repo, result in results.items():
        status = "ok" if result is True else f"failed: {result}"
        print(f"  {repo}: {status}")


def cmd_commit(args: argparse.Namespace) -> None:
    """Commit staged changes across repos."""
    workspace = _load_workspace()
    from ..git.multi import commit_all

    repos = args.repos.split(",") if args.repos else None
    results = commit_all(workspace, args.message, repos)

    if args.json:
        _print_json({"message": args.message, "results": results})
        return

    for repo, result in results.items():
        print(f"  {repo}: {result}")


def cmd_log(args: argparse.Namespace) -> None:
    """Interleaved log across repos."""
    workspace = _load_workspace()
    from ..git.multi import log_all

    entries = log_all(workspace, max_count=args.count, feature=args.feature)

    if args.json:
        _print_json(entries)
        return

    if not entries:
        print("  No commits found.")
        return

    for entry in entries:
        date_short = entry["date"][:10] if entry.get("date") else ""
        print(f"  {entry.get('short_sha', '')} [{entry.get('repo', '')}] "
              f"{entry.get('subject', '')}  ({entry.get('author', '')}, {date_short})")


def cmd_branch_list(args: argparse.Namespace) -> None:
    """List branches across repos."""
    workspace = _load_workspace()
    from ..git.multi import branches_all

    results = branches_all(workspace)

    if args.json:
        _print_json(results)
        return

    for repo_name, branches in results.items():
        print(f"\n  {repo_name}")
        for b in branches:
            marker = "* " if b["is_current"] else "  "
            print(f"    {marker}{b['name']}  {b['sha']}  {b['subject']}")

    print()


def cmd_branch_delete(args: argparse.Namespace) -> None:
    """Delete a branch across repos."""
    workspace = _load_workspace()
    from ..git.multi import delete_branch_all

    repos = args.repos.split(",") if args.repos else None
    results = delete_branch_all(workspace, args.name, force=args.force, repos=repos)

    if args.json:
        _print_json({"branch": args.name, "results": results})
        return

    for repo, result in results.items():
        print(f"  {repo}: {result}")


def cmd_branch_rename(args: argparse.Namespace) -> None:
    """Rename a branch across repos."""
    workspace = _load_workspace()
    from ..git.multi import rename_branch_all

    repos = args.repos.split(",") if args.repos else None
    results = rename_branch_all(workspace, args.old, args.new, repos)

    if args.json:
        _print_json({"old": args.old, "new": args.new, "results": results})
        return

    for repo, result in results.items():
        print(f"  {repo}: {result}")


def cmd_stash_save(args: argparse.Namespace) -> None:
    """Stash uncommitted changes across repos."""
    workspace = _load_workspace()
    from ..git.multi import stash_save_all

    repos = args.repos.split(",") if args.repos else None
    results = stash_save_all(workspace, message=args.message or "", repos=repos)

    if args.json:
        _print_json({"results": results})
        return

    for repo, result in results.items():
        print(f"  {repo}: {result}")


def cmd_stash_pop(args: argparse.Namespace) -> None:
    """Pop stash across repos."""
    workspace = _load_workspace()
    from ..git.multi import stash_pop_all

    repos = args.repos.split(",") if args.repos else None
    results = stash_pop_all(workspace, index=args.index, repos=repos)

    if args.json:
        _print_json({"results": results})
        return

    for repo, result in results.items():
        print(f"  {repo}: {result}")


def cmd_stash_list(args: argparse.Namespace) -> None:
    """List stashes across repos."""
    workspace = _load_workspace()
    from ..git.multi import stash_list_all

    results = stash_list_all(workspace)

    if args.json:
        _print_json(results)
        return

    if not results:
        print("  No stashes found.")
        return

    for repo_name, stashes in results.items():
        print(f"\n  {repo_name}")
        for s in stashes:
            print(f"    {s['ref']}: {s['message']}")

    print()


def cmd_stash_drop(args: argparse.Namespace) -> None:
    """Drop stash across repos."""
    workspace = _load_workspace()
    from ..git.multi import stash_drop_all

    repos = args.repos.split(",") if args.repos else None
    results = stash_drop_all(workspace, index=args.index, repos=repos)

    if args.json:
        _print_json({"results": results})
        return

    for repo, result in results.items():
        print(f"  {repo}: {result}")


def cmd_worktree_list(args: argparse.Namespace) -> None:
    """Show worktree info for repos in the workspace."""
    workspace = _load_workspace()
    from ..git import repo as git

    all_info = {}
    for state in workspace.repos:
        if not state.abs_path.exists():
            continue
        worktrees = git.worktree_list(state.abs_path)
        is_wt = git.is_worktree(state.abs_path)
        main_path = git.worktree_main_path(state.abs_path) if is_wt else None
        all_info[state.config.name] = {
            "is_linked_worktree": is_wt,
            "main_working_tree": str(main_path) if main_path else None,
            "worktrees": worktrees,
        }

    if args.json:
        _print_json(all_info)
        return

    for repo_name, info in all_info.items():
        print(f"\n  {repo_name}")
        if info["is_linked_worktree"]:
            print(f"    (linked worktree of {info['main_working_tree']})")
        worktrees = info["worktrees"]
        if len(worktrees) > 1:
            print(f"    worktrees:")
            for wt in worktrees:
                branch = wt.get("branch", "(detached)")
                print(f"      {wt['path']}  [{branch}]")
        elif len(worktrees) == 1:
            print(f"    single working tree")
        else:
            print(f"    no worktree info")

    print()


def _open_ide(ide_cmd: str, args: argparse.Namespace) -> None:
    """Open an IDE with the right directories for a feature or workspace.

    Supports two modes:
    - `canopy code <feature>` — open repos/worktrees for a feature lane
    - `canopy code .` — open all repos in the workspace
    """
    workspace = _load_workspace()

    target = args.target

    if target == ".":
        # Open all repos in workspace
        paths = [str(state.abs_path) for state in workspace.repos
                 if state.abs_path.exists()]
        label = workspace.config.name
    else:
        # Open repos for a feature lane
        from ..features.coordinator import FeatureCoordinator
        coordinator = FeatureCoordinator(workspace)
        try:
            paths_dict = coordinator.resolve_paths(target)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        if not paths_dict:
            print(f"No paths found for feature '{target}'", file=sys.stderr)
            sys.exit(1)

        paths = list(paths_dict.values())
        label = target

    if not paths:
        print("No directories to open.", file=sys.stderr)
        sys.exit(1)

    if args.json:
        _print_json({"ide": ide_cmd, "target": target, "paths": paths})
        return

    # If multiple paths, generate a .code-workspace file for multi-root
    if len(paths) > 1:
        workspace_file = _generate_workspace_file(
            workspace.config.root, label, paths
        )
        cmd = [ide_cmd, workspace_file]
        print(f"  Opening {ide_cmd} with workspace: {workspace_file}")
    else:
        cmd = [ide_cmd, paths[0]]
        print(f"  Opening {ide_cmd}: {paths[0]}")

    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        print(f"Error: '{ide_cmd}' not found. Is it installed and on PATH?",
              file=sys.stderr)
        print(f"  VS Code: install 'code' command from Command Palette",
              file=sys.stderr)
        print(f"  Cursor:  install 'cursor' command from Command Palette",
              file=sys.stderr)
        sys.exit(1)


def _generate_workspace_file(
    root: Path,
    label: str,
    paths: list[str],
) -> str:
    """Generate a .code-workspace file for multi-root workspace.

    Returns the path to the generated file.
    """
    canopy_dir = root / ".canopy"
    canopy_dir.mkdir(parents=True, exist_ok=True)

    workspace_data = {
        "folders": [{"path": p} for p in paths],
        "settings": {
            "canopy.feature": label,
        },
    }

    ws_file = canopy_dir / f"{label}.code-workspace"
    ws_file.write_text(json.dumps(workspace_data, indent=2))
    return str(ws_file)


def cmd_code(args: argparse.Namespace) -> None:
    """Open VS Code with feature or workspace directories."""
    _open_ide("code", args)


def cmd_cursor(args: argparse.Namespace) -> None:
    """Open Cursor with feature or workspace directories."""
    _open_ide("cursor", args)


def cmd_fork(args: argparse.Namespace) -> None:
    """Open Fork.app with feature or workspace repos."""
    workspace = _load_workspace()

    target = args.target

    if target == ".":
        paths = [str(state.abs_path) for state in workspace.repos
                 if state.abs_path.exists()]
    else:
        from ..features.coordinator import FeatureCoordinator
        coordinator = FeatureCoordinator(workspace)
        try:
            paths_dict = coordinator.resolve_paths(target)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        paths = list(paths_dict.values())

    if not paths:
        print("No directories to open.", file=sys.stderr)
        sys.exit(1)

    if args.json:
        _print_json({"ide": "fork", "target": target, "paths": paths})
        return

    # Fork opens repos individually — each path becomes a tab
    import platform
    import shutil

    use_fork_cli = shutil.which("fork") is not None
    is_macos = platform.system() == "Darwin"

    if not use_fork_cli and not is_macos:
        print(
            "Error: 'fork' CLI not found.\n"
            "  Install it from Fork → Preferences → Integration → Install CLI Tool.",
            file=sys.stderr,
        )
        sys.exit(1)

    for p in paths:
        if use_fork_cli:
            subprocess.Popen(
                ["fork", p],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            # macOS fallback: open -a Fork
            result = subprocess.run(
                ["open", "-a", "Fork", p],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                print(f"Error: could not open Fork. Is Fork.app installed?",
                      file=sys.stderr)
                sys.exit(1)
        print(f"  opened: {p}")


def cmd_stage(args: argparse.Namespace) -> None:
    """Context-aware stage + commit across repos in current feature.

    When run from inside a feature worktree directory, stages all
    changes and commits with the given message across every repo
    worktree in that feature.

    When run from inside a single repo worktree, stages + commits
    just that repo.
    """
    from ..workspace.context import detect_context
    from ..git import repo as git_repo

    ctx = detect_context()

    if ctx.context_type == "unknown":
        print("Error: can't detect canopy context from current directory.", file=sys.stderr)
        print("Run this from inside a feature worktree or a workspace repo.", file=sys.stderr)
        sys.exit(1)

    if not ctx.repo_paths:
        print("Error: no repos found in current context.", file=sys.stderr)
        sys.exit(1)

    message = args.message
    results: dict[str, str] = {}

    for repo_path, repo_name in zip(ctx.repo_paths, ctx.repo_names):
        # Check if there are any changes to stage
        status = git_repo.status_porcelain(repo_path)
        if not status:
            results[repo_name] = "clean"
            continue

        # Stage everything
        try:
            # Stage all changes (new, modified, deleted)
            git_repo._run(["add", "-A"], cwd=repo_path)

            # Commit
            sha = git_repo.commit(repo_path, message)
            results[repo_name] = sha[:12]
        except git_repo.GitError as e:
            results[repo_name] = f"error: {e}"

    if args.json:
        _print_json({
            "message": message,
            "feature": ctx.feature,
            "context_type": ctx.context_type,
            "results": results,
        })
        return

    if ctx.feature:
        print(f"\n  Feature: {ctx.feature}")
    print(f"  Message: {message}")
    print()
    for repo, result in results.items():
        print(f"  {repo}: {result}")
    print()


def cmd_context(args: argparse.Namespace) -> None:
    """Show detected canopy context for current directory (debug)."""
    from ..workspace.context import detect_context

    ctx = detect_context()

    if args.json:
        _print_json(ctx.to_dict())
        return

    print(f"\n  Context type: {ctx.context_type}")
    print(f"  Working dir:  {ctx.cwd}")
    if ctx.workspace_root:
        print(f"  Workspace:    {ctx.workspace_root}")
    if ctx.feature:
        print(f"  Feature:      {ctx.feature}")
    if ctx.branch:
        print(f"  Branch:       {ctx.branch}")
    if ctx.repo_names:
        print(f"  Repos:        {', '.join(ctx.repo_names)}")
        for name, path in zip(ctx.repo_names, ctx.repo_paths):
            print(f"    {name}: {path}")
    print()


# ── Entry point ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="canopy",
        description="Workspace-first development orchestrator.",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    subparsers = parser.add_subparsers(dest="command")

    # init
    init_p = subparsers.add_parser("init", help="Initialize a workspace")
    init_p.add_argument("path", nargs="?", default=None, help="Workspace root path")
    init_p.add_argument("--name", default=None, help="Workspace name")
    init_p.add_argument("--force", action="store_true", help="Overwrite existing canopy.toml")
    init_p.add_argument("--dry-run", action="store_true", help="Print toml without writing")
    init_p.add_argument("--json", action="store_true", help="Output as JSON")

    # status
    status_p = subparsers.add_parser("status", help="Workspace status")
    status_p.add_argument("--json", action="store_true", help="Output as JSON")

    # feature (with subcommands)
    feature_p = subparsers.add_parser("feature", help="Feature lane operations")
    feature_sub = feature_p.add_subparsers(dest="feature_command")

    # feature create
    fc = feature_sub.add_parser("create", help="Create a feature lane")
    fc.add_argument("name", help="Feature/branch name")
    fc.add_argument("--repos", default=None, help="Comma-separated repo names (default: all)")
    fc.add_argument("--worktree", action="store_true",
                    help="Create linked worktrees (each repo gets its own directory)")
    fc.add_argument("--json", action="store_true", help="Output as JSON")

    # feature list
    fl = feature_sub.add_parser("list", help="List feature lanes")
    fl.add_argument("--json", action="store_true", help="Output as JSON")

    # feature switch
    fs = feature_sub.add_parser("switch", help="Switch to a feature lane")
    fs.add_argument("name", help="Feature name")
    fs.add_argument("--json", action="store_true", help="Output as JSON")

    # feature diff
    fd = feature_sub.add_parser("diff", help="Feature lane diff")
    fd.add_argument("name", help="Feature name")
    fd.add_argument("--json", action="store_true", help="Output as JSON")

    # feature status
    fst = feature_sub.add_parser("status", help="Feature lane status")
    fst.add_argument("name", help="Feature name")
    fst.add_argument("--json", action="store_true", help="Output as JSON")

    # sync
    sync_p = subparsers.add_parser("sync", help="Pull + rebase across repos")
    sync_p.add_argument("--strategy", choices=["rebase", "merge"], default="rebase")
    sync_p.add_argument("--json", action="store_true", help="Output as JSON")

    # checkout
    co_p = subparsers.add_parser("checkout", help="Checkout branch across repos")
    co_p.add_argument("branch", help="Branch to checkout")
    co_p.add_argument("--repos", default=None, help="Comma-separated repo names")
    co_p.add_argument("--json", action="store_true", help="Output as JSON")

    # commit
    ci_p = subparsers.add_parser("commit", help="Commit staged changes across repos")
    ci_p.add_argument("-m", "--message", required=True, help="Commit message")
    ci_p.add_argument("--repos", default=None, help="Comma-separated repo names")
    ci_p.add_argument("--json", action="store_true", help="Output as JSON")

    # log
    log_p = subparsers.add_parser("log", help="Interleaved log across repos")
    log_p.add_argument("-n", "--count", type=int, default=20, help="Max entries")
    log_p.add_argument("--feature", default=None, help="Show log for feature branch")
    log_p.add_argument("--json", action="store_true", help="Output as JSON")

    # branch (with subcommands)
    branch_p = subparsers.add_parser("branch", help="Branch operations across repos")
    branch_sub = branch_p.add_subparsers(dest="branch_command")

    bl = branch_sub.add_parser("list", help="List branches")
    bl.add_argument("--json", action="store_true", help="Output as JSON")

    bd = branch_sub.add_parser("delete", help="Delete a branch")
    bd.add_argument("name", help="Branch to delete")
    bd.add_argument("--force", action="store_true", help="Force delete")
    bd.add_argument("--repos", default=None, help="Comma-separated repo names")
    bd.add_argument("--json", action="store_true", help="Output as JSON")

    br = branch_sub.add_parser("rename", help="Rename a branch")
    br.add_argument("old", help="Current branch name")
    br.add_argument("new", help="New branch name")
    br.add_argument("--repos", default=None, help="Comma-separated repo names")
    br.add_argument("--json", action="store_true", help="Output as JSON")

    # stash (with subcommands)
    stash_p = subparsers.add_parser("stash", help="Stash operations across repos")
    stash_sub = stash_p.add_subparsers(dest="stash_command")

    ss = stash_sub.add_parser("save", help="Stash changes")
    ss.add_argument("-m", "--message", default="", help="Stash message")
    ss.add_argument("--repos", default=None, help="Comma-separated repo names")
    ss.add_argument("--json", action="store_true", help="Output as JSON")

    sp = stash_sub.add_parser("pop", help="Pop stash")
    sp.add_argument("--index", type=int, default=0, help="Stash index")
    sp.add_argument("--repos", default=None, help="Comma-separated repo names")
    sp.add_argument("--json", action="store_true", help="Output as JSON")

    sl = stash_sub.add_parser("list", help="List stashes")
    sl.add_argument("--json", action="store_true", help="Output as JSON")

    sd = stash_sub.add_parser("drop", help="Drop stash")
    sd.add_argument("--index", type=int, default=0, help="Stash index")
    sd.add_argument("--repos", default=None, help="Comma-separated repo names")
    sd.add_argument("--json", action="store_true", help="Output as JSON")

    # worktree
    wt_p = subparsers.add_parser("worktree", help="Worktree info for repos")
    wt_p.add_argument("--json", action="store_true", help="Output as JSON")

    # code (IDE launcher)
    code_p = subparsers.add_parser("code", help="Open VS Code for feature or workspace")
    code_p.add_argument("target", help="Feature name, or '.' for whole workspace")
    code_p.add_argument("--json", action="store_true", help="Output paths as JSON")

    # cursor (IDE launcher)
    cursor_p = subparsers.add_parser("cursor", help="Open Cursor for feature or workspace")
    cursor_p.add_argument("target", help="Feature name, or '.' for whole workspace")
    cursor_p.add_argument("--json", action="store_true", help="Output paths as JSON")

    # fork (IDE launcher)
    fork_p = subparsers.add_parser("fork", help="Open Fork.app for feature or workspace")
    fork_p.add_argument("target", help="Feature name, or '.' for whole workspace")
    fork_p.add_argument("--json", action="store_true", help="Output paths as JSON")

    # stage (context-aware add + commit)
    stage_p = subparsers.add_parser("stage", help="Stage + commit in current feature context")
    stage_p.add_argument("message", help="Commit message")
    stage_p.add_argument("--json", action="store_true", help="Output as JSON")

    # context (debug)
    ctx_p = subparsers.add_parser("context", help="Show detected canopy context (debug)")
    ctx_p.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {
        "init": cmd_init,
        "status": cmd_status,
        "sync": cmd_sync,
        "checkout": cmd_checkout,
        "commit": cmd_commit,
        "log": cmd_log,
        "worktree": cmd_worktree_list,
        "code": cmd_code,
        "cursor": cmd_cursor,
        "fork": cmd_fork,
        "stage": cmd_stage,
        "context": cmd_context,
    }

    if args.command == "feature":
        if not args.feature_command:
            feature_p.print_help()
            sys.exit(0)
        feature_commands = {
            "create": cmd_feature_create,
            "list": cmd_feature_list,
            "switch": cmd_feature_switch,
            "diff": cmd_feature_diff,
            "status": cmd_feature_status,
        }
        feature_commands[args.feature_command](args)
    elif args.command == "branch":
        if not args.branch_command:
            branch_p.print_help()
            sys.exit(0)
        branch_commands = {
            "list": cmd_branch_list,
            "delete": cmd_branch_delete,
            "rename": cmd_branch_rename,
        }
        branch_commands[args.branch_command](args)
    elif args.command == "stash":
        if not args.stash_command:
            stash_p.print_help()
            sys.exit(0)
        stash_commands = {
            "save": cmd_stash_save,
            "pop": cmd_stash_pop,
            "list": cmd_stash_list,
            "drop": cmd_stash_drop,
        }
        stash_commands[args.stash_command](args)
    elif args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
