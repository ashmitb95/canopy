"""Tests for canopy.actions.doctor — diagnostic + repair primitive.

One section per category; each section pairs a "detects" test with a
"repairs" test where applicable. Uses the existing workspace_with_feature
fixture and targeted mutations to build known-bad states.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from canopy.actions.doctor import (
    Issue,
    RepairResult,
    _CHECKS,
    _REPAIRS,
    check_active_feature_orphan,
    check_active_feature_path_missing,
    check_branches_missing,
    check_cli_stale,
    check_features_unknown_repo,
    check_heads_stale,
    check_hook_chained_unsafe,
    check_hook_missing,
    check_mcp_missing_in_workspace,
    check_mcp_stale,
    check_preflight_stale,
    check_skill_missing,
    check_skill_stale,
    check_vsix_duplicates,
    check_worktree_missing,
    check_worktree_orphan,
    doctor,
    repair_active_feature_orphan,
    repair_active_feature_path_missing,
    repair_heads_stale,
    repair_hook_chained_unsafe,
    repair_hook_missing,
    repair_preflight_stale,
    repair_worktree_missing,
    repair_worktree_orphan,
)
from canopy.git import hooks as canopy_hooks
from canopy.git import repo as git
from canopy.workspace.config import RepoConfig, WorkspaceConfig
from canopy.workspace.workspace import Workspace


# ── helpers ──────────────────────────────────────────────────────────────


def _make_workspace(workspace_dir, repos=("repo-a", "repo-b")) -> Workspace:
    config = WorkspaceConfig(
        name="test",
        repos=[
            RepoConfig(name=name, path=f"./{name}", role="x", lang="x")
            for name in repos
        ],
        root=workspace_dir,
    )
    return Workspace(config)


def _write_features(workspace_dir, features: dict) -> Path:
    canopy = workspace_dir / ".canopy"
    canopy.mkdir(exist_ok=True)
    path = canopy / "features.json"
    path.write_text(json.dumps(features))
    return path


def _write_active(workspace_dir, **fields) -> Path:
    state_dir = workspace_dir / ".canopy" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "active_feature.json"
    path.write_text(json.dumps(fields))
    return path


def _write_heads(workspace_dir, **per_repo) -> Path:
    state_dir = workspace_dir / ".canopy" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state = {}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for repo_kw, entry in per_repo.items():
        repo = repo_kw.replace("_", "-")
        state[repo] = {
            "branch": entry["branch"],
            "sha": entry.get("sha", "0" * 40),
            "prev_sha": entry.get("prev_sha", entry.get("sha", "0" * 40)),
            "ts": entry.get("ts", now),
        }
    path = state_dir / "heads.json"
    path.write_text(json.dumps(state))
    return path


# ── heads_stale ──────────────────────────────────────────────────────────


def test_heads_stale_detects_branch_mismatch(workspace_with_feature):
    """heads.json says auth-flow but live HEAD is on auth-flow → aligned (no issue)."""
    _write_heads(workspace_with_feature,
                 repo_a={"branch": "auth-flow", "sha": "deadbeef"},
                 repo_b={"branch": "auth-flow", "sha": "deadbeef"})
    ws = _make_workspace(workspace_with_feature)
    issues = check_heads_stale(ws)
    # both shas are wrong → 2 issues
    assert len(issues) == 2
    assert all(i.code == "heads_stale" for i in issues)
    assert {i.repo for i in issues} == {"repo-a", "repo-b"}


def test_heads_stale_aligned_returns_empty(workspace_with_feature):
    """Real shas in heads.json → no issue."""
    real_a = git.head_sha(workspace_with_feature / "repo-a")
    real_b = git.head_sha(workspace_with_feature / "repo-b")
    _write_heads(workspace_with_feature,
                 repo_a={"branch": "auth-flow", "sha": real_a},
                 repo_b={"branch": "auth-flow", "sha": real_b})
    ws = _make_workspace(workspace_with_feature)
    assert check_heads_stale(ws) == []


def test_heads_stale_no_state_file_returns_empty(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    assert check_heads_stale(ws) == []


def test_repair_heads_stale_rewrites_from_live(workspace_with_feature):
    _write_heads(workspace_with_feature,
                 repo_a={"branch": "auth-flow", "sha": "0" * 40},
                 repo_b={"branch": "auth-flow", "sha": "0" * 40})
    ws = _make_workspace(workspace_with_feature)
    issues = check_heads_stale(ws)
    assert issues
    result = repair_heads_stale(ws, issues[0])
    assert result.success
    # re-check should drop the issue for that repo
    remaining = check_heads_stale(ws)
    assert {i.repo for i in remaining} == {"repo-b"}


# ── active_feature_orphan / path_missing ────────────────────────────────


def test_active_feature_orphan_detects_unknown_feature(workspace_with_feature):
    _write_features(workspace_with_feature, {})  # empty features.json
    _write_active(workspace_with_feature, feature="ghost",
                  per_repo_paths={})
    ws = _make_workspace(workspace_with_feature)
    issues = check_active_feature_orphan(ws)
    assert len(issues) == 1
    assert issues[0].code == "active_feature_orphan"
    assert issues[0].feature == "ghost"
    assert issues[0].auto_fixable


def test_active_feature_orphan_skipped_when_feature_present(workspace_with_feature):
    _write_features(workspace_with_feature, {"auth-flow": {
        "repos": ["repo-a"], "status": "active",
    }})
    _write_active(workspace_with_feature, feature="auth-flow",
                  per_repo_paths={})
    ws = _make_workspace(workspace_with_feature)
    assert check_active_feature_orphan(ws) == []


def test_repair_active_feature_orphan_clears_file(workspace_with_feature):
    _write_features(workspace_with_feature, {})
    path = _write_active(workspace_with_feature, feature="ghost",
                         per_repo_paths={})
    ws = _make_workspace(workspace_with_feature)
    issues = check_active_feature_orphan(ws)
    result = repair_active_feature_orphan(ws, issues[0])
    assert result.success
    assert not path.exists()


def test_active_feature_path_missing_detects(workspace_with_feature):
    _write_features(workspace_with_feature, {"auth-flow": {
        "repos": ["repo-a"], "status": "active",
    }})
    _write_active(workspace_with_feature, feature="auth-flow",
                  per_repo_paths={"repo-a": "/nonexistent/path"})
    ws = _make_workspace(workspace_with_feature)
    issues = check_active_feature_path_missing(ws)
    assert len(issues) == 1
    assert issues[0].repo == "repo-a"


def test_repair_active_feature_path_missing_re_resolves(workspace_with_feature):
    _write_features(workspace_with_feature, {"auth-flow": {
        "repos": ["repo-a"], "status": "active",
    }})
    _write_active(workspace_with_feature, feature="auth-flow",
                  per_repo_paths={"repo-a": "/nonexistent/path"})
    ws = _make_workspace(workspace_with_feature)
    issues = check_active_feature_path_missing(ws)
    result = repair_active_feature_path_missing(ws, issues[0])
    assert result.success
    # After repair, path should be the real repo-a path
    af = json.loads((workspace_with_feature / ".canopy" / "state" /
                     "active_feature.json").read_text())
    assert af["per_repo_paths"]["repo-a"] == str(workspace_with_feature / "repo-a")


# ── worktree_orphan / worktree_missing ──────────────────────────────────


def test_worktree_orphan_detects_unreferenced_dir(workspace_with_feature):
    _write_features(workspace_with_feature, {})  # no features
    orphan = workspace_with_feature / ".canopy" / "worktrees" / "ghost" / "repo-a"
    orphan.mkdir(parents=True)
    ws = _make_workspace(workspace_with_feature)
    issues = check_worktree_orphan(ws)
    assert len(issues) == 1
    assert issues[0].feature == "ghost"
    assert issues[0].repo == "repo-a"


def test_repair_worktree_orphan_removes(workspace_with_feature):
    _write_features(workspace_with_feature, {})
    orphan = workspace_with_feature / ".canopy" / "worktrees" / "ghost" / "repo-a"
    orphan.mkdir(parents=True)
    ws = _make_workspace(workspace_with_feature)
    issues = check_worktree_orphan(ws)
    result = repair_worktree_orphan(ws, issues[0])
    assert result.success
    assert not orphan.exists()


def test_worktree_missing_detects(workspace_with_feature):
    _write_features(workspace_with_feature, {"auth-flow": {
        "repos": ["repo-a"], "status": "active",
        "worktree_paths": {"repo-a": "/nonexistent/wt"},
    }})
    ws = _make_workspace(workspace_with_feature)
    issues = check_worktree_missing(ws)
    assert len(issues) == 1
    assert issues[0].code == "worktree_missing"


def test_repair_worktree_missing_clears_entry(workspace_with_feature):
    _write_features(workspace_with_feature, {"auth-flow": {
        "repos": ["repo-a"], "status": "active",
        "worktree_paths": {"repo-a": "/nonexistent/wt"},
    }})
    ws = _make_workspace(workspace_with_feature)
    issues = check_worktree_missing(ws)
    result = repair_worktree_missing(ws, issues[0])
    assert result.success
    data = json.loads((workspace_with_feature / ".canopy" / "features.json").read_text())
    assert "worktree_paths" not in data["auth-flow"]


# ── hook_missing / hook_chained_unsafe ──────────────────────────────────


def test_hook_missing_when_no_hook(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    issues = check_hook_missing(ws)
    assert {i.repo for i in issues} == {"repo-a", "repo-b"}


def test_hook_missing_skipped_when_installed(workspace_with_feature):
    canopy_hooks.install_hook(workspace_with_feature / "repo-a", "repo-a",
                              workspace_with_feature)
    canopy_hooks.install_hook(workspace_with_feature / "repo-b", "repo-b",
                              workspace_with_feature)
    ws = _make_workspace(workspace_with_feature)
    assert check_hook_missing(ws) == []


def test_repair_hook_missing_installs(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    issues = check_hook_missing(ws)
    result = repair_hook_missing(ws, issues[0])
    assert result.success
    # re-check should drop that repo
    remaining = check_hook_missing(ws)
    assert issues[0].repo not in {i.repo for i in remaining}


def test_hook_chained_unsafe_when_chained_not_executable(workspace_with_feature):
    """Install hook with a chained user hook, then strip exec bit."""
    repo = workspace_with_feature / "repo-a"
    hooks_dir = canopy_hooks.resolve_hooks_dir(repo)
    hooks_dir.mkdir(parents=True, exist_ok=True)
    user_hook = hooks_dir / "post-checkout"
    user_hook.write_text("#!/bin/sh\necho user-hook\n")
    user_hook.chmod(0o755)
    canopy_hooks.install_hook(repo, "repo-a", workspace_with_feature)
    chained = hooks_dir / "post-checkout.canopy-chained"
    assert chained.exists()
    # strip exec bit
    chained.chmod(0o644)
    ws = _make_workspace(workspace_with_feature)
    issues = check_hook_chained_unsafe(ws)
    assert any(i.repo == "repo-a" for i in issues)
    # repair
    result = repair_hook_chained_unsafe(ws, issues[0])
    assert result.success
    assert os.access(chained, os.X_OK)


# ── preflight_stale ─────────────────────────────────────────────────────


def test_preflight_stale_when_head_moved(workspace_with_feature):
    _write_features(workspace_with_feature, {"auth-flow": {
        "repos": ["repo-a", "repo-b"], "status": "active",
    }})
    state_path = workspace_with_feature / ".canopy" / "state" / "preflight.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({
        "auth-flow": {
            "passed": True,
            "ran_at": "2026-01-01T00:00:00Z",
            "head_sha_per_repo": {"repo-a": "deadbeef", "repo-b": "deadbeef"},
            "summary": "",
        }
    }))
    ws = _make_workspace(workspace_with_feature)
    issues = check_preflight_stale(ws)
    assert len(issues) == 1
    assert issues[0].feature == "auth-flow"


def test_repair_preflight_stale_drops_entry(workspace_with_feature):
    state_path = workspace_with_feature / ".canopy" / "state" / "preflight.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({
        "auth-flow": {"passed": True, "head_sha_per_repo": {"repo-a": "deadbeef"}},
        "other": {"passed": True, "head_sha_per_repo": {}},
    }))
    ws = _make_workspace(workspace_with_feature)
    issue = Issue(code="preflight_stale", severity="info", what="",
                   feature="auth-flow", auto_fixable=True)
    result = repair_preflight_stale(ws, issue)
    assert result.success
    state = json.loads(state_path.read_text())
    assert "auth-flow" not in state
    assert "other" in state


# ── features_unknown_repo / branches_missing ────────────────────────────


def test_features_unknown_repo(workspace_with_feature):
    _write_features(workspace_with_feature, {"auth-flow": {
        "repos": ["repo-a", "repo-c-removed"], "status": "active",
    }})
    ws = _make_workspace(workspace_with_feature)
    issues = check_features_unknown_repo(ws)
    assert len(issues) == 1
    assert issues[0].repo == "repo-c-removed"
    assert not issues[0].auto_fixable


def test_branches_missing(workspace_with_feature):
    _write_features(workspace_with_feature, {"ghost-feature": {
        "repos": ["repo-a"], "status": "active",
    }})
    ws = _make_workspace(workspace_with_feature)
    issues = check_branches_missing(ws)
    assert len(issues) == 1
    assert issues[0].feature == "ghost-feature"


def test_branches_missing_honors_per_repo_branch_map(workspace_with_feature):
    _write_features(workspace_with_feature, {"auth-flow": {
        "repos": ["repo-a"], "status": "active",
        "branches": {"repo-a": "DOES-NOT-EXIST"},
    }})
    ws = _make_workspace(workspace_with_feature)
    issues = check_branches_missing(ws)
    assert len(issues) == 1
    assert issues[0].expected == "DOES-NOT-EXIST"


def test_branches_missing_aligned(workspace_with_feature):
    _write_features(workspace_with_feature, {"auth-flow": {
        "repos": ["repo-a"], "status": "active",
    }})
    ws = _make_workspace(workspace_with_feature)
    assert check_branches_missing(ws) == []


# ── install-staleness checks ────────────────────────────────────────────


def test_check_cli_stale_when_binary_missing(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    with patch("canopy.actions.doctor.shutil.which", return_value=None):
        issues = check_cli_stale(ws)
    assert len(issues) == 1
    assert issues[0].code == "cli_stale"


def test_check_cli_stale_when_older(workspace_with_feature, tmp_path):
    ws = _make_workspace(workspace_with_feature)
    fake = tmp_path / "canopy"
    fake.write_text("#!/bin/sh\necho 'canopy 0.0.1'\n")
    fake.chmod(0o755)
    with patch("canopy.actions.doctor.shutil.which", return_value=str(fake)):
        issues = check_cli_stale(ws)
    assert len(issues) == 1
    assert issues[0].actual == "0.0.1"


def test_check_cli_stale_when_current(workspace_with_feature, tmp_path):
    from canopy import __version__
    ws = _make_workspace(workspace_with_feature)
    fake = tmp_path / "canopy"
    fake.write_text(f"#!/bin/sh\necho 'canopy {__version__}'\n")
    fake.chmod(0o755)
    with patch("canopy.actions.doctor.shutil.which", return_value=str(fake)):
        assert check_cli_stale(ws) == []


def test_check_mcp_stale_when_missing(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    with patch("canopy.actions.doctor.shutil.which", return_value=None):
        issues = check_mcp_stale(ws)
    assert len(issues) == 1
    assert issues[0].severity == "error"


def test_check_mcp_missing_in_workspace_no_file(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    issues = check_mcp_missing_in_workspace(ws)
    assert len(issues) == 1
    assert issues[0].auto_fixable


def test_check_mcp_missing_in_workspace_wrong_root(workspace_with_feature):
    (workspace_with_feature / ".mcp.json").write_text(json.dumps({
        "mcpServers": {"canopy": {
            "command": "canopy-mcp",
            "env": {"CANOPY_ROOT": "/different/root"},
        }}
    }))
    ws = _make_workspace(workspace_with_feature)
    issues = check_mcp_missing_in_workspace(ws)
    assert len(issues) == 1
    assert "CANOPY_ROOT" in issues[0].what


def test_check_mcp_missing_in_workspace_aligned(workspace_with_feature):
    (workspace_with_feature / ".mcp.json").write_text(json.dumps({
        "mcpServers": {"canopy": {
            "command": "canopy-mcp",
            "env": {"CANOPY_ROOT": str(workspace_with_feature.resolve())},
        }}
    }))
    ws = _make_workspace(workspace_with_feature)
    assert check_mcp_missing_in_workspace(ws) == []


def test_check_skill_missing(workspace_with_feature, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    ws = _make_workspace(workspace_with_feature)
    issues = check_skill_missing(ws)
    assert len(issues) == 1


def test_check_skill_stale_byte_mismatch(workspace_with_feature, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / ".claude" / "skills" / "using-canopy" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("name: using-canopy\nold content drifted\n")
    ws = _make_workspace(workspace_with_feature)
    issues = check_skill_stale(ws)
    assert len(issues) == 1
    assert issues[0].auto_fixable


def test_check_vsix_duplicates_detects(workspace_with_feature, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    ext = tmp_path / ".vscode" / "extensions"
    ext.mkdir(parents=True)
    (ext / "singularityinc.canopy-0.1.0").mkdir()
    (ext / "singularityinc.canopy-0.0.9").mkdir()
    ws = _make_workspace(workspace_with_feature)
    issues = check_vsix_duplicates(ws)
    assert len(issues) == 1
    assert "2" in str(issues[0].actual)


def test_check_vsix_duplicates_skipped_when_single(workspace_with_feature, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    ext = tmp_path / ".vscode" / "extensions"
    ext.mkdir(parents=True)
    (ext / "singularityinc.canopy-0.1.0").mkdir()
    ws = _make_workspace(workspace_with_feature)
    assert check_vsix_duplicates(ws) == []


# ── orchestrator ────────────────────────────────────────────────────────


def test_doctor_clean_workspace_returns_no_issues(workspace_with_feature, tmp_path,
                                                   monkeypatch):
    """Sanity: a freshly-set-up workspace with hooks installed, .mcp.json
    written, and skill present should report only install-staleness issues
    (which depend on test environment) — but state-integrity issues should
    all be absent.
    """
    canopy_hooks.install_hook(workspace_with_feature / "repo-a", "repo-a",
                              workspace_with_feature)
    canopy_hooks.install_hook(workspace_with_feature / "repo-b", "repo-b",
                              workspace_with_feature)
    ws = _make_workspace(workspace_with_feature)
    report = doctor(ws)
    state_codes = {
        "heads_stale", "active_feature_orphan", "active_feature_path_missing",
        "worktree_orphan", "worktree_missing", "hook_missing",
        "hook_chained_unsafe", "preflight_stale", "features_unknown_repo",
        "branches_missing",
    }
    state_issues = [i for i in report["issues"] if i["code"] in state_codes]
    assert state_issues == []


def test_doctor_summarizes_severities(workspace_with_feature):
    """Mix of issues across severities."""
    _write_features(workspace_with_feature, {"ghost": {
        "repos": ["repo-a", "unknown-repo"], "status": "active",
    }})
    ws = _make_workspace(workspace_with_feature)
    report = doctor(ws)
    assert report["summary"]["errors"] >= 1   # features_unknown_repo
    assert "issues" in report
    assert isinstance(report["issues"], list)


def test_doctor_fix_repairs_auto_fixable(workspace_with_feature):
    """Run --fix; auto-fixable issues should be resolved on second pass."""
    canopy_hooks.install_hook(workspace_with_feature / "repo-a", "repo-a",
                              workspace_with_feature)
    canopy_hooks.install_hook(workspace_with_feature / "repo-b", "repo-b",
                              workspace_with_feature)
    _write_heads(workspace_with_feature,
                 repo_a={"branch": "wrong", "sha": "0" * 40},
                 repo_b={"branch": "wrong", "sha": "0" * 40})
    ws = _make_workspace(workspace_with_feature)
    first = doctor(ws)
    stale = [i for i in first["issues"] if i["code"] == "heads_stale"]
    assert len(stale) == 2
    second = doctor(ws, fix=True)
    fixed_codes = {f["code"] for f in second["fixed"]}
    assert "heads_stale" in fixed_codes
    third = doctor(ws)
    assert [i for i in third["issues"] if i["code"] == "heads_stale"] == []


def test_doctor_fix_categories_filter(workspace_with_feature):
    """`fix_categories=["heads"]` only repairs heads-category issues."""
    canopy_hooks.install_hook(workspace_with_feature / "repo-a", "repo-a",
                              workspace_with_feature)
    canopy_hooks.install_hook(workspace_with_feature / "repo-b", "repo-b",
                              workspace_with_feature)
    _write_heads(workspace_with_feature,
                 repo_a={"branch": "wrong", "sha": "0" * 40})
    _write_features(workspace_with_feature, {})
    _write_active(workspace_with_feature, feature="ghost", per_repo_paths={})
    ws = _make_workspace(workspace_with_feature)
    report = doctor(ws, fix_categories=["heads"])
    fixed_codes = {f["code"] for f in report["fixed"]}
    assert "heads_stale" in fixed_codes
    # active_feature_orphan should NOT have been repaired
    assert "active_feature_orphan" not in fixed_codes


def test_doctor_vsix_requires_clean_vsix_flag(workspace_with_feature, tmp_path,
                                                monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    ext = tmp_path / ".vscode" / "extensions"
    ext.mkdir(parents=True)
    (ext / "singularityinc.canopy-0.1.0").mkdir()
    (ext / "singularityinc.canopy-0.0.9").mkdir()
    ws = _make_workspace(workspace_with_feature)
    # fix=True alone shouldn't clean vsix
    report = doctor(ws, fix=True)
    skipped_codes = {s["code"] for s in report["skipped"]}
    assert "vsix_duplicates" in skipped_codes
    # fix=True + clean_vsix=True does
    report2 = doctor(ws, fix=True, clean_vsix=True)
    fixed_codes = {f["code"] for f in report2["fixed"]}
    assert "vsix_duplicates" in fixed_codes


def test_doctor_check_runs_all_categories(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    report = doctor(ws)
    # No exceptions, response shape stable
    assert set(report.keys()) >= {
        "workspace", "workspace_root", "checked_at",
        "issues", "summary", "fixed", "skipped",
    }
    assert all(k in report["summary"] for k in ("errors", "warnings", "info"))


def test_doctor_check_protocol_registry_complete():
    """Every check in _CHECKS has a category in either STATE or INSTALL."""
    from canopy.actions.doctor import (
        ALL_CATEGORIES, INSTALL_CATEGORIES, STATE_CATEGORIES,
    )
    for code, (category, fn) in _CHECKS.items():
        assert category in ALL_CATEGORIES, f"{code} has unknown category {category}"
        assert callable(fn)
    assert STATE_CATEGORIES.isdisjoint(INSTALL_CATEGORIES)


# ── End-to-end recovery (T8) ─────────────────────────────────────────────


def test_e2e_corrupt_then_repair_then_clean(workspace_with_feature):
    """Compose multiple corruptions, doctor reports them, --fix repairs,
    re-check is clean for the auto-fixable subset.
    """
    canopy_hooks.install_hook(workspace_with_feature / "repo-a", "repo-a",
                              workspace_with_feature)
    canopy_hooks.install_hook(workspace_with_feature / "repo-b", "repo-b",
                              workspace_with_feature)

    # Corrupt 1: heads.json out of sync for repo-a
    _write_heads(workspace_with_feature,
                 repo_a={"branch": "wrong-branch", "sha": "0" * 40})

    # Corrupt 2: orphan worktree dir
    orphan = workspace_with_feature / ".canopy" / "worktrees" / "ghost" / "repo-a"
    orphan.mkdir(parents=True)

    # Corrupt 3: active_feature points at unknown feature
    _write_features(workspace_with_feature, {})
    _write_active(workspace_with_feature, feature="ghost",
                  per_repo_paths={})

    # Corrupt 4: stale preflight
    state_path = workspace_with_feature / ".canopy" / "state" / "preflight.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({
        "auth-flow": {"passed": True,
                       "head_sha_per_repo": {"repo-a": "deadbeef"},
                       "summary": ""},
    }))

    ws = _make_workspace(workspace_with_feature)
    initial = doctor(ws)
    initial_codes = {i["code"] for i in initial["issues"]}
    # Each corruption produces its expected code
    assert "heads_stale" in initial_codes
    assert "worktree_orphan" in initial_codes
    assert "active_feature_orphan" in initial_codes
    assert "preflight_stale" in initial_codes

    # Repair
    repaired = doctor(ws, fix=True)
    fixed_codes = {f["code"] for f in repaired["fixed"] if f["success"]}
    assert "heads_stale" in fixed_codes
    assert "worktree_orphan" in fixed_codes
    assert "active_feature_orphan" in fixed_codes
    assert "preflight_stale" in fixed_codes

    # Re-check
    final = doctor(ws)
    final_codes = {i["code"] for i in final["issues"]}
    # All four state-integrity issues should be cleared
    for code in ("heads_stale", "worktree_orphan",
                  "active_feature_orphan", "preflight_stale"):
        assert code not in final_codes, f"{code} still present after repair"
    # Filesystem effects
    assert not orphan.exists()
    assert not (workspace_with_feature / ".canopy" / "state" /
                 "active_feature.json").exists()


def test_e2e_feature_scoping(workspace_with_feature):
    """``feature=X`` filters feature-bearing issues; workspace-wide checks still run."""
    _write_features(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a"], "status": "active"},
        "ghost": {"repos": ["repo-a"], "status": "active",
                   "worktree_paths": {"repo-a": "/nonexistent"}},
    })
    ws = _make_workspace(workspace_with_feature)
    report = doctor(ws, feature="auth-flow")
    issues = report["issues"]
    # Worktree_missing for "ghost" should be filtered out (other feature).
    wt_missing = [i for i in issues if i["code"] == "worktree_missing"]
    assert wt_missing == []
    # hook_missing (workspace-wide) should still appear.
    hook_missing = [i for i in issues if i["code"] == "hook_missing"]
    assert hook_missing  # not filtered


def test_e2e_returns_serializable_result(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    report = doctor(ws)
    # Round-trips through json without errors
    text = json.dumps(report, default=str)
    parsed = json.loads(text)
    assert parsed["summary"] == report["summary"]
