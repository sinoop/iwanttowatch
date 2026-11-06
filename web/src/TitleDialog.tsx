import type { TitleDetail } from '@iwanttowatch/api-client'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { api, errorMessage, facts } from './api'
import { JustWatchCredit, ProviderLogo } from './Streaming'
import { Button, ErrorText, Poster } from './ui'

/** A film's details: why it was suggested, who made it, and where to watch it. */
export default function TitleDialog({
  tmdbId,
  onClose,
  onRate,
}: {
  tmdbId: number | null
  onClose: () => void
  onRate: (tmdbId: number) => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    if (tmdbId !== null) dialog.current?.showModal()
    else dialog.current?.close()
  }, [tmdbId])

  return (
    <dialog
      ref={dialog}
      onClose={onClose}
      onClick={(e) => e.target === dialog.current && dialog.current.close()}
      aria-label="Film details"
      className="m-auto max-h-[calc(100dvh-2rem)] w-[min(40rem,calc(100vw-2rem))] rounded-2xl border border-white/10 bg-[#11141b] p-0 text-[#e7e9ee] shadow-2xl backdrop:bg-black/70"
    >
      {tmdbId !== null && (
        <Details key={tmdbId} tmdbId={tmdbId} onClose={() => dialog.current?.close()} onRate={() => onRate(tmdbId)} />
      )}
    </dialog>
  )
}

function Details({ tmdbId, onClose, onRate }: { tmdbId: number; onClose: () => void; onRate: () => void }) {
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
      <div className="flex gap-4 sm:gap-5">
        <div className="w-24 shrink-0 sm:w-32">
          <Poster path={film.poster_path} title={film.title} />
        </div>
        <div className="min-w-0">
          <h2 className="text-xl font-semibold">{film.title}</h2>
          {film.original_title !== film.title && <p className="text-sm text-white/55">{film.original_title}</p>}
          <p className="mt-1 text-sm text-white/55">{facts(film).join(' · ')}</p>
          {film.match !== null && <MatchBadge match={film.match} className="mt-3" />}
          {film.tagline && <p className="mt-3 text-sm text-white/70 italic">{film.tagline}</p>}
        </div>
      </div>

      {film.reasons.length > 0 && (
        <section className="mt-5">
          <h3 className="text-sm font-medium text-white/80">Why it’s suggested</h3>
          <ul className="mt-1.5 list-disc space-y-1 pl-5 text-sm text-white/65">
            {film.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </section>
      )}

      {film.overview && <p className="mt-5 text-sm leading-relaxed text-white/75">{film.overview}</p>}

      <dl className="mt-4 space-y-1 text-sm">
        {film.directors.length > 0 && (
          <div>
            <dt className="inline text-white/45">Directed by </dt>
            <dd className="inline">{film.directors.join(', ')}</dd>
          </div>
        )}
        {film.cast.length > 0 && (
          <div>
            <dt className="inline text-white/45">Starring </dt>
            <dd className="inline">{film.cast.join(', ')}</dd>
          </div>
        )}
      </dl>

      <Chips genres={film.genres} moods={film.moods} className="mt-4" />

      <WhereToWatch film={film} />

      <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
        <Button variant="ghost" onClick={onRate}>
          I’ve seen it — rate it
        </Button>
        <Button onClick={onClose}>Close</Button>
      </div>
    </div>
  )
}

function WhereToWatch({ film }: { film: TitleDetail }) {
  const { availability } = film
  const nothing = !availability.on_jellyfin && availability.offers.length === 0
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
                ▶ Play on Jellyfin
              </a>
            ) : (
              <span className="inline-flex rounded-full bg-violet-500/20 px-3 py-1 text-sm text-violet-100">
                On Jellyfin
              </span>
            )}
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

export function MatchBadge({ match, className = '' }: { match: number; className?: string }) {
  const tone =
    match >= 80
      ? 'bg-accent text-black'
      : match >= 60
        ? 'bg-accent/25 text-accent-strong'
        : 'bg-white/15 text-white/80'
  return (
    <span className={`inline-block rounded-md px-1.5 py-0.5 text-xs font-semibold ${tone} ${className}`}>
      {match}% match
    </span>
  )
}

export function Chips({ genres, moods, className = '' }: { genres: string[]; moods: string[]; className?: string }) {
  if (genres.length === 0 && moods.length === 0) return null
  return (
    <ul className={`flex flex-wrap gap-1 ${className}`} aria-label="Genres and moods">
      {moods.map((m) => (
        <li key={m} className="rounded-full bg-accent/10 px-2 py-0.5 text-[11px] text-accent-strong">
          {m}
        </li>
      ))}
      {genres.map((g) => (
        <li key={g} className="rounded-full bg-white/8 px-2 py-0.5 text-[11px] text-white/60">
          {g}
        </li>
      ))}
    </ul>
  )
}
