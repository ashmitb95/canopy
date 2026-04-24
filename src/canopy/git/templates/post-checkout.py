#!/usr/bin/env python3
# __CANOPY_HOOK_MARKER__ post-checkout v1
"""Canopy post-checkout hook — records HEAD state to .canopy/state/heads.json.

Installed by `canopy hooks install`. Never blocks git operations on errors.
Chains to a pre-existing post-checkout.canopy-chained if present.
"""
import fcntl
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Substituted at install time.
CANOPY_REPO = "__CANOPY_REPO__"
CANOPY_WORKSPACE_ROOT = Path("__CANOPY_WORKSPACE_ROOT__")


def _record_state() -> None:
    if len(sys.argv) < 4:
        return
    prev_sha, new_sha, is_branch_checkout = sys.argv[1], sys.argv[2], sys.argv[3]
    # Only record on branch checkouts (not file checkouts).
    if is_branch_checkout != "1":
        return

    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    if not branch or branch == "HEAD":
        return  # detached; skip

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = {"branch": branch, "sha": new_sha, "prev_sha": prev_sha, "ts": ts}

    state_dir = CANOPY_WORKSPACE_ROOT / ".canopy" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / "heads.json"
    lock_file = state_dir / "heads.json.lock"

    with open(lock_file, "w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            state = json.loads(state_file.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            state = {}
        state[CANOPY_REPO] = entry
        tmp = state_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2))
        os.replace(tmp, state_file)


def _chain_existing() -> None:
    chained = Path(__file__).parent / "post-checkout.canopy-chained"
    if chained.is_file() and os.access(chained, os.X_OK):
        os.execv(str(chained), [str(chained), *sys.argv[1:]])


if __name__ == "__main__":
    try:
        _record_state()
    except Exception:
        pass  # never block git on hook failure
    _chain_existing()
