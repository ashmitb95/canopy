"""Tests for actions/resume.py — feature_resume compound orchestrator.

Fixture strategy
----------------
- ``canopy_toml_for_workspace`` for all tests — this fixture has both
  repo-a and repo-b with an ``auth-flow`` branch already checked out,
  which means ``resolve_feature`` can resolve "auth-flow" without an
  explicit features.json entry (implicit multi-repo feature).
- ``_make_canonical`` writes slots.json directly so switch doesn't need
  to run in test setup (avoids worktree overhead).
- Monkeypatch for the switch-when-not-canonical path (faster and
  avoids real worktree ops in tests).

Single-bump invariant (plan lines 131-146):
  - switch ran  → resume does NOT call mark_visited.
  - no switch   → resume calls mark_visited once at the end.
"""
import json
import time

import pytest

from canopy.actions import last_visit as lv
from canopy.actions import slots as slots_mod
from canopy.actions.resume import feature_resume
from canopy.workspace.config import load_config
from canopy.workspace.workspace import Workspace


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_workspace(root) -> Workspace:
    """Load a Workspace from the fixture root path."""
    return Workspace(load_config(root))


def _make_canonical(ws: Workspace, feature: str) -> None:
    """Write slots.json so ``feature`` is recorded as canonical.

    Uses direct state write (no switch) to avoid worktree overhead in tests.
    ``per_repo_paths`` points at the real repo dirs on disk so the staleness
    check in ``read_state`` keeps the entry valid.
    """
    per_repo = {
        repo.name: str(ws.config.root / repo.path)
        for repo in ws.config.repos
    }
    slots_mod.write_state(
        ws,
        slots_mod.SlotState(
            slot_count=2,
            canonical=slots_mod.CanonicalEntry(
                feature=feature,
                activated_at=slots_mod.now_iso(),
                per_repo_paths=per_repo,
            ),
        ),
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestFirstVisitAndShape:
    """Tests that don't require switch (feature already canonical or mocked)."""

    def test_resume_first_visit_marks_flag(self, canopy_toml_for_workspace):
        """No prior anchor → first_visit=True, last_visit=None."""
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")
        brief = feature_resume(ws, "auth-flow")

        assert brief["feature"] == "auth-flow"
        assert brief["first_visit"] is True
        assert brief["last_visit"] is None
        assert "since_last_visit" in brief
        assert "current_state" in brief
        assert "intent_hints" in brief
        assert isinstance(brief["intent_hints"], list)

    def test_resume_no_switch_when_already_canonical(self, canopy_toml_for_workspace):
        """Feature already canonical → switch_performed=False, switch_summary=None."""
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")
        brief = feature_resume(ws, "auth-flow")

        assert brief["switch_performed"] is False
        assert brief["switch_summary"] is None

    def test_resume_brief_shape_has_all_keys(self, canopy_toml_for_workspace):
        """Regression guard: all required top-level keys must be present."""
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")
        brief = feature_resume(ws, "auth-flow")

        required_top = {
            "version", "feature", "now", "last_visit", "first_visit",
            "window_hours", "switch_performed", "switch_summary",
            "intent_hints", "since_last_visit", "current_state",
        }
        assert required_top <= set(brief.keys()), (
            f"Missing keys: {required_top - set(brief.keys())}"
        )

        required_since = {
            "commits", "threads_new", "threads_resolved_on_github",
            "threads_resolved_by_canopy", "ci_status_delta",
            "draft_replies_pending", "historian_excerpt",
        }
        assert required_since <= set(brief["since_last_visit"].keys()), (
            f"Missing since_last_visit keys: "
            f"{required_since - set(brief['since_last_visit'].keys())}"
        )

        required_current = {
            "feature_state", "open_thread_count", "ci_summary_per_repo",
            "bot_unresolved_total", "draft_replies_summary",
            "branch_position_per_repo", "linear_issue", "linear_url",
        }
        assert required_current <= set(brief["current_state"].keys()), (
            f"Missing current_state keys: "
            f"{required_current - set(brief['current_state'].keys())}"
        )

    def test_resume_strips_internal_keys(self, canopy_toml_for_workspace):
        """__feature_name__ transport key must NOT appear in the returned brief."""
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")
        brief = feature_resume(ws, "auth-flow")

        assert "__feature_name__" not in brief["current_state"]

    def test_resume_since_containers_are_empty_stubs(self, canopy_toml_for_workspace):
        """T6-T7 stubs: most since_last_visit containers are empty (T8+ fills them).

        T7 fills commits; T8-T12 fill the rest.
        """
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")
        # Pre-seed a visit so _populate_since is invoked.
        lv.mark_visited(ws, "auth-flow")
        brief = feature_resume(ws, "auth-flow")

        s = brief["since_last_visit"]
        # T7 fills commits (so it's now a populated dict, not empty {}).
        assert isinstance(s["commits"], dict), "commits must be populated by T7"
        # T8+ fill the remaining containers.
        assert s["threads_new"] == []
        assert s["threads_resolved_on_github"] == []
        assert s["threads_resolved_by_canopy"] == []
        assert s["ci_status_delta"] == {}
        assert s["draft_replies_pending"] == 0
        assert s["historian_excerpt"] == ""


class TestSwitchBehavior:
    """Tests for the switch-if-not-canonical path (monkeypatched)."""

    def test_resume_switches_when_not_canonical(
        self, canopy_toml_for_workspace, monkeypatch
    ):
        """Feature not canonical → switch() is called with (workspace, feature)."""
        ws = _load_workspace(canopy_toml_for_workspace)
        # No slots.json → read_state returns None → not canonical → switch runs.
        calls = []

        def fake_switch(workspace, feature, **kwargs):
            calls.append((workspace, feature))
            return {"feature": feature, "switch_performed": True}

        # Patch the module-level `switch` name in resume so feature_resume uses fake.
        import canopy.actions.resume as resume_mod
        monkeypatch.setattr(resume_mod, "switch", fake_switch)

        brief = feature_resume(ws, "auth-flow")

        assert brief["switch_performed"] is True
        assert brief["switch_summary"] is not None
        assert len(calls) == 1
        assert calls[0][1] == "auth-flow"

    def test_resume_does_not_double_bump_when_switch_ran(
        self, canopy_toml_for_workspace, monkeypatch
    ):
        """Single-bump invariant: resume does NOT call mark_visited when switch ran.

        The mock switch does NOT bump last_visit (T13 hasn't landed). We verify
        that resume also skips the bump, leaving the anchor at the pre-seeded value.
        """
        ws = _load_workspace(canopy_toml_for_workspace)
        # Pre-seed a visit.
        t0 = lv.mark_visited(ws, "auth-flow")

        def fake_switch(workspace, feature, **kwargs):
            # Deliberately does NOT bump last_visit (simulating pre-T13 state).
            return {"feature": feature, "switch_performed": True}

        import canopy.actions.resume as resume_mod
        monkeypatch.setattr(resume_mod, "switch", fake_switch)
        # Report NOT canonical so the switch branch fires.
        monkeypatch.setattr(resume_mod.slots_mod, "read_state", lambda ws: None)

        feature_resume(ws, "auth-flow")

        # last_visit should still be t0 — neither mock-switch nor resume bumped.
        after = lv.get_last_visit(ws, "auth-flow")
        assert after["last_visit"] == t0, (
            "resume must not bump last_visit when switch_summary is truthy "
            "(single-bump invariant)"
        )


class TestAnchorBumping:
    """Tests for the last_visit bumping logic (no-switch path)."""

    def test_resume_bumps_anchor_once_when_no_switch(self, canopy_toml_for_workspace):
        """No switch ran → resume bumps last_visit at the end."""
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")
        ts1 = lv.mark_visited(ws, "auth-flow")

        feature_resume(ws, "auth-flow")

        after = lv.get_last_visit(ws, "auth-flow")
        assert after["last_visit"] >= ts1, "last_visit must have advanced"
        assert after["previous_visit"] == ts1, (
            "previous_visit must equal the pre-resume anchor"
        )

    def test_resume_diffs_against_prior_anchor(self, canopy_toml_for_workspace):
        """The brief's last_visit field must show the anchor BEFORE the bump.

        Ensures the orchestrator captures prior_iso before calling mark_visited
        so T7+ populators diff against the correct window.
        """
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")
        t0 = lv.mark_visited(ws, "auth-flow")

        brief = feature_resume(ws, "auth-flow")

        # The brief must report t0 (the prior anchor), not the freshly-bumped value.
        assert brief["last_visit"] == t0, (
            "brief['last_visit'] must be the anchor captured BEFORE the bump"
        )

    def test_resume_returns_window_hours_when_visited(self, canopy_toml_for_workspace):
        """window_hours >= 0 when a prior anchor exists; first_visit=False."""
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")
        lv.mark_visited(ws, "auth-flow")

        brief = feature_resume(ws, "auth-flow")

        assert brief["first_visit"] is False
        assert brief["window_hours"] is not None
        assert brief["window_hours"] >= 0.0

    def test_resume_first_visit_has_no_window(self, canopy_toml_for_workspace):
        """On first visit, window_hours must be None."""
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")
        brief = feature_resume(ws, "auth-flow")

        assert brief["first_visit"] is True
        assert brief["window_hours"] is None


class TestIntentHints:
    """Tests for _intent_hints with empty stubs (T6 state: all hints [])."""

    def test_intent_hints_empty_when_no_data(self, canopy_toml_for_workspace):
        """With T6 stubs, no populators fill since/current, so no hints fire."""
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")
        brief = feature_resume(ws, "auth-flow")

        assert brief["intent_hints"] == []

    def test_intent_hints_is_list(self, canopy_toml_for_workspace):
        """intent_hints must always be a list, never None."""
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")
        brief = feature_resume(ws, "auth-flow")

        assert isinstance(brief["intent_hints"], list)


class TestCommitsSinceLastVisit:
    """Tests for T7: commits-since-last-visit population (T7)."""

    def test_resume_includes_commits_per_repo(self, canopy_toml_for_workspace):
        """Commits authored after last_visit, on the feature branch."""
        import subprocess
        import os
        import time

        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")

        # Mark first visit.
        lv.mark_visited(ws, "auth-flow")
        time.sleep(1.1)  # ensure --since granularity passes

        # Make a commit on auth-flow in repo-a (repo_a is the first repo in canopy_toml).
        repo_a = ws.config.root / ws.config.repos[0].path
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@test.com",
        }
        # Ensure we're on auth-flow branch.
        subprocess.run(["git", "checkout", "auth-flow"], cwd=repo_a, env=env, check=True)
        # Make an empty commit with a recognizable message.
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "tweak: update auth module"],
            cwd=repo_a,
            env=env,
            check=True,
        )

        # Resume and check commits are included.
        brief = feature_resume(ws, "auth-flow")
        repo_a_name = ws.config.repos[0].name
        repo_a_commits = brief["since_last_visit"]["commits"].get(repo_a_name, [])

        assert len(repo_a_commits) >= 1, "Expected at least one commit in repo_a since last visit"
        assert "tweak" in repo_a_commits[0]["subject"], "Expected 'tweak' in commit subject"
        assert "update auth module" in repo_a_commits[0]["subject"]

    def test_resume_commits_empty_when_no_anchor(self, canopy_toml_for_workspace):
        """First visit (no prior anchor) → commits not populated."""
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")
        # No mark_visited() call — first visit.

        brief = feature_resume(ws, "auth-flow")

        # On first visit, _populate_since is not called (prior_iso is None).
        # commits should remain as the empty stub from initialization.
        assert brief["since_last_visit"]["commits"] == {}

    def test_resume_commits_empty_when_no_new_commits(self, canopy_toml_for_workspace):
        """Anchor set, no new commits → repos map to [].

        Fixture creates commits at setup time. We set anchor, sleep, then resume.
        Since no commits are made AFTER the anchor, all repos should be empty.
        """
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")

        # Sleep to ensure fixture commits are older than the anchor.
        time.sleep(2)
        # Mark visit — this captures the current second as the anchor.
        lv.mark_visited(ws, "auth-flow")
        # Sleep past the second to verify absence of new commits.
        time.sleep(1.1)

        # Resume WITHOUT making new commits.
        brief = feature_resume(ws, "auth-flow")

        commits = brief["since_last_visit"]["commits"]
        assert isinstance(commits, dict), "commits must be a dict"

        # All repos should have empty lists (no commits AFTER the anchor).
        for repo_name, commit_list in commits.items():
            assert commit_list == [], (
                f"Expected empty commit list for {repo_name}, "
                f"but got {commit_list}"
            )


