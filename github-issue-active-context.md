# GitHub Issue: Active Feature Context

**Title:** `canopy switch` should set active context so subsequent commands don't need the feature name

**Labels:** `enhancement`, `ux`

---

## Problem

After running `canopy switch doc-3028`, every subsequent command still requires the feature name:

```bash
canopy switch doc-3028      # switch context
canopy code doc-3028        # why do I need to type this again?
canopy fork doc-3028        # and again?
canopy preflight            # this one works (context detection from cwd) but only if you cd first
```

Canopy already has context detection (`workspace/context.py`) that works when you're physically inside a worktree directory. But `canopy switch` doesn't change your cwd — it just checks out branches. So you're left at the workspace root with no implicit context, and every command needs the feature name repeated.

## Proposal

Introduce an **active feature** that `canopy switch` sets automatically. Commands that accept a feature name should fall back to the active feature when none is provided.

### Implementation

1. **Store active feature** in `.canopy/active` (plain text file, just the feature name). Simple, no JSON overhead, easy to `cat`.

2. **`canopy switch <feature>`** writes the feature name to `.canopy/active` after switching.

3. **Resolution order** for commands that accept a feature target (`code`, `cursor`, `fork`, `done`, `review`, `feature status`, `feature diff`, etc.):
   - Explicit argument → use it
   - No argument → read `.canopy/active` → use it
   - No argument, no active feature → error with helpful message

4. **`canopy switch` with no args** could show the current active feature (or clear it).

5. **`canopy done <feature>`** should clear `.canopy/active` if the completed feature was the active one.

6. **`canopy worktree` dashboard** could highlight the active feature.

### Files to change

- **`workspace/context.py`** — add `get_active_feature()` / `set_active_feature()` helpers that read/write `.canopy/active`
- **`features/coordinator.py`** — `switch()` calls `set_active_feature()` after checkout; `done()` clears if active
- **`cli/main.py`** — commands that take a `target` argument: make it optional, fall back to active feature via `get_active_feature()`
  - `cmd_code`, `cmd_cursor`, `cmd_fork` — target becomes optional
  - `cmd_switch` — writes active after switch
  - `cmd_done` — clears active if matching
  - `cmd_feature_status`, `cmd_feature_diff`, `cmd_feature_switch` — fall back to active
  - `cmd_review` — fall back to active
- **`mcp/server.py`** — MCP tools that accept a feature name: fall back to active feature when not provided
- **Tests** — new test file `tests/test_active_context.py`:
  - switch sets active
  - commands resolve active when no arg given
  - done clears active
  - explicit arg overrides active
  - no active + no arg = clear error

### UX detail

When a command resolves via active context, show it:
```
  (active: doc-3028 → doc-3028-document-summarizer)
```

Same pattern as alias resolution — user always sees what resolved.

### Edge cases

- **Stale active feature**: active file references a feature that was cleaned up externally (branch deleted outside canopy). `get_active_feature()` should validate the feature still exists, return `None` if not.
- **Multiple terminals**: `.canopy/active` is workspace-global. If you switch in one terminal, the other terminal picks it up. This is probably fine — you're focusing on one feature at a time, which is the whole point.
- **`canopy preflight`**: Already works via cwd-based context detection. Active feature is a separate, complementary mechanism — cwd detection should take priority when available.
