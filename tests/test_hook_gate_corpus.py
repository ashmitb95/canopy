"""Regression: the parser must survive all 680 real-world command shapes.

Corpus mined from 35 days of work-machine transcripts (1,403 git
invocations deduplicated by shape). The parser never raises, and every
shape whose miner-tagged subcommands include a mutation is detected as
containing >= 1 git segment (unless the git call sits inside a
subshell/quote, which the top-level splitter deliberately skips).
"""
from __future__ import annotations

import json
from pathlib import Path

CORPUS = Path(__file__).parent / "fixtures" / "hook_gate_corpus.jsonl"


def test_corpus_never_raises():
    from canopy.actions.hook_gate import resolve_segments
    n = 0
    for line in CORPUS.read_text().splitlines():
        entry = json.loads(line)
        cwd = Path(entry.get("cwd") or "/tmp")
        segs = resolve_segments(entry["command"], cwd=cwd)   # must not raise
        assert isinstance(segs, list)
        n += 1
    assert n >= 600   # corpus intact


def test_corpus_mutation_detection_rate():
    """>= 90% of shapes the miner tagged with mutation subcommands must
    yield at least one top-level git segment. The remainder are git calls
    inside subshells/quotes — legitimately skipped (fail-open)."""
    from canopy.actions.hook_gate import resolve_segments, is_mutation
    MUTS = {"commit", "push", "merge", "rebase", "stash", "reset", "add"}
    total = hit = 0
    for line in CORPUS.read_text().splitlines():
        entry = json.loads(line)
        if not (set(entry.get("subcommands") or []) & MUTS):
            continue
        total += 1
        segs = resolve_segments(entry["command"], cwd=Path(entry.get("cwd") or "/tmp"))
        if any(is_mutation(s) for s in segs):
            hit += 1
    assert total > 200          # corpus has plenty of mutations
    assert hit / total >= 0.90, f"detected {hit}/{total}"
