/**
 * Tiny HTML helpers shared across webview components.
 *
 * Webview content runs in a sandboxed iframe but anything we splice into
 * a template literal gets interpreted as markup — escape user-controlled
 * strings (feature names, branch names, file paths, PR titles, comment
 * bodies) at every interpolation point.
 */

const ESC: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

export function escapeHtml(value: unknown): string {
  if (value === null || value === undefined) return "";
  return String(value).replace(/[&<>"']/g, (ch) => ESC[ch]);
}

/**
 * Build a single CSS class list from conditionally-included names.
 * `cx("a", cond && "b", { c: true, d: false })` → `"a b c"`.
 */
export function cx(
  ...parts: Array<string | false | null | undefined | Record<string, unknown>>
): string {
  const out: string[] = [];
  for (const p of parts) {
    if (!p) continue;
    if (typeof p === "string") {
      out.push(p);
    } else if (typeof p === "object") {
      for (const [k, v] of Object.entries(p)) if (v) out.push(k);
    }
  }
  return out.join(" ");
}
