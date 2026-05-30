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
        """T6 stubs: all since_last_visit containers are empty (T7+ fills them)."""
        ws = _load_workspace(canopy_toml_for_workspace)
        _make_canonical(ws, "auth-flow")
        # Pre-seed a visit so _populate_since is invoked.
        lv.mark_visited(ws, "auth-flow")
        brief = feature_resume(ws, "auth-flow")

        s = brief["since_last_visit"]
        assert s["commits"] == {}
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
