import type { DivergentTitle, ImportJob, Me, RatedTitle, TitleAvailability } from '@iwanttowatch/api-client'
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { api, errorMessage, REACTIONS, TAG_LABELS, useAvailability, useServerSettings } from './api'
import RateDialog, { ReactionIcon } from './RateDialog'
import { FilmSearch } from './Search'
import { WatchBadges } from './Streaming'
import TitleDialog from './TitleDialog'
import { Button, ErrorText, Poster } from './ui'

const languageName = new Intl.DisplayNames(['en'], { type: 'language' })
const PAGE = 48
const SOURCE_NAMES: Record<string, string> = {
  imdb: 'IMDb',
  letterboxd: 'Letterboxd',
  netflix: 'Netflix',
}

export default function Taste({ me }: { me: Me }) {
  const [rating, setRating] = useState<number | null>(null)
  const [detailId, setDetailId] = useState<number | null>(null)
  const isChild = me.is_child
  return (
    <>
      <h1 className="text-2xl font-semibold">My taste</h1>
      <p className="mt-2 max-w-prose text-white/60">
        {isChild
          ? 'Everything iWantToWatch knows about what you like.'
          : 'Everything iWantToWatch knows about what you like. Import your history from IMDb, Letterboxd, or Netflix; importing again later only adds what changed.'}
      </p>
      <PersonaCard />
      {!isChild && <Imports />}
      <Ratings onRate={setRating} onSelectFilm={setDetailId} />
      <RateDialog tmdbId={rating} onClose={() => setRating(null)} />
      <TitleDialog tmdbId={detailId} onClose={() => setDetailId(null)} />
    </>
  )
}

function PersonaCard() {
  const queryClient = useQueryClient()
  const persona = useQuery({
    queryKey: ['persona'],
    queryFn: async () => (await api.GET('/api/v1/me/persona')).data ?? null,
    refetchInterval: (query) => (query.state.data?.refreshing ? 2000 : false),
  })
  const write = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST('/api/v1/me/persona')
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => queryClient.setQueryData(['persona'], data),
  })
  const p = persona.data
  if (!p) return null
  const writing = write.isPending || p.refreshing
  const enough = p.current_ratings >= p.min_ratings
  const newRatings = p.current_ratings - p.based_on_ratings

  if (!p.text && p.refreshing) {
    return (
      <section className="mt-8 rounded-xl border border-dashed border-white/15 p-5 text-sm text-white/60">
        Summing up your taste…
      </section>
    )
  }

  if (!p.text) {
    return (
      <section className="mt-8 rounded-xl border border-dashed border-white/15 p-5 text-sm text-white/60">
        {!p.llm_configured ? (
          <>
            Connect Ollama or Gemini in{' '}
            <Link to="/settings" className="text-accent underline-offset-2 hover:underline">
              Settings
            </Link>{' '}
            to get a short AI-written summary of your taste.
          </>
        ) : !enough ? (
          `Rate at least ${p.min_ratings} movies and iWantToWatch will sum up your taste.`
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span>Ready to sum up your taste.</span>
            <Button onClick={() => write.mutate()} disabled={write.isPending}>
              {write.isPending ? 'Writing…' : 'Sum up my taste'}
            </Button>
          </div>
        )}
        {write.error && (
          <div className="mt-3">
            <ErrorText>{write.error.message}</ErrorText>
          </div>
        )}
      </section>
    )
  }

  return (
    <section className="mt-8 rounded-xl border border-accent/25 bg-gradient-to-br from-accent/10 to-transparent p-5 sm:p-6">
      <p className="text-xs font-medium tracking-wide text-accent uppercase">Your taste in brief</p>
      <p className={`mt-3 max-w-prose text-lg leading-relaxed ${writing ? 'opacity-50' : ''}`}>
        {p.text}
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-white/50">
        <span>
          Based on {p.based_on_ratings} ratings
          {newRatings > 0 && ` · ${newRatings} new since`}
        </span>
        {p.llm_configured && (
          <Button variant="ghost" onClick={() => write.mutate()} disabled={writing}>
            {writing ? 'Writing… a local model can take a minute' : 'Write a new one'}
          </Button>
        )}
      </div>
      {write.error && (
        <div className="mt-3">
          <ErrorText>{write.error.message}</ErrorText>
        </div>
      )}
    </section>
  )
}

