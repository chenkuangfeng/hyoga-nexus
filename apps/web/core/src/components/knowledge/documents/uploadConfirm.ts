import type { KnowledgeProcessOverrides } from '@nexus-web/core/types/knowledgeProcess'

export type UploadConfirmMode = 'file' | 'url' | 'manual' | 'reparse'

export interface UploadConfirmManualSource {
  kbId: string
  knowledgeId?: string
  title: string
  content: string
  tagIds?: string[]
}

export interface UploadConfirmReparseSource {
  knowledgeId: string
  fileName?: string
  fileType?: string
  processOverrides?: KnowledgeProcessOverrides | null
}

export interface UploadConfirmResult {
  processConfig: KnowledgeProcessOverrides
  mode: UploadConfirmMode
  tagIds?: string[]
  files?: File[]
  urls?: string[]
  manual?: UploadConfirmManualSource
  reparse?: UploadConfirmReparseSource
  /**
   * Folder the batch is uploaded into ('' = knowledge base root). Returned as
   * part of the result because the dialog lets the user change it, so callers
   * must use this value rather than whatever folder was open when they opened
   * the dialog.
   */
  targetFolder?: string
}
