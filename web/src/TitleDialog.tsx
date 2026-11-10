import type { ChildProfile, Me, Reaction, TitleDetail } from '@iwanttowatch/api-client'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api, errorMessage, facts, ratingToReaction, useAssignToChild, useChildren, useServerSettings, useShortlist } from './api'
import { RatePicker, ReactionBadge } from './RateDialog'
import { JellyfinLogo, JustWatchCredit, ProviderLogo } from './Streaming'
import { Button, ErrorText, Poster } from './ui'
import PersonDialog from './PersonDialog'

/** A film's details: why it was suggested, who made it, and where to watch it. */
export default function TitleDialog({ tmdbId, onClose }: { tmdbId: number | null; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [history, setHistory] = useState<number[]>([])
  const [activeId, setActiveId] = useState<number | null>(tmdbId)
  const [prevTmdbId, setPrevTmdbId] = useState<number | null>(tmdbId)
  const [searchingTitle, setSearchingTitle] = useState<string | null>(null)
  const [personId, setPersonId] = useState<number | null>(null)

  if (tmdbId !== prevTmdbId) {
    setPrevTmdbId(tmdbId)
    setActiveId(tmdbId)
    setHistory([])
  }

  useEffect(() => {
    if (tmdbId !== null) dialog.current?.showModal()
    else dialog.current?.close()
  }, [tmdbId])

  const handleSelectFilm = async (filmName: string) => {
    setSearchingTitle(filmName)
    try {
      const cleanName = filmName.replace(/\s*\(\d{4}\)/, '').trim()
      const { data, error } = await api.GET('/api/v1/catalog/search', {
        params: { query: { query: cleanName || filmName } },
      })
      if (!error && data && data.length > 0) {
        if (activeId !== null) {
          setHistory((prev) => [...prev, activeId])
        }
        setActiveId(data[0].tmdb_id)
        return
      }
    } catch {
      // Fallback
    } finally {
      setSearchingTitle(null)
    }
    window.open(`https://www.themoviedb.org/search?query=${encodeURIComponent(filmName)}`, '_blank')
  }

  const handleBack = () => {
    setHistory((prev) => {
      if (prev.length === 0) return prev
      const nextHistory = [...prev]
      const prevId = nextHistory.pop()
      if (prevId !== undefined) {
        setActiveId(prevId)
      }
      return nextHistory
    })
  }

  return (
    <>
      <dialog
        ref={dialog}
        onClose={onClose}
        onClick={(e) => e.target === dialog.current && dialog.current.close()}
        aria-label="Film details"
        className="m-auto max-h-[calc(100dvh-2rem)] w-[min(40rem,calc(100vw-2rem))] rounded-2xl border border-white/10 bg-[#11141b] p-0 text-[#e7e9ee] shadow-2xl backdrop:bg-black/70"
      >
        {activeId !== null && (
          <Details
            key={activeId}
            tmdbId={activeId}
            onClose={() => dialog.current?.close()}
            onSelectFilm={handleSelectFilm}
            onSelectPerson={(pid) => setPersonId(pid)}
            onBack={history.length > 0 ? handleBack : undefined}
            searchingTitle={searchingTitle}
          />
        )}
      </dialog>
      <PersonDialog
        personId={personId}
        onClose={() => setPersonId(null)}
        onSelectFilm={(newTmdbId) => {
          setPersonId(null)
          if (activeId !== null) {
            setHistory((prev) => [...prev, activeId])
          }
          setActiveId(newTmdbId)
        }}
      />
    </>
  )
}

function Details({
  tmdbId,
  onClose,
  onSelectFilm,
  onSelectPerson,
  onBack,
  searchingTitle,
}: {
  tmdbId: number
  onClose: () => void
  onSelectFilm?: (title: string) => void
  onSelectPerson?: (personId: number) => void
  onBack?: () => void
  searchingTitle?: string | null
}) {
  const queryClient = useQueryClient()
  const me = queryClient.getQueryData<Me>(['me'])
  const children = useChildren(!me?.is_child)
  const shortlist = useShortlist()
  const title = useQuery({
    queryKey: ['title', tmdbId],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/titles/{tmdb_id}', { params: { path: { tmdb_id: tmdbId } } })
      if (error) throw new Error(errorMessage(error))
      return data
    },
  })
  if (title.error) {
    return (
      <div className="space-y-4 p-6">
        <ErrorText>{title.error.message}</ErrorText>
        <Button variant="ghost" onClick={onClose}>
          Close
        </Button>
      </div>
    )
  }
  const film = title.data
  if (!film) return <p className="p-6 text-sm text-white/50">Loading…</p>

  return (
    <div className="p-5 sm:p-6">
      {onBack && (
        <Button
          variant="ghost"
          onClick={onBack}
          className="mb-3 px-2 py-0.5 text-xs text-white/70 hover:text-white"
        >
          ← Back
        </Button>
      )}
      <div className="flex gap-4 sm:gap-5">
        <div className="w-24 shrink-0 sm:w-32">
          <Poster path={film.poster_path} title={film.title} />
        </div>
        <div className="min-w-0">
          <h2 className="text-xl font-semibold">{film.title}</h2>
          {film.original_title !== film.title && <p className="text-sm text-white/55">{film.original_title}</p>}
          <p className="mt-1 text-sm text-white/55">{facts(film).join(' · ')}</p>
          {(film.match !== null || film.imdb) && (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {film.match !== null && <MatchBadge match={film.match} />}
              {film.imdb && <ImdbBadge imdb={film.imdb} isLink showVotes />}
            </div>
          )}
          {/* A reaction given here shows in the rating buttons below instead. */}
          {film.seen && !film.seen.reaction && (
            <p className="mt-3 text-sm font-medium text-accent-strong">{seenText(film.seen)}</p>
          )}
          {film.tagline && <p className="mt-3 text-sm text-white/70 italic">{film.tagline}</p>}
        </div>
      </div>

      <RatePicker tmdbId={tmdbId} compact className="mt-4" />

      <WhySection film={film} onSelectFilm={onSelectFilm} searchingTitle={searchingTitle} />

      <ClashSection film={film} />

      {film.overview && <p className="mt-5 text-sm leading-relaxed text-white/75">{film.overview}</p>}

      <dl className="mt-4 space-y-2 text-sm">
        {film.directors.length > 0 && (
          <div className="flex flex-wrap items-baseline gap-1.5">
            <dt className="text-white/45">Directed by</dt>
            <dd className="flex flex-wrap gap-1.5">
              {film.directors.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => onSelectPerson?.(p.id)}
                  className="rounded-md border border-white/10 bg-white/5 px-2 py-0.5 text-xs font-medium text-white/90 hover:border-accent/40 hover:bg-accent/10 hover:text-accent transition-colors"
                >
                  {p.name}
                </button>
              ))}
            </dd>
          </div>
        )}
        {film.cast.length > 0 && (
          <div className="flex flex-wrap items-baseline gap-1.5">
            <dt className="text-white/45">Starring</dt>
            <dd className="flex flex-wrap gap-1.5">
              {film.cast.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => onSelectPerson?.(p.id)}
                  className="rounded-md border border-white/10 bg-white/5 px-2 py-0.5 text-xs font-medium text-white/90 hover:border-accent/40 hover:bg-accent/10 hover:text-accent transition-colors"
                >
                  {p.name}
                </button>
              ))}
            </dd>
          </div>
        )}
      </dl>

      <Chips genres={film.genres} moods={film.moods} className="mt-4" />

      <WhereToWatch film={film} />

      {shortlist.error && (
        <div className="mt-4">
          <ErrorText>{shortlist.error.message}</ErrorText>
        </div>
      )}
      <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          <Button
            variant="ghost"
            aria-pressed={film.shortlisted}
            disabled={shortlist.isPending}
            onClick={() => shortlist.mutate({ tmdbId, save: !film.shortlisted })}
            className={film.shortlisted ? 'text-accent-strong!' : undefined}
          >
            <BookmarkIcon filled={film.shortlisted} className="mr-1.5 inline size-4 align-[-3px]" />
            {film.shortlisted ? 'On your shortlist' : 'Add to shortlist'}
          </Button>
          {!me?.is_child && (children.data?.length ?? 0) > 0 && (
            <AssignToChildButton
              tmdbId={tmdbId}
              title={film.title}
              assigned={film.assigned_children ?? []}
              childProfiles={children.data ?? []}
            />
          )}
        </div>
        <Button onClick={onClose}>Close</Button>
      </div>
    </div>
  )
}

