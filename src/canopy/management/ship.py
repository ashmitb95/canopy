"""``canopy ship`` — capstone of the per-feature workflow (M8 / Wave 2.4).

Take a feature from "code is committed" to "PR is open and reviewers
can look." Per-repo recipe: ensure-pushed → ensure-PR-exists. After all
PRs are open, a second pass updates each PR body with the *now-known*
sibling PR numbers so reviewers landing on the API PR see the UI PR
linked (and vice versa).

**Idempotent.** Re-running ``ship`` after more commits + push reports
``up_to_date`` per repo (PRs auto-track the branch). Re-running after
manually closing a PR reports ``closed`` and refuses to silently
recreate.

**Atomic.** No silent destruction. If the PR's head SHA doesn't match
what we just pushed (force-push divergence), we report ``diverged``
and skip the body update — the user investigates.

Read the existing push primitive first; this orchestrator only opens/
updates PRs and re-uses ``actions/push.push`` for the publish step.
"""
from __future__ import annotations

from typing import Any

from ..git import repo as git
from ..integrations import github as gh
from ..workspace.workspace import Workspace
from ..actions import slots as slots_mod
from ..actions.aliases import _resolve_owner_slug, repos_for_feature, resolve_feature
from ..actions.errors import BlockerError, FixAction
from .feature_state import resolve_repo_paths
from ..actions.push import push as push_impl


def ship(
    workspace: Workspace,
    *,
    feature: str | None = None,
    repos: list[str] | None = None,
    draft: bool = False,
    reviewers: list[str] | None = None,
    dry_run: bool = False,
    base: str | None = None,
) -> dict[str, Any]:
    """Open or update one PR per repo in the canonical (or named) feature.

    Args:
        workspace: loaded workspace.
        feature: feature alias. Defaults to the canonical slot.
        repos: optional filter — only ship these repos within the feature
            scope.
        draft: open PRs as drafts (initial open only; doesn't auto-undraft
            on subsequent ships).
        reviewers: GitHub usernames / team slugs to request review from.
        dry_run: enumerate what would happen without firing pushes or
            opening PRs.
        base: override the base branch for every repo. Default: each
            repo's ``default_branch`` from canopy.toml (matches Phil's
            per-repo target_branch when set there).

    Returns ``{feature, results: {<repo>: {status, pr_number?, url?,
    reason?, warning?}}, cross_repo_links_updated: bool}``.
    """
    feature_name = _resolve_feature_name(workspace, feature)
    repo_branches = repos_for_feature(workspace, feature_name)
    if not repo_branches:
        raise BlockerError(
            code="empty_feature",
            what=f"feature '{feature_name}' has no associated repos",
        )

    if repos:
        wanted = set(repos)
        repo_branches = {r: b for r, b in repo_branches.items() if r in wanted}
        if not repo_branches:
            raise BlockerError(
                code="repos_filter_empty",
                what=f"none of {sorted(repos)} are in feature '{feature_name}'",
            )

    repo_paths, _ = resolve_repo_paths(workspace, feature_name, repo_branches)

    # First pass: per-repo ensure-pushed → ensure-PR-exists.
    results: dict[str, dict[str, Any]] = {}
    for repo_name, branch in repo_branches.items():
        repo_path = repo_paths.get(repo_name)
        if repo_path is None:
            results[repo_name] = {"status": "failed", "reason": "repo path unresolved"}
            continue
        results[repo_name] = _ship_one(
            workspace, feature_name, repo_name, branch, repo_path,
            draft=draft, reviewers=reviewers, dry_run=dry_run, base_override=base,
        )

    cross_links_updated = False
    if not dry_run:
        cross_links_updated = _refresh_cross_repo_links(
            workspace, feature_name, results,
        )

    return {
        "feature": feature_name,
        "results": results,
        "cross_repo_links_updated": cross_links_updated,
    }


# ── per-repo ────────────────────────────────────────────────────────────

