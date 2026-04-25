"""
Canopy MCP Client — call tools on external MCP servers.

Two transports supported:

1. **stdio** (subprocess) — for local npm/python MCP servers::

    {
        "github": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
            "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_..."}
        }
    }

2. **HTTP (streamable)** — for hosted MCP servers like Linear's. Set
   ``"type": "http"`` (or just include ``"url"``); pass headers for
   token-based auth, or ``"oauth": true`` for browser-based OAuth flow
   with token caching::

    {
        "linear": {
            "type": "http",
            "url": "https://mcp.linear.app/mcp",
            "oauth": true
        }
    }

Configs live in ``.canopy/mcps.json`` (canopy-specific) or ``.mcp.json``
(shared with Claude Code et al.); canopy merges with .canopy taking
precedence.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any


class McpClientError(Exception):
    """An MCP client operation failed."""


def _is_http_config(server_config: dict) -> bool:
    """True if the config describes an HTTP-transport MCP server."""
    return (
        server_config.get("type") in {"http", "streamable-http", "sse"}
        or bool(server_config.get("url"))
    )


def _load_mcp_configs(workspace_root: Path) -> dict[str, dict]:
    """Load MCP server configs.

    Reads two sources, merging with .canopy/mcps.json taking precedence:

    1. ``.mcp.json`` at workspace root — the Claude Code / portable
       convention. Entries live under a top-level ``mcpServers`` key.
    2. ``.canopy/mcps.json`` — canopy's own flat format. Overrides
       anything in .mcp.json on key collision so users can customize
       per-server configs without editing the shared file.
    """
    configs: dict[str, dict] = {}

    shared_path = workspace_root / ".mcp.json"
    if shared_path.exists():
        try:
            shared = json.loads(shared_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            raise McpClientError(f"Failed to read {shared_path}: {e}")
        servers = shared.get("mcpServers") if isinstance(shared, dict) else None
        if isinstance(servers, dict):
            for name, cfg in servers.items():
                if isinstance(cfg, dict):
                    configs[name] = cfg

    canopy_path = workspace_root / ".canopy" / "mcps.json"
    if canopy_path.exists():
        try:
            canopy_cfg = json.loads(canopy_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            raise McpClientError(f"Failed to read {canopy_path}: {e}")
        if isinstance(canopy_cfg, dict):
            for name, cfg in canopy_cfg.items():
                if isinstance(cfg, dict):
                    configs[name] = cfg

    return configs


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
    server_name: str | None = None,
) -> Any:
    """Connect to an MCP server, call a tool, and return the result.

    Dispatches to stdio or HTTP transport based on the config shape.
    """
    if _is_http_config(server_config):
        return await _http_call(
            server_config, "call_tool", tool_name=tool_name,
            arguments=arguments or {}, server_name=server_name,
        )
    return await _stdio_call(
        server_config, "call_tool", tool_name=tool_name,
        arguments=arguments or {},
    )


async def _stdio_call(server_config: dict, op: str, **kwargs) -> Any:
    """Spawn a stdio MCP server and run one operation."""
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
            return await _run_op(session, op, **kwargs)


async def _http_call(
    server_config: dict, op: str, *,
    server_name: str | None = None, **kwargs,
) -> Any:
    """Connect to an HTTP MCP server (streamable HTTP) and run one operation.

    Auth handling:
      - ``headers`` (dict) on config — passed through (e.g. ``Authorization: Bearer ...``)
      - ``oauth: true`` on config — uses OAuthClientProvider with token cache at
        ``~/.canopy/mcp-tokens/<server_name>.json``. First call opens a browser
        for the OAuth flow; cached token is reused after.
    """
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    url = server_config["url"]
    headers = dict(server_config.get("headers") or {})
    auth = None
    if server_config.get("oauth"):
        auth = _make_oauth_provider(server_name or "default", url)

    async with streamablehttp_client(url, headers=headers or None, auth=auth) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await _run_op(session, op, **kwargs)


async def _run_op(session, op: str, **kwargs) -> Any:
    if op == "call_tool":
        return await session.call_tool(kwargs["tool_name"], kwargs.get("arguments") or {})
    if op == "list_tools":
        return await session.list_tools()
    raise McpClientError(f"unknown MCP op: {op}")


def _make_oauth_provider(server_name: str, server_url: str):
    """Build an OAuthClientProvider with on-disk token caching.

    Imported lazily so canopy doesn't require the auth dependency tree
    when only stdio servers are used.
    """
    from mcp.client.auth import OAuthClientProvider, TokenStorage
    from mcp.shared.auth import OAuthClientMetadata, OAuthClientInformationFull, OAuthToken

    cache_dir = Path.home() / ".canopy" / "mcp-tokens"
    cache_dir.mkdir(parents=True, exist_ok=True)
    token_path = cache_dir / f"{server_name}.tokens.json"
    client_info_path = cache_dir / f"{server_name}.client.json"

    class FileTokenStorage(TokenStorage):
        async def get_tokens(self) -> OAuthToken | None:
            if not token_path.exists():
                return None
            data = json.loads(token_path.read_text())
            return OAuthToken(**data)

        async def set_tokens(self, tokens: OAuthToken) -> None:
            token_path.write_text(tokens.model_dump_json(indent=2))

        async def get_client_info(self) -> OAuthClientInformationFull | None:
            if not client_info_path.exists():
                return None
            return OAuthClientInformationFull(**json.loads(client_info_path.read_text()))

        async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
            client_info_path.write_text(client_info.model_dump_json(indent=2))

    metadata = OAuthClientMetadata(
        client_name="canopy",
        redirect_uris=["http://localhost:33418/callback"],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
    )

    async def redirect_handler(authorization_url: str) -> None:
        """Open the user's browser to the OAuth authorization URL."""
        import webbrowser
        print(f"\n  → Opening browser for {server_name} OAuth: {authorization_url}\n")
        webbrowser.open(authorization_url)

    async def callback_handler() -> tuple[str, str | None]:
        """Run a one-shot HTTP server on localhost:33418 to catch the OAuth redirect."""
        import http.server
        import socketserver
        import urllib.parse

        captured: dict[str, str] = {}

        class CallbackHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed.query)
                captured["code"] = (params.get("code") or [""])[0]
                captured["state"] = (params.get("state") or [""])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<html><body style='font-family:sans-serif;padding:2em'>"
                    b"<h2>Canopy: authorization received</h2>"
                    b"<p>You can close this tab.</p>"
                    b"</body></html>"
                )

            def log_message(self, format, *args):
                pass  # silence

        loop = asyncio.get_event_loop()

        def _serve():
            with socketserver.TCPServer(("localhost", 33418), CallbackHandler) as httpd:
                httpd.handle_request()

        await loop.run_in_executor(None, _serve)
        return captured.get("code", ""), captured.get("state") or None

    return OAuthClientProvider(
        server_url=server_url,
        client_metadata=metadata,
        storage=FileTokenStorage(),
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )


