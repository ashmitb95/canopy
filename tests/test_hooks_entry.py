"""Tests for the hook console-script shims (hooks_entry).

These run the shim in a REAL subprocess to lock in the fail-open exit-code
contract, stderr routing, and — critically — that the gate path never
writes to stdout (stdout is shown to the model in transcript mode).
"""
from __future__ import annotations

import json
import subprocess
import sys


def _run_gate(payload_text: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c",
         "from canopy.hooks_entry import gate_main; gate_main()"],
        input=payload_text, capture_output=True, text=True,
    )


def test_gate_shim_garbage_stdin_allows():
    p = _run_gate("not json at all")
    assert p.returncode == 0
    assert p.stdout == ""


def test_gate_shim_empty_stdin_allows():
    p = _run_gate("")
    assert p.returncode == 0
    assert p.stdout == ""


def test_gate_shim_non_bash_tool_allows():
    p = _run_gate(json.dumps({
        "tool_name": "Edit", "cwd": "/tmp",
        "tool_input": {"command": "git push"},
    }))
    assert p.returncode == 0
    assert p.stdout == ""


def test_gate_shim_outside_workspace_allows(tmp_path):
    p = _run_gate(json.dumps({
        "tool_name": "Bash", "cwd": str(tmp_path),
        "tool_input": {"command": "git commit -m x"},
    }))
    assert p.returncode == 0
    assert p.stdout == ""


def test_gate_shim_blocks_with_stderr_only(workspace_with_canonical_only):
    ws = workspace_with_canonical_only
    p = _run_gate(json.dumps({
        "tool_name": "Bash", "cwd": str(ws.config.root),
        "tool_input": {"command": 'git commit -m "x"'},
    }))
    assert p.returncode == 2
    assert "canopy: blocked" in p.stderr
    assert p.stdout == ""      # NEVER pollute stdout on the gate path
