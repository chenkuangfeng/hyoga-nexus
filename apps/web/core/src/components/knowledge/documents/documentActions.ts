/** Actions emitted by the shared document menu for the host to authorize and execute. */
export type DocumentAction = 'download' | 'edit' | 'view-trace' | 'reparse' | 'retry'
  | 'cancel-parse' | 'move' | 'move-folder' | 'batch-manage' | 'delete'

/** Actions whose handling and confirmation are delegated to the host. */
export type HostDocumentAction = Extract<DocumentAction, 'download' | 'reparse' | 'retry' | 'delete'>