function seenText(_seen: NonNullable<TitleDetail['seen']>): string {
  return 'You’ve seen it'
}

/** The reasons this film fits the user: algorithmic signals, personal critique, and themes & values. */
function WhySection({
  film,
  onSelectFilm,
  searchingTitle,
}: {
  film: TitleDetail
  onSelectFilm?: (title: string) => void
  searchingTitle?: string | null
}) {
  const queryClient = useQueryClient()
  const settings = useServerSettings()
  const llmConfigured = (settings.data?.llm.order.length ?? 0) > 0
  const ask = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST('/api/v1/titles/{tmdb_id}/why', {
        params: { path: { tmdb_id: film.tmdb_id } },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => queryClient.setQueryData(['title', film.tmdb_id], data),
  })
  const aiReviewed = film.reasons.some((r) => r.startsWith('AI'))
  const nonAiReasons = film.reasons.filter((r) => !r.startsWith('AI'))
  const reasonsToShow = film.explanation ? nonAiReasons : film.reasons
  const hasAiNote = Boolean(film.explanation || film.themes_note)
  const hasContent = Boolean(
    film.explanation || film.themes_note || film.reasons.length > 0 || (llmConfigured && !aiReviewed)
  )

  if (!hasContent) return null

  return (
    <section className="mt-5 rounded-xl border border-white/10 bg-white/[0.02] p-3.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-medium text-white/80">Why it suits you</h3>
        {hasAiNote && (
          <span className="rounded-full bg-accent/10 px-2 py-0.5 text-[11px] font-medium text-accent-strong">
            AI-written
          </span>
        )}
      </div>

      {film.explanation && (
        <p className="mt-1.5 text-sm leading-relaxed text-white/70">{film.explanation}</p>
      )}

      {reasonsToShow.length > 0 && (
        <ul
          className={`list-disc space-y-1 pl-5 text-sm text-white/65 ${
            film.explanation ? 'mt-3 border-t border-white/5 pt-2.5' : 'mt-1.5'
          }`}
        >
          {reasonsToShow.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}

      {film.themes_note && (
        <div
          className={`${
            film.explanation || reasonsToShow.length > 0
              ? 'mt-3 border-t border-white/5 pt-2.5'
              : 'mt-1.5'
          }`}
        >
          {renderThemesNote(film.themes_note, onSelectFilm, searchingTitle)}
        </div>
      )}

      {!film.explanation && llmConfigured && !aiReviewed && (
        <div className={reasonsToShow.length > 0 || film.themes_note ? 'mt-3' : 'mt-2'}>
          <Button
            variant="ghost"
            className="border border-white/10 px-3 py-1 text-xs"
            onClick={() => ask.mutate()}
            disabled={ask.isPending}
          >
            {ask.isPending ? 'Asking the AI…' : 'Why this? Ask the AI'}
          </Button>
          {ask.error && (
            <div className="mt-2">
              <ErrorText>{ask.error.message}</ErrorText>
            </div>
          )}
        </div>
      )}
    </section>
  )
}

function ClashSection({ film }: { film: TitleDetail }) {
  const queryClient = useQueryClient()
  const settings = useServerSettings()
  const llmConfigured = Boolean(settings.data?.llm.order.length)

  const ask = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST('/api/v1/titles/{tmdb_id}/clash', {
        params: { path: { tmdb_id: film.tmdb_id } },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['title', film.tmdb_id], data)
      queryClient.invalidateQueries({ queryKey: ['divergent-ratings'] })
    },
  })

  const userRating = film.seen?.rating
  const audienceRating = film.imdb?.rating
  const reactionValue =
    (film.seen?.reaction as Reaction | undefined) ||
    (userRating != null ? ratingToReaction(userRating) : undefined)
  const isDivergent =
    userRating !== null &&
    userRating !== undefined &&
    audienceRating !== null &&
    audienceRating !== undefined &&
    Math.abs(userRating - audienceRating) >= 1.5

  if (!film.clash && (!isDivergent || !llmConfigured)) return null

  return (
    <section className="mt-5 rounded-xl border border-accent/25 bg-accent/5 p-3.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-medium text-accent-strong flex items-center gap-1.5">
          <span>⚡ Conflicting opinion</span>
          {audienceRating !== null && audienceRating !== undefined && (reactionValue || userRating != null) && (
            <span className="text-xs text-white/60 font-normal flex items-center gap-1.5">
              <span>(You:</span>
              {reactionValue && <ReactionBadge reaction={reactionValue} size="xs" />}
              <span>vs Audience: {audienceRating.toFixed(1)})</span>
            </span>
          )}
        </h3>
        {film.clash && (
          <span className="rounded-full bg-accent/10 px-2 py-0.5 text-[11px] font-medium text-accent-strong">
            AI-written
          </span>
        )}
      </div>

      {film.clash ? (
        <p className="mt-2 text-sm leading-relaxed text-white/80">{film.clash}</p>
      ) : (
        <div className="mt-2">
          <p className="text-xs text-white/60 mb-2">
            Your rating strongly differed from the general audience consensus.
          </p>
          <Button
            variant="ghost"
            className="border border-accent/30 text-accent-strong px-3 py-1 text-xs hover:bg-accent/10"
            onClick={() => ask.mutate()}
            disabled={ask.isPending}
          >
            {ask.isPending ? 'Analyzing with AI…' : 'Why did you disagree? Ask AI'}
          </Button>
          {ask.error && (
            <div className="mt-2">
              <ErrorText>{ask.error.message}</ErrorText>
            </div>
          )}
        </div>
      )}
    </section>
  )
}

