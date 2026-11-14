import { createApiClient, type Reaction, type TitleDetail, type TitleReaction } from '@iwanttowatch/api-client'
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
      queryClient.invalidateQueries({ queryKey: ['radarr', 'shortlist'] })
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

/** The user's ratings import jobs. */
export function useImports() {
  return useQuery({
    queryKey: ['imports'],
    queryFn: async () => (await api.GET('/api/v1/imports')).data ?? [],
    refetchInterval: (query) =>
      query.state.data?.some((job) => job.status === 'pending' || job.status === 'running')
        ? 1500
        : false,
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

/** Converts a numeric 0–10 rating to the 3-point reaction scale. */
export function ratingToReaction(rating: number): Reaction {
  if (rating >= 9.0) return 'loved'
  if (rating >= 6.0) return 'liked'
  return 'disliked'
}

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
  great_cinematography: 'Stunning cinematography',
  great_pacing: 'Great pacing',
  creative_original: 'Original concept',
  great_chemistry: 'Great chemistry',
  atmospheric: 'Atmospheric',
  cozy_comfort: 'Cozy & comfort watch',
  dark_intense: 'Dark & intense',
  rewatchable: 'Highly rewatchable',
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
  pacing_issues: 'Pacing issues / Drags',
  flat_characters: 'Flat characters',
  plot_holes: 'Plot holes / Illogical',
  cringe_dialogue: 'Awkward dialogue',
  poor_cgi: 'Poor CGI / effects',
  wasted_potential: 'Wasted potential',
  boring: 'Boring',
  inconsistent_tone: 'Inconsistent tone',
}

export const NEGATIVE_TAG_IDS: ReadonlySet<string> = new Set([
  'weak_story',
  'predictable',
  'too_slow',
  'too_long',
  'unconvincing_acting',
  'disappointing_ending',
  'cliched',
  'too_violent',
  'not_funny',
  'not_scary',
  'confusing',
  'overhyped',
  'pacing_issues',
  'flat_characters',
  'plot_holes',
  'cringe_dialogue',
  'poor_cgi',
  'wasted_potential',
  'boring',
  'inconsistent_tone',
])

const reactionKey = (tmdbId: number) => ['reaction', tmdbId]

/** A rating changes what the user has seen, their taste, and what the feed and group picks offer. */
export function refreshAfterReaction(queryClient: QueryClient, tmdbId: number) {
  queryClient.invalidateQueries({ queryKey: ['ratings'] })
  queryClient.invalidateQueries({ queryKey: ['persona'] })
  // Rated films leave the feed and group picks.
  queryClient.invalidateQueries({ queryKey: ['feed'] })
  queryClient.invalidateQueries({ queryKey: ['together'] })
  queryClient.invalidateQueries({ queryKey: ['title', tmdbId] })
  queryClient.invalidateQueries({ queryKey: ['jellyfin', 'rating-prompts'] })
  queryClient.invalidateQueries({ queryKey: ['jellyfin', 'in-progress'] })
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
    mutationFn: async (body: { reaction?: Reaction | null; watched?: boolean; tags?: string[]; note?: string }) => {
      const { data, error } = await api.PUT('/api/v1/titles/{tmdb_id}/reaction', {
        params: { path: { tmdb_id: tmdbId } },
        body: {
          reaction: body.reaction ?? null,
          watched: body.watched ?? true,
          tags: body.tags ?? [],
          note: body.note ?? '',
        },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    // Show the choice at once; the server's answer replaces it.
    onMutate: (body) =>
      queryClient.setQueryData<TitleReaction>(key, (old) =>
        old
          ? {
              ...old,
              reaction: body.reaction !== undefined ? body.reaction : old.reaction,
              watched: body.watched !== undefined ? body.watched : true,
              tags: body.tags ?? old.tags,
              note: body.note !== undefined ? (body.note || null) : old.note,
            }
          : undefined,
      ),
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

/** Rate a film or mark as watched in one click, without tags or a note, as from a card in a list. */
export function useQuickRate() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      tmdbId,
      reaction,
      watched = true,
    }: {
      tmdbId: number
      reaction?: Reaction | null
      watched?: boolean
    }) => {
      const { data, error } = await api.PUT('/api/v1/titles/{tmdb_id}/reaction', {
        params: { path: { tmdb_id: tmdbId } },
        body: { reaction: reaction ?? null, watched, tags: [], note: '' },
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
 * ("jellyfin" or TMDb provider IDs), everything including films on none of them,
 * or only films unavailable to the user. */
export type WatchOn = 'anywhere' | 'everything' | 'unavailable' | string[]

export function watchOnQuery(watchOn: WatchOn) {
  return {
    available_only: watchOn !== 'everything' && watchOn !== 'unavailable',
    unavailable_only: watchOn === 'unavailable' || undefined,
    platforms: Array.isArray(watchOn) ? watchOn : undefined,
  }
}

/** Inspect streaming availability and Radarr status of shortlisted films. */
export function useRadarrShortlist(scope: 'user' | 'group' | 'all' = 'user', enabled = true) {
  return useQuery({
    queryKey: ['radarr', 'shortlist', scope],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/titles/shortlist/radarr', {
        params: { query: { scope } },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    enabled,
  })
}

/** Batch request unstreamable shortlisted films into Radarr. */
export function useRadarrBatchSync() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (variables?: { scope?: 'user' | 'group' | 'all'; tmdbIds?: number[] }) => {
      const scope = variables?.scope ?? 'user'
      const body = {
        scope,
        tmdb_ids: variables?.tmdbIds ?? null,
      }
      const { data, error } = await api.POST('/api/v1/titles/shortlist/radarr', {
        body,
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['radarr', 'shortlist'] })
      queryClient.invalidateQueries({ queryKey: ['title'] })
      queryClient.invalidateQueries({ queryKey: ['feed'] })
      queryClient.invalidateQueries({ queryKey: ['together'] })
    },
  })
}

/** Declutter inspection: fetch library prune candidates and storage metrics. */
export type DeclutterWhitelistFilter = 'hide' | 'only' | 'all'
export type DeclutterCategoriesMode = 'all' | 'any'

export function useDeclutterCandidates(
  category?: string | string[],
  whitelistFilter: DeclutterWhitelistFilter = 'hide',
  categoriesMode: DeclutterCategoriesMode = 'all',
  enabled = true,
) {
  const categoryParam = Array.isArray(category)
    ? category.filter((c) => c && c !== 'all').join(',')
    : category && category !== 'all'
      ? category
      : undefined

  return useQuery({
    queryKey: ['declutter', categoryParam, whitelistFilter, categoriesMode],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/library/declutter', {
        params: {
          query: {
            category: categoryParam || undefined,
            categories_mode: categoriesMode,
            whitelist: whitelistFilter,
            include_ignored: whitelistFilter !== 'hide',
          },
        },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    enabled,
  })
}

/** Batch delete prune candidates from Radarr. */
export function useDeleteDeclutterCandidates() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      tmdbIds,
      deleteFiles = true,
      addImportExclusion = false,
    }: {
      tmdbIds: number[]
      deleteFiles?: boolean
      addImportExclusion?: boolean
    }) => {
      const { data, error } = await api.POST('/api/v1/library/declutter/delete', {
        body: {
          tmdb_ids: tmdbIds,
          delete_files: deleteFiles,
          add_import_exclusion: addImportExclusion,
        },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['declutter'] })
      queryClient.invalidateQueries({ queryKey: ['feed'] })
      queryClient.invalidateQueries({ queryKey: ['title'] })
    },
  })
}

