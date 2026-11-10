import type { DivergentTitle, Me, RatedTitle, TitleAvailability } from '@iwanttowatch/api-client'
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { api, errorMessage, REACTIONS, TAG_LABELS, useAvailability, useImports, usePeopleTaste, useServerSettings } from './api'
import RateDialog, { ReactionIcon } from './RateDialog'
import PersonDialog, { HeartIcon } from './PersonDialog'
import { FilmSearch } from './Search'
import { WatchBadges } from './Streaming'
import TitleDialog from './TitleDialog'
import { Button, ErrorText, Poster } from './ui'

const languageName = new Intl.DisplayNames(['en'], { type: 'language' })
const PAGE = 48

export default function Taste({ me }: { me: Me }) {
  const [rating, setRating] = useState<number | null>(null)
  const [detailId, setDetailId] = useState<number | null>(null)
  const isChild = me.is_child
  const imports = useImports()

  const runningJob = !isChild
    ? imports.data?.find((job) => job.status === 'pending' || job.status === 'running')
    : undefined
  const reviewCount = !isChild
    ? imports.data?.reduce(
        (sum, job) => sum + (job.status !== 'pending' && job.status !== 'running' ? job.counts.review : 0),
        0,
      ) ?? 0
    : 0

  return (
    <>
      {runningJob && (
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-accent/30 bg-accent/10 p-4 text-sm">
          <div className="flex items-center gap-2.5">
            <span className="size-2 animate-pulse rounded-full bg-accent" />
            <span className="text-white/90">
              Matching ratings from <span className="font-medium text-white">{runningJob.source}</span> ({runningJob.filename}) in the background…
            </span>
          </div>
          <Link to="/settings/imports" className="font-semibold text-accent hover:underline">
            View progress →
          </Link>
        </div>
      )}

      {reviewCount > 0 && !runningJob && (
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/5 p-4 text-sm">
          <span className="text-white/80">
            You have <span className="font-medium text-white">{reviewCount}</span> imported {reviewCount === 1 ? 'rating' : 'ratings'} to review.
          </span>
          <Link to="/settings/imports" className="font-semibold text-accent hover:underline">
            Review matches →
          </Link>
        </div>
      )}

      <Ratings onRate={setRating} onSelectFilm={setDetailId} />
      <RateDialog tmdbId={rating} onClose={() => setRating(null)} />
      <TitleDialog tmdbId={detailId} onClose={() => setDetailId(null)} />
    </>
  )
}

