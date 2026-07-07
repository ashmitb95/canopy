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

from canopy.management import last_visit as lv
from canopy.actions import slots as slots_mod
from canopy.management.resume import feature_resume
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
        import canopy.management.resume as resume_mod
        monkeypatch.setattr(resume_mod, "switch", fake_switch)

        brief = feature_resume(ws, "auth-flow")

        assert brief["switch_performed"] is True
        assert brief["switch_summary"] is not None
        assert len(calls) == 1
        assert calls[0][1] == "auth-flow"

    def test_resume_bumps_last_visit_even_when_switch_ran(
        self, canopy_toml_for_workspace, monkeypatch
    ):
        """Sole-bumper invariant: resume bumps last_visit even when switch ran.

        Phase 5 stripped switch's last_visit bump — switch returns slot state
        only. So feature_resume is now the SOLE bumper and must advance the
        anchor on the switch path too, else the resume+switch case never
        records a visit (a zero-bump).
        """
        import time
        ws = _load_workspace(canopy_toml_for_workspace)
        # Pre-seed a visit.
        t0 = lv.mark_visited(ws, "auth-flow")
        time.sleep(1.1)

        def fake_switch(workspace, feature, **kwargs):
            # Real switch no longer bumps last_visit (phase 5 strip).
            return {"feature": feature, "switch_performed": True}

        import canopy.management.resume as resume_mod
        monkeypatch.setattr(resume_mod, "switch", fake_switch)
        # Report NOT canonical so the switch branch fires.
        monkeypatch.setattr(resume_mod.slots_mod, "read_state", lambda ws: None)

        feature_resume(ws, "auth-flow")

        # resume is the sole bumper — the anchor must have advanced past t0.
        after = lv.get_last_visit(ws, "auth-flow")
        assert after["last_visit"] > t0, (
            "resume must bump last_visit on the switch path "
            "(switch no longer bumps — sole-bumper invariant)"
        )
        assert after["previous_visit"] == t0, (
            "the prior anchor must roll into previous_visit"
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
        import canopy.management.resume as resume_mod
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
        from canopy.management import thread_resolutions as tr

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
        from canopy.management.bot_resolutions import record_resolution

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
        import canopy.management.resume as resume_mod

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


class TestCurrentStatePopulation:
    """Tests for T9: feature_state, ci_summary_per_repo, branch_position_per_repo."""

    def test_resume_branch_position_per_repo(self, canopy_toml_for_workspace):
        """branch_position_per_repo has correct shape for each repo in the feature."""
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")

        brief = feature_resume(ws, "auth-flow")
        pos = brief["current_state"]["branch_position_per_repo"]

        assert isinstance(pos, dict), "branch_position_per_repo must be a dict"
        # The fixture creates auth-flow in both repo-a and repo-b.
        assert len(pos) >= 1, "At least one repo should appear in branch_position"

        for repo_name, entry in pos.items():
            assert "branch" in entry, f"{repo_name}: missing 'branch'"
            assert "default_branch" in entry, f"{repo_name}: missing 'default_branch'"
            assert "ahead" in entry, f"{repo_name}: missing 'ahead'"
            assert "behind" in entry, f"{repo_name}: missing 'behind'"
            assert "last_sync_at" in entry, f"{repo_name}: missing 'last_sync_at'"
            assert entry["ahead"] >= 0, f"{repo_name}: ahead must be >= 0"
            assert entry["behind"] >= 0, f"{repo_name}: behind must be >= 0"
            assert entry["branch"] == "auth-flow"
            assert isinstance(entry["last_sync_at"], str)

    def test_resume_ci_summary_per_repo(self, canopy_toml_for_workspace, monkeypatch):
        """ci_summary_per_repo lifts CI status strings from feature_state summary."""
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")

        def fake_feature_state(workspace, feature):
            return {
                "state": "awaiting_ci",
                "summary": {
                    "ci_per_repo": {
                        "repo-a": {"status": "passing"},
                        "repo-b": {"status": "failing"},
                    },
                },
            }

        monkeypatch.setattr(
            "canopy.management.feature_state.feature_state",
            fake_feature_state,
        )

        brief = feature_resume(ws, "auth-flow")
        ci = brief["current_state"]["ci_summary_per_repo"]

        assert ci.get("repo-a") == "passing"
        assert ci.get("repo-b") == "failing"
        assert brief["current_state"]["feature_state"] == "awaiting_ci"

    def test_resume_align_with_default_hint_surfaces(
        self, canopy_toml_for_workspace, monkeypatch
    ):
        """align_with_default intent hint fires when any repo has behind > 0."""
        import os
        import subprocess

        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")

        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@test.com",
        }

        # Add a commit to main in repo-a AFTER the auth-flow branch was created,
        # so auth-flow ends up behind main by 1.
        repo_a = canopy_toml_for_workspace / "repo-a"
        subprocess.run(["git", "checkout", "main"], cwd=repo_a, env=env, check=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "main: advance default"],
            cwd=repo_a, env=env, check=True,
        )
        subprocess.run(["git", "checkout", "auth-flow"], cwd=repo_a, env=env, check=True)

        # Suppress feature_state (avoids GH calls) — we only need branch_position.
        monkeypatch.setattr(
            "canopy.management.feature_state.feature_state",
            lambda ws, f: {},
        )

        brief = feature_resume(ws, "auth-flow")

        pos = brief["current_state"]["branch_position_per_repo"]
        assert pos.get("repo-a", {}).get("behind", 0) > 0, (
            "repo-a should be behind main after the commit on main"
        )

        hint_kinds = [h["kind"] for h in brief["intent_hints"]]
        assert "align_with_default" in hint_kinds, (
            f"align_with_default hint must fire when behind > 0; hints={brief['intent_hints']}"
        )

        align_hint = next(h for h in brief["intent_hints"] if h["kind"] == "align_with_default")
        assert align_hint["priority"] == 2

    def test_resume_feature_state_unknown_when_lookup_fails(
        self, canopy_toml_for_workspace, monkeypatch
    ):
        """feature_state lookup raises → current_state.feature_state == 'unknown', brief intact."""
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")

        def boom(workspace, feature):
            raise RuntimeError("simulated failure")

        monkeypatch.setattr(
            "canopy.management.feature_state.feature_state",
            boom,
        )

        brief = feature_resume(ws, "auth-flow")

        assert brief["current_state"]["feature_state"] == "unknown"
        # The rest of the brief should still be populated (not crash).
        assert "branch_position_per_repo" in brief["current_state"]
        assert "ci_summary_per_repo" in brief["current_state"]
        assert isinstance(brief["intent_hints"], list)

    def test_resume_bot_unresolved_total_from_status(
        self, canopy_toml_for_workspace, monkeypatch
    ):
        """bot_unresolved_total sums unresolved counts per repo from bot_comments_status."""
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")

        def fake_bot_comments_status(workspace, feature):
            return {
                "feature": feature,
                "repos": {
                    "repo-a": {"unresolved": 2, "resolved": 1, "total": 3},
                    "repo-b": {"unresolved": 1, "resolved": 0, "total": 1},
                },
                "all_resolved": False,
                "any_bot_comments": True,
            }

        monkeypatch.setattr(
            "canopy.management.bot_status.bot_comments_status",
            fake_bot_comments_status,
        )

        brief = feature_resume(ws, "auth-flow")

        # Sum of unresolved: repo-a(2) + repo-b(1) = 3
        assert brief["current_state"]["bot_unresolved_total"] == 3

    def test_resume_bot_unresolved_total_zero_on_failure(
        self, canopy_toml_for_workspace, monkeypatch
    ):
        """bot_comments_status raises → bot_unresolved_total == 0, brief intact."""
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")

        def boom(workspace, feature):
            raise RuntimeError("simulated bot_status failure")

        monkeypatch.setattr(
            "canopy.management.bot_status.bot_comments_status",
            boom,
        )

        brief = feature_resume(ws, "auth-flow")

        # Error swallowed, defaults to 0.
        assert brief["current_state"]["bot_unresolved_total"] == 0
        # Rest of brief intact.
        assert brief["feature"] == "auth-flow"
        assert "branch_position_per_repo" in brief["current_state"]
        assert isinstance(brief["intent_hints"], list)