class TestThreadDeltaSinceLastVisit:
    """Tests for T8: threads_new, threads_resolved_on_github, threads_resolved_by_canopy."""

    # Shared fake threads used across several tests.
    _FAKE_THREADS = [
        {
            "thread_id": "PRRT_old",
            "is_resolved": False,
            "resolved_at": None,
            "comments": [{
                "comment_id": 1,
                "created_at": "1900-01-01T00:00:00Z",
                "author": "alice",
                "path": "a.py",
                "line": 1,
                "body": "old comment",
                "url": "https://github.com/o/r/pull/1#discussion_r1",
            }],
        },
        {
            "thread_id": "PRRT_new",
            "is_resolved": False,
            "resolved_at": None,
            "comments": [{
                "comment_id": 2,
                "created_at": "2999-01-01T00:00:00Z",
                "author": "bob",
                "path": "b.py",
                "line": 2,
                "body": "new comment",
                "url": "https://github.com/o/r/pull/1#discussion_r2",
            }],
        },
    ]

    def _patch_pr_coords(self, monkeypatch):
        """Patch _pr_coords_per_repo to return one fake repo+PR."""
        import canopy.actions.resume as resume_mod
        monkeypatch.setattr(
            resume_mod,
            "_pr_coords_per_repo",
            lambda ws, f: {"repo-a": {"owner": "o", "repo_slug": "r", "pr_number": 1}},
        )

    def test_resume_threads_new_only_after_last_visit(
        self, canopy_toml_for_workspace, monkeypatch
    ):
        """Only threads with created_at > last_visit and not resolved land in threads_new."""
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")
        lv.mark_visited(ws, "auth-flow")
        time.sleep(1.1)

        self._patch_pr_coords(monkeypatch)
        monkeypatch.setattr(
            "canopy.integrations.github.list_review_threads",
            lambda *a, **k: self._FAKE_THREADS,
        )

        brief = feature_resume(ws, "auth-flow")
        new_ids = [t["thread_id"] for t in brief["since_last_visit"]["threads_new"]]
        assert new_ids == ["PRRT_new"], (
            f"Expected only PRRT_new in threads_new, got {new_ids}"
        )
        # PRRT_old predates the anchor and must be absent.
        assert "PRRT_old" not in new_ids

    def test_resume_threads_resolved_gh_attributed_to_canopy(
        self, canopy_toml_for_workspace, monkeypatch
    ):
        """A resolved thread whose thread_id is in thread_resolutions.json gets by_canopy=True."""
        from canopy.actions import thread_resolutions as tr

        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")
        lv.mark_visited(ws, "auth-flow")
        time.sleep(1.1)

        # Pre-write a canopy resolution for PRRT_resolved.
        tr.record(
            ws.config.root,
            thread_id="PRRT_resolved",
            feature="auth-flow",
            via_command="resolve",
        )

        resolved_thread = {
            "thread_id": "PRRT_resolved",
            "is_resolved": True,
            "resolved_at": "2999-06-01T00:00:00Z",
            "comments": [{
                "comment_id": 10,
                "created_at": "2999-01-01T00:00:00Z",
                "author": "carol",
                "path": "x.py",
                "line": 5,
                "body": "please fix this",
                "url": "https://github.com/o/r/pull/1#discussion_r10",
            }],
        }

        self._patch_pr_coords(monkeypatch)
        monkeypatch.setattr(
            "canopy.integrations.github.list_review_threads",
            lambda *a, **k: [resolved_thread],
        )

        brief = feature_resume(ws, "auth-flow")
        resolved = brief["since_last_visit"]["threads_resolved_on_github"]
        assert len(resolved) == 1
        assert resolved[0]["thread_id"] == "PRRT_resolved"
        assert resolved[0]["by_canopy"] is True

    def test_resume_threads_resolved_gh_not_attributed_when_external(
        self, canopy_toml_for_workspace, monkeypatch
    ):
        """A resolved thread with no canopy log entry gets by_canopy=False."""
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")
        lv.mark_visited(ws, "auth-flow")
        time.sleep(1.1)

        resolved_thread = {
            "thread_id": "PRRT_external",
            "is_resolved": True,
            "resolved_at": "2999-06-01T00:00:00Z",
            "comments": [{
                "comment_id": 20,
                "created_at": "2999-01-01T00:00:00Z",
                "author": "dave",
                "path": "y.py",
                "line": 7,
                "body": "fix this too",
                "url": "https://github.com/o/r/pull/1#discussion_r20",
            }],
        }

        self._patch_pr_coords(monkeypatch)
        monkeypatch.setattr(
            "canopy.integrations.github.list_review_threads",
            lambda *a, **k: [resolved_thread],
        )

        brief = feature_resume(ws, "auth-flow")
        resolved = brief["since_last_visit"]["threads_resolved_on_github"]
        assert len(resolved) == 1
        assert resolved[0]["thread_id"] == "PRRT_external"
        assert resolved[0]["by_canopy"] is False

    def test_resume_threads_by_canopy_filtered_by_feature_and_since(
        self, canopy_toml_for_workspace, monkeypatch
    ):
        """bot_resolutions entries: only matching feature AND addressed_at > anchor appear."""
        from canopy.actions.bot_resolutions import record_resolution

        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")
        lv.mark_visited(ws, "auth-flow")
        time.sleep(1.1)

        # Record one entry for auth-flow AFTER anchor, one BEFORE, one for wrong feature.
        record_resolution(
            ws.config.root,
            comment_id="111",
            feature="auth-flow",
            repo="repo-a",
            commit_sha="abc",
            comment_title="fix cache",
            addressed_at="2999-01-01T00:00:00Z",   # after anchor → should appear
        )
        record_resolution(
            ws.config.root,
            comment_id="222",
            feature="auth-flow",
            repo="repo-a",
            commit_sha="def",
            comment_title="old fix",
            addressed_at="1900-01-01T00:00:00Z",   # before anchor → must be excluded
        )
        record_resolution(
            ws.config.root,
            comment_id="333",
            feature="other-feature",
            repo="repo-a",
            commit_sha="ghi",
            comment_title="unrelated",
            addressed_at="2999-06-01T00:00:00Z",   # after anchor but wrong feature
        )

        # Suppress GH calls — threads_by_canopy doesn't need them.
        self._patch_pr_coords(monkeypatch)
        monkeypatch.setattr(
            "canopy.integrations.github.list_review_threads",
            lambda *a, **k: [],
        )

        brief = feature_resume(ws, "auth-flow")
        by_canopy = brief["since_last_visit"]["threads_resolved_by_canopy"]
        cids = [e["comment_id"] for e in by_canopy]
        assert "111" in cids, "entry 111 (auth-flow, after anchor) must appear"
        assert "222" not in cids, "entry 222 (auth-flow, before anchor) must be excluded"
        assert "333" not in cids, "entry 333 (other-feature) must be excluded"

    def test_resume_threads_delta_empty_when_no_pr(
        self, canopy_toml_for_workspace, monkeypatch
    ):
        """When _pr_coords_per_repo returns {}, all three thread fields are empty arrays."""
        import canopy.actions.resume as resume_mod

        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")
        lv.mark_visited(ws, "auth-flow")
        time.sleep(1.1)

        monkeypatch.setattr(
            resume_mod, "_pr_coords_per_repo", lambda ws, f: {},
        )

        brief = feature_resume(ws, "auth-flow")
        s = brief["since_last_visit"]
        assert s["threads_new"] == []
        assert s["threads_resolved_on_github"] == []
        assert s["threads_resolved_by_canopy"] == []
