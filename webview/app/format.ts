import type { PromptPart } from '../../src/core/types'

export function promptText(parts: PromptPart[]): string {
  return parts
    .filter((part): part is Extract<PromptPart, { type: 'text' }> => part.type === 'text')
    .map((part) => part.text)
    .join('\n\n')
}

export function fileName(path: string): string {
  return path.split(/[\\/]/).pop() ?? path
}