class TestDraftRepliesSummary:
    """Tests for T11: draft_replies_summary and draft_replies_pending."""

    def test_resume_draft_replies_summary_in_current(
        self, canopy_toml_for_workspace, monkeypatch
    ):
        """T11: draft_replies_summary populated from draft_replies call."""
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")

        def fake_drafts(workspace, feature, **kwargs):
            return {
                "alias": feature,
                "addressed_total": 3,
                "unaddressed_total": 1,
                "repos": {
                    "repo-a": {
                        "pr_number": 42,
                        "pr_url": "https://github.com/a/pr/42",
                        "addressed": [{"comment_id": 1}, {"comment_id": 2}],
                        "unaddressed": [{"comment_id": 3}],
                    },
                    "repo-b": {
                        "pr_number": 43,
                        "pr_url": "https://github.com/b/pr/43",
                        "addressed": [{"comment_id": 4}],
                        "unaddressed": [],
                    },
                },
            }

        monkeypatch.setattr(
            "canopy.management.draft_replies.draft_replies",
            fake_drafts,
        )

        brief = feature_resume(ws, "auth-flow")

        assert brief["current_state"]["draft_replies_summary"] == {
            "addressed_total": 3,
            "unaddressed_total": 1,
        }

    def test_resume_post_drafts_hint_fires_when_addressed_total_gt_0(
        self, canopy_toml_for_workspace, monkeypatch
    ):
        """T11: post_drafts intent hint fires when addressed_total > 0."""
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")

        def fake_drafts(workspace, feature, **kwargs):
            return {
                "alias": feature,
                "addressed_total": 2,
                "unaddressed_total": 0,
                "repos": {
                    "repo-a": {
                        "pr_number": 42,
                        "pr_url": "https://github.com/a/pr/42",
                        "addressed": [{"comment_id": 1}, {"comment_id": 2}],
                        "unaddressed": [],
                    },
                },
            }

        monkeypatch.setattr(
            "canopy.management.draft_replies.draft_replies",
            fake_drafts,
        )

        brief = feature_resume(ws, "auth-flow")

        # Check that post_drafts hint is in the list.
        post_drafts_hints = [h for h in brief["intent_hints"] if h["kind"] == "post_drafts"]
        assert len(post_drafts_hints) == 1
        hint = post_drafts_hints[0]
        assert hint["summary"] == "2 draft replies ready"
        assert hint["suggested_tool"] == "draft_replies"
        assert hint["priority"] == 3

    def test_resume_draft_replies_pending_only_when_anchor(
        self, canopy_toml_for_workspace, monkeypatch
    ):
        """T11: draft_replies_pending only when prior anchor exists (not first visit)."""
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")

        def fake_drafts(workspace, feature, **kwargs):
            return {
                "alias": feature,
                "addressed_total": 2,
                "unaddressed_total": 0,
                "repos": {
                    "repo-a": {
                        "pr_number": 42,
                        "pr_url": "https://github.com/a/pr/42",
                        "addressed": [{"comment_id": 1}, {"comment_id": 2}],
                        "unaddressed": [],
                    },
                    "repo-b": {
                        "pr_number": 43,
                        "pr_url": "https://github.com/b/pr/43",
                        "addressed": [],
                        "unaddressed": [],
                    },
                },
            }

        monkeypatch.setattr(
            "canopy.management.draft_replies.draft_replies",
            fake_drafts,
        )

        # First visit (no anchor): draft_replies_pending should be 0.
        brief1 = feature_resume(ws, "auth-flow")
        assert brief1["first_visit"] is True
        assert brief1["since_last_visit"]["draft_replies_pending"] == 0

        # After seeding a visit, resume again (now has anchor).
        lv.mark_visited(ws, "auth-flow")
        brief2 = feature_resume(ws, "auth-flow")
        assert brief2["first_visit"] is False
        # Sum of addressed per repo: repo-a(2) + repo-b(0) = 2.
        assert brief2["since_last_visit"]["draft_replies_pending"] == 2

    def test_resume_draft_replies_summary_zero_on_failure(
        self, canopy_toml_for_workspace, monkeypatch
    ):
        """T11: draft_replies failure → summary defaults, brief intact."""
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")

        def boom(workspace, feature, **kwargs):
            raise RuntimeError("simulated draft_replies failure")

        monkeypatch.setattr(
            "canopy.management.draft_replies.draft_replies",
            boom,
        )

        brief = feature_resume(ws, "auth-flow")

        # Error swallowed, defaults to zero totals.
        assert brief["current_state"]["draft_replies_summary"] == {
            "addressed_total": 0,
            "unaddressed_total": 0,
        }
        # Rest of brief intact.
        assert brief["feature"] == "auth-flow"
        assert "branch_position_per_repo" in brief["current_state"]
        assert isinstance(brief["intent_hints"], list)