/** Whitelist/ignore or unignore a prune candidate. */
export function useIgnoreDeclutterCandidate() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ tmdbId, ignored }: { tmdbId: number; ignored: boolean }) => {
      const { data, error } = await api.POST('/api/v1/library/declutter/ignore', {
        body: { tmdb_id: tmdbId, ignored },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['declutter'] })
    },
  })
}

/** Radar: inspect unwatched high-match recommendations missing from streaming. */
export function useRadarMissing(minMatch = 70, scope: 'user' | 'group' = 'user', enabled = true) {
  return useQuery({
    queryKey: ['radar', 'missing', minMatch, scope],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/library/radar/missing', {
        params: {
          query: {
            min_match: minMatch,
            scope,
          },
        },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    enabled,
  })
}

/** Radar: discover high-taste theatrical releases and check Radarr tracking status. */
export function useRadarTheatrical(minMatch = 50, region?: string, enabled = true) {
  return useQuery({
    queryKey: ['radar', 'theatrical', minMatch, region],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/library/radar/theatrical', {
        params: {
          query: {
            min_match: minMatch,
            region: region || undefined,
          },
        },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    enabled,
  })
}

/** Radar: queue or track titles in Radarr. */
export function useRadarQueue() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      tmdbIds,
      minimumAvailability,
    }: {
      tmdbIds: number[]
      minimumAvailability?: string
    }) => {
      const { data, error } = await api.POST('/api/v1/library/radar/queue', {
        body: {
          tmdb_ids: tmdbIds,
          minimum_availability: minimumAvailability,
        },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['radar'] })
      queryClient.invalidateQueries({ queryKey: ['radarr'] })
      queryClient.invalidateQueries({ queryKey: ['title'] })
    },
  })
}

