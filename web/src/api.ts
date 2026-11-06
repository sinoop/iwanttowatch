import { createApiClient, type Reaction } from '@iwanttowatch/api-client'
import { useQuery } from '@tanstack/react-query'

export const api = createApiClient()

/** Turns a FastAPI error body into a sentence for the user. */
export function errorMessage(error: unknown): string {
  const detail = (error as { detail?: unknown } | undefined)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg)
  return 'Something went wrong. Please try again.'
}

export function useServerSettings() {
  return useQuery({
    queryKey: ['settings'],
    queryFn: async () => (await api.GET('/api/v1/settings')).data ?? null,
  })
}

export const REACTIONS: { value: Reaction; label: string }[] = [
  { value: 'disliked', label: 'Didn’t like' },
  { value: 'liked', label: 'Liked' },
  { value: 'loved', label: 'Loved' },
]
