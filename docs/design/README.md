# Look and feel

The mockups in [`mockups/`](mockups/) lock the visual direction: shadcn/ui and AI Elements components themed by the active VS Code theme. They render the Dark Modern theme as a stand-in; in the extension every color comes from VS Code theme variables (see the spec's *Component stack and theming* section).

Open any file directly in a browser. The live, editable canvas is the "AgentDeck UX mockups" artifact: https://claude.ai/artifact/4zR2DF5GQdX7HMEyPUasM5 (private to its owner).

| Mockup | Shows |
|---|---|
| [1 · First run](mockups/1-first-run.html) | Provider list with state (ready, not installed, signed out); welcome cards with the next step per provider; empty sessions state |
| [2 · Chat tab](mockups/2-chat-tab.html) | Full turn: user message with file pill, Reasoning, Tool cards with status, markdown reply, diff card, approval card with keyboard hints, message actions; working status, queued message, composer with model/mode/MCP/context controls; quota hover card |
| [3 · Providers and sign-in](mockups/3-providers-sign-in.html) | Claude mid sign-in (three-step stepper, copy link, cancel); Codex not installed; Grok signed out with terminal sign-in |
| [4 · Side by side](mockups/4-side-by-side.html) | Two chats split: Claude working through a plan, Codex waiting on an approval; toast and status bar counts |
| [5 · Sidebar chat](mockups/5-sidebar-chat.html) | Chat docked in the sidebar beside the editor; session switcher as a command menu (new chat per provider, recent sessions); live plan and shimmer status |

## Conventions the mockups establish

- Provider identity: monogram avatar (C, Cx, G) with a per-provider tint; no logos.
- Status: pill badges (Ready, Signed out, Running, Completed, Exit 1, Input) using the theme's success, warning, info, and error colors.
- Tool calls: one collapsible card per call with an icon, verb, target, and status badge; failures expand to show output.
- Approvals: a warning-tinted card, command in a code box, primary *Allow once*, secondary *Always allow …*, ghost *Deny*, with ⏎ and esc hints.
- Composer: rounded container with attachment pills on top, the editor, and a toolbar holding attach, model, mode, MCP, the context ring, and Send/Stop.
- Quota: a compact pill that opens a hover card with each window, its reset time, and how old the data is.
