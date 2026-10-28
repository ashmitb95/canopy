# MVP plan 5: Release — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read the [MVP overview](2026-10-28-mvp-overview.md) conventions first. Plans 1–4 must be complete.

**Goal:** Make the MVP shippable as a sideloaded VSIX: verify it under high-contrast themes, version it, document it for a new user, and bring the design docs up to date with what was built.

**Architecture:** No new runtime code except a high-contrast token override. The preview harness gains a high-contrast theme so the check is repeatable.

**Tech Stack:** as before.

---

### Task 1: High-contrast themes

**Files:**
- Modify: `webview/theme.css`, `webview/preview/themes.css`, `webview/preview/index.html`

VS Code high-contrast themes draw every widget with `--vscode-contrastBorder` and often leave `--vscode-widget-border` unset. Cards, pills, and the composer must keep a visible outline there.

- [ ] **Step 1: Use the contrast border in high-contrast themes**

In `webview/theme.css`, replace the rule

```css
  .vscode-high-contrast [data-slot] {
    outline-color: var(--vscode-contrastBorder);
  }
```

(inside `@layer base`) with nothing, and add after the `body[data-surface="view"]` rule:

```css
/* High-contrast themes outline every widget with the contrast border. */
body.vscode-high-contrast {
  --border: var(--vscode-contrastBorder, var(--vscode-widget-border));
  --ring: var(--vscode-contrastActiveBorder, var(--vscode-focusBorder));
}

/* Filled buttons have no border of their own; outline them so they stay distinguishable. */
body.vscode-high-contrast [data-slot="button"]:is([data-variant="default"], [data-variant="secondary"], [data-variant="outline"]) {
  outline: 1px solid var(--vscode-contrastBorder);
}
```

- [ ] **Step 2: Add a high-contrast preview theme**

Append to `webview/preview/themes.css`:

```css
:root[data-preview-theme="hc"] {
  --vscode-font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --vscode-font-size: 13px;
  --vscode-editor-font-family: Menlo, Monaco, "Courier New", monospace;
  --vscode-editor-background: #000000;
  --vscode-sideBar-background: #000000;
  --vscode-foreground: #ffffff;
  --vscode-descriptionForeground: #ffffff;
  --vscode-editorWidget-background: #0c141f;
  --vscode-button-background: #000000;
  --vscode-button-foreground: #ffffff;
  --vscode-button-secondaryBackground: #000000;
  --vscode-button-secondaryForeground: #ffffff;
  --vscode-textCodeBlock-background: #000000;
  --vscode-list-hoverBackground: #000000;
  --vscode-errorForeground: #f48771;
  --vscode-input-background: #000000;
  --vscode-focusBorder: #f38518;
  --vscode-contrastBorder: #6fc3df;
  --vscode-contrastActiveBorder: #f38518;
  --vscode-testing-iconPassed: #73c991;
  --vscode-editorWarning-foreground: #ffd700;
  --vscode-charts-blue: #3794ff;
  --vscode-diffEditor-insertedLineBackground: rgba(155, 185, 85, 0.2);
  --vscode-diffEditor-removedLineBackground: rgba(255, 0, 0, 0.2);
  --vscode-list-activeSelectionBackground: #000000;
  --vscode-list-activeSelectionForeground: #ffffff;
  --vscode-badge-background: #000000;
  --vscode-badge-foreground: #ffffff;
}
```

In `webview/preview/index.html`, change the theme detection so `theme=hc` works: replace

```js
  window.previewTheme = new URLSearchParams(location.search).get('theme') === 'light' ? 'light' : 'dark'
```

with

```js
  window.previewTheme = ['light', 'hc'].includes(new URLSearchParams(location.search).get('theme')) ? new URLSearchParams(location.search).get('theme') : 'dark'
```

and the body-class script's first statement with:

```js
document.body.classList.add({ light: 'vscode-light', hc: 'vscode-high-contrast' }[window.previewTheme] ?? 'vscode-dark')
```

- [ ] **Step 3: Review all three themes**

Run:

