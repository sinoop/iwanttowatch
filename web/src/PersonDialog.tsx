import type { components, Reaction } from '@iwanttowatch/api-client'
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { fetchTitleDetail, ratingToReaction, type TitlePreview, useFavoritePerson, usePerson } from './api'
import { ReactionBadge } from './RateDialog'
import { JellyfinLogo, ProviderLogo } from './Streaming'
import { ImdbBadge, MatchBadge } from './TitleDialog'
import { segmentedBadgeClass, segmentedTabClass } from './tabs'
import { Button, ErrorText, Poster, SegmentedCapsule } from './ui'

type PersonCredit = components['schemas']['PersonCredit']

export function HeartIcon({ filled, className = 'size-4' }: { filled: boolean; className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill={filled ? 'currentColor' : 'none'}
      stroke="currentColor"
      strokeWidth={filled ? '0' : '2'}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z" />
    </svg>
  )
}

function FilmCreditRow({
  film,
  highlight,
  onPrefetchSchedule,
  onPrefetchCancel,
  onPrefetchImmediate,
  onSelect,
}: {
  film: PersonCredit
  highlight?: 'section' | 'inline'
  onPrefetchSchedule: (tmdbId: number) => void
  onPrefetchCancel: () => void
  onPrefetchImmediate: (tmdbId: number) => void
  onSelect: (film: PersonCredit) => void
}) {
  const rowClass =
    highlight === 'section'
      ? 'hover:bg-amber-400/[0.10]'
      : highlight === 'inline'
        ? 'border-l-2 border-amber-400/70 bg-amber-500/[0.07] hover:bg-amber-500/[0.12]'
        : 'hover:bg-white/[0.04]'

  const reaction =
    (film.user_reaction as Reaction | null) ||
    (film.user_rating !== null && film.user_rating !== undefined
      ? ratingToReaction(film.user_rating)
      : null)

  return (
    <button
      type="button"
      onMouseEnter={() => onPrefetchSchedule(film.tmdb_id)}
      onMouseLeave={onPrefetchCancel}
      onFocus={() => onPrefetchImmediate(film.tmdb_id)}
      onClick={() => onSelect(film)}
      className={`flex w-full items-center justify-between gap-3 rounded-lg px-2 py-2.5 text-left transition-colors group ${rowClass}`}
    >
      <div className="flex min-w-0 items-center gap-3">
        <Poster
          path={film.poster_path ?? null}
          title={film.title}
          className="w-10 shrink-0 rounded-md sm:w-11"
        />
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-semibold text-white transition-colors group-hover:text-accent">
              {film.title}
            </span>
            {film.year && <span className="shrink-0 text-xs text-white/40">({film.year})</span>}
            {highlight === 'inline' && (
              <span className="shrink-0 rounded bg-amber-400/15 px-1.5 py-0.5 text-[10px] font-semibold text-amber-300">
                Popular
              </span>
            )}
          </div>

          <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-white/50">
            {film.job && (
              <span
                className={
                  film.character
                    ? 'rounded bg-amber-500/15 px-1.5 py-0.2 text-[10px] font-semibold text-amber-300'
                    : 'font-medium text-white/70'
                }
              >
                {film.job}
              </span>
            )}
            {film.character && <span className="max-w-[200px] truncate">as {film.character}</span>}
          </div>

          {/* Badges row */}
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            {film.match !== null && film.match !== undefined && <MatchBadge match={film.match} />}
            {film.imdb_rating !== null && film.imdb_rating !== undefined ? (
              <ImdbBadge
                imdb={{ id: '', rating: film.imdb_rating, votes: film.imdb_votes ?? 0 }}
                showVotes
              />
            ) : film.vote_average ? (
              <span className="rounded bg-white/10 px-1.5 py-0.5 text-[10px] font-medium text-white/70 tabular-nums">
                TMDb {film.vote_average.toFixed(1)}
              </span>
            ) : null}
            {film.in_library && (
              <span title="On Jellyfin" className="inline-flex items-center">
                <JellyfinLogo className="size-4.5" />
                <span className="sr-only">On Jellyfin</span>
              </span>
            )}
            {film.streaming_offers?.map((offer) => (
              <span
                key={offer.provider_id}
                title={`On ${offer.name}${offer.kind === 'flatrate' ? '' : ' (free)'}`}
                className="inline-flex items-center"
              >
                <ProviderLogo path={offer.logo_path} name={offer.name} className="size-4.5" />
                <span className="sr-only">On {offer.name}</span>
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* Right status: personal reaction or watched pill */}
      <div className="flex shrink-0 items-center gap-2 text-right">
        {reaction ? (
          <ReactionBadge reaction={reaction} />
        ) : film.watched ? (
          <span className="rounded bg-white/5 px-2 py-0.5 text-xs text-white/40">✓ Watched</span>
        ) : null}
        <svg
          viewBox="0 0 20 20"
          fill="currentColor"
          className="size-4 text-white/30 transition-colors group-hover:text-white"
        >
          <path
            fillRule="evenodd"
            d="M7.21 14.77a.75.75 0 0 1 .02-1.06L11.168 10 7.23 6.29a.75.75 0 1 1 1.04-1.08l4.5 4.25a.75.75 0 0 1 0 1.08l-4.5 4.25a.75.75 0 0 1-1.06-.02Z"
            clipRule="evenodd"
          />
        </svg>
      </div>
    </button>
  )
}

interface PersonDialogProps {
  personId: number | null
  onClose: () => void
  onSelectFilm?: (tmdbId: number) => void
}

export default function PersonDialog({ personId, onClose, onSelectFilm }: PersonDialogProps) {
  const dialog = useRef<HTMLDialogElement>(null)
  const queryClient = useQueryClient()
  const prefetchTimer = useRef<number | null>(null)
  const personQuery = usePerson(personId)
  const favoriteMutation = useFavoritePerson()
  const [prevPersonId, setPrevPersonId] = useState<number | null>(personId)
  const [tab, setTab] = useState<'available' | 'all'>('available')
  const [roleFilter, setRoleFilter] = useState<'all' | 'directed' | 'acted'>('all')
  const [sortBy, setSortBy] = useState<'popular' | 'newest' | 'rating'>('popular')
  const [filmSearch, setFilmSearch] = useState('')
  const [bioExpanded, setBioExpanded] = useState(false)

  if (personId !== prevPersonId) {
    setPrevPersonId(personId)
    setTab('available')
    setRoleFilter('all')
    setSortBy('popular')
    setFilmSearch('')
    setBioExpanded(false)
  }

  const person = personQuery.data

  useEffect(() => {
    if (personId !== null) {
      dialog.current?.showModal()
    } else {
      dialog.current?.close()
    }
  }, [personId])

  const handleClose = () => {
    dialog.current?.close()
    onClose()
  }

  const allFilms = person?.filmography ?? []
  const hasDirected = allFilms.some((f) => f.job === 'Director')
  const hasActed = allFilms.some((f) => Boolean(f.character) || !f.job)
  const isDualRole = hasDirected && hasActed
  const availableFilms = allFilms.filter(
    (f) => f.in_library || (f.streaming_offers?.length ?? f.streaming_services?.length ?? 0) > 0,
  )
  const filterByRole = (films: PersonCredit[]) =>
    !isDualRole || roleFilter === 'all'
      ? films
      : films.filter((f) =>
          roleFilter === 'directed' ? f.job === 'Director' : Boolean(f.character) || !f.job,
        )

  const tabFilms = tab === 'available' ? availableFilms : allFilms
  const roleFilteredFilms = filterByRole(tabFilms)

  const normalizedQuery = filmSearch.trim().toLowerCase()
  const isSearching = normalizedQuery.length > 0
  const matchesFilmQuery = (f: PersonCredit) => {
    if (!isSearching) return true
    return (
      f.title.toLowerCase().includes(normalizedQuery) ||
      f.original_title.toLowerCase().includes(normalizedQuery) ||
      (f.character?.toLowerCase().includes(normalizedQuery) ?? false) ||
      (f.year !== null && f.year !== undefined && String(f.year).includes(normalizedQuery))
    )
  }

  const baseFilms = isSearching ? roleFilteredFilms.filter(matchesFilmQuery) : roleFilteredFilms
  const displayedFilms =
    sortBy === 'popular'
      ? baseFilms
      : [...baseFilms].sort((a, b) => {
          if (sortBy === 'newest') {
            return (b.year ?? -1) - (a.year ?? -1) || (b.vote_count ?? 0) - (a.vote_count ?? 0)
          }
          return (b.vote_average ?? -1) - (a.vote_average ?? -1) || (b.vote_count ?? 0) - (a.vote_count ?? 0)
        })

  const hasAudienceVotes = (f: PersonCredit) => (f.vote_count ?? 0) > 0 || (f.imdb_votes ?? 0) > 0
  const canHighlightPopular = tab === 'all' && roleFilteredFilms.length >= 5
  const maxPopular = Math.min(5, Math.floor(roleFilteredFilms.length / 2))
  const popularFilms = canHighlightPopular
    ? roleFilteredFilms.filter(hasAudienceVotes).slice(0, maxPopular)
    : []
  const popularIds = new Set(popularFilms.map((f) => f.tmdb_id))
  const otherFilms = canHighlightPopular
    ? roleFilteredFilms.filter((f) => !popularIds.has(f.tmdb_id))
    : roleFilteredFilms
  const hasPopularHighlights = canHighlightPopular && popularFilms.length > 0 && otherFilms.length > 0
  const showPopularSection = !isSearching && hasPopularHighlights
  const popularHasImdb = popularFilms.some((f) => (f.imdb_votes ?? 0) > 0)
  const allSearchMatchesCount =
    isSearching && tab === 'available' ? filterByRole(allFilms).filter(matchesFilmQuery).length : 0

  const prefetchFilm = (tmdbId: number) => {
    void queryClient.prefetchQuery({
      queryKey: ['title', tmdbId],
      queryFn: () => fetchTitleDetail(tmdbId),
      staleTime: 60_000,
    })
  }

  const schedulePrefetch = (tmdbId: number) => {
    if (prefetchTimer.current !== null) {
      window.clearTimeout(prefetchTimer.current)
    }
    prefetchTimer.current = window.setTimeout(() => {
      prefetchTimer.current = null
      prefetchFilm(tmdbId)
    }, 120)
  }

  const cancelPrefetch = () => {
    if (prefetchTimer.current !== null) {
      window.clearTimeout(prefetchTimer.current)
      prefetchTimer.current = null
    }
  }

  useEffect(() => () => cancelPrefetch(), [])

  const handleSelectFilm = (film: PersonCredit) => {
    cancelPrefetch()
    queryClient.setQueryData<TitlePreview>(['title-preview', film.tmdb_id], {
      title: film.title,
      year: film.year,
      poster_path: film.poster_path,
      match: film.match,
      imdb:
        film.imdb_rating !== null && film.imdb_rating !== undefined
          ? { id: '', rating: film.imdb_rating, votes: film.imdb_votes ?? 0 }
          : null,
    })
    if (onSelectFilm) {
      onSelectFilm(film.tmdb_id)
    }
  }

  const toggleFavorite = () => {
    if (!person) return
    favoriteMutation.mutate({
      personId: person.id,
      favorite: !person.is_favorite,
      name: person.name,
      role: person.known_for_department ?? undefined,
      profilePath: person.profile_path,
    })
  }

  return (
    <dialog
      ref={dialog}
      onClose={handleClose}
      className="m-auto w-full max-w-2xl rounded-2xl border border-white/10 bg-[#121316] p-0 text-white shadow-2xl backdrop:bg-black/75 backdrop:backdrop-blur-sm"
    >
      {personQuery.isLoading && (
        <div className="flex h-64 items-center justify-center">
          <span className="size-6 animate-spin rounded-full border-2 border-accent border-t-transparent" />
        </div>
      )}

      {personQuery.error && (
        <div className="p-6">
          <ErrorText>{personQuery.error.message}</ErrorText>
          <div className="mt-4 flex justify-end">
            <Button variant="ghost" onClick={handleClose}>
              Close
            </Button>
          </div>
        </div>
      )}

      {person && (
        <div className="max-h-[90vh] overflow-y-auto p-6 sm:p-7">
          {/* Top header navigation & actions */}
          <div className="flex items-center justify-between gap-3">
            <button
              type="button"
              onClick={toggleFavorite}
              disabled={favoriteMutation.isPending}
              className={`flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs font-semibold transition-colors ${
                person.is_favorite
                  ? 'border-red-500/40 bg-red-500/10 text-red-400 hover:bg-red-500/20'
                  : 'border-white/10 bg-white/5 text-white/70 hover:border-white/20 hover:text-white'
              }`}
            >
              <HeartIcon filled={person.is_favorite} className="size-3.5" />
              <span>{person.is_favorite ? 'Favorited' : 'Add to favourites'}</span>
            </button>

            <button
              type="button"
              onClick={handleClose}
              className="rounded-lg p-1.5 text-white/50 hover:bg-white/10 hover:text-white transition-colors"
              aria-label="Close"
            >
              <svg viewBox="0 0 20 20" fill="currentColor" className="size-5">
                <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
              </svg>
            </button>
          </div>

          {/* Person overview profile */}
          <div className="mt-5 flex gap-4 sm:gap-6">
            <div className="size-20 sm:size-24 shrink-0 overflow-hidden rounded-2xl border border-white/10 bg-white/5">
              {person.profile_path ? (
                <img
                  src={`https://image.tmdb.org/t/p/w185${person.profile_path}`}
                  alt={person.name}
                  className="h-full w-full object-cover"
                />
              ) : (
                <div className="flex h-full w-full items-center justify-center text-xl font-bold text-white/30">
                  {person.name.slice(0, 2).toUpperCase()}
                </div>
              )}
            </div>

            <div className="min-w-0 flex-1">
              <h2 className="text-xl font-bold tracking-tight text-white sm:text-2xl">{person.name}</h2>
              <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-white/50">
                {person.known_for_department && (
                  <span className="rounded bg-white/10 px-2 py-0.5 font-medium text-white/80">
                    {person.known_for_department}
                  </span>
                )}
                {person.birthday && (
                  <span>
                    Born {person.birthday.slice(0, 4)}
                    {person.place_of_birth ? ` in ${person.place_of_birth}` : ''}
                  </span>
                )}
                {person.deathday && <span>(Died {person.deathday.slice(0, 4)})</span>}
              </div>

              {person.biography && (
                <div className="mt-2 text-xs leading-relaxed text-white/70">
                  <p className={bioExpanded ? '' : 'line-clamp-2'}>{person.biography}</p>
                  {person.biography.length > 150 && (
                    <button
                      type="button"
                      onClick={() => setBioExpanded(!bioExpanded)}
                      className="mt-0.5 text-accent hover:underline font-medium"
                    >
                      {bioExpanded ? 'Show less' : 'Read more'}
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Taste Affinity Section */}
          <div className="mt-6 rounded-2xl border border-white/10 bg-white/[0.03] p-4 sm:p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <span className="text-xs font-semibold tracking-wider uppercase text-accent">Your taste affinity</span>
                <p className="mt-0.5 text-xs text-white/60">
                  {person.affinity.rated_count > 0
                    ? `Based on ${person.affinity.rated_count} ${person.affinity.rated_count === 1 ? 'film' : 'films'} you've rated or watched`
                    : 'Rate films to teach iWantToWatch how much you like this person’s work'}
                </p>
              </div>

              {person.affinity.rated_count > 0 && (
                <div className="flex flex-wrap items-center gap-2">
                  {person.affinity.loved_count > 0 && (
                    <ReactionBadge reaction="loved" label={`${person.affinity.loved_count} Loved`} />
                  )}
                  {person.affinity.liked_count > 0 && (
                    <ReactionBadge reaction="liked" label={`${person.affinity.liked_count} Liked`} />
                  )}
                  {person.affinity.disliked_count > 0 && (
                    <ReactionBadge reaction="disliked" label={`${person.affinity.disliked_count} Disliked`} />
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Filmography Section with Tabs */}
          <div className="mt-6">
            <div className="flex flex-wrap items-center justify-between gap-2 pb-2.5">
              <SegmentedCapsule role="tablist" aria-label="Filmography tabs">
                <button
                  type="button"
                  role="tab"
                  aria-selected={tab === 'available'}
                  onClick={() => setTab('available')}
                  className={segmentedTabClass({ active: tab === 'available', size: 'xs' })}
                >
                  <span>Available to watch</span>
                  <span className={segmentedBadgeClass({ active: tab === 'available', size: 'xs' })}>
                    {availableFilms.length}
                  </span>
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={tab === 'all'}
                  onClick={() => setTab('all')}
                  className={segmentedTabClass({ active: tab === 'all', size: 'xs' })}
                >
                  <span>All filmography</span>
                  <span className={segmentedBadgeClass({ active: tab === 'all', size: 'xs' })}>
                    {allFilms.length}
                  </span>
                </button>
              </SegmentedCapsule>
              <div className="flex items-center gap-2">
                {isDualRole && (
                  <div className="inline-flex rounded-lg border border-white/10 bg-black/40 p-0.5 text-xs">
                    {(['all', 'directed', 'acted'] as const).map((role) => (
                      <button
                        key={role}
                        type="button"
                        onClick={() => setRoleFilter(role)}
                        className={`rounded-md px-2 py-0.5 font-medium transition-colors ${
                          roleFilter === role
                            ? 'bg-accent text-white'
                            : 'text-white/60 hover:text-white'
                        }`}
                      >
                        {role === 'all' ? 'All roles' : role === 'directed' ? 'Directed' : 'Acted'}
                      </button>
                    ))}
                  </div>
                )}
                <select
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value as 'popular' | 'newest' | 'rating')}
                  aria-label="Sort filmography"
                  className="rounded-lg border border-white/10 bg-black/40 px-2.5 py-1 text-xs text-white/80 outline-none transition-colors hover:border-white/25 focus:border-accent"
                >
                  <option value="popular">Popular</option>
                  <option value="newest">Newest</option>
                  <option value="rating">Top rated</option>
                </select>
              </div>
            </div>

            {allFilms.length > 0 && (
              <div className="relative mb-2">
                <svg
                  viewBox="0 0 20 20"
                  fill="currentColor"
                  className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-white/35"
                  aria-hidden="true"
                >
                  <path
                    fillRule="evenodd"
                    d="M9 3.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11ZM2 9a7 7 0 1 1 12.452 4.391l3.328 3.329a.75.75 0 1 1-1.06 1.06l-3.329-3.328A7 7 0 0 1 2 9Z"
                    clipRule="evenodd"
                  />
                </svg>
                <input
                  type="text"
                  value={filmSearch}
                  onChange={(e) => setFilmSearch(e.target.value)}
                  placeholder={`Search ${person.name}’s films by title, role, or year…`}
                  aria-label="Search films under this person"
                  className="w-full rounded-xl border border-white/10 bg-black/35 py-2 pl-9 pr-20 text-xs text-white outline-none transition-colors placeholder:text-white/35 focus:border-accent focus:ring-2 focus:ring-accent/25"
                />
                {isSearching && (
                  <div className="absolute right-2.5 top-1/2 flex -translate-y-1/2 items-center gap-1.5">
                    <span className="text-[11px] text-white/45 tabular-nums">
                      {displayedFilms.length}
                    </span>
                    <button
                      type="button"
                      onClick={() => setFilmSearch('')}
                      className="rounded p-0.5 text-white/45 transition-colors hover:bg-white/10 hover:text-white"
                      aria-label="Clear film search"
                      title="Clear search"
                    >
                      <svg viewBox="0 0 20 20" fill="currentColor" className="size-3.5">
                        <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
                      </svg>
                    </button>
                  </div>
                )}
              </div>
            )}

            {displayedFilms.length === 0 ? (
              <div className="py-12 text-center text-xs text-white/40">
                {isSearching ? (
                  <div className="space-y-2">
                    <p>
                      {tab === 'available'
                        ? `No available films matching “${filmSearch.trim()}”.`
                        : `No films matching “${filmSearch.trim()}”.`}
                    </p>
                    <div className="flex flex-wrap items-center justify-center gap-3">
                      {tab === 'available' && allSearchMatchesCount > 0 && (
                        <button
                          type="button"
                          onClick={() => setTab('all')}
                          className="font-medium text-accent hover:underline"
                        >
                          Show {allSearchMatchesCount}{' '}
                          {allSearchMatchesCount === 1 ? 'match' : 'matches'} in All filmography →
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => setFilmSearch('')}
                        className="font-medium text-white/70 hover:text-white hover:underline"
                      >
                        Clear search
                      </button>
                    </div>
                  </div>
                ) : tab === 'available' ? (
                  <div>
                    <p>No films currently found in your Jellyfin library or subscribed streaming services.</p>
                    <button
                      type="button"
                      onClick={() => setTab('all')}
                      className="mt-2 text-accent hover:underline font-medium"
                    >
                      Browse full filmography →
                    </button>
                  </div>
                ) : (
                  <p>No film credits available.</p>
                )}
              </div>
            ) : showPopularSection && sortBy === 'popular' ? (
              <div
                key={tab}
                className="mt-3 max-h-80 sm:max-h-96 overflow-y-auto overscroll-contain pr-1.5"
              >
                <div className="rounded-xl border border-amber-400/25 bg-amber-500/[0.08] p-2.5">
                  <div className="mb-1.5 flex items-center justify-between gap-2 px-1">
                    <div className="flex items-center gap-1.5">
                      <svg
                        viewBox="0 0 20 20"
                        fill="currentColor"
                        className="size-3.5 text-amber-400"
                        aria-hidden="true"
                      >
                        <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
                      </svg>
                      <span className="text-[11px] font-semibold tracking-wider uppercase text-amber-300">
                        Popular films
                      </span>
                      <span className="rounded-full bg-amber-400/20 px-1.5 py-0.5 text-[10px] font-bold text-amber-200 tabular-nums">
                        {popularFilms.length}
                      </span>
                    </div>
                    <span className="text-[10px] text-amber-200/60">
                      {popularHasImdb ? 'IMDb & TMDb votes' : 'TMDb votes & buzz'}
                    </span>
                  </div>
                  <div className="divide-y divide-amber-400/15">
                    {popularFilms.map((film) => (
                      <FilmCreditRow
                        key={film.tmdb_id}
                        film={film}
                        highlight="section"
                        onPrefetchSchedule={schedulePrefetch}
                        onPrefetchCancel={cancelPrefetch}
                        onPrefetchImmediate={prefetchFilm}
                        onSelect={handleSelectFilm}
                      />
                    ))}
                  </div>
                </div>

                <div className="mt-3">
                  <div className="mb-1 px-2">
                    <span className="text-[11px] font-semibold tracking-wider uppercase text-white/45">
                      All other films ({otherFilms.length})
                    </span>
                  </div>
                  <div className="divide-y divide-white/5">
                    {otherFilms.map((film) => (
                      <FilmCreditRow
                        key={film.tmdb_id}
                        film={film}
                        onPrefetchSchedule={schedulePrefetch}
                        onPrefetchCancel={cancelPrefetch}
                        onPrefetchImmediate={prefetchFilm}
                        onSelect={handleSelectFilm}
                      />
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <div
                key={tab}
                className="mt-3 max-h-80 sm:max-h-96 overflow-y-auto overscroll-contain divide-y divide-white/5 pr-1.5"
              >
                {displayedFilms.map((film) => (
                  <FilmCreditRow
                    key={film.tmdb_id}
                    film={film}
                    highlight={hasPopularHighlights && popularIds.has(film.tmdb_id) ? 'inline' : undefined}
                    onPrefetchSchedule={schedulePrefetch}
                    onPrefetchCancel={cancelPrefetch}
                    onPrefetchImmediate={prefetchFilm}
                    onSelect={handleSelectFilm}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </dialog>
  )
}
