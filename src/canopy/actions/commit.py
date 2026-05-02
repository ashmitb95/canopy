"""commit — feature-scoped multi-repo commit.

Stages tracked changes (or explicit ``paths``) and commits across every
repo in a feature lane with a single message. The canonical feature is
inferred from ``active_feature.json`` when no ``--feature`` is given;
explicit names override.

Pre-flight: every in-scope repo must currently be on its expected branch
(``lane.branches[repo]`` or, by default, the feature name). If any repo
has drifted to a different branch, commit refuses before any side effects
and surfaces a ``BlockerError(code='wrong_branch')`` whose ``details``
carry the per-repo expected/actual map.

Per-repo recipe::

    1. stage --paths if given, else `git add -u` (all tracked changes)
    2. if nothing staged → status: "nothing"
    3. else `git commit -m <message>` (hooks honored unless no_hooks)
    4. on hook failure → status: "hooks_failed" + hook_output tail
    5. on success     → status: "ok" + sha + files_changed

Per-repo failure does NOT cancel other repos. Result aggregates the
per-repo outcome dict so the caller can act on partial success.

The ``--address <comment-id>`` flag (M3) auto-formats the commit message
with a bot comment's title + URL and records a resolution entry in
``.canopy/state/bot_resolutions.json`` when the matching repo commits
successfully.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..git import repo as git
from ..workspace.workspace import Workspace
from . import active_feature as af
from .aliases import repos_for_feature, resolve_feature
from .bot_resolutions import record_resolution
from .errors import BlockerError, FixAction
from .feature_state import _per_repo_facts, resolve_repo_paths


def _resolve_feature_name(
    workspace: Workspace, feature: str | None,
) -> str:
    """Pick the feature: explicit alias → resolved name, else canonical."""
    if feature:
        return resolve_feature(workspace, feature)
    active = af.read_active(workspace)
    if active is None:
        raise BlockerError(
            code="no_canonical_feature",
            what="no active feature; pass --feature or run `canopy switch <name>` first",
            fix_actions=[
                FixAction(action="switch", args={}, safe=False,
                          preview="canopy switch <feature> sets the canonical slot"),
            ],
        )
    return active.feature


def _verify_branches(
    repo_paths: dict[str, Path],
    repo_branches: dict[str, str],
) -> None:
    """Raise BlockerError if any repo's current branch != expected.

    Ran before any per-repo work. ``details.per_repo`` carries the
    full expected/actual map so the agent can decide how to recover.
    """
    mismatches: dict[str, dict[str, str]] = {}
    for repo_name, expected in repo_branches.items():
        path = repo_paths.get(repo_name)
        if path is None:
            continue
        actual = git.current_branch(path)
        if actual != expected:
            mismatches[repo_name] = {"expected": expected, "actual": actual}

    if not mismatches:
        return

    fixes = [
        FixAction(action="switch", args={}, safe=False,
                  preview="canopy switch <feature> aligns all repos"),
    ]
    raise BlockerError(
        code="wrong_branch",
        what=(
            f"{len(mismatches)} repo(s) are on a different branch than the feature expects"
        ),
        details={"per_repo": mismatches},
        fix_actions=fixes,
    )


def _commit_one(
    repo_path: Path,
    message: str,
    *,
    paths: list[str] | None,
    no_hooks: bool,
    amend: bool,
) -> dict[str, Any]:
    """Commit one repo. Returns a per-repo result dict."""
    if amend:
        # `--amend` works regardless of staging state; we still stage paths
        # if requested, but skip the empty-stage early-return below.
        if paths:
            try:
                git.stage_files(repo_path, paths)
            except git.GitError as e:
                return {"status": "failed", "reason": str(e)}
        else:
            try:
                git.stage_all_tracked(repo_path)
            except git.GitError as e:
                return {"status": "failed", "reason": str(e)}
        try:
            result = git.commit(
                repo_path, message, amend=True, no_hooks=no_hooks,
            )
        except git.GitError as e:
            return _classify_commit_error(e)
        return {
            "status": "ok",
            "sha": result["sha"],
            "files_changed": result["files_changed"],
            "amended": True,
        }

    # Non-amend path: stage, then short-circuit if nothing's staged.
    try:
        if paths:
            git.stage_files(repo_path, paths)
        else:
            git.stage_all_tracked(repo_path)
    except git.GitError as e:
        return {"status": "failed", "reason": str(e)}

    if git.staged_file_count(repo_path) == 0:
        return {"status": "nothing", "reason": "no changes to commit"}

    try:
        result = git.commit(repo_path, message, no_hooks=no_hooks)
    except git.GitError as e:
        return _classify_commit_error(e)

    return {
        "status": "ok",
        "sha": result["sha"],
        "files_changed": result["files_changed"],
    }


def _classify_commit_error(err: git.GitError) -> dict[str, Any]:
    """Distinguish hook-failures from other commit failures.

    Pre-commit / commit-msg hooks fail with stderr that mentions the hook
    name; other failures (gpg, locked index, etc.) get reported as-is.
    """
    msg = str(err)
    lower = msg.lower()
    if "pre-commit" in lower or "commit-msg" in lower or "hook" in lower:
        tail = "\n".join(msg.splitlines()[-10:])
        return {"status": "hooks_failed", "hook_output": tail}
    return {"status": "failed", "reason": msg}


def commit(
    workspace: Workspace,
    message: str,
    *,
    feature: str | None = None,
    repos: list[str] | None = None,
    paths: list[str] | None = None,
    no_hooks: bool = False,
    amend: bool = False,
    address: str | None = None,
) -> dict[str, Any]:
    """Commit across every repo in a feature lane.

    Args:
        workspace: the workspace.
        message: commit message (required unless ``amend`` or ``address``
            supplies one). Empty messages should be rejected at the CLI
            parse layer before reaching here.
        feature: feature alias. If None, falls back to the canonical
            feature in ``active_feature.json``.
        repos: optional filter — only commit in these repos within
            the feature scope. Repos NOT in the feature lane are
            silently skipped (single source of truth: the feature).
        paths: optional file path filter; relative to each repo root.
            If given, ``git add <paths>`` instead of ``git add -u``.
        no_hooks: skip pre-commit / commit-msg hooks (``--no-verify``).
        amend: amend HEAD instead of creating a new commit.
        address: a bot review comment ID or its GitHub URL (M3). When
            set, the commit message is auto-suffixed with the comment
            title + URL, and on success the resolution is recorded in
            ``.canopy/state/bot_resolutions.json``. Comment must belong
            to one of the feature's actionable bot threads; a non-bot
            comment raises ``BlockerError(code='not_a_bot_comment')``.

    Returns ``{feature, results: {<repo>: {...}}, addressed?}``. The
    per-repo dict has shape ``{status, sha?, files_changed?, reason?,
    hook_output?, amended?}`` where ``status`` is one of
    ``ok | nothing | hooks_failed | failed``. When ``--address`` is given
    and a resolution was recorded, ``addressed`` carries
    ``{comment_id, repo, sha, title, url}``.
    """
    feature_name = _resolve_feature_name(workspace, feature)
    repo_branches = repos_for_feature(workspace, feature_name)
    if not repo_branches:
        raise BlockerError(
            code="empty_feature",
            what=f"feature '{feature_name}' has no associated repos",
        )

    # Optional repo filter — restrict to subset, but never expand beyond
    # the feature scope.
    if repos:
        repo_branches = {
            r: b for r, b in repo_branches.items() if r in set(repos)
        }
        if not repo_branches:
            raise BlockerError(
                code="repos_filter_empty",
                what=f"none of {sorted(repos)} are in feature '{feature_name}'",
                details={"feature_repos": sorted(repos_for_feature(workspace, feature_name).keys())},
            )

    repo_paths, _has_wt = resolve_repo_paths(workspace, feature_name, repo_branches)

    # ── --address: locate the bot comment and rewrite the message ───────
    addressed_info: dict[str, Any] | None = None
    if address is not None:
        comment_id = _parse_comment_id(address)
        bot_comment, owning_repo = _find_actionable_bot_comment(
            workspace, feature_name, repo_branches, repo_paths, comment_id,
        )
        if bot_comment is None:
            raise BlockerError(
                code="not_a_bot_comment",
                what=(
                    f"comment {comment_id} is not in any actionable bot thread for "
                    f"feature '{feature_name}'"
                ),
                details={
                    "feature": feature_name,
                    "comment_id": comment_id,
                    "hint": (
                        "verify the id with `canopy bot-status --feature "
                        f"{feature_name}` and pass either the numeric id or "
                        "the comment URL"
                    ),
                },
            )
        title = _comment_title(bot_comment.get("body", ""))
        url = bot_comment.get("url", "")
        message = _format_address_message(message or "", title, url)
        addressed_info = {
            "comment_id": comment_id,
            "repo": owning_repo,
            "title": title,
            "url": url,
        }

    if not message and not amend:
        # CLI argparse should catch this, but guard for direct callers.
        raise BlockerError(
            code="empty_message",
            what="commit message is required",
        )

    if amend:
        # Amend skips the wrong_branch pre-check — amending a commit on a
        # different branch is sometimes intentional (rebase aftermath).
        # Other failures still surface per-repo.
        pass
    else:
        _verify_branches(repo_paths, repo_branches)

    results: dict[str, dict[str, Any]] = {}
    for repo_name, repo_path in repo_paths.items():
        results[repo_name] = _commit_one(
            repo_path,
            message,
            paths=paths,
            no_hooks=no_hooks,
            amend=amend,
        )

    out: dict[str, Any] = {"feature": feature_name, "results": results}

    # Record the resolution iff the owning repo committed successfully.
    if addressed_info is not None:
        owning = addressed_info["repo"]
        owning_result = results.get(owning, {})
        if owning_result.get("status") == "ok":
            sha = owning_result["sha"]
            record_resolution(
                workspace.config.root,
                comment_id=addressed_info["comment_id"],
                feature=feature_name,
                repo=owning,
                commit_sha=sha,
                comment_title=addressed_info["title"],
                comment_url=addressed_info["url"],
            )
            addressed_info["sha"] = sha
            addressed_info["recorded"] = True
        else:
            addressed_info["recorded"] = False
            addressed_info["reason"] = (
                f"owning repo '{owning}' commit status: {owning_result.get('status', 'unknown')}"
            )
        out["addressed"] = addressed_info

    return out


# ── --address helpers ────────────────────────────────────────────────────


_TRAILING_DIGITS = re.compile(r"(\d+)\s*$")


def _parse_comment_id(address: str) -> str:
    """Accept a numeric id, a ``#123`` form, or a GitHub URL.

    GitHub URLs end with ``#discussion_r<N>``, ``#issuecomment-<N>``, or
    similar — we extract the trailing digit run as the canonical id.
    """
    raw = address.strip()
    match = _TRAILING_DIGITS.search(raw)
    if not match:
        raise BlockerError(
            code="invalid_comment_id",
            what=f"could not parse a comment id from '{address}'",
            details={"hint": "pass a numeric id (e.g. 123456) or the GitHub comment URL"},
        )
    return match.group(1)


def _find_actionable_bot_comment(
    workspace: Workspace,
    feature_name: str,
    repo_branches: dict[str, str],
    repo_paths: dict[str, Path],
    comment_id: str,
) -> tuple[dict | None, str | None]:
    """Walk per-repo bot threads for a matching comment id.

    Returns ``(comment_dict, owning_repo)`` or ``(None, None)`` when no
    actionable bot thread carries the requested id.
    """
    facts = _per_repo_facts(workspace, feature_name, repo_branches, repo_paths)
    for repo_name, repo_facts in facts.items():
        for thread in repo_facts.get("actionable_bot_threads", []):
            if str(thread.get("id", "")) == comment_id:
                return thread, repo_name
    return None, None


def _comment_title(body: str, max_len: int = 80) -> str:
    """First non-empty line of the comment, trimmed to ``max_len``."""
    for line in (body or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if len(line) <= max_len:
            return line
        return line[:max_len].rstrip() + "…"
    return ""


def _format_address_message(user_message: str, title: str, url: str) -> str:
    """Append the standard ``Addresses bot comment`` trailer."""
    suffix_parts = [f'Addresses bot comment: "{title}"' if title else "Addresses bot comment"]
    if url:
        suffix_parts[-1] += f" ({url})"
    suffix = "\n\n".join(suffix_parts)
    if user_message.strip():
        return f"{user_message.rstrip()}\n\n{suffix}"
    return suffix