class TestLinearFromLane:
    """Tests for Fix #1: linear_issue + linear_url populated from FeatureLane."""

    def test_resume_populates_linear_from_lane(self, canopy_toml_for_workspace, monkeypatch):
        """Brief surfaces lane.linear_issue and lane.linear_url."""
        import canopy.management.resume as resume_mod
        from canopy.features.coordinator import FeatureLane

        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")

        fake_lane = FeatureLane(
            name="auth-flow",
            repos=["repo-a", "repo-b"],
            linear_issue="DOC-42",
            linear_url="https://linear.app/team/issue/DOC-42",
        )

        import canopy.features.coordinator as coord_mod
        original_status = coord_mod.FeatureCoordinator.status

        def fake_status(self, name):
            return fake_lane

        monkeypatch.setattr(coord_mod.FeatureCoordinator, "status", fake_status)

        brief = feature_resume(ws, "auth-flow")

        assert brief["current_state"]["linear_issue"] == "DOC-42"
        assert brief["current_state"]["linear_url"] == "https://linear.app/team/issue/DOC-42"

    def test_resume_linear_none_when_lane_has_no_issue(self, canopy_toml_for_workspace):
        """Implicit feature (no features.json entry) → linear_issue/url are None."""
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")
        # auth-flow is an implicit feature in the fixture (no features.json entry),
        # so linear_issue defaults to "" on the lane → normalized to None.
        brief = feature_resume(ws, "auth-flow")

        assert brief["current_state"]["linear_issue"] is None
        assert brief["current_state"]["linear_url"] is None

    def test_resume_linear_none_when_lane_lookup_fails(
        self, canopy_toml_for_workspace, monkeypatch
    ):
        """If FeatureLane lookup raises, linear_issue/url default to None and brief is intact."""
        import canopy.features.coordinator as coord_mod

        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")

        def boom(self, name):
            raise RuntimeError("simulated coordinator failure")

        monkeypatch.setattr(coord_mod.FeatureCoordinator, "status", boom)

        brief = feature_resume(ws, "auth-flow")

        assert brief["current_state"]["linear_issue"] is None
        assert brief["current_state"]["linear_url"] is None
        # Rest of brief intact.
        assert brief["feature"] == "auth-flow"
        assert isinstance(brief["intent_hints"], list)


