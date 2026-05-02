"""Cross-session feature memory (M4).

Per-feature markdown file at ``<workspace>/.canopy/memory/<feature>.md``
that captures decisions, events, comment activity, and PR context across
agent sessions. Auto-read by ``canopy switch`` so a fresh agent picks up
where the last one left off.

Three top-level sections (newest content first within each):

1. **Resolutions log** — per-comment outcomes; ``✓`` resolved, ``⊙`` likely-
   resolved by classifier, ``⚠`` unresolved, ``⊘`` deferred. Never
   compacted (the always-current source of truth for review state).
2. **PR context** — one block per PR opened against the feature, plus
   per-PR update entries. Never compacted.
3. **Sessions** — per-session narrative entries. The only section that
   gets compacted on switch-away.

API contract: every record function appends a structured entry; reads
return either raw structured entries (for tests / extensions) or rendered
markdown (for the agent / dashboard). Storage is line-delimited JSON
under the hood, rendered to markdown on demand. This keeps writes O(1)
and lets the rendering layer evolve without a data migration.

File concurrency: writes use ``fcntl.flock`` with the same pattern as
``.canopy/state/heads.json`` so concurrent agents on the same feature
across worktrees don't corrupt the log.
"""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


_MEMORY_DIR = ".canopy/memory"

# Storage is JSONL; the public surface is the rendered .md. We keep both
# alongside each other so external tools can grep the markdown while the
# write path stays append-only.
_STORE_SUFFIX = ".jsonl"
_RENDER_SUFFIX = ".md"


# ── Paths ────────────────────────────────────────────────────────────────


def _memory_dir(workspace_root: Path) -> Path:
    return workspace_root / _MEMORY_DIR


def store_path(workspace_root: Path, feature: str) -> Path:
    """Append-only JSONL store for the feature's memory entries."""
    return _memory_dir(workspace_root) / f"{feature}{_STORE_SUFFIX}"


def render_path(workspace_root: Path, feature: str) -> Path:
    """Rendered markdown view written alongside the store."""
    return _memory_dir(workspace_root) / f"{feature}{_RENDER_SUFFIX}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Locking + atomic write helpers ──────────────────────────────────────


