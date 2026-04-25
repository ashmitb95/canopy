/**
 * Theme tokens — the schema every dashboard theme satisfies.
 *
 * Components reference tokens via `var(--<token>)` only. Adding a new
 * theme means writing one file (a `ThemeTokens` object) and registering
 * it in `index.ts`. Components don't change.
 *
 * Three layers:
 *   - colors        — the visual palette
 *   - fonts         — sans + mono families with optional OpenType features
 *   - type          — base size, line height, letter-spacing, headline weight
 *   - shape         — radii + border widths
 *
 * Naming follows the GitHub-Primer convention loosely:
 *   bg / bgElev / bgElev2 / bgElev3   — surface elevation tiers
 *   border / borderSoft               — separator weight tiers
 *   fg / fgMuted / fgDim              — text contrast tiers
 *   accent + accentSoft               — primary action color
 *   ok / warn / hot / bot (+ Soft)    — semantic colors with soft fills
 */
export type ThemeTokens = {
  /** Display name shown in the theme picker. */
  name: string;
  /** One-line description shown next to the name. */
  description: string;

  colors: {
    /** Page background. */
    bg: string;
    /** First elevation (cards, sidebar). */
    bgElev: string;
    /** Second elevation (rows inside cards, drawer rail). */
    bgElev2: string;
    /** Third elevation (selected row, hover-pressed). */
    bgElev3: string;

    /** Primary border weight. */
    border: string;
    /** Hairline / inner divider. */
    borderSoft: string;

    /** Primary text. */
    fg: string;
    /** Secondary text (labels, metadata). */
    fgMuted: string;
    /** Tertiary text (timestamps, hints). */
    fgDim: string;

    /** Primary action color (CTAs, focus rings, primary links). */
    accent: string;
    /** Soft fill of the accent (badges, pill backgrounds). */
    accentSoft: string;

    /** Canonical / approved / passing — anything green-positive. */
    ok: string;
    okSoft: string;
    /** Warm / dirty / signal — anything yellow-attention. */
    warn: string;
    warnSoft: string;
    /** Changes_requested / actionable / error — anything red-blocking. */
    hot: string;
    hotSoft: string;
    /** Bot / automation accent (claude[bot] threads, automated reviews). */
    bot: string;
    botSoft: string;
  };

  fonts: {
    /** Body + UI text family. */
    sans: string;
    /** Code, branch names, paths, technical data. */
    mono: string;
    /** OpenType feature settings for sans (e.g. `'"ss01", "cv11"'` for Inter). */
    sansFeatures?: string;
    /** OpenType feature settings for mono. */
    monoFeatures?: string;
  };

  type: {
    /** Body font-size (e.g. `"13px"`). */
    baseSize: string;
    /** Body line-height (e.g. `"1.55"`). */
    lineHeight: string;
    /** Body letter-spacing (e.g. `"0"` or `"-0.05px"`). */
    letterSpacing: string;
    /** Mono font-size (usually 1px smaller than baseSize). */
    monoSize: string;
    /** Headline font-weight (e.g. `"600"`). */
    headlineWeight: string;
    /** Headline letter-spacing (e.g. `"-0.3px"`). */
    headlineLetterSpacing: string;
    /** Letter-spacing for small-caps section labels (e.g. `"0.12em"`). */
    smallCapsLetterSpacing: string;
  };

  shape: {
    /** Base border-radius (cards, panels). */
    radius: string;
    /** Smaller radius (inputs, badges, pill buttons). */
    radiusSm: string;
    /** Border-width across the UI. */
    borderWidth: string;
  };
};