def _ship_one(
    workspace: Workspace,
    feature_name: str,
    repo_name: str,
    branch: str,
    repo_path,
    *,
    draft: bool,
    reviewers: list[str] | None,
    dry_run: bool,
    base_override: str | None,
) -> dict[str, Any]:
    """Run ship for one repo. Returns the per-repo result dict."""
    state = workspace.get_repo(repo_name)
    base = base_override or state.config.default_branch

    # 0. Check that the branch exists locally + has commits ahead of base.
    if not git.branch_exists(repo_path, branch):
        return {"status": "skipped", "reason": "no branch on disk"}
    ahead = _ahead_count(repo_path, branch, base)
    if ahead == 0:
        return {"status": "skipped", "reason": "no commits ahead of base"}

    if dry_run:
        return _dry_run_one(workspace, repo_name, branch, base, ahead)

    # 1. Make sure the branch is pushed. push_impl handles set-upstream,
    #    up-to-date short-circuit, and rejected/failed classification.
    push_result = push_impl(
        workspace, feature=feature_name, repos=[repo_name], set_upstream=True,
    )
    pushed = push_result["results"].get(repo_name, {})
    if pushed.get("status") in ("rejected", "failed"):
        return {
            "status": "failed",
            "reason": f"push failed: {pushed.get('reason', pushed['status'])}",
        }

    # 2. Look up an existing PR for this branch.
    try:
        owner, repo_slug = _resolve_owner_slug(workspace, repo_name)
    except BlockerError as err:
        return {"status": "failed", "reason": f"owner/slug unresolved: {err.what}"}
    try:
        existing = gh.find_pull_request(workspace.config.root, owner, repo_slug, branch)
    except gh.GitHubNotConfiguredError as err:
        return {
            "status": "failed",
            "reason": f"github not configured: {err.payload.get('what', '')}",
        }

    if existing:
        return _classify_existing_pr(repo_path, branch, existing)

    # 3. No PR — open one.
    title = _format_title(workspace, feature_name)
    body = _format_body_initial(workspace, feature_name, repo_name)
    try:
        created = gh.create_pr(
            workspace.config.root, owner, repo_slug,
            branch=branch, base=base, title=title, body=body,
            draft=draft, reviewers=reviewers,
        )
    except gh.GitHubNotConfiguredError as err:
        return {"status": "failed", "reason": f"create failed: {err.payload.get('what', '')}"}
    return {
        "status": "opened",
        "pr_number": created.get("number"),
        "url": created.get("url"),
        "draft": draft,
    }


def _classify_existing_pr(repo_path, branch: str, pr: dict) -> dict[str, Any]:
    """Classify an existing PR vs the local branch state."""
    pr_state = (pr.get("state") or "").lower()
    if pr_state in ("closed", "merged"):
        return {
            "status": "closed",
            "pr_number": pr.get("number"),
            "url": pr.get("url"),
            "reason": f"PR is {pr_state}; manual reopen needed",
        }

    pr_head = pr.get("head_sha") or pr.get("head", {}).get("sha") or ""
    local_head = git.head_sha(repo_path)
    if pr_head and local_head and pr_head != local_head:
        return {
            "status": "diverged",
            "pr_number": pr.get("number"),
            "url": pr.get("url"),
            "warning": "PR head sha doesn't match local; force-push divergence — manual review recommended",
        }

    return {
        "status": "up_to_date",
        "pr_number": pr.get("number"),
        "url": pr.get("url"),
    }


def _dry_run_one(
    workspace: Workspace, repo_name: str, branch: str, base: str, ahead: int,
) -> dict[str, Any]:
    """Cheap read-only enumeration of what ship would do for this repo."""
    try:
        owner, repo_slug = _resolve_owner_slug(workspace, repo_name)
        existing = gh.find_pull_request(workspace.config.root, owner, repo_slug, branch)
    except (BlockerError, gh.GitHubNotConfiguredError):
        existing = None
    if existing:
        return {
            "status": "would_update_or_skip",
            "pr_number": existing.get("number"),
            "url": existing.get("url"),
            "ahead": ahead,
            "base": base,
            "dry_run": True,
        }
    return {
        "status": "would_open",
        "ahead": ahead,
        "base": base,
        "dry_run": True,
    }


# ── cross-repo body refresh ─────────────────────────────────────────────

def _refresh_cross_repo_links(
    workspace: Workspace, feature_name: str, results: dict[str, dict],
) -> bool:
    """After all PRs are open/up-to-date, update each body with sibling PR
    numbers. Returns True iff at least one body was updated."""
    pr_pairs: list[tuple[str, int, str]] = []
    for repo, result in results.items():
        pr_number = result.get("pr_number")
        url = result.get("url") or ""
        if pr_number and result.get("status") in ("opened", "up_to_date"):
            pr_pairs.append((repo, int(pr_number), url))
    if len(pr_pairs) < 2:
        # Single-repo feature — body's "1 of 1" line is already accurate
        # from the initial open. Nothing cross-repo to add.
        return False

    updated_any = False
    for repo_name, pr_number, _url in pr_pairs:
        try:
            owner, repo_slug = _resolve_owner_slug(workspace, repo_name)
        except BlockerError:
            continue
        new_body = _format_body_with_siblings(
            workspace, feature_name, repo_name, pr_pairs,
        )
        try:
            gh.update_pr_body(
                workspace.config.root, owner, repo_slug, pr_number, new_body,
            )
            updated_any = True
        except gh.GitHubNotConfiguredError:
            break
    return updated_any


