"""Tests for hook installation into <workspace>/.claude/settings.json."""
from __future__ import annotations

import json


def test_install_into_empty_workspace(tmp_path):
    from canopy.agent_setup import install_hooks
    result = install_hooks(tmp_path)
    assert result["action"] == "added"
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    pre = settings["hooks"]["PreToolUse"]
    assert pre[0]["matcher"] == "Bash"
    assert pre[0]["hooks"][0]["command"] == "canopy-hook-gate"
    session = settings["hooks"]["SessionStart"]
    assert session[0]["hooks"][0]["command"] == "canopy-hook-context"


def test_install_preserves_existing_settings(tmp_path):
    from canopy.agent_setup import install_hooks
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(json.dumps({
        "permissions": {"allow": ["Bash(ls:*)"]},
        "hooks": {"PreToolUse": [
            {"matcher": "Bash",
             "hooks": [{"type": "command", "command": "my-other-hook"}]},
        ]},
    }))
    install_hooks(tmp_path)
    settings = json.loads((claude_dir / "settings.json").read_text())
    assert settings["permissions"] == {"allow": ["Bash(ls:*)"]}
    commands = [h["hooks"][0]["command"] for h in settings["hooks"]["PreToolUse"]]
    assert "my-other-hook" in commands and "canopy-hook-gate" in commands


def test_install_is_idempotent(tmp_path):
    from canopy.agent_setup import install_hooks
    install_hooks(tmp_path)
    result = install_hooks(tmp_path)
    assert result["action"] == "unchanged"
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    gate_entries = [h for h in settings["hooks"]["PreToolUse"]
                    if h["hooks"][0]["command"] == "canopy-hook-gate"]
    assert len(gate_entries) == 1


def test_install_refuses_invalid_json(tmp_path):
    from canopy.agent_setup import install_hooks
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text("{not json")
    result = install_hooks(tmp_path)
    assert result["action"] == "skipped"
    assert (claude_dir / "settings.json").read_text() == "{not json"  # untouched
