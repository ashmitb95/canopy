/** Orders workspace files for the @ menu: recently opened first, then name prefixes, name matches, path matches, subsequences. */
export function rankFiles(labels: string[], query: string, recent: ReadonlySet<string>, limit = 20): string[] {
  const needle = query.toLowerCase()
  return labels
    .flatMap((label) => {
      const lower = label.toLowerCase()
      const name = lower.slice(lower.lastIndexOf('/') + 1)
      const score = !needle
        ? 3
        : name.startsWith(needle)
          ? 0
          : name.includes(needle)
            ? 1
            : lower.includes(needle)
              ? 2
              : isSubsequence(lower, needle)
                ? 3
                : -1
      return score < 0 ? [] : [{ label, score: score - (recent.has(label) ? 10 : 0) }]
    })
    .sort((a, b) => a.score - b.score || a.label.length - b.label.length || a.label.localeCompare(b.label))
    .slice(0, limit)
    .map((entry) => entry.label)
}

function isSubsequence(text: string, needle: string): boolean {
  let index = 0
  for (const char of text) if (char === needle[index]) index++
  return index === needle.length
}
