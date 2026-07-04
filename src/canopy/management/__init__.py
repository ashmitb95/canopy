"""canopy.management — quarantined human-management surface.

Modules here are removed from the agent MCP surface and CLI. They stay
intact and importable; a future surface (dashboard rebuild or a separate
canopy-management package) may re-expose them. Nothing under
canopy.actions/features/agent (the agent-core) may import from here — see
tests/test_import_boundary.py.
"""