def call_tool(
    server_config: dict,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    timeout: float = 30.0,
    server_name: str | None = None,
) -> Any:
    """Sync wrapper — connect to MCP server, call tool, return result.

    Dispatches to stdio or HTTP based on config shape (see module docstring).
    ``server_name`` is used to scope OAuth token cache when the config is
    HTTP+oauth; pass it from the caller (it's the key in mcps.json).
    """
    return _run_sync(
        _call_tool_async(server_config, tool_name, arguments, timeout, server_name),
        timeout=timeout,
        what=f"call_tool({tool_name})",
    )


def list_tools(
    server_config: dict, timeout: float = 15.0, server_name: str | None = None,
) -> list[dict]:
    """List available tools on an MCP server (stdio or HTTP)."""
    async def _list():
        if _is_http_config(server_config):
            tools_result = await _http_call(
                server_config, "list_tools", server_name=server_name,
            )
        else:
            tools_result = await _stdio_call(server_config, "list_tools")
        return [
            {"name": t.name, "description": t.description or ""}
            for t in tools_result.tools
        ]

    return _run_sync(_list(), timeout=timeout, what="list_tools")


def _run_sync(coro, *, timeout: float, what: str) -> Any:
    """Run an async coroutine, handling the case where we're already inside a loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    try:
        if loop and loop.is_running():
            # Inside an existing loop (e.g., the canopy MCP server host).
            # Run in a separate thread with a fresh loop.
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result(timeout=timeout)
        return asyncio.run(coro)
    except Exception as e:
        raise McpClientError(f"MCP {what} failed: {e}") from e
