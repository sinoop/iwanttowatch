import type { ChildProfile, FeedItem, FeedPage, FeedSort, InProgressItem, Me, RadarrShortlistStatus, RatingPromptItem, Reaction } from '@iwanttowatch/api-client'
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { api, errorMessage, facts, useChildren, useDismissRatingPrompt, useInProgress, useQuickRate, useRadarrBatchSync, useRadarrShortlist, useRatingPrompts, useServerSettings, useShortlist, watchOnQuery, type WatchOn } from './api'
import { QuickTags, ReactionIcon } from './RateDialog'
import HeaderSearch from './Search'
import { JellyfinLogo, PlatformFilter, WatchBadges } from './Streaming'
import TitleDialog, { AssignToChildButton, BookmarkIcon, Chips, DownloadIcon, ImdbBadge, MatchBadge } from './TitleDialog'
import { Button, ErrorText, Poster } from './ui'
import { YearFilter } from './YearFilter'

const languageName = new Intl.DisplayNames(['en'], { type: 'language' })
const PAGE = 24
// Below this many ratings the feed leans on quality rather than taste.
const FEW_RATINGS = 15
const TOAST_SECONDS = 10

type Toast =
  | { type: 'reaction'; item: FeedItem; reaction: Reaction | 'watched' }
  | { type: 'feedback'; item: FeedItem; kind: 'snoozed' | 'dismissed' }
type ShortlistFilter = 'all' | 'only' | 'hide'

