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
    except ConfigNotFoundError:
        _print_no_workspace_error()
        sys.exit(1)

    return Workspace(config)


def _print_no_workspace_error() -> None:
    """Render the canonical 'no canopy.toml' error.

    Centralised so every workspace-scoped command prints the same helpful
    message instead of a terse "No canopy.toml found." See test-findings
    F-1: this is the first error a fresh user is likely to hit.
    """
    print("Error: no canopy.toml found here or in any parent directory.",
          file=sys.stderr)
    print(file=sys.stderr)
    print(
        "Canopy needs to be run from a workspace — a non-git directory that holds",
        file=sys.stderr,
    )
    print(
        "your repos as subdirectories along with canopy.toml. Either:",
        file=sys.stderr,
    )
    print(file=sys.stderr)
    print("  • cd into your existing workspace root, or", file=sys.stderr)
    print(
        "  • run `canopy init` from a non-git directory containing the repos to bootstrap one.",
        file=sys.stderr,
    )


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
        # Detect existing worktrees, keyed by FEATURE (slot dirs resolve their
        # occupant via slots.json — not reported as if the slot id were a feature).
        from ..workspace.discovery import summarize_worktree_dirs
        active_worktrees = summarize_worktree_dirs(root)
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

    if not args.no_agent:
        from ..agent_setup import setup_agent as _setup_agent
        agent_result = _setup_agent(root, do_skill=True, do_mcp=True, reinstall=False)
        skill = agent_result.get("skill", {})
        mcp = agent_result.get("mcp", {})
        console.print()
        console.print(f"  [header]Claude Code agent setup[/]")
        if skill.get("action") in ("installed", "reinstalled"):
            console.print(f"  skill   [success]{SYM_CHECK}[/] {skill['action']}  [muted]{skill['path']}[/]")
        else:
            note = skill.get("reason") or skill.get("action", "")
            console.print(f"  skill   [muted]· {note}[/]")
        if mcp.get("action") in ("added", "updated", "created"):
            console.print(f"  mcp     [success]{SYM_CHECK}[/] {mcp['action']}  [muted]{mcp['path']}[/]")
        else:
            note = mcp.get("reason") or mcp.get("action", "")
            console.print(f"  mcp     [muted]· {note}[/]")
        console.print(f"  [muted]Restart Claude Code to pick up the skill + MCP. Skip with --no-agent.[/]")

    # Report existing worktrees under .canopy/, keyed by feature (slot dirs
    # resolve their occupant via slots.json — see summarize_worktree_dirs).
    from ..workspace.discovery import summarize_worktree_dirs
    worktrees = summarize_worktree_dirs(root)
    if worktrees:
        console.print()
        console.print(f"  [header]Active worktrees ({len(worktrees)})[/]")
        for feat, wt_repos in sorted(worktrees.items()):
            console.print(f"  [feature]{feat}[/] [muted]{SYM_ARROW}[/] {', '.join(wt_repos)}")
    console.print()


def cmd_status(args: argparse.Namespace) -> None:
    """Show cross-repo workspace status."""
    from .ui import console, separator, spinner, SYM_BRANCH

    workspace = _load_workspace()
    with spinner("Reading workspace state…"):
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
    from .ui import spinner

    repo_count = len(workspace.repos)
    with spinner(f"Syncing {repo_count} repo{'s' if repo_count != 1 else ''}…"):
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
    # Route to the feature-tagged path when --feature is passed.
    if getattr(args, "feature", None):
        cmd_stash_save_feature(args)
        return

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
    # Route to feature-tagged pop when --feature is passed.
    if getattr(args, "feature", None):
        cmd_stash_pop_feature(args)
        return

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
    # Route to grouped list whenever --feature is passed (or always if you
    # want grouping by default; for now keep flat list as default).
    if getattr(args, "feature", None):
        cmd_stash_list_grouped(args)
        return

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
                console.print(f"  [muted]Or:[/]  [info]canopy config slots {e.limit + 1}[/]")
        else:
            print_error(str(e))
        sys.exit(1)

    result = lane.to_dict()
    result["worktree_paths"] = coordinator.resolve_paths(name)
    from ..actions import slots as _slots_mod
    _slot_id = _slots_mod.slot_for_feature(workspace, name)
    if _slot_id is not None:
        result["slot_id"] = _slot_id

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


def cmd_slots(args: argparse.Namespace) -> None:
    """Show slot occupancy: canonical + warm slots + last_touched.

    ``--json`` always returns the rich shape (single call powers the
    dashboard + agent); pretty terminal output stays compact unless
    ``--rich`` is passed.
    """
    from ..actions import slots as slots_mod
    from .ui import console

    workspace = _load_workspace()
    state = slots_mod.read_state(workspace)
    if args.json:
        from ..actions.slot_details import rich_slots
        _print_json(rich_slots(workspace))
        return
    if state is None:
        console.print()
        console.print("  [muted]No slot state yet — run `canopy switch <feature>`.[/]")
        console.print()
        return
    console.print()
    if state.canonical:
        console.print(f"  [header]Canonical:[/] [info]{state.canonical.feature}[/]"
                      f"  [muted]({state.canonical.activated_at[:16]})[/]")
    console.print(f"  [header]Slots ({len(state.slots)}/{state.slot_count}):[/]")
    for i in range(1, state.slot_count + 1):
        sid = f"worktree-{i}"
        entry = state.slots.get(sid)
        if entry:
            last = state.last_touched.get(entry.feature, "")
            console.print(f"    {sid}: [info]{entry.feature}[/]"
                          f"  [muted]touched {last[:16]}[/]")
        else:
            console.print(f"    {sid}: [muted]<empty>[/]")
    console.print()


def cmd_slot_load(args: argparse.Namespace) -> None:
    """Warm a cold feature into a slot without changing canonical."""
    from ..actions.slot_load import slot_load
    from .ui import console

    workspace = _load_workspace()
    result = slot_load(
        workspace, args.feature,
        slot_id=args.slot_id, replace=args.replace, bootstrap=args.bootstrap,
    )
    if args.json:
        _print_json(result)
        return
    console.print(f"[ok]Loaded[/] [info]{result['feature']}[/] into [info]{result['slot_id']}[/]")
    if result.get("evicted"):
        console.print(f"  Evicted: [muted]{result['evicted']['feature']}[/]")


def cmd_slot_clear(args: argparse.Namespace) -> None:
    """Evict a slot's occupant to cold."""
    from ..actions.slot_load import slot_clear
    from .ui import console

    workspace = _load_workspace()
    result = slot_clear(workspace, args.slot_id)
    if args.json:
        _print_json(result)
        return
    console.print(f"[ok]Cleared[/] {result['slot_id']}: evicted [info]{result['feature']}[/]")


def cmd_slot_swap(args: argparse.Namespace) -> None:
    """Exchange occupants of two slots."""
    from ..actions.slot_load import slot_swap
    from .ui import console

    workspace = _load_workspace()
    result = slot_swap(workspace, args.slot_a, args.slot_b)
    if args.json:
        _print_json(result)
        return
    console.print(f"[ok]Swapped:[/] {result['swapped'][0]} ({result['slot_a']} ↔ {result['slot_b']})")


def cmd_migrate_slots(args: argparse.Namespace) -> None:
    """One-shot migration from pre-3.0 layout to 3.0 slot model."""
    from ..actions.migrate_slots import migrate, AlreadyMigratedError, NotLegacyError
    from .ui import console

    # Don't use _load_workspace() — pre-3.0 canopy.toml fails load_config validation.
    # Walk up from cwd looking for canopy.toml directly.
    root = Path.cwd().resolve()
    while root != root.parent:
        if (root / "canopy.toml").exists():
            break
        root = root.parent
    else:
        print("Error: not inside a canopy workspace (no canopy.toml found)", file=sys.stderr)
        sys.exit(1)

    try:
        result = migrate(root)
    except AlreadyMigratedError as e:
        print(f"Error: already migrated: {e}", file=sys.stderr)
        sys.exit(1)
    except NotLegacyError as e:
        console.print(f"  [muted]Nothing to migrate: {e}[/]")
        return

    if args.json:
        _print_json(result)
        return

    console.print()
    console.print(f"  [success]Migrated {len(result['moved'])} worktree dir(s) to slots[/]")
    for sid, feat in result["slots"].items():
        console.print(f"    {sid}: [info]{feat}[/]")
    if result["canonical"]:
        console.print(f"  [header]Canonical:[/] [info]{result['canonical']}[/]")
    console.print()


def cmd_reclaim(args: argparse.Namespace) -> None:
    """Free warm slots whose PR merged (clean-only; dirty→advisory)."""
    from ..actions.reclaim import reclaim_merged
    ws = _load_workspace()
    result = reclaim_merged(ws)
    if args.json:
        _print_json(result); return
    from .ui import console, print_success
    for f in result["freed"]:
        print_success(f"freed: {f}")
    for a in result["advisories"]:
        console.print(f"  [warning]⚠ {a['message']}[/]")
    if not result["freed"] and not result["advisories"]:
        console.print("  [muted]nothing to reclaim[/]")


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


def _cmd_preflight_feature(args: argparse.Namespace) -> None:
    """Feature-scoped preflight via coordinator.review_prep (records result)."""
    from ..management.review_ops import review_prep as review_prep_op
    from .ui import console, separator, spinner, SYM_CHECK, SYM_DOT, SYM_CROSS

    workspace = _load_workspace()
    with spinner(f"Running preflight on {args.feature}…"):
        result = review_prep_op(workspace, args.feature)

    if args.json:
        _print_json(result)
        return

    console.print()
    console.print(f"  [feature]{result['feature']}[/]  preflight")
    separator()
    for repo, info in result["repos"].items():
        pc = info.get("precommit") or {}
        glyph = "[success]✓[/]" if pc.get("passed") else "[error]✗[/]"
        kind = pc.get("type", "")
        dirty = info.get("dirty_count", 0)
        console.print(f"  [repo]{repo}[/]  {glyph} {dirty} files  [muted]{kind}[/]")
    console.print()
    if result.get("all_passed"):
        console.print("  [success]Ready to commit.[/]")
    else:
        console.print("  [error]One or more repos failed checks.[/]")
    console.print()


def cmd_preflight(args: argparse.Namespace) -> None:
    if getattr(args, "feature", None):
        _cmd_preflight_feature(args)
    else:
        _cmd_preflight_context(args)


