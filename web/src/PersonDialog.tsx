import type { Reaction } from '@iwanttowatch/api-client'
import { useEffect, useRef, useState } from 'react'
import { ratingToReaction, useFavoritePerson, usePerson } from './api'
import { ReactionBadge } from './RateDialog'
import { Button, ErrorText, Poster } from './ui'

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

interface PersonDialogProps {
  personId: number | null
  onClose: () => void
  onSelectFilm?: (tmdbId: number) => void
}

export default function PersonDialog({ personId, onClose, onSelectFilm }: PersonDialogProps) {
  const dialog = useRef<HTMLDialogElement>(null)
  const personQuery = usePerson(personId)
  const favoriteMutation = useFavoritePerson()
  const [prevPersonId, setPrevPersonId] = useState<number | null>(personId)
  const [tab, setTab] = useState<'available' | 'all'>('available')
  const [bioExpanded, setBioExpanded] = useState(false)

  if (personId !== prevPersonId) {
    setPrevPersonId(personId)
    setTab('available')
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
  const availableFilms = allFilms.filter((f) => f.in_library || (f.streaming_services?.length ?? 0) > 0)
  const displayedFilms = tab === 'available' ? availableFilms : allFilms

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
            <div className="flex items-center justify-between border-b border-white/10 pb-3">
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setTab('available')}
                  className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                    tab === 'available'
                      ? 'bg-white/15 text-white'
                      : 'text-white/60 hover:bg-white/5 hover:text-white'
                  }`}
                >
                  Available to watch ({availableFilms.length})
                </button>
                <button
                  type="button"
                  onClick={() => setTab('all')}
                  className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                    tab === 'all'
                      ? 'bg-white/15 text-white'
                      : 'text-white/60 hover:bg-white/5 hover:text-white'
                  }`}
                >
                  All filmography ({allFilms.length})
                </button>
              </div>
            </div>

            {displayedFilms.length === 0 ? (
              <div className="py-12 text-center text-xs text-white/40">
                {tab === 'available' ? (
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
            ) : (
              <div
                key={tab}
                className="mt-3 max-h-80 sm:max-h-96 overflow-y-auto overscroll-contain divide-y divide-white/5 pr-1.5"
              >
                {displayedFilms.map((film) => (
                  <button
                    key={film.tmdb_id}
                    type="button"
                    onClick={() => {
                      if (onSelectFilm) {
                        onSelectFilm(film.tmdb_id)
                      }
                    }}
                    className="flex w-full items-center justify-between gap-3 py-2.5 text-left transition-colors hover:bg-white/[0.04] rounded-lg px-2 group"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <Poster
                        path={film.poster_path ?? null}
                        title={film.title}
                        className="w-10 sm:w-11 shrink-0 rounded-md"
                      />
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-sm text-white group-hover:text-accent transition-colors truncate">
                            {film.title}
                          </span>
                          {film.year && <span className="text-xs text-white/40 shrink-0">({film.year})</span>}
                        </div>

                        <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-white/50">
                          {film.job && <span className="font-medium text-white/70">{film.job}</span>}
                          {film.character && (
                            <span className="truncate max-w-[200px]">as {film.character}</span>
                          )}
                        </div>

                        {/* Badges row */}
                        <div className="mt-1 flex flex-wrap items-center gap-1.5">
                          {film.in_library && (
                            <span className="rounded bg-indigo-500/20 px-1.5 py-0.2 text-[10px] font-semibold text-indigo-300">
                              On Jellyfin
                            </span>
                          )}
                          {film.streaming_services?.map((svc) => (
                            <span
                              key={svc}
                              className="rounded bg-emerald-500/15 px-1.5 py-0.2 text-[10px] font-medium text-emerald-300"
                            >
                              On {svc}
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>

                    {/* Right status: personal reaction or watched pill */}
                    <div className="shrink-0 flex items-center gap-2 text-right">
                      {(() => {
                        const reaction =
                          (film.user_reaction as Reaction | null) ||
                          (film.user_rating !== null && film.user_rating !== undefined
                            ? ratingToReaction(film.user_rating)
                            : null)
                        if (reaction) {
                          return <ReactionBadge reaction={reaction} />
                        }
                        if (film.watched) {
                          return (
                            <span className="rounded bg-white/5 px-2 py-0.5 text-xs text-white/40">
                              ✓ Watched
                            </span>
                          )
                        }
                        return null
                      })()}
                      <svg
                        viewBox="0 0 20 20"
                        fill="currentColor"
                        className="size-4 text-white/30 group-hover:text-white transition-colors"
                      >
                        <path
                          fillRule="evenodd"
                          d="M7.21 14.77a.75.75 0 0 1 .02-1.06L11.168 10 7.23 6.29a.75.75 0 1 1 1.04-1.08l4.5 4.25a.75.75 0 0 1 0 1.08l-4.5 4.25a.75.75 0 0 1-1.06-.02Z"
                          clipRule="evenodd"
                        />
                      </svg>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </dialog>
  )
}