function parseFilmTitles(text: string): string[] {
  const cleaned = text.trim().replace(/\.$/, '')
  return cleaned
    .split(/,\s*(?:and\s+)?|\s+and\s+/i)
    .map((t) => t.trim().replace(/^and\s+/i, ''))
    .filter(Boolean)
}

function OtherFilmsLinks({
  text,
  onSelect,
  searchingTitle,
}: {
  text: string
  onSelect: (title: string) => void
  searchingTitle?: string | null
}) {
  const titles = parseFilmTitles(text)
  if (titles.length === 0) return <span>{text}</span>

  return (
    <span>
      {titles.map((title, i) => {
        const isSearching = searchingTitle === title
        return (
          <span key={title}>
            {i > 0 && <span className="text-white/40">, </span>}
            <button
              type="button"
              onClick={() => onSelect(title)}
              disabled={Boolean(searchingTitle)}
              title={`View ${title}`}
              className="inline cursor-pointer underline decoration-accent/40 underline-offset-2 transition-colors hover:text-white hover:decoration-accent focus-visible:ring-1 focus-visible:ring-accent focus-visible:outline-none disabled:opacity-50"
            >
              {title}
              {isSearching && <span className="ml-1 text-xs text-accent">…</span>}
            </button>
          </span>
        )
      })}
    </span>
  )
}

