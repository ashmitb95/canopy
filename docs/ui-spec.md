# UI spec

The target UI. Screens are in [design/end-to-end/](design/end-to-end/) as design-canvas source, one file per screen; the live version is the AgentDeck End to End canvas. Nothing here is built yet unless [architecture.md](architecture.md) says so.

## Terms

- **Primary checkout:** the repo's original folder, which Git calls the main working tree. It holds the user's env files and dev server. Never call it "main" in the UI, which reads as a Git branch.
- **Lane:** a unit of work, branch `X` in each repo that has it.
- **Slot:** a generically named worktree folder (`.worktrees/wt-1`). The UI shows the lane first and the slot second; the screens still show lane-named paths.
- **Warm:** has a ready worktree. **Cold:** branch only.
- **Lead:** the agent that talks with the user and hands out work. **Roster:** which provider holds each role.
- **Delegate:** an agent doing work handed to it.

Label for moving a lane into the primary checkout: "Switch to this lane" is proposed; the screens still say "Run in primary". Its result message names both lanes and where each went.

## Screens

| Screen | File | Contents |
|---|---|---|
| Connect agents | `Main.dc.html` | Detected CLIs, sign-in state, install, add an ACP agent |
| Who does what | `Roster.dc.html` | Lead, provider per role, delegate questions, permissions, enforce roles |
| Workspace | `Workspace.dc.html` | Setup command and env files per repo, GitHub and Linear, colors |
| New worktree | `NewLane.dc.html` | Optional issue, derived lane name, lead, create and open chat |
| Chat | `Chat.dc.html` | Group chat, delegate cards, Now and Next queue, handoff panel |
| Lane view | `Lanes.dc.html` | Primary checkout and what it shares, warm lane cards, cold lanes |
| Review | `Review.dc.html` | Who did what, each agent's report and changes, undo per agent |
| Sidebar | `Side.dc.html` | Collapsible Lanes above Sessions, on every workspace screen |

## Delegate states

Every delegate card keeps one shape: avatar, role and task, a status line, a status icon, and an action area when needed.

| State | Status line | Action |
|---|---|---|
| Working | Current activity and time | None |
| Up next | Who it follows | Cancel |
| Needs permission | The request | Allow, Always allow, Deny |
| Asked the lead | Waiting for an answer | Answer myself |
| Answered by lead | The answer | Change answer |
| Needs your answer | The lead could not decide | Options, Reply |
| Report ready | Files and test result | View handoff, Undo changes |
| Failed | Reason; partial changes kept | Review, Undo |
| Write blocked | Role is read-only | Allow this time |
| Resuming after reload | Session restored | None |
| Stopped by you | Partial changes kept | Review, Resume |
| Paused | Too many rounds with the lead | Open |

## Visual system

- **Palette:** Paper by default (`agentdeck.palette`). Backgrounds, surfaces, text, and borders come from the VS Code theme. The palette sets only brand and status colors. Paper's main color is the theme's text color, inverted.
- **Style:** flat solid color and components. No gradients or illustration.
- **Type:** the VS Code UI and editor fonts in the product; lane names, paths, and numbers use the monospace font.
- **Status:** needs you, working, waiting, done, failed, and idle each differ in shape as well as color.

## Not yet designed

Lanes across repos where the primary checkouts hold different lanes, a settings screen after setup (reuse the setup screens), and light and dark passes for every screen.