def _cmd_preflight_context(args: argparse.Namespace) -> None:
    """Context-aware pre-commit quality gate.

    Detects which feature/repos you're in, stages all changes (git add -A),
    runs pre-commit hooks, and reports results. Does NOT commit — that's
    your job when you're satisfied.

    When run from inside a feature worktree directory, checks all repo
    worktrees in that feature.

    When run from inside a single repo worktree, checks just that repo.
    """
    from ..workspace.context import detect_context
    from ..workspace.config import load_config, ConfigNotFoundError, ConfigError
    from ..git import repo as git_repo
    from ..integrations.precommit import run_precommit
    from ..actions.augments import repo_augments

    ctx = detect_context()

    if ctx.context_type == "unknown":
        print("Error: can't detect canopy context from current directory.", file=sys.stderr)
        print("Run this from inside a feature worktree or a workspace repo.", file=sys.stderr)
        sys.exit(1)

    if not ctx.repo_paths:
        print("Error: no repos found in current context.", file=sys.stderr)
        sys.exit(1)

    workspace_config = None
    if ctx.workspace_root:
        try:
            workspace_config = load_config(ctx.workspace_root)
        except (ConfigNotFoundError, ConfigError):
            workspace_config = None

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

        # Run pre-commit hooks (honoring per-repo augments.preflight_cmd)
        augments = (
            repo_augments(workspace_config, repo_name) if workspace_config else None
        )
        hook_result = run_precommit(repo_path, augments=augments)
        passed = hook_result["passed"]
        if not passed:
            all_passed = False

        dirty_count = len(status)
        results[repo_name] = {
            "status": "staged" if passed else "hooks_failed",
            "dirty_count": dirty_count,
            "hooks": hook_result,
        }

    # Persist preflight result so feature_state can distinguish
    # IN_PROGRESS from READY_TO_COMMIT. Maps detect_context's directory
    # names back to canopy-registered repo names so feature_state
    # (which uses canonical names) can match.
    #
    # F-11: when run from the workspace root (not inside a worktree),
    # ``ctx.feature`` is None — but we may still have a canonical
    # feature in ``slots.json`` whose repos overlap. Fall back
    # to that so `canopy preflight` from the workspace root persists a
    # record for the canonical feature, which is what `canopy state`
    # then keys off to surface ready_to_commit.
    feature_for_record = ctx.feature
    if feature_for_record is None and ctx.workspace_root:
        try:
            from ..actions import slots as _slots_mod
            from ..workspace.config import load_config as _load_config
            from ..workspace.workspace import Workspace as _WS
            _ws = _WS(_load_config(ctx.workspace_root))
            _state = _slots_mod.read_state(_ws)
            if _state and _state.canonical and _state.canonical.feature:
                feature_for_record = _state.canonical.feature
        except Exception:
            pass

    if feature_for_record and ctx.workspace_root:
        try:
            from ..actions.preflight_state import record_result
            from ..workspace.config import load_config
            from ..workspace.workspace import Workspace as _WS
            cfg = load_config(ctx.workspace_root)
            ws = _WS(cfg)
            path_to_canonical = {
                str(state.abs_path.resolve()): state.config.name
                for state in ws.repos
            }
            head_sha_per_repo: dict[str, str] = {}
            for path in ctx.repo_paths:
                resolved = str(Path(path).resolve())
                canonical = path_to_canonical.get(resolved)
                if not canonical:
                    continue
                head_sha_per_repo[canonical] = git_repo.head_sha(path)
            if head_sha_per_repo:
                record_result(
                    ctx.workspace_root, feature_for_record,
                    passed=all_passed,
                    head_sha_per_repo=head_sha_per_repo,
                    summary=("preflight passed" if all_passed
                              else "preflight failed"),
                )
        except Exception:
            pass

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
    from ..management.review_ops import (
        review_status as review_status_op,
        review_comments as review_comments_op,
        review_prep as review_prep_op,
    )

    feature = args.name

    # ── Step 1: Check PR status ──
    try:
        with spinner(f"Checking PRs for {feature}..."):
            status = review_status_op(workspace, feature)
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
            comments_data = review_comments_op(workspace, feature)
    except PullRequestNotFoundError as e:
        print_error(str(e))
        sys.exit(1)

    # ── Step 3: Run pre-commit + stage ──
    prep_data = None
    if not args.comments_only:
        with spinner(f"Running pre-commit hooks..."):
            prep_data = review_prep_op(
                workspace, feature, message=args.message or "",
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


def cmd_run(args: argparse.Namespace) -> None:
    """Run a shell command in a canopy-managed repo, with directory resolution."""
    from ..agent.runner import run_in_repo
    from ..actions.errors import ActionError
    from .render import render_blocker
    from .ui import console

    workspace = _load_workspace()
    try:
        result = run_in_repo(
            workspace,
            repo=args.repo,
            command=args.cmd,
            feature=getattr(args, "feature", None),
            timeout_seconds=getattr(args, "timeout", 60),
        )
    except ActionError as err:
        if args.json:
            _print_json(err.to_dict())
        else:
            render_blocker(err, action="run")
        sys.exit(1)

    if args.json:
        _print_json(result)
        return

    if result["stdout"]:
        sys.stdout.write(result["stdout"])
        if not result["stdout"].endswith("\n"):
            sys.stdout.write("\n")
    if result["stderr"]:
        sys.stderr.write(result["stderr"])
        if not result["stderr"].endswith("\n"):
            sys.stderr.write("\n")
    sys.exit(result["exit_code"])


def _read_command(impl, args, action_label: str, *extra_kwargs_keys):
    """Run a read primitive with structured error rendering. Returns the result dict
    (or None on failure — caller should sys.exit after this)."""
    from ..actions.errors import ActionError
    from .render import render_blocker

    workspace = _load_workspace()
    kwargs = {k: getattr(args, k) for k in extra_kwargs_keys if hasattr(args, k)}
    try:
        return impl(workspace, args.alias, **kwargs)
    except ActionError as err:
        if args.json:
            _print_json(err.to_dict())
        else:
            render_blocker(err, action=action_label)
        sys.exit(1)


def cmd_issue(args: argparse.Namespace) -> None:
    """Fetch an issue from the workspace's configured provider.

    Uses the M5 ``issue_get`` action so the CLI surface matches the
    ``mcp__canopy__issue_get`` MCP tool — canonical state mapping
    (``todo`` / ``in_progress`` / ``done`` / ``cancelled``) and the
    full ``Issue`` shape (id, identifier, title, description, state,
    url, assignee, labels, priority, raw).
    """
    from ..actions.reads import issue_get
    from .ui import console

    result = _read_command(issue_get, args, "issue")
    if args.json:
        _print_json(result)
        return
    console.print()
    identifier = result.get("identifier") or result.get("id") or ""
    state = result.get("state") or ""
    console.print(f"  [feature]{identifier}[/]  [muted]{state}[/]")
    if result.get("title"):
        console.print(f"  {result['title']}")
    if result.get("url"):
        console.print(f"  [muted]{result['url']}[/]")
    if result.get("assignee"):
        console.print(f"  [muted]assignee:[/] {result['assignee']}")
    labels = result.get("labels") or []
    if labels:
        console.print(f"  [muted]labels:[/] {', '.join(labels)}")
    if result.get("description"):
        desc = result["description"].strip()
        if len(desc) > 400:
            desc = desc[:400] + "…"
        console.print()
        console.print(f"  [muted]{desc}[/]")
    console.print()


def cmd_issues(args: argparse.Namespace) -> None:
    """List the current user's open issues from the configured provider (F-5).

    Mirrors ``mcp__canopy__issue_list_my_issues``. Empty list when the
    provider isn't configured (no autocomplete signal). Each entry is
    the canonical ``Issue.to_dict()`` shape.
    """
    from ..providers import (
        IssueProviderError, ProviderNotConfigured, get_issue_provider,
    )
    from ..actions.errors import BlockerError, FixAction
    from .render import render_blocker
    from .ui import console

    workspace = _load_workspace()
    try:
        provider = get_issue_provider(workspace)
        issues = provider.list_my_issues(limit=args.limit)
    except ProviderNotConfigured:
        if args.json:
            _print_json([])
        else:
            console.print("  [muted]no issue provider configured[/]")
        return
    except IssueProviderError as e:
        err = BlockerError(
            code="issue_provider_failed",
            what="issue provider call failed",
            details={"error": str(e)},
            fix_actions=[
                FixAction(action="doctor", args={}, safe=True,
                            preview="canopy doctor surfaces provider config drift"),
            ],
        )
        if args.json:
            _print_json(err.to_dict())
        else:
            render_blocker(err, action="issues")
        sys.exit(1)

    items = [i.to_dict() for i in issues]
    if args.json:
        _print_json(items)
        return
    console.print()
    if not items:
        console.print("  [muted]no open issues[/]")
        console.print()
        return
    for it in items:
        identifier = it.get("identifier") or it.get("id") or ""
        state = it.get("state") or ""
        title = it.get("title") or ""
        console.print(f"  [feature]{identifier}[/]  [muted]{state}[/]  {title}")
    console.print()


def cmd_pr(args: argparse.Namespace) -> None:
    """Fetch PR data per repo for an alias."""
    from ..actions.reads import github_get_pr
    from .ui import console

    result = _read_command(github_get_pr, args, "pr")
    if args.json:
        _print_json(result)
        return
    console.print()
    for repo, info in result["repos"].items():
        if not info.get("found"):
            console.print(f"  [repo]{repo}[/]  [muted]PR #{info['pr_number']} not found[/]")
            continue
        decision = info.get("review_decision") or "—"
        draft = " [muted](draft)[/]" if info.get("draft") else ""
        console.print(f"  [repo]{repo}[/]  PR #{info['pr_number']}  [muted]{decision}[/]{draft}")
        if info.get("title"):
            console.print(f"    {info['title']}")
        if info.get("url"):
            console.print(f"    [muted]{info['url']}[/]")
    console.print()


def cmd_branch(args: argparse.Namespace) -> None:
    """Fetch branch info (HEAD, divergence, upstream) per repo."""
    from ..actions.reads import github_get_branch
    from .ui import console

    workspace = _load_workspace()
    from ..actions.errors import ActionError
    from .render import render_blocker
    try:
        result = github_get_branch(workspace, args.alias, repo=args.repo)
    except ActionError as err:
        if args.json:
            _print_json(err.to_dict())
        else:
            render_blocker(err, action="branch")
        sys.exit(1)

    if args.json:
        _print_json(result)
        return
    console.print()
    for repo, info in result["repos"].items():
        if not info.get("exists_locally"):
            console.print(f"  [repo]{repo}[/]  [muted]{info['branch']} (not present locally)[/]")
            continue
        sha = info.get("head_sha", "")
        ahead = info.get("ahead", 0)
        behind = info.get("behind", 0)
        upstream = "↑" if info.get("has_upstream") else "no upstream"
        suffix = f"  [muted]{upstream}"
        if info.get("has_upstream"):
            suffix += f"  ↑{ahead} ↓{behind}"
        suffix += "[/]"
        console.print(f"  [repo]{repo}[/]  {info['branch']}  [muted]@ {sha[:8]}[/]{suffix}")
    console.print()


def cmd_comments(args: argparse.Namespace) -> None:
    """Fetch temporally classified PR review comments per repo."""
    from ..actions.reads import github_get_pr_comments
    from .ui import console

    result = _read_command(github_get_pr_comments, args, "comments")
    if args.json:
        _print_json(result)
        return
    console.print()
    console.print(
        f"  [header]actionable: {result['actionable_count']}[/]  "
        f"[muted]likely resolved: {result['likely_resolved_count']}  "
        f"resolved: {result['resolved_thread_count']}[/]"
    )
    for repo, info in result["repos"].items():
        console.print()
        console.print(f"  [repo]{repo}[/]  PR #{info['pr_number']}  [muted]{info.get('pr_url','')}[/]")
        actionable = info.get("actionable_threads") or []
        if not actionable:
            console.print("    [muted]no actionable threads[/]")
            continue
        for t in actionable:
            line = f"{t.get('path','')}:{t.get('line','')}" if t.get("path") else "(general)"
            console.print(f"    [warning]•[/] [muted]{line}[/]  {t.get('author','')}")
            body = (t.get("body") or "").strip().split("\n")[0]
            if len(body) > 120:
                body = body[:120] + "…"
            console.print(f"      {body}")
    console.print()


def cmd_setup_agent(args: argparse.Namespace) -> None:
    """Install the using-canopy skill + register canopy MCP for the workspace."""
    from ..agent_setup import setup_agent, check_status
    from .ui import console, print_success, print_warning

    if args.check:
        # Best-effort workspace detection, but still works without one.
        try:
            workspace = _load_workspace()
            workspace_root = workspace.config.root
        except Exception:
            workspace_root = Path.cwd()
        status = check_status(workspace_root)
        if args.json:
            _print_json(status)
            return
        skills_state = status.get("skills") or [status["skill"]]
        mcp = status["mcp"]
        console.print()
        for skill in skills_state:
            label_name = skill.get("name", "")
            if skill["installed"] and skill["is_canopy_skill"]:
                label = "[success]✓ up to date[/]" if skill["up_to_date"] else "[warning]● out of date[/]"
                console.print(f"  skill[{label_name}]  {label}  [muted]{skill['path']}[/]")
            elif skill["installed"]:
                console.print(f"  skill[{label_name}]  [warning]foreign file present[/]  [muted]{skill['path']}[/]")
            else:
                console.print(f"  skill[{label_name}]  [muted]not installed[/]  [muted]{skill['path']}[/]")
        if mcp["configured"]:
            root = (mcp.get("env") or {}).get("CANOPY_ROOT", "")
            console.print(f"  mcp     [success]✓ configured[/]  [muted]CANOPY_ROOT={root}[/]")
        else:
            console.print(f"  mcp     [error]✗ not configured[/]  [muted]{mcp['path']}[/]")
        hooks_state = status.get("hooks") or {}
        if hooks_state.get("configured"):
            console.print(f"  hooks   [success]✓ installed[/]  [muted]{hooks_state.get('path', '')}[/]")
        else:
            console.print(f"  hooks   [muted]· not installed[/]  [muted]{hooks_state.get('path', '')}[/]")
        console.print()
        return

    do_skill = not args.mcp_only
    do_mcp = not args.skill_only

    from ..agent_setup import DEFAULT_SKILL
    extra = list(dict.fromkeys(args.skill or []))   # dedupe, preserve order
    skills: tuple[str, ...] = (
        tuple([DEFAULT_SKILL] + [s for s in extra if s != DEFAULT_SKILL])
        if do_skill else ()
    )

    workspace_root: Path | None = None
    if do_mcp:
        try:
            workspace = _load_workspace()
            workspace_root = workspace.config.root
        except Exception:
            workspace_root = None

    result = setup_agent(
        workspace_root, skills=skills, do_mcp=do_mcp, reinstall=args.reinstall,
    )

    if args.hooks:
        from ..agent_setup import install_hooks
        if workspace_root is None:
            # Resolve the workspace without _load_workspace()'s sys.exit —
            # a missing workspace must not discard the skill/MCP result
            # already computed above; report hooks as skipped instead.
            from ..workspace.config import load_config
            from ..workspace.workspace import Workspace
            try:
                workspace_root = Workspace(load_config()).config.root
            except Exception:
                workspace_root = None
        if workspace_root is None:
            result["hooks"] = {
                "action": "skipped", "path": "",
                "reason": "no canopy workspace found — run `canopy setup-agent --hooks` from inside one",
            }
        else:
            result["hooks"] = install_hooks(workspace_root)

    if args.json:
        _print_json(result)
        return

    console.print()
    for s in result.get("skills") or ([result["skill"]] if "skill" in result else []):
        glyph = {
            "installed": "[success]✓ installed[/]",
            "reinstalled": "[success]✓ reinstalled[/]",
            "skipped": "[muted]· skipped[/]",
        }.get(s["action"], s["action"])
        label = f"skill[{s.get('name', DEFAULT_SKILL)}]"
        console.print(f"  {label:<22} {glyph}  [muted]{s['path']}[/]")
        if s.get("reason"):
            console.print(f"          [muted]{s['reason']}[/]")
    if "mcp" in result:
        m = result["mcp"]
        glyph = {
            "added": "[success]✓ added[/]",
            "updated": "[success]✓ updated[/]",
            "created": "[success]✓ created[/]",
            "skipped": "[muted]· skipped[/]",
        }.get(m["action"], m["action"])
        console.print(f"  mcp     {glyph}  [muted]{m['path']}[/]")
        if m.get("reason"):
            console.print(f"          [muted]{m['reason']}[/]")
    if "hooks" in result:
        h = result["hooks"]
        glyph = {
            "added": "[success]✓ installed[/]",
            "unchanged": "[muted]· already installed[/]",
            "skipped": "[warning]● skipped[/]",
        }.get(h["action"], h["action"])
        console.print(f"  hooks   {glyph}  [muted]{h['path']}[/]")
        if h.get("reason"):
            console.print(f"          [muted]{h['reason']}[/]")
    console.print()
    console.print("  [muted]Restart Claude Code (or open a new session) to pick up changes.[/]")
    console.print()


def cmd_state(args: argparse.Namespace) -> None:
    """Show the feature state + suggested next actions."""
    from ..actions.errors import ActionError, BlockerError, FixAction
    from ..actions import slots as slots_mod
    from ..actions.feature_state import feature_state as state_impl
    from .render import render_blocker
    from .ui import console

    workspace = _load_workspace()
    feature = args.feature
    if feature is None:
        slot_state = slots_mod.read_state(workspace)
        if slot_state is None or slot_state.canonical is None:
            err = BlockerError(
                code="no_active_feature",
                what="no feature passed and no active feature is set",
                fix_actions=[
                    FixAction(action="switch", args={"feature": "<name>"},
                              safe=True, preview="set active feature with: canopy switch <feature>"),
                    FixAction(action="state", args={"feature": "<name>"},
                              safe=True, preview="or pass a feature explicitly: canopy state <feature>"),
                ],
            )
            if args.json:
                _print_json(err.to_dict())
            else:
                render_blocker(err, action="state")
            sys.exit(1)
        feature = slot_state.canonical.feature

    try:
        result = state_impl(workspace, feature)
    except ActionError as err:
        if args.json:
            _print_json(err.to_dict())
        else:
            render_blocker(err, action="state")
        sys.exit(1)

    if args.json:
        _print_json(result)
        return

    state_glyph = {
        "drifted": "[error]✗[/]",
        "in_progress": "[warning]●[/]",
        "ready_to_commit": "[info]●[/]",
        "ready_to_push": "[info]●[/]",
        "needs_work": "[error]●[/]",
        "approved": "[success]●[/]",
        "awaiting_review": "[muted]●[/]",
        "no_prs": "[muted]○[/]",
    }
    glyph = state_glyph.get(result["state"], "[muted]?[/]")
    console.print()
    console.print(f"  {glyph} [feature]{result['feature']}[/]  [muted]({result['state']})[/]")

    summary = result.get("summary", {})
    alignment = summary.get("alignment")
    if alignment and not alignment.get("aligned"):
        for repo, exp in (alignment.get("expected") or {}).items():
            actual = (alignment.get("actual") or {}).get(repo) or "(missing)"
            mark = "[error]✗[/]" if actual != exp else "[success]✓[/]"
            console.print(f"      {mark} [repo]{repo}[/]  [muted]→ {actual}  (expected {exp})[/]")
    else:
        repos = summary.get("repos") or {}
        for repo, info in repos.items():
            bits = []
            if info.get("is_dirty"):
                bits.append(f"dirty: {info.get('dirty_count', '?')} files")
            if info.get("ahead", 0) > 0:
                bits.append(f"↑{info['ahead']}")
            if info.get("behind", 0) > 0:
                bits.append(f"↓{info['behind']}")
            if info.get("actionable_count", 0) > 0:
                bits.append(f"actionable: {info['actionable_count']}")
            if info.get("review_decision"):
                bits.append(info["review_decision"])
            extra = "  [muted](" + ", ".join(bits) + ")[/]" if bits else ""
            console.print(f"      [repo]{repo}[/]  [muted]→ {info.get('branch','')}[/]{extra}")

    pf = summary.get("preflight") or {}
    if pf.get("ran"):
        status = "passed" if pf.get("passed") else "failed"
        fresh = "fresh" if pf.get("fresh") else "stale"
        console.print(f"      [muted]preflight: {status} ({fresh}, ran {pf.get('ran_at','')})[/]")

    for w in result.get("warnings", []):
        console.print(f"      [warning]⚠ {w.get('what','')}[/]  [muted]({w.get('code','')})[/]")

    next_actions = result.get("next_actions") or []
    if next_actions:
        console.print()
        console.print("    [header]next:[/]")
        for i, a in enumerate(next_actions):
            tag = "[info]→[/]" if a.get("primary") else "  "
            label = a.get("label") or a.get("action") or "?"
            preview = a.get("preview")
            line = f"      {tag} [info]canopy {a['action']} {a.get('args', {}).get('feature','')}[/]  [muted]{label}[/]"
            console.print(line)
            if preview:
                console.print(f"          [muted]{preview}[/]")
    console.print()


def cmd_triage(args: argparse.Namespace) -> None:
    """Show prioritized list of features needing attention."""
    from ..actions.errors import ActionError
    from ..actions.triage import triage as triage_impl
    from .render import render_blocker
    from .ui import console

    workspace = _load_workspace()
    try:
        result = triage_impl(
            workspace,
            author=getattr(args, "author", "@me"),
            repos=_split_csv(getattr(args, "repos", None)),
        )
    except ActionError as err:
        if args.json:
            _print_json(err.to_dict())
        else:
            render_blocker(err, action="triage")
        sys.exit(1)

    if args.json:
        _print_json(result)
        return

    console.print()
    console.print(f"  [header]triage[/]  [muted]author={result['author']}  ({len(result['features'])} features)[/]")
    if not result["features"]:
        console.print("  [muted]nothing needs attention[/]")
        console.print()
        return
    glyphs = {
        "changes_requested": "[error]●[/]",
        "review_required_with_bot_comments": "[warning]●[/]",
        "review_required": "[muted]●[/]",
        "approved": "[success]●[/]",
        "unknown": "[muted]?[/]",
    }
    for f in result["features"]:
        glyph = glyphs.get(f["priority"], "[muted]?[/]")
        label = f["feature"]
        linear = f.get("linear_issue") or ""
        title = f.get("linear_title") or ""
        suffix = f"  [muted]{linear} {title}[/]".rstrip() if linear or title else ""
        console.print()
        console.print(f"  {glyph} [feature]{label}[/]  [muted]({f['priority']})[/]{suffix}")
        for repo, info in f["repos"].items():
            decision = info.get("review_decision") or "—"
            counts = []
            if info.get("actionable_count"):
                counts.append(f"actionable: {info['actionable_count']}")
            if info.get("likely_resolved_count"):
                counts.append(f"likely_resolved: {info['likely_resolved_count']}")
            count_str = "  [muted](" + ", ".join(counts) + ")[/]" if counts else ""
            console.print(
                f"      [repo]{repo}[/]  PR #{info['pr_number']}  "
                f"[muted]{decision}[/]{count_str}"
            )
    console.print()


def cmd_switch(args: argparse.Namespace) -> None:
    """Promote a feature to the canonical slot (canonical-slot model, Wave 2.9)."""
    from ..actions.errors import ActionError
    from ..actions.switch import switch as switch_impl
    from .render import render_blocker
    from .ui import console, spinner

    workspace = _load_workspace()
    to_slot = getattr(args, "to_slot", None)
    label = to_slot or args.feature or "feature"
    try:
        with spinner(f"Switching to {label}…"):
            result = switch_impl(
                workspace, args.feature,
                release_current=getattr(args, "release_current", False),
                no_evict=getattr(args, "no_evict", False),
                evict=getattr(args, "evict", None),
                evict_to=getattr(args, "evict_to", None),
                to_slot=to_slot,
            )
    except ActionError as err:
        if args.json:
            _print_json(err.to_dict())
        else:
            render_blocker(err, action="switch")
        sys.exit(1)

    if args.json:
        _print_json(result)
        return

    console.print()
    feature = result["feature"]
    mode = result["mode"]
    glyph = "[success]✓[/]"
    label = {"active_rotation": "active rotation",
              "wind_down": "wind down"}.get(mode, mode)
    console.print(f"  {glyph} canonical: [feature]{feature}[/]  [muted]({label})[/]")
    if result.get("previously_canonical"):
        prev = result["previously_canonical"]
        if mode == "wind_down":
            console.print(f"      [muted]previous '{prev}' → cold (stashed if dirty)[/]")
        else:
            console.print(f"      [muted]previous '{prev}' → warm worktree[/]")
    if result.get("eviction"):
        ev = result["eviction"]
        stashed_repos = [r for r in ev["repos"] if r["stashed"]]
        console.print(
            f"      [warning]evicted '{ev['feature']}'[/] → cold "
            f"({len(stashed_repos)}/{len(ev['repos'])} repos auto-stashed)"
        )
    if result.get("branches_created"):
        for b in result["branches_created"]:
            console.print(f"      [muted]created branch {b['repo']}/{b['branch']} from {b['base']}[/]")
    for repo, path in result["per_repo_paths"].items():
        console.print(f"      [repo]{repo}[/]  [muted]→ {path}[/]")
    if result.get("migration"):
        m = result["migration"]
        if m.get("ran"):
            detected = m.get("canonical_detected") or "(none)"
            console.print(f"      [muted]migrated workspace to 2.9 schema; canonical detected: {detected}[/]")
    console.print()
    console.print(
        "  [muted]now: 'canopy state' / 'canopy run <repo> <cmd>' default to this feature[/]"
    )
    console.print()


def cmd_commit(args: argparse.Namespace) -> None:
    """Feature-scoped multi-repo commit (Wave 2.3)."""
    from ..actions.commit import commit as commit_impl
    from ..actions.errors import ActionError
    from .render import render_blocker
    from .ui import console, spinner

    workspace = _load_workspace()
    spin_msg = "Committing (running hooks)…" if not args.no_hooks else "Committing…"
    try:
        with spinner(spin_msg):
            result = commit_impl(
                workspace,
                args.message or "",
                feature=args.feature,
                repos=_split_csv(args.repos),
                paths=args.paths or None,
                no_hooks=args.no_hooks,
                amend=args.amend,
            )
    except ActionError as err:
        if args.json:
            _print_json(err.to_dict())
        else:
            render_blocker(err, action="commit")
        sys.exit(1)

    if args.json:
        _print_json(result)
        return

    console.print()
    console.print(f"  [feature]{result['feature']}[/]")
    for repo, r in result["results"].items():
        status = r["status"]
        if status == "ok":
            sha = r["sha"][:8]
            files = r["files_changed"]
            tag = " (amended)" if r.get("amended") else ""
            console.print(f"    [success]✓[/] [repo]{repo}[/]  {sha}  ({files} files{tag})")
        elif status == "nothing":
            console.print(f"    [muted]·[/] [repo]{repo}[/]  no changes")
        elif status == "hooks_failed":
            console.print(f"    [error]✗[/] [repo]{repo}[/]  hook failed")
            for line in (r.get("hook_output") or "").splitlines()[:5]:
                console.print(f"        [muted]{line}[/]")
        else:  # failed
            console.print(f"    [error]✗[/] [repo]{repo}[/]  {r.get('reason', 'failed')}")
    console.print()


def cmd_bot_status(args: argparse.Namespace) -> None:
    """Per-feature bot-comment rollup (M3)."""
    from ..actions.bot_status import bot_comments_status
    from ..actions.errors import ActionError
    from .render import render_blocker
    from .ui import console

    workspace = _load_workspace()
    try:
        result = bot_comments_status(workspace, feature=args.feature)
    except ActionError as err:
        if args.json:
            _print_json(err.to_dict())
        else:
            render_blocker(err, action="bot-status")
        sys.exit(1)

    if args.json:
        _print_json(result)
        return

    console.print()
    console.print(f"  [feature]{result['feature']}[/]")
    if not result["any_bot_comments"]:
        console.print("    [muted]no bot comments tracked[/]")
        console.print()
        return

    for repo, info in result["repos"].items():
        if info["total"] == 0:
            continue
        glyph = "[success]✓[/]" if info["unresolved"] == 0 else "[warning]●[/]"
        pr = f"PR #{info['pr_number']}" if info.get("pr_number") else "no PR"
        console.print(
            f"    {glyph} [repo]{repo}[/]  {pr}  "
            f"resolved {info['resolved']}/{info['total']}",
        )
        threads = (
            [t for t in info["threads"] if not t["resolved"]]
            if args.unresolved_only
            else info["threads"]
        )
        for t in threads:
            mark = "[success]✓[/]" if t["resolved"] else "[warning]●[/]"
            label = f"{t.get('author', '')}".strip() or "(unknown)"
            preview = t.get("body_preview", "")
            console.print(f"        {mark} [muted]{t.get('id', '')}[/] {label}: {preview}")
    overall = "[success]all resolved[/]" if result["all_resolved"] else "[warning]unresolved[/]"
    console.print(f"    [muted]→ {overall}[/]")
    console.print()


def _resolve_historian_feature(workspace, feature: str | None):
    """Resolve (workspace_root, feature_name) for a historian CLI call."""
    from ..actions import slots as slots_mod
    from ..actions.aliases import resolve_feature
    from ..actions.errors import BlockerError
    if feature:
        return workspace.config.root, resolve_feature(workspace, feature)
    state = slots_mod.read_state(workspace)
    if state is None or state.canonical is None:
        raise BlockerError(
            code="no_canonical_feature",
            what="no active feature; pass <feature> or run `canopy switch <name>` first",
        )
    return workspace.config.root, state.canonical.feature


def cmd_historian(args: argparse.Namespace) -> None:
    """Read or compact a feature's historian memory file (M4)."""
    from ..actions import historian
    from ..actions.errors import ActionError
    from .render import render_blocker
    from .ui import console

    workspace = _load_workspace()
    try:
        root, name = _resolve_historian_feature(workspace, args.feature)
    except ActionError as err:
        if args.json:
            _print_json(err.to_dict())
        else:
            render_blocker(err, action=f"historian {args.subcommand}")
        sys.exit(1)

    if args.subcommand == "show":
        memory = historian.format_for_agent(root, name)
        if args.json:
            _print_json({"feature": name, "memory": memory})
            return
        if not memory:
            console.print()
            console.print(f"  [muted]no memory recorded yet for [feature]{name}[/][/]")
            console.print()
            return
        console.print(memory)
        return

    if args.subcommand == "compact":
        result = historian.compact(root, name, keep_sessions=args.keep_sessions)
        if args.json:
            _print_json({"feature": name, **result})
            return
        console.print()
        console.print(f"  [feature]{name}[/]  {result.get('action')}: "
                       f"kept {result.get('kept', '?')} entries, "
                       f"dropped {result.get('dropped', 0)}")
        console.print()
        return


def cmd_push(args: argparse.Namespace) -> None:
    """Feature-scoped multi-repo push (Wave 2.3)."""
    from ..actions.errors import ActionError
    from ..actions.push import push as push_impl
    from .render import render_blocker
    from .ui import console, spinner

    workspace = _load_workspace()
    spin_msg = "Dry-run push (no network)…" if args.dry_run else "Pushing…"
    try:
        with spinner(spin_msg):
            result = push_impl(
                workspace,
                feature=args.feature,
                repos=_split_csv(args.repos),
                set_upstream=args.set_upstream,
                force_with_lease=args.force_with_lease,
                dry_run=args.dry_run,
            )
    except ActionError as err:
        if args.json:
            _print_json(err.to_dict())
        else:
            render_blocker(err, action="push")
        sys.exit(1)

    if args.json:
        _print_json(result)
        return

    console.print()
    console.print(f"  [feature]{result['feature']}[/]")
    for repo, r in result["results"].items():
        status = r["status"]
        if status == "ok":
            count = r.get("pushed_count", 0)
            ref = r.get("ref", "")
            extras = []
            if r.get("set_upstream"):
                extras.append("upstream set")
            if r.get("dry_run"):
                extras.append("dry-run")
            extra = f" ({', '.join(extras)})" if extras else ""
            console.print(f"    [success]✓[/] [repo]{repo}[/]  {ref}  +{count}{extra}")
        elif status == "up_to_date":
            console.print(f"    [muted]·[/] [repo]{repo}[/]  up to date")
        elif status == "rejected":
            console.print(f"    [error]✗[/] [repo]{repo}[/]  rejected")
            console.print(f"        [muted]{r.get('reason', '')}[/]")
        else:  # failed
            console.print(f"    [error]✗[/] [repo]{repo}[/]  {r.get('reason', 'failed')}")
    console.print()


def cmd_stash_save_feature(args: argparse.Namespace) -> None:
    """Feature-tagged stash save (extends `canopy stash save --feature`)."""
    from ..actions.errors import ActionError
    from ..actions.stash import save_for_feature
    from .render import render_blocker
    from .ui import console

    workspace = _load_workspace()
    try:
        result = save_for_feature(
            workspace, args.feature, args.message or "",
            repos=_split_csv(getattr(args, "repos", None)),
        )
    except ActionError as err:
        if args.json:
            _print_json(err.to_dict())
        else:
            render_blocker(err, action="stash save")
        sys.exit(1)
    if args.json:
        _print_json(result)
        return
    console.print()
    console.print(f"  [muted]message:[/] {result['message']}")
    for repo, status in result["repos"].items():
        glyph = "[success]✓[/]" if status == "stashed" else (
            "[muted]·[/]" if status == "clean" else "[error]✗[/]"
        )
        console.print(f"  {glyph} [repo]{repo}[/]  [muted]{status}[/]")
    console.print()


def cmd_stash_list_grouped(args: argparse.Namespace) -> None:
    """Grouped stash list (extends `canopy stash list [--feature]`)."""
    from ..actions.errors import ActionError
    from ..actions.stash import list_grouped
    from .render import render_blocker
    from .ui import console

    workspace = _load_workspace()
    try:
        result = list_grouped(workspace, feature=getattr(args, "feature", None))
    except ActionError as err:
        if args.json:
            _print_json(err.to_dict())
        else:
            render_blocker(err, action="stash list")
        sys.exit(1)
    if args.json:
        _print_json(result)
        return
    console.print()
    if not result["by_feature"] and not result["untagged"]:
        console.print("  [muted]no stashes[/]")
        console.print()
        return
    for feature, entries in result["by_feature"].items():
        console.print(f"  [feature]{feature}[/]  [muted]({len(entries)})[/]")
        for e in entries:
            console.print(f"      [repo]{e['repo']}[/]  {e['ref']}  [muted]{e.get('ts','')}[/]  {e.get('user_message','')}")
    if result["untagged"]:
        console.print(f"  [header]untagged[/]  [muted]({len(result['untagged'])})[/]")
        for e in result["untagged"]:
            console.print(f"      [repo]{e['repo']}[/]  {e['ref']}  [muted]{e.get('message','')}[/]")
    console.print()


def cmd_stash_pop_feature(args: argparse.Namespace) -> None:
    """Pop most recent feature-tagged stash per repo."""
    from ..actions.errors import ActionError
    from ..actions.stash import pop_feature
    from .render import render_blocker
    from .ui import console

    workspace = _load_workspace()
    try:
        result = pop_feature(
            workspace, args.feature,
            repos=_split_csv(getattr(args, "repos", None)),
        )
    except ActionError as err:
        if args.json:
            _print_json(err.to_dict())
        else:
            render_blocker(err, action="stash pop")
        sys.exit(1)
    if args.json:
        _print_json(result)
        return
    console.print()
    for repo, info in result["repos"].items():
        if info["status"] == "popped":
            console.print(f"  [success]✓[/] [repo]{repo}[/]  [muted]{info.get('user_message') or info.get('message','')}[/]")
        elif info["status"] == "no_match":
            console.print(f"  [muted]·[/] [repo]{repo}[/]  [muted]no matching stash[/]")
        else:
            console.print(f"  [error]✗[/] [repo]{repo}[/]  [error]{info.get('error','')}[/]")
    console.print()


def _split_csv(value: str | None) -> list[str] | None:
    if value is None or value == "":
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


def cmd_drift(args: argparse.Namespace) -> None:
    """Compare recorded HEAD state vs feature lane expectations across repos."""
    from ..actions.drift import detect_drift
    from .ui import console, print_warning, SYM_CHECK, SYM_CROSS

    workspace = _load_workspace()
    feature = getattr(args, "feature", None)
    report = detect_drift(workspace, feature_name=feature)

    if args.json:
        _print_json(report.to_dict())
        return

    console.print()
    if report.note:
        console.print(f"  [muted]{report.note}[/]")
        console.print()
        return

    for fd in report.features:
        glyph = f"[success]{SYM_CHECK}[/]" if fd.aligned else f"[error]{SYM_CROSS}[/]"
        console.print(f"  {glyph} [feature]{fd.feature}[/]")
        for r in fd.repos:
            if r.actual is None:
                line = f"      [repo]{r.repo}[/]  [muted]→ no recorded state (expected {r.expected})[/]"
            elif r.aligned:
                line = f"      [repo]{r.repo}[/]  [muted]→ {r.actual}[/]"
            else:
                line = f"      [repo]{r.repo}[/]  [warning]→ {r.actual}[/]  [muted](expected {r.expected})[/]"
            console.print(line)
        if not fd.aligned:
            console.print(f"      [muted]fix:[/] [info]canopy switch {fd.feature}[/]")
        console.print()


def cmd_pr_checks(args: argparse.Namespace) -> None:
    """Fetch CI check runs for a PR alias (M10)."""
    from ..actions.aliases import resolve_pr_targets
    from ..integrations import github as gh
    from .ui import console

    workspace = _load_workspace()
    targets = resolve_pr_targets(workspace, args.alias)
    results = []
    for t in targets:
        rollup, raw = gh.get_pr_checks(
            workspace.config.root, t.owner, t.repo_slug, t.pr_number,
        )
        results.append({
            "repo": t.repo,
            "pr_number": t.pr_number,
            "ci_status": rollup,
            "checks": raw,
        })

    if args.json:
        _print_json({"alias": args.alias, "results": results})
        return

    console.print()
    for r in results:
        ci = r["ci_status"]
        glyph = {
            "passing": "[success]✓[/]",
            "failing": "[error]✗[/]",
            "pending": "[warning]·[/]",
            "no_checks": "[muted]·[/]",
        }.get(ci.get("status"), "?")
        console.print(
            f"  [repo]{r['repo']}[/]  PR #{r['pr_number']}  "
            f"{glyph} {ci.get('status', '')}  "
            f"[muted]passed: {ci.get('passed', 0)}, failing: {ci.get('failing', 0)}, "
            f"pending: {ci.get('pending', 0)}[/]"
        )
        if ci.get("required_failing"):
            console.print(
                f"    [error]failing:[/] {', '.join(ci['required_failing'])}"
            )
        if ci.get("details_url"):
            console.print(f"    [muted]{ci['details_url']}[/]")
    console.print()


def cmd_worktree_bootstrap(args: argparse.Namespace) -> None:
    """Bootstrap a feature's worktrees: env-files, deps, IDE workspace (M6)."""
    from ..actions.bootstrap import ALLOWED_STEPS, bootstrap_feature
    from ..actions.errors import ActionError
    from .render import render_blocker
    from .ui import console, spinner

    workspace = _load_workspace()

    slot_id = getattr(args, "_slot", None)
    if slot_id:
        # Detached deps worker (spawned by slot_bootstrap._spawn_deps_background):
        # just install deps for this slot and record status — no other output.
        from ..actions import slot_bootstrap
        slot_bootstrap._run_deps_now(workspace, args.feature, slot_id)
        return

    # --interactive: run the deps install without capturing its stdio, so it
    # streams to the terminal and can satisfy prompts (auth, a pnpm
    # build-script approval) the detached background install can't.
    interactive = getattr(args, "interactive", False)
    if getattr(args, "deps", False):
        steps = ["deps"]
    else:
        steps_arg = getattr(args, "step", None)
        steps = [steps_arg] if steps_arg else None

    try:
        # Under --interactive the install streams to the terminal; a spinner
        # would fight that output, so run bare.
        if interactive:
            result = bootstrap_feature(
                workspace, args.feature,
                force=getattr(args, "force", False),
                steps=steps, interactive=True,
            )
        else:
            with spinner("Bootstrapping…"):
                result = bootstrap_feature(
                    workspace, args.feature,
                    force=getattr(args, "force", False),
                    steps=steps,
                )
    except ActionError as err:
        if args.json:
            _print_json(err.to_dict())
        else:
            render_blocker(err, action="worktree-bootstrap")
        sys.exit(1)

    if args.json:
        _print_json(result)
        return

    console.print()
    console.print(f"  [feature]{result['feature']}[/]")
    for repo, r in result["results"].items():
        console.print(f"\n    [repo]{repo}[/]")
        env = r["env"]
        env_glyph = {"ok": "[success]✓[/]", "skipped": "[muted]·[/]",
                     "missing_source": "[warning]·[/]"}.get(env["status"], "?")
        copied = env.get("files_copied", [])
        env_summary = f"{len(copied)} file(s)" if copied else env.get("reason", env["status"])
        console.print(f"      env  {env_glyph}  {env_summary}")
        deps = r["deps"]
        deps_glyph = {"ok": "[success]✓[/]", "failed": "[error]✗[/]",
                       "skipped": "[muted]·[/]"}.get(deps["status"], "?")
        deps_extra = ""
        if deps["status"] == "ok":
            deps_extra = f"  [muted]({deps.get('duration_ms', 0)}ms)[/]"
        elif deps["status"] == "failed":
            deps_extra = f"  [error]exit {deps.get('exit_code', '?')}[/]"
        elif deps.get("reason"):
            deps_extra = f"  [muted]{deps['reason']}[/]"
        console.print(f"      deps {deps_glyph}{deps_extra}")
    ide = result["ide"]
    ide_glyph = {"ok": "[success]✓[/]", "skipped": "[muted]·[/]",
                 "no_ide_configured": "[muted]·[/]"}.get(ide["status"], "?")
    if ide.get("path"):
        console.print(f"\n    ide  {ide_glyph}  [muted]{ide['path']}[/]")
    elif ide.get("reason"):
        console.print(f"\n    ide  {ide_glyph}  [muted]{ide['reason']}[/]")
    else:
        console.print(f"\n    ide  {ide_glyph}  [muted]{ide['status']}[/]")
    console.print()


def cmd_ship(args: argparse.Namespace) -> None:
    """Open or update one PR per repo in the canonical feature (M8 / Wave 2.4)."""
    from ..actions.errors import ActionError
    from ..actions.ship import ship as ship_impl
    from .render import render_blocker
    from .ui import console, spinner

    workspace = _load_workspace()
    spin_msg = "Dry-run ship…" if args.dry_run else "Shipping…"
    try:
        with spinner(spin_msg):
            result = ship_impl(
                workspace,
                feature=args.feature,
                repos=_split_csv(args.repos),
                draft=args.draft,
                reviewers=_split_csv(args.reviewers),
                dry_run=args.dry_run,
                base=args.base,
            )
    except ActionError as err:
        if args.json:
            _print_json(err.to_dict())
        else:
            render_blocker(err, action="ship")
        sys.exit(1)

    if args.json:
        _print_json(result)
        return

    console.print()
    console.print(f"  [feature]{result['feature']}[/]")
    for repo, r in result["results"].items():
        status = r["status"]
        if status == "opened":
            console.print(
                f"    [success]✓[/] [repo]{repo}[/]  opened PR #{r['pr_number']}  "
                f"[muted]{r.get('url', '')}[/]"
                + ("  [muted](draft)[/]" if r.get("draft") else "")
            )
        elif status == "up_to_date":
            console.print(
                f"    [muted]·[/] [repo]{repo}[/]  PR #{r['pr_number']} up to date"
            )
        elif status == "diverged":
            console.print(
                f"    [warning]⚠[/] [repo]{repo}[/]  PR #{r['pr_number']} diverged "
                f"[muted]{r.get('warning', '')}[/]"
            )
        elif status == "closed":
            console.print(
                f"    [warning]·[/] [repo]{repo}[/]  PR #{r['pr_number']} closed/merged "
                f"[muted]{r.get('reason', '')}[/]"
            )
        elif status == "skipped":
            console.print(
                f"    [muted]·[/] [repo]{repo}[/]  skipped — {r.get('reason', '')}"
            )
        elif status.startswith("would_"):
            console.print(
                f"    [muted]·[/] [repo]{repo}[/]  {status} (dry-run)"
            )
        else:
            console.print(f"    [error]✗[/] [repo]{repo}[/]  {r.get('reason', status)}")
    if result.get("cross_repo_links_updated"):
        console.print()
        console.print("    [muted]cross-repo PR descriptions updated with sibling links[/]")
    console.print()


def cmd_draft_replies(args: argparse.Namespace) -> None:
    """Auto-draft "Done in <sha>" replies for addressed PR comments (M9)."""
    from ..actions.draft_replies import draft_replies
    from .ui import console

    workspace = _load_workspace()
    result = draft_replies(
        workspace, args.alias,
        include_likely_resolved=getattr(args, "include_likely_resolved", False),
    )

    if args.json:
        _print_json(result)
        return

    console.print()
    console.print(
        f"  [header]drafts: {result['addressed_total']} addressed, "
        f"{result['unaddressed_total']} unaddressed[/]"
    )
    for repo, info in result["repos"].items():
        console.print()
        console.print(
            f"  [repo]{repo}[/]  PR #{info['pr_number']}  [muted]{info.get('pr_url', '')}[/]"
        )
        for draft in info["addressed"]:
            conf = draft["confidence"]
            tag = {"high": "[success]✓[/]", "medium": "[warning]·[/]",
                   "low": "[muted]·[/]"}.get(conf, "·")
            orig = draft["original_comment"]
            location = (
                f"{orig['path']}:{orig['line']}" if orig.get("path") else "(general)"
            )
            console.print(
                f"    {tag} [muted]{location}[/]  {orig.get('author', '')}  "
                f"[muted]({conf})[/]"
            )
            console.print(f"      → [info]{draft['draft_reply']}[/]")
        if not info["addressed"]:
            console.print(
                f"    [muted]no draftable replies; "
                f"{len(info['unaddressed'])} unaddressed[/]"
            )
    console.print()


def cmd_conflicts(args: argparse.Namespace) -> None:
    """Cross-feature file-overlap detection (M12)."""
    from ..actions.conflicts import find_conflicts
    from .ui import console

    workspace = _load_workspace()
    result = find_conflicts(
        workspace,
        feature=getattr(args, "feature", None),
        other=getattr(args, "with_", None),
        include_cold=getattr(args, "include_cold", False),
        line_level=getattr(args, "lines", False),
    )

    if args.json:
        _print_json(result)
        return

    pairs = result["pairs"]
    console.print()
    console.print(f"  [header]Conflicts ({len(pairs)} pair{'' if len(pairs) == 1 else 's'})[/]")
    console.print(f"  {'─' * 60}")
    if not pairs:
        console.print("  [muted]no overlaps detected[/]")
        console.print()
        return

    severity_glyph = {
        "high": "[error]⚠[/]",
        "medium": "[warning]·[/]",
        "low": "[muted]·[/]",
    }
    for pair in pairs:
        glyph = severity_glyph.get(pair["severity"], "·")
        console.print(
            f"\n  {glyph} [feature]{pair['feature_a']}[/] ↔ [feature]{pair['feature_b']}[/]  "
            f"[muted]{pair['severity']}[/]"
        )
        for repo, entry in pair["overlap"].items():
            files = entry["files"]
            file_list = ", ".join(files[:3])
            if len(files) > 3:
                file_list += f" (+{len(files) - 3} more)"
            line_bit = ""
            if "lines_both" in entry and entry["lines_both"] > 0:
                line_bit = f", {entry['lines_both']} lines overlapping"
            console.print(f"    [repo]{repo}[/]  {file_list}{line_bit}")
        console.print(f"    [muted]suggestion: {pair['suggestion']}[/]")
    console.print()


def cmd_doctor(args: argparse.Namespace) -> None:
    """Diagnose workspace + install integrity; optionally repair."""
    from ..actions.doctor import doctor
    from .ui import console

    workspace = _load_workspace()

    fix_categories = None
    if getattr(args, "fix_category", None):
        fix_categories = [args.fix_category]
    fix = bool(getattr(args, "fix", False) or fix_categories)
    feature = getattr(args, "feature", None)
    clean_vsix = bool(getattr(args, "clean_vsix", False))

    report = doctor(
        workspace,
        fix=fix,
        fix_categories=fix_categories,
        feature=feature,
        clean_vsix=clean_vsix,
    )

    if args.json:
        _print_json(report)
        return

    issues = report["issues"]
    summary = report["summary"]
    fixed = report.get("fixed") or []
    skipped = report.get("skipped") or []

    console.print()
    if not issues:
        console.print("  [success]✓[/] doctor: workspace + install look clean")
        console.print()
        return

    # Group by severity, errors first.
    glyphs = {"error": ("[error]✗[/]", "errors"),
              "warn":  ("[warning]![/]", "warnings"),
              "info":  ("[muted]·[/]", "info")}
    for sev, (glyph, label) in glyphs.items():
        sev_issues = [i for i in issues if i["severity"] == sev]
        if not sev_issues:
            continue
        console.print(f"  {glyph} [header]{label}:[/] {len(sev_issues)}")
        for issue in sev_issues:
            scope = ""
            if issue.get("repo") and issue.get("feature"):
                scope = f"  [muted]({issue['feature']}/{issue['repo']})[/]"
            elif issue.get("repo"):
                scope = f"  [muted]({issue['repo']})[/]"
            elif issue.get("feature"):
                scope = f"  [muted]({issue['feature']})[/]"
            console.print(
                f"      {glyph} {issue['what']}{scope}  [muted]({issue['code']})[/]"
            )
            if getattr(args, "verbose", False):
                if issue.get("expected") is not None:
                    console.print(f"          [muted]expected:[/] {issue['expected']}")
                if issue.get("actual") is not None:
                    console.print(f"          [muted]actual:  [/] {issue['actual']}")
            if issue.get("fix_action"):
                tag = "[muted](safe)[/]" if issue.get("auto_fixable") else "[warning](manual)[/]"
                console.print(f"          [muted]fix:[/] {issue['fix_action']}  {tag}")
        console.print()

    if fix:
        console.print(f"  [info]repaired:[/] {len(fixed)}; [muted]skipped:[/] {len(skipped)}")
        for f in fixed:
            ok = "[success]✓[/]" if f.get("success") else "[error]✗[/]"
            console.print(f"      {ok} {f['action_taken']}  [muted]({f['code']})[/]")
            if f.get("error"):
                console.print(f"          [error]error:[/] {f['error']}")
        for s in skipped:
            console.print(
                f"      [muted]· skipped {s['code']}: {s.get('skip_reason', '')}[/]"
            )
        console.print()

    console.print(
        f"  [muted]summary:[/] errors={summary['errors']} "
        f"warnings={summary['warnings']} info={summary['info']}"
    )
    console.print()


def _resolve_thread_feature(workspace, feature: str | None) -> str:
    """Return a feature name for thread commands, falling back to canonical."""
    from ..actions import slots as slots_mod
    from ..actions.aliases import resolve_feature
    from ..actions.errors import BlockerError
    if feature:
        return resolve_feature(workspace, feature)
    state = slots_mod.read_state(workspace)
    if state is None or state.canonical is None:
        raise BlockerError(
            code="no_canonical_feature",
            what="no active feature; pass --feature or run `canopy switch <name>` first",
        )
    return state.canonical.feature


def cmd_reply_thread(args: argparse.Namespace) -> None:
    """Post a reply to a GitHub PR review thread, optionally resolving it."""
    from ..actions.thread_actions import reply_to_thread
    from ..actions.errors import ActionError, BlockerError
    from .render import render_blocker
    from .ui import console

    workspace = _load_workspace()
    try:
        feature = _resolve_thread_feature(workspace, getattr(args, "feature", None))
    except ActionError as err:
        if args.json:
            _print_json(err.to_dict())
        else:
            render_blocker(err, action="reply")
        sys.exit(1)

    if args.body is not None:
        body = args.body
    elif args.body_file is not None:
        from pathlib import Path
        body = Path(args.body_file).read_text()
    else:
        if sys.stdin.isatty():
            err = BlockerError(
                code="missing_reply_body",
                what="reply body required: pass --body, --body-file, or pipe stdin",
            )
            if args.json:
                _print_json(err.to_dict())
            else:
                render_blocker(err, action="reply")
            sys.exit(1)
        body = sys.stdin.read()

    if not body.strip():
        err = BlockerError(code="empty_reply_body", what="reply body is empty")
        if args.json:
            _print_json(err.to_dict())
        else:
            render_blocker(err, action="reply")
        sys.exit(1)

    try:
        result = reply_to_thread(workspace, args.thread_id, body,
                                 feature=feature, resolve_after=args.resolve)
    except ActionError as err:
        if args.json:
            _print_json(err.to_dict())
        else:
            render_blocker(err, action="reply")
        sys.exit(1)

    if args.json:
        _print_json(result)
        return

    console.print()
    console.print(f"  Posted reply: [info]{result['posted']['url']}[/]")
    if args.resolve and "resolved" in result:
        console.print(f"  Resolved [info]{args.thread_id}[/]")
    console.print()


def cmd_resolve_thread(args: argparse.Namespace) -> None:
    """Resolve a GitHub PR review thread and record the resolution locally."""
    from ..actions.thread_actions import resolve_thread
    from ..actions.errors import ActionError
    from .render import render_blocker
    from .ui import console

    workspace = _load_workspace()
    try:
        feature = _resolve_thread_feature(workspace, getattr(args, "feature", None))
    except ActionError as err:
        if args.json:
            _print_json(err.to_dict())
        else:
            render_blocker(err, action="resolve")
        sys.exit(1)

    try:
        result = resolve_thread(workspace, args.thread_id, feature=feature)
    except ActionError as err:
        if args.json:
            _print_json(err.to_dict())
        else:
            render_blocker(err, action="resolve")
        sys.exit(1)

    if args.json:
        _print_json(result)
        return

    console.print()
    console.print(f"  Resolved [info]{args.thread_id}[/]")
    console.print()


def _render_resume_human(brief: dict, console) -> None:
    """Paint the resume brief in a human-readable layout."""
    from .ui import SYM_ARROW, separator

    feature = brief.get("feature", "")
    fstate = (brief.get("current_state") or {}).get("feature_state") or "unknown"
    last_visit = brief.get("last_visit")
    window_hours = brief.get("window_hours")
    first_visit = brief.get("first_visit", False)
    switch_performed = brief.get("switch_performed", False)
    switch_summary = brief.get("switch_summary") or {}
    since = brief.get("since_last_visit") or {}
    current = brief.get("current_state") or {}
    hints = brief.get("intent_hints") or []

    console.print()
    console.print(
        f"  [feature]{feature}[/]  [muted]state: {fstate}[/]"
    )

    # Last visit line
    if first_visit:
        console.print(f"  [muted]first visit[/]")
    else:
        ago = f"  [muted]({window_hours:.0f}h ago)[/]" if window_hours is not None else ""
        console.print(f"  [muted]last visit: {last_visit}{ago}[/]")

    if switch_performed:
        prev = switch_summary.get("previously_canonical") or ""
        mode = switch_summary.get("mode", "active_rotation")
        mode_label = {"active_rotation": "active_rotation", "wind_down": "wind_down"}.get(mode, mode)
        arrow_str = f"{prev} {SYM_ARROW} {feature}" if prev else feature
        console.print(f"  [muted]switch: {arrow_str}  [{mode_label}][/]")

    # ── Since last visit ──────────────────────────────────────────────────
    separator()
    console.print(f"  [header]Since last visit[/]")

    commits = since.get("commits") or {}
    if commits:
        parts = "  ".join(
            f"[repo]{r}[/] {len(cs)}" for r, cs in commits.items() if cs
        )
        if parts:
            console.print(f"    Commits         {parts}")

    new_threads = since.get("threads_new") or []
    resolved_gh = since.get("threads_resolved_on_github") or []
    resolved_by_canopy = since.get("threads_resolved_by_canopy") or []
    if new_threads:
        repos_hit = {t.get("repo") for t in new_threads if t.get("repo")}
        suffix = f"  [muted]({', '.join(sorted(repos_hit))})[/]" if repos_hit else ""
        console.print(f"    New threads     {len(new_threads)}{suffix}")
    if resolved_gh:
        by_canopy = sum(1 for t in resolved_gh if t.get("by_canopy"))
        canon_str = f"  [muted](by canopy: {by_canopy})[/]" if by_canopy else ""
        console.print(f"    Resolved threads {len(resolved_gh)}{canon_str}")
    elif resolved_by_canopy:
        console.print(f"    Resolved by canopy {len(resolved_by_canopy)}")

    drafts_pending = since.get("draft_replies_pending", 0)
    if drafts_pending:
        console.print(f"    Draft replies   {drafts_pending} pending")

    historian_excerpt = since.get("historian_excerpt") or ""
    if historian_excerpt:
        first_line = historian_excerpt.splitlines()[0]
        console.print(f"    Memory          [muted]{first_line}[/]")

    if not any([commits, new_threads, resolved_gh, resolved_by_canopy, drafts_pending, historian_excerpt]):
        console.print(f"    [muted]nothing new[/]")

    # ── Current ───────────────────────────────────────────────────────────
    separator()
    console.print(f"  [header]Current[/]")

    linear_issue = current.get("linear_issue")
    linear_url = current.get("linear_url")
    if linear_issue:
        url_str = f"  [muted]{linear_url}[/]" if linear_url else ""
        console.print(f"    Linear          [linear]{linear_issue}[/]{url_str}")

    ci = current.get("ci_summary_per_repo") or {}
    if ci:
        ci_parts = []
        for r, status in ci.items():
            if status in ("passing", "success"):
                ci_parts.append(f"[repo]{r}[/] [success]{status}[/]")
            elif status in ("failing", "failure"):
                ci_parts.append(f"[repo]{r}[/] [error]{status}[/]")
            else:
                ci_parts.append(f"[repo]{r}[/] [muted]{status}[/]")
        console.print(f"    CI              {'  '.join(ci_parts)}")

    open_threads = current.get("open_thread_count", 0)
    if open_threads:
        console.print(f"    Open threads    {open_threads}")

    bot_unresolved = current.get("bot_unresolved_total", 0)
    if bot_unresolved:
        console.print(f"    Bot unresolved  {bot_unresolved}")

    branch_pos = current.get("branch_position_per_repo") or {}
    if branch_pos:
        for repo_name, pos in branch_pos.items():
            ahead = pos.get("ahead", 0)
            behind = pos.get("behind", 0)
            default = pos.get("default_branch", "main")
            parts = []
            if ahead:
                parts.append(f"[ahead]+{ahead}[/]")
            if behind:
                parts.append(f"[behind]-{behind}[/]")
            div_str = " ".join(parts) if parts else "[muted]up to date[/]"
            console.print(
                f"    Branch          [repo]{repo_name}[/] {div_str} [muted]from {default}[/]"
            )

    # ── Next actions ──────────────────────────────────────────────────────
    if hints:
        separator()
        console.print(f"  [header]Next actions[/]")
        for i, hint in enumerate(hints, 1):
            kind = hint.get("kind", "")
            summary = hint.get("summary", "")
            tool = hint.get("suggested_tool", "")
            tool_args = hint.get("suggested_args") or {}
            args_str = ", ".join(f'{k}="{v}"' for k, v in tool_args.items() if v)
            call_str = f"{tool}({args_str})" if tool else ""
            console.print(f"    {i}. [info]{kind}[/]  [muted]{summary}[/]")
            if call_str:
                console.print(f"         [muted]{SYM_ARROW} {call_str}[/]")

    console.print()


def cmd_resume(args: argparse.Namespace) -> None:
    """Show a fresh resume brief: what changed since last visit."""
    from ..actions.resume import feature_resume
    from ..actions.last_visit import reset_anchor
    from ..actions.errors import ActionError
    from .render import render_blocker
    from .ui import console

    workspace = _load_workspace()

    if args.reset_anchor:
        from ..actions.aliases import resolve_feature
        try:
            feature = resolve_feature(workspace, args.alias)
        except ActionError as err:
            if args.json:
                _print_json(err.to_dict())
            else:
                render_blocker(err, action="resume")
            sys.exit(1)
        cleared = reset_anchor(workspace, feature)
        if args.json:
            _print_json({"feature": feature, "cleared": cleared})
            return
        console.print(f"  [success]Cleared last_visit for {feature}[/]")
        return

    try:
        brief = feature_resume(workspace, args.alias)
    except ActionError as err:
        if args.json:
            _print_json(err.to_dict())
        else:
            render_blocker(err, action="resume")
        sys.exit(1)

    if args.json:
        _print_json(brief)
        return

    _render_resume_human(brief, console)


def cmd_context(args: argparse.Namespace) -> None:
    """Show the registry (feature ↔ repo ↔ branch ↔ path ↔ state)."""
    from ..actions.registry import context
    ws = _load_workspace()
    ctx = context(ws, cwd=Path.cwd(),
                  remote=getattr(args, "remote", False))
    if args.json:
        _print_json(ctx)
        return
    from .ui import console
    w = ctx["workspace"]
    console.print()
    console.print(f"  [header]{w['name']}[/]  active: [feature]{w['active_feature'] or '(none)'}[/]")
    for fname, fdata in ctx["features"].items():
        console.print(f"  [feature]{fname}[/]")
        for repo, r in fdata["repos"].items():
            pr = f"  PR #{r['pr']['number']} {r['pr'].get('review_decision','')}" if r.get("pr") else ""
            console.print(f"    {repo} → {r.get('current_branch', r['branch'])} "
                          f"({'dirty' if r.get('dirty') else 'clean'}){pr}")
    for adv in ctx.get("advisories", []):
        console.print(f"  [warning]⚠ {adv['message']}[/]")
    console.print()


def cmd_start(args: argparse.Namespace) -> None:
    """Begin new work on a feature (lazy)."""
    from ..actions.start import start
    from ..actions.errors import ActionError
    from .render import render_blocker
    ws = _load_workspace()
    try:
        result = start(ws, args.alias, repos=args.repos)
    except ActionError as e:
        render_blocker(e); sys.exit(1)
    if args.json:
        _print_json(result); return
    from .ui import console, print_success
    print_success(f"{result['status']}: {result['feature']}")
    if result.get("degraded"):
        console.print("  [muted]· Linear unreachable — created with id only[/]")


def cmd_join(args: argparse.Namespace) -> None:
    """Join a repo to the active feature (create + register its branch)."""
    from ..actions.join import join
    from ..actions.errors import ActionError
    from .render import render_blocker
    ws = _load_workspace()
    try:
        result = join(ws, args.repo)
    except ActionError as e:
        render_blocker(e); sys.exit(1)
    if args.json:
        _print_json(result); return
    from .ui import print_success
    print_success(f"{result['status']}: {result['repo']} → {result['branch']}")


# ── Entry point ───────────────────────────────────────────────────────────

def main() -> None:
    from .. import __version__

    parser = argparse.ArgumentParser(
        prog="canopy",
        description="Workspace-first development orchestrator.",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument(
        "--version", action="version", version=f"canopy {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command")

    # init
    init_p = subparsers.add_parser("init", help="Initialize a workspace")
    init_p.add_argument("path", nargs="?", default=None, help="Workspace root path")
    init_p.add_argument("--name", default=None, help="Workspace name")
    init_p.add_argument("--force", action="store_true", help="Overwrite existing canopy.toml")
    init_p.add_argument("--dry-run", action="store_true", help="Print toml without writing")
    init_p.add_argument("--json", action="store_true", help="Output as JSON")
    init_p.add_argument("--no-agent", action="store_true",
                         help="Skip Claude Code agent setup (skill + MCP config)")

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

    binfo = branch_sub.add_parser(
        "info",
        help="Branch info per repo (alias = feature or <repo>:<branch>)",
    )
    binfo.add_argument("alias", help="Feature alias or <repo>:<branch>")
    binfo.add_argument("--repo", default=None,
                        help="Filter feature-alias result to one repo")
    binfo.add_argument("--json", action="store_true", help="Output as JSON")

    # stash (with subcommands)
    stash_p = subparsers.add_parser("stash", help="Stash operations across repos")
    stash_sub = stash_p.add_subparsers(dest="stash_command")

    ss = stash_sub.add_parser("save", help="Stash changes")
    ss.add_argument("-m", "--message", default="", help="Stash message")
    ss.add_argument("--repos", default=None, help="Comma-separated repo names")
    ss.add_argument("--feature", default=None,
                     help="Tag stash with this feature (canopy:<f>:...) and "
                          "include untracked files")
    ss.add_argument("--json", action="store_true", help="Output as JSON")

    sp = stash_sub.add_parser("pop", help="Pop stash")
    sp.add_argument("--index", type=int, default=0, help="Stash index")
    sp.add_argument("--repos", default=None, help="Comma-separated repo names")
    sp.add_argument("--feature", default=None,
                     help="Pop the most recent stash tagged with this feature")
    sp.add_argument("--json", action="store_true", help="Output as JSON")

    sl = stash_sub.add_parser("list", help="List stashes")
    sl.add_argument("--feature", default=None,
                     help="Group/filter by feature tag")
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
    preflight_p.add_argument("feature", nargs="?", default=None,
                              help="Feature alias — when set, runs against the lane's repos and records the result")
    preflight_p.add_argument("--json", action="store_true", help="Output as JSON")

    # list (top-level shortcut)
    list_p = subparsers.add_parser("list", help="List all feature lanes")
    list_p.add_argument("--json", action="store_true", help="Output as JSON")

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
    ctx_p.add_argument("--remote", action="store_true",
                       help="Include the live PR + CI overlay (network)")

    # start (begin new work on a feature — lazy)
    start_p = subparsers.add_parser("start", help="Begin new work on a feature (lazy)")
    start_p.add_argument("alias", help="Feature name or issue id (e.g. DOC-3029)")
    start_p.add_argument("--repos", nargs="*", default=None,
                         help="Declare repos up front (default: none, lazy)")
    start_p.add_argument("--json", action="store_true")

    # join (join a repo to the active feature)
    join_p = subparsers.add_parser("join", help="Join a repo to the active feature")
    join_p.add_argument("repo", help="Repo name to join")
    join_p.add_argument("--json", action="store_true")

    # commit (feature-scoped multi-repo commit — Wave 2.3)
    commit_p = subparsers.add_parser(
        "commit",
        help="Commit across every repo in the canonical (or named) feature",
    )
    commit_p.add_argument("-m", "--message", required=False, default="",
                            help="Commit message (single message across all repos)")
    commit_p.add_argument("--feature", default=None,
                            help="Feature alias; defaults to canonical feature")
    commit_p.add_argument("--repo", "--repos", dest="repos", default=None,
                            help="Comma-separated subset of repos within the feature")
    commit_p.add_argument("--paths", nargs="*", default=None,
                            help="Filter staging to these paths (relative to each repo root)")
    commit_p.add_argument("--no-hooks", action="store_true",
                            help="Pass --no-verify to skip pre-commit / commit-msg hooks")
    commit_p.add_argument("--amend", action="store_true",
                            help="Amend HEAD in each repo instead of creating new commits")
    commit_p.add_argument("--json", action="store_true", help="Output as JSON")

    # bot-status — per-feature bot-comment rollup (M3)
    bot_status_p = subparsers.add_parser(
        "bot-status",
        help="Show bot review comments for the canonical (or named) feature",
    )
    bot_status_p.add_argument("--feature", default=None,
                                help="Feature alias; defaults to canonical feature")
    bot_status_p.add_argument("--unresolved-only", action="store_true",
                                help="Only list unresolved threads")
    bot_status_p.add_argument("--json", action="store_true", help="Output as JSON")

    # historian — cross-session feature memory (M4)
    historian_p = subparsers.add_parser(
        "historian",
        help="Read or compact a feature's persistent memory file (M4)",
    )
    historian_sub = historian_p.add_subparsers(dest="subcommand", required=True)

    historian_show = historian_sub.add_parser(
        "show", help="Print the rendered memory file for the feature",
    )
    historian_show.add_argument("feature", nargs="?", default=None,
                                  help="Feature alias; defaults to canonical feature")
    historian_show.add_argument("--json", action="store_true", help="Output as JSON")

    historian_compact = historian_sub.add_parser(
        "compact",
        help="Trim the Sessions section to the most recent N entries",
    )
    historian_compact.add_argument("feature", nargs="?", default=None,
                                     help="Feature alias; defaults to canonical feature")
    historian_compact.add_argument("--keep-sessions", type=int, default=5,
                                     dest="keep_sessions",
                                     help="Number of most-recent sessions to keep (default 5)")
    historian_compact.add_argument("--json", action="store_true", help="Output as JSON")

    # push (feature-scoped multi-repo push — Wave 2.3)
    push_p = subparsers.add_parser(
        "push",
        help="Push the feature branch in every repo (canonical by default)",
    )
    push_p.add_argument("--feature", default=None,
                          help="Feature alias; defaults to canonical feature")
    push_p.add_argument("--repo", "--repos", dest="repos", default=None,
                          help="Comma-separated subset of repos within the feature")
    push_p.add_argument("--set-upstream", action="store_true",
                          help="Pass --set-upstream for repos that lack an upstream")
    push_p.add_argument("--force-with-lease", action="store_true",
                          help="Pass --force-with-lease to allow safe non-fast-forward pushes")
    push_p.add_argument("--dry-run", action="store_true",
                          help="Enumerate what would happen without firing pushes")
    push_p.add_argument("--json", action="store_true", help="Output as JSON")

    # switch (canonical-slot focus primitive — Wave 2.9)
    switch_p = subparsers.add_parser(
        "switch",
        help="Promote a feature to the canonical slot (canonical-slot model)",
    )
    switch_p.add_argument("feature", nargs="?", default=None,
                           help="Feature alias (name or Linear ID)")
    switch_p.add_argument("--release-current", action="store_true",
                           help="Wind-down mode: previous canonical goes cold (no warm worktree)")
    switch_p.add_argument("--no-evict", action="store_true",
                           help="Refuse to auto-evict an LRU warm worktree if cap would fire")
    switch_p.add_argument("--evict", default=None,
                           help="Explicit feature name to evict to cold (overrides LRU pick)")
    switch_p.add_argument("--evict-to", default=None,
                           help="Pin which slot the previous canonical evacuates to")
    switch_p.add_argument("--to-slot", default=None,
                           help="Promote the feature currently in this slot to canonical")
    switch_p.add_argument("--json", action="store_true", help="Output as JSON")

    # slots
    slots_p = subparsers.add_parser(
        "slots",
        help="Show slot occupancy: canonical + warm slots + last_touched LRU",
    )
    slots_p.add_argument("--json", action="store_true", help="Output as JSON (always rich)")
    slots_p.add_argument("--rich", action="store_true",
                          help="Include per-slot PR/CI/bots/linear (implied by --json)")

    # slot (sub-command group for slot operations)
    slot_p = subparsers.add_parser("slot", help="Slot-targeted operations")
    slot_sub = slot_p.add_subparsers(dest="slot_cmd", required=True)
    slot_load_p = slot_sub.add_parser("load", help="Warm a cold feature into a slot")
    slot_load_p.add_argument("feature")
    slot_load_p.add_argument("slot_id", nargs="?", default=None,
                              help="Target slot id (e.g. worktree-1); defaults to lowest free")
    slot_load_p.add_argument("--replace", action="store_true",
                              help="Evict slot's current occupant first")
    slot_load_p.add_argument("--bootstrap", action="store_true",
                              help="Run env/install bootstrap after load")
    slot_load_p.add_argument("--json", action="store_true")

    slot_clear_p = slot_sub.add_parser("clear", help="Evict a slot's occupant to cold")
    slot_clear_p.add_argument("slot_id")
    slot_clear_p.add_argument("--json", action="store_true")

    slot_swap_p = slot_sub.add_parser("swap", help="Exchange occupants of two slots")
    slot_swap_p.add_argument("slot_a")
    slot_swap_p.add_argument("slot_b")
    slot_swap_p.add_argument("--json", action="store_true")

    # migrate-slots
    migrate_slots_p = subparsers.add_parser(
        "migrate-slots",
        help="One-shot migration from pre-3.0 feature-named worktrees to the 3.0 slot model",
    )
    migrate_slots_p.add_argument("--json", action="store_true", help="Output as JSON")

    # reclaim
    reclaim_p = subparsers.add_parser("reclaim", help="Free warm slots whose PR merged")
    reclaim_p.add_argument("--json", action="store_true")

    # setup-agent
    setup_p = subparsers.add_parser(
        "setup-agent",
        help="Install the using-canopy skill + add canopy MCP to .mcp.json",
    )
    setup_p.add_argument("--skill-only", action="store_true",
                          help="Install only the skill(s) (skip MCP config)")
    setup_p.add_argument("--mcp-only", action="store_true",
                          help="Install only the MCP config (skip skills)")
    setup_p.add_argument("--skill", action="append", default=None, metavar="NAME",
                          help="Install an extra bundled skill by name (e.g. 'augment-canopy'). "
                               "Repeatable. The default 'using-canopy' skill is always installed.")
    setup_p.add_argument("--reinstall", action="store_true",
                          help="Overwrite existing files even if foreign or current")
    setup_p.add_argument("--hooks", action="store_true",
                          help="Install Claude Code enforcement hooks into <workspace>/.claude/settings.json")
    setup_p.add_argument("--check", action="store_true",
                          help="Report status without changing anything")
    setup_p.add_argument("--json", action="store_true", help="Output as JSON")

    # state
    state_p = subparsers.add_parser(
        "state",
        help="Feature state + suggested next actions (dashboard backend)",
    )
    state_p.add_argument("feature", nargs="?", default=None,
                          help="Feature alias (name or Linear ID). Defaults to active feature if any.")
    state_p.add_argument("--json", action="store_true", help="Output as JSON")

    # triage
    triage_p = subparsers.add_parser(
        "triage",
        help="Prioritized list of features needing attention",
    )
    triage_p.add_argument("--author", default="@me",
                           help="Filter PRs to this author (default: @me)")
    triage_p.add_argument("--repos", default=None,
                           help="Comma-separated subset of repos to scan")
    triage_p.add_argument("--json", action="store_true", help="Output as JSON")

    # drift
    pr_checks_p = subparsers.add_parser(
        "pr-checks",
        help="CI check rollup for a PR alias (M10)",
    )
    pr_checks_p.add_argument("alias", help="Feature alias, <repo>#<n>, or PR URL")
    pr_checks_p.add_argument("--json", action="store_true", help="Output as JSON")

    bootstrap_p = subparsers.add_parser(
        "worktree-bootstrap",
        help="Bootstrap a feature's worktrees (env files, deps, IDE workspace) — M6",
    )
    bootstrap_p.add_argument("feature", help="Feature alias to bootstrap")
    bootstrap_p.add_argument("--force", action="store_true",
                              help="Overwrite existing destination env files")
    bootstrap_p.add_argument("--step", choices=["env", "deps", "ide"], default=None,
                              help="Run only one step instead of all three")
    bootstrap_p.add_argument("--deps", action="store_true",
                              help="Deps step only (env/ide/hooks skipped)")
    bootstrap_p.add_argument("--interactive", action="store_true",
                              help="Run deps install in the foreground (streams output, handles prompts)")
    bootstrap_p.add_argument("--_slot", default=None, help=argparse.SUPPRESS)
    bootstrap_p.add_argument("--json", action="store_true", help="Output as JSON")

    ship_p = subparsers.add_parser(
        "ship",
        help="Open or update one PR per repo in the canonical feature (M8 / Wave 2.4)",
    )
    ship_p.add_argument("--feature", default=None,
                          help="Feature alias (defaults to canonical)")
    ship_p.add_argument("--repo", "--repos", dest="repos", default=None,
                          help="Comma-separated repo names to scope the ship")
    ship_p.add_argument("--draft", action="store_true",
                          help="Open PRs as drafts (initial open only)")
    ship_p.add_argument("--reviewers", default=None,
                          help="Comma-separated GitHub handles to request review from")
    ship_p.add_argument("--base", default=None,
                          help="Override base branch (default: each repo's default_branch)")
    ship_p.add_argument("--dry-run", action="store_true",
                          help="Enumerate without firing pushes or opening PRs")
    ship_p.add_argument("--json", action="store_true", help="Output as JSON")

    draft_replies_p = subparsers.add_parser(
        "draft-replies",
        help="Auto-draft replies for addressed PR review comments (M9)",
    )
    draft_replies_p.add_argument(
        "alias", help="Feature alias, <repo>#<n>, or PR URL",
    )
    draft_replies_p.add_argument(
        "--include-likely-resolved", action="store_true",
        help="Also draft for the temporal classifier's likely_resolved set (low confidence)",
    )
    draft_replies_p.add_argument("--json", action="store_true", help="Output as JSON")

    conflicts_p = subparsers.add_parser(
        "conflicts",
        help="Cross-feature file-overlap detection (M12)",
    )
    conflicts_p.add_argument("--feature", default=None,
                              help="Scope to pairs involving this feature")
    conflicts_p.add_argument("--with", dest="with_", default=None,
                              help="Further scope to <feature> vs <other>")
    conflicts_p.add_argument("--include-cold", action="store_true",
                              help="Also scan cold features (default: active only)")
    conflicts_p.add_argument("--lines", action="store_true",
                              help="Compute line-range overlap (slower; downgrades to medium when files overlap but lines don't)")
    conflicts_p.add_argument("--json", action="store_true", help="Output as JSON")

    drift_p = subparsers.add_parser(
        "drift",
        help="Show alignment between recorded HEADs and active feature lanes",
    )
    drift_p.add_argument("feature", nargs="?", default=None,
                         help="Limit to a specific feature lane")
    drift_p.add_argument("--json", action="store_true", help="Output as JSON")

    # issue — fetch one issue from the configured provider (M5+)
    issue_p = subparsers.add_parser(
        "issue",
        help="Fetch an issue from the workspace provider (Linear / GitHub Issues)",
    )
    issue_p.add_argument("alias",
                          help="Provider-native id (SIN-412 / 5 / #5 / owner/repo#5 / URL) or feature alias")
    issue_p.add_argument("--json", action="store_true", help="Output as JSON")

    # issues — list current user's open issues from the configured provider (F-5)
    issues_p = subparsers.add_parser(
        "issues",
        help="List the current user's open issues from the workspace provider",
    )
    issues_p.add_argument("--limit", type=int, default=25,
                            help="Max issues to return (default 25)")
    issues_p.add_argument("--json", action="store_true", help="Output as JSON")

    # pr (GitHub)
    pr_p = subparsers.add_parser(
        "pr",
        help="Fetch PR data per repo (alias = feature, <repo>#<n>, or PR URL)",
    )
    pr_p.add_argument("alias", help="Feature alias, <repo>#<n>, or PR URL")
    pr_p.add_argument("--json", action="store_true", help="Output as JSON")

    # branch info (read tool — sits alongside branch list/delete/rename)

    # comments (PR review comments)
    comments_p = subparsers.add_parser(
        "comments",
        help="Temporally classified PR review comments (alias = feature, <repo>#<n>, URL)",
    )
    comments_p.add_argument("alias", help="Feature alias, <repo>#<n>, or PR URL")
    comments_p.add_argument("--json", action="store_true", help="Output as JSON")

    # run
    run_p = subparsers.add_parser(
        "run",
        help="Run a shell command in a canopy-managed repo (resolves cwd safely)",
    )
    run_p.add_argument("repo", help="Repo name (from canopy.toml)")
    # NB: positional named "cmd" not "command" — the top-level subparser
    # dispatch uses dest="command" and would clobber it.
    run_p.add_argument("cmd", help="Shell command to run")
    run_p.add_argument("--feature", default=None,
                       help="Feature lane (selects worktree path if applicable)")
    run_p.add_argument("--timeout", type=int, default=60,
                       help="Kill the process after N seconds (default 60)")
    run_p.add_argument("--json", action="store_true", help="Output as JSON")

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

    # doctor
    doctor_p = subparsers.add_parser(
        "doctor",
        help="Diagnose workspace + install integrity; --fix to repair",
    )
    doctor_p.add_argument(
        "--fix", action="store_true",
        help="Repair every auto-fixable issue",
    )
    doctor_p.add_argument(
        "--fix-category",
        choices=sorted(["heads", "active_feature", "worktrees", "hooks",
                        "preflight", "features", "branches",
                        "cli", "mcp", "skill", "vsix"]),
        default=None,
        help="Repair only one category (implies --fix)",
    )
    doctor_p.add_argument(
        "--feature", default=None,
        help="Scope feature-bearing checks to one feature",
    )
    doctor_p.add_argument(
        "--clean-vsix", action="store_true",
        help="Remove duplicate vsix install dirs (gates the vsix repair)",
    )
    doctor_p.add_argument(
        "-v", "--verbose", action="store_true",
        help="Show expected/actual values per issue",
    )
    doctor_p.add_argument("--json", action="store_true", help="Output as JSON")

    reply_p = subparsers.add_parser(
        "reply",
        help="Post a reply to a GH review thread",
    )
    reply_p.add_argument("thread_id", help="Thread node ID (starts with PRRT_)")
    _reply_body_g = reply_p.add_mutually_exclusive_group()
    _reply_body_g.add_argument("--body", default=None,
                               help="Reply body text")
    _reply_body_g.add_argument("--body-file", default=None,
                               help="Path to file containing the reply body")
    reply_p.add_argument("--resolve", action="store_true",
                         help="Resolve the thread after posting")
    reply_p.add_argument("--feature", default=None,
                         help="Feature alias; defaults to canonical feature")
    reply_p.add_argument("--json", action="store_true", help="Output as JSON")

    resolve_p = subparsers.add_parser(
        "resolve",
        help="Resolve a GitHub PR review thread and record it locally",
    )
    resolve_p.add_argument("thread_id", help="Thread node ID (starts with PRRT_)")
    resolve_p.add_argument("--feature", default=None,
                           help="Feature alias; defaults to canonical feature")
    resolve_p.add_argument("--json", action="store_true", help="Output as JSON")

    # resume
    resume_p = subparsers.add_parser(
        "resume",
        help="Fresh brief: what changed since last visit",
    )
    resume_p.add_argument("alias", help="Feature alias (name, Linear ID, slot id, etc.)")
    resume_p.add_argument("--json", action="store_true", help="Output as JSON")
    resume_p.add_argument(
        "--reset-anchor", action="store_true",
        help="Clear last_visit so the next call is treated as a first visit",
    )

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
        "review": cmd_review,
        "done": cmd_done,
        "config": cmd_config,
        "context": cmd_context,
        "start": cmd_start,
        "join": cmd_join,
        "hooks": cmd_hooks,
        "drift": cmd_drift,
        "run": cmd_run,
        "issue": cmd_issue,
        "issues": cmd_issues,
        "pr": cmd_pr,
        "comments": cmd_comments,
        "switch": cmd_switch,
        "slots": cmd_slots,
        "migrate-slots": cmd_migrate_slots,
        "reclaim": cmd_reclaim,
        "commit": cmd_commit,
        "bot-status": cmd_bot_status,
        "historian": cmd_historian,
        "push": cmd_push,
        "triage": cmd_triage,
        "state": cmd_state,
        "setup-agent": cmd_setup_agent,
        "doctor": cmd_doctor,
        "conflicts": cmd_conflicts,
        "draft-replies": cmd_draft_replies,
        "ship": cmd_ship,
        "worktree-bootstrap": cmd_worktree_bootstrap,
        "pr-checks": cmd_pr_checks,
        "resolve": cmd_resolve_thread,
        "reply": cmd_reply_thread,
        "resume": cmd_resume,
    }

    if args.command == "feature":
        if not args.feature_command:
            feature_p.print_help()
            sys.exit(0)
        feature_commands = {
            "create": cmd_feature_create,
            "list": cmd_feature_list,
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
            "info": cmd_branch,
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
    elif args.command == "slot":
        slot_commands = {
            "load": cmd_slot_load,
            "clear": cmd_slot_clear,
            "swap": cmd_slot_swap,
        }
        slot_commands[args.slot_cmd](args)
    elif args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