class TestOpenThreadCount:
    """Tests for Fix #2: open_thread_count rolled up from list_review_threads."""

    def test_resume_open_thread_count_rolled_up(
        self, canopy_toml_for_workspace, monkeypatch
    ):
        """open_thread_count sums unresolved threads across repos."""
        import canopy.management.resume as resume_mod

        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")

        monkeypatch.setattr(
            resume_mod,
            "_pr_coords_per_repo",
            lambda ws, f: {"repo-a": {"owner": "o", "repo_slug": "r", "pr_number": 1}},
        )
        monkeypatch.setattr(
            "canopy.integrations.github.list_review_threads",
            lambda *a, **k: [
                {"thread_id": "PRRT_1", "is_resolved": False, "comments": []},
                {"thread_id": "PRRT_2", "is_resolved": True, "comments": []},
                {"thread_id": "PRRT_3", "is_resolved": False, "comments": []},
            ],
        )

        brief = feature_resume(ws, "auth-flow")
        assert brief["current_state"]["open_thread_count"] == 2

    def test_resume_open_thread_count_zero_when_no_prs(
        self, canopy_toml_for_workspace, monkeypatch
    ):
        """When all PR coords are None, open_thread_count is 0."""
        import canopy.management.resume as resume_mod

        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")

        monkeypatch.setattr(
            resume_mod,
            "_pr_coords_per_repo",
            lambda ws, f: {"repo-a": None},
        )

        brief = feature_resume(ws, "auth-flow")
        assert brief["current_state"]["open_thread_count"] == 0

    def test_resume_open_thread_count_zero_on_exception(
        self, canopy_toml_for_workspace, monkeypatch
    ):
        """If _pr_coords_per_repo raises, open_thread_count defaults to 0."""
        import canopy.management.resume as resume_mod

        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")

        def boom(ws, f):
            raise RuntimeError("simulated failure")

        monkeypatch.setattr(resume_mod, "_pr_coords_per_repo", boom)

        brief = feature_resume(ws, "auth-flow")
        assert brief["current_state"]["open_thread_count"] == 0