```bash
pnpm build:preview && pnpm screenshot dark && pnpm screenshot light && pnpm screenshot hc
```

Expected: three PNGs. In `screenshot-hc-panel.png`, every card, pill, the composer, and the approval card has a visible light-blue outline on black, text is white, and the primary button is distinguishable (outlined). Fix only `webview/theme.css` if something is invisible; report any fix.

- [ ] **Step 4: Commit**

```bash
git add webview
git commit -m "feat(webview): outline widgets with the contrast border in high-contrast themes"
```

---

### Task 2: Version, changelog, and README

**Files:**
- Modify: `package.json` (`version`), `README.md` (full replacement)
- Create: `CHANGELOG.md`

- [ ] **Step 1: Version**

In `package.json`, set `"version": "0.1.0"`.

- [ ] **Step 2: Changelog**

`CHANGELOG.md`:

```markdown
# Changelog

## 0.1.0

First usable release.

- Chat with Claude Code and Codex from VS Code, in editor tabs or the AgentDeck sidebar, on your own subscriptions through each official CLI.
- Sessions persist across reloads and resume where they left off; messages sent while the agent works are queued.
- Streaming replies, reasoning, tool cards, diffs that open in VS Code's diff editor, plans, and approvals with keyboard shortcuts.
- Model and permission-mode pickers, a context meter, and an MCP popover with per-server status, sign-in, and reconnect.
- Sessions list with rename, stop, and delete; running and waiting counts in the status bar.
- Follows the active VS Code theme, including high-contrast themes.
```

- [ ] **Step 3: README**

`README.md` (full replacement):

````markdown
# AgentDeck

Chat with coding agents — Claude Code and Codex — from one place in VS Code, on your own subscriptions.

AgentDeck runs each provider through its official CLI: your installed `claude`, and `codex` (on your PATH or bundled with the official Codex extension). It never reads, stores, or forwards your credentials and never calls provider APIs itself. Sign-in, MCP servers, and their sign-ins stay with each CLI, so anything you set up for the official extensions works here too.

## Features

- **Chats in tabs or the sidebar.** Open as many as you like side by side; the same chat can show in both places.
- **Sessions that last.** Close VS Code, come back, and continue: history is kept per workspace and the agent resumes its own context.
- **The agent's work, readable.** Streaming replies, reasoning, collapsible tool cards, diffs (open them in VS Code's diff editor), and the agent's plan.
- **Approvals.** Allow once, always allow, or deny; Enter and Esc work from the keyboard.
- **Controls.** Switch model and permission mode mid-chat, see how much context is used, and stop a turn.
- **MCP.** See every server's state and tools; sign in to a server that needs it and reconnect without restarting the chat.
- **Your theme.** Every color comes from the active VS Code theme.

## Requirements

- VS Code 1.95 or later.
- For Claude: Claude Code installed and signed in with your claude.ai account (`claude auth status`).
- For Codex: the Codex CLI or the official Codex extension, signed in (`codex login status`).

## Install

AgentDeck is not on the Marketplace yet. Build and sideload it:

```sh
pnpm install
pnpm run package
code --install-extension agentdeck-0.1.0.vsix --force
```

Reload VS Code and open AgentDeck from the activity bar.

## Development

Open this folder in VS Code and press F5: an Extension Development Host opens on `playground/` with other extensions disabled.

