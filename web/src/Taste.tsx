import type { ImportJob, RatedTitle, TitleAvailability } from '@iwanttowatch/api-client'
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { api, errorMessage, REACTIONS, useAvailability, useServerSettings } from './api'
import RateDialog, { ReactionIcon } from './RateDialog'
import { WatchBadges } from './Streaming'
import { Button, ErrorText, Poster } from './ui'

const languageName = new Intl.DisplayNames(['en'], { type: 'language' })
const PAGE = 48

export default function Taste() {
  const [rating, setRating] = useState<number | null>(null)
  return (
    <>
      <h1 className="text-2xl font-semibold">My taste</h1>
      <p className="mt-2 max-w-prose text-white/60">
        Everything iWantToWatch knows about what you like. Import your history from IMDb or
        Letterboxd; importing again later only adds what changed.
      </p>
      <PersonaCard />
      <Imports />
      <Ratings onRate={setRating} />
      <RateDialog tmdbId={rating} onClose={() => setRating(null)} />
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
        Writing the sketch of the person your taste describes…
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
            to get an AI-written sketch of the person your taste describes.
          </>
        ) : !enough ? (
          `Rate at least ${p.min_ratings} movies and iWantToWatch will sketch the person your taste describes.`
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span>Ready to sketch the person your taste describes.</span>
            <Button onClick={() => write.mutate()} disabled={write.isPending}>
              {write.isPending ? 'Writing…' : 'Write my persona'}
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
      <p className="text-xs font-medium tracking-wide text-accent uppercase">Your taste as a person</p>
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
          {job.source === 'imdb' ? 'IMDb' : 'Letterboxd'}{' '}
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

function Ratings({ onRate }: { onRate: (tmdbId: number) => void }) {
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
        <h2 className="text-lg font-semibold">
          Your ratings <span className="font-normal text-white/45">{first.total}</span>
        </h2>
        {first.languages.length > 0 && (
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
      <RateSearch onRate={onRate} />
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
    </section>
  )
}

function RateSearch({ onRate }: { onRate: (tmdbId: number) => void }) {
  const settings = useServerSettings()
  const [query, setQuery] = useState('')
  const search = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.GET('/api/v1/catalog/search', { params: { query: { query } } })
      if (error) throw new Error(errorMessage(error))
      return data.slice(0, 8)
    },
  })
  if (!settings.data?.tmdb_configured) return null
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (query.trim()) search.mutate()
  }

  return (
    <div className="mt-5">
      <form onSubmit={submit} className="flex max-w-md gap-2" role="search">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Rate a film you’ve seen…"
          aria-label="Search for a film to rate"
          className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm outline-none placeholder:text-white/35 focus:border-accent focus:ring-2 focus:ring-accent/30"
        />
        <Button type="submit" variant="ghost" disabled={search.isPending}>
          Search
        </Button>
      </form>
      {search.error && (
        <div className="mt-2 max-w-md">
          <ErrorText>{search.error.message}</ErrorText>
        </div>
      )}
      {search.data && (
        <div className="mt-3 rounded-xl border border-white/10 bg-white/[0.02] p-3">
          <div className="mb-2 flex items-center justify-between gap-3 text-sm">
            <span className="text-white/60">
              {search.data.length ? 'Pick the film to rate' : 'No films found.'}
            </span>
            <Button variant="ghost" className="px-2 py-1" onClick={() => search.reset()}>
              Clear
            </Button>
          </div>
          <ul className="flex gap-3 overflow-x-auto pb-1" aria-label="Search results">
            {search.data.map((c) => (
              <li key={c.tmdb_id} className="w-24 shrink-0">
                <button
                  type="button"
                  onClick={() => onRate(c.tmdb_id)}
                  className="group w-full rounded-lg text-left focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:outline-none"
                >
                  <Poster path={c.poster_path} title={c.title} className="group-hover:ring-2 group-hover:ring-accent" />
                  <p className="mt-1 truncate text-xs font-medium">{c.title}</p>
                  <p className="truncate text-xs text-white/45">
                    {[c.year, languageName.of(c.original_language)].filter(Boolean).join(' · ')}
                  </p>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
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
      </button>
      <WatchBadges availability={where} />
    </li>
  )
}