/** Lightweight title metadata used as an instant placeholder while full details load. */
export interface TitlePreview {
  title: string
  year?: number | null
  poster_path?: string | null
  match?: number | null
  imdb?: TitleDetail['imdb']
}

/** Fetch full title details without blocking on Radarr status. */
export async function fetchTitleDetail(tmdbId: number): Promise<TitleDetail> {
  const { data, error } = await api.GET('/api/v1/titles/{tmdb_id}', {
    params: { path: { tmdb_id: tmdbId }, query: { include_radarr: false } },
  })
  if (error) throw new Error(errorMessage(error))
  return data
}

/** A person's biography, credits, and affinity. */
export function usePerson(personId: number | null) {
  return useQuery({
    queryKey: ['person', personId],
    queryFn: async () => {
      if (!personId) return null
      const { data, error } = await api.GET('/api/v1/people/{person_id}', {
        params: { path: { person_id: personId } },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    enabled: personId !== null,
  })
}

/** Toggle favorite status for a person. */
export function useFavoritePerson() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      personId,
      favorite,
      name,
      role,
      profilePath,
    }: {
      personId: number
      favorite: boolean
      name?: string
      role?: string
      profilePath?: string | null
    }) => {
      const params = { params: { path: { person_id: personId } } }
      const { error } = favorite
        ? await api.PUT('/api/v1/people/{person_id}/favorite', {
            ...params,
            body: { name, role, profile_path: profilePath },
          })
        : await api.DELETE('/api/v1/people/{person_id}/favorite', params)
      if (error) throw new Error(errorMessage(error))
    },
    onSettled: (_, __, { personId }) => {
      queryClient.invalidateQueries({ queryKey: ['person', personId] })
      queryClient.invalidateQueries({ queryKey: ['people', 'favorites'] })
      queryClient.invalidateQueries({ queryKey: ['people', 'taste'] })
    },
  })
}

/** The user's favorited people. */
export function useFavoritePeople() {
  return useQuery({
    queryKey: ['people', 'favorites'],
    queryFn: async () => (await api.GET('/api/v1/people/favorites')).data ?? [],
  })
}

/** The user's people taste overview: favorites + top learned directors and actors. */
export function usePeopleTaste() {
  return useQuery({
    queryKey: ['people', 'taste'],
    queryFn: async () =>
      (await api.GET('/api/v1/people/taste')).data ?? {
        favorites: [],
        top_directors: [],
        top_actors: [],
      },
  })
}

/** Movies the user is currently watching on Jellyfin (in progress / resume). */
export function useInProgress(enabled = true) {
  return useQuery({
    queryKey: ['jellyfin', 'in-progress'],
    queryFn: async () => (await api.GET('/api/v1/me/in-progress')).data ?? [],
    enabled,
    refetchInterval: enabled ? 30_000 : false,
  })
}

/** Prompts to rate movies recently finished on Jellyfin. */
export function useRatingPrompts() {
  return useQuery({
    queryKey: ['jellyfin', 'rating-prompts'],
    queryFn: async () => (await api.GET('/api/v1/me/rating-prompts')).data ?? [],
    refetchInterval: 30_000,
  })
}

/** Dismiss a rating prompt without rating the movie. */
export function useDismissRatingPrompt() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (tmdbId: number) => {
      const { error } = await api.POST('/api/v1/me/rating-prompts/{tmdb_id}/dismiss', {
        params: { path: { tmdb_id: tmdbId } },
      })
      if (error) throw new Error(errorMessage(error))
    },
    onSuccess: (_, tmdbId) => {
      queryClient.setQueryData<Array<{ tmdb_id: number }>>(['jellyfin', 'rating-prompts'], (prev) =>
        prev ? prev.filter((p) => p.tmdb_id !== tmdbId) : []
      )
      queryClient.invalidateQueries({ queryKey: ['jellyfin', 'rating-prompts'] })
    },
  })
}
