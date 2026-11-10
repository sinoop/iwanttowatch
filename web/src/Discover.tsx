import type { AskAnswer, ChildProfile, FeedItem, FeedPage, FeedSort, Me, Reaction } from '@iwanttowatch/api-client'
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { api, errorMessage, facts, useChildren, useQuickRate, useServerSettings, useShortlist, watchOnQuery, type WatchOn } from './api'
import RateDialog, { QuickTags, ReactionIcon } from './RateDialog'
import { PlatformFilter, WatchBadges } from './Streaming'
import TitleDialog, { AssignToChildButton, BookmarkIcon, Chips, MatchBadge } from './TitleDialog'
import { Button, ErrorText, Poster } from './ui'

const languageName = new Intl.DisplayNames(['en'], { type: 'language' })
const PAGE = 24
// Below this many ratings the feed leans on quality rather than taste.
const FEW_RATINGS = 15
const TOAST_SECONDS = 10

type Toast =
  | { type: 'reaction'; item: FeedItem; reaction: Reaction }
  | { type: 'feedback'; item: FeedItem; kind: 'snoozed' | 'dismissed' }
type Answer = AskAnswer & { text: string }
type ShortlistFilter = 'all' | 'only' | 'hide'

export default function Discover({ me }: { me: Me }) {
  const settings = useServerSettings()
  const children = useChildren(!me.is_child)
  const [watchOn, setWatchOn] = useState<WatchOn>('anywhere')
  const [language, setLanguage] = useState<string | null>(null)
  const [genre, setGenre] = useState<string | null>(null)
  const [certificate, setCertificate] = useState<string | null>(null)
  const [shortlistFilter, setShortlistFilter] = useState<ShortlistFilter>('all')
  const [sort, setSort] = useState<FeedSort>('match')
  const [ageLimitOffFor, setAgeLimitOffFor] = useState<number | null>(null)
  const ageLimit = ageLimitOffFor !== me.id
  const setAgeLimit = (on: boolean) => setAgeLimitOffFor(on ? null : me.id)
  const [open, setOpen] = useState<number | null>(null)
  const [rating, setRating] = useState<number | null>(null)
  const [toast, setToast] = useState<Toast | null>(null)
  const [answer, setAnswer] = useState<Answer | null>(null)
  const queryClient = useQueryClient()
  const refreshFeed = () => queryClient.invalidateQueries({ queryKey: ['feed'] })
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
  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(null), TOAST_SECONDS * 1000)
    return () => clearTimeout(timer)
  }, [toast])
  const act = (item: FeedItem, kind: 'snoozed' | 'dismissed') => feedback.mutate({ item, kind })
  const rateFilm = (item: FeedItem, reaction: Reaction) => {
    quickRate.mutate({ tmdbId: item.tmdb_id, reaction })
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
    max_certificate: !me.is_child ? (certificate ?? undefined) : undefined,
    shortlist: shortlistFilter === 'only' || undefined,
    hide_shortlisted: shortlistFilter === 'hide' || undefined,
    age_limit: me.max_certificate ? ageLimit : undefined,
  }
  const ask = useMutation({
    mutationFn: async (text: string) => {
      const { data, error } = await api.POST('/api/v1/feed/ask', { params: { query: filters }, body: { text } })
      if (error) throw new Error(errorMessage(error))
      return { ...data, text }
    },
    onSuccess: setAnswer,
  })
  // While an answer is shown, the feed lists only the AI's picks, in the feed's order.
  const only = answer?.picks.map((p) => p.tmdb_id)
  const feed = useInfiniteQuery({
    queryKey: ['feed', me.id, watchOn, language, genre, certificate, shortlistFilter, sort, ageLimit, only],
    queryFn: async ({ pageParam }) => {
      const { data, error } = await api.GET('/api/v1/feed', {
        params: {
          query: {
            ...filters,
            sort: sort !== 'match' ? sort : undefined,
            only: only?.length ? only : undefined,
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
  const nothingFits = answer?.picks.length === 0
  const items = nothingFits ? [] : (feed.data?.pages.flatMap((p) => p.items) ?? [])
  const tmdbMissing = settings.data && !settings.data.tmdb_configured
  const llmConfigured = (settings.data?.llm.order.length ?? 0) > 0
  const whyFor = new Map(answer?.picks.map((p) => [p.tmdb_id, p.why]))

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Discover</h1>
          <p className="mt-1 text-white/60">Films picked for {me.display_name}, best match first.</p>
        </div>
        {first && <RefreshButton page={first} language={language} genre={genre} />}
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

      {first?.status === 'ready' && llmConfigured && (
        <AskBox
          answer={answer}
          asking={ask.isPending}
          error={ask.error?.message}
          onAsk={(text) => ask.mutate(text)}
          onClear={() => {
            ask.reset()
            setAnswer(null)
          }}
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
          language={language}
          onLanguage={setLanguage}
          genre={genre}
          onGenre={setGenre}
          certificate={!me.is_child ? certificate : null}
          onCertificate={setCertificate}
          shortlistFilter={shortlistFilter}
          onShortlistFilter={setShortlistFilter}
          sort={sort}
          onSort={setSort}
        />
      )}

      {(feedback.error || shortlist.error) && (
        <div className="mt-6">
          <ErrorText>{(feedback.error ?? shortlist.error)?.message}</ErrorText>
        </div>
      )}
      {feed.error && (
        <div className="mt-6">
          <ErrorText>{feed.error.message}</ErrorText>
        </div>
      )}
      {first && <BuildStatus page={first} empty={items.length === 0} />}
      {first?.status === 'ready' && items.length === 0 && !answer && (
        <EmptyFeed
          emptyShortlist={shortlistFilter === 'only' && first.shortlist_count === 0}
          filtered={
            language !== null ||
            genre !== null ||
            (!me.is_child && certificate !== null) ||
            shortlistFilter === 'hide'
          }
          watchOn={watchOn}
          onWatchOn={setWatchOn}
          onClearFilters={() => {
            setLanguage(null)
            setGenre(null)
            setCertificate(null)
            if (shortlistFilter === 'hide') setShortlistFilter('all')
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
              fit={whyFor.get(item.tmdb_id)}
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
      {answer && items.length === 0 && first && !feed.isFetching && (
        <div className="mt-6 rounded-xl border border-dashed border-white/15 p-6 text-sm text-white/60">
          {answer.considered === 0
            ? 'There are no films to choose from with these filters.'
            : nothingFits
              ? `None of the top ${answer.considered} films in your feed fit that. Try asking more loosely, or choose Include unavailable to include films you can’t play now.`
              : 'None of the AI’s picks match these filters.'}
        </div>
      )}
      {feed.hasNextPage && !nothingFits && (
        <div className="mt-6 flex justify-center">
          <Button variant="ghost" onClick={() => feed.fetchNextPage()} disabled={feed.isFetchingNextPage}>
            {feed.isFetchingNextPage ? 'Loading…' : `Show more (${(first?.total ?? 0) - items.length} left)`}
          </Button>
        </div>
      )}

      <TitleDialog tmdbId={open} onClose={() => setOpen(null)} />
      <RateDialog tmdbId={rating} onClose={() => setRating(null)} />
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

function RefreshButton({
  page,
  language,
  genre,
}: {
  page: FeedPage
  language: string | null
  genre: string | null
}) {
  const queryClient = useQueryClient()
  const targetFilters = (language !== null || genre !== null) && page.total < 25
  const refresh = useMutation({
    mutationFn: () =>
      api.POST('/api/v1/feed/refresh', {
        params: {
          query: {
            language: targetFilters ? (language ?? undefined) : undefined,
            genre: targetFilters ? (genre ?? undefined) : undefined,
          },
        },
      }),
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
  maxCertificate,
  ageLimit,
  onAgeLimit,
  watchOn,
  onWatchOn,
  language,
  onLanguage,
  genre,
  onGenre,
  certificate,
  onCertificate,
  shortlistFilter,
  onShortlistFilter,
  sort,
  onSort,
}: {
  page: FeedPage
  maxCertificate: string | null
  ageLimit: boolean
  onAgeLimit: (value: boolean) => void
  watchOn: WatchOn
  onWatchOn: (value: WatchOn) => void
  language: string | null
  onLanguage: (value: string | null) => void
  genre: string | null
  onGenre: (value: string | null) => void
  certificate: string | null
  onCertificate: (value: string | null) => void
  shortlistFilter: ShortlistFilter
  onShortlistFilter: (value: ShortlistFilter) => void
  sort: FeedSort
  onSort: (value: FeedSort) => void
}) {
  const selectClass = (active: boolean) =>
    `rounded-lg border px-3 py-1.5 text-sm outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-accent/30 ${
      active
        ? 'border-accent/60 bg-accent/10 text-accent-strong'
        : 'border-white/10 bg-black/30 text-white/80 hover:border-white/25 hover:text-white'
    }`
  // Keep a chosen filter visible even when it no longer matches anything.
  const languages = page.languages.map((l) => l.language)
  if (language && !languages.includes(language)) languages.push(language)
  const genres = genre && !page.genres.includes(genre) ? [...page.genres, genre] : page.genres
  const certificates =
    certificate && !page.certificates.includes(certificate)
      ? [...page.certificates, certificate]
      : page.certificates

  return (
    <div className="mt-6 flex flex-wrap items-center gap-2.5">
      <PlatformFilter platforms={page.platforms} value={watchOn} onChange={onWatchOn} />
      <select
        value={shortlistFilter}
        onChange={(e) => onShortlistFilter(e.target.value as ShortlistFilter)}
        aria-label="Shortlist"
        className={selectClass(shortlistFilter !== 'all')}
      >
        <option value="all">All films</option>
        <option value="only">Shortlist only ({page.shortlist_count})</option>
        <option value="hide">Hide shortlisted ({page.shortlist_count})</option>
      </select>
      {(languages.length > 1 || language) && (
        <select
          value={language ?? ''}
          onChange={(e) => onLanguage(e.target.value || null)}
          aria-label="Language"
          className={selectClass(language !== null)}
        >
          <option value="">All languages</option>
          {languages.map((code) => (
            <option key={code} value={code}>
              {languageName.of(code)}
            </option>
          ))}
        </select>
      )}
      {genres.length > 0 && (
        <select
          value={genre ?? ''}
          onChange={(e) => onGenre(e.target.value || null)}
          aria-label="Genre"
          className={selectClass(genre !== null)}
        >
          <option value="">All genres</option>
          {genres.map((g) => (
            <option key={g} value={g}>
              {g}
            </option>
          ))}
        </select>
      )}
      {!maxCertificate && certificates.length > 0 && (
        <select
          value={certificate ?? ''}
          onChange={(e) => onCertificate(e.target.value || null)}
          aria-label="Age rating"
          className={selectClass(certificate !== null)}
        >
          <option value="">All age ratings</option>
          {certificates.map((cert) => (
            <option key={cert} value={cert}>
              Rated {cert} &amp; under
            </option>
          ))}
        </select>
      )}
      <select
        value={sort}
        onChange={(e) => onSort(e.target.value as FeedSort)}
        aria-label="Order by"
        className={selectClass(sort !== 'match')}
      >
        <option value="match">Order: Best match</option>
        <option value="rating">Order: Highest rated</option>
        <option value="newest">Order: Newest first</option>
        <option value="oldest">Order: Oldest first</option>
        <option value="shortest">Order: Shortest first</option>
      </select>
      {maxCertificate && (
        <div className="inline-flex items-center gap-1">
          <select
            value={ageLimit ? 'on' : 'off'}
            onChange={(e) => onAgeLimit(e.target.value === 'on')}
            aria-label="Age restriction"
            className={selectClass(ageLimit)}
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
              className="flex size-8 items-center justify-center rounded-lg border border-white/10 bg-black/30 text-sm text-white/60 hover:border-white/25 hover:text-white focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:outline-none"
            >
              ×
            </button>
          )}
        </div>
      )}
    </div>
  )
}

const EXAMPLE_REQUEST = 'a light Malayalam comedy under 2 hours'

/** A request in the user's own words, which the AI answers from the top of the feed. */
function AskBox({
  answer,
  asking,
  error,
  onAsk,
  onClear,
}: {
  answer: Answer | null
  asking: boolean
  error?: string
  onAsk: (text: string) => void
  onClear: () => void
}) {
  const [text, setText] = useState('')
  return (
    <section className="mt-6 rounded-xl border border-white/10 bg-white/[0.02] p-3.5">
      <form
        className="flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (text.trim()) onAsk(text.trim())
        }}
      >
        <label htmlFor="ask" className="sr-only">
          Ask for something
        </label>
        <input
          id="ask"
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={200}
          placeholder={`What are you in the mood for? Try “${EXAMPLE_REQUEST}”`}
          className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm outline-none placeholder:text-white/35 focus:border-accent focus:ring-2 focus:ring-accent/30"
        />
        <Button type="submit" disabled={asking || !text.trim()}>
          {asking ? 'Asking…' : 'Ask'}
        </Button>
      </form>
      {asking && (
        <p role="status" className="mt-2 text-xs text-white/50">
          The AI is choosing from the top of your feed…
        </p>
      )}
      {error && (
        <div className="mt-2">
          <ErrorText>{error}</ErrorText>
        </div>
      )}
      {answer && !asking && (
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-white/55">
          <span>
            <span className="mr-1.5 rounded-full bg-accent/10 px-2 py-0.5 text-[11px] font-medium text-accent-strong">
              AI-chosen
            </span>
            {answer.picks.length === 0
              ? `Nothing fits “${answer.text}”.`
              : `${answer.picks.length} ${answer.picks.length === 1 ? 'pick' : 'picks'} for “${answer.text}” from the top ${answer.considered} films in your feed, best match first.`}
          </span>
          <Button variant="ghost" className="px-3 py-1 text-xs" onClick={onClear}>
            Back to the full feed
          </Button>
        </div>
      )}
    </section>
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
      ) : watchOn === 'anywhere' ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span>
            None of your picks are on your Jellyfin server or your streaming services. Choose your services in{' '}
            <Link to="/settings" className="text-accent underline-offset-2 hover:underline">
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
  onRate: (reaction: Reaction) => void
  onAct: (kind: 'snoozed' | 'dismissed') => void
  onShortlist: () => void
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
      <div className="mt-1.5 flex items-center justify-between" role="group" aria-label={`Actions for ${item.title}`}>
        <div className="flex items-center rounded-full border border-white/10 bg-white/[0.03] p-0.5">
          <CardAction label="Didn’t like" disabled={busy} onClick={() => onRate('disliked')}>
            <ReactionIcon reaction="disliked" className="size-4" />
          </CardAction>
          <CardAction label="Liked" disabled={busy} onClick={() => onRate('liked')}>
            <ReactionIcon reaction="liked" className="size-4" />
          </CardAction>
          <CardAction label="Loved" disabled={busy} onClick={() => onRate('loved')}>
            <ReactionIcon reaction="loved" className="size-4" />
          </CardAction>
        </div>
        <div className="flex items-center">
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
      </div>
      <h2 className="mt-1 text-sm leading-snug font-medium">{item.title}</h2>
      <p className="text-xs text-white/50">{facts(item).join(' · ')}</p>
      <WatchBadges availability={item.availability} />
      <Chips genres={item.genres.slice(0, 3 - item.moods.length)} moods={item.moods} className="mt-2" />
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
    const label = toast.reaction === 'loved' ? 'Loved' : toast.reaction === 'liked' ? 'Liked' : 'Didn’t like'
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
        <QuickTags tmdbId={toast.item.tmdb_id} />
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