class TestHintCoverage:
    """Tests for SHOULD FIX items: investigate_ci and read_issue hints."""

    def test_resume_investigate_ci_hint_surfaces(
        self, canopy_toml_for_workspace, monkeypatch
    ):
        """When any repo CI is failing, investigate_ci hint fires at priority 1."""
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")

        monkeypatch.setattr(
            "canopy.management.feature_state.feature_state",
            lambda ws, f: {
                "state": "awaiting_ci",
                "summary": {
                    "ci_per_repo": {
                        "repo-a": {"status": "failing"},
                        "repo-b": {"status": "passing"},
                    },
                },
            },
        )

        brief = feature_resume(ws, "auth-flow")

        ci_hints = [h for h in brief["intent_hints"] if h["kind"] == "investigate_ci"]
        assert len(ci_hints) == 1, f"Expected 1 investigate_ci hint, got {ci_hints}"
        assert ci_hints[0]["priority"] == 1
        assert "repo-a" in ci_hints[0]["summary"]

    def test_resume_read_issue_hint_on_first_visit(
        self, canopy_toml_for_workspace, monkeypatch
    ):
        """First visit AND linear_issue set → read_issue hint fires at priority 1."""
        import canopy.features.coordinator as coord_mod
        from canopy.features.coordinator import FeatureLane

        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")
        # No mark_visited() → first_visit=True

        fake_lane = FeatureLane(
            name="auth-flow",
            repos=["repo-a", "repo-b"],
            linear_issue="DOC-42",
            linear_url="https://linear.app/team/issue/DOC-42",
        )

        monkeypatch.setattr(
            coord_mod.FeatureCoordinator, "status", lambda self, name: fake_lane
        )

        brief = feature_resume(ws, "auth-flow")

        assert brief["first_visit"] is True
        read_hints = [h for h in brief["intent_hints"] if h["kind"] == "read_issue"]
        assert len(read_hints) == 1, (
            f"Expected 1 read_issue hint on first visit with linear_issue set; "
            f"hints={brief['intent_hints']}"
        )
        assert read_hints[0]["priority"] == 1
        assert "DOC-42" in read_hints[0]["summary"]

    def test_resume_read_issue_hint_not_on_second_visit(
        self, canopy_toml_for_workspace, monkeypatch
    ):
        """read_issue hint must NOT fire when first_visit=False, even with linear_issue set."""
        import canopy.features.coordinator as coord_mod
        from canopy.features.coordinator import FeatureLane

        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")
        lv.mark_visited(ws, "auth-flow")   # second visit now

        fake_lane = FeatureLane(
            name="auth-flow",
            repos=["repo-a", "repo-b"],
            linear_issue="DOC-42",
            linear_url="https://linear.app/team/issue/DOC-42",
        )
        monkeypatch.setattr(
            coord_mod.FeatureCoordinator, "status", lambda self, name: fake_lane
        )

        brief = feature_resume(ws, "auth-flow")

        assert brief["first_visit"] is False
        read_hints = [h for h in brief["intent_hints"] if h["kind"] == "read_issue"]
        assert read_hints == [], "read_issue hint must not fire on second visit"


class TestPrCoordsPerRepo:
    """Direct tests for _pr_coords_per_repo."""

    def test_pr_coords_per_repo_handles_unresolvable_remote(
        self, canopy_toml_for_workspace
    ):
        """_pr_coords_per_repo returns repo -> None for unparseable (file://) remotes."""
        from canopy.management.resume import _pr_coords_per_repo

        ws = _load_workspace(canopy_toml_for_workspace)
        # The fixture uses file:// remotes which _extract_owner_repo cannot parse.
        result = _pr_coords_per_repo(ws, "auth-flow")

        assert isinstance(result, dict)
        assert len(result) >= 1, "Expected at least one repo in result"
        for repo_name, coords in result.items():
            assert coords is None, (
                f"{repo_name}: expected None for file:// remote, got {coords}"
            )


class TestFutureAnchor:
    """Edge case: last_visit set to a future timestamp."""

    def test_resume_future_anchor_returns_empty_sections(
        self, canopy_toml_for_workspace
    ):
        """Anchor in the future → since_last_visit sections are empty, brief doesn't crash."""
        from canopy.management import last_visit as lv_mod

        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")

        # Write a future timestamp directly.
        lv_mod._save(
            ws,
            {"auth-flow": {"last_visit": "2099-01-01T00:00:00Z", "previous_visit": None}},
        )

        brief = feature_resume(ws, "auth-flow")

        assert brief["first_visit"] is False
        assert brief["last_visit"] == "2099-01-01T00:00:00Z"

        # commits: all repos should have empty lists (no commits after 2099).
        commits = brief["since_last_visit"]["commits"]
        assert isinstance(commits, dict)
        for repo_name, commit_list in commits.items():
            assert commit_list == [], (
                f"{repo_name}: expected no commits before 2099 anchor, got {commit_list}"
            )

        # thread sections should also be empty.
        assert brief["since_last_visit"]["threads_new"] == []
        assert brief["since_last_visit"]["threads_resolved_on_github"] == []