@contextmanager
def _locked_append(path: Path):
    """Append-mode file handle with an exclusive flock.

    Same pattern the post-checkout hook uses for heads.json — concurrent
    agents writing to the same feature's memory queue safely. The first
    write into the memory directory drops a ``.gitignore`` so the
    per-feature memory files don't accidentally get committed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_memory_gitignore(path.parent)
    with open(path, "a", encoding="utf-8") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            yield f
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _ensure_memory_gitignore(memory_dir: Path) -> None:
    """Drop a ``.gitignore`` that ignores everything under .canopy/memory/.

    Memory files are local working state — useful to the agent on this
    machine, not something to commit to the workspace's repos. The
    .gitignore itself stays tracked so the policy is visible in the diff.
    """
    gi = memory_dir / ".gitignore"
    if gi.exists():
        return
    gi.write_text("# Auto-written by canopy historian (M4).\n*\n!.gitignore\n")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


# ── Append + load primitives ────────────────────────────────────────────


def _append_entry(workspace_root: Path, feature: str, entry: dict[str, Any]) -> None:
    entry.setdefault("at", _now_iso())
    line = json.dumps(entry, sort_keys=True, ensure_ascii=False)
    with _locked_append(store_path(workspace_root, feature)) as f:
        f.write(line + "\n")
    # Re-render the markdown view so external readers see fresh state.
    _refresh_render(workspace_root, feature)


def _load_entries(workspace_root: Path, feature: str) -> list[dict[str, Any]]:
    path = store_path(workspace_root, feature)
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


# ── Public record API ───────────────────────────────────────────────────


def record_decision(
    workspace_root: Path, feature: str, *,
    title: str, rationale: str = "", at: str | None = None,
) -> dict[str, Any]:
    """Capture a decision the agent made (e.g. choosing one library over another).

    Decisions are deduplicated by ``title`` within the most-recent session
    so the hybrid capture mechanism (explicit tool call + Stop-hook
    tail-parse) doesn't double-log.
    """
    entry = {
        "kind": "decision", "title": title, "rationale": rationale,
        "at": at or _now_iso(), "session": _current_session_id(),
    }
    if _decision_already_logged(workspace_root, feature, title, entry["session"]):
        return {"action": "deduped", "title": title}
    _append_entry(workspace_root, feature, entry)
    return {"action": "recorded", "title": title}


def record_event(
    workspace_root: Path, feature: str, *,
    summary: str, kind: str = "event", at: str | None = None,
) -> dict[str, Any]:
    """One-line summary of a tool invocation (Edit, Bash, preflight, etc.).

    The ``kind`` field lets later renderers group events by type
    (e.g. "edited" vs "ran" vs "preflight"). Defaults to ``event``.
    """
    entry = {
        "kind": kind, "summary": summary,
        "at": at or _now_iso(), "session": _current_session_id(),
    }
    _append_entry(workspace_root, feature, entry)
    return {"action": "recorded", "summary": summary}


def record_pause(
    workspace_root: Path, feature: str, *,
    reason: str, at: str | None = None,
) -> dict[str, Any]:
    """Capture why the agent stopped — what's blocked, what's needed next."""
    entry = {
        "kind": "pause", "reason": reason,
        "at": at or _now_iso(), "session": _current_session_id(),
    }
    _append_entry(workspace_root, feature, entry)
    return {"action": "recorded"}


def record_comment_read(
    workspace_root: Path, feature: str, *,
    comment_id: str | int, author: str, path: str, line: int = 0,
    body_excerpt: str = "", url: str = "", at: str | None = None,
) -> dict[str, Any]:
    """Log that the agent read a specific comment. Deduped per-session by id."""
    cid = str(comment_id)
    if _comment_read_already_logged(workspace_root, feature, cid, _current_session_id()):
        return {"action": "deduped", "comment_id": cid}
    entry = {
        "kind": "comment_read", "comment_id": cid, "author": author,
        "path": path, "line": line, "body_excerpt": body_excerpt, "url": url,
        "at": at or _now_iso(), "session": _current_session_id(),
    }
    _append_entry(workspace_root, feature, entry)
    return {"action": "recorded", "comment_id": cid}


def record_comment_resolved(
    workspace_root: Path, feature: str, *,
    comment_id: str | int, author: str = "", path: str = "", line: int = 0,
    commit_sha: str, gist: str = "", url: str = "", at: str | None = None,
) -> dict[str, Any]:
    """Log that a comment was addressed by a specific commit."""
    entry = {
        "kind": "comment_resolved", "comment_id": str(comment_id),
        "author": author, "path": path, "line": line,
        "commit_sha": commit_sha, "gist": gist, "url": url,
        "at": at or _now_iso(), "session": _current_session_id(),
    }
    _append_entry(workspace_root, feature, entry)
    return {"action": "recorded", "comment_id": str(comment_id)}


def record_comment_deferred(
    workspace_root: Path, feature: str, *,
    comment_id: str | int, reason: str, author: str = "", path: str = "",
    line: int = 0, url: str = "", at: str | None = None,
) -> dict[str, Any]:
    """Log a comment the user / agent intentionally deferred."""
    entry = {
        "kind": "comment_deferred", "comment_id": str(comment_id),
        "reason": reason, "author": author, "path": path, "line": line,
        "url": url, "at": at or _now_iso(), "session": _current_session_id(),
    }
    _append_entry(workspace_root, feature, entry)
    return {"action": "recorded", "comment_id": str(comment_id)}


def record_classifier_resolved(
    workspace_root: Path, feature: str, *,
    threads: list[dict], at: str | None = None,
) -> dict[str, Any]:
    """Log the temporal classifier's likely-resolved set (one batch per session)."""
    if not threads:
        return {"action": "noop"}
    if _classifier_already_logged(workspace_root, feature, _current_session_id()):
        return {"action": "deduped"}
    entry = {
        "kind": "classifier_resolved", "threads": threads,
        "at": at or _now_iso(), "session": _current_session_id(),
    }
    _append_entry(workspace_root, feature, entry)
    return {"action": "recorded", "count": len(threads)}


