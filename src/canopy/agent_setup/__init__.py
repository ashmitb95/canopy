"""Agent setup — install the using-canopy skill and wire canopy MCP into the workspace.

The skill (``skill.md`` in this package) goes into ``~/.claude/skills/using-canopy/SKILL.md``
so any Claude Code session knows to prefer canopy MCP tools over raw git/gh/bash.
The MCP config (``.mcp.json`` at the workspace root) registers canopy-mcp as an
MCP server with ``CANOPY_ROOT`` pointing at the workspace.

Both pieces are independent — install one, both, or neither. ``setup_agent``
returns a structured report describing what was done so callers can render it.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, asdict
from pathlib import Path

_SKILL_NAME = "using-canopy"
_SKILL_SOURCE = Path(__file__).parent / "skill.md"


def skill_install_target() -> Path:
    """Default location for the user's skill install."""
    return Path.home() / ".claude" / "skills" / _SKILL_NAME / "SKILL.md"


def mcp_config_path(workspace_root: Path) -> Path:
    """Default location for the workspace's MCP config."""
    return workspace_root / ".mcp.json"


@dataclass
class SkillResult:
    action: str        # "installed", "reinstalled", "skipped"
    path: str
    reason: str | None = None


@dataclass
class McpResult:
    action: str        # "added", "updated", "skipped", "created"
    path: str
    reason: str | None = None


def install_skill(*, reinstall: bool = False) -> SkillResult:
    """Install the using-canopy skill into ~/.claude/skills/.

    If a skill file already exists and isn't ours, leaves it alone unless
    ``reinstall=True``. Detection: the source skill file's full body is
    written verbatim, so we can byte-compare to know if it's ours.
    """
    target = skill_install_target()
    source_text = _SKILL_SOURCE.read_text()

    if target.exists():
        existing = target.read_text()
        if existing == source_text:
            return SkillResult(action="skipped", path=str(target),
                                reason="already up to date")
        if not reinstall and "name: using-canopy" not in existing:
            return SkillResult(action="skipped", path=str(target),
                                reason="foreign skill present; use --reinstall to overwrite")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source_text)
        return SkillResult(action="reinstalled", path=str(target))

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source_text)
    return SkillResult(action="installed", path=str(target))


def install_mcp(workspace_root: Path, *, reinstall: bool = False) -> McpResult:
    """Add (or update) a 'canopy' entry in the workspace's .mcp.json.

    Merges with any existing ``mcpServers`` block. If a 'canopy' entry
    already exists with the right shape, leaves it alone unless
    ``reinstall=True``.
    """
    workspace_root = workspace_root.resolve()
    target = mcp_config_path(workspace_root)
    desired = {
        "command": "canopy-mcp",
        "args": [],
        "env": {"CANOPY_ROOT": str(workspace_root)},
    }

    config: dict
    created = False
    if target.exists():
        try:
            config = json.loads(target.read_text())
        except json.JSONDecodeError:
            return McpResult(action="skipped", path=str(target),
                              reason="existing .mcp.json is not valid JSON; refusing to overwrite")
        if not isinstance(config, dict):
            return McpResult(action="skipped", path=str(target),
                              reason="existing .mcp.json root is not an object")
    else:
        config = {}
        created = True

    servers = config.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        return McpResult(action="skipped", path=str(target),
                          reason="existing mcpServers block is not an object")

    if "canopy" in servers and not reinstall:
        existing = servers["canopy"]
        if (isinstance(existing, dict)
                and existing.get("command") == "canopy-mcp"
                and (existing.get("env") or {}).get("CANOPY_ROOT") == desired["env"]["CANOPY_ROOT"]):
            return McpResult(action="skipped", path=str(target),
                              reason="canopy entry already present and current")

    servers["canopy"] = desired
    target.write_text(json.dumps(config, indent=2) + "\n")
    return McpResult(
        action=("created" if created else ("added" if "canopy" not in (servers or {}) else "updated")),
        path=str(target),
    )


def check_status(workspace_root: Path) -> dict:
    """Report what's installed without changing anything."""
    target = skill_install_target()
    skill_state = {
        "path": str(target),
        "installed": target.exists(),
        "is_canopy_skill": False,
        "up_to_date": False,
    }
    if target.exists():
        existing = target.read_text()
        skill_state["is_canopy_skill"] = "name: using-canopy" in existing
        skill_state["up_to_date"] = existing == _SKILL_SOURCE.read_text()

    mcp_target = mcp_config_path(workspace_root)
    mcp_state = {"path": str(mcp_target), "configured": False}
    if mcp_target.exists():
        try:
            cfg = json.loads(mcp_target.read_text())
            servers = (cfg.get("mcpServers") if isinstance(cfg, dict) else {}) or {}
            entry = servers.get("canopy") if isinstance(servers, dict) else None
            mcp_state["configured"] = bool(
                isinstance(entry, dict) and entry.get("command") == "canopy-mcp"
            )
            mcp_state["env"] = (entry or {}).get("env", {}) if isinstance(entry, dict) else {}
        except json.JSONDecodeError:
            mcp_state["error"] = "invalid JSON"

    return {"skill": skill_state, "mcp": mcp_state}


def setup_agent(
    workspace_root: Path | None,
    *,
    do_skill: bool = True,
    do_mcp: bool = True,
    reinstall: bool = False,
) -> dict:
    """Install both pieces by default. Returns ``{skill, mcp}`` results."""
    out: dict = {}
    if do_skill:
        out["skill"] = asdict(install_skill(reinstall=reinstall))
    if do_mcp:
        if workspace_root is None:
            out["mcp"] = {
                "action": "skipped", "path": "",
                "reason": "no workspace_root (run from inside a canopy workspace)",
            }
        else:
            out["mcp"] = asdict(install_mcp(workspace_root, reinstall=reinstall))
    return out
