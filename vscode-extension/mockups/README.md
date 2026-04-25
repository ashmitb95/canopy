# Dashboard mockups

Static HTML mockups of the proposed canopy dashboard, reimagined around the **canonical-slot focus model** (Wave 2.9 capabilities) instead of treating features as a flat list.

These are **design surfaces**, not implementations — open each in a browser, react, iterate. The eventual VSCode webview implementation will mirror the same DOM/layout decisions.

## Design language

- **One headline concept: your focus.** The canonical feature is the largest tile in the center; everything else is supporting context.
- **Three feature states** (canopy's actual model): `canonical` · `warm` · `cold`.
- **CTAs are sourced from `feature_state(feature).next_actions`** — the dashboard never invents its own buttons; it renders what the agent would also see.
- **Cap-reached blockers are first-class UI** — they're the moment the canonical-slot model demands an explicit user choice.
- **Same data the agent sees.** Anything in the dashboard maps to an `mcp__canopy__*` call — humans and agents stay in lockstep.

## Mockups

| File | Purpose |
|---|---|
| `dashboard-steady.html` | Steady state — 1 canonical (SIN-12 in `needs_work`), 2 warm (SIN-13, SIN-14), 3 cold features in the ledger. Triage feed shows what *should* be your focus. |
| `dashboard-cap-reached.html` | The user just clicked "switch to SIN-15"; cap is full; modal surfaces the three structured `fix_actions` (wind-down, evict by name, raise cap). |
| `dashboard-state-detail.html` | Focused-feature deep-dive: actionable review threads inline, secondary CTAs visible, per-repo path resolution shown. |

## After review

Once a direction is locked, the implementation plan replaces the original `~/.claude/plans/wave-7-dashboard-execution.md` with a refreshed Phase A-G that translates these mockups to TypeScript + the existing `dashboardPanel.ts` rebuild path.
