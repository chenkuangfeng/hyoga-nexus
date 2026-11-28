/** Preserve the server's failure reason: the request client rejects plain objects as well as Errors. */
export function memoryErrorText(error: unknown, fallback: string): string {
  if (typeof error === 'object' && error !== null && 'message' in error
    && typeof error.message === 'string' && error.message.trim()) {
    return error.message
  }
  return fallback
}