export default function Discover({ me }: { me: Me }) {
  const settings = useServerSettings()
  const children = useChildren(!me.is_child)
  const [watchOn, setWatchOn] = useState<WatchOn>('anywhere')
  const [contentType, setContentType] = useState<string>(me.default_content_type ?? 'movies')
  const [language, setLanguage] = useState<string | null>(null)
  const [genre, setGenre] = useState<string | null>(null)
  const [decade, setDecade] = useState<number | null>(null)
  const [yearMin, setYearMin] = useState<number | null>(null)
  const [yearMax, setYearMax] = useState<number | null>(null)
  const [certificate, setCertificate] = useState<string | null>(null)
  const [shortlistFilter, setShortlistFilter] = useState<ShortlistFilter>('all')
  const [sort, setSort] = useState<FeedSort>('recommended')
  const [ageLimitOffFor, setAgeLimitOffFor] = useState<number | null>(null)
  const ageLimit = ageLimitOffFor !== me.id
  const setAgeLimit = (on: boolean) => setAgeLimitOffFor(on ? null : me.id)
  const [open, setOpen] = useState<number | null>(null)
  const [toast, setToast] = useState<Toast | null>(null)
  const queryClient = useQueryClient()
  const refreshFeed = () => queryClient.invalidateQueries({ queryKey: ['feed'] })

  const radarrShortlist = useRadarrShortlist(
    'user',
    shortlistFilter === 'only' && !!settings.data?.radarr.configured && !me.is_child
  )
  const batchSync = useRadarrBatchSync()
  const jellyfinAccount = useQuery({
    queryKey: ['me', 'jellyfin'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/me/jellyfin')
      if (error) throw new Error(errorMessage(error))
      return data
    },
    enabled: shortlistFilter === 'only' && !me.is_child,
  })
  const jellyfinSync = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST('/api/v1/jellyfin/sync-shortlist')
      if (error) throw new Error(errorMessage(error))
      return data
    },
  })
  const quickRate = useQuickRate()
  const feedback = useMutation({
    mutationFn: async ({ item, kind }: { item: FeedItem; kind: 'snoozed' | 'dismissed' }) => {
      const { error } = await api.PUT('/api/v1/titles/{tmdb_id}/feedback', {
        params: { path: { tmdb_id: item.tmdb_id } },
        body: { kind },
      })
      if (error) throw new Error(errorMessage(error))
    },
    onSuccess: (_, { item, kind }) => setToast({ type: 'feedback', item, kind }),
    onSettled: refreshFeed,
  })
  const undo = useMutation({
    mutationFn: (tmdbId: number) =>
      api.DELETE('/api/v1/titles/{tmdb_id}/feedback', { params: { path: { tmdb_id: tmdbId } } }),
    onSettled: refreshFeed,
  })
  const undoReaction = useMutation({
    mutationFn: (tmdbId: number) =>
      api.DELETE('/api/v1/titles/{tmdb_id}/reaction', { params: { path: { tmdb_id: tmdbId } } }),
    onSettled: refreshFeed,
  })
  const shortlist = useShortlist()
  const inProgress = useInProgress(me.show_continue_watching)
  const hideContinueWatching = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.PUT('/api/v1/me/profile', { body: { show_continue_watching: false } })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['me'], data)
      queryClient.invalidateQueries({ queryKey: ['jellyfin', 'in-progress'] })
    },
  })
  const ratingPrompts = useRatingPrompts()
  const dismissRatingPrompt = useDismissRatingPrompt()
  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(null), TOAST_SECONDS * 1000)
    return () => clearTimeout(timer)
  }, [toast])
  const act = (item: FeedItem, kind: 'snoozed' | 'dismissed') => feedback.mutate({ item, kind })
  const rateFilm = (item: FeedItem, reaction: Reaction | 'watched') => {
    quickRate.mutate({
      tmdbId: item.tmdb_id,
      reaction: reaction === 'watched' ? null : reaction,
      watched: true,
    })
    setToast({ type: 'reaction', item, reaction })
  }

  const ratings = useQuery({
    queryKey: ['ratings', 'count'],
    queryFn: async () => (await api.GET('/api/v1/ratings', { params: { query: { limit: 1 } } })).data?.total ?? 0,
  })
  const filters = {
    ...watchOnQuery(watchOn),
    language: language ?? undefined,
    genre: genre ?? undefined,
    decade: decade ?? undefined,
    year_min: yearMin ?? undefined,
    year_max: yearMax ?? undefined,
    content_type: contentType,
    max_certificate: !me.is_child ? (certificate ?? undefined) : undefined,
    shortlist: shortlistFilter === 'only' || undefined,
    hide_shortlisted: shortlistFilter === 'hide' || undefined,
    age_limit: me.max_certificate ? ageLimit : undefined,
  }

  const feed = useInfiniteQuery({
    queryKey: ['feed', me.id, watchOn, language, genre, decade, yearMin, yearMax, contentType, certificate, shortlistFilter, sort, ageLimit],
    queryFn: async ({ pageParam }) => {
      const { data, error } = await api.GET('/api/v1/feed', {
        params: {
          query: {
            ...filters,
            sort: sort !== 'recommended' ? sort : undefined,
            offset: pageParam,
            limit: PAGE,
          },
        },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, p) => n + p.items.length, 0)
      return loaded < last.total ? loaded : undefined
    },
    placeholderData: (previous) => previous,
    // While the feed is being built or re-ranked, watch its progress.
    refetchInterval: (query) => {
      const page = query.state.data?.pages[0]
      return building(page) ? 2000 : page?.rescoring ? 3000 : false
    },
  })

  const first = feed.data?.pages[0]
  const items = feed.data?.pages.flatMap((p) => p.items) ?? []
  const tmdbMissing = settings.data && !settings.data.tmdb_configured

  return (
    <>
      <div className="w-full">
        <HeaderSearch className="w-full" />
      </div>

      {tmdbMissing ? (
        <NextStep to={me.is_admin ? '/settings/integrations' : '/settings/profile'} action="Open Settings">
          {me.is_admin
            ? 'First, add a free TMDb API key so iWantToWatch can look up movies.'
            : 'Ask your admin to add a TMDb API key so iWantToWatch can look up movies.'}
        </NextStep>
      ) : (
        ratings.data !== undefined &&
        ratings.data < FEW_RATINGS && (
          <NextStep to="/settings/imports" action="Import ratings">
            {ratings.data === 0
              ? 'These picks are well-loved films, not yet yours. Import your IMDb or Letterboxd ratings to teach iWantToWatch your taste.'
              : `Only ${ratings.data} ratings so far. Import your IMDb or Letterboxd history for picks that match your taste.`}
          </NextStep>
        )
      )}



      {/* Prompts for movies recently finished on Jellyfin */}
      {ratingPrompts.data && ratingPrompts.data.length > 0 && (
        <RatingPromptBanner
          prompt={ratingPrompts.data[0]}
          onRate={(reaction) => {
            const p = ratingPrompts.data[0]
            rateFilm({ tmdb_id: p.tmdb_id, title: p.title } as FeedItem, reaction)
            dismissRatingPrompt.mutate(p.tmdb_id)
          }}
          onDismiss={() => dismissRatingPrompt.mutate(ratingPrompts.data[0].tmdb_id)}
          onOpen={() => setOpen(ratingPrompts.data[0].tmdb_id)}
        />
      )}

      {/* Movies in progress / continue watching on Jellyfin */}
      {me.show_continue_watching && inProgress.data && inProgress.data.length > 0 && (
        <ContinueWatchingShelf
          items={inProgress.data}
          onOpen={(tmdbId) => setOpen(tmdbId)}
          onHide={() => hideContinueWatching.mutate()}
        />
      )}

      {first && (
        <Filters
          page={first}
          maxCertificate={me.max_certificate ?? null}
          ageLimit={ageLimit}
          onAgeLimit={setAgeLimit}
          watchOn={watchOn}
          onWatchOn={setWatchOn}
          contentType={contentType}
          onContentType={setContentType}
          defaultContentType={me.default_content_type ?? 'movies'}
          language={language}
          onLanguage={setLanguage}
          genre={genre}
          onGenre={setGenre}
          decade={decade}
          onDecade={setDecade}
          yearMin={yearMin}
          yearMax={yearMax}
          onYearRange={(min, max) => {
            setYearMin(min)
            setYearMax(max)
          }}
          certificate={!me.is_child ? certificate : null}
          onCertificate={setCertificate}
          shortlistFilter={shortlistFilter}
          onShortlistFilter={setShortlistFilter}
          sort={sort}
          onSort={setSort}
          radarrShortlist={radarrShortlist.data}
          batchSync={batchSync}
          jellyfinLinked={!!jellyfinAccount.data?.linked}
          jellyfinSync={jellyfinSync}
        />
      )}

      {(feedback.error || shortlist.error || batchSync.error || jellyfinSync.error) && (
        <div className="mt-6">
          <ErrorText>
            {(feedback.error ?? shortlist.error ?? batchSync.error ?? jellyfinSync.error)?.message}
          </ErrorText>
        </div>
      )}
      {feed.error && (
        <div className="mt-6">
          <ErrorText>{feed.error.message}</ErrorText>
        </div>
      )}
      {first && <BuildStatus page={first} empty={items.length === 0} />}
      {first?.status === 'ready' && items.length === 0 && (
        <EmptyFeed
          emptyShortlist={shortlistFilter === 'only' && first.shortlist_count === 0}
          filtered={
            language !== null ||
            genre !== null ||
            decade !== null ||
            yearMin !== null ||
            yearMax !== null ||
            (!me.is_child && certificate !== null) ||
            shortlistFilter === 'hide'
          }
          watchOn={watchOn}
          onWatchOn={setWatchOn}
          onClearFilters={() => {
            setLanguage(null)
            setGenre(null)
            setDecade(null)
            setYearMin(null)
            setYearMax(null)
            setCertificate(null)
            if (shortlistFilter !== 'all') setShortlistFilter('all')
            if (contentType !== (me.default_content_type ?? 'movies')) setContentType(me.default_content_type ?? 'movies')
          }}
        />
      )}

      {items.length > 0 && (
        <ul className="mt-6 grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-3 lg:grid-cols-4" aria-label="Recommendations">
          {items.map((item) => (
            <FeedCard
              key={item.tmdb_id}
              item={item}
              childProfiles={me.is_child ? [] : (children.data ?? [])}
              onOpen={() => setOpen(item.tmdb_id)}
              onRate={(reaction) => rateFilm(item, reaction)}
              onAct={(kind) => act(item, kind)}
              onShortlist={() => shortlist.mutate({ tmdbId: item.tmdb_id, save: !item.shortlisted })}
              busy={
                (quickRate.isPending && quickRate.variables?.tmdbId === item.tmdb_id) ||
                (feedback.isPending && feedback.variables?.item.tmdb_id === item.tmdb_id) ||
                (undo.isPending && undo.variables === item.tmdb_id) ||
                (undoReaction.isPending && undoReaction.variables === item.tmdb_id) ||
                (shortlist.isPending && shortlist.variables.tmdbId === item.tmdb_id)
              }
            />
          ))}
        </ul>
      )}
      {feed.hasNextPage && (
        <div className="mt-6 flex justify-center">
          <Button variant="ghost" onClick={() => feed.fetchNextPage()} disabled={feed.isFetchingNextPage}>
            {feed.isFetchingNextPage ? 'Loading…' : `Show more (${(first?.total ?? 0) - items.length} left)`}
          </Button>
        </div>
      )}

      <TitleDialog tmdbId={open} onClose={() => setOpen(null)} />
      {toast && (
        <UndoToast
          key={
            toast.type === 'reaction'
              ? `${toast.item.tmdb_id}-${toast.reaction}`
              : `${toast.item.tmdb_id}-${toast.kind}`
          }
          toast={toast}
          onUndo={() => {
            if (toast.type === 'reaction') {
              undoReaction.mutate(toast.item.tmdb_id)
            } else {
              undo.mutate(toast.item.tmdb_id)
            }
            setToast(null)
          }}
          onMore={() => {
            setOpen(toast.item.tmdb_id)
            setToast(null)
          }}
        />
      )}
    </>
  )
}

