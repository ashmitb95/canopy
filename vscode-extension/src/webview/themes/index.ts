/**
 * Theme registry — adding a theme is two steps:
 *
 *   1. Create `<name>.ts` with a `ThemeTokens` export.
 *   2. Add it to `themes` below.
 *
 * Components reference tokens via `var(--*)` only. The dashboard panel
 * picks a theme by name (from VS Code config `canopy.dashboard.theme`),
 * looks it up here, and renders its CSS via `renderThemeCss`.
 *
 * If the configured theme name doesn't exist, falls back to `defaultTheme`.
 */
import type { ThemeTokens } from "./types";
import { navy } from "./navy";
import { minimal } from "./minimal";

export { renderThemeCss } from "./render";
export type { ThemeTokens } from "./types";

export const themes = {
  navy,
  minimal,
} as const;

export type ThemeName = keyof typeof themes;

export const defaultTheme: ThemeName = "navy";

export function getTheme(name: string | undefined): ThemeTokens {
  if (name && name in themes) {
    return themes[name as ThemeName];
  }
  return themes[defaultTheme];
}

export function listThemes(): Array<{ id: ThemeName; name: string; description: string }> {
  return (Object.keys(themes) as ThemeName[]).map((id) => ({
    id,
    name: themes[id].name,
    description: themes[id].description,
  }));
}
