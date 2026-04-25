import type { ThemeTokens } from "./types";

/**
 * Minimal — Linear / Vercel / Stripe Dashboard aesthetic.
 *
 * Near-monochrome (#0a0a0a bg), single subtle blue accent, generous
 * breathing room. Inter with stylistic features for the friendlier
 * single-storey 'a' (`ss01`) and tabular figures. Berkeley Mono fallback
 * to SF Mono.
 */
export const minimal: ThemeTokens = {
  name: "Minimal",
  description: "Near-monochrome with a single accent — quiet / premium",

  colors: {
    bg: "#0a0a0a",
    bgElev: "#111111",
    bgElev2: "#181818",
    bgElev3: "#1f1f1f",

    border: "#2a2a2a",
    borderSoft: "#1f1f1f",

    fg: "#fafafa",
    fgMuted: "#a1a1a1",
    fgDim: "#6b6b6b",

    accent: "#4f80ff",
    accentSoft: "#4f80ff1f",

    ok: "#5dd0a8",
    okSoft: "#5dd0a81f",
    warn: "#f5b945",
    warnSoft: "#f5b9451f",
    hot: "#ff6363",
    hotSoft: "#ff63631f",
    bot: "#b08aff",
    botSoft: "#b08aff1f",
  },

  fonts: {
    sans: '"Inter", -apple-system, BlinkMacSystemFont, sans-serif',
    mono: '"Berkeley Mono", "SF Mono", "JetBrains Mono", Consolas, monospace',
    sansFeatures: '"ss01", "cv11"',
  },

  type: {
    baseSize: "13px",
    lineHeight: "1.55",
    letterSpacing: "-0.05px",
    monoSize: "12px",
    headlineWeight: "600",
    headlineLetterSpacing: "-0.3px",
    smallCapsLetterSpacing: "0.1em",
  },

  shape: {
    radius: "7px",
    radiusSm: "5px",
    borderWidth: "1px",
  },
};