function building(page: FeedPage | undefined) {
  return page?.status === 'none' || page?.status === 'queued' || page?.status === 'building'
}

function RefreshButton({
  page,
  language,
  genre,
  contentType,
}: {
  page: FeedPage
  language: string | null
  genre: string | null
  contentType?: string
}) {
  const queryClient = useQueryClient()
  const targetFilters =
    (language !== null || genre !== null || (contentType && contentType !== 'movies')) && page.total < 25
  const refresh = useMutation({
    mutationFn: () =>
      api.POST('/api/v1/feed/refresh', {
        params: {
          query: {
            language: targetFilters ? (language ?? undefined) : undefined,
            genre: targetFilters ? (genre ?? undefined) : undefined,
            content_type: targetFilters ? (contentType ?? undefined) : undefined,
          },
        },
      }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['feed'] }),
  })
  return (
    <div className="flex items-center gap-2 text-xs text-white/45">
      <button
        type="button"
        className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-black/30 px-3 py-1.5 text-sm font-medium text-white/80 hover:border-white/25 hover:text-white disabled:opacity-40 transition-colors cursor-pointer"
        onClick={() => refresh.mutate()}
        disabled={refresh.isPending || building(page)}
        title={
          page.built_at
            ? `Updated ${new Date(page.built_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}`
            : undefined
        }
      >
        <svg
          viewBox="0 0 20 20"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          className={`size-3.5 ${refresh.isPending || building(page) ? 'animate-spin' : ''}`}
          aria-hidden="true"
        >
          <path
            d="M3.5 10a6.5 6.5 0 1 1 1.9 4.6M3.5 15V10h5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <span>{refresh.isPending ? 'Refreshing…' : 'Refresh'}</span>
      </button>
      {page.rescoring ? (
        <span role="status" className="text-xs text-accent-strong">
          Re-ranking with your feedback…
        </span>
      ) : page.built_at ? (
        <span className="hidden sm:inline text-xs text-white/40">
          Updated {new Date(page.built_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}
        </span>
      ) : null}
    </div>
  )
}

function SlidersIcon({ className = 'size-4' }: { className?: string }) {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" className={className} aria-hidden="true">
      <path d="M3 5h8M15 5h2M3 10h2M9 10h8M3 15h11M18 15h-1" strokeLinecap="round" />
      <circle cx="13" cy="5" r="2" />
      <circle cx="7" cy="10" r="2" />
      <circle cx="16" cy="15" r="2" />
    </svg>
  )
}

