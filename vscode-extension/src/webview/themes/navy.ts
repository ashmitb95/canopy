import type { ThemeTokens } from "./types";

/**
 * Canopy Command — naval / instrument-panel aesthetic.
 *
 * Cool deep navy bg, signal-yellow + signal-red accents, brushed-steel
 * mids. Inter for body, JetBrains Mono for code. Reads as a developer
 * tool with a strong identity.
 */
export const navy: ThemeTokens = {
  name: "Navy",
  description: "Canopy Command — deep navy with signal accents",

  colors: {
    bg: "#08111c",
    bgElev: "#0d1a26",
    bgElev2: "#11202f",
    bgElev3: "#16293c",

    border: "#20405e",
    borderSoft: "#1c3450",

    fg: "#e6eef7",
    fgMuted: "#8aa3bd",
    fgDim: "#506c87",

    accent: "#2f81f7",
    accentSoft: "#2f81f71f",

    ok: "#5dd0a8",
    okSoft: "#5dd0a822",
    warn: "#e6c34c",
    warnSoft: "#e6c34c1f",
    hot: "#f85149",
    hotSoft: "#f8514922",
    bot: "#a371f7",
    botSoft: "#a371f722",
  },

  fonts: {
    sans: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", "Segoe UI", sans-serif',
    mono: '"JetBrains Mono", "SF Mono", Consolas, monospace',
  },

  type: {
    baseSize: "13px",
    lineHeight: "1.55",
    letterSpacing: "0",
    monoSize: "12px",
    headlineWeight: "600",
    headlineLetterSpacing: "-0.2px",
    smallCapsLetterSpacing: "0.12em",
  },

  shape: {
    radius: "5px",
    radiusSm: "3px",
    borderWidth: "1px",
  },
};
