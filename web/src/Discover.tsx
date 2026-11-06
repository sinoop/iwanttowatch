import type { FeedbackKind, FeedItem, FeedPage, Me } from '@iwanttowatch/api-client'
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { api, errorMessage, facts, useServerSettings } from './api'
import RateDialog, { ReactionIcon } from './RateDialog'
import { WatchBadges } from './Streaming'
import TitleDialog, { Chips, MatchBadge } from './TitleDialog'
import { Button, ErrorText, Poster } from './ui'

const languageName = new Intl.DisplayNames(['en'], { type: 'language' })
const PAGE = 24
// Below this many ratings the feed leans on quality rather than taste.
const FEW_RATINGS = 15
const TOAST_SECONDS = 8

type Toast = { item: FeedItem; kind: FeedbackKind }

export default function Discover({ me }: { me: Me }) {
  const settings = useServerSettings()
  const [availableOnly, setAvailableOnly] = useState(true)
  const [language, setLanguage] = useState<string | null>(null)
  const [genre, setGenre] = useState<string | null>(null)
  const [open, setOpen] = useState<number | null>(null)
  const [rating, setRating] = useState<number | null>(null)
  const [toast, setToast] = useState<Toast | null>(null)
  const queryClient = useQueryClient()
  const refreshFeed = () => queryClient.invalidateQueries({ queryKey: ['feed'] })
  const feedback = useMutation({
    mutationFn: async ({ item, kind }: Toast) => {
      const { error } = await api.PUT('/api/v1/titles/{tmdb_id}/feedback', {
        params: { path: { tmdb_id: item.tmdb_id } },
        body: { kind },
      })
      if (error) throw new Error(errorMessage(error))
    },
    onSuccess: (_, toast) => {
      if (toast.kind !== 'up') setToast(toast)
      if (toast.kind === 'seen') queryClient.invalidateQueries({ queryKey: ['ratings'] })
    },
    onSettled: refreshFeed,
  })
  const undo = useMutation({
    mutationFn: (tmdbId: number) =>
      api.DELETE('/api/v1/titles/{tmdb_id}/feedback', { params: { path: { tmdb_id: tmdbId } } }),
    onSettled: refreshFeed,
  })
  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(null), TOAST_SECONDS * 1000)
    return () => clearTimeout(timer)
  }, [toast])
  const act = (item: FeedItem, kind: FeedbackKind) => {
    // A second thumbs up takes it back.
    if (kind === 'up' && item.thumbs_up) undo.mutate(item.tmdb_id)
    else feedback.mutate({ item, kind })
  }

  const ratings = useQuery({
    queryKey: ['ratings', 'count'],
    queryFn: async () => (await api.GET('/api/v1/ratings', { params: { query: { limit: 1 } } })).data?.total ?? 0,
  })
  const feed = useInfiniteQuery({
    queryKey: ['feed', availableOnly, language, genre],
    queryFn: async ({ pageParam }) => {
      const { data, error } = await api.GET('/api/v1/feed', {
        params: {
          query: {
            available_only: availableOnly,
            language: language ?? undefined,
            genre: genre ?? undefined,
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
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Discover</h1>
          <p className="mt-1 text-white/60">Films picked for {me.display_name}, best match first.</p>
        </div>
        {first && <RefreshButton page={first} />}
      </div>

      {tmdbMissing ? (
        <NextStep to="/settings" action="Open Settings">
          {me.is_admin
            ? 'First, add a free TMDb API key so iWantToWatch can look up movies.'
            : 'Ask your admin to add a TMDb API key so iWantToWatch can look up movies.'}
        </NextStep>
      ) : (
        ratings.data !== undefined &&
        ratings.data < FEW_RATINGS && (
          <NextStep to="/taste" action="Import ratings">
            {ratings.data === 0
              ? 'These picks are well-loved films, not yet yours. Import your IMDb or Letterboxd ratings to teach iWantToWatch your taste.'
              : `Only ${ratings.data} ratings so far. Import your IMDb or Letterboxd history for picks that match your taste.`}
          </NextStep>
        )
      )}

      {first && (
        <Filters
          page={first}
          availableOnly={availableOnly}
          onAvailableOnly={setAvailableOnly}
          language={language}
          onLanguage={setLanguage}
          genre={genre}
          onGenre={setGenre}
        />
      )}

      {feedback.error && (
        <div className="mt-6">
          <ErrorText>{feedback.error.message}</ErrorText>
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
          filtered={language !== null || genre !== null}
          availableOnly={availableOnly}
          onShowAll={() => setAvailableOnly(false)}
          onClearFilters={() => {
            setLanguage(null)
            setGenre(null)
          }}
        />
      )}

      {items.length > 0 && (
        <ul className="mt-6 grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-3 lg:grid-cols-4" aria-label="Recommendations">
          {items.map((item) => (
            <FeedCard
              key={item.tmdb_id}
              item={item}
              onOpen={() => setOpen(item.tmdb_id)}
              onAct={(kind) => act(item, kind)}
              busy={
                (feedback.isPending && feedback.variables.item.tmdb_id === item.tmdb_id) ||
                (undo.isPending && undo.variables === item.tmdb_id)
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

      <TitleDialog
        tmdbId={open}
        onClose={() => setOpen(null)}
        onRate={(id) => {
          setOpen(null)
          setRating(id)
        }}
      />
      <RateDialog tmdbId={rating} onClose={() => setRating(null)} />
      {toast && (
        <UndoToast
          key={`${toast.item.tmdb_id}-${toast.kind}`}
          toast={toast}
          onUndo={() => {
            undo.mutate(toast.item.tmdb_id)
            setToast(null)
          }}
          onRate={() => {
            setRating(toast.item.tmdb_id)
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

function RefreshButton({ page }: { page: FeedPage }) {
  const queryClient = useQueryClient()
  const refresh = useMutation({
    mutationFn: () => api.POST('/api/v1/feed/refresh'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['feed'] }),
  })
  return (
    <div className="flex items-center gap-3 text-xs text-white/45">
      {page.rescoring ? (
        <span role="status">Re-ranking with your feedback…</span>
      ) : page.built_at && (
        <span>
          Updated{' '}
          {new Date(page.built_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}
        </span>
      )}
      <Button
        variant="ghost"
        className="border border-white/10 px-3 py-1.5"
        onClick={() => refresh.mutate()}
        disabled={refresh.isPending || building(page)}
      >
        Refresh
      </Button>
    </div>
  )
}

function Filters({
  page,
  availableOnly,
  onAvailableOnly,
  language,
  onLanguage,
  genre,
  onGenre,
}: {
  page: FeedPage
  availableOnly: boolean
  onAvailableOnly: (value: boolean) => void
  language: string | null
  onLanguage: (value: string | null) => void
  genre: string | null
  onGenre: (value: string | null) => void
}) {
  const chip = (selected: boolean) =>
    `rounded-full border px-3 py-1 text-sm transition-colors focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:outline-none ${
      selected
        ? 'border-accent bg-accent/15 text-accent-strong'
        : 'border-white/10 text-white/65 hover:border-white/25 hover:text-white'
    }`
  // Keep a chosen filter visible even when it no longer matches anything.
  const languages = page.languages.map((l) => l.language)
  if (language && !languages.includes(language)) languages.push(language)
  const genres = genre && !page.genres.includes(genre) ? [...page.genres, genre] : page.genres

  return (
    <div className="mt-6 flex flex-wrap items-center gap-x-4 gap-y-3">
      <label className="flex cursor-pointer items-center gap-2 text-sm">
        <button
          type="button"
          role="switch"
          aria-checked={availableOnly}
          onClick={() => onAvailableOnly(!availableOnly)}
          className={`relative h-5 w-9 rounded-full transition-colors focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:outline-none ${
            availableOnly ? 'bg-accent' : 'bg-white/20'
          }`}
        >
          <span
            className={`absolute top-0.5 left-0.5 size-4 rounded-full bg-white transition-transform ${
              availableOnly ? 'translate-x-4' : ''
            }`}
          />
        </button>
        Available to watch
      </label>
      {languages.length > 1 || language ? (
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Language">
          <button type="button" aria-pressed={language === null} onClick={() => onLanguage(null)} className={chip(language === null)}>
            All languages
          </button>
          {languages.map((code) => (
            <button
              key={code}
              type="button"
              aria-pressed={language === code}
              onClick={() => onLanguage(language === code ? null : code)}
              className={chip(language === code)}
            >
              {languageName.of(code)}
            </button>
          ))}
        </div>
      ) : null}
      {genres.length > 0 && (
        <select
          value={genre ?? ''}
          onChange={(e) => onGenre(e.target.value || null)}
          aria-label="Genre"
          className="rounded-lg border border-white/10 bg-black/30 px-3 py-1.5 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent/30"
        >
          <option value="">All genres</option>
          {genres.map((g) => (
            <option key={g} value={g}>
              {g}
            </option>
          ))}
        </select>
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
  filtered,
  availableOnly,
  onShowAll,
  onClearFilters,
}: {
  filtered: boolean
  availableOnly: boolean
  onShowAll: () => void
  onClearFilters: () => void
}) {
  return (
    <div className="mt-6 rounded-xl border border-dashed border-white/15 p-6 text-sm text-white/60">
      {filtered ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span>No picks match these filters.</span>
          <Button variant="ghost" onClick={onClearFilters}>
            Clear filters
          </Button>
        </div>
      ) : availableOnly ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span>
            None of your picks are on your Jellyfin server or your streaming services. Choose your services in{' '}
            <Link to="/settings" className="text-accent underline-offset-2 hover:underline">
              Settings
            </Link>
            , or see every pick.
          </span>
          <Button variant="ghost" onClick={onShowAll}>
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
  onOpen,
  onAct,
  busy,
}: {
  item: FeedItem
  onOpen: () => void
  onAct: (kind: FeedbackKind) => void
  busy: boolean
}) {
  return (
    <li className="flex flex-col">
      <button
        type="button"
        onClick={onOpen}
        className="group relative block rounded-lg text-left focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:outline-none"
        aria-label={`${item.title}, ${item.match}% match`}
      >
        <Poster
          path={item.poster_path}
          title={item.title}
          className="transition-shadow group-hover:ring-2 group-hover:ring-accent"
        />
        <MatchBadge match={item.match} className="absolute top-2 left-2 shadow-lg shadow-black/50" />
      </button>
      <div className="mt-1.5 flex items-center justify-between" role="group" aria-label={`Feedback on ${item.title}`}>
        <div className="flex">
          <CardAction label="More like this" pressed={item.thumbs_up} disabled={busy} onClick={() => onAct('up')}>
            <ReactionIcon reaction="liked" className="size-4" />
          </CardAction>
          <CardAction label="Less like this" disabled={busy} onClick={() => onAct('down')}>
            <ReactionIcon reaction="disliked" className="size-4" />
          </CardAction>
        </div>
        <div className="flex">
          <CardAction label="Seen it" disabled={busy} onClick={() => onAct('seen')}>
            <Icon d="M2.06 12.35a1 1 0 0 1 0-.7 10.75 10.75 0 0 1 19.88 0 1 1 0 0 1 0 .7 10.75 10.75 0 0 1-19.88 0M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0" />
          </CardAction>
          <CardAction label="Not now (hide for 30 days)" disabled={busy} onClick={() => onAct('snoozed')}>
            <Icon d="M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0M12 6v6l4 2" />
          </CardAction>
          <CardAction label="Not interested" disabled={busy} onClick={() => onAct('dismissed')}>
            <Icon d="M18 6 6 18M6 6l12 12" />
          </CardAction>
        </div>
      </div>
      <h2 className="mt-1 text-sm leading-snug font-medium">{item.title}</h2>
      <p className="text-xs text-white/50">{facts(item).join(' · ')}</p>
      <WatchBadges availability={item.availability} />
      <Chips genres={item.genres.slice(0, 3 - item.moods.length)} moods={item.moods} className="mt-2" />
      {item.reasons[0] && <p className="mt-1.5 line-clamp-2 text-xs text-white/50">{item.reasons[0]}</p>}
    </li>
  )
}

function CardAction({
  label,
  pressed,
  disabled,
  onClick,
  children,
}: {
  label: string
  pressed?: boolean
  disabled: boolean
  onClick: () => void
  children: ReactNode
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
      }`}
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

const TOAST_TEXT: Record<FeedbackKind, (title: string) => string> = {
  up: (title) => `More like ${title}.`,
  down: (title) => `Got it: fewer films like ${title}.`,
  dismissed: (title) => `${title} won’t be suggested again.`,
  snoozed: (title) => `${title} is hidden for 30 days.`,
  seen: (title) => `Marked ${title} as seen.`,
}

function UndoToast({
  toast,
  onUndo,
  onRate,
}: {
  toast: Toast
  onUndo: () => void
  onRate: () => void
}) {
  return (
    <div
      role="status"
      className="fixed inset-x-4 bottom-4 z-10 mx-auto flex max-w-md items-center gap-3 rounded-xl border border-white/10 bg-[#1a1e27] py-2 pr-2 pl-4 text-sm shadow-2xl shadow-black/60"
    >
      <span className="flex-1">{TOAST_TEXT[toast.kind](toast.item.title)}</span>
      {toast.kind === 'seen' && (
        <Button variant="ghost" className="px-3 py-1.5" onClick={onRate}>
          Rate it
        </Button>
      )}
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