function Filters({
  page,
  maxCertificate,
  ageLimit,
  onAgeLimit,
  watchOn,
  onWatchOn,
  contentType,
  onContentType,
  defaultContentType,
  language,
  onLanguage,
  genre,
  onGenre,
  decade,
  onDecade,
  yearMin,
  yearMax,
  onYearRange,
  certificate,
  onCertificate,
  shortlistFilter,
  onShortlistFilter,
  sort,
  onSort,
  radarrShortlist,
  batchSync,
  jellyfinLinked,
  jellyfinSync,
}: {
  page: FeedPage
  maxCertificate: string | null
  ageLimit: boolean
  onAgeLimit: (value: boolean) => void
  watchOn: WatchOn
  onWatchOn: (value: WatchOn) => void
  contentType: string
  onContentType: (value: string) => void
  defaultContentType: string
  language: string | null
  onLanguage: (value: string | null) => void
  genre: string | null
  onGenre: (value: string | null) => void
  decade: number | null
  onDecade: (value: number | null) => void
  yearMin: number | null
  yearMax: number | null
  onYearRange: (min: number | null, max: number | null) => void
  certificate: string | null
  onCertificate: (value: string | null) => void
  shortlistFilter: ShortlistFilter
  onShortlistFilter: (value: ShortlistFilter) => void
  sort: FeedSort
  onSort: (value: FeedSort) => void
  radarrShortlist?: RadarrShortlistStatus | null
  batchSync?: ReturnType<typeof useRadarrBatchSync>
  jellyfinLinked?: boolean
  jellyfinSync?: {
    isPending: boolean
    data?: { synced_count: number; skipped_count: number; playlist_name: string }
    mutate: () => void
  }
}) {
  const [expanded, setExpanded] = useState(false)

  const filterSelectClass = (active: boolean) =>
    `rounded-lg border px-3 py-1.5 text-sm outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-accent/30 cursor-pointer ${
      active
        ? 'border-accent/60 bg-accent/15 text-accent-strong font-medium shadow-xs'
        : 'border-white/10 bg-black/30 text-white/80 hover:border-white/25 hover:text-white'
    }`

  const panelSelectClass = (active: boolean) =>
    `w-full rounded-lg border px-3 py-2 text-sm outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-accent/30 cursor-pointer ${
      active
        ? 'border-accent/60 bg-accent/15 text-accent-strong font-medium'
        : 'border-white/10 bg-black/40 text-white/90 hover:border-white/25'
    }`

  // Keep a chosen filter visible even when it no longer matches anything.
  const languages = page.languages.map((l) => l.language)
  if (language && !languages.includes(language)) languages.push(language)
  const genres = genre && !page.genres.includes(genre) ? [...page.genres, genre] : page.genres
  const certificates =
    certificate && !page.certificates.includes(certificate)
      ? [...page.certificates, certificate]
      : page.certificates

  // Build active filter chips for quick removal
  interface ActiveChip {
    id: string
    label: string
    onRemove: () => void
  }
  const activeChips: ActiveChip[] = []

  if (genre !== null) {
    activeChips.push({
      id: 'genre',
      label: `Genre: ${genre}`,
      onRemove: () => onGenre(null),
    })
  }

  if (yearMin !== null || yearMax !== null) {
    const rangeLabel =
      yearMin !== null && yearMax !== null
        ? `${yearMin}–${yearMax}`
        : yearMin !== null
          ? `From ${yearMin}`
          : `Until ${yearMax}`
    activeChips.push({
      id: 'yearRange',
      label: `Years: ${rangeLabel}`,
      onRemove: () => onYearRange(null, null),
    })
  } else if (decade !== null) {
    activeChips.push({
      id: 'decade',
      label: `${decade}s`,
      onRemove: () => onDecade(null),
    })
  }

  if (language !== null) {
    activeChips.push({
      id: 'language',
      label: `Language: ${languageName.of(language) ?? language}`,
      onRemove: () => onLanguage(null),
    })
  }

  if (contentType !== defaultContentType) {
    const typeLabels: Record<string, string> = {
      movies: 'Movies only',
      standup: 'Stand-up comedy',
      concerts: 'Concerts & Live',
      all: 'All content',
    }
    activeChips.push({
      id: 'contentType',
      label: typeLabels[contentType] ?? contentType,
      onRemove: () => onContentType(defaultContentType),
    })
  }

  if (shortlistFilter !== 'all') {
    activeChips.push({
      id: 'shortlist',
      label: shortlistFilter === 'only' ? 'Shortlist only' : 'Hide shortlisted',
      onRemove: () => onShortlistFilter('all'),
    })
  }

  if (!maxCertificate && certificate !== null) {
    activeChips.push({
      id: 'certificate',
      label: `Rated ${certificate} & under`,
      onRemove: () => onCertificate(null),
    })
  } else if (maxCertificate && !ageLimit) {
    activeChips.push({
      id: 'ageLimit',
      label: 'Age restriction: Off',
      onRemove: () => onAgeLimit(true),
    })
  }

  const secondaryActiveCount = activeChips.filter((c) => c.id !== 'genre').length

  const clearAllFilters = () => {
    onGenre(null)
    onDecade(null)
    onYearRange(null, null)
    onLanguage(null)
    onCertificate(null)
    onShortlistFilter('all')
    onContentType(defaultContentType)
    if (maxCertificate) onAgeLimit(true)
  }

  return (
    <div className="mt-6 space-y-3">
      {/* Primary Filter Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-2.5">
        <div className="flex flex-wrap items-center gap-2">
          {/* Where to watch */}
          <PlatformFilter platforms={page.platforms} value={watchOn} onChange={onWatchOn} />

          {/* Genre quick selector */}
          {genres.length > 0 && (
            <select
              value={genre ?? ''}
              onChange={(e) => onGenre(e.target.value || null)}
              aria-label="Genre"
              className={filterSelectClass(genre !== null)}
            >
              <option value="">All genres</option>
              {genres.map((g) => (
                <option key={g} value={g}>
                  {g}
                </option>
              ))}
            </select>
          )}
          {/* Sort order */}
          <select
            value={sort}
            onChange={(e) => onSort(e.target.value as FeedSort)}
            aria-label="Order by"
            className={filterSelectClass(sort !== 'recommended')}
          >
            <option value="recommended">Recommended</option>
            <option value="match">Highest match</option>
            <option value="rating">Highest rated</option>
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
            <option value="shortest">Shortest first</option>
          </select>

          {/* More Filters button with active count badge */}
          <button
            type="button"
            onClick={() => setExpanded((prev) => !prev)}
            aria-expanded={expanded}
            className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors cursor-pointer ${
              expanded || secondaryActiveCount > 0
                ? 'border-accent/60 bg-accent/15 text-accent-strong shadow-xs'
                : 'border-white/10 bg-black/30 text-white/80 hover:border-white/25 hover:text-white'
            }`}
          >
            <SlidersIcon className="size-3.5" />
            <span>Filters</span>
            {secondaryActiveCount > 0 && (
              <span className="rounded-full bg-accent px-1.5 py-0.2 text-[10px] font-bold text-black leading-tight">
                {secondaryActiveCount}
              </span>
            )}
            <svg
              viewBox="0 0 20 20"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className={`size-3 text-white/50 transition-transform ${expanded ? 'rotate-180' : ''}`}
            >
              <path d="m5 7.5 5 5 5-5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>

          {/* Refresh button next to filter dropdowns */}
          <RefreshButton page={page} language={language} genre={genre} contentType={contentType} />
        </div>

        {/* Right side: Radarr batch sync & Jellyfin playlist sync if shortlist only is selected */}
        {shortlistFilter === 'only' && (
          <div className="flex flex-wrap items-center gap-2">
            {radarrShortlist?.configured && (
              <>
                {radarrShortlist.to_request_count > 0 && (
                  <button
                    type="button"
                    disabled={batchSync?.isPending}
                    onClick={() => batchSync?.mutate({ scope: 'user' })}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-sky-500/40 bg-sky-500/10 px-3 py-1.5 text-xs font-medium text-sky-200 hover:bg-sky-500/20 disabled:opacity-50 transition-colors cursor-pointer"
                    title="Batch request unstreamable shortlisted films to Radarr"
                  >
                    <DownloadIcon className="size-3.5" />
                    {batchSync?.isPending
                      ? 'Requesting…'
                      : `Download via Radarr (${radarrShortlist.to_request_count})`}
                  </button>
                )}
                {radarrShortlist.to_request_count === 0 && radarrShortlist.unstreamable_count > 0 && (
                  <span className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-xs text-white/60">
                    {radarrShortlist.downloading_count > 0 ? (
                      <>
                        <span className="text-amber-400">⏳</span> {radarrShortlist.downloading_count} downloading in Radarr
                      </>
                    ) : (
                      <>
                        <span className="text-emerald-400">✓</span> Radarr synced
                      </>
                    )}
                  </span>
                )}
                {batchSync?.data && (
                  <span className="inline-flex items-center text-xs text-emerald-400">
                    ✓ Queued {batchSync.data.requested_count} film(s)
                  </span>
                )}
              </>
            )}
            {jellyfinLinked && (
              <>
                <button
                  type="button"
                  disabled={jellyfinSync?.isPending}
                  onClick={() => jellyfinSync?.mutate()}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-500/40 bg-indigo-500/10 px-3 py-1.5 text-xs font-medium text-indigo-200 hover:bg-indigo-500/20 disabled:opacity-50 transition-colors cursor-pointer"
                  title="Sync shortlisted movies on Jellyfin into a Jellyfin playlist"
                >
                  <JellyfinLogo className="size-3.5" />
                  {jellyfinSync?.isPending ? 'Syncing…' : 'Sync to Jellyfin playlist'}
                </button>
                {jellyfinSync?.data && (
                  <span className="inline-flex items-center text-xs text-emerald-400">
                    ✓ Synced {jellyfinSync.data.synced_count} film(s)
                    {jellyfinSync.data.skipped_count > 0
                      ? ` (${jellyfinSync.data.skipped_count} not in Jellyfin)`
                      : ''}
                  </span>
                )}
              </>
            )}
          </div>
        )}
      </div>

      {/* Expandable Detailed Filters Drawer */}
      {expanded && (
        <div className="rounded-2xl border border-white/10 bg-[#131722]/95 p-4 shadow-xl backdrop-blur-md">
          <div className="mb-3.5 flex items-center justify-between border-b border-white/10 pb-2.5 text-xs">
            <span className="font-semibold uppercase tracking-wider text-white/50">Detailed filters</span>
            <div className="flex items-center gap-3">
              {activeChips.length > 0 && (
                <button
                  type="button"
                  onClick={clearAllFilters}
                  className="font-medium text-white/60 hover:text-accent transition cursor-pointer"
                >
                  Reset all
                </button>
              )}
              <button
                type="button"
                onClick={() => setExpanded(false)}
                className="text-white/60 hover:text-white transition cursor-pointer"
              >
                Done
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-4">
            {/* Shortlist Filter */}
            <div>
              <label className="mb-1 block text-xs font-medium text-white/60">Shortlist</label>
              <select
                value={shortlistFilter}
                onChange={(e) => onShortlistFilter(e.target.value as ShortlistFilter)}
                aria-label="Shortlist"
                className={panelSelectClass(shortlistFilter !== 'all')}
              >
                <option value="all">All films</option>
                <option value="only">Shortlist only ({page.shortlist_count})</option>
                <option value="hide">Hide shortlisted ({page.shortlist_count})</option>
              </select>
            </div>

            {/* Format / Content Type */}
            <div>
              <label className="mb-1 block text-xs font-medium text-white/60">Format</label>
              <select
                value={contentType}
                onChange={(e) => onContentType(e.target.value)}
                aria-label="Content type"
                className={panelSelectClass(contentType !== defaultContentType)}
              >
                <option value="movies">Movies only</option>
                <option value="standup">Stand-up comedy</option>
                <option value="concerts">Concerts &amp; Live</option>
                <option value="all">All content</option>
              </select>
            </div>

            {/* Decade & Year Range */}
            <div>
              <label className="mb-1 block text-xs font-medium text-white/60">Decade / Era</label>
              <YearFilter
                decades={page.decades ?? []}
                decade={decade}
                yearMin={yearMin}
                yearMax={yearMax}
                onDecade={onDecade}
                onYearRange={onYearRange}
                allLabel="All decades"
                ariaLabel="Decade"
                selectClass={panelSelectClass}
              />
            </div>

            {/* Language */}
            {(languages.length > 1 || language) && (
              <div>
                <label className="mb-1 block text-xs font-medium text-white/60">Language</label>
                <select
                  value={language ?? ''}
                  onChange={(e) => onLanguage(e.target.value || null)}
                  aria-label="Language"
                  className={panelSelectClass(language !== null)}
                >
                  <option value="">All languages</option>
                  {languages.map((code) => (
                    <option key={code} value={code}>
                      {languageName.of(code)}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {/* Age Rating (Adult) */}
            {!maxCertificate && certificates.length > 0 && (
              <div>
                <label className="mb-1 block text-xs font-medium text-white/60">Age rating</label>
                <select
                  value={certificate ?? ''}
                  onChange={(e) => onCertificate(e.target.value || null)}
                  aria-label="Age rating"
                  className={panelSelectClass(certificate !== null)}
                >
                  <option value="">All age ratings</option>
                  {certificates.map((cert) => (
                    <option key={cert} value={cert}>
                      Rated {cert} &amp; under
                    </option>
                  ))}
                </select>
              </div>
            )}

            {/* Age Restriction (Child) */}
            {maxCertificate && (
              <div>
                <label className="mb-1 block text-xs font-medium text-white/60">Age limit</label>
                <div className="flex items-center gap-1">
                  <select
                    value={ageLimit ? 'on' : 'off'}
                    onChange={(e) => onAgeLimit(e.target.value === 'on')}
                    aria-label="Age restriction"
                    className={panelSelectClass(ageLimit)}
                  >
                    <option value="on">Rated {maxCertificate} &amp; under</option>
                    <option value="off">All age ratings</option>
                  </select>
                  {ageLimit && (
                    <button
                      type="button"
                      title="Remove age restriction filter"
                      aria-label="Remove age restriction filter"
                      onClick={() => onAgeLimit(false)}
                      className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-black/40 text-sm text-white/60 hover:border-white/25 hover:text-white transition cursor-pointer"
                    >
                      ×
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Active Filter Chips */}
      {activeChips.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 pt-1 text-xs">
          <span className="text-[11px] font-medium text-white/40 mr-1">Active filters:</span>
          {activeChips.map((chip) => (
            <span
              key={chip.id}
              className="inline-flex items-center gap-1.5 rounded-full border border-accent/40 bg-accent/10 px-2.5 py-1 text-xs font-medium text-accent-strong"
            >
              <span>{chip.label}</span>
              <button
                type="button"
                onClick={chip.onRemove}
                aria-label={`Remove filter ${chip.label}`}
                className="rounded-full p-0.5 text-accent-strong hover:bg-accent/25 transition cursor-pointer"
              >
                <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" className="size-3">
                  <path d="M4 4l8 8M12 4l-8 8" strokeLinecap="round" />
                </svg>
              </button>
            </span>
          ))}
          <button
            type="button"
            onClick={clearAllFilters}
            className="ml-1 text-xs text-white/50 hover:text-white underline underline-offset-2 transition cursor-pointer"
          >
            Clear all
          </button>
        </div>
      )}
    </div>
  )
}

function BuildStatus({ page, empty }: { page: FeedPage; empty: boolean }) {
  const queryClient = useQueryClient()
  const retry = useMutation({
    mutationFn: () => api.POST('/api/v1/feed/refresh'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['feed'] }),
  })
  if (page.status === 'failed') {
    return (
      <div className="mt-6 flex flex-wrap items-center gap-3 rounded-xl border border-red-400/20 bg-red-500/5 p-4 text-sm">
        <p role="alert" className="flex-1 text-red-200">
          {empty ? 'Your feed couldn’t be built' : 'Updating your feed failed; showing the last one'}
          {page.error ? `: ${page.error}` : '.'}
        </p>
        <Button variant="ghost" onClick={() => retry.mutate()} disabled={retry.isPending}>
          Try again
        </Button>
      </div>
    )
  }
  if (!building(page)) return null
  return (
    <div
      role="status"
      className={`mt-6 flex items-center gap-3 rounded-xl border border-white/10 text-sm text-white/70 ${empty ? 'p-8' : 'p-3'}`}
    >
      <span className="size-4 shrink-0 animate-spin rounded-full border-2 border-white/20 border-t-accent" aria-hidden />
      <span>
        {empty ? 'Building your feed' : 'Updating your feed'}
        {page.step ? ` — ${page.step.charAt(0).toLowerCase()}${page.step.slice(1)}` : ''}…
      </span>
    </div>
  )
}

function EmptyFeed({
  emptyShortlist,
  filtered,
  watchOn,
  onWatchOn,
  onClearFilters,
}: {
  emptyShortlist: boolean
  filtered: boolean
  watchOn: WatchOn
  onWatchOn: (value: WatchOn) => void
  onClearFilters: () => void
}) {
  return (
    <div className="mt-6 rounded-xl border border-dashed border-white/15 p-6 text-sm text-white/60">
      {emptyShortlist ? (
        'Your shortlist is empty. Save films with the bookmark on any card to choose from later.'
      ) : filtered ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span>No picks match these filters.</span>
          <Button variant="ghost" onClick={onClearFilters}>
            Clear filters
          </Button>
        </div>
      ) : Array.isArray(watchOn) ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span>None of your picks are on the platforms you chose.</span>
          <Button variant="ghost" onClick={() => onWatchOn('anywhere')}>
            Show what’s available to me
          </Button>
        </div>
      ) : watchOn === 'unavailable' ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span>None of your picks are unavailable to you.</span>
          <Button variant="ghost" onClick={() => onWatchOn('anywhere')}>
            Show what’s available to me
          </Button>
        </div>
      ) : watchOn === 'anywhere' ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span>
            None of your picks are on your Jellyfin server or your streaming services. Choose your services in{' '}
            <Link to="/settings/streaming" className="text-accent underline-offset-2 hover:underline">
              Settings
            </Link>
            , or see every pick.
          </span>
          <Button variant="ghost" onClick={() => onWatchOn('everything')}>
            Show all picks
          </Button>
        </div>
      ) : (
        'No picks yet. Import some ratings, then refresh your feed.'
      )}
    </div>
  )
}

function FeedCard({
  item,
  childProfiles,
  fit,
  onOpen,
  onRate,
  onAct,
  onShortlist,
  busy,
}: {
  item: FeedItem
  childProfiles: ChildProfile[]
  // How the film fits the user's request, when it's one of the AI's picks.
  fit?: string
  onOpen: () => void
  onRate: (reaction: Reaction | 'watched') => void
  onAct: (kind: 'snoozed' | 'dismissed') => void
  onShortlist: () => void
  busy: boolean
}) {
  return (
    <li className="flex flex-col">
      <div className="group relative rounded-lg">
        <button
          type="button"
          onClick={onOpen}
          className="block w-full rounded-lg text-left focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:outline-none"
          aria-label={`${item.title}, ${item.match}% match${item.imdb ? `, IMDb ${item.imdb.rating.toFixed(1)}` : ''}`}
        >
          <Poster
            path={item.poster_path}
            title={item.title}
            className="transition-shadow group-hover:ring-2 group-hover:ring-accent"
          />
          <div className="absolute top-2 left-2 flex items-center gap-1.5">
            <MatchBadge match={item.match} className="shadow-lg shadow-black/50" />
            {item.imdb && <ImdbBadge imdb={item.imdb} className="shadow-lg shadow-black/50" />}
          </div>
        </button>
        <div
          className="absolute bottom-2 left-2 z-10 flex items-center gap-0.5 rounded-full border border-white/15 bg-black/60 p-0.5 shadow-xl shadow-black/50 backdrop-blur-md"
          role="group"
          aria-label={`Rate or mark ${item.title}`}
          onClick={(e) => e.stopPropagation()}
        >
          <CardAction
            label="Watched"
            disabled={busy}
            onClick={() => onRate('watched')}
            className="text-white/70 hover:bg-white/15"
          >
            <ReactionIcon reaction="watched" className="size-4" />
          </CardAction>
          <CardAction
            label="Didn’t like"
            disabled={busy}
            onClick={() => onRate('disliked')}
            className="text-white/70 hover:bg-white/15"
          >
            <ReactionIcon reaction="disliked" className="size-4" />
          </CardAction>
          <CardAction
            label="Liked"
            disabled={busy}
            onClick={() => onRate('liked')}
            className="text-white/70 hover:bg-white/15"
          >
            <ReactionIcon reaction="liked" className="size-4" />
          </CardAction>
          <CardAction
            label="Loved"
            disabled={busy}
            onClick={() => onRate('loved')}
            className="text-white/70 hover:bg-white/15"
          >
            <ReactionIcon reaction="loved" className="size-4" />
          </CardAction>
        </div>
      </div>
      <div className="mt-1.5 flex items-center justify-end" role="group" aria-label={`Actions for ${item.title}`}>
        <CardAction
          label={item.shortlisted ? 'Remove from shortlist' : 'Add to shortlist'}
          pressed={item.shortlisted}
          disabled={busy}
          onClick={onShortlist}
        >
          <BookmarkIcon filled={item.shortlisted} />
        </CardAction>
        <AssignToChildButton
          compact
          tmdbId={item.tmdb_id}
          title={item.title}
          assigned={item.assigned_children ?? []}
          childProfiles={childProfiles}
        />
        <CardAction label="Not now (hide for 30 days)" disabled={busy} onClick={() => onAct('snoozed')}>
          <Icon d="M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0M12 6v6l4 2" />
        </CardAction>
        <CardAction label="Not interested" disabled={busy} onClick={() => onAct('dismissed')}>
          <Icon d="M18 6 6 18M6 6l12 12" />
        </CardAction>
      </div>
      <h2 className="mt-1 text-sm leading-snug font-medium">{item.title}</h2>
      <p className="text-xs text-white/50">{facts(item).join(' · ')}</p>
      <WatchBadges availability={item.availability} />
      <Chips genres={item.genres} moods={item.moods} max={3} className="mt-2" />
      {fit ? (
        <p className="mt-1.5 line-clamp-3 text-xs text-accent-strong/80">{fit}</p>
      ) : (
        item.reasons[0] && <p className="mt-1.5 line-clamp-2 text-xs text-white/50">{item.reasons[0]}</p>
      )}
    </li>
  )
}

function CardAction({
  label,
  pressed,
  disabled,
  onClick,
  children,
  className = '',
}: {
  label: string
  pressed?: boolean
  disabled: boolean
  onClick: () => void
  children: ReactNode
  className?: string
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={pressed}
      disabled={disabled}
      onClick={onClick}
      className={`flex size-8 items-center justify-center rounded-full transition-colors focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:outline-none disabled:opacity-40 ${
        pressed ? 'bg-accent/15 text-accent-strong' : 'text-white/45 hover:bg-white/10 hover:text-white'
      } ${className}`}
    >
      {children}
    </button>
  )
}

function Icon({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" className="size-4" aria-hidden="true">
      <path d={d} fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function UndoToast({
  toast,
  onUndo,
  onMore,
}: {
  toast: Toast
  onUndo: () => void
  onMore: () => void
}) {
  if (toast.type === 'reaction') {
    const label =
      toast.reaction === 'watched'
        ? 'Watched'
        : toast.reaction === 'loved'
          ? 'Loved'
          : toast.reaction === 'liked'
            ? 'Liked'
            : 'Didn’t like'
    return (
      <div
        role="status"
        className="fixed inset-x-4 bottom-4 z-10 mx-auto flex max-w-xl flex-col gap-2 rounded-xl border border-accent/30 bg-[#1a1e27] p-3 text-sm shadow-2xl shadow-black/80 sm:p-3.5"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="flex items-center gap-1 font-semibold text-accent-strong">
              <ReactionIcon reaction={toast.reaction} className="size-4" />
              {label}
            </span>
            <span className="truncate">
              <strong>{toast.item.title}</strong> · Marked as watched
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <Button variant="ghost" className="px-2.5 py-1 text-xs" onClick={onMore}>
              More tags / note…
            </Button>
            <Button variant="ghost" className="px-2.5 py-1 text-xs" onClick={onUndo}>
              Undo
            </Button>
          </div>
        </div>
        {toast.reaction !== 'watched' && <QuickTags tmdbId={toast.item.tmdb_id} />}
      </div>
    )
  }

  return (
    <div
      role="status"
      className="fixed inset-x-4 bottom-4 z-10 mx-auto flex max-w-md items-center gap-3 rounded-xl border border-white/10 bg-[#1a1e27] py-2 pr-2 pl-4 text-sm shadow-2xl shadow-black/60"
    >
      <span className="flex-1">
        {toast.kind === 'snoozed'
          ? `${toast.item.title} is hidden for 30 days.`
          : `${toast.item.title} won’t be suggested again.`}
      </span>
      <Button variant="ghost" className="px-3 py-1.5" onClick={onUndo}>
        Undo
      </Button>
    </div>
  )
}

function NextStep({ to, action, children }: { to: string; action: string; children: string }) {
  return (
    <div className="mt-6 flex flex-wrap items-center justify-between gap-4 rounded-xl border border-accent/30 bg-accent/5 p-4">
      <p className="max-w-prose text-sm">{children}</p>
      <Link
        to={to}
        className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-black hover:bg-accent-strong"
      >
        {action}
      </Link>
    </div>
  )
}

function RatingPromptBanner({
  prompt,
  onRate,
  onDismiss,
  onOpen,
}: {
  prompt: RatingPromptItem
  onRate: (reaction: Reaction) => void
  onDismiss: () => void
  onOpen: () => void
}) {
  return (
    <div className="relative mt-6 overflow-hidden rounded-2xl border border-accent/30 bg-gradient-to-r from-accent/15 via-[#1a1e27] to-[#12161f] p-4 shadow-xl shadow-black/40 sm:p-5">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3.5 sm:gap-4 min-w-0">
          <button
            type="button"
            onClick={onOpen}
            className="group relative shrink-0 overflow-hidden rounded-xl ring-1 ring-white/10 hover:ring-accent transition"
          >
            <Poster
              path={prompt.poster_path}
              title={prompt.title}
              className="h-20 w-14 object-cover sm:h-24 sm:w-16 transition group-hover:scale-105"
            />
          </button>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center gap-1 rounded-full bg-black/40 px-2 py-0.5 text-[11px] font-medium text-white/80 ring-1 ring-white/10">
                <JellyfinLogo className="size-3.5 rounded-full" />
                <span>Finished on Jellyfin</span>
              </span>
            </div>
            <h2 className="mt-1 text-base font-semibold text-white sm:text-lg truncate">
              {prompt.title} {prompt.year ? <span className="text-white/40 font-normal">({prompt.year})</span> : null}
            </h2>
            <p className="text-xs text-white/60">
              How was it? Rating teaches iWantToWatch your taste for tonight’s recommendations.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 self-end sm:self-center shrink-0">
          <div className="flex items-center gap-1.5 rounded-xl border border-white/10 bg-black/40 p-1 backdrop-blur-md">
            <button
              type="button"
              onClick={() => onRate('disliked')}
              title="Didn't like"
              className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-white/75 hover:bg-rose-500/20 hover:text-rose-300 transition"
            >
              <ReactionIcon reaction="disliked" className="size-4" />
              <span className="hidden sm:inline">Didn't like</span>
            </button>
            <button
              type="button"
              onClick={() => onRate('liked')}
              title="Liked"
              className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-white/75 hover:bg-sky-500/20 hover:text-sky-300 transition"
            >
              <ReactionIcon reaction="liked" className="size-4" />
              <span className="hidden sm:inline">Liked</span>
            </button>
            <button
              type="button"
              onClick={() => onRate('loved')}
              title="Loved"
              className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-white/75 hover:bg-accent/20 hover:text-accent-strong transition"
            >
              <ReactionIcon reaction="loved" className="size-4" />
              <span className="hidden sm:inline">Loved</span>
            </button>
          </div>
          <button
            type="button"
            onClick={onDismiss}
            title="Dismiss rating prompt"
            aria-label="Dismiss rating prompt"
            className="flex size-8 items-center justify-center rounded-lg border border-white/10 bg-black/30 text-white/40 hover:text-white hover:bg-white/10 transition"
          >
            ×
          </button>
        </div>
      </div>
    </div>
  )
}

function ContinueWatchingShelf({
  items,
  onOpen,
  onHide,
}: {
  items: InProgressItem[]
  onOpen: (tmdbId: number) => void
  onHide?: () => void
}) {
  if (items.length === 0) return null
  return (
    <div className="mt-6">
      <div className="flex items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <JellyfinLogo className="size-4.5 rounded" />
          <h2 className="text-sm font-semibold text-white/90">Continue Watching on Jellyfin</h2>
          <span className="rounded-full bg-white/10 px-2 py-0.5 text-[11px] font-medium text-white/60">
            {items.length}
          </span>
        </div>
        {onHide && (
          <button
            type="button"
            onClick={onHide}
            className="text-xs text-white/40 hover:text-white transition cursor-pointer"
            title="Hide shelf from Discover (can re-enable in Settings)"
          >
            Hide shelf
          </button>
        )}
      </div>

      <div className="flex gap-3.5 overflow-x-auto pb-2 scrollbar-thin">
        {items.map((item) => {
          const minsLeft = item.runtime
            ? Math.max(1, Math.round(item.runtime * (1 - item.playback_percentage / 100)))
            : null
          const progressLabel =
            minsLeft !== null
              ? minsLeft >= 60
                ? `${Math.floor(minsLeft / 60)}h ${minsLeft % 60}m left`
                : `${minsLeft}m left`
              : `${Math.round(item.playback_percentage)}%`

          return (
            <div
              key={item.tmdb_id}
              className="group relative flex w-36 sm:w-40 shrink-0 flex-col rounded-xl border border-white/10 bg-[#161922] p-2 hover:border-white/20 transition shadow-lg"
            >
              <div className="relative aspect-[2/3] w-full overflow-hidden rounded-lg bg-black/40">
                <button
                  type="button"
                  onClick={() => onOpen(item.tmdb_id)}
                  className="size-full cursor-pointer"
                  title={`View details for ${item.title}`}
                >
                  <Poster
                    path={item.poster_path}
                    title={item.title}
                    className="size-full object-cover transition group-hover:scale-105"
                  />
                </button>
                {/* Match badge on top left */}
                {item.match !== undefined && item.match !== null && (
                  <div className="absolute top-1.5 left-1.5 pointer-events-none">
                    <MatchBadge match={item.match} />
                  </div>
                )}
                {/* Progress pill on top right */}
                <div className="absolute top-1.5 right-1.5 pointer-events-none">
                  <span className="rounded-md bg-black/80 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-300 ring-1 ring-emerald-500/30 backdrop-blur-xs">
                    {progressLabel}
                  </span>
                </div>
                {/* Progress bar at bottom */}
                <div className="absolute inset-x-0 bottom-0 h-1.5 bg-black/60 overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-emerald-500 to-accent"
                    style={{ width: `${Math.min(100, Math.max(2, item.playback_percentage))}%` }}
                  />
                </div>
              </div>

              <div className="mt-2 flex-1 min-w-0">
                <button
                  type="button"
                  onClick={() => onOpen(item.tmdb_id)}
                  className="block text-left text-xs font-semibold text-white/90 hover:text-accent transition truncate w-full"
                  title={item.title}
                >
                  {item.title}
                </button>
                <div className="flex items-center justify-between text-[11px] text-white/50 mt-0.5">
                  <span className="flex items-center gap-1.5">
                    {item.year && <span>{item.year}</span>}
                    {item.is_rewatch && (
                      <span className="rounded bg-amber-400/15 px-1 py-0.2 text-[9px] font-semibold text-amber-300">
                        Rewatch
                      </span>
                    )}
                  </span>
                  <span>{Math.round(item.playback_percentage)}%</span>
                </div>
              </div>

              {item.jellyfin_url && (
                <a
                  href={item.jellyfin_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-2 flex items-center justify-center gap-1.5 rounded-lg border border-white/10 bg-white/5 py-1 text-xs font-medium text-white/80 hover:bg-white/10 hover:text-white transition"
                  title="Resume in Jellyfin"
                >
                  <svg viewBox="0 0 24 24" className="size-3 fill-current" aria-hidden="true">
                    <polygon points="5 3 19 12 5 21 5 3" />
                  </svg>
                  <span>Resume</span>
                </a>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
