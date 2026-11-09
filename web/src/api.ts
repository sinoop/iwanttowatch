import { createApiClient, type Reaction } from '@iwanttowatch/api-client'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'

export const api = createApiClient()

/** Turns a FastAPI error body into a sentence for the user. */
export function errorMessage(error: unknown): string {
  const detail = (error as { detail?: unknown } | undefined)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg)
  return 'Something went wrong. Please try again.'
}

/** Copy text to the clipboard, falling back to a temporary textarea when served over plain HTTP. */
export async function copyToClipboard(text: string): Promise<boolean> {
  if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // Fall through to the textarea fallback when the Clipboard API is blocked.
    }
  }
  if (typeof document === 'undefined' || typeof document.execCommand !== 'function') {
    return false
  }
  const active = document.activeElement instanceof HTMLElement ? document.activeElement : null
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.readOnly = true
  textarea.style.position = 'fixed'
  textarea.style.top = '0'
  textarea.style.left = '0'
  textarea.style.opacity = '0'
  textarea.style.pointerEvents = 'none'
  document.body.appendChild(textarea)
  try {
    textarea.focus({ preventScroll: true })
    textarea.select()
    textarea.setSelectionRange(0, text.length)
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    document.body.removeChild(textarea)
    active?.focus({ preventScroll: true })
  }
}

/** Save a film to the shortlist, or take it off. */
export function useShortlist() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ tmdbId, save }: { tmdbId: number; save: boolean }) => {
      const params = { params: { path: { tmdb_id: tmdbId } } }
      const { error } = save
        ? await api.PUT('/api/v1/titles/{tmdb_id}/shortlist', params)
        : await api.DELETE('/api/v1/titles/{tmdb_id}/shortlist', params)
      if (error) throw new Error(errorMessage(error))
    },
    onSettled: (_, __, { tmdbId }) => {
      queryClient.invalidateQueries({ queryKey: ['feed'] })
      queryClient.invalidateQueries({ queryKey: ['title', tmdbId] })
    },
  })
}

/** The household's child profiles. */
export function useChildren(enabled = true) {
  return useQuery({
    queryKey: ['children'],
    queryFn: async () => (await api.GET('/api/v1/children')).data ?? [],
    enabled,
  })
}

/** Assign a film to a child profile's shortlist, or take it off. */
export function useAssignToChild() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ childId, tmdbId, save }: { childId: number; tmdbId: number; save: boolean }) => {
      const params = { params: { path: { child_id: childId, tmdb_id: tmdbId } } }
      const { error } = save
        ? await api.PUT('/api/v1/children/{child_id}/shortlist/{tmdb_id}', params)
        : await api.DELETE('/api/v1/children/{child_id}/shortlist/{tmdb_id}', params)
      if (error) throw new Error(errorMessage(error))
    },
    onSettled: (_, __, { tmdbId }) => {
      queryClient.invalidateQueries({ queryKey: ['feed'] })
      queryClient.invalidateQueries({ queryKey: ['together', 'picks'] })
      queryClient.invalidateQueries({ queryKey: ['title', tmdbId] })
    },
  })
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

const languageName = new Intl.DisplayNames(['en'], { type: 'language' })

/** Year, certificate, language, running time, and IMDb rating when known. */
export function facts(film: {
  year: number | null
  certificate?: string | null
  original_language: string
  runtime: number | null
  imdb?: { rating: number } | null
}) {
  return [
    film.year,
    film.certificate,
    languageName.of(film.original_language),
    film.runtime ? `${Math.floor(film.runtime / 60)}h ${film.runtime % 60}m` : null,
    film.imdb ? `IMDb ${film.imdb.rating.toFixed(1)}` : null,
  ].filter(Boolean) as (string | number)[]
}

/** Where films must be playable: anywhere the user can watch, on chosen platforms
 * ("jellyfin" or TMDb provider IDs), or everything including films on none of them. */
export type WatchOn = 'anywhere' | 'everything' | string[]

export function watchOnQuery(watchOn: WatchOn) {
  return {
    available_only: watchOn !== 'everything',
    platforms: Array.isArray(watchOn) ? watchOn : undefined,
  }
}
