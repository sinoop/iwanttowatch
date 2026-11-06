import { createApiClient } from '@cinematch/api-client'

export const api = createApiClient()

/** Turns a FastAPI error body into a sentence for the user. */
export function errorMessage(error: unknown): string {
  const detail = (error as { detail?: unknown } | undefined)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg)
  return 'Something went wrong. Please try again.'
}