def record_pr_context(
    workspace_root: Path, feature: str, *,
    pr_number: int, repo: str, title: str, base: str = "main",
    rationale: str = "", url: str = "", at: str | None = None,
) -> dict[str, Any]:
    """Log when a PR is opened for the feature."""
    entry = {
        "kind": "pr_context", "pr_number": pr_number, "repo": repo,
        "title": title, "base": base, "rationale": rationale, "url": url,
        "at": at or _now_iso(), "session": _current_session_id(),
    }
    _append_entry(workspace_root, feature, entry)
    return {"action": "recorded", "pr_number": pr_number}


def record_pr_update(
    workspace_root: Path, feature: str, *,
    pr_number: int, repo: str, summary: str, at: str | None = None,
) -> dict[str, Any]:
    """Log an update pushed to an existing PR."""
    entry = {
        "kind": "pr_update", "pr_number": pr_number, "repo": repo,
        "summary": summary,
        "at": at or _now_iso(), "session": _current_session_id(),
    }
    _append_entry(workspace_root, feature, entry)
    return {"action": "recorded", "pr_number": pr_number}


# ── Read API ────────────────────────────────────────────────────────────


def read(workspace_root: Path, feature: str) -> list[dict[str, Any]]:
    """Return the raw entries (oldest → newest)."""
    return _load_entries(workspace_root, feature)


def format_for_agent(workspace_root: Path, feature: str) -> str:
    """Render the memory as markdown for inclusion in switch responses.

    Returns an empty string when no memory exists yet (so callers can
    cheaply check truthiness before embedding).
    """
    entries = _load_entries(workspace_root, feature)
    if not entries:
        return ""
    return _render(feature, entries)


# ── Compaction ──────────────────────────────────────────────────────────


def compact(
    workspace_root: Path, feature: str, *, keep_sessions: int = 5,
) -> dict[str, Any]:
    """Trim the Sessions section to the most-recent ``keep_sessions``.

    v1 deliberately avoids an LLM call — it just drops session entries
    older than the cutoff. The Resolutions log + PR context entries are
    always preserved, regardless of session age. The plan reserves a
    future LLM-based summarization pass; until then this keeps the file
    bounded without losing structured state.
    """
    entries = _load_entries(workspace_root, feature)
    if not entries:
        return {"action": "noop", "reason": "no memory file"}

    sessions_seen: list[str] = []
    for e in reversed(entries):
        s = e.get("session")
        if s and s not in sessions_seen:
            sessions_seen.append(s)
        if len(sessions_seen) > keep_sessions:
            break

    if len(sessions_seen) <= keep_sessions:
        return {"action": "noop", "reason": "already within keep_sessions"}

    keep_ids = set(sessions_seen[:keep_sessions])
    structural_kinds = {
        "comment_resolved", "comment_deferred", "classifier_resolved",
        "pr_context", "pr_update",
    }
    kept = [
        e for e in entries
        if e.get("kind") in structural_kinds
        or e.get("session") in keep_ids
        or e.get("session") is None   # legacy entries without session
    ]
    dropped = len(entries) - len(kept)

    # Rewrite the JSONL store atomically.
    text = "\n".join(
        json.dumps(e, sort_keys=True, ensure_ascii=False) for e in kept
    )
    if text:
        text += "\n"
    _atomic_write(store_path(workspace_root, feature), text)
    _refresh_render(workspace_root, feature)
    return {"action": "compacted", "kept": len(kept), "dropped": dropped}


# ── Internals ───────────────────────────────────────────────────────────


