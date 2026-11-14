import { useMutation } from '@tanstack/react-query'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, errorMessage, useServerSettings } from './api'
import PersonDialog from './PersonDialog'
import TitleDialog from './TitleDialog'
import { Button, ErrorText, Poster } from './ui'

const languageName = new Intl.DisplayNames(['en'], { type: 'language' })
const EXAMPLE_REQUEST = 'a light Malayalam comedy under 2 hours'

/** Search TMDb for films and pick one. */
export function FilmSearch({
  placeholder,
  label,
  prompt,
  onPick,
  autoFocus = false,
}: {
  placeholder: string
  label: string
  // Shown above the results, such as "Pick the film to rate".
  prompt: string
  onPick: (tmdbId: number) => void
  autoFocus?: boolean
}) {
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
    <div>
      <form onSubmit={submit} className="flex max-w-md gap-2" role="search">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={placeholder}
          aria-label={label}
          autoFocus={autoFocus}
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
              {search.data.length ? prompt : 'No films found.'}
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
                  onClick={() => onPick(c.tmdb_id)}
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

/** The unified search and Ask AI box. */
export default function HeaderSearch({ className = '' }: { className?: string } = {}) {
  const settings = useServerSettings()

  const containerRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const [mode, setMode] = useState<'search' | 'ask'>('search')
  const [text, setText] = useState('')
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const [openTitle, setOpenTitle] = useState<number | null>(null)
  const [openPerson, setOpenPerson] = useState<number | null>(null)

  const llmConfigured = (settings.data?.llm.order.length ?? 0) > 0

  const search = useMutation({
    mutationFn: async (queryText?: string) => {
      const q = (queryText ?? text).trim()
      const { data, error } = await api.GET('/api/v1/catalog/search-all', {
        params: { query: { query: q } },
      })
      if (error) throw new Error(errorMessage(error))
      return {
        movies: data.movies.slice(0, 10),
        people: data.people.slice(0, 6),
      }
    },
  })

  const ask = useMutation({
    mutationFn: async (queryText?: string) => {
      const q = (queryText ?? text).trim()
      const { data, error } = await api.POST('/api/v1/catalog/search-ai', {
        body: { query: q },
      })
      if (error) throw new Error(errorMessage(error))
      return {
        movies: data.movies.slice(0, 10),
        people: data.people.slice(0, 6),
      }
    },
  })

  const active = mode === 'ask' ? ask : search

  // Close search dropdown on click outside or Escape
  useEffect(() => {
    if (!dropdownOpen) return
    const onMouseDown = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setDropdownOpen(false)
      }
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setDropdownOpen(false)
    }
    document.addEventListener('mousedown', onMouseDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onMouseDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [dropdownOpen])

  const handleClose = () => {
    setDropdownOpen(false)
    search.reset()
    ask.reset()
  }

  const handleSearchSubmit = (queryText?: string) => {
    const q = (queryText ?? text).trim()
    if (!q) return
    setMode('search')
    setDropdownOpen(true)
    ask.reset()
    search.mutate(q)
  }

  const handleAskSubmit = (queryText?: string) => {
    const q = (queryText ?? text).trim()
    if (!q || !llmConfigured || ask.isPending) return
    setMode('ask')
    setDropdownOpen(true)
    search.reset()
    ask.mutate(q)
  }


  if (!settings.data?.tmdb_configured) return null

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (mode === 'search') {
      handleSearchSubmit()
    } else {
      handleAskSubmit()
    }
  }

  const handleSearchClick = (e: React.MouseEvent) => {
    e.preventDefault()
    setMode('search')
    if (text.trim()) {
      handleSearchSubmit()
    } else {
      setDropdownOpen(false)
      inputRef.current?.focus()
    }
  }

  const handleAskClick = (e: React.MouseEvent) => {
    e.preventDefault()
    if (!llmConfigured) return
    setMode('ask')
    if (text.trim()) {
      handleAskSubmit()
    } else {
      setDropdownOpen(false)
      inputRef.current?.focus()
    }
  }

  return (
    <div
      ref={containerRef}
      className={`relative ${className || 'order-2 w-full sm:order-none sm:ml-auto sm:w-72 md:w-80 lg:w-96'}`}
    >
      <form onSubmit={handleSubmit} role="search" className="relative flex items-center">
        <label htmlFor="header-search" className="sr-only">
          {mode === 'search' ? 'Search films, actors, or directors' : 'Ask AI for recommendations'}
        </label>
        <span className="pointer-events-none absolute left-2.5 flex items-center text-white/40">
          {mode === 'search' ? (
            <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true" className="size-4">
              <circle cx="8.5" cy="8.5" r="5.5" />
              <path d="m13 13 4.5 4.5" strokeLinecap="round" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" className="size-4 text-accent">
              <path d="M12 2L14.4 9.6L22 12L14.4 14.4L12 22L9.6 14.4L2 12L9.6 9.6L12 2Z" />
            </svg>
          )}
        </span>
        <input
          ref={inputRef}
          id="header-search"
          type="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={
            mode === 'search'
              ? 'Search films, actors…'
              : `Ask AI: e.g. “${EXAMPLE_REQUEST}”…`
          }
          className="w-full rounded-lg border border-white/10 bg-black/40 py-1.5 pl-9 pr-36 text-sm text-white outline-none placeholder:text-white/35 focus:border-accent focus:ring-2 focus:ring-accent/30"
        />
        <div className="absolute right-1 flex items-center rounded-md border border-white/10 bg-white/[0.04] p-0.5 text-xs">
          <button
            type={mode === 'search' ? 'submit' : 'button'}
            onClick={handleSearchClick}
            aria-pressed={mode === 'search'}
            title="Search films and actors"
            className={`rounded px-2.5 py-1 font-semibold transition-all ${
              mode === 'search'
                ? 'bg-accent text-black shadow-xs'
                : 'text-white/60 hover:text-white hover:bg-white/10'
            }`}
          >
            {search.isPending ? 'Searching…' : 'Search'}
          </button>
          <button
            type={mode === 'ask' ? 'submit' : 'button'}
            disabled={!llmConfigured || ask.isPending}
            onClick={handleAskClick}
            aria-pressed={mode === 'ask'}
            title={
              !llmConfigured
                ? 'Configure an AI provider in Settings to use Ask AI'
                : ask.isPending
                  ? 'Asking AI…'
                  : 'Ask AI'
            }
            className={`rounded px-2.5 py-1 font-semibold transition-all disabled:cursor-not-allowed disabled:opacity-40 ${
              mode === 'ask'
                ? 'bg-accent text-black shadow-xs'
                : 'text-white/60 hover:text-white hover:bg-white/10'
            }`}
          >
            {ask.isPending ? 'Asking…' : 'Ask AI'}
          </button>
        </div>
      </form>

      {dropdownOpen && (
        <div
          className={`absolute top-full left-0 z-50 mt-2 rounded-xl border border-white/15 bg-[#11141b] p-3 text-white shadow-2xl shadow-black/80 backdrop-blur-md ${
            className ? 'right-0' : 'right-0 sm:right-auto sm:w-[28rem] md:w-[32rem]'
          }`}
        >
          {active.isPending && (
            <div className="flex items-center gap-2 py-3 text-xs text-white/60">
              <span className="size-3.5 animate-spin rounded-full border-2 border-white/20 border-t-accent" aria-hidden />
              <span>
                {mode === 'ask' ? 'Asking AI to find movies & people…' : 'Searching TMDb…'}
              </span>
            </div>
          )}
          {active.error && (
            <div className="py-2">
              <ErrorText>{active.error.message}</ErrorText>
            </div>
          )}
          {active.data && !active.isPending && (() => {
            const hasPeople = active.data.people.length > 0
            const hasMovies = active.data.movies.length > 0
            const hasResults = hasPeople || hasMovies

            return (
              <div>
                <div className="mb-2.5 flex items-center justify-between gap-3 text-xs">
                  <span className="text-white/60 flex items-center gap-1.5 min-w-0">
                    {mode === 'ask' ? (
                      hasResults ? (
                        <>
                          <span className="inline-flex shrink-0 items-center gap-1 rounded bg-accent/15 px-1.5 py-0.5 text-[11px] font-medium text-accent">
                            <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" className="size-3">
                              <path d="M12 2L14.4 9.6L22 12L14.4 14.4L12 22L9.6 14.4L2 12L9.6 9.6L12 2Z" />
                            </svg>
                            AI picks
                          </span>
                          <span className="truncate">for “{text.trim()}”</span>
                        </>
                      ) : (
                        'No films or people found by the AI.'
                      )
                    ) : hasResults ? (
                      hasPeople && hasMovies
                        ? 'Pick a person or film to view details'
                        : hasPeople
                          ? 'Pick a person to view filmography'
                          : 'Pick a film to see your match'
                    ) : (
                      'No films or people found.'
                    )}
                  </span>
                  <Button
                    variant="ghost"
                    className="shrink-0 px-2 py-0.5 text-xs text-white/50 hover:text-white"
                    onClick={handleClose}
                  >
                    Close
                  </Button>
                </div>

                {hasPeople && (
                  <div className="mb-3">
                    <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-white/50">
                      Actors &amp; Crew
                    </div>
                    <ul className="flex gap-3 overflow-x-auto pb-1" aria-label="People search results">
                      {active.data.people.map((p) => (
                        <li key={p.id} className="w-24 shrink-0">
                          <button
                            type="button"
                            onClick={() => {
                              setDropdownOpen(false)
                              setOpenPerson(p.id)
                            }}
                            className="group w-full rounded-lg text-center focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:outline-none"
                          >
                            <div className="mx-auto size-14 overflow-hidden rounded-full border border-white/10 bg-white/5 transition group-hover:ring-2 group-hover:ring-accent">
                              {p.profile_path ? (
                                <img
                                  src={`https://image.tmdb.org/t/p/w185${p.profile_path}`}
                                  alt={p.name}
                                  className="h-full w-full object-cover"
                                />
                              ) : (
                                <div className="flex h-full w-full items-center justify-center text-xs font-semibold text-white/30">
                                  {p.name.slice(0, 2).toUpperCase()}
                                </div>
                              )}
                            </div>
                            <p className="mt-1.5 truncate text-xs font-medium text-white group-hover:text-accent">
                              {p.name}
                            </p>
                            <p className="line-clamp-2 text-[10px] text-white/45">
                              {p.why || (p.known_for_department === 'Acting'
                                ? 'Actor'
                                : p.known_for_department === 'Directing'
                                  ? 'Director'
                                  : p.known_for_department || 'Artist')}
                            </p>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {hasMovies && (
                  <div>
                    {hasPeople && (
                      <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-white/50">
                        Films
                      </div>
                    )}
                    <ul className="flex gap-3 overflow-x-auto pb-1" aria-label="Movie search results">
                      {active.data.movies.map((c) => (
                        <li key={c.tmdb_id} className="w-28 shrink-0">
                          <button
                            type="button"
                            onClick={() => {
                              setDropdownOpen(false)
                              setOpenTitle(c.tmdb_id)
                            }}
                            className="group w-full rounded-lg text-left focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:outline-none"
                          >
                            <Poster path={c.poster_path} title={c.title} className="group-hover:ring-2 group-hover:ring-accent" />
                            <p className="mt-1 truncate text-xs font-medium">{c.title}</p>
                            <p className="truncate text-xs text-white/45">
                              {[c.year, languageName.of(c.original_language)].filter(Boolean).join(' · ')}
                            </p>
                            {c.why && (
                              <p className="mt-0.5 line-clamp-2 text-[10px] leading-tight text-accent/80 italic">
                                {c.why}
                              </p>
                            )}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )
          })()}
        </div>
      )}

      <TitleDialog tmdbId={openTitle} onClose={() => setOpenTitle(null)} />
      <PersonDialog
        personId={openPerson}
        onClose={() => setOpenPerson(null)}
        onSelectFilm={(tmdbId) => {
          setOpenPerson(null)
          setOpenTitle(tmdbId)
        }}
      />
    </div>
  )
}
