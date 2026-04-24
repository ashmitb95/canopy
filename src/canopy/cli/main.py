"""
Canopy CLI — workspace-first development orchestrator.

Commands:
    init                         Auto-detect repos, generate canopy.toml
    status                       Cross-repo workspace status
    checkout <branch>            Checkout branch across repos
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
    list                         List all feature lanes
    switch <name>                Switch to a feature lane
    preflight                   Context-aware add + run hooks (from worktree dir)
    review <feature>             Fetch PR comments + run pre-commit + preflight
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
    from .ui import console, spinner, print_error, print_warning

    root = Path(args.path).resolve() if args.path else Path.cwd().resolve()

    # Check if canopy.toml already exists
    toml_path = root / "canopy.toml"
    if toml_path.exists() and not args.force:
        print_error(f"canopy.toml already exists at [path]{toml_path}[/]")
        console.print(f"  [muted]Use [info]--force[/] to overwrite.[/]")
        sys.exit(1)

    is_reinit = toml_path.exists() and args.force
    scan_msg = "Rescanning workspace..." if is_reinit else "Scanning for repos..."

    with spinner(scan_msg):
        repos = discover_repos(root)

    if not repos:
        print_error(f"No Git repositories found in [path]{root}[/]")
        sys.exit(1)

    toml_content = generate_toml(root, workspace_name=args.name)

    if is_reinit:
        print_warning("Overwriting existing canopy.toml")

    if args.json:
        all_dirs = [d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")]
        skipped = [d.name for d in all_dirs if not (d / ".git").exists()]
        # Detect existing feature worktrees
        worktrees_dir = root / ".canopy" / "worktrees"
        active_worktrees = {}
        if worktrees_dir.is_dir():
            for feat_dir in worktrees_dir.iterdir():
                if feat_dir.is_dir():
                    active_worktrees[feat_dir.name] = sorted(
                        d.name for d in feat_dir.iterdir() if d.is_dir()
                    )
        _print_json({
            "root": str(root),
            "repos": [{
                "name": r.name, "path": r.path, "role": r.role, "lang": r.lang,
                "is_worktree": r.is_worktree, "worktree_main": r.worktree_main,
            } for r in repos],
            "skipped": skipped,
            "active_worktrees": active_worktrees,
            "toml": toml_content,
        })
        return

    if args.dry_run:
        print(toml_content)
        return

    from .ui import console, print_success, print_warning, separator, SYM_ARROW, SYM_CHECK

    toml_path.write_text(toml_content)

    # Install drift-tracking post-checkout hooks in each non-worktree repo.
    # Worktrees inherit hooks from their main repo via commondir.
    hook_results = _install_hooks_for_repos(root, repos)

    # Count non-git dirs that were skipped
    all_dirs = [d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")]
    skipped = [d.name for d in all_dirs if not (d / ".git").exists()]

    console.print()
    print_success(f"Created [path]{toml_path}[/]")
    console.print()
    console.print(f"  [header]Found {len(repos)} repos[/]")

    for r in repos:
        tags = []
        if r.role:
            tags.append(r.role)
        if r.lang:
            tags.append(r.lang)
        if r.is_worktree:
            tags.append(f"worktree {SYM_ARROW} {r.worktree_main}")
        tag_str = f"  [muted]{', '.join(tags)}[/]" if tags else ""
        console.print(f"  [repo]{r.name}[/]{tag_str}")

    if skipped:
        console.print(f"  [muted]Skipped {len(skipped)} non-git dirs: {', '.join(skipped)}[/]")

    if hook_results:
        installed = [h for h in hook_results if h["action"] in ("installed", "reinstalled")]
        chained = [h for h in hook_results if h["action"] == "chained_existing"]
        if installed or chained:
            console.print()
            console.print(f"  [header]Drift hooks ({len(installed) + len(chained)})[/]")
            for h in installed + chained:
                note = "" if h["action"] == "installed" else f" [muted]({h['action']})[/]"
                console.print(f"  [repo]{h['repo']}[/]{note}")

    # Report existing feature worktrees under .canopy/
    canopy_dir = root / ".canopy"
    worktrees_dir = canopy_dir / "worktrees"
    if worktrees_dir.is_dir():
        features_with_wt = sorted(
            d.name for d in worktrees_dir.iterdir() if d.is_dir()
        )
        if features_with_wt:
            console.print()
            console.print(f"  [header]Active worktrees ({len(features_with_wt)})[/]")
            for feat in features_with_wt:
                feat_dir = worktrees_dir / feat
                wt_repos = sorted(
                    d.name for d in feat_dir.iterdir() if d.is_dir()
                )
                console.print(f"  [feature]{feat}[/] [muted]{SYM_ARROW}[/] {', '.join(wt_repos)}")
    console.print()


def cmd_status(args: argparse.Namespace) -> None:
    """Show cross-repo workspace status."""
    from .ui import console, separator, SYM_BRANCH

    workspace = _load_workspace()
    workspace.refresh()

    if args.json:
        _print_json(workspace.to_dict())
        return

    console.print()
    console.print(f"  [header]{workspace.config.name}[/]  [path]{workspace.config.root}[/]")
    separator()

    for state in workspace.repos:
        role = f"  [muted]{state.config.role}[/]" if state.config.role else ""
        console.print(f"\n  [repo]{state.config.name}[/]{role}")

        # Branch line with status indicators
        parts = []
        if state.is_dirty:
            parts.append(f"[dirty]{state.dirty_count} dirty[/]")
        if state.ahead_of_default:
            parts.append(f"[ahead]↑{state.ahead_of_default}[/]")
        if state.behind_default:
            parts.append(f"[behind]↓{state.behind_default}[/]")
        status_str = f"  {' '.join(parts)}" if parts else ""

        console.print(f"    {SYM_BRANCH} [branch]{state.current_branch}[/]{status_str}")
        console.print(f"    [muted]{state.head_sha}[/]")

    features = workspace.active_features()
    if features:
        separator()
        feat_str = "  ".join(f"[feature]{f}[/]" for f in features)
        console.print(f"  Active features: {feat_str}")

    console.print()


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
    from .ui import console, separator, SYM_LINK

    workspace = _load_workspace()
    from ..features.coordinator import FeatureCoordinator

    coordinator = FeatureCoordinator(workspace)
    lanes = coordinator.list_active()

    if args.json:
        _print_json([lane.to_dict() for lane in lanes])
        return

    if not lanes:
        console.print()
        console.print("  [muted]No active feature lanes.[/]")
        console.print(f"  [muted]Create one with:[/] [info]canopy worktree <name>[/]")
        console.print()
        return

    console.print()
    console.print(f"  [header]Feature Lanes ({len(lanes)})[/]")

    for lane in lanes:
        separator()
        linear_str = ""
        if lane.linear_issue:
            title_bit = f" — {lane.linear_title}" if lane.linear_title else ""
            linear_str = f"  [linear]{SYM_LINK} {lane.linear_issue}{title_bit}[/]"
        console.print(f"  [feature]{lane.name}[/]{linear_str}")

        for repo_name, state in lane.repo_states.items():
            if "error" in state:
                console.print(f"    [repo]{repo_name}[/]  [error]error — {state['error']}[/]")
                continue
            if not state.get("has_branch"):
                console.print(f"    [repo]{repo_name}[/]  [muted]no branch[/]")
                continue
            parts = []
            if state.get("ahead"):
                parts.append(f"[ahead]↑{state['ahead']}[/]")
            if state.get("behind"):
                parts.append(f"[behind]↓{state['behind']}[/]")
            if state.get("dirty"):
                parts.append("[dirty]dirty[/]")
            if state.get("changed_file_count"):
                parts.append(f"[muted]{state['changed_file_count']} files[/]")
            status = " ".join(parts) if parts else "[clean]up to date[/]"
            console.print(f"    [repo]{repo_name}[/]  {status}")

    console.print()


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


def cmd_feature_changes(args: argparse.Namespace) -> None:
    """Show per-file change status (M/A/D/?) for each repo in a feature."""
    workspace = _load_workspace()
    from ..features.coordinator import FeatureCoordinator

    coordinator = FeatureCoordinator(workspace)

    try:
        result = coordinator.feature_changes(args.name)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        _print_json(result)
        return

    print(f"\n  Feature: {result['feature']}")
    print(f"  {'─' * 60}")

    for repo_name, data in result["repos"].items():
        if data.get("error"):
            print(f"\n  {repo_name}: error — {data['error']}")
            continue
        if not data.get("has_branch"):
            print(f"\n  {repo_name}: (no branch)")
            continue
        changes = data.get("changes", [])
        print(f"\n  {repo_name} ({len(changes)} change{'s' if len(changes) != 1 else ''})")
        for c in changes:
            print(f"    {c['status']}  {c['path']}")

    print()


def cmd_feature_status(args: argparse.Namespace) -> None:
    """Show detailed feature lane status."""
    from .ui import console, separator, print_success, SYM_CHECK, SYM_CROSS, SYM_LINK

    workspace = _load_workspace()
    from ..features.coordinator import FeatureCoordinator

    coordinator = FeatureCoordinator(workspace)

    try:
        lane = coordinator.status(args.name)
    except ValueError as e:
        from .ui import print_error
        print_error(str(e))
        sys.exit(1)

    if args.json:
        _print_json(lane.to_dict())
        return

    console.print()
    linear_str = ""
    if lane.linear_issue:
        title_bit = f" — {lane.linear_title}" if lane.linear_title else ""
        linear_str = f"  [linear]{SYM_LINK} {lane.linear_issue}{title_bit}[/]"
    console.print(f"  [feature]{lane.name}[/]{linear_str}")
    console.print(f"  [muted]status: {lane.status}[/]")
    if lane.created_at:
        console.print(f"  [muted]created: {lane.created_at}[/]")
    separator()

    for repo_name, state in lane.repo_states.items():
        if "error" in state:
            console.print(f"\n  [repo]{repo_name}[/]  [error]error — {state['error']}[/]")
            continue
        if not state.get("has_branch"):
            console.print(f"\n  [repo]{repo_name}[/]  [muted]no branch[/]")
            continue

        parts = []
        if state.get("ahead"):
            parts.append(f"[ahead]↑{state['ahead']} ahead[/]")
        if state.get("behind"):
            parts.append(f"[behind]↓{state['behind']} behind[/]")
        if state.get("dirty"):
            parts.append("[dirty]uncommitted changes[/]")
        divergence = "  ".join(parts) if parts else "[clean]up to date[/]"

        console.print(f"\n  [repo]{repo_name}[/]  {divergence}")
        files = state.get("changed_files", [])
        if files:
            console.print(f"    [muted]files ({len(files)}):[/]")
            for f in files[:8]:
                console.print(f"    [path]{f}[/]")
            if len(files) > 8:
                console.print(f"    [muted]... and {len(files) - 8} more[/]")

    # Merge readiness
    readiness = coordinator.merge_readiness(lane.name)
    separator()
    if readiness["ready"]:
        console.print(f"  [success]{SYM_CHECK} Merge ready[/]")
    else:
        console.print(f"  [error]{SYM_CROSS} Not merge ready[/]")
        for issue in readiness["issues"]:
            console.print(f"    [muted]•[/] {issue}")

    console.print()


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


def cmd_worktree(args: argparse.Namespace) -> None:
    """Dispatch: list worktrees or create a new one."""
    if args.name:
        cmd_worktree_create(args)
    else:
        cmd_worktree_list(args)


def cmd_worktree_create(args: argparse.Namespace) -> None:
    """Create a feature with worktrees, optionally linked to a Linear issue."""
    from .ui import console, spinner, print_success, print_warning, print_error, separator, SYM_ARROW, SYM_LINK

    workspace = _load_workspace()
    from ..features.coordinator import FeatureCoordinator

    name = args.name
    issue_id = args.issue
    repos = args.repos

    # ── Linear integration ──
    linear_issue = ""
    linear_title = ""
    linear_url = ""

    if issue_id:
        from ..integrations.linear import (
            is_linear_configured,
            get_issue,
            format_branch_name,
            LinearNotConfiguredError,
            LinearIssueNotFoundError,
        )
        from ..mcp.client import McpClientError

        if is_linear_configured(workspace.config.root):
            try:
                with spinner(f"Fetching {issue_id} from Linear..."):
                    issue_data = get_issue(workspace.config.root, issue_id)
                linear_issue = issue_data.get("identifier", issue_id)
                linear_title = issue_data.get("title", "")
                linear_url = issue_data.get("url", "")
                if linear_title:
                    console.print(f"  [linear]{SYM_LINK} {linear_issue}: {linear_title}[/]")
            except (LinearNotConfiguredError, LinearIssueNotFoundError, McpClientError) as e:
                print_warning(f"Could not fetch Linear issue: {e}")
                console.print(f"  [muted]Continuing without Linear link...[/]")
                linear_issue = issue_id
        else:
            print_warning(f"Linear MCP not configured — storing '{issue_id}' without fetching.")
            linear_issue = issue_id

    # ── Create the feature with worktrees ──
    coordinator = FeatureCoordinator(workspace)
    try:
        with spinner(f"Creating worktrees for {name}..."):
            lane = coordinator.create(
                name,
                repos=repos,
                use_worktrees=True,
                linear_issue=linear_issue,
                linear_title=linear_title,
                linear_url=linear_url,
            )
    except (RuntimeError,) as e:
        print_error(str(e))
        sys.exit(1)
    except ValueError as e:
        # Check if this is a worktree limit error
        from ..features.coordinator import WorktreeLimitError
        if isinstance(e, WorktreeLimitError):
            print_error(f"Worktree limit reached ({e.current}/{e.limit})")
            if e.stale:
                console.print()
                console.print(f"  [muted]Suggested cleanup:[/]")
                for s in e.stale:
                    console.print(f"    [feature]{s['name']}[/]  [muted]{s['reason']}[/]")
                console.print()
                console.print(f"  [muted]Run:[/] [info]canopy done <feature>[/]")
            else:
                console.print(f"  [muted]Run:[/] [info]canopy done <feature>[/] to free a slot")
                console.print(f"  [muted]Or:[/]  [info]canopy config max_worktrees {e.limit + 1}[/]")
        else:
            print_error(str(e))
        sys.exit(1)

    result = lane.to_dict()
    result["worktree_paths"] = coordinator.resolve_paths(name)

    if args.json:
        _print_json(result)
        return

    console.print()
    for repo_name, path in result["worktree_paths"].items():
        print_success(f"[repo]{repo_name}[/] [muted]{SYM_ARROW}[/] [path]{path}[/]")

    if linear_issue and not linear_title:
        console.print(f"\n  [linear]{SYM_LINK} {linear_issue}[/]")

    console.print()
    console.print(f"  [muted]Open in IDE:[/]")
    console.print(f"    [info]canopy code {name}[/]")
    console.print(f"    [info]canopy cursor {name}[/]")
    console.print(f"    [info]canopy fork {name}[/]")
    console.print()


def cmd_worktree_list(args: argparse.Namespace) -> None:
    """Show live worktree status — always reflects current filesystem."""
    from .ui import console, spinner, separator, SYM_BRANCH, SYM_LINK

    workspace = _load_workspace()
    from ..features.coordinator import FeatureCoordinator

    coordinator = FeatureCoordinator(workspace)

    with spinner("Scanning worktrees..."):
        data = coordinator.worktrees_live()

    if args.json:
        _print_json(data)
        return

    features = data.get("features", {})
    repos_wt = data.get("repos", {})

    # Also load feature metadata for Linear links
    features_json = coordinator._load_features()

    if not features and all(
        len(r.get("worktrees", [])) <= 1 for r in repos_wt.values()
    ):
        console.print()
        console.print("  [muted]No active worktrees.[/]")
        console.print(f"  [muted]Create one with:[/] [info]canopy worktree <name>[/]")
        console.print()
        return

    # ── Feature worktrees ──
    if features:
        console.print()
        console.print(f"  [header]Worktrees ({len(features)})[/]")
        for feat_name, feat_data in features.items():
            separator()
            # Show Linear link if present
            meta = features_json.get(feat_name, {})
            linear_id = meta.get("linear_issue", "")
            linear_title = meta.get("linear_title", "")
            if linear_id:
                title_str = f" — {linear_title}" if linear_title else ""
                console.print(f"  [feature]{feat_name}[/]  [linear]{SYM_LINK} {linear_id}{title_str}[/]")
            else:
                console.print(f"  [feature]{feat_name}[/]")

            for repo_name, info in feat_data.get("repos", {}).items():
                branch = info.get("branch", "?")
                dirty = info.get("dirty", False)
                dirty_count = info.get("dirty_count", 0)
                ahead = info.get("ahead", 0)
                behind = info.get("behind", 0)

                parts = []
                if dirty:
                    parts.append(f"[dirty]{dirty_count} dirty[/]")
                if ahead:
                    parts.append(f"[ahead]↑{ahead}[/]")
                if behind:
                    parts.append(f"[behind]↓{behind}[/]")
                status_str = f"  {' '.join(parts)}" if parts else ""

                console.print(f"    [repo]{repo_name}[/]  {SYM_BRANCH} [branch]{branch}[/]{status_str}")
                console.print(f"      [path]{info.get('path', '?')}[/]")

    # ── Per-repo git worktrees (only show if repo has >1 worktree) ──
    multi_wt = {
        name: info for name, info in repos_wt.items()
        if len(info.get("worktrees", [])) > 1
    }
    if multi_wt:
        console.print()
        console.print(f"  [subheader]Git worktrees per repo[/]")
        for repo_name, info in multi_wt.items():
            separator()
            console.print(f"  [repo]{repo_name}[/]  [path]{info['main_path']}[/]")
            for wt in info["worktrees"]:
                branch = wt.get("branch", "(detached)")
                console.print(f"    [path]{wt['path']}[/]  [branch]\\[{branch}][/]")

    console.print()


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

    import time

    for i, p in enumerate(paths):
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
        # Small delay between opens so Fork can register each repo
        if i < len(paths) - 1:
            time.sleep(0.5)


def cmd_preflight(args: argparse.Namespace) -> None:
    """Context-aware pre-commit quality gate.

    Detects which feature/repos you're in, stages all changes (git add -A),
    runs pre-commit hooks, and reports results. Does NOT commit — that's
    your job when you're satisfied.

    When run from inside a feature worktree directory, checks all repo
    worktrees in that feature.

    When run from inside a single repo worktree, checks just that repo.
    """
    from ..workspace.context import detect_context
    from ..git import repo as git_repo
    from ..integrations.precommit import run_precommit

    ctx = detect_context()

    if ctx.context_type == "unknown":
        print("Error: can't detect canopy context from current directory.", file=sys.stderr)
        print("Run this from inside a feature worktree or a workspace repo.", file=sys.stderr)
        sys.exit(1)

    if not ctx.repo_paths:
        print("Error: no repos found in current context.", file=sys.stderr)
        sys.exit(1)

    results: dict[str, dict] = {}
    all_passed = True

    for repo_path, repo_name in zip(ctx.repo_paths, ctx.repo_names):
        # Check if there are any changes
        status = git_repo.status_porcelain(repo_path)
        if not status:
            results[repo_name] = {"status": "clean", "hooks": None}
            continue

        # Stage everything so hooks can inspect staged changes
        try:
            git_repo._run(["add", "-A"], cwd=repo_path)
        except git_repo.GitError as e:
            results[repo_name] = {"status": "error", "error": str(e), "hooks": None}
            all_passed = False
            continue

        # Run pre-commit hooks
        hook_result = run_precommit(repo_path)
        passed = hook_result["passed"]
        if not passed:
            all_passed = False

        dirty_count = len(status.strip().splitlines())
        results[repo_name] = {
            "status": "staged" if passed else "hooks_failed",
            "dirty_count": dirty_count,
            "hooks": hook_result,
        }

    if args.json:
        _print_json({
            "feature": ctx.feature,
            "context_type": ctx.context_type,
            "all_passed": all_passed,
            "results": results,
        })
        return

    from .ui import console, separator, SYM_CHECK, SYM_DOT, SYM_CROSS

    console.print()
    if ctx.feature:
        console.print(f"  [feature]{ctx.feature}[/]  preflight")
    else:
        console.print(f"  preflight")
    separator()

    for repo, result in results.items():
        status = result["status"]
        if status == "clean":
            console.print(f"  [repo]{repo}[/]  [muted]{SYM_DOT} clean[/]")
        elif status == "error":
            console.print(f"  [repo]{repo}[/]  [error]{SYM_CROSS} {result['error']}[/]")
        elif status == "hooks_failed":
            dirty = result["dirty_count"]
            console.print(f"  [repo]{repo}[/]  [error]{SYM_CROSS} hooks failed[/]  [muted]{dirty} staged[/]")
            # Show hook output indented
            hook_output = result["hooks"]["output"]
            if hook_output:
                for line in hook_output.splitlines()[:20]:
                    console.print(f"    [muted]{line}[/]")
                if len(hook_output.splitlines()) > 20:
                    console.print(f"    [muted]... ({len(hook_output.splitlines()) - 20} more lines)[/]")
        else:
            # staged, hooks passed
            dirty = result["dirty_count"]
            hook_type = result["hooks"]["type"] if result["hooks"] else "none"
            if hook_type == "none":
                console.print(f"  [repo]{repo}[/]  [success]{SYM_CHECK} {dirty} staged[/]  [muted]no hooks[/]")
            else:
                console.print(f"  [repo]{repo}[/]  [success]{SYM_CHECK} {dirty} staged[/]  [success]hooks passed[/]")

    console.print()
    if all_passed:
        console.print("  [success]Ready to commit.[/]")
    else:
        console.print("  [error]Fix hook failures, then run preflight again.[/]")
    console.print()
    print()


def cmd_review(args: argparse.Namespace) -> None:
    """Fetch PR review comments and run preflight.

    Full workflow:
    1. Check if PRs exist for the feature
    2. Fetch unresolved review comments
    3. Run pre-commit hooks + stage changes (preflight)
    """
    from .ui import console, spinner, separator, print_success, print_warning, print_error, SYM_CHECK, SYM_CROSS, SYM_LINK
    from ..integrations.github import GitHubNotConfiguredError, PullRequestNotFoundError

    workspace = _load_workspace()
    from ..features.coordinator import FeatureCoordinator

    coordinator = FeatureCoordinator(workspace)
    feature = args.name

    # ── Step 1: Check PR status ──
    try:
        with spinner(f"Checking PRs for {feature}..."):
            status = coordinator.review_status(feature)
    except GitHubNotConfiguredError as e:
        print_error(str(e))
        sys.exit(1)
    except ValueError as e:
        print_error(str(e))
        sys.exit(1)

    if not status["has_prs"]:
        print_error(f"No open PRs found for feature '{feature}'")
        console.print(f"  [muted]Push your branch and create a PR first.[/]")
        if args.json:
            _print_json(status)
        sys.exit(1)

    # ── Step 2: Fetch comments ──
    try:
        with spinner(f"Fetching review comments..."):
            comments_data = coordinator.review_comments(feature)
    except PullRequestNotFoundError as e:
        print_error(str(e))
        sys.exit(1)

    # ── Step 3: Run pre-commit + stage ──
    prep_data = None
    if not args.comments_only:
        with spinner(f"Running pre-commit hooks..."):
            prep_data = coordinator.review_prep(
                feature, message=args.message or "",
            )

    if args.json:
        result = {
            "review_status": status,
            "comments": comments_data,
        }
        if prep_data:
            result["prep"] = prep_data
        _print_json(result)
        return

    # ── Display PR status ──
    console.print()
    console.print(f"  [header]Review: {feature}[/]")

    for repo_name, info in status["repos"].items():
        pr = info.get("pr")
        if pr:
            console.print(
                f"  [repo]{repo_name}[/]  "
                f"[linear]{SYM_LINK} #{pr['number']}[/] {pr['title']}"
            )
            console.print(f"    [path]{pr.get('url', '')}[/]")
        elif "error" in info:
            console.print(f"  [repo]{repo_name}[/]  [error]{info['error']}[/]")
        else:
            console.print(f"  [repo]{repo_name}[/]  [muted]no PR[/]")

    # ── Display comments ──
    separator()
    total = comments_data.get("total_comments", 0)
    if total == 0:
        print_success("No unresolved review comments")
    else:
        console.print(f"  [warning]{total} unresolved comment{'s' if total != 1 else ''}[/]")
        console.print()

        for repo_name, repo_data in comments_data.get("repos", {}).items():
            comments = repo_data.get("comments", [])
            if not comments:
                continue

            console.print(f"  [repo]{repo_name}[/]  [muted]#{repo_data.get('pr_number', '?')}[/]")

            # Group by file
            by_file: dict[str, list] = {}
            for c in comments:
                path = c.get("path") or "(general)"
                by_file.setdefault(path, []).append(c)

            for filepath, file_comments in by_file.items():
                console.print(f"    [path]{filepath}[/]")
                for c in file_comments:
                    line = c.get("line")
                    line_str = f"L{line}" if line else ""
                    author = c.get("author", "")
                    body = c.get("body", "").split("\n")[0][:120]
                    console.print(
                        f"      [muted]{line_str}[/] "
                        f"[info]{author}[/]: {body}"
                    )

    # ── Display prep results ──
    if prep_data:
        separator()
        if prep_data["all_passed"]:
            print_success("Pre-commit hooks passed")
        else:
            print_warning("Pre-commit hooks failed in some repos")

        for repo_name, info in prep_data["repos"].items():
            pc = info.get("precommit", {})
            pc_type = pc.get("type", "none")
            passed = pc.get("passed", True)
            staged = info.get("staged", False)
            dirty = info.get("dirty_count", 0)

            status_parts = []
            if pc_type != "none":
                icon = SYM_CHECK if passed else SYM_CROSS
                style = "success" if passed else "error"
                status_parts.append(f"[{style}]{icon} hooks[/]")
            if staged:
                status_parts.append(f"[ahead]{dirty} staged[/]")
            elif dirty == 0:
                status_parts.append("[muted]clean[/]")

            console.print(
                f"  [repo]{repo_name}[/]  {' '.join(status_parts)}"
            )

            if not passed and pc.get("output"):
                # Show first few lines of hook output
                for line in pc["output"].split("\n")[:5]:
                    console.print(f"    [muted]{line}[/]")

    console.print()


def cmd_list(args: argparse.Namespace) -> None:
    """List all feature lanes — quick overview of what exists."""
    from .ui import console, separator, SYM_BRANCH, SYM_LINK, SYM_ARROW

    workspace = _load_workspace()
    from ..features.coordinator import FeatureCoordinator

    coordinator = FeatureCoordinator(workspace)
    lanes = coordinator.list_active()

    if args.json:
        _print_json([lane.to_dict() for lane in lanes])
        return

    if not lanes:
        console.print()
        console.print("  [muted]No features.[/] Create one with [info]canopy worktree <name>[/]")
        console.print()
        return

    console.print()
    for lane in lanes:
        # Feature name + Linear link on one line
        linear_str = ""
        if lane.linear_issue:
            title_bit = f" {lane.linear_title}" if lane.linear_title else ""
            linear_str = f"  [linear]{SYM_LINK} {lane.linear_issue}{title_bit}[/]"

        console.print(f"  [feature]{lane.name}[/]{linear_str}")

        # Per-repo: branch context line
        for repo_name, state in lane.repo_states.items():
            if "error" in state or not state.get("has_branch"):
                console.print(f"    [muted]{repo_name}[/]  [muted]no branch[/]")
                continue

            parts = [f"    [repo]{repo_name}[/]"]
            # Dirty count
            dirty_count = state.get("changed_file_count", 0)
            if state.get("dirty") and dirty_count:
                parts.append(f"[dirty]{dirty_count} dirty[/]")
            elif state.get("dirty"):
                parts.append("[dirty]*[/]")
            # Ahead/behind
            if state.get("ahead"):
                parts.append(f"[ahead]↑{state['ahead']}[/]")
            if state.get("behind"):
                parts.append(f"[behind]↓{state['behind']}[/]")
            # Worktree path
            wt_path = state.get("worktree_path")
            if wt_path:
                parts.append(f"[path]{wt_path}[/]")

            console.print("  ".join(parts))

    console.print()


def cmd_switch(args: argparse.Namespace) -> None:
    """Switch to a feature lane — checkout branches across repos."""
    from .ui import console, print_success, print_error, print_warning, SYM_ARROW, SYM_CHECK, SYM_BRANCH, SYM_LINK

    workspace = _load_workspace()
    from ..features.coordinator import FeatureCoordinator

    coordinator = FeatureCoordinator(workspace)
    name = args.name

    try:
        result = coordinator.switch(name)
    except ValueError as e:
        print_error(str(e))
        sys.exit(1)

    if args.json:
        _print_json(result)
        return

    feature = result["feature"]
    alias = result.get("alias")

    # Try to get PR info (best-effort, don't fail if GitHub isn't configured)
    pr_map: dict[str, dict] = {}
    try:
        review = coordinator.review_status(feature)
        for repo_name, info in review.get("repos", {}).items():
            pr = info.get("pr")
            if pr:
                pr_map[repo_name] = pr
    except Exception:
        pass  # GitHub not configured or no PRs — that's fine

    console.print()

    # Show alias resolution
    if alias:
        console.print(f"  [muted]{alias} {SYM_ARROW}[/] [feature]{feature}[/]")
        console.print()

    has_worktree = False
    for repo_name, info in result["repos"].items():
        if not info["ok"]:
            print_warning(f"[repo]{repo_name}[/]  {info.get('error', 'failed')}")
            continue

        # Line 1: repo + path
        path = info["path"]
        is_wt = info.get("worktree", False)
        if is_wt:
            has_worktree = True
        print_success(f"[repo]{repo_name}[/]  [muted]{SYM_ARROW}[/] [path]{path}[/]")

        # Line 2: branch + dirty + ahead/behind + PR
        parts = [f"    [muted]{SYM_BRANCH}[/] [branch]{info['branch']}[/]"]
        dirty = info.get("dirty_count", 0)
        if dirty:
            parts.append(f"[dirty]{dirty} dirty[/]")
        ahead = info.get("ahead", 0)
        behind = info.get("behind", 0)
        if ahead:
            parts.append(f"[ahead]↑{ahead}[/]")
        if behind:
            parts.append(f"[behind]↓{behind}[/]")
        pr = pr_map.get(repo_name)
        if pr:
            parts.append(f"[linear]{SYM_LINK} #{pr.get('number', '')}[/]")
        console.print("  ".join(parts))

    if has_worktree:
        console.print()
        console.print(f"  [muted]Open in IDE:[/]")
        console.print(f"    [info]canopy code {feature}[/]")
        console.print(f"    [info]canopy cursor {feature}[/]")
    console.print()


def cmd_done(args: argparse.Namespace) -> None:
    """Clean up a completed feature — remove worktrees, branches, archive."""
    from .ui import console, spinner, print_success, print_error, print_warning, separator, SYM_CHECK, SYM_CROSS, SYM_ARROW

    workspace = _load_workspace()
    from ..features.coordinator import FeatureCoordinator

    coordinator = FeatureCoordinator(workspace)
    name = args.name

    # Resolve alias for display
    resolved = coordinator._resolve_name(name)

    try:
        with spinner(f"Cleaning up {resolved}..."):
            result = coordinator.done(name, force=args.force)
    except ValueError as e:
        print_error(str(e))
        sys.exit(1)

    if args.json:
        _print_json(result)
        return

    feature = result["feature"]
    console.print()

    # Show alias resolution
    if name != feature:
        console.print(f"  [muted]{name} {SYM_ARROW}[/] [feature]{feature}[/]")
        console.print()

    console.print(f"  [header]Done: {feature}[/]")

    wt = result.get("worktrees_removed", {})
    if wt:
        separator()
        console.print(f"  [muted]Worktrees removed:[/]")
        for repo, path in wt.items():
            if "error" in str(path):
                console.print(f"    [repo]{repo}[/]  [error]{path}[/]")
            else:
                print_success(f"[repo]{repo}[/]  [muted]{path}[/]")

    br = result.get("branches_deleted", {})
    if br:
        separator()
        console.print(f"  [muted]Branches deleted:[/]")
        for repo, status in br.items():
            if status == "ok":
                print_success(f"[repo]{repo}[/]  [branch]{feature}[/]  [muted]deleted[/]")
            elif status == "no branch":
                console.print(f"    [repo]{repo}[/]  [muted]no branch[/]")
            else:
                print_warning(f"[repo]{repo}[/]  {status}")

    if result.get("archived"):
        separator()
        print_success("Archived in features.json")

    console.print()


def cmd_config(args: argparse.Namespace) -> None:
    """Read or write workspace settings in canopy.toml."""
    from .ui import console, print_success, print_error
    from ..workspace.config import (
        get_config_value, set_config_value, get_all_config,
        ConfigNotFoundError, ConfigError, WORKSPACE_SETTINGS,
    )

    # Find workspace root
    from ..workspace.config import _find_config
    try:
        toml_path = _find_config()
        root = toml_path.parent
    except ConfigNotFoundError as e:
        print_error(str(e))
        sys.exit(1)

    key = args.key
    value = args.value

    try:
        if key is None:
            # Show all settings
            settings = get_all_config(root)
            if args.json:
                _print_json(settings)
                return
            console.print()
            for k, v in settings.items():
                display = v if v is not None else "[muted]not set[/]"
                console.print(f"  [info]{k}[/] = {display}")
            console.print()

        elif value is None:
            # Get a single setting
            v = get_config_value(root, key)
            if args.json:
                _print_json({"key": key, "value": v})
                return
            if v is not None:
                console.print(f"  {v}")
            else:
                console.print(f"  [muted]not set[/]")

        else:
            # Set a value
            coerced = set_config_value(root, key, value)
            if args.json:
                _print_json({"key": key, "value": coerced})
                return
            print_success(f"[info]{key}[/] = {coerced}")

    except (ConfigNotFoundError, ConfigError) as e:
        print_error(str(e))
        sys.exit(1)


def _install_hooks_for_repos(root: Path, repos) -> list[dict]:
    """Install canopy post-checkout hooks in each non-worktree repo.

    Worktrees share their main repo's hooks dir, so they're skipped here.
    Returns a list of {repo, action, path} dicts (one per non-worktree repo).
    """
    from ..git.hooks import install_hook

    results = []
    for r in repos:
        if r.is_worktree:
            continue
        repo_abs = (root / r.path).resolve() if not Path(r.path).is_absolute() else Path(r.path)
        try:
            res = install_hook(repo_abs, r.name, root)
            results.append({"repo": res.repo, "action": res.action, "path": res.path})
        except Exception as e:
            results.append({"repo": r.name, "action": "failed", "error": str(e)})
    return results


def cmd_hooks(args: argparse.Namespace) -> None:
    """Manage drift-tracking post-checkout hooks across the workspace."""
    from ..git.hooks import install_hook, uninstall_hook, hook_status, read_heads_state
    from .ui import console, print_success, print_error, print_warning

    workspace = _load_workspace()
    root = workspace.config.root

    sub = getattr(args, "hooks_command", None) or "status"
    results: list[dict] = []

    for state in workspace.repos:
        if state.config.is_worktree:
            continue
        repo_abs = state.abs_path
        try:
            if sub == "install":
                r = install_hook(repo_abs, state.config.name, root)
                results.append({"repo": r.repo, "action": r.action, "path": r.path})
            elif sub == "uninstall":
                r = uninstall_hook(repo_abs, state.config.name)
                results.append({
                    "repo": r.repo, "action": r.action, "reason": r.reason,
                })
            elif sub == "status":
                s = hook_status(repo_abs)
                results.append({"repo": state.config.name, **s})
            else:
                print_error(f"Unknown hooks subcommand: {sub}")
                sys.exit(2)
        except Exception as e:
            results.append({"repo": state.config.name, "action": "failed", "error": str(e)})

    if args.json:
        payload = {"command": sub, "repos": results}
        if sub == "status":
            payload["heads_state"] = read_heads_state(root)
        _print_json(payload)
        return

    console.print()
    if sub == "status":
        heads = read_heads_state(root)
        for r in results:
            mark = "[green]✓[/]" if r.get("installed") else (
                "[yellow]foreign[/]" if r.get("foreign_hook") else "[red]✗[/]"
            )
            head = heads.get(r["repo"], {})
            head_note = f"  [muted]→ {head['branch']} @ {head['sha'][:8]}[/]" if head else ""
            chained = "  [muted](chained user hook present)[/]" if r.get("chained_present") else ""
            console.print(f"  {mark}  [repo]{r['repo']}[/]{head_note}{chained}")
    else:
        for r in results:
            action = r.get("action", "unknown")
            extra = ""
            if action == "failed":
                extra = f"  [red]{r.get('error', '')}[/]"
            elif r.get("reason"):
                extra = f"  [muted]({r['reason']})[/]"
            console.print(f"  [repo]{r['repo']}[/] [muted]→[/] {action}{extra}")
    console.print()


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

    # feature changes
    fch = feature_sub.add_parser("changes", help="Per-file change status across repos")
    fch.add_argument("name", help="Feature name")
    fch.add_argument("--json", action="store_true", help="Output as JSON")

    # sync
    sync_p = subparsers.add_parser("sync", help="Pull + rebase across repos")
    sync_p.add_argument("--strategy", choices=["rebase", "merge"], default="rebase")
    sync_p.add_argument("--json", action="store_true", help="Output as JSON")

    # checkout
    co_p = subparsers.add_parser("checkout", help="Checkout branch across repos")
    co_p.add_argument("branch", help="Branch to checkout")
    co_p.add_argument("--repos", default=None, help="Comma-separated repo names")
    co_p.add_argument("--json", action="store_true", help="Output as JSON")

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
    wt_p = subparsers.add_parser(
        "worktree",
        help="Create or list worktrees (canopy worktree <name> [issue])",
    )
    wt_p.add_argument(
        "name", nargs="?", default=None,
        help="Feature name to create. Omit to list existing worktrees.",
    )
    wt_p.add_argument(
        "issue", nargs="?", default=None,
        help="Linear issue ID (e.g. ENG-123). Fetches via Linear MCP if configured.",
    )
    wt_p.add_argument(
        "--repos", nargs="+",
        help="Subset of repos (default: all)",
    )
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

    # preflight (context-aware add + hooks)
    preflight_p = subparsers.add_parser("preflight", help="Stage + run hooks (does not commit)")
    preflight_p.add_argument("--json", action="store_true", help="Output as JSON")

    # list (top-level shortcut)
    list_p = subparsers.add_parser("list", help="List all feature lanes")
    list_p.add_argument("--json", action="store_true", help="Output as JSON")

    # switch (top-level shortcut)
    switch_p = subparsers.add_parser("switch", help="Switch to a feature lane")
    switch_p.add_argument("name", help="Feature lane name")
    switch_p.add_argument("--json", action="store_true", help="Output as JSON")

    # review
    review_p = subparsers.add_parser(
        "review",
        help="Fetch PR review comments and prep for commit",
    )
    review_p.add_argument("name", help="Feature lane name")
    review_p.add_argument(
        "-m", "--message", default="",
        help="Placeholder commit message (staged but not committed)",
    )
    review_p.add_argument(
        "--comments-only", action="store_true",
        help="Only fetch comments — skip pre-commit and staging",
    )
    review_p.add_argument("--json", action="store_true", help="Output as JSON")

    # done
    done_p = subparsers.add_parser(
        "done",
        help="Clean up a feature — remove worktrees, branches, archive",
    )
    done_p.add_argument("name", help="Feature lane name")
    done_p.add_argument("--force", action="store_true", help="Remove even with dirty worktrees")
    done_p.add_argument("--json", action="store_true", help="Output as JSON")

    # config
    config_p = subparsers.add_parser(
        "config",
        help="Read or write workspace settings (canopy config [key] [value])",
    )
    config_p.add_argument("key", nargs="?", default=None, help="Setting name")
    config_p.add_argument("value", nargs="?", default=None, help="New value")
    config_p.add_argument("--json", action="store_true", help="Output as JSON")

    # context (debug)
    ctx_p = subparsers.add_parser("context", help="Show detected canopy context (debug)")
    ctx_p.add_argument("--json", action="store_true", help="Output as JSON")

    # hooks
    hooks_p = subparsers.add_parser(
        "hooks",
        help="Manage drift-tracking post-checkout hooks (install/uninstall/status)",
    )
    hooks_sub = hooks_p.add_subparsers(dest="hooks_command")
    hooks_install_p = hooks_sub.add_parser("install", help="Install hooks in all managed repos")
    hooks_install_p.add_argument("--json", action="store_true", help="Output as JSON")
    hooks_uninstall_p = hooks_sub.add_parser("uninstall", help="Remove canopy hooks; restore chained user hooks")
    hooks_uninstall_p.add_argument("--json", action="store_true", help="Output as JSON")
    hooks_status_p = hooks_sub.add_parser("status", help="Show hook + heads state per repo")
    hooks_status_p.add_argument("--json", action="store_true", help="Output as JSON")
    hooks_p.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {
        "init": cmd_init,
        "status": cmd_status,
        "sync": cmd_sync,
        "checkout": cmd_checkout,
        "log": cmd_log,
        "worktree": cmd_worktree,
        "code": cmd_code,
        "cursor": cmd_cursor,
        "fork": cmd_fork,
        "preflight": cmd_preflight,
        "list": cmd_list,
        "switch": cmd_switch,
        "review": cmd_review,
        "done": cmd_done,
        "config": cmd_config,
        "context": cmd_context,
        "hooks": cmd_hooks,
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
            "changes": cmd_feature_changes,
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
