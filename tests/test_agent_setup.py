"""Tests for canopy.agent_setup — skill + MCP installer."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from canopy.agent_setup import (
    check_status, install_mcp, install_skill, mcp_config_path,
    setup_agent, skill_install_target,
)


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Redirect ~ to a temp dir so tests don't touch the real ~/.claude."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


# ── install_skill ────────────────────────────────────────────────────────

def test_install_skill_first_time(fake_home):
    result = install_skill()
    assert result.action == "installed"
    target = skill_install_target()
    assert target.exists()
    assert "name: using-canopy" in target.read_text()


def test_install_skill_idempotent(fake_home):
    install_skill()
    result = install_skill()
    assert result.action == "skipped"
    assert "up to date" in (result.reason or "")


def test_install_skill_skips_foreign_file(fake_home):
    """If a different SKILL.md exists at the path, leave it alone unless --reinstall."""
    target = skill_install_target()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# someone else's skill\n")
    result = install_skill()
    assert result.action == "skipped"
    assert "foreign" in (result.reason or "")
    assert target.read_text() == "# someone else's skill\n"


def test_install_skill_reinstall_overwrites_foreign(fake_home):
    target = skill_install_target()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# someone else\n")
    result = install_skill(reinstall=True)
    assert result.action == "reinstalled"
    assert "name: using-canopy" in target.read_text()


def test_install_skill_updates_outdated_canopy_skill(fake_home):
    """An older version of our own skill should be updated to current."""
    target = skill_install_target()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("---\nname: using-canopy\n---\n# old version\n")
    result = install_skill()
    assert result.action == "reinstalled"
    assert "Tool selection" in target.read_text()  # body of current skill


# ── install_mcp ──────────────────────────────────────────────────────────

def test_install_mcp_creates_new_file(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = install_mcp(workspace)
    assert result.action in ("created", "added")
    cfg = json.loads(mcp_config_path(workspace).read_text())
    assert cfg["mcpServers"]["canopy"]["command"] == "canopy-mcp"
    assert cfg["mcpServers"]["canopy"]["env"]["CANOPY_ROOT"] == str(workspace.resolve())


def test_install_mcp_merges_with_existing_servers(tmp_path):
    """If .mcp.json already has other servers, merge in canopy without overwriting."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    existing = mcp_config_path(workspace)
    existing.write_text(json.dumps({
        "mcpServers": {
            "linear": {"type": "http", "url": "https://mcp.linear.app/mcp", "oauth": True},
        }
    }))
    install_mcp(workspace)
    cfg = json.loads(existing.read_text())
    assert "linear" in cfg["mcpServers"]
    assert "canopy" in cfg["mcpServers"]


def test_install_mcp_idempotent_when_current(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    install_mcp(workspace)
    result = install_mcp(workspace)
    assert result.action == "skipped"


def test_install_mcp_updates_with_reinstall(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    existing = mcp_config_path(workspace)
    existing.write_text(json.dumps({
        "mcpServers": {
            "canopy": {"command": "canopy-mcp", "args": [],
                        "env": {"CANOPY_ROOT": "/wrong/path"}}
        }
    }))
    result = install_mcp(workspace)
    # Without --reinstall, only updates if the env doesn't match
    assert result.action == "updated"
    cfg = json.loads(existing.read_text())
    assert cfg["mcpServers"]["canopy"]["env"]["CANOPY_ROOT"] == str(workspace.resolve())


def test_install_mcp_skips_invalid_json(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    mcp_config_path(workspace).write_text("not json {")
    result = install_mcp(workspace)
    assert result.action == "skipped"
    assert "valid JSON" in (result.reason or "")


# ── check_status ─────────────────────────────────────────────────────────

def test_check_status_when_nothing_installed(fake_home, tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    status = check_status(workspace)
    assert status["skill"]["installed"] is False
    assert status["mcp"]["configured"] is False


def test_check_status_after_install(fake_home, tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    install_skill()
    install_mcp(workspace)
    status = check_status(workspace)
    assert status["skill"]["installed"] is True
    assert status["skill"]["is_canopy_skill"] is True
    assert status["skill"]["up_to_date"] is True
    assert status["mcp"]["configured"] is True


# ── setup_agent (composite) ──────────────────────────────────────────────

def test_setup_agent_does_both_by_default(fake_home, tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    result = setup_agent(workspace)
    assert "skill" in result
    assert "mcp" in result
    assert result["skill"]["action"] in ("installed", "reinstalled")
    assert result["mcp"]["action"] in ("created", "added")


def test_setup_agent_skill_only(fake_home, tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    result = setup_agent(workspace, do_mcp=False)
    assert "skill" in result
    assert "mcp" not in result


def test_setup_agent_no_workspace_skips_mcp(fake_home):
    result = setup_agent(None, do_skill=True, do_mcp=True)
    assert "skill" in result
    assert result["mcp"]["action"] == "skipped"
    assert "no workspace_root" in result["mcp"]["reason"]
