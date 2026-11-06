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
    // Until a newly connected Jellyfin finishes its first sync.
    refetchInterval: (query) => {
      const jellyfin = query.state.data?.jellyfin
      return jellyfin?.url && !jellyfin.synced_at && !jellyfin.error ? 2000 : false
    },
  })
}

export const REACTIONS: { value: Reaction; label: string }[] = [
  { value: 'disliked', label: 'Didn’t like' },
  { value: 'liked', label: 'Liked' },
  { value: 'loved', label: 'Loved' },
]
