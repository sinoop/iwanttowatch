import type { ChildProfile, Me, TitleDetail } from '@iwanttowatch/api-client'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api, errorMessage, facts, useAssignToChild, useChildren, useServerSettings, useShortlist } from './api'
import { RatePicker } from './RateDialog'
import { JustWatchCredit, ProviderLogo } from './Streaming'
import { Button, ErrorText, Poster } from './ui'

/** A film's details: why it was suggested, who made it, and where to watch it. */
export default function TitleDialog({ tmdbId, onClose }: { tmdbId: number | null; onClose: () => void }) {
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
      {tmdbId !== null && <Details key={tmdbId} tmdbId={tmdbId} onClose={() => dialog.current?.close()} />}
    </dialog>
  )
}

function Details({ tmdbId, onClose }: { tmdbId: number; onClose: () => void }) {
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
      <div className="flex gap-4 sm:gap-5">
        <div className="w-24 shrink-0 sm:w-32">
          <Poster path={film.poster_path} title={film.title} />
        </div>
        <div className="min-w-0">
          <h2 className="text-xl font-semibold">{film.title}</h2>
          {film.original_title !== film.title && <p className="text-sm text-white/55">{film.original_title}</p>}
          <p className="mt-1 text-sm text-white/55">{facts({ ...film, imdb: null }).join(' · ')}</p>
          {film.imdb && (
            <a
              href={`https://www.imdb.com/title/${film.imdb.id}/`}
              target="_blank"
              rel="noreferrer"
              className="mt-1 block w-fit text-sm text-white/70 underline-offset-2 hover:underline"
            >
              IMDb {film.imdb.rating.toFixed(1)}{' '}
              <span className="text-white/45">({film.imdb.votes.toLocaleString()} votes)</span>
            </a>
          )}
          {film.match !== null && <MatchBadge match={film.match} className="mt-3" />}
          {/* A reaction given here shows in the rating buttons below instead. */}
          {film.seen && !film.seen.reaction && (
            <p className="mt-3 text-sm font-medium text-accent-strong">{seenText(film.seen)}</p>
          )}
          {film.tagline && <p className="mt-3 text-sm text-white/70 italic">{film.tagline}</p>}
        </div>
      </div>

      <RatePicker tmdbId={tmdbId} compact className="mt-4" />

      {film.reasons.length > 0 && (
        <section className="mt-5">
          <h3 className="text-sm font-medium text-white/80">Why it suits you</h3>
          <ul className="mt-1.5 list-disc space-y-1 pl-5 text-sm text-white/65">
            {film.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </section>
      )}

      <WhySection film={film} />

      {film.overview && <p className="mt-5 text-sm leading-relaxed text-white/75">{film.overview}</p>}

      <ThemesSection film={film} />

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

function seenText(seen: NonNullable<TitleDetail['seen']>): string {
  if (seen.rating !== null) return `You’ve seen it · rated ${Number.isInteger(seen.rating) ? seen.rating : seen.rating.toFixed(1)}/10`
  return 'You’ve seen it'
}

/** The AI's take on how the film fits the user, asked for films the AI hasn't reviewed. */
function WhySection({ film }: { film: TitleDetail }) {
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

  if (film.explanation) {
    return (
      <section className="mt-4 rounded-xl border border-white/10 bg-white/[0.02] p-3.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-medium text-white/80">Why this?</h3>
          <span className="rounded-full bg-accent/10 px-2 py-0.5 text-[11px] font-medium text-accent-strong">
            AI-written
          </span>
        </div>
        <p className="mt-1.5 text-sm leading-relaxed text-white/70">{film.explanation}</p>
      </section>
    )
  }
  if (!llmConfigured || aiReviewed) return null
  return (
    <div className="mt-4">
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
  )
}

function ThemesSection({ film }: { film: TitleDetail }) {
  const queryClient = useQueryClient()
  const settings = useServerSettings()
  const llmConfigured = (settings.data?.llm.order.length ?? 0) > 0
  const write = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST('/api/v1/titles/{tmdb_id}/themes', {
        params: { path: { tmdb_id: film.tmdb_id } },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => queryClient.setQueryData(['title', film.tmdb_id], data),
  })

  if (!film.themes_note && !llmConfigured) return null

  return (
    <section className="mt-4 rounded-xl border border-white/10 bg-white/[0.02] p-3.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-medium text-white/80">Themes and values</h3>
        <span className="rounded-full bg-accent/10 px-2 py-0.5 text-[11px] font-medium text-accent-strong">
          AI-written
        </span>
      </div>
      {film.themes_note ? (
        <p className="mt-1.5 text-sm leading-relaxed text-white/70">{film.themes_note}</p>
      ) : (
        <div className="mt-2">
          <Button variant="ghost" className="border border-white/10 px-3 py-1 text-xs" onClick={() => write.mutate()} disabled={write.isPending}>
            {write.isPending ? 'Writing note…' : 'Write themes and values note'}
          </Button>
          {write.error && (
            <div className="mt-2">
              <ErrorText>{write.error.message}</ErrorText>
            </div>
          )}
        </div>
      )}
    </section>
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
