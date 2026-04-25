"""Drift detection: compare recorded heads vs feature lane expectations.

Reads ground truth from ``.canopy/state/heads.json`` (written by the
post-checkout hook) and compares it to ``FeatureLane.repos`` from
``.canopy/features.json``. Returns a structured report; ``assert_aligned``
raises a ``BlockerError`` so any action that has alignment as a precondition
can use the same primitive.

v1 assumes ``expected_branch == feature_name`` per repo. Per-repo branch
overrides (e.g., ``doc-3010-UI-fixes`` in api vs ``DOC-3010-UI-fixes-2``
in ui) will be added when the feature lane schema gains per-repo branch
mapping. For now, exact match against feature name.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..git.hooks import read_heads_state
from ..workspace.workspace import Workspace
from .errors import BlockerError, FixAction


@dataclass
class RepoAlignment:
    repo: str
    expected: str
    actual: str | None
    aligned: bool
    state_recorded_at: str | None = None
    state_age_seconds: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "expected": self.expected,
            "actual": self.actual,
            "aligned": self.aligned,
            "state_recorded_at": self.state_recorded_at,
            "state_age_seconds": self.state_age_seconds,
        }


@dataclass
class FeatureDrift:
    feature: str
    aligned: bool
    repos: list[RepoAlignment] = field(default_factory=list)
    drifted_repos: list[str] = field(default_factory=list)
    untracked_repos: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "aligned": self.aligned,
            "repos": [r.to_dict() for r in self.repos],
            "drifted_repos": list(self.drifted_repos),
            "untracked_repos": list(self.untracked_repos),
        }


@dataclass
class DriftReport:
    workspace_root: str
    overall_aligned: bool
    features: list[FeatureDrift] = field(default_factory=list)
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "workspace_root": self.workspace_root,
            "overall_aligned": self.overall_aligned,
            "features": [f.to_dict() for f in self.features],
        }
        if self.note:
            out["note"] = self.note
        return out


def detect_drift(workspace: Workspace, feature_name: str | None = None) -> DriftReport:
    """Compute drift across one or all active features.

    Args:
        workspace: loaded ``Workspace``.
        feature_name: if set, scope to one feature (resolved through coordinator
            alias logic). If None, report all active features.

    The expected branch for each repo is the feature name. Repos in
    ``feature.repos`` but missing from heads.json are reported as
    ``untracked_repos`` — usually because the post-checkout hook hasn't
    fired in that repo since install (e.g., a fresh workspace where ui
    hasn't been switched yet).
    """
    from ..features.coordinator import FeatureCoordinator

    coordinator = FeatureCoordinator(workspace)
    heads = read_heads_state(workspace.config.root)

    # list_active() returns only active lanes from features.json + implicit
    # branches present across multiple repos.
    active_lanes = coordinator.list_active()

    if feature_name is not None:
        resolved = coordinator._resolve_name(feature_name)
        active_lanes = [l for l in active_lanes if l.name == resolved]
        if not active_lanes:
            return DriftReport(
                workspace_root=str(workspace.config.root),
                overall_aligned=False,
                note=f"feature '{feature_name}' is not an active feature lane",
            )

    if not active_lanes:
        return DriftReport(
            workspace_root=str(workspace.config.root),
            overall_aligned=True,
            note="no active features",
        )

    feature_drifts: list[FeatureDrift] = []
    overall = True
    for lane in active_lanes:
        fd = _compute_feature_drift(lane, heads)
        feature_drifts.append(fd)
        if not fd.aligned:
            overall = False

    return DriftReport(
        workspace_root=str(workspace.config.root),
        overall_aligned=overall,
        features=feature_drifts,
    )


def assert_aligned(workspace: Workspace, feature_name: str) -> None:
    """Raise ``BlockerError(code="drift_detected")`` if the feature has drift.

    Used by mutating actions (commit, push, ship) as a precondition. The
    error's ``fix_actions`` always includes a ``realign`` suggestion for
    the feature.
    """
    report = detect_drift(workspace, feature_name=feature_name)
    if report.note and "not an active" in report.note:
        raise BlockerError(
            code="unknown_feature",
            what=report.note,
            details={"feature": feature_name},
        )
    drifted = [f for f in report.features if not f.aligned]
    if not drifted:
        return
    fd = drifted[0]
    expected = {r.repo: r.expected for r in fd.repos}
    actual = {r.repo: r.actual for r in fd.repos}
    raise BlockerError(
        code="drift_detected",
        what=f"branches don't match feature lane '{fd.feature}'",
        expected={"feature": fd.feature, "branches": expected},
        actual={"branches": actual},
        fix_actions=[
            FixAction(
                action="realign",
                args={"feature": fd.feature},
                safe=_realign_is_safe(fd),
                preview=_realign_preview(fd),
            ),
        ],
        details={
            "drifted_repos": fd.drifted_repos,
            "untracked_repos": fd.untracked_repos,
        },
    )


def _compute_feature_drift(lane, heads: dict) -> FeatureDrift:
    repos: list[RepoAlignment] = []
    drifted: list[str] = []
    untracked: list[str] = []

    for repo_name in lane.repos:
        # Use lane.branch_for to honor per-repo branch overrides
        # (handles cases like doc-3010-UI-fixes vs DOC-3010-UI-fixes-2).
        expected = lane.branch_for(repo_name)
        head = heads.get(repo_name)
        if head is None:
            ra = RepoAlignment(
                repo=repo_name, expected=expected,
                actual=None, aligned=False,
            )
            untracked.append(repo_name)
        else:
            actual = head.get("branch")
            aligned = actual == expected
            ts = head.get("ts")
            age = _age_seconds(ts) if ts else None
            ra = RepoAlignment(
                repo=repo_name, expected=expected,
                actual=actual, aligned=aligned,
                state_recorded_at=ts, state_age_seconds=age,
            )
            if not aligned:
                drifted.append(repo_name)
        repos.append(ra)

    return FeatureDrift(
        feature=lane.name,
        aligned=not drifted and not untracked,
        repos=repos,
        drifted_repos=drifted,
        untracked_repos=untracked,
    )


def _age_seconds(iso_ts: str) -> float | None:
    try:
        # Hook writes ISO with trailing 'Z'.
        ts = datetime.strptime(iso_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - ts).total_seconds()


def _realign_is_safe(fd: FeatureDrift) -> bool:
    """Untracked repos are safe to realign (we don't know their state, but
    realign will check for dirty trees itself before mutating). Drifted
    repos are also safe — realign refuses to act on dirty trees."""
    return True


def _realign_preview(fd: FeatureDrift) -> str:
    parts = []
    for r in fd.repos:
        if r.aligned:
            continue
        if r.actual is None:
            parts.append(f"{r.repo} (no recorded state; will checkout {r.expected})")
        else:
            parts.append(f"{r.repo}: {r.actual} → {r.expected}")
    return "; ".join(parts)
