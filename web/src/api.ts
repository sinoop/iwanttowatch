import { createApiClient, type Reaction, type TitleReaction } from '@iwanttowatch/api-client'
import { useMutation, useQueries, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'

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

export const TAG_LABELS: Record<string, string> = {
  great_story: 'Great story',
  great_acting: 'Great acting',
  great_direction: 'Great direction',
  beautiful_visuals: 'Beautiful visuals',
  great_music: 'Great music',
  sharp_dialogue: 'Sharp dialogue',
  exciting: 'Exciting',
  great_action: 'Great action scenes',
  unexpected_suspense: 'Unexpected suspense',
  clever_twist: 'Clever twist',
  great_villain: 'Great villain performance',
  genuinely_scary: 'Genuinely scary',
  made_me_laugh: 'Made me laugh',
  feel_good: 'Feel-good',
  moved_me: 'Moved me',
  lovely_romance: 'Lovely romance',
  relatable_characters: 'Relatable characters',
  slice_of_life: 'Slice of life',
  felt_real: 'Felt real',
  thought_provoking: 'Thought-provoking',
  mind_bending: 'Mind-bending',
  world_building: 'Great world-building',
  epic_scale: 'Epic scale',
  great_with_family: 'Great with family',
  learned_something: 'Learned something',
  weak_story: 'Weak story',
  predictable: 'Predictable',
  too_slow: 'Too slow',
  too_long: 'Too long',
  unconvincing_acting: 'Unconvincing acting',
  disappointing_ending: 'Disappointing ending',
  cliched: 'Clichéd',
  too_violent: 'Too violent',
  not_funny: 'Not funny',
  not_scary: 'Not scary',
  confusing: 'Confusing',
  overhyped: 'Overhyped',
}

const reactionKey = (tmdbId: number) => ['reaction', tmdbId]

/** A rating changes what the user has seen, their taste, and what the feed and group picks offer. */
export function refreshAfterReaction(queryClient: QueryClient, tmdbId: number) {
  queryClient.invalidateQueries({ queryKey: ['ratings'] })
  queryClient.invalidateQueries({ queryKey: ['persona'] })
  // Rated films leave the feed and group picks.
  queryClient.invalidateQueries({ queryKey: ['feed'] })
  queryClient.invalidateQueries({ queryKey: ['together'] })
  queryClient.invalidateQueries({ queryKey: ['title', tmdbId] })
}

/** A film's reaction, tags and note, with saving and removing; rating a film also marks it watched. */
export function useReaction(tmdbId: number) {
  const queryClient = useQueryClient()
  const key = reactionKey(tmdbId)
  const state = useQuery({
    queryKey: key,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/titles/{tmdb_id}/reaction', {
        params: { path: { tmdb_id: tmdbId } },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
  })
  const save = useMutation({
    mutationFn: async (body: { reaction: Reaction; tags: string[]; note: string }) => {
      const { data, error } = await api.PUT('/api/v1/titles/{tmdb_id}/reaction', {
        params: { path: { tmdb_id: tmdbId } },
        body,
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    // Show the choice at once; the server's answer replaces it.
    onMutate: (body) => queryClient.setQueryData<TitleReaction>(key, (old) => old && { ...old, ...body }),
    onSuccess: (data) => {
      queryClient.setQueryData(key, data)
      refreshAfterReaction(queryClient, tmdbId)
    },
    onError: () => queryClient.invalidateQueries({ queryKey: key }),
  })
  const remove = useMutation({
    mutationFn: () => api.DELETE('/api/v1/titles/{tmdb_id}/reaction', { params: { path: { tmdb_id: tmdbId } } }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: key })
      refreshAfterReaction(queryClient, tmdbId)
    },
  })
  return { film: state.data, error: state.error, save, remove }
}

/** Rate a film in one click, without tags or a note, as from a card in a list. */
export function useQuickRate() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ tmdbId, reaction }: { tmdbId: number; reaction: Reaction }) => {
      const { data, error } = await api.PUT('/api/v1/titles/{tmdb_id}/reaction', {
        params: { path: { tmdb_id: tmdbId } },
        body: { reaction, tags: [], note: '' },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => {
      queryClient.setQueryData(reactionKey(data.tmdb_id), data)
      refreshAfterReaction(queryClient, data.tmdb_id)
    },
  })
}

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

/** Year, certificate, language, and running time. */
export function facts(film: {
  year: number | null
  certificate?: string | null
  original_language: string
  runtime: number | null
}) {
  return [
    film.year,
    film.certificate,
    languageName.of(film.original_language),
    film.runtime ? `${Math.floor(film.runtime / 60)}h ${film.runtime % 60}m` : null,
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