function renderThemesNote(
  note: string,
  onSelectFilm?: (title: string) => void,
  searchingTitle?: string | null
) {
  const lines = note
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
  const isBulletList = lines.some((l) => /^[•\-*]\s+/.test(l))
  if (isBulletList) {
    return (
      <ul className="list-disc space-y-1.5 pl-5 text-sm leading-relaxed text-white/70">
        {lines.map((line, idx) => {
          const content = line.replace(/^[•\-*]\s+/, '')
          const match = content.match(/^(\*\*[^*]+?\*\*|[^:]+?:)\s*(.*)$/)
          if (match) {
            const label = match[1].replace(/^\*\*|\*\*$/g, '')
            const value = match[2]
            const isOtherFilms = label.toLowerCase().includes('other famous films')
            return (
              <li key={idx}>
                <span className="font-medium text-white/90">{label}</span>{' '}
                {isOtherFilms && onSelectFilm ? (
                  <OtherFilmsLinks text={value} onSelect={onSelectFilm} searchingTitle={searchingTitle} />
                ) : (
                  value
                )}
              </li>
            )
          }
          return <li key={idx}>{content}</li>
        })}
      </ul>
    )
  }
  return <p className="text-sm leading-relaxed text-white/70 whitespace-pre-line">{note}</p>
}

