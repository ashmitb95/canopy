import { describe, expect, it } from 'vitest'
import { diffFiles } from '../../src/group/diff-files'

const DIFF = `diff --git a/api/export.ts b/api/export.ts
index 1111111..2222222 100644
--- a/api/export.ts
+++ b/api/export.ts
@@ -1,3 +1,4 @@
-const rows = await loadAll(invoice)
+const cursor = openCursor(invoice)
+return streamCsv(cursor, res)
 export {}
diff --git a/notes.md b/notes.md
new file mode 100644
--- /dev/null
+++ b/notes.md
@@ -0,0 +1 @@
+hello
`

describe('diffFiles', () => {
  it('splits a diff into files with line counts', () => {
    const files = diffFiles(DIFF)
    expect(files.map(({ path, added, removed }) => ({ path, added, removed }))).toEqual([
      { path: 'api/export.ts', added: 2, removed: 1 },
      { path: 'notes.md', added: 1, removed: 0 }
    ])
    expect(files[0].lines[0]).toBe('@@ -1,3 +1,4 @@')
  })

  it('returns nothing for an empty diff', () => {
    expect(diffFiles('')).toEqual([])
  })
})