# ── formatters ──────────────────────────────────────────────────────────

def _format_title(workspace: Workspace, feature_name: str) -> str:
    """`<LINEAR-ID> <feature title or feature name>` per spec."""
    feature_meta = _read_feature_entry(workspace, feature_name)
    linear_id = (feature_meta or {}).get("linear_issue") or ""
    title = (feature_meta or {}).get("linear_title") or feature_name
    if linear_id:
        return f"{linear_id} {title}".strip()
    return feature_name


def _format_body_initial(
    workspace: Workspace, feature_name: str, repo_name: str,
) -> str:
    """Body emitted on first open — no sibling PR numbers yet."""
    feature_meta = _read_feature_entry(workspace, feature_name) or {}
    linear_url = feature_meta.get("linear_url") or ""
    linear_id = feature_meta.get("linear_issue") or ""
    repos = feature_meta.get("repos") or [repo_name]

    lines: list[str] = []
    if linear_url:
        lines.append(f"[Linear: {linear_id}]({linear_url})")
        lines.append("")
    lines.append(
        f"This PR is part of the canopy feature `{feature_name}` "
        f"({_position(repo_name, repos)} of {len(repos)} repos):"
    )
    lines.append("")
    for r in repos:
        if r == repo_name:
            lines.append(f"- {r}: this PR")
        else:
            lines.append(f"- {r}: (sibling PR pending; ship will link on second pass)")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("🌳 Opened by [canopy](https://github.com/ashmitb95/canopy)")
    return "\n".join(lines)


def _format_body_with_siblings(
    workspace: Workspace,
    feature_name: str,
    repo_name: str,
    pr_pairs: list[tuple[str, int, str]],
) -> str:
    """Body emitted on the cross-repo refresh pass — sibling PRs known."""
    feature_meta = _read_feature_entry(workspace, feature_name) or {}
    linear_url = feature_meta.get("linear_url") or ""
    linear_id = feature_meta.get("linear_issue") or ""
    by_repo = {r: (n, u) for r, n, u in pr_pairs}

    lines: list[str] = []
    if linear_url:
        lines.append(f"[Linear: {linear_id}]({linear_url})")
        lines.append("")
    lines.append(
        f"This PR is part of the canopy feature `{feature_name}` "
        f"({_position(repo_name, [r for r, _, _ in pr_pairs])} of {len(pr_pairs)} repos):"
    )
    lines.append("")
    for r, n, u in pr_pairs:
        if r == repo_name:
            lines.append(f"- {r}: this PR (#{n})")
        else:
            lines.append(f"- {r}: [#{n}]({u})")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("🌳 Opened by [canopy](https://github.com/ashmitb95/canopy)")
    return "\n".join(lines)


# ── helpers ─────────────────────────────────────────────────────────────

def _resolve_feature_name(workspace: Workspace, feature: str | None) -> str:
    if feature:
        return resolve_feature(workspace, feature)
    state = slots_mod.read_state(workspace)
    if state is None or state.canonical is None:
        raise BlockerError(
            code="no_canonical_feature",
            what="no active feature; pass --feature or run `canopy switch <name>` first",
            fix_actions=[
                FixAction(action="switch", args={}, safe=False,
                          preview="canopy switch <feature> sets the canonical slot"),
            ],
        )
    return state.canonical.feature


def _read_feature_entry(workspace: Workspace, feature_name: str) -> dict | None:
    """Load the features.json entry for ``feature_name``, or None."""
    import json
    path = workspace.config.root / ".canopy" / "features.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return data.get(feature_name)


def _ahead_count(repo_path, branch: str, base: str) -> int:
    """Count commits unique to ``branch`` vs ``base``. 0 means nothing to ship."""
    try:
        out = git._run_ok(
            ["rev-list", "--count", f"{base}..{branch}"], cwd=repo_path,
        )
    except git.GitError:
        return 0
    try:
        return int(out.strip())
    except (TypeError, ValueError):
        return 0


def _position(needle: str, haystack: list[str]) -> int:
    """1-based index of ``needle`` in ``haystack``, or len+1 if missing."""
    try:
        return haystack.index(needle) + 1
    except ValueError:
        return len(haystack) + 1