function WhereToWatch({ film }: { film: TitleDetail }) {
  const queryClient = useQueryClient()
  const me = queryClient.getQueryData<Me>(['me'])
  const { availability } = film
  const nothing = !availability.on_jellyfin && availability.offers.length === 0
  const others = availability.other_offers ?? []
  const elsewhere = others.filter((o) => o.kind === 'flatrate')
  const rent = others.filter((o) => o.kind === 'rent')
  const buy = others.filter((o) => o.kind === 'buy')
  const hasRentOrBuy = rent.length > 0 || buy.length > 0
  const [showRentBuy, setShowRentBuy] = useState(me?.show_rent_buy ?? false)
  const rentBuyLabel = rent.length > 0 && buy.length > 0 ? 'rent and buy' : rent.length > 0 ? 'rent' : 'buy'

  const download = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST('/api/v1/titles/{tmdb_id}/radarr', {
        params: { path: { tmdb_id: film.tmdb_id } },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => {
      queryClient.setQueryData<TitleDetail>(['title', film.tmdb_id], (current) =>
        current ? { ...current, radarr: data } : current,
      )
    },
  })

  return (
    <section className="mt-5 rounded-xl border border-white/10 p-4">
      <h3 className="text-sm font-medium text-white/80">Where to watch</h3>
      {nothing && (
        <p className="mt-1.5 text-sm text-white/55">Not on your Jellyfin server or your streaming services.</p>
      )}
      <ul className="mt-2 flex flex-wrap gap-2">
        {availability.on_jellyfin && (
          <li>
            {film.jellyfin_url ? (
              <a
                href={film.jellyfin_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-2 rounded-full bg-violet-500/20 px-3 py-1 text-sm font-medium text-violet-100 hover:bg-violet-500/30"
              >
                <JellyfinLogo className="size-4.5 rounded-full" />
                Play on Jellyfin
              </a>
            ) : (
              <span className="inline-flex items-center gap-2 rounded-full bg-violet-500/20 px-3 py-1 text-sm text-violet-100">
                <JellyfinLogo className="size-4.5 rounded-full" />
                On Jellyfin
              </span>
            )}
          </li>
        )}
        {!availability.on_jellyfin && film.radarr?.configured && (
          <li>
            {film.radarr.has_file ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/20 px-3 py-1 text-sm font-medium text-emerald-300">
                ✓ Downloaded in Radarr
              </span>
            ) : film.radarr.monitored ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-500/20 px-3 py-1 text-sm font-medium text-amber-300">
                ⏳ Downloading in Radarr
              </span>
            ) : (
              <button
                type="button"
                disabled={download.isPending || me?.is_child}
                onClick={() => download.mutate()}
                className="inline-flex items-center gap-1.5 rounded-full bg-sky-500/20 px-3 py-1 text-sm font-medium text-sky-200 hover:bg-sky-500/30 disabled:opacity-50"
              >
                <DownloadIcon className="size-4" />
                {download.isPending ? 'Requesting…' : 'Download via Radarr'}
              </button>
            )}
          </li>
        )}
        {film.radarr?.radarr_url && (
          <li>
            <a
              href={film.radarr.radarr_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 rounded-full border border-white/10 px-3 py-1 text-xs text-white/50 hover:bg-white/5 hover:text-white/80"
            >
              Open in Radarr ↗
            </a>
          </li>
        )}
        {availability.offers.map((offer) => (
          <li
            key={offer.provider_id}
            className="flex items-center gap-2 rounded-full border border-white/10 py-1 pr-3 pl-1 text-sm"
          >
            <ProviderLogo path={offer.logo_path} name={offer.name} className="size-6" />
            {offer.name}
            {offer.kind !== 'flatrate' && <span className="text-white/45">free</span>}
          </li>
        ))}
      </ul>
      {download.error && (
        <div className="mt-2">
          <ErrorText>{download.error.message}</ErrorText>
        </div>
      )}
      <OtherOffers label="On other streaming services" offers={elsewhere} />
      {showRentBuy && (
        <>
          <OtherOffers label="Rent" offers={rent} />
          <OtherOffers label="Buy" offers={buy} />
        </>
      )}
      {hasRentOrBuy && (
        <div className="mt-3">
          <button
            type="button"
            onClick={() => setShowRentBuy((v) => !v)}
            className="text-xs text-white/50 underline-offset-2 hover:text-white/80 hover:underline"
          >
            {showRentBuy ? `Hide ${rentBuyLabel} options` : `Show ${rentBuyLabel} options`}
          </button>
        </div>
      )}
      {availability.stale && availability.checked_at && (
        <p className="mt-2 text-xs text-amber-300/80">
          Last checked {new Date(availability.checked_at).toLocaleDateString()}
        </p>
      )}
      <p className="mt-3 text-xs text-white/40">
        {availability.link && (
          <>
            <a href={availability.link} target="_blank" rel="noreferrer" className="underline-offset-2 hover:underline">
              All options on TMDb
            </a>
            {' · '}
          </>
        )}
        <JustWatchCredit />
      </p>
    </section>
  )
}