def _current_session_id() -> str:
    """Stable per-process id so dedup-per-session works.

    Defaults to ``CANOPY_SESSION_ID`` when set (autopilot / external
    runners can pass a stable id across tool calls). Falls back to the
    UTC date so manual CLI / test runs still cluster sensibly.
    """
    explicit = os.environ.get("CANOPY_SESSION_ID")
    if explicit:
        return explicit
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _decision_already_logged(
    workspace_root: Path, feature: str, title: str, session: str,
) -> bool:
    for e in reversed(_load_entries(workspace_root, feature)):
        if e.get("session") != session:
            return False
        if e.get("kind") == "decision" and e.get("title") == title:
            return True
    return False


def _comment_read_already_logged(
    workspace_root: Path, feature: str, comment_id: str, session: str,
) -> bool:
    for e in reversed(_load_entries(workspace_root, feature)):
        if e.get("session") != session:
            return False
        if e.get("kind") == "comment_read" and e.get("comment_id") == comment_id:
            return True
    return False


def _classifier_already_logged(
    workspace_root: Path, feature: str, session: str,
) -> bool:
    for e in reversed(_load_entries(workspace_root, feature)):
        if e.get("session") != session:
            return False
        if e.get("kind") == "classifier_resolved":
            return True
    return False


def _refresh_render(workspace_root: Path, feature: str) -> None:
    entries = _load_entries(workspace_root, feature)
    text = _render(feature, entries) if entries else ""
    _atomic_write(render_path(workspace_root, feature), text)


# ── Markdown rendering ──────────────────────────────────────────────────


def _render(feature: str, entries: list[dict[str, Any]]) -> str:
    resolutions = _render_resolutions(entries)
    pr_context = _render_pr_context(entries)
    sessions = _render_sessions(entries)
    parts = [f"# Feature: {feature}\n"]
    parts.append("## Resolutions log\n\n" + (resolutions or "_(no comment activity yet)_\n"))
    parts.append("## PR context\n\n" + (pr_context or "_(no PRs opened yet)_\n"))
    parts.append("## Sessions (newest first)\n\n" + (sessions or "_(no sessions logged yet)_\n"))
    return "\n".join(parts)


def _render_resolutions(entries: list[dict[str, Any]]) -> str:
    """Per-comment outcomes — never compacted."""
    items: list[str] = []
    for e in entries:
        kind = e.get("kind")
        if kind == "comment_resolved":
            sha = (e.get("commit_sha") or "")[:8]
            cid = e.get("comment_id", "?")
            author = e.get("author", "?")
            file_loc = _file_loc(e)
            gist = e.get("gist", "")
            items.append(_resolution_line("✓", cid, author, file_loc, f"resolved by {sha}", gist))
        elif kind == "classifier_resolved":
            for t in e.get("threads", []):
                cid = t.get("id", t.get("comment_id", "?"))
                author = t.get("author", "?")
                file_loc = _thread_file_loc(t)
                reason = t.get("reason", "file modified since")
                items.append(_resolution_line("⊙", cid, author, file_loc, "likely-resolved by classifier", reason))
        elif kind == "comment_deferred":
            cid = e.get("comment_id", "?")
            author = e.get("author", "?")
            file_loc = _file_loc(e)
            items.append(_resolution_line("⊘", cid, author, file_loc, "DEFERRED", e.get("reason", "")))
    if not items:
        return ""
    # Newest first.
    return "\n".join(reversed(items)) + "\n"


def _render_pr_context(entries: list[dict[str, Any]]) -> str:
    """One block per PR + ordered updates."""
    by_pr: dict[tuple[str, int], dict[str, Any]] = {}
    for e in entries:
        if e.get("kind") == "pr_context":
            key = (e.get("repo", ""), e.get("pr_number", 0))
            by_pr.setdefault(key, {"context": None, "updates": []})
            by_pr[key]["context"] = e
        elif e.get("kind") == "pr_update":
            key = (e.get("repo", ""), e.get("pr_number", 0))
            by_pr.setdefault(key, {"context": None, "updates": []})
            by_pr[key]["updates"].append(e)
    if not by_pr:
        return ""

    blocks: list[str] = []
    for (repo, pr_num), data in sorted(by_pr.items(), key=lambda kv: -kv[0][1]):
        ctx = data["context"] or {}
        title = ctx.get("title", "(no title recorded)")
        opened = ctx.get("at", "")[:10]
        base = ctx.get("base", "main")
        url = ctx.get("url", "")
        rationale = ctx.get("rationale", "")
        header = f"### PR #{pr_num} — {repo} — {title}\n"
        body_lines = [f"**Opened:** {opened} against `{base}`"]
        if url:
            body_lines.append(f"**URL:** {url}")
        if rationale:
            body_lines.append(f"**Rationale:** {rationale}")
        if data["updates"]:
            body_lines.append("")
            body_lines.append("**Updates:**")
            # Newest update first.
            for u in reversed(data["updates"]):
                body_lines.append(f"- {u.get('at', '')[:10]}: {u.get('summary', '')}")
        blocks.append(header + "\n".join(body_lines) + "\n")
    return "\n".join(blocks)


