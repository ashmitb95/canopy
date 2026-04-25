"""Feature-aware stash tagging.

Wraps the existing per-repo stash primitives so a stash saved in a
feature context carries a structured prefix in its message. The prefix
shape — ``[canopy <feature> @ <iso_ts>] <user_message>`` — is readable
in ``git stash list`` output and easy to parse back.

Untagged stashes still work end-to-end. ``list_grouped`` groups stashes
by feature using the tag; entries without the prefix go in
``untagged``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..git import multi as git_multi
from ..git import repo as git
from ..workspace.workspace import Workspace
from .aliases import resolve_feature
from .errors import BlockerError, FailedError, FixAction


# Git stash auto-prefixes the stored message with "On <branch>: " (or
# "WIP on <branch>: ..." when no -m given). Match the canopy tag anywhere
# after that optional prefix; user message is whatever follows the ``]``.
_TAG = re.compile(r"\[canopy (\S+) @ (\S+)\] ?(.*)$", re.DOTALL)


@dataclass(frozen=True)
class StashEntry:
    repo: str
    index: int
    ref: str            # 'stash@{N}'
    message: str        # raw message as git stored it
    feature: str | None # parsed from tag, None if untagged
    ts: str | None      # parsed from tag
    user_message: str   # message text after the tag, OR raw if untagged

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "index": self.index,
            "ref": self.ref,
            "message": self.message,
            "feature": self.feature,
            "ts": self.ts,
            "user_message": self.user_message,
        }


def _format_tag(feature: str, message: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    msg = message.strip()
    return f"[canopy {feature} @ {ts}]" + (f" {msg}" if msg else "")


def parse_message(raw: str) -> tuple[str | None, str | None, str]:
    """Extract ``(feature, ts, user_message)`` from a stored stash message.

    Returns ``(None, None, raw)`` if the message isn't a canopy tag.
    """
    m = _TAG.search(raw)
    if not m:
        return None, None, raw
    return m.group(1), m.group(2), m.group(3)


def _parse_entry(repo: str, raw: dict) -> StashEntry:
    feature, ts, user_message = parse_message(raw.get("message", ""))
    return StashEntry(
        repo=repo,
        index=raw.get("index", 0),
        ref=raw.get("ref", f"stash@{{{raw.get('index', 0)}}}"),
        message=raw.get("message", ""),
        feature=feature,
        ts=ts,
        user_message=user_message,
    )


def save_for_feature(
    workspace: Workspace,
    feature: str,
    message: str,
    repos: list[str] | None = None,
) -> dict[str, Any]:
    """Stash dirty changes in feature.repos with a feature-tagged message.

    ``repos`` overrides which repos to stash (default: all repos in the
    feature lane). Repos not in the feature lane are silently skipped
    when expanding from the lane; if ``repos`` is passed explicitly,
    unknown names raise.
    """
    feature_name = resolve_feature(workspace, feature)
    target_repos = _select_repos(workspace, feature_name, repos)
    tagged_message = _format_tag(feature_name, message)

    raw = git_multi.stash_save_all(
        workspace, tagged_message, target_repos, include_untracked=True,
    )
    return {
        "feature": feature_name,
        "message": tagged_message,
        "repos": raw,  # {repo: "stashed" | "clean" | error_str}
    }


def list_grouped(
    workspace: Workspace, feature: str | None = None,
) -> dict[str, Any]:
    """List stashes across repos, grouped by feature tag.

    If ``feature`` is passed, returns only entries matching that feature
    (in ``by_feature[<feature>]``). Otherwise groups all tagged entries
    by feature; unmatched go to ``untagged``.
    """
    target_feature = resolve_feature(workspace, feature) if feature else None
    raw_per_repo = git_multi.stash_list_all(workspace)

    by_feature: dict[str, list[dict]] = {}
    untagged: list[dict] = []

    for repo_name, entries in raw_per_repo.items():
        for raw in entries:
            entry = _parse_entry(repo_name, raw)
            if entry.feature is None:
                if target_feature is not None:
                    continue  # feature filter applied — skip untagged
                untagged.append(entry.to_dict())
                continue
            if target_feature is not None and entry.feature != target_feature:
                continue
            by_feature.setdefault(entry.feature, []).append(entry.to_dict())

    return {"by_feature": by_feature, "untagged": untagged}


def pop_feature(
    workspace: Workspace,
    feature: str,
    repos: list[str] | None = None,
) -> dict[str, Any]:
    """Pop the most recent tagged stash for a feature in each target repo.

    Returns per-repo ``{status: 'popped' | 'no_match' | 'failed', ref, message}``.
    Raises ``BlockerError`` if no matching stash exists in any target repo.
    """
    feature_name = resolve_feature(workspace, feature)
    target_repos = _select_repos(workspace, feature_name, repos)

    raw_per_repo = git_multi.stash_list_all(workspace)
    results: dict[str, dict] = {}
    any_popped = False

    for repo_name in target_repos:
        entries_raw = raw_per_repo.get(repo_name, [])
        # Most recent matching = lowest index where feature matches.
        match: StashEntry | None = None
        for raw in entries_raw:
            parsed = _parse_entry(repo_name, raw)
            if parsed.feature == feature_name:
                if match is None or parsed.index < match.index:
                    match = parsed
        if match is None:
            results[repo_name] = {"status": "no_match"}
            continue
        try:
            state = workspace.get_repo(repo_name)
            git.stash_pop(state.abs_path, match.index)
            results[repo_name] = {
                "status": "popped",
                "ref": match.ref,
                "message": match.user_message,
                "ts": match.ts,
            }
            any_popped = True
        except git.GitError as e:
            results[repo_name] = {
                "status": "failed",
                "ref": match.ref,
                "error": str(e),
            }

    if not any_popped:
        raise BlockerError(
            code="no_tagged_stash",
            what=f"no stash tagged with feature '{feature_name}' in any target repo",
            expected={"feature": feature_name, "target_repos": list(target_repos)},
            actual={"per_repo": results},
            fix_actions=[
                FixAction(action="stash list", args={"feature": feature_name},
                          safe=True, preview="see what tagged stashes exist"),
            ],
        )

    return {"feature": feature_name, "repos": results}


def _select_repos(
    workspace: Workspace,
    feature_name: str,
    requested: list[str] | None,
) -> list[str]:
    """Pick the repo set for a stash op.

    If ``requested`` is given, validate names. Otherwise default to the
    feature lane's ``repos`` (from features.json) or all workspace repos
    when the feature is implicit / has no explicit lane.
    """
    all_names = {r.config.name for r in workspace.repos}

    if requested is not None:
        unknown = [r for r in requested if r not in all_names]
        if unknown:
            raise BlockerError(
                code="unknown_repo",
                what=f"unknown repos: {', '.join(unknown)}",
                expected={"available_repos": sorted(all_names)},
                details={"requested": list(requested)},
            )
        return list(requested)

    from ..features.coordinator import FeatureCoordinator
    features = FeatureCoordinator(workspace)._load_features()
    feature_data = features.get(feature_name) or {}
    declared = feature_data.get("repos") or sorted(all_names)
    return [r for r in declared if r in all_names]