- `pnpm test` runs the unit tests; `pnpm typecheck` checks the extension and the webview.
- `pnpm build:preview && pnpm screenshot dark` renders the chat UI with sample data to `dist/preview/` (needs Playwright's headless Chromium); `light` and `hc` render the other themes.
- `node dist/smoke.js [claude|codex]` (after `pnpm build`) drives a real session through the session manager: sign-in check, MCP status, an approved edit, memory across turns, and resume after a simulated reload.
- `node dist/record-claude.js` and `node dist/record-codex.js` re-record the translator fixtures in `test/fixtures/`.

## Docs

- [Design spec](docs/superpowers/specs/2026-10-28-agentdeck-design.md) — roadmap, architecture, provider contracts, sessions, UI, theming
- [Decisions](docs/decisions.md) — what was decided and why
- [MVP plans](docs/superpowers/plans/2026-10-28-mvp-overview.md) — how the MVP was built
- [Look and feel](docs/design/README.md) — the mockups behind the UI
- [Orca reference notes](docs/research/orca.md) — what we learned from Orca's implementation
````

- [ ] **Step 4: Commit**

```bash
git add package.json CHANGELOG.md README.md
git commit -m "docs: version 0.1.0 with a changelog and a user-facing README"
```

---

### Task 3: Bring the design docs up to date

**Files:**
- Modify: `docs/decisions.md`, `docs/superpowers/plans/2026-10-28-mvp-overview.md`, `docs/superpowers/specs/2026-10-28-agentdeck-design.md`

- [ ] **Step 1: Decisions made while building**

Append to the table in `docs/decisions.md` (after decision 21):

```markdown
| 22 | Codex runs from `codex` on PATH, else the binary bundled with the newest official Codex extension | Many users have Codex only through its extension; its bundled CLI is the same official binary, and it shares the user's `~/.codex` login. |
| 23 | Codex MCP sign-in goes through `mcpServer/oauth/login`; AgentDeck only opens the returned link | Codex completes the OAuth and keeps the token, which keeps decision 2 intact while giving Codex servers a one-click sign-in. |
| 24 | The webview loads as an ES module with code splitting | Shiki's grammars load on demand, keeping the entry script small. |
| 25 | UI is checked from headless screenshots of a preview build with scripted sessions | Agents and reviewers can verify UI changes without a VS Code window; the manual check covers what the preview cannot (focus, real themes, reloads). |
```

- [ ] **Step 2: Plan statuses**

In `docs/superpowers/plans/2026-10-28-mvp-overview.md`, set every plan's status to `Done`, and replace the plan 2–4 *Delivers* descriptions' "Written after …" wording in the *Status* column accordingly. Link plans 2–5 in the *Plan* column the way plan 1 is linked:
- `[Chat app foundation](2026-10-28-mvp-2-chat-app.md)`
- `[Chat items and controls](2026-10-28-mvp-3-items-and-controls.md)`
- `[Codex](2026-10-28-mvp-4-codex.md)`
- `[Release](2026-10-28-mvp-5-release.md)`

Delete the paragraph that begins "Plans 2–5 are written when the previous plan lands" and the "Carried forward from plan 1's live run" paragraph (plan 3 Task 1 resolved it).

- [ ] **Step 3: Spec**

In `docs/superpowers/specs/2026-10-28-agentdeck-design.md`, in the *MVP* section, add after the scope table:

```markdown
The MVP shipped as 0.1.0. Codex is found on PATH or inside the official Codex extension (decision 22), and Codex MCP servers sign in through Codex's own OAuth flow (decision 23).
```

- [ ] **Step 4: Commit**

```bash
git add docs
git commit -m "docs: record build-time decisions and mark the MVP plans done"
```

---

### Task 4: Final verification

- [ ] **Step 1: Everything that runs headless**

Run:

```bash
pnpm typecheck && pnpm test && pnpm build && node dist/smoke.js claude && node dist/smoke.js codex && pnpm run package && unzip -l agentdeck-0.1.0.vsix | tail -3
```

Expected: clean; all tests pass; `SMOKE OK` twice; the VSIX is built and its listing ends with the file count and total size. Report the VSIX size (`ls -lh agentdeck-0.1.0.vsix`).

- [ ] **Step 2: Hand off**

Stop and ask the user to:
1. Install `agentdeck-0.1.0.vsix`, reload, and repeat the manual checks from plans 2–4 once on the release build.
2. Switch to one third-party theme they use and to a high-contrast theme, and confirm the chat follows both.
3. Decide how to integrate the `mvp` branch (merge to `main`, open a PR, or keep it) — use superpowers:finishing-a-development-branch for that step.

---

## Done when

- Task 4's headless checks pass and the user has done the hand-off checks.
- The docs describe what shipped.