function Ratings({
  onRate,
  onSelectFilm,
}: {
  onRate: (tmdbId: number) => void
  onSelectFilm: (tmdbId: number) => void
}) {
  const [tab, setTab] = useState<'all' | 'divergent' | 'people'>('all')
  const [personDetailId, setPersonDetailId] = useState<number | null>(null)
  const peopleTaste = usePeopleTaste()

  // Filter & sort states
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [reactionFilter, setReactionFilter] = useState<string | null>(null)
  const [languageFilter, setLanguageFilter] = useState<string | null>(null)
  const [genreFilter, setGenreFilter] = useState<string | null>(null)
  const [decadeFilter, setDecadeFilter] = useState<number | null>(null)
  const [tagFilter, setTagFilter] = useState<string | null>(null)
  const [personFilter, setPersonFilter] = useState('')
  const [debouncedPerson, setDebouncedPerson] = useState('')
  const [watchOnFilter, setWatchOnFilter] = useState<string | null>(null)
  const [hasNoteFilter, setHasNoteFilter] = useState(false)
  const [sortOrder, setSortOrder] = useState<string>('newest')

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 250)
    return () => clearTimeout(timer)
  }, [search])

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedPerson(personFilter), 250)
    return () => clearTimeout(timer)
  }, [personFilter])

  const isFiltered = Boolean(
    search.trim() ||
      reactionFilter ||
      languageFilter ||
      genreFilter ||
      decadeFilter !== null ||
      tagFilter ||
      personFilter.trim() ||
      watchOnFilter ||
      hasNoteFilter ||
      sortOrder !== 'newest',
  )

  const clearFilters = () => {
    setSearch('')
    setDebouncedSearch('')
    setReactionFilter(null)
    setLanguageFilter(null)
    setGenreFilter(null)
    setDecadeFilter(null)
    setTagFilter(null)
    setPersonFilter('')
    setDebouncedPerson('')
    setWatchOnFilter(null)
    setHasNoteFilter(false)
    setSortOrder('newest')
  }

  const selectClass = (active: boolean) =>
    `rounded-lg border px-3 py-1.5 text-sm outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-accent/30 ${
      active
        ? 'border-accent/60 bg-accent/10 text-accent-strong'
        : 'border-white/10 bg-black/30 text-white/80 hover:border-white/25 hover:text-white'
    }`

  const ratings = useInfiniteQuery({
    queryKey: [
      'ratings',
      debouncedSearch,
      reactionFilter,
      languageFilter,
      genreFilter,
      decadeFilter,
      tagFilter,
      debouncedPerson,
      watchOnFilter,
      hasNoteFilter,
      sortOrder,
    ],
    initialPageParam: 0,
    queryFn: async ({ pageParam }) =>
      (
        await api.GET('/api/v1/ratings', {
          params: {
            query: {
              limit: PAGE,
              offset: pageParam,
              query: debouncedSearch.trim() || undefined,
              reaction: reactionFilter || undefined,
              language: languageFilter || undefined,
              genre: genreFilter || undefined,
              decade: decadeFilter ?? undefined,
              tag: tagFilter || undefined,
              person: debouncedPerson.trim() || undefined,
              watch_on: watchOnFilter || undefined,
              has_note: hasNoteFilter || undefined,
              sort: sortOrder,
            },
          },
        })
      ).data ?? {
        total: 0,
        total_unfiltered: 0,
        items: [],
        languages: [],
        genres: [],
        decades: [],
        tags: [],
        reactions: {},
        top_people: [],
        has_notes_count: 0,
      },
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
    <section>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="max-w-full overflow-x-auto pb-1">
          <div className="inline-flex items-center gap-1.5 rounded-2xl border border-white/10 bg-white/[0.04] p-1.5 shadow-lg shadow-black/20 backdrop-blur-md">
            <button
              type="button"
              onClick={() => setTab('all')}
              className={`flex cursor-pointer items-center gap-2.5 rounded-xl px-4 py-2 text-sm font-semibold whitespace-nowrap transition-all ${
                tab === 'all'
                  ? 'border border-white/15 bg-white/15 text-white shadow-sm'
                  : 'border border-transparent text-white/60 hover:bg-white/5 hover:text-white'
              }`}
            >
              <span>Your ratings</span>
              <span
                className={`rounded-full px-2 py-0.5 text-[11px] font-bold leading-none transition-colors ${
                  tab === 'all' ? 'bg-accent text-black' : 'bg-white/10 text-white/60'
                }`}
              >
                {first.total_unfiltered || first.total}
              </span>
            </button>

            <button
              type="button"
              onClick={() => setTab('divergent')}
              className={`flex cursor-pointer items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold whitespace-nowrap transition-all ${
                tab === 'divergent'
                  ? 'border border-white/15 bg-white/15 text-white shadow-sm'
                  : 'border border-transparent text-white/60 hover:bg-white/5 hover:text-white'
              }`}
            >
              <span>Against the grain</span>
              <span
                className={`rounded-full border px-2 py-0.5 text-[11px] font-medium leading-none transition-colors ${
                  tab === 'divergent'
                    ? 'border-accent/50 bg-accent/25 font-semibold text-accent-strong'
                    : 'border-accent/30 bg-accent/15 text-accent'
                }`}
              >
                Hot takes
              </span>
            </button>

            <button
              type="button"
              onClick={() => setTab('people')}
              className={`flex cursor-pointer items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold whitespace-nowrap transition-all ${
                tab === 'people'
                  ? 'border border-white/15 bg-white/15 text-white shadow-sm'
                  : 'border border-transparent text-white/60 hover:bg-white/5 hover:text-white'
              }`}
            >
              <span>Directors & Cast</span>
              {(peopleTaste.data?.favorites?.length ?? 0) > 0 && (
                <span
                  className={`rounded-full border px-2 py-0.5 text-[11px] font-medium leading-none transition-colors ${
                    tab === 'people'
                      ? 'border-red-500/50 bg-red-500/25 font-semibold text-red-300'
                      : 'border-red-500/30 bg-red-500/15 text-red-400'
                  }`}
                >
                  {peopleTaste.data?.favorites?.length} fav
                </span>
              )}
            </button>
          </div>
        </div>
        {tab === 'all' && first.languages.length > 0 && (
          <ul className="flex flex-wrap gap-2" aria-label="Languages you rated">
            {first.languages.map((lang) => {
              const active = languageFilter === lang.language
              return (
                <li key={lang.language}>
                  <button
                    type="button"
                    onClick={() => setLanguageFilter(active ? null : lang.language)}
                    className={`cursor-pointer rounded-full px-3 py-1 text-xs transition-colors ${
                      active
                        ? 'border border-accent/60 bg-accent/20 text-accent font-semibold'
                        : 'bg-white/5 text-white/70 hover:bg-white/10 hover:text-white'
                    }`}
                  >
                    {languageName.of(lang.language) ?? lang.language}{' '}
                    <span className={active ? 'text-accent/80' : 'text-white/40'}>{lang.count}</span>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      {tab === 'divergent' ? (
        <DivergentSection onRate={onRate} onSelectFilm={onSelectFilm} />
      ) : tab === 'people' ? (
        <PeopleSection onSelectPerson={(id) => setPersonDetailId(id)} />
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

          {/* Filter & Sort Controls */}
          {first.total_unfiltered > 0 && (
            <div className="mt-6 space-y-3 rounded-2xl border border-white/10 bg-white/[0.02] p-4">
              {/* Row 1: Reaction pills & quick toggles */}
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setReactionFilter(null)}
                    className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-colors cursor-pointer ${
                      reactionFilter === null
                        ? 'bg-white text-black font-semibold'
                        : 'bg-white/5 text-white/70 hover:bg-white/10 hover:text-white'
                    }`}
                  >
                    All
                    <span className={reactionFilter === null ? 'text-black/60' : 'text-white/40'}>
                      {first.total_unfiltered}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setReactionFilter(reactionFilter === 'loved' ? null : 'loved')}
                    className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-colors cursor-pointer ${
                      reactionFilter === 'loved'
                        ? 'bg-accent text-black font-semibold ring-2 ring-accent/50'
                        : 'bg-white/5 text-white/70 hover:bg-white/10 hover:text-white'
                    }`}
                  >
                    <ReactionIcon reaction="loved" className="h-3.5" />
                    <span>Loved</span>
                    <span className={reactionFilter === 'loved' ? 'text-black/60' : 'text-white/40'}>
                      {first.reactions?.loved ?? 0}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setReactionFilter(reactionFilter === 'liked' ? null : 'liked')}
                    className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-colors cursor-pointer ${
                      reactionFilter === 'liked'
                        ? 'bg-accent text-black font-semibold ring-2 ring-accent/50'
                        : 'bg-white/5 text-white/70 hover:bg-white/10 hover:text-white'
                    }`}
                  >
                    <ReactionIcon reaction="liked" className="h-3.5" />
                    <span>Liked</span>
                    <span className={reactionFilter === 'liked' ? 'text-black/60' : 'text-white/40'}>
                      {first.reactions?.liked ?? 0}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setReactionFilter(reactionFilter === 'disliked' ? null : 'disliked')}
                    className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-colors cursor-pointer ${
                      reactionFilter === 'disliked'
                        ? 'bg-white text-black font-semibold ring-2 ring-white/50'
                        : 'bg-white/5 text-white/70 hover:bg-white/10 hover:text-white'
                    }`}
                  >
                    <ReactionIcon reaction="disliked" className="h-3.5" />
                    <span>Didn’t like</span>
                    <span className={reactionFilter === 'disliked' ? 'text-black/60' : 'text-white/40'}>
                      {first.reactions?.disliked ?? 0}
                    </span>
                  </button>

                  {first.has_notes_count > 0 && (
                    <button
                      type="button"
                      onClick={() => setHasNoteFilter(!hasNoteFilter)}
                      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-colors cursor-pointer ${
                        hasNoteFilter
                          ? 'border border-amber-400/50 bg-amber-400/20 text-amber-300'
                          : 'bg-white/5 text-white/70 hover:bg-white/10 hover:text-white'
                      }`}
                    >
                      <span>📝 With notes</span>
                      <span className={hasNoteFilter ? 'text-amber-200' : 'text-white/40'}>
                        {first.has_notes_count}
                      </span>
                    </button>
                  )}
                </div>

                {isFiltered && (
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-white/50">
                      Showing {first.total} of {first.total_unfiltered}
                    </span>
                    <button
                      type="button"
                      onClick={clearFilters}
                      className="cursor-pointer text-xs font-semibold text-accent hover:underline"
                    >
                      Reset filters
                    </button>
                  </div>
                )}
              </div>

              {/* Row 2: Search, Person, Genre, Language, Decade, Tag, Watch on, Sort */}
              <div className="flex flex-wrap items-center gap-2.5 pt-1">
                {/* Search title */}
                <div className="relative min-w-[160px] flex-1 sm:max-w-xs">
                  <input
                    type="text"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Filter by title…"
                    aria-label="Filter rated films by title"
                    className="w-full rounded-lg border border-white/10 bg-black/30 pl-7 pr-7 py-1.5 text-sm text-white outline-none placeholder:text-white/30 focus:border-accent focus:ring-2 focus:ring-accent/30"
                  />
                  <span className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-xs text-white/40">
                    🔍
                  </span>
                  {search && (
                    <button
                      type="button"
                      onClick={() => setSearch('')}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-sm text-white/40 hover:text-white cursor-pointer"
                      title="Clear search"
                    >
                      ×
                    </button>
                  )}
                </div>

                {/* Director / Actor */}
                <div className="relative min-w-[150px] flex-1 sm:max-w-xs">
                  <input
                    type="text"
                    list="taste-top-people"
                    value={personFilter}
                    onChange={(e) => setPersonFilter(e.target.value)}
                    placeholder="Director or actor…"
                    aria-label="Filter by director or actor"
                    className={`w-full rounded-lg border pl-3 pr-7 py-1.5 text-sm outline-none placeholder:text-white/30 transition-colors focus:border-accent focus:ring-2 focus:ring-accent/30 ${
                      personFilter
                        ? 'border-accent/60 bg-accent/10 text-accent-strong'
                        : 'border-white/10 bg-black/30 text-white/80 hover:border-white/25 hover:text-white'
                    }`}
                  />
                  {first.top_people.length > 0 && (
                    <datalist id="taste-top-people">
                      {first.top_people.map((name) => (
                        <option key={name} value={name} />
                      ))}
                    </datalist>
                  )}
                  {personFilter && (
                    <button
                      type="button"
                      onClick={() => setPersonFilter('')}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-sm text-white/40 hover:text-white cursor-pointer"
                      title="Clear person filter"
                    >
                      ×
                    </button>
                  )}
                </div>

                {/* Genre */}
                {first.genres.length > 0 && (
                  <select
                    value={genreFilter ?? ''}
                    onChange={(e) => setGenreFilter(e.target.value || null)}
                    aria-label="Filter by genre"
                    className={selectClass(genreFilter !== null)}
                  >
                    <option value="">All genres</option>
                    {first.genres.map((g) => (
                      <option key={g} value={g}>
                        {g}
                      </option>
                    ))}
                  </select>
                )}

                {/* Decade */}
                {first.decades.length > 0 && (
                  <select
                    value={decadeFilter ?? ''}
                    onChange={(e) => setDecadeFilter(e.target.value ? Number(e.target.value) : null)}
                    aria-label="Filter by decade"
                    className={selectClass(decadeFilter !== null)}
                  >
                    <option value="">All eras</option>
                    {first.decades.map((dec) => (
                      <option key={dec} value={dec}>
                        {dec}s
                      </option>
                    ))}
                  </select>
                )}

                {/* Tag ("What I liked") */}
                {first.tags.length > 0 && (
                  <select
                    value={tagFilter ?? ''}
                    onChange={(e) => setTagFilter(e.target.value || null)}
                    aria-label="Filter by tag"
                    className={selectClass(tagFilter !== null)}
                  >
                    <option value="">All reaction tags</option>
                    {first.tags.map((t) => (
                      <option key={t} value={t}>
                        {TAG_LABELS[t] ?? t}
                      </option>
                    ))}
                  </select>
                )}

                {/* Availability */}
                <select
                  value={watchOnFilter ?? ''}
                  onChange={(e) => setWatchOnFilter(e.target.value || null)}
                  aria-label="Watch availability"
                  className={selectClass(watchOnFilter !== null)}
                >
                  <option value="">Any availability</option>
                  <option value="jellyfin">In Jellyfin</option>
                  <option value="streamable">Streamable (Jellyfin / Subscriptions)</option>
                </select>

                {/* Sort Order */}
                <select
                  value={sortOrder}
                  onChange={(e) => setSortOrder(e.target.value)}
                  aria-label="Sort order"
                  className={selectClass(sortOrder !== 'newest')}
                >
                  <option value="newest">Recently rated</option>
                  <option value="reaction">Loved first</option>
                  <option value="year_desc">Release year: Newest</option>
                  <option value="year_asc">Release year: Oldest</option>
                  <option value="title_asc">Title: A–Z</option>
                </select>
              </div>
            </div>
          )}

          {items.length === 0 ? (
            isFiltered ? (
              <div className="mt-8 rounded-2xl border border-white/10 bg-white/[0.02] p-8 text-center">
                <span className="mx-auto block text-3xl">🔍</span>
                <h3 className="mt-3 text-base font-semibold text-white">No ratings match your filters</h3>
                <p className="mt-1.5 text-sm text-white/50 max-w-md mx-auto">
                  Try clearing some of your search or filter choices to see your rated movies.
                </p>
                <div className="mt-4">
                  <Button variant="ghost" onClick={clearFilters}>
                    Reset all filters
                  </Button>
                </div>
              </div>
            ) : (
              <p className="mt-4 text-sm text-white/50">
                No ratings yet. Import a file above, or search for a film you’ve seen.
              </p>
            )
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
      <PersonDialog
        personId={personDetailId}
        onClose={() => setPersonDetailId(null)}
        onSelectFilm={onSelectFilm}
      />
    </section>
  )
}

function PeopleSection({ onSelectPerson }: { onSelectPerson: (id: number) => void }) {
  const people = usePeopleTaste()

  if (people.isLoading) {
    return (
      <div className="mt-12 flex items-center justify-center py-12">
        <span className="size-6 animate-spin rounded-full border-2 border-accent border-t-transparent" />
      </div>
    )
  }

  if (people.error) {
    return (
      <div className="mt-6">
        <ErrorText>{people.error.message}</ErrorText>
      </div>
    )
  }

  const favorites = people.data?.favorites ?? []
  const top_directors = people.data?.top_directors ?? []
  const top_actors = people.data?.top_actors ?? []

  const hasAny = favorites.length > 0 || top_directors.length > 0 || top_actors.length > 0

  if (!hasAny) {
    return (
      <div className="mt-8 rounded-2xl border border-white/10 bg-white/[0.02] p-8 text-center">
        <span className="mx-auto block text-3xl">🎬</span>
        <h3 className="mt-3 text-base font-semibold text-white">No people data yet</h3>
        <p className="mt-1.5 text-sm text-white/50 max-w-md mx-auto">
          As you rate films, iWantToWatch will discover your favourite directors and lead actors. You can also favorite any person directly from movie details.
        </p>
      </div>
    )
  }

  return (
    <div className="mt-6 space-y-8">
      {favorites.length > 0 && (
        <section>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold tracking-wide uppercase text-accent flex items-center gap-2">
              <HeartIcon filled className="size-4 text-red-400" />
              <span>Favorited People ({favorites.length})</span>
            </h3>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
            {favorites.map((fav) => (
              <button
                key={fav.person_id}
                type="button"
                onClick={() => onSelectPerson(fav.person_id)}
                className="group flex flex-col items-center rounded-xl border border-white/10 bg-white/[0.03] p-3 text-center transition-all hover:border-accent/40 hover:bg-white/[0.06]"
              >
                <div className="size-16 overflow-hidden rounded-full border border-white/10 bg-white/5 mb-2.5 shrink-0">
                  {fav.profile_path ? (
                    <img
                      src={`https://image.tmdb.org/t/p/w185${fav.profile_path}`}
                      alt={fav.name}
                      className="h-full w-full object-cover"
                    />
                  ) : (
                    <div className="flex h-full w-full items-center justify-center text-sm font-bold text-white/30">
                      {fav.name.slice(0, 2).toUpperCase()}
                    </div>
                  )}
                </div>
                <span className="font-semibold text-sm text-white group-hover:text-accent transition-colors line-clamp-1">
                  {fav.name}
                </span>
                {fav.role && <span className="mt-0.5 text-xs text-white/40">{fav.role}</span>}
              </button>
            ))}
          </div>
        </section>
      )}

      {top_directors.length > 0 && (
        <section>
          <div className="flex items-center justify-between mb-3">
            <div>
              <h3 className="text-sm font-semibold tracking-wide uppercase text-white/80">Top Directors</h3>
              <p className="text-xs text-white/40">Learned from your ratings (minimum 2 films)</p>
            </div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {top_directors.map((dir) => (
              <button
                key={dir.id}
                type="button"
                onClick={() => onSelectPerson(dir.id)}
                className="group flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/[0.03] p-3 text-left transition-all hover:border-accent/40 hover:bg-white/[0.06]"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="font-semibold text-sm text-white group-hover:text-accent transition-colors truncate">
                      {dir.name}
                    </span>
                    {dir.is_favorite && <HeartIcon filled className="size-3 text-red-400 shrink-0" />}
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-xs text-white/50">
                    <span>{dir.rated_count} films rated</span>
                  </div>
                </div>
                <div className="shrink-0 flex flex-col items-end gap-1">
                  <span className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-xs font-bold text-emerald-400">
                    ★ {dir.average_rating}
                  </span>
                  {(dir.loved_count > 0 || dir.liked_count > 0) && (
                    <span className="text-[11px] text-white/40">
                      {dir.loved_count > 0 ? `${dir.loved_count} loved` : `${dir.liked_count} liked`}
                    </span>
                  )}
                </div>
              </button>
            ))}
          </div>
        </section>
      )}

      {top_actors.length > 0 && (
        <section>
          <div className="flex items-center justify-between mb-3">
            <div>
              <h3 className="text-sm font-semibold tracking-wide uppercase text-white/80">Top Lead Cast</h3>
              <p className="text-xs text-white/40">Learned from your ratings (minimum 3 films)</p>
            </div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {top_actors.map((actor) => (
              <button
                key={actor.id}
                type="button"
                onClick={() => onSelectPerson(actor.id)}
                className="group flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/[0.03] p-3 text-left transition-all hover:border-accent/40 hover:bg-white/[0.06]"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="font-semibold text-sm text-white group-hover:text-accent transition-colors truncate">
                      {actor.name}
                    </span>
                    {actor.is_favorite && <HeartIcon filled className="size-3 text-red-400 shrink-0" />}
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-xs text-white/50">
                    <span>{actor.rated_count} films rated</span>
                  </div>
                </div>
                <div className="shrink-0 flex flex-col items-end gap-1">
                  <span className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-xs font-bold text-emerald-400">
                    ★ {actor.average_rating}
                  </span>
                  {(actor.loved_count > 0 || actor.liked_count > 0) && (
                    <span className="text-[11px] text-white/40">
                      {actor.loved_count > 0 ? `${actor.loved_count} loved` : `${actor.liked_count} liked`}
                    </span>
                  )}
                </div>
              </button>
            ))}
          </div>
        </section>
      )}
    </div>
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
        {item.note && (
          <p className="mt-1.5 line-clamp-2 text-xs italic text-white/60" title={item.note}>
            "{item.note}"
          </p>
        )}
      </button>
      <WatchBadges availability={where} />
    </li>
  )
}
