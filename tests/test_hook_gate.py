"""Tests for the PreToolUse Bash gate (hook_gate)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


# ── split_top_level ─────────────────────────────────────────────────────

def test_split_simple_chain():
    from canopy.actions.hook_gate import split_top_level
    assert split_top_level("cd api && git push") == ["cd api", "git push"]


def test_split_respects_quotes():
    from canopy.actions.hook_gate import split_top_level
    parts = split_top_level('git commit -m "fix a && b; done"')
    assert parts == ['git commit -m "fix a && b; done"']


def test_split_semicolons_and_pipes():
    from canopy.actions.hook_gate import split_top_level
    assert split_top_level("git log --oneline | head -5; git status") == [
        "git log --oneline", "head -5", "git status",
    ]


def test_split_ignores_operators_inside_subshell():
    from canopy.actions.hook_gate import split_top_level
    parts = split_top_level('git commit -m "$(date +%s && echo x)" && git push')
    assert parts == ['git commit -m "$(date +%s && echo x)"', "git push"]


def test_split_single_or_chain():
    from canopy.actions.hook_gate import split_top_level
    assert split_top_level("git fetch || true") == ["git fetch", "true"]


# ── resolve_segments ────────────────────────────────────────────────────

def test_cd_chain_updates_effective_dir(tmp_path):
    from canopy.actions.hook_gate import resolve_segments
    segs = resolve_segments("cd api && git push", cwd=tmp_path)
    assert len(segs) == 1  # only git segments are returned
    assert segs[0].argv[:2] == ["git", "push"]
    assert segs[0].effective_dir == tmp_path / "api"
    assert segs[0].dir_known is True


def test_git_dash_c_overrides_dir(tmp_path):
    from canopy.actions.hook_gate import resolve_segments
    segs = resolve_segments(f"git -C {tmp_path}/ui commit -m 'x'", cwd=tmp_path)
    assert segs[0].effective_dir == tmp_path / "ui"
    assert segs[0].argv_after_globals[0] == "commit"


def test_absolute_cd(tmp_path):
    from canopy.actions.hook_gate import resolve_segments
    segs = resolve_segments(f"cd {tmp_path}/api && git add -A && git commit -m 'x'",
                            cwd=Path("/somewhere/else"))
    assert [s.argv_after_globals[0] for s in segs] == ["add", "commit"]
    assert all(s.effective_dir == tmp_path / "api" for s in segs)


def test_unresolvable_cd_marks_dir_unknown(tmp_path):
    from canopy.actions.hook_gate import resolve_segments
    segs = resolve_segments('cd "$PROJECT_DIR" && git push', cwd=tmp_path)
    assert segs[0].dir_known is False   # fail-open downstream


def test_non_git_segments_skipped(tmp_path):
    from canopy.actions.hook_gate import resolve_segments
    segs = resolve_segments("ls -la && pytest tests/ -v", cwd=tmp_path)
    assert segs == []


def test_unparseable_segment_skipped(tmp_path):
    from canopy.actions.hook_gate import resolve_segments
    # unbalanced quote inside one segment must not raise
    segs = resolve_segments("git commit -m 'unclosed && git push", cwd=tmp_path)
    assert isinstance(segs, list)


# ── classification ──────────────────────────────────────────────────────

def test_mutation_classification(tmp_path):
    from canopy.actions.hook_gate import resolve_segments, is_mutation
    segs = resolve_segments(
        "git status && git add -A && git checkout main && git push", cwd=tmp_path)
    flags = [(s.argv_after_globals[0], is_mutation(s)) for s in segs]
    assert flags == [("status", False), ("add", True),
                     ("checkout", False), ("push", True)]


# ── gate_command: path check ────────────────────────────────────────────
# Uses the slot-model fixtures from conftest.py:
#   workspace_with_canonical_only — X canonical in trunk, Y cold, slots=2


def _root(ws):
    return ws.config.root


def test_gate_allows_mutation_inside_trunk_repo(workspace_with_canonical_only):
    from canopy.actions.hook_gate import gate_command
    ws = workspace_with_canonical_only
    d = gate_command(ws, "git add -A", cwd=_root(ws) / "repo-a")
    assert d.allow is True


def test_gate_allows_cd_chain_from_workspace_root(workspace_with_canonical_only):
    from canopy.actions.hook_gate import gate_command
    ws = workspace_with_canonical_only
    d = gate_command(ws, 'cd repo-a && git commit -m "x"', cwd=_root(ws))
    assert d.allow is True


def test_gate_blocks_mutation_from_workspace_root(workspace_with_canonical_only):
    from canopy.actions.hook_gate import gate_command
    ws = workspace_with_canonical_only
    d = gate_command(ws, 'git commit -m "x"', cwd=_root(ws))
    assert d.allow is False
    assert d.code == "outside_repo"
    assert "repo-a" in d.reason and "repo-b" in d.reason  # lists real repos


def test_gate_allows_reads_anywhere(workspace_with_canonical_only):
    from canopy.actions.hook_gate import gate_command
    ws = workspace_with_canonical_only
    d = gate_command(ws, "git status && git log --oneline -5", cwd=_root(ws))
    assert d.allow is True   # reads are never gated


def test_gate_fails_open_on_unknown_dir(workspace_with_canonical_only):
    from canopy.actions.hook_gate import gate_command
    ws = workspace_with_canonical_only
    d = gate_command(ws, 'cd "$SOMEWHERE" && git push', cwd=_root(ws))
    assert d.allow is True


def test_gate_allows_mutation_in_slot_worktree(workspace_with_slots):
    from canopy.actions.hook_gate import gate_command
    from canopy.actions import slots as sm
    ws = workspace_with_slots      # X canonical, Y warm in worktree-1
    slot_dir = sm.slot_worktree_path(ws, "worktree-1", "repo-a")
    d = gate_command(ws, 'git commit -m "review fix"', cwd=slot_dir)
    assert d.allow is True


# ── gate_command: branch drift ──────────────────────────────────────────

def _write_features(ws, features: dict):
    fpath = _root(ws) / ".canopy" / "features.json"
    fpath.parent.mkdir(exist_ok=True)
    fpath.write_text(json.dumps(
        {name: {"repos": repos} for name, repos in features.items()}))


def test_gate_blocks_commit_on_drifted_trunk(workspace_with_canonical_only):
    from canopy.actions.hook_gate import gate_command
    ws = workspace_with_canonical_only          # canonical = X
    _write_features(ws, {"X": ["repo-a", "repo-b"], "Y": ["repo-a", "repo-b"]})
    # manually drift trunk repo-a onto Y (as if a raw `git checkout Y` happened)
    subprocess.run(["git", "checkout", "Y"], cwd=_root(ws) / "repo-a",
                   check=True, capture_output=True)
    d = gate_command(ws, 'git commit -m "x"', cwd=_root(ws) / "repo-a")
    assert d.allow is False
    assert d.code == "trunk_branch_drift"
    assert "canopy switch" in d.reason


def test_gate_allows_commit_on_default_branch(workspace_with_canonical_only):
    from canopy.actions.hook_gate import gate_command
    ws = workspace_with_canonical_only
    _write_features(ws, {"X": ["repo-a", "repo-b"]})
    subprocess.run(["git", "checkout", "main"], cwd=_root(ws) / "repo-a",
                   check=True, capture_output=True)
    d = gate_command(ws, 'git commit -m "x"', cwd=_root(ws) / "repo-a")
    assert d.allow is True


def test_gate_allows_unregistered_branch(workspace_with_canonical_only):
    from canopy.actions.hook_gate import gate_command
    ws = workspace_with_canonical_only
    _write_features(ws, {"X": ["repo-a", "repo-b"]})
    subprocess.run(["git", "checkout", "-b", "scratch-experiment"],
                   cwd=_root(ws) / "repo-a", check=True, capture_output=True)
    d = gate_command(ws, 'git commit -m "x"', cwd=_root(ws) / "repo-a")
    assert d.allow is True


def test_gate_blocks_wrong_branch_in_slot(workspace_with_slots):
    from canopy.actions.hook_gate import gate_command
    from canopy.actions import slots as sm
    ws = workspace_with_slots                   # Y warm in worktree-1
    _write_features(ws, {"X": ["repo-a", "repo-b"], "Y": ["repo-a", "repo-b"]})
    slot_dir = sm.slot_worktree_path(ws, "worktree-1", "repo-a")
    # drift the slot worktree onto a different branch
    subprocess.run(["git", "checkout", "-b", "sneaky"], cwd=slot_dir,
                   check=True, capture_output=True)
    d = gate_command(ws, 'git commit -m "x"', cwd=slot_dir)
    assert d.allow is False
    assert d.code == "slot_branch_drift"
    assert "Y" in d.reason                      # names the expected occupant


# ── gate_command: push refspec ──────────────────────────────────────────

def test_gate_blocks_push_of_branch_from_other_repo(workspace_with_canonical_only):
    from canopy.actions.hook_gate import gate_command
    ws = workspace_with_canonical_only
    # create a branch that exists ONLY in repo-b
    subprocess.run(["git", "branch", "only-in-b"], cwd=_root(ws) / "repo-b",
                   check=True, capture_output=True)
    d = gate_command(ws, "git push -u origin only-in-b", cwd=_root(ws) / "repo-a")
    assert d.allow is False
    assert d.code == "push_unknown_branch"
    assert "repo-b" in d.reason        # tells the agent where the branch lives


def test_gate_allows_push_of_existing_branch(workspace_with_canonical_only):
    from canopy.actions.hook_gate import gate_command
    ws = workspace_with_canonical_only
    d = gate_command(ws, "git push -u origin X", cwd=_root(ws) / "repo-a")
    assert d.allow is True             # X exists in repo-a


def test_gate_allows_bare_push(workspace_with_canonical_only):
    from canopy.actions.hook_gate import gate_command
    ws = workspace_with_canonical_only
    d = gate_command(ws, "git push", cwd=_root(ws) / "repo-a")
    assert d.allow is True


def test_gate_allows_push_options_and_head(workspace_with_canonical_only):
    from canopy.actions.hook_gate import gate_command
    ws = workspace_with_canonical_only
    assert gate_command(ws, "git push --force-with-lease origin HEAD",
                        cwd=_root(ws) / "repo-a").allow is True
    assert gate_command(ws, "git push origin --delete X",
                        cwd=_root(ws) / "repo-a").allow is True


# ── run_gate: payload wrapper ───────────────────────────────────────────

def _payload(command, cwd, tool="Bash"):
    return {"hook_event_name": "PreToolUse", "tool_name": tool,
            "cwd": str(cwd), "tool_input": {"command": command}}


def test_run_gate_blocks_and_explains(workspace_with_canonical_only):
    from canopy.actions.hook_gate import run_gate
    ws = workspace_with_canonical_only
    code, msg = run_gate(_payload('git commit -m "x"', _root(ws)))
    assert code == 2
    assert "not inside a workspace repo" in msg


def test_run_gate_allows_inside_repo(workspace_with_canonical_only):
    from canopy.actions.hook_gate import run_gate
    ws = workspace_with_canonical_only
    code, msg = run_gate(_payload("git add -A", _root(ws) / "repo-a"))
    assert (code, msg) == (0, "")


def test_run_gate_ignores_non_bash_tools(workspace_with_canonical_only):
    ws = workspace_with_canonical_only
    from canopy.actions.hook_gate import run_gate
    code, _ = run_gate(_payload("git push", _root(ws), tool="Edit"))
    assert code == 0


def test_run_gate_fast_path_no_git(workspace_with_canonical_only, monkeypatch):
    from canopy.actions import hook_gate
    # fast path must not even try to load a workspace
    monkeypatch.setattr(hook_gate, "_load_workspace_from",
                        lambda p: (_ for _ in ()).throw(AssertionError("loaded")))
    code, _ = hook_gate.run_gate(_payload("pytest tests/ -v",
                                          _root(workspace_with_canonical_only)))
    assert code == 0


def test_run_gate_outside_any_workspace(tmp_path):
    from canopy.actions.hook_gate import run_gate
    code, _ = run_gate(_payload("git push", tmp_path))
    assert code == 0                    # no canopy.toml above → not our problem


def test_run_gate_fails_open_on_garbage():
    from canopy.actions.hook_gate import run_gate
    assert run_gate({})[0] == 0
    assert run_gate({"tool_name": "Bash", "tool_input": {}})[0] == 0


def test_run_gate_respects_disable_env(workspace_with_canonical_only, monkeypatch):
    from canopy.actions.hook_gate import run_gate
    ws = workspace_with_canonical_only
    monkeypatch.setenv("CANOPY_HOOKS_DISABLED", "1")
    code, _ = run_gate(_payload('git commit -m "x"', _root(ws)))
    assert code == 0     # would block without the escape hatch
