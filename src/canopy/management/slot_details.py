"""Rich per-slot enrichment for the slots MCP shape (T15).

Composes ``feature_state`` + ``bot_status`` + ``FeatureCoordinator.status``
per slot occupant + canonical. Single function so the CLI / MCP / dashboard
layers stay thin — and so the agent and the human read the same payload.

The shape mirrors the dashboard's grid: one slot block per occupied slot
(``None`` when empty, never ``{}``), and per-repo facts inside each block
limited to the repos the feature actually touches (partial-scope features
stay partial here).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..features.coordinator import FeatureCoordinator
from ..git import repo as git
from ..workspace.workspace import Workspace
from . import bot_status
from . import feature_state as fs
from ..actions import slots as slots_mod
from ..actions.aliases import repos_for_feature


def rich_slots(workspace: Workspace) -> dict[str, Any]:
    """Return the full dashboard payload for every slot + canonical.

    Empty slots are explicit ``None`` (the dashboard renders these as
    placeholders). When ``slots.json`` is absent we still return the
    skeleton — ``slot_count`` from canopy.toml, every slot ``None``,
    ``canonical`` ``None`` — so the consumer never has to special-case
    "no state yet."
    """
    state = slots_mod.read_state(workspace) or slots_mod.SlotState(
        slot_count=workspace.config.slots,
    )
    out: dict[str, Any] = {
        "version": 1,
        "slot_count": state.slot_count,
        "canonical": _enrich_canonical(workspace, state),
        "slots": {},
        "last_touched": dict(state.last_touched),
    }
    for i in range(1, state.slot_count + 1):
        sid = f"worktree-{i}"
        entry = state.slots.get(sid)
        out["slots"][sid] = (
            _enrich_slot(workspace, sid, entry) if entry else None
        )
    return out


def _enrich_canonical(
    workspace: Workspace, state: slots_mod.SlotState,
) -> dict[str, Any] | None:
    if state.canonical is None:
        return None
    return {
        "slot_id": "canonical",
        "feature": state.canonical.feature,
        "activated_at": state.canonical.activated_at,
        **_enrich_feature_payload(workspace, state.canonical.feature),
    }


def _enrich_slot(
    workspace: Workspace, slot_id: str, entry: slots_mod.SlotEntry,
) -> dict[str, Any]:
    return {
        "slot_id": slot_id,
        "feature": entry.feature,
        "occupied_at": entry.occupied_at,
        **_enrich_feature_payload(workspace, entry.feature),
    }


def _enrich_feature_payload(
    workspace: Workspace, feature: str,
) -> dict[str, Any]:
    """Per-feature payload shared by canonical + slot blocks.

    Delegates to ``feature_state`` for the heavy lifting (dirty / diverge
    / PR / CI) and to ``bot_status`` for the unresolved-bot rollup. We
    only translate field names + fill the few extras the dashboard wants
    (short sha, commit subject + date, default branch). No new git or
    GitHub calls beyond what those two paths already make.
    """
    repo_branches = repos_for_feature(workspace, feature)
    errors: list[dict] = []
    try:
        st = fs.feature_state(workspace, feature)
    except Exception as e:
        st = {"state": "unknown", "summary": {"repos": {}, "prs": {},
                                                 "ci_per_repo": {}}}
        errors.append({"source": "feature_state", "what": str(e)})
    summary = st.get("summary") or {}
    facts_by_repo: dict[str, dict] = summary.get("repos") or {}
    prs_by_repo: dict[str, dict] = summary.get("prs") or {}
    ci_by_repo: dict[str, dict] = summary.get("ci_per_repo") or {}

    # Per-repo path resolution mirrors feature_state's: worktree path for
    # worktree-backed features, main repo otherwise. We need the path so
    # we can run a few cheap extra git reads (short sha, subject, default
    # branch) without re-doing the worktree resolution dance.
    repo_paths, _has_wt = fs.resolve_repo_paths(workspace, feature, repo_branches)

    try:
        bot_roll = bot_status.bot_comments_status(workspace, feature)
    except Exception as e:
        bot_roll = {"repos": {}}
        errors.append({"source": "bot_status", "what": str(e)})
    bot_repos = bot_roll.get("repos") or {}

    try:
        lane = FeatureCoordinator(workspace).status(feature)
        linear_issue = getattr(lane, "linear_issue", "") or None
        linear_url = getattr(lane, "linear_url", "") or None
    except Exception as e:
        linear_issue = None
        linear_url = None
        errors.append({"source": "coordinator.status", "what": str(e)})

    repos_out: dict[str, dict] = {}
    for repo_name, expected_branch in repo_branches.items():
        repo_facts = facts_by_repo.get(repo_name) or {}
        repo_path = repo_paths.get(repo_name)
        pr = prs_by_repo.get(repo_name)
        pr_block = _pr_block(pr, ci_by_repo.get(repo_name))

        repos_out[repo_name] = {
            "branch": repo_facts.get("branch", expected_branch),
            "path": str(repo_path) if repo_path else "",
            "dirty": bool(repo_facts.get("is_dirty", False)),
            "dirty_file_count": int(repo_facts.get("dirty_count", 0)),
            "ahead": int(repo_facts.get("ahead", 0)),
            "behind": int(repo_facts.get("behind", 0)),
            "default_branch": _default_branch(repo_path),
            "last_commit": _last_commit(repo_path, repo_facts.get("head_sha", "")),
            "pr": pr_block,
            "bot_unresolved": int((bot_repos.get(repo_name) or {}).get("unresolved", 0)),
            # Feature-tagged stash count: skipped in T15 (would need an
            # extra `git stash list` per repo). The shape includes the
            # field so the dashboard never KeyErrors; populated by a later
            # plan if it earns its keep.
            "feature_tagged_stash_count": 0,
        }

    return {
        "repos": repos_out,
        "feature_state": st.get("state", "unknown"),
        "linear_issue": linear_issue,
        "linear_url": linear_url,
        # last_visit lands with the feature-resume plan; reserved here so
        # the shape is stable when that plan ships.
        "last_visit": None,
        # Empty list when all enrichment sources succeeded. Populated with
        # ``{source, what}`` dicts when a source raised — surfaces real
        # bugs that previously vanished into bare ``except Exception``.
        "errors": errors,
    }


def _pr_block(pr: dict | None, ci_status: dict | None) -> dict | None:
    if not pr:
        return None
    return {
        "number": pr.get("number"),
        "url": pr.get("url", ""),
        "state": pr.get("state", ""),
        "review_decision": pr.get("review_decision", ""),
        "ci_status": ci_status or {"status": "no_checks"},
    }


def _default_branch(repo_path: Path | None) -> str:
    if repo_path is None:
        return "main"
    try:
        return git.default_branch(repo_path) or "main"
    except Exception:
        return "main"


def _last_commit(repo_path: Path | None, head_sha: str) -> dict | None:
    """Last-commit detail block. Returns None when the branch has no commits.

    Re-uses the already-resolved ``head_sha`` from feature_state to avoid a
    second rev-parse. Subject + ISO date are one cheap git log each — same
    cost feature_state would pay anyway if it asked.
    """
    if not head_sha or repo_path is None:
        return None
    short = head_sha[:8]
    subject = ""
    try:
        lines = git.log_oneline(repo_path, head_sha, max_count=1)
        if lines:
            # `<short_sha> <subject>` — drop the hash prefix.
            parts = lines[0].split(" ", 1)
            subject = parts[1] if len(parts) > 1 else ""
    except Exception:
        pass
    try:
        at = git.commit_iso_date(repo_path, head_sha)
    except Exception:
        at = ""
    return {"sha": head_sha, "short": short, "subject": subject, "at": at}
