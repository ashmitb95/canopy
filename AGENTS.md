# AgentDeck

VS Code extension: one chat UI for coding agents (Claude, Codex, ACP agents) that run through the user's installed CLIs, plus lanes, which coordinate chats, branches, and worktrees across repos.

Read before changing an area:

- [docs/architecture.md](docs/architecture.md): layers, data flow, and the rules that constrain changes
- [docs/providers.md](docs/providers.md): the provider contract, per-provider protocol facts, adding an agent
- [docs/lanes.md](docs/lanes.md): the lane model, `.agentdeck/` files, switching, write boundaries
- [docs/roadmap.md](docs/roadmap.md): planned work, with what to verify before building it
- [docs/build-plan.md](docs/build-plan.md): the order it gets built in: a headless core first, the UI last
- [docs/ui-spec.md](docs/ui-spec.md): the target UI and its terms, with screens in `docs/design/`

## Commands

```sh
pnpm install
pnpm check            # typecheck + unit tests; run before every commit
pnpm test <path>      # one test file
pnpm build            # bundles dist/
pnpm build:preview && pnpm screenshot dark   # renders the webview to dist/preview/ (also: light, hc)
pnpm run package      # builds agentdeck-<version>.vsix
```

Press F5 in VS Code for an Extension Development Host on `playground/`.

## Verifying a change

| What changed | How to verify |
|---|---|
| Logic in `src/` | A unit test in the matching `test/` folder. vitest cannot load `vscode`, so keep testable logic in modules that do not import it. |
| Webview | `pnpm build:preview && pnpm screenshot dark`, then look at the image. Add a case to `webview/preview/scenario.ts` if none shows the change. |
| Provider behaviour | Translators: replay fixtures in `test/fixtures/`. Real protocol: the live scripts below. |
| Commands, menus, focus, tree view, notifications | Only a real VS Code window shows these. Say that it is unverified unless you ran it. |

Live scripts run real CLIs on the user's subscription, so they spend quota. After `pnpm build`, run `node dist/<script>.js [claude|codex|grok]`:

| Script | Checks |
|---|---|
| `smoke` | Sign-in, MCP status, an approved edit, memory across turns, resume |
| `smoke-prompts` | Questions, plan approval, mode switch |
| `smoke-lanes` | Lane brief reaches the agent; its summary lands in the lane |
| `smoke-boundary` | Writes outside the lane are refused or redirected |
| `smoke-steer` | Steering a running turn |
| `smoke-rewind` | Rewinding a conversation |
| `record-claude`, `record-codex`, `record-grok` | Re-record `test/fixtures/` |

## Hard rules

- Never read, store, log, or forward credentials, and never call provider APIs directly. Auth stays in each CLI.
- Never print raw ACP frames or the environment: they can contain API keys.
- Do not install CLIs or other software on the user's machine without asking.
- Git operations on user repos must never lose work: no `reset --hard`, no deleting branches. A step that cannot finish cleanly stops and shows why.

## Conventions

- Comments and docs describe what the code does and why, never how it was developed. No plan numbers, process narrative, or references to other products.
- Prefer small modules with one responsibility. Match the style of the surrounding file.
- Colors come only from the tokens in `webview/theme.css`: VS Code theme variables, with brand and status colors overridden by the palettes in `webview/palettes.css`. Backgrounds, surfaces, text, and borders always come from the theme.
- A UI control appears only when the provider declares the matching capability; do not branch on provider id in the webview.
- Commit in small working steps. Do not use `--amend` on shared work.
