"""Agent setup — install bundled skills and wire canopy MCP into a workspace.

Skills live at ``skills/<name>/SKILL.md`` inside this package and are copied
into ``~/.claude/skills/<name>/SKILL.md`` so any Claude Code session knows
to use them. The MCP config (``.mcp.json`` at the workspace root) registers
canopy-mcp as an MCP server with ``CANOPY_ROOT`` pointing at the workspace.

Both pieces are independent — install skills, MCP, both, or neither.
``setup_agent`` returns a structured report describing what was done so
callers can render it.

The bundled skill set today: ``using-canopy`` (always installed by default)
and ``augment-canopy`` (opt-in via ``--skill augment-canopy``).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

_SKILLS_DIR = Path(__file__).parent / "skills"

DEFAULT_SKILL = "using-canopy"


def _user_skills_dir() -> Path:
    """Resolved at call time so tests that monkeypatch ``HOME`` work."""
    return Path.home() / ".claude" / "skills"

# Backward-compat alias — doctor.py imports this directly. Points at the
# bundled source for the default skill.
_SKILL_SOURCE = _SKILLS_DIR / DEFAULT_SKILL / "SKILL.md"


def available_skills() -> tuple[str, ...]:
    """Return the names of all bundled skills (directories under ``skills/``)."""
    if not _SKILLS_DIR.exists():
        return ()
    return tuple(sorted(
        d.name for d in _SKILLS_DIR.iterdir()
        if d.is_dir() and (d / "SKILL.md").exists()
    ))


def skill_source(name: str = DEFAULT_SKILL) -> Path:
    """Path to the bundled SKILL.md for the named skill."""
    return _SKILLS_DIR / name / "SKILL.md"


def skill_install_target(name: str = DEFAULT_SKILL) -> Path:
    """Default install location for the named skill."""
    return _user_skills_dir() / name / "SKILL.md"


def mcp_config_path(workspace_root: Path) -> Path:
    """Default location for the workspace's MCP config."""
    return workspace_root / ".mcp.json"


@dataclass
class SkillResult:
    action: str        # "installed", "reinstalled", "skipped"
    path: str
    reason: str | None = None
    name: str = DEFAULT_SKILL


@dataclass
class McpResult:
    action: str        # "added", "updated", "skipped", "created"
    path: str
    reason: str | None = None


def install_skill(name: str = DEFAULT_SKILL, *, reinstall: bool = False) -> SkillResult:
    """Install the named skill into ~/.claude/skills/<name>/SKILL.md.

    If a skill file already exists and isn't ours, leaves it alone unless
    ``reinstall=True``. Detection: the source skill file's full body is
    written verbatim, so we can byte-compare to know if it's ours.

    Raises ``FileNotFoundError`` if the named skill isn't bundled.
    """
    source = skill_source(name)
    if not source.exists():
        raise FileNotFoundError(
            f"No bundled skill named '{name}'. Available: {', '.join(available_skills()) or '(none)'}",
        )
    target = skill_install_target(name)
    source_text = source.read_text()

    if target.exists():
        existing = target.read_text()
        if existing == source_text:
            return SkillResult(
                action="skipped", path=str(target), name=name,
                reason="already up to date",
            )
        if not reinstall and f"name: {name}" not in existing:
            return SkillResult(
                action="skipped", path=str(target), name=name,
                reason="foreign skill present; use --reinstall to overwrite",
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source_text)
        return SkillResult(action="reinstalled", path=str(target), name=name)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source_text)
    return SkillResult(action="installed", path=str(target), name=name)


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
    """Report what's installed without changing anything.

    Returns ``{skill, skills, mcp}``:

    - ``skill`` — the default ``using-canopy`` entry (kept for
      backward-compat with existing callers / dashboard).
    - ``skills`` — every bundled skill's install state, including
      opt-ins like ``augment-canopy`` once they're installed (M4
      revealed that ``--check`` only reported the default; F-9).
    - ``mcp`` — the workspace's ``.mcp.json`` canopy entry state.
    """
    skill_state = check_skill_status(DEFAULT_SKILL)
    skills_state = [check_skill_status(name) for name in available_skills()]

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

    return {"skill": skill_state, "skills": skills_state, "mcp": mcp_state}


def check_skill_status(name: str) -> dict:
    """Report install state for a single named skill."""
    source = skill_source(name)
    target = skill_install_target(name)
    state = {
        "name": name,
        "path": str(target),
        "installed": target.exists(),
        "is_canopy_skill": False,
        "up_to_date": False,
    }
    if target.exists() and source.exists():
        existing = target.read_text()
        state["is_canopy_skill"] = f"name: {name}" in existing
        state["up_to_date"] = existing == source.read_text()
    return state


def setup_agent(
    workspace_root: Path | None,
    *,
    skills: tuple[str, ...] = (DEFAULT_SKILL,),
    do_mcp: bool = True,
    reinstall: bool = False,
    do_skill: bool | None = None,
) -> dict:
    """Install one or more skills + (optionally) wire MCP.

    ``skills`` is the tuple of bundled skill names to install. Defaults to
    just ``using-canopy``. Pass ``()`` to skip all skill installs.

    ``do_skill`` is a backward-compat alias — when ``do_skill=False`` is
    passed, no skills are installed regardless of the ``skills`` arg.
    """
    if do_skill is False:
        skills = ()

    out: dict = {}
    if skills:
        results = []
        for name in skills:
            try:
                results.append(asdict(install_skill(name, reinstall=reinstall)))
            except FileNotFoundError as e:
                results.append({
                    "action": "skipped",
                    "path": str(skill_install_target(name)),
                    "name": name,
                    "reason": str(e),
                })
        # Preserve legacy single-skill report at "skill" for callers that
        # only know about the default skill.
        default = next(
            (r for r in results if r.get("name") == DEFAULT_SKILL),
            results[0] if results else None,
        )
        if default is not None:
            out["skill"] = default
        out["skills"] = results

    if do_mcp:
        if workspace_root is None:
            out["mcp"] = {
                "action": "skipped", "path": "",
                "reason": "no workspace_root (run from inside a canopy workspace)",
            }
        else:
            out["mcp"] = asdict(install_mcp(workspace_root, reinstall=reinstall))
    return out