def _render_sessions(entries: list[dict[str, Any]]) -> str:
    """Group by session id, newest session first, with a per-entry digest."""
    sessions: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for e in entries:
        sid = e.get("session") or "_unsessioned"
        if sid not in sessions:
            sessions[sid] = []
            order.append(sid)
        sessions[sid].append(e)
    if not sessions:
        return ""

    blocks: list[str] = []
    for sid in reversed(order):
        block = [f"### {sid}"]
        for e in sessions[sid]:
            block.append(_session_line(e))
        blocks.append("\n".join(block) + "\n")
    return "\n".join(blocks)


# ── Tiny render helpers ─────────────────────────────────────────────────


def _resolution_line(
    glyph: str, cid: Any, author: str, file_loc: str, status: str, gist: str,
) -> str:
    head = f"- {glyph} comment {cid} ({author}{file_loc}) {status}"
    if gist:
        return head + f"\n  {gist}"
    return head


def _file_loc(entry: dict[str, Any]) -> str:
    path = entry.get("path", "")
    line = entry.get("line", 0)
    if not path:
        return ""
    if line:
        return f", {path}:{line}"
    return f", {path}"


def _thread_file_loc(thread: dict[str, Any]) -> str:
    return _file_loc(thread)


def _session_line(entry: dict[str, Any]) -> str:
    kind = entry.get("kind", "")
    when = entry.get("at", "")[11:19]   # HH:MM:SS slice of ISO
    if kind == "decision":
        title = entry.get("title", "")
        rationale = entry.get("rationale", "")
        if rationale:
            return f"- [{when}] **decision:** {title} — {rationale}"
        return f"- [{when}] **decision:** {title}"
    if kind == "pause":
        return f"- [{when}] **pause:** {entry.get('reason', '')}"
    if kind == "comment_read":
        cid = entry.get("comment_id", "?")
        author = entry.get("author", "?")
        path = entry.get("path", "")
        line = entry.get("line", 0)
        loc = f" {path}:{line}" if path else ""
        excerpt = entry.get("body_excerpt", "")
        suffix = f" — {excerpt}" if excerpt else ""
        return f"- [{when}] read comment {cid} ({author}{loc}){suffix}"
    if kind == "comment_resolved":
        cid = entry.get("comment_id", "?")
        sha = (entry.get("commit_sha") or "")[:8]
        return f"- [{when}] resolved comment {cid} → {sha}"
    if kind == "comment_deferred":
        cid = entry.get("comment_id", "?")
        return f"- [{when}] deferred comment {cid}: {entry.get('reason', '')}"
    if kind == "classifier_resolved":
        n = len(entry.get("threads", []))
        return f"- [{when}] classifier marked {n} thread(s) likely-resolved"
    if kind == "pr_context":
        return f"- [{when}] opened PR #{entry.get('pr_number', '?')} ({entry.get('repo', '')})"
    if kind == "pr_update":
        return f"- [{when}] PR #{entry.get('pr_number', '?')}: {entry.get('summary', '')}"
    if kind == "event":
        return f"- [{when}] {entry.get('summary', '')}"
    return f"- [{when}] {kind}: {entry.get('summary', entry.get('title', ''))}"
