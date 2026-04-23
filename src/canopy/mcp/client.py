"""
Canopy MCP Client — call tools on external MCP servers.

Canopy can act as an MCP client, spawning configured MCP servers
(like Linear, GitHub, etc.) and calling their tools. This enables
workflows like "create a worktree linked to a Linear issue" without
adding direct API dependencies.

MCP server configs live in .canopy/mcps.json:

    {
        "linear": {
            "command": "npx",
            "args": ["-y", "@anthropic/linear-mcp"],
            "env": {"LINEAR_API_KEY": "lin_api_..."}
        }
    }
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any


class McpClientError(Exception):
    """An MCP client operation failed."""


def _load_mcp_configs(workspace_root: Path) -> dict[str, dict]:
    """Load MCP server configs from .canopy/mcps.json."""
    config_path = workspace_root / ".canopy" / "mcps.json"
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        raise McpClientError(f"Failed to read {config_path}: {e}")


def get_mcp_config(workspace_root: Path, server_name: str) -> dict | None:
    """Get config for a named MCP server, or None if not configured."""
    configs = _load_mcp_configs(workspace_root)
    return configs.get(server_name)


def is_mcp_configured(workspace_root: Path, server_name: str) -> bool:
    """Check if a named MCP server is configured."""
    return get_mcp_config(workspace_root, server_name) is not None


async def _call_tool_async(
    server_config: dict,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> Any:
    """Spawn an MCP server, call a tool, and return the result.

    Args:
        server_config: Dict with "command", "args", "env" keys.
        tool_name: Name of the MCP tool to call.
        arguments: Tool arguments.
        timeout: Timeout in seconds for the entire operation.

    Returns:
        The tool result content (list of content blocks).
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    # Merge env: start with current env, overlay config env
    env = dict(os.environ)
    if server_config.get("env"):
        env.update(server_config["env"])

    server_params = StdioServerParameters(
        command=server_config["command"],
        args=server_config.get("args", []),
        env=env,
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments or {})
            return result


def call_tool(
    server_config: dict,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> Any:
    """Synchronous wrapper — spawn MCP server, call tool, return result.

    This is the main entry point for non-async code (CLI, coordinator).

    Args:
        server_config: Dict with "command", "args", "env" keys.
        tool_name: Name of the MCP tool to call.
        arguments: Tool arguments.
        timeout: Timeout in seconds.

    Returns:
        The tool result content.

    Raises:
        McpClientError: On connection or tool call failure.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    try:
        if loop and loop.is_running():
            # We're inside an existing event loop (e.g., MCP server context).
            # Create a new loop in a thread to avoid nested loop issues.
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    asyncio.run,
                    _call_tool_async(server_config, tool_name, arguments, timeout),
                )
                return future.result(timeout=timeout)
        else:
            return asyncio.run(
                _call_tool_async(server_config, tool_name, arguments, timeout)
            )
    except Exception as e:
        raise McpClientError(f"MCP call failed ({tool_name}): {e}") from e


def list_tools(server_config: dict, timeout: float = 15.0) -> list[dict]:
    """List available tools on an MCP server.

    Useful for discovery — see what tools a configured server exposes.
    """
    async def _list():
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        env = dict(os.environ)
        if server_config.get("env"):
            env.update(server_config["env"])

        server_params = StdioServerParameters(
            command=server_config["command"],
            args=server_config.get("args", []),
            env=env,
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools_result = await session.list_tools()
                return [
                    {
                        "name": t.name,
                        "description": t.description or "",
                    }
                    for t in tools_result.tools
                ]

    try:
        return asyncio.run(_list())
    except Exception as e:
        raise McpClientError(f"Failed to list tools: {e}") from e