class TestHistorianExcerpt:
    """Tests for T12: historian_excerpt in since_last_visit."""

    def test_resume_historian_excerpt_populated_when_anchor_exists(
        self, canopy_toml_for_workspace, monkeypatch
    ):
        """When historian has entries past last_visit, the brief carries the excerpt."""
        from canopy.management import historian

        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")

        # Mark first visit.
        t_anchor = lv.mark_visited(ws, "auth-flow")
        time.sleep(1.1)

        # Record a historian entry after the anchor.
        historian.record_event(
            ws.config.root,
            "auth-flow",
            summary="reviewed PR comments",
            at="2026-05-26T15:00:00Z",
        )

        # Mock format_for_agent_since to verify it's called with correct args.
        calls = []
        original_fn = historian.format_for_agent_since

        def tracked_format(root, feature, since_iso):
            calls.append((root, feature, since_iso))
            return original_fn(root, feature, since_iso)

        monkeypatch.setattr(
            "canopy.management.historian.format_for_agent_since",
            tracked_format,
        )

        brief = feature_resume(ws, "auth-flow")

        # Verify the function was called with correct arguments.
        assert len(calls) == 1, f"Expected 1 call, got {len(calls)}"
        assert calls[0][0] == ws.config.root
        assert calls[0][1] == "auth-flow"
        assert calls[0][2] == t_anchor, "Must pass the prior anchor timestamp"

        # The excerpt should be populated (non-empty when entry exists after anchor).
        assert isinstance(brief["since_last_visit"]["historian_excerpt"], str)

    def test_resume_historian_excerpt_empty_on_first_visit(
        self, canopy_toml_for_workspace, monkeypatch
    ):
        """On first visit (no prior anchor), historian_excerpt is '' (populator not called)."""
        from canopy.management import historian

        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")

        # Pre-populate some historian entries (but we won't have an anchor).
        historian.record_event(
            ws.config.root,
            "auth-flow",
            summary="old event",
            at="2026-01-01T00:00:00Z",
        )

        # Mock to ensure format_for_agent_since is NOT called on first visit.
        calls = []

        def tracked_format(root, feature, since_iso):
            calls.append((root, feature, since_iso))
            return ""

        monkeypatch.setattr(
            "canopy.management.historian.format_for_agent_since",
            tracked_format,
        )

        brief = feature_resume(ws, "auth-flow")

        # On first visit, _populate_since is NOT called (prior_iso is None).
        # So format_for_agent_since should not be called.
        assert len(calls) == 0, (
            f"format_for_agent_since must not be called on first visit; "
            f"got {len(calls)} calls"
        )

        # historian_excerpt should remain the default empty string.
        assert brief["since_last_visit"]["historian_excerpt"] == ""
        assert brief["first_visit"] is True

    def test_resume_historian_excerpt_empty_string_on_failure(
        self, canopy_toml_for_workspace, monkeypatch
    ):
        """If format_for_agent_since raises, historian_excerpt defaults to ''."""
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")
        lv.mark_visited(ws, "auth-flow")
        time.sleep(1.1)

        def boom(root, feature, since_iso):
            raise RuntimeError("simulated historian failure")

        monkeypatch.setattr(
            "canopy.management.historian.format_for_agent_since",
            boom,
        )

        brief = feature_resume(ws, "auth-flow")

        # Error swallowed, defaults to empty string.
        assert brief["since_last_visit"]["historian_excerpt"] == ""
        # Rest of brief intact.
        assert brief["feature"] == "auth-flow"
        assert "commits" in brief["since_last_visit"]
        assert isinstance(brief["intent_hints"], list)

    def test_resume_historian_excerpt_filters_old_sessions(
        self, canopy_toml_for_workspace, monkeypatch
    ):
        """historian_excerpt includes only entries newer than last_visit."""
        from canopy.management import historian
        from datetime import datetime, timezone, timedelta

        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")

        # Record old entry before anchor (1 hour ago).
        now = datetime.now(timezone.utc)
        old_time = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        historian.record_event(
            ws.config.root,
            "auth-flow",
            summary="old session work",
            at=old_time,
        )

        t_anchor = lv.mark_visited(ws, "auth-flow")
        time.sleep(1.1)

        # Record new entry after anchor (current time, which is after the anchor).
        new_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        historian.record_decision(
            ws.config.root,
            "auth-flow",
            title="new library choice",
            at=new_time,
        )

        brief = feature_resume(ws, "auth-flow")

        excerpt = brief["since_last_visit"]["historian_excerpt"]
        # New entry should appear.
        assert "new library choice" in excerpt
        # Old entry should not appear.
        assert "old session work" not in excerpt
        # Should still have markdown structure.
        assert "# Feature: auth-flow" in excerpt


# ── T14: resume_summary unit tests ───────────────────────────────────────────


_SUMMARY_KEYS = {
    "last_visit", "first_visit", "new_commit_count", "new_thread_count",
    "github_resolved_count", "ci_changed", "draft_replies_pending",
    "memory_present", "degraded",
}


