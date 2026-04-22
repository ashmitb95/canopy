"""
Canopy CLI — workspace-first development orchestrator.

Commands:
    init                         Auto-detect repos, generate canopy.toml
    status                       Cross-repo workspace status
    feature create <name>        Create a feature lane across repos
    feature list                 List active feature lanes
    feature switch <name>        Checkout feature branch in all repos
    feature diff <name>          Aggregate diff for a feature lane
    feature status <name>        Detailed feature lane status
    sync                         Pull + rebase across all repos
"""
from __future__ import annotations

import argparse
import json
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

    try:
        lane = coordinator.create(args.name, repos)
    except (ValueError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        _print_json(lane.to_dict())
        return

    print(f"Created feature lane: {lane.name}")
    print(f"  Repos: {', '.join(lane.repos)}")
    print(f"\nSwitch to it with: canopy feature switch {lane.name}")


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

    for repo, result in results.items():
        status = "ok" if result is True else f"failed: {result}"
        print(f"  {repo}: {status}")


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

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {
        "init": cmd_init,
        "status": cmd_status,
        "sync": cmd_sync,
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
        # Inherit --json from parent parser if set there
        if hasattr(args, "json") and not getattr(args, "json", False):
            pass  # already False
        feature_commands[args.feature_command](args)
    elif args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
