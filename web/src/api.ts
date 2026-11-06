import { createApiClient, type Reaction } from '@iwanttowatch/api-client'
import { useQueries, useQuery } from '@tanstack/react-query'

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

const AVAILABILITY_CHUNK = 48

/** Where the signed-in user can watch each title; refetched when their services change. */
export function useAvailability(tmdbIds: number[]) {
  const chunks: number[][] = []
  for (let i = 0; i < tmdbIds.length; i += AVAILABILITY_CHUNK) chunks.push(tmdbIds.slice(i, i + AVAILABILITY_CHUNK))
  return useQueries({
    queries: chunks.map((ids) => ({
      queryKey: ['availability', ids.join()],
      queryFn: async () => (await api.GET('/api/v1/availability', { params: { query: { ids } } })).data ?? [],
      staleTime: 10 * 60 * 1000,
    })),
    combine: (results) => new Map(results.flatMap((r) => r.data ?? []).map((a) => [a.tmdb_id, a])),
  })
}