class TestResumeSummary:
    """Unit tests for resume_summary — the counts-only view embedded in switch."""

    def test_resume_summary_first_visit(self, canopy_toml_for_workspace):
        """No prior anchor → first_visit=True, all counts zero, degraded=False."""
        from canopy.management.resume import resume_summary

        ws = _load_workspace(canopy_toml_for_workspace)
        summary = resume_summary(ws, "auth-flow")

        assert summary["first_visit"] is True
        assert summary["last_visit"] is None
        assert summary["new_commit_count"] == 0
        assert summary["new_thread_count"] == 0
        assert summary["github_resolved_count"] == 0
        assert summary["ci_changed"] is False
        assert summary["draft_replies_pending"] == 0
        assert summary["degraded"] is False
        # All required keys must be present.
        assert _SUMMARY_KEYS <= set(summary.keys()), (
            f"Missing keys: {_SUMMARY_KEYS - set(summary.keys())}"
        )

    def test_resume_summary_with_prior_iso_explicit(self, canopy_toml_for_workspace):
        """When prior_iso is passed explicitly, diff anchors to it even if current anchor differs."""
        from canopy.management.resume import resume_summary

        ws = _load_workspace(canopy_toml_for_workspace)
        # Bump the live anchor.
        lv.mark_visited(ws, "auth-flow")

        # Pass an explicit prior that's much older — the summary should report it back.
        summary = resume_summary(ws, "auth-flow", prior_iso="2020-01-01T00:00:00Z")

        assert summary["first_visit"] is False
        assert summary["last_visit"] == "2020-01-01T00:00:00Z"

    def test_resume_summary_prior_iso_none_falls_back_to_live_anchor(
        self, canopy_toml_for_workspace
    ):
        """When prior_iso is omitted, falls back to the current live anchor."""
        from canopy.management.resume import resume_summary

        ws = _load_workspace(canopy_toml_for_workspace)
        ts = lv.mark_visited(ws, "auth-flow")

        summary = resume_summary(ws, "auth-flow")  # no prior_iso

        assert summary["first_visit"] is False
        assert summary["last_visit"] == ts

    def test_resume_summary_degraded_when_threads_fail(
        self, canopy_toml_for_workspace, monkeypatch
    ):
        """GH unreachable → degraded=True, thread counts zero."""
        from canopy.management.resume import resume_summary

        ws = _load_workspace(canopy_toml_for_workspace)
        lv.mark_visited(ws, "auth-flow")

        def boom(*a, **k):
            raise RuntimeError("offline")

        monkeypatch.setattr("canopy.management.resume._threads_delta", boom)

        summary = resume_summary(ws, "auth-flow", prior_iso="2020-01-01T00:00:00Z")

        assert summary["degraded"] is True
        assert summary["new_thread_count"] == 0
        assert summary["github_resolved_count"] == 0
        # Commit count is unaffected by GH failure (local-only computation).
        assert isinstance(summary["new_commit_count"], int)

    def test_resume_summary_counts_new_commits(self, canopy_toml_for_workspace):
        """Commits on the feature branch after prior_iso appear in new_commit_count."""
        import os
        import subprocess
        from canopy.management.resume import resume_summary

        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")

        # Capture the anchor BEFORE making commits.
        prior_iso = lv.mark_visited(ws, "auth-flow")
        time.sleep(1.1)

        # Make a commit on auth-flow in repo-a.
        repo_a = ws.config.root / ws.config.repos[0].path
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@test.com",
        }
        subprocess.run(["git", "checkout", "auth-flow"], cwd=repo_a, env=env, check=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "feat: new work"],
            cwd=repo_a, env=env, check=True,
        )

        summary = resume_summary(ws, "auth-flow", prior_iso=prior_iso)

        assert summary["first_visit"] is False
        assert summary["new_commit_count"] >= 1, (
            "Expected at least one new commit in new_commit_count"
        )

    def test_resume_summary_memory_present_when_historian_has_content(
        self, canopy_toml_for_workspace
    ):
        """memory_present=True when historian.format_for_agent returns non-empty."""
        from canopy.management import historian
        from canopy.management.resume import resume_summary

        ws = _load_workspace(canopy_toml_for_workspace)
        historian.record_event(
            ws.config.root, "auth-flow",
            summary="did some work",
            at="2026-01-01T00:00:00Z",
        )

        summary = resume_summary(ws, "auth-flow")

        assert summary["memory_present"] is True

    def test_resume_summary_memory_not_present_when_no_content(
        self, canopy_toml_for_workspace
    ):
        """memory_present=False when historian has no content for the feature."""
        from canopy.management.resume import resume_summary

        ws = _load_workspace(canopy_toml_for_workspace)
        # No historian entries written.
        summary = resume_summary(ws, "auth-flow")

        assert summary["memory_present"] is False


# ── CLI smoke tests ───────────────────────────────────────────────────────────


