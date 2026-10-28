import { createContext, useContext } from 'react'
import { fileName } from './format'

/** Webview URI of the attachment store; images in prompts are shown from there. */
export const AttachmentsContext = createContext<string | undefined>(undefined)

export function useAttachmentSrc(path: string): string | undefined {
  const base = useContext(AttachmentsContext)
  return base ? `${base}/${fileName(path)}` : undefined
}