function useImports() {
  return useQuery({
    queryKey: ['imports'],
    queryFn: async () => (await api.GET('/api/v1/imports')).data ?? [],
    refetchInterval: (query) =>
      query.state.data?.some((job) => job.status === 'pending' || job.status === 'running')
        ? 1500
        : false,
  })
}

function Imports() {
  const queryClient = useQueryClient()
  const settings = useServerSettings()
  const imports = useImports()
  const input = useRef<HTMLInputElement>(null)
  const [error, setError] = useState<string | null>(null)

  const upload = useMutation({
    mutationFn: async (file: File) => {
      const body = new FormData()
      body.append('file', file)
      // openapi-fetch sends FormData as-is, letting the browser set the multipart boundary.
      const { data, error } = await api.POST('/api/v1/imports', {
        body: body as unknown as { file: string },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onMutate: () => setError(null),
    onError: (e) => setError(e.message),
    onSettled: () => {
      if (input.current) input.current.value = ''
      queryClient.invalidateQueries({ queryKey: ['imports'] })
    },
  })

  // When a job finishes or fails, refresh the ratings it added.
  const statuses = (imports.data ?? []).map((job) => `${job.id}:${job.status}`).join()
  useEffect(() => {
    queryClient.invalidateQueries({ queryKey: ['ratings'] })
    queryClient.invalidateQueries({ queryKey: ['persona'] })
  }, [statuses, queryClient])

  const ready = settings.data?.tmdb_configured

  return (
    <section className="mt-8 rounded-xl border border-white/10 p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-prose text-sm text-white/60">
          <h2 className="text-base font-semibold text-white">Import ratings</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            <li>
              <span className="text-white/80">IMDb:</span> open Your Ratings, then use the menu to
              export <code className="text-white/80">ratings.csv</code>.
            </li>
            <li>
              <span className="text-white/80">Letterboxd:</span> Settings → Data → Export your data,
              then upload the ZIP file as it is.
            </li>
            <li>
              <span className="text-white/80">Netflix:</span> Account → Profiles → your profile →
              Viewing activity, then Download all. It has no ratings, so films only count as
              watched; series are skipped.
            </li>
          </ul>
        </div>
        <div>
          <input
            ref={input}
            type="file"
            accept=".csv,.zip"
            className="hidden"
            aria-label="Export file"
            onChange={(e) => e.target.files?.[0] && upload.mutate(e.target.files[0])}
          />
          <Button
            onClick={() => input.current?.click()}
            disabled={!ready || upload.isPending}
            title={ready ? undefined : 'Add a TMDb API key in Settings first'}
          >
            {upload.isPending ? 'Uploading…' : 'Choose file'}
          </Button>
        </div>
      </div>
      {!ready && settings.data && (
        <p className="mt-4 text-sm text-amber-300">
          Add a TMDb API key in <Link to="/settings" className="underline">Settings</Link> before
          importing.
        </p>
      )}
      {error && (
        <div className="mt-4">
          <ErrorText>{error}</ErrorText>
        </div>
      )}
      {imports.data && imports.data.length > 0 && (
        <ul className="mt-5 divide-y divide-white/5 border-t border-white/10">
          {imports.data.map((job) => (
            <ImportRow key={job.id} job={job} />
          ))}
        </ul>
      )}
    </section>
  )
}

function ImportRow({ job }: { job: ImportJob }) {
  const queryClient = useQueryClient()
  const retry = useMutation({
    mutationFn: () => api.POST('/api/v1/imports/{job_id}/retry', { params: { path: { job_id: job.id } } }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['imports'] }),
  })
  const { pending, matched, review, skipped } = job.counts
  const total = pending + matched + review + skipped
  const done = total - pending
  const active = job.status === 'pending' || job.status === 'running'

  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 py-3 text-sm">
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium">
          {SOURCE_NAMES[job.source] ?? job.source}{' '}
          <span className="font-normal text-white/45">{job.filename}</span>
        </p>
        <p className="text-white/55">
          {active
            ? `Matching ${done} of ${total}…`
            : `${matched} matched · ${review} to review · ${skipped} skipped`}
        </p>
        {active && (
          <div className="mt-2 h-1 w-full max-w-xs overflow-hidden rounded bg-white/10">
            <div
              className="h-full bg-accent transition-[width]"
              style={{ width: `${total ? (done / total) * 100 : 0}%` }}
            />
          </div>
        )}
        {job.status === 'failed' && <p className="mt-1 text-red-300">{job.error}</p>}
      </div>
      {job.status === 'failed' && (
        <Button variant="ghost" onClick={() => retry.mutate()} disabled={retry.isPending}>
          Retry
        </Button>
      )}
      {review > 0 && !active && (
        <Link
          to={`/taste/imports/${job.id}`}
          className="rounded-lg border border-accent/40 px-3 py-1.5 font-medium text-accent hover:bg-accent/10"
        >
          Review {review}
        </Link>
      )}
    </li>
  )
}

function Ratings({
  onRate,
  onSelectFilm,
}: {
  onRate: (tmdbId: number) => void
  onSelectFilm: (tmdbId: number) => void
}) {
  const [tab, setTab] = useState<'all' | 'divergent'>('all')
  const ratings = useInfiniteQuery({
    queryKey: ['ratings'],
    initialPageParam: 0,
    queryFn: async ({ pageParam }) =>
      (await api.GET('/api/v1/ratings', { params: { query: { limit: PAGE, offset: pageParam } } }))
        .data ?? { total: 0, items: [], languages: [] },
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((sum, page) => sum + page.items.length, 0)
      return loaded < last.total ? loaded : undefined
    },
  })
  const pages = ratings.data?.pages ?? []
  const items = pages.flatMap((page) => page.items)
  const where = useAvailability(items.map((item) => item.tmdb_id))
  const first = pages[0]
  if (!first) return null

  return (
    <section className="mt-10">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setTab('all')}
            className={`cursor-pointer text-lg font-semibold transition-colors ${
              tab === 'all' ? 'text-white' : 'text-white/40 hover:text-white/70'
            }`}
          >
            Your ratings <span className="font-normal text-white/45">{first.total}</span>
          </button>
          <span className="text-white/20">|</span>
          <button
            type="button"
            onClick={() => setTab('divergent')}
            className={`cursor-pointer text-lg font-semibold transition-colors flex items-center gap-1.5 ${
              tab === 'divergent' ? 'text-accent-strong' : 'text-white/40 hover:text-white/70'
            }`}
          >
            <span>Against the grain</span>
            <span className="rounded-full bg-accent/15 px-2 py-0.5 text-xs text-accent">Hot takes</span>
          </button>
        </div>
        {tab === 'all' && first.languages.length > 0 && (
          <ul className="flex flex-wrap gap-2" aria-label="Languages you rated">
            {first.languages.map((lang) => (
              <li key={lang.language} className="rounded-full bg-white/5 px-3 py-1 text-xs text-white/70">
                {languageName.of(lang.language) ?? lang.language}{' '}
                <span className="text-white/40">{lang.count}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {tab === 'divergent' ? (
        <DivergentSection onRate={onRate} onSelectFilm={onSelectFilm} />
      ) : (
        <>
          <div className="mt-5">
            <FilmSearch
              placeholder="Rate a film you’ve seen…"
              label="Search for a film to rate"
              prompt="Pick the film to rate"
              onPick={onRate}
            />
          </div>
          {items.length === 0 ? (
            <p className="mt-4 text-sm text-white/50">
              No ratings yet. Import a file above, or search for a film you’ve seen.
            </p>
          ) : (
            <ul className="mt-5 grid grid-cols-3 gap-4 sm:grid-cols-4 md:grid-cols-6">
              {items.map((item) => (
                <RatingCard key={item.tmdb_id} item={item} where={where.get(item.tmdb_id)} onRate={onRate} />
              ))}
            </ul>
          )}
          {ratings.hasNextPage && (
            <div className="mt-6">
              <Button variant="ghost" onClick={() => ratings.fetchNextPage()} disabled={ratings.isFetchingNextPage}>
                Show more
              </Button>
            </div>
          )}
        </>
      )}
    </section>
  )
}

function DivergentSection({
  onRate,
  onSelectFilm,
}: {
  onRate: (tmdbId: number) => void
  onSelectFilm: (tmdbId: number) => void
}) {
  const queryClient = useQueryClient()
  const settings = useServerSettings()
  const llmConfigured = Boolean(settings.data?.llm.order.length)

  const divergent = useQuery({
    queryKey: ['divergent-ratings'],
    queryFn: async () => (await api.GET('/api/v1/me/divergent-ratings')).data ?? [],
  })

  const askClash = useMutation({
    mutationFn: async (tmdbId: number) => {
      const { data, error } = await api.POST('/api/v1/titles/{tmdb_id}/clash', {
        params: { path: { tmdb_id: tmdbId } },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['title', data.tmdb_id], data)
      queryClient.invalidateQueries({ queryKey: ['divergent-ratings'] })
    },
  })

  const items = divergent.data ?? []
  const where = useAvailability(items.map((item) => item.tmdb_id))

  if (divergent.isLoading) {
    return <p className="mt-6 text-sm text-white/50">Analyzing where your taste diverges from the crowd…</p>
  }

  if (items.length === 0) {
    return (
      <div className="mt-6 rounded-xl border border-white/10 p-6 text-center text-sm text-white/60">
        <p className="font-medium text-white">No conflicting opinions found yet</p>
        <p className="mx-auto mt-1 max-w-prose">
          Films where your rating differs by at least 1.5 stars from the IMDb or TMDb consensus will appear here,
          along with an AI analysis explaining why you disagreed with the audience.
        </p>
      </div>
    )
  }

  return (
    <div className="mt-6">
      <p className="text-sm text-white/60">
        Films where your ratings strongly conflicted with general audience ratings on IMDb and TMDb.
      </p>
      <ul className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((item) => (
          <DivergentCard
            key={item.tmdb_id}
            item={item}
            where={where.get(item.tmdb_id)}
            onRate={onRate}
            onSelectFilm={onSelectFilm}
            llmConfigured={llmConfigured}
            onAskClash={(id) => askClash.mutate(id)}
            isAsking={askClash.isPending && askClash.variables === item.tmdb_id}
            error={askClash.variables === item.tmdb_id ? askClash.error?.message : null}
          />
        ))}
      </ul>
    </div>
  )
}

function DivergentCard({
  item,
  where,
  onRate,
  onSelectFilm,
  llmConfigured,
  onAskClash,
  isAsking,
  error,
}: {
  item: DivergentTitle
  where: TitleAvailability | undefined
  onRate: (tmdbId: number) => void
  onSelectFilm: (tmdbId: number) => void
  llmConfigured: boolean
  onAskClash: (tmdbId: number) => void
  isAsking: boolean
  error: string | null | undefined
}) {
  const showOriginal = item.original_title && item.original_title !== item.title
  const reaction = REACTIONS.find((r) => r.value === item.reaction)
  const lovedMore = item.divergence > 0

  return (
    <li className="flex flex-col rounded-xl border border-white/10 bg-white/[0.02] p-3.5 transition-colors hover:border-white/20">
      <div className="flex gap-3">
        <div className="w-16 shrink-0 sm:w-20">
          <button
            type="button"
            onClick={() => onSelectFilm(item.tmdb_id)}
            className="group block w-full cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            <Poster
              path={item.poster_path}
              title={item.title}
              className="group-hover:ring-2 group-hover:ring-accent/70"
            />
          </button>
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-1">
            <button
              type="button"
              onClick={() => onSelectFilm(item.tmdb_id)}
              className="cursor-pointer truncate text-left text-sm font-semibold hover:text-accent focus-visible:outline-none"
              title={item.title}
            >
              {item.title}
            </button>
            <button
              type="button"
              onClick={() => onRate(item.tmdb_id)}
              title="Edit your rating"
              className="shrink-0 cursor-pointer rounded px-1.5 py-0.5 text-xs text-white/50 hover:bg-white/10 hover:text-white"
            >
              Edit
            </button>
          </div>
          <p className="truncate text-xs text-white/45" title={showOriginal ? item.original_title : undefined}>
            {[item.year, showOriginal ? item.original_title : languageName.of(item.original_language)]
              .filter(Boolean)
              .join(' · ')}
          </p>

          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
            <span
              className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 font-medium ${
                lovedMore
                  ? 'border border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                  : 'border border-rose-500/30 bg-rose-500/10 text-rose-300'
              }`}
            >
              {lovedMore ? '▲ You liked more' : '▼ Crowd liked more'} (
              {lovedMore ? `+${item.divergence.toFixed(1)}` : item.divergence.toFixed(1)})
            </span>
          </div>

          <div className="mt-1.5 flex items-center gap-3 text-xs text-white/70">
            <span className="flex items-center gap-1">
              <span className="text-white/40">You:</span>
              <span className="font-semibold text-white">
                {reaction ? reaction.label : item.user_rating.toFixed(1)}
              </span>
            </span>
            <span className="flex items-center gap-1">
              <span className="text-white/40">Audience:</span>
              <span className="font-semibold text-white">{item.consensus_rating.toFixed(1)}</span>
            </span>
          </div>

          {item.tags.length > 0 && (
            <ul className="mt-2 flex flex-wrap gap-1" aria-label="What you thought">
              {item.tags.map((tagId) => (
                <li
                  key={tagId}
                  className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10.5px] text-white/60"
                >
                  {TAG_LABELS[tagId] ?? tagId}
                </li>
              ))}
            </ul>
          )}

          {item.note && (
            <p className="mt-2 line-clamp-2 text-xs italic text-white/60">"{item.note}"</p>
          )}
        </div>
      </div>

      <div className="mt-3 flex-1 border-t border-white/5 pt-2.5">
        {item.clash ? (
          <div className="rounded-lg border border-accent/20 bg-accent/5 p-2.5 text-xs text-white/80">
            <div className="mb-1 flex items-center justify-between">
              <span className="text-[11px] font-medium tracking-wide uppercase text-accent-strong">
                ⚡ Conflicting opinion
              </span>
              <span className="rounded-full bg-accent/10 px-1.5 py-0.2 text-[10px] text-accent-strong">
                AI
              </span>
            </div>
            <p className="leading-relaxed">{item.clash}</p>
          </div>
        ) : llmConfigured ? (
          <div>
            <Button
              variant="ghost"
              className="w-full border border-white/10 py-1.5 text-xs hover:bg-white/5"
              onClick={() => onAskClash(item.tmdb_id)}
              disabled={isAsking}
            >
              {isAsking ? 'Analyzing conflict…' : '⚡ Why did you disagree? Ask AI'}
            </Button>
            {error && (
              <div className="mt-1">
                <ErrorText>{error}</ErrorText>
              </div>
            )}
          </div>
        ) : (
          <p className="text-xs text-white/40">
            Connect AI in{' '}
            <Link to="/settings" className="underline hover:text-white">
              Settings
            </Link>{' '}
            to analyze this disagreement.
          </p>
        )}
      </div>

      <div className="mt-2">
        <WatchBadges availability={where} />
      </div>
    </li>
  )
}

function RatingCard({
  item,
  where,
  onRate,
}: {
  item: RatedTitle
  where: TitleAvailability | undefined
  onRate: (tmdbId: number) => void
}) {
  const showOriginal = item.original_title && item.original_title !== item.title
  const reaction = REACTIONS.find((r) => r.value === item.reaction)
  return (
    <li className="min-w-0">
      <button
        type="button"
        onClick={() => onRate(item.tmdb_id)}
        aria-label={`Rate ${item.title}`}
        className="group block w-full rounded-lg text-left focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:outline-none"
      >
        <div className="relative">
          <Poster path={item.poster_path} title={item.title} className="group-hover:ring-2 group-hover:ring-accent/70" />
          <span
            className="absolute top-1.5 right-1.5 flex items-center gap-1 rounded-md bg-black/80 px-1.5 py-0.5 text-xs font-semibold text-accent-strong [--thumb-bg:#000]"
            title={reaction?.label}
          >
            {item.favorite && <span aria-label="Liked on Letterboxd">♥</span>}
            {reaction ? (
              <>
                <ReactionIcon reaction={reaction.value} className="h-3.5" />
                <span className="sr-only">{reaction.label}</span>
              </>
            ) : Number.isInteger(item.rating) ? (
              item.rating
            ) : (
              item.rating.toFixed(1)
            )}
          </span>
        </div>
        <p className="mt-2 truncate text-sm font-medium" title={item.title}>
          {item.title}
        </p>
        <p className="truncate text-xs text-white/45" title={showOriginal ? item.original_title : undefined}>
          {[item.year, showOriginal ? item.original_title : languageName.of(item.original_language)]
            .filter(Boolean)
            .join(' · ')}
        </p>
        {item.tags.length > 0 && (
          <ul className="mt-1.5 flex flex-wrap gap-1" aria-label="What you thought">
            {item.tags.map((tagId) => (
              <li
                key={tagId}
                className={`rounded-full px-2 py-0.5 text-[10.5px] ${
                  item.reaction === 'disliked'
                    ? 'border border-white/10 bg-white/5 text-white/60'
                    : 'border border-accent/25 bg-accent/10 text-accent-strong'
                }`}
              >
                {TAG_LABELS[tagId] ?? tagId}
              </li>
            ))}
          </ul>
        )}
      </button>
      <WatchBadges availability={where} />
    </li>
  )
}