/** Services the user can't play a film on now, such as ones they don't pay for or to rent. */
function OtherOffers({ label, offers }: { label: string; offers: TitleDetail['availability']['offers'] }) {
  if (offers.length === 0) return null
  return (
    <div className="mt-3">
      <h4 className="text-xs font-medium text-white/50">{label}</h4>
      <ul className="mt-1.5 flex flex-wrap gap-2">
        {offers.map((offer) => (
          <li
            key={offer.provider_id}
            className="flex items-center gap-2 rounded-full border border-white/10 py-1 pr-3 pl-1 text-sm text-white/65"
          >
            <ProviderLogo path={offer.logo_path} name={offer.name} className="size-6" />
            {offer.name}
          </li>
        ))}
      </ul>
    </div>
  )
}

export function MatchBadge({ match, className = '' }: { match: number; className?: string }) {
  const clamped = Math.max(0, Math.min(100, match))
  const arcColor =
    match >= 80 ? 'text-emerald-400' : match >= 60 ? 'text-accent' : 'text-white/55'
  return (
    <span
      title={`${match}% match`}
      aria-label={`${match}% match`}
      className={`inline-grid size-10 shrink-0 place-items-center rounded-full bg-black/85 ring-1 ring-white/15 backdrop-blur-sm ${className}`}
    >
      <svg viewBox="0 0 36 36" className="col-start-1 row-start-1 size-full -rotate-90" aria-hidden="true">
        <circle
          cx="18"
          cy="18"
          r="14.5"
          fill="none"
          stroke="currentColor"
          strokeWidth="3"
          className="text-white/15"
        />
        {clamped > 0 && (
          <circle
            cx="18"
            cy="18"
            r="14.5"
            fill="none"
            stroke="currentColor"
            strokeWidth="3"
            strokeLinecap="round"
            pathLength={100}
            strokeDasharray={`${clamped} 100`}
            className={arcColor}
          />
        )}
      </svg>
      <span className="col-start-1 row-start-1 flex items-baseline text-[11px] leading-none font-bold tracking-tight text-white tabular-nums">
        {match}
        <span className="text-[8px] font-semibold text-white/75">%</span>
      </span>
    </span>
  )
}

