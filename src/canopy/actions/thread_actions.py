"""Thread action wrappers — resolve, reply, unresolve a GitHub review thread.

Each wrapper calls the GitHub integration and records the event locally in
``.canopy/state/thread_resolutions.json`` so the resume brief can attribute
"resolved by canopy" vs "resolved on GitHub directly".
"""
from __future__ import annotations

from ..workspace.workspace import Workspace
from .errors import BlockerError
from . import thread_resolutions as tr


def _validate_thread_id(thread_id: str) -> None:
    if not thread_id.startswith("PRRT_"):
        raise BlockerError(
            code="invalid_thread_id",
            what=f"thread_id must start with 'PRRT_'; got {thread_id!r}",
        )


def resolve_thread(
    workspace: Workspace,
    thread_id: str,
    *,
    feature: str,
    via_command: str = "resolve",
    via_commit_sha: str | None = None,
) -> dict:
    """Resolve a GitHub PR review thread and record it locally.

    Steps:
    1. Validate thread_id format.
    2. Call the GitHub GraphQL mutation.
    3. Log the resolution to ``.canopy/state/thread_resolutions.json``.
    4. Return the combined result.

    Raises:
        BlockerError: if ``thread_id`` does not start with ``PRRT_``.
    """
    from ..integrations import github as gh

    _validate_thread_id(thread_id)
    gh_result = gh.resolve_thread(workspace.config.root, thread_id)
    log_entry = tr.record(
        workspace.config.root,
        thread_id=thread_id,
        feature=feature,
        via_command=via_command,
        via_commit_sha=via_commit_sha,
    )
    return {**gh_result, "logged": log_entry}


def reply_to_thread(
    workspace: Workspace,
    thread_id: str,
    body: str,
    *,
    feature: str,
    resolve_after: bool = False,
) -> dict:
    """Post a reply to a GitHub PR review thread, optionally resolving it.

    Steps:
    1. Validate thread_id format.
    2. Post the reply via the GitHub GraphQL mutation.
    3. If ``resolve_after`` is True, resolve the thread and include the result.

    Returns a dict with ``posted`` and optionally ``resolved`` keys.

    Raises:
        BlockerError: if ``thread_id`` does not start with ``PRRT_``.
    """
    from ..integrations import github as gh

    _validate_thread_id(thread_id)
    posted = gh.reply_to_thread(workspace.config.root, thread_id, body)
    result: dict = {"posted": posted}
    if resolve_after:
        resolved = resolve_thread(
            workspace, thread_id, feature=feature, via_command="reply_resolve",
        )
        result["resolved"] = resolved
    return result
