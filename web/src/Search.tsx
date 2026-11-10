import { useIsMutating, useMutation } from '@tanstack/react-query'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router'
import { api, errorMessage, useServerSettings } from './api'
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

/** The header's unified search and Ask AI box. */
export default function HeaderSearch() {
  const settings = useServerSettings()
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams, setSearchParams] = useSearchParams()

  const containerRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const askParam = searchParams.get('ask') ?? ''
  const [prevAskParam, setPrevAskParam] = useState(askParam)
  const [mode, setMode] = useState<'search' | 'ask'>(askParam ? 'ask' : 'search')
  const [text, setText] = useState(askParam)
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const [openTitle, setOpenTitle] = useState<number | null>(null)

  if (askParam !== prevAskParam) {
    setPrevAskParam(askParam)
    if (askParam) {
      setText(askParam)
      setMode('ask')
    }
  }

  const llmConfigured = (settings.data?.llm.order.length ?? 0) > 0
  const isAsking = useIsMutating({ mutationKey: ['feed', 'ask'] }) > 0

  const search = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.GET('/api/v1/catalog/search', { params: { query: { query: text.trim() } } })
      if (error) throw new Error(errorMessage(error))
      return data.slice(0, 8)
    },
  })

  // Listen for clear events from Discover
  useEffect(() => {
    const handleClear = () => {
      if (mode === 'ask') {
        setText('')
      }
    }
    window.addEventListener('iwanttowatch:clear-ask-ai', handleClear)
    return () => window.removeEventListener('iwanttowatch:clear-ask-ai', handleClear)
  }, [mode])

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

  if (!settings.data?.tmdb_configured) return null

  const handleSearchSubmit = () => {
    if (!text.trim()) return
    setDropdownOpen(true)
    search.mutate()
  }

  const handleAskSubmit = () => {
    const query = text.trim()
    if (!query || !llmConfigured || isAsking) return
    setDropdownOpen(false)
    search.reset()

    if (location.pathname === '/') {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev)
        next.set('ask', query)
        return next
      })
      window.dispatchEvent(new CustomEvent('iwanttowatch:ask-ai', { detail: { text: query } }))
    } else {
      navigate(`/?ask=${encodeURIComponent(query)}`)
    }
  }

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (mode === 'search') {
      handleSearchSubmit()
    } else {
      handleAskSubmit()
    }
  }

  const handleToggleMode = (targetMode: 'search' | 'ask') => {
    if (mode === targetMode) return
    if (targetMode === 'ask' && !llmConfigured) return
    setMode(targetMode)
    setDropdownOpen(false)
    inputRef.current?.focus()
  }

  return (
    <div ref={containerRef} className="relative order-2 w-full sm:order-none sm:ml-auto sm:w-72 md:w-80 lg:w-96">
      <form onSubmit={handleSubmit} role="search" className="relative flex items-center">
        <label htmlFor="header-search" className="sr-only">
          {mode === 'search' ? 'Search for a film' : 'Ask AI for recommendations'}
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
              ? 'Search films…'
              : `Ask AI: e.g. “${EXAMPLE_REQUEST}”…`
          }
          className="w-full rounded-lg border border-white/10 bg-black/40 py-1.5 pl-9 pr-36 text-sm text-white outline-none placeholder:text-white/35 focus:border-accent focus:ring-2 focus:ring-accent/30"
        />
        <div className="absolute right-1 flex items-center rounded-md border border-white/10 bg-white/[0.04] p-0.5 text-xs">
          <button
            type={mode === 'search' ? 'submit' : 'button'}
            onClick={() => handleToggleMode('search')}
            aria-pressed={mode === 'search'}
            title="Search films"
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
            disabled={!llmConfigured || isAsking}
            onClick={() => handleToggleMode('ask')}
            aria-pressed={mode === 'ask'}
            title={
              !llmConfigured
                ? 'Configure an AI provider in Settings to use Ask AI'
                : isAsking
                  ? 'Asking AI…'
                  : 'Ask AI'
            }
            className={`rounded px-2.5 py-1 font-semibold transition-all disabled:cursor-not-allowed disabled:opacity-40 ${
              mode === 'ask'
                ? 'bg-accent text-black shadow-xs'
                : 'text-white/60 hover:text-white hover:bg-white/10'
            }`}
          >
            {isAsking ? 'Asking…' : 'Ask AI'}
          </button>
        </div>
      </form>

      {dropdownOpen && mode === 'search' && (
        <div className="absolute top-full left-0 right-0 z-50 mt-2 sm:right-auto sm:w-[28rem] md:w-[32rem] rounded-xl border border-white/15 bg-[#11141b] p-3 text-white shadow-2xl shadow-black/80 backdrop-blur-md">
          {search.isPending && (
            <div className="flex items-center gap-2 py-3 text-xs text-white/60">
              <span className="size-3.5 animate-spin rounded-full border-2 border-white/20 border-t-accent" aria-hidden />
              <span>Searching TMDb…</span>
            </div>
          )}
          {search.error && (
            <div className="py-2">
              <ErrorText>{search.error.message}</ErrorText>
            </div>
          )}
          {search.data && !search.isPending && (
            <div>
              <div className="mb-2 flex items-center justify-between gap-3 text-xs">
                <span className="text-white/60">
                  {search.data.length ? 'Pick a film to see your match' : 'No films found.'}
                </span>
                <Button
                  variant="ghost"
                  className="px-2 py-0.5 text-xs text-white/50 hover:text-white"
                  onClick={() => {
                    setDropdownOpen(false)
                    search.reset()
                  }}
                >
                  Close
                </Button>
              </div>
              {search.data.length > 0 && (
                <ul className="flex gap-3 overflow-x-auto pb-1" aria-label="Search results">
                  {search.data.map((c) => (
                    <li key={c.tmdb_id} className="w-24 shrink-0">
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
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}

      <TitleDialog tmdbId={openTitle} onClose={() => setOpenTitle(null)} />
    </div>
  )
}
