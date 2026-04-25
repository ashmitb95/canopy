import type { ThemeTokens } from "./types";

/**
 * Render a theme as a CSS `:root` block + minimal global resets.
 *
 * Components reference tokens via `var(--token-name)` only — they don't
 * import from `themes/`. Swapping themes only changes this output.
 *
 * Token names follow the `--<group>-<token>` convention with kebab-case:
 *   --color-bg, --color-fg-muted, --color-accent
 *   --font-sans, --font-mono
 *   --type-base-size, --type-line-height
 *   --shape-radius, --shape-radius-sm
 */
export function renderThemeCss(theme: ThemeTokens): string {
  const c = theme.colors;
  const f = theme.fonts;
  const t = theme.type;
  const s = theme.shape;

  const sansFeatures = f.sansFeatures
    ? `font-feature-settings: ${f.sansFeatures};`
    : "";
  const monoFeatures = f.monoFeatures
    ? `font-feature-settings: ${f.monoFeatures};`
    : "";

  return `
:root {
  /* colors */
  --color-bg: ${c.bg};
  --color-bg-elev: ${c.bgElev};
  --color-bg-elev-2: ${c.bgElev2};
  --color-bg-elev-3: ${c.bgElev3};
  --color-border: ${c.border};
  --color-border-soft: ${c.borderSoft};
  --color-fg: ${c.fg};
  --color-fg-muted: ${c.fgMuted};
  --color-fg-dim: ${c.fgDim};
  --color-accent: ${c.accent};
  --color-accent-soft: ${c.accentSoft};
  --color-ok: ${c.ok};
  --color-ok-soft: ${c.okSoft};
  --color-warn: ${c.warn};
  --color-warn-soft: ${c.warnSoft};
  --color-hot: ${c.hot};
  --color-hot-soft: ${c.hotSoft};
  --color-bot: ${c.bot};
  --color-bot-soft: ${c.botSoft};

  /* fonts */
  --font-sans: ${f.sans};
  --font-mono: ${f.mono};

  /* type scale */
  --type-base-size: ${t.baseSize};
  --type-line-height: ${t.lineHeight};
  --type-letter-spacing: ${t.letterSpacing};
  --type-mono-size: ${t.monoSize};
  --type-headline-weight: ${t.headlineWeight};
  --type-headline-letter-spacing: ${t.headlineLetterSpacing};
  --type-small-caps-letter-spacing: ${t.smallCapsLetterSpacing};

  /* shape */
  --shape-radius: ${s.radius};
  --shape-radius-sm: ${s.radiusSm};
  --shape-border-width: ${s.borderWidth};
}

* { box-sizing: border-box; }

html, body {
  margin: 0;
  padding: 0;
  background: var(--color-bg);
  color: var(--color-fg);
  font-family: var(--font-sans);
  font-size: var(--type-base-size);
  line-height: var(--type-line-height);
  letter-spacing: var(--type-letter-spacing);
  -webkit-font-smoothing: antialiased;
  ${sansFeatures}
}

code, kbd, .mono {
  font-family: var(--font-mono);
  font-size: var(--type-mono-size);
  ${monoFeatures}
}

h1, h2, h3, h4 {
  font-weight: var(--type-headline-weight);
  letter-spacing: var(--type-headline-letter-spacing);
}
`.trim();
}