export function ImdbBadge({
  imdb,
  className = '',
  showVotes = false,
  isLink = false,
}: {
  imdb: { id: string; rating: number; votes: number }
  className?: string
  showVotes?: boolean
  isLink?: boolean
}) {
  const color =
    imdb.rating >= 7.5 ? 'text-emerald-400' : imdb.rating >= 6.0 ? 'text-accent' : 'text-white/55'

  const content = (
    <>
      <span className="rounded bg-[#f5c518] px-1 py-0.5 text-[9.5px] font-black leading-none text-black tracking-tight select-none">
        IMDb
      </span>
      <span className={`text-[12px] font-bold leading-none tabular-nums ${color}`}>
        {imdb.rating.toFixed(1)}
      </span>
      {showVotes && imdb.votes > 0 && (
        <span className="text-[11px] font-normal text-white/45">
          ({imdb.votes >= 1_000_000
            ? `${(imdb.votes / 1_000_000).toFixed(1)}M`
            : imdb.votes >= 1_000
              ? `${Math.round(imdb.votes / 1_000)}k`
              : imdb.votes.toLocaleString()})
        </span>
      )}
    </>
  )

  const classes = `inline-flex h-10 shrink-0 items-center gap-1.5 rounded-full bg-black/85 px-2.5 ring-1 ring-white/15 backdrop-blur-sm ${
    isLink ? 'transition-all hover:ring-white/30 hover:bg-black/95' : ''
  } ${className}`

  if (isLink) {
    return (
      <a
        href={`https://www.imdb.com/title/${imdb.id}/`}
        target="_blank"
        rel="noreferrer"
        title={`IMDb rating ${imdb.rating.toFixed(1)} (${imdb.votes.toLocaleString()} votes)`}
        aria-label={`IMDb rating ${imdb.rating.toFixed(1)} (${imdb.votes.toLocaleString()} votes)`}
        className={classes}
      >
        {content}
      </a>
    )
  }

  return (
    <span
      title={`IMDb rating ${imdb.rating.toFixed(1)} (${imdb.votes.toLocaleString()} votes)`}
      aria-label={`IMDb rating ${imdb.rating.toFixed(1)}`}
      className={classes}
    >
      {content}
    </span>
  )
}

/** Standard TMDb genres that mirror a mood tag in the curated vocabulary. */
const REDUNDANT_GENRES: Record<string, string> = {
  thrilling: 'thriller',
  scary: 'horror',
  funny: 'comedy',
  romantic: 'romance',
  'true story': 'documentary',
}

export function Chips({
  genres,
  moods,
  max,
  className = '',
}: {
  genres: string[]
  moods: string[]
  max?: number
  className?: string
}) {
  const redundant = new Set(moods.map((m) => REDUNDANT_GENRES[m.trim().toLowerCase()]).filter(Boolean))
  const visibleGenres = genres.filter((g) => !redundant.has(g.trim().toLowerCase()))
  const remaining = max !== undefined ? Math.max(0, max - moods.length) : undefined
  const displayedGenres = remaining !== undefined ? visibleGenres.slice(0, remaining) : visibleGenres

  if (moods.length === 0 && displayedGenres.length === 0) return null
  return (
    <ul className={`flex flex-wrap gap-1 ${className}`} aria-label="Genres and moods">
      {moods.map((m) => (
        <li key={m} className="rounded-full bg-accent/10 px-2 py-0.5 text-[11px] text-accent-strong">
          {m}
        </li>
      ))}
      {displayedGenres.map((g) => (
        <li key={g} className="rounded-full bg-white/8 px-2 py-0.5 text-[11px] text-white/60">
          {g}
        </li>
      ))}
    </ul>
  )
}