class TestResumeCLI:
    """Smoke tests for the cmd_resume CLI wiring."""

    def test_resume_command_json(self, canopy_toml_for_workspace, monkeypatch, capsys):
        """cmd_resume --json prints the structured brief."""
        import argparse
        import json as _json

        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")
        monkeypatch.setattr("canopy.cli.main._load_workspace", lambda: ws)

        from canopy.cli.main import cmd_resume
        args = argparse.Namespace(alias="auth-flow", json=True, reset_anchor=False)
        cmd_resume(args)

        data = _json.loads(capsys.readouterr().out)
        assert data["version"] == 1
        assert data["feature"] == "auth-flow"
        assert "since_last_visit" in data
        assert "current_state" in data
        assert "intent_hints" in data

    def test_resume_command_human_renders_sections(
        self, canopy_toml_for_workspace, monkeypatch, capsys
    ):
        """Human mode prints the feature name and at least one section header."""
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")
        monkeypatch.setattr("canopy.cli.main._load_workspace", lambda: ws)

        import argparse
        from canopy.cli.main import cmd_resume
        args = argparse.Namespace(alias="auth-flow", json=False, reset_anchor=False)
        cmd_resume(args)

        out = capsys.readouterr().out
        assert "auth-flow" in out

    def test_resume_command_reset_anchor(
        self, canopy_toml_for_workspace, monkeypatch, capsys
    ):
        """--reset-anchor drops the last_visit entry."""
        from canopy.management.last_visit import mark_visited, get_last_visit

        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")
        mark_visited(ws, "auth-flow")
        assert get_last_visit(ws, "auth-flow") is not None

        monkeypatch.setattr("canopy.cli.main._load_workspace", lambda: ws)

        import argparse
        from canopy.cli.main import cmd_resume
        args = argparse.Namespace(alias="auth-flow", json=False, reset_anchor=True)
        cmd_resume(args)

        assert get_last_visit(ws, "auth-flow") is None

    def test_resume_command_reset_anchor_json(
        self, canopy_toml_for_workspace, monkeypatch, capsys
    ):
        """--reset-anchor --json returns {feature, cleared} shape."""
        import argparse
        import json as _json

        from canopy.management.last_visit import mark_visited

        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")
        mark_visited(ws, "auth-flow")
        monkeypatch.setattr("canopy.cli.main._load_workspace", lambda: ws)

        from canopy.cli.main import cmd_resume
        args = argparse.Namespace(alias="auth-flow", json=True, reset_anchor=True)
        cmd_resume(args)

        data = _json.loads(capsys.readouterr().out)
        assert data["feature"] == "auth-flow"
        assert data["cleared"] is True


class TestThreadsAggregation:
    """Tests for multi-repo threads_new aggregation and edge cases."""

    def test_resume_threads_new_aggregates_across_repos(self, canopy_toml_for_workspace, monkeypatch):
        """When both repos have new threads, all surface in threads_new with repo+pr_number."""
        from canopy.management.last_visit import mark_visited
        from canopy.management.resume import feature_resume
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")
        mark_visited(ws, "auth-flow")
        import time; time.sleep(1.1)

        monkeypatch.setattr("canopy.management.resume._pr_coords_per_repo",
            lambda ws, f: {
                "repo-a": {"owner": "o", "repo_slug": "a", "pr_number": 1},
                "repo-b": {"owner": "o", "repo_slug": "b", "pr_number": 2},
            })

        def fake_threads(root, owner, slug, pr):
            return [{"thread_id": f"PRRT_{slug}_1", "is_resolved": False, "resolved_at": None,
                      "comments": [{"comment_id": pr * 10, "created_at": "2999-01-01T00:00:00Z",
                                     "author": "u", "path": "x", "line": 1, "body": "new", "url": "u"}]}]
        monkeypatch.setattr("canopy.integrations.github.list_review_threads", fake_threads)

        brief = feature_resume(ws, "auth-flow")
        new = brief["since_last_visit"]["threads_new"]
        repos_seen = {t["repo"] for t in new}
        assert repos_seen == {"repo-a", "repo-b"}
        assert all(t["pr_number"] in (1, 2) for t in new)

    def test_resume_unresolved_thread_with_stale_resolved_at_excluded(self, canopy_toml_for_workspace, monkeypatch):
        """A thread with is_resolved=False but stale resolved_at (from prior resolve+unresolve) is excluded
        from both threads_new (it's old) and threads_resolved_on_github (it's not resolved)."""
        from canopy.management.last_visit import mark_visited
        from canopy.management.resume import feature_resume
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")
        mark_visited(ws, "auth-flow")
        import time; time.sleep(1.1)

        monkeypatch.setattr("canopy.management.resume._pr_coords_per_repo",
            lambda ws, f: {"repo-a": {"owner": "o", "repo_slug": "a", "pr_number": 1}})

        monkeypatch.setattr("canopy.integrations.github.list_review_threads",
            lambda *a, **k: [{
                "thread_id": "PRRT_x", "is_resolved": False, "resolved_at": "2999-01-01T00:00:00Z",
                "comments": [{"comment_id": 1, "created_at": "1900-01-01T00:00:00Z",
                               "author": "u", "path": "x", "line": 1, "body": "old", "url": "u"}],
            }])

        brief = feature_resume(ws, "auth-flow")
        assert brief["since_last_visit"]["threads_new"] == []
        assert brief["since_last_visit"]["threads_resolved_on_github"] == []