/** A bookmark: outlined, or filled once the film is on the shortlist. */
export function BookmarkIcon({ filled, className = 'size-4' }: { filled: boolean; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      <path
        d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"
        fill={filled ? 'currentColor' : 'none'}
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export function DownloadIcon({ className = 'size-4' }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  )
}

/** Dropdown button to assign or unassign a film to household child accounts. */
export function AssignToChildButton({
  tmdbId,
  title,
  assigned,
  childProfiles,
  compact = false,
}: {
  tmdbId: number
  title: string
  assigned: number[]
  childProfiles: ChildProfile[]
  compact?: boolean
}) {
  const [open, setOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const assign = useAssignToChild()

  useEffect(() => {
    if (!open) return
    const onPointerDown = (e: PointerEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setOpen(false)
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('pointerdown', onPointerDown)
    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('pointerdown', onPointerDown)
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  if (childProfiles.length === 0) return null
  const assignedChildren = childProfiles.filter((c) => assigned.includes(c.id))
  const hasAssigned = assignedChildren.length > 0
  const label = hasAssigned
    ? `Assigned to ${assignedChildren.map((c) => c.name).join(', ')}`
    : `Assign ${title} to a child profile`

  return (
    <div ref={menuRef} className="relative inline-flex">
      {compact ? (
        <button
          type="button"
          title={label}
          aria-label={label}
          aria-haspopup="menu"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          className={`flex h-8 min-w-8 items-center justify-center gap-1 rounded-full px-1.5 transition-colors focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:outline-none ${
            hasAssigned ? 'bg-accent/15 text-accent-strong' : 'text-white/45 hover:bg-white/10 hover:text-white'
          }`}
        >
          <svg viewBox="0 0 24 24" className="size-4 shrink-0" aria-hidden="true">
            <path
              d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M19 8v6M22 11h-6"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          {hasAssigned && (
            <span className="flex items-center -space-x-1" aria-hidden>
              {assignedChildren.slice(0, 3).map((c) => (
                <span
                  key={c.id}
                  className="flex size-4 items-center justify-center rounded-full bg-accent text-[9px] font-bold text-black ring-1 ring-[#0c0e13]"
                >
                  {c.name.slice(0, 1).toUpperCase()}
                </span>
              ))}
            </span>
          )}
        </button>
      ) : (
        <Button
          variant="ghost"
          aria-haspopup="menu"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          className={hasAssigned ? 'text-accent-strong!' : undefined}
        >
          <svg viewBox="0 0 24 24" className="mr-1.5 inline size-4 align-[-3px]" aria-hidden="true">
            <path
              d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M19 8v6M22 11h-6"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          {hasAssigned ? `For ${assignedChildren.map((c) => c.name).join(', ')}` : 'Assign to child'}
        </Button>
      )}
      {open && (
        <div
          role="menu"
          aria-label={`Assign ${title} to child profile`}
          className="absolute bottom-full left-0 z-20 mb-1.5 w-48 rounded-xl border border-white/10 bg-[#151922] p-1.5 shadow-2xl shadow-black/70"
        >
          <p className="px-2 py-1 text-[11px] font-medium tracking-wide text-white/40 uppercase">Child shortlist</p>
          {childProfiles.map((child) => {
            const on = assigned.includes(child.id)
            return (
              <button
                key={child.id}
                type="button"
                role="menuitemcheckbox"
                aria-checked={on}
                disabled={assign.isPending}
                onClick={() => assign.mutate({ childId: child.id, tmdbId, save: !on })}
                className={`flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 text-left text-sm transition-colors ${
                  on ? 'bg-accent/15 text-accent-strong' : 'text-white/75 hover:bg-white/5 hover:text-white'
                }`}
              >
                <span className="min-w-0 flex-1 truncate">{child.name}</span>
                {child.max_certificate && <span className="text-xs opacity-50">{child.max_certificate}</span>}
                {on && <span aria-hidden>✓</span>}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
