import { useMutation } from '@tanstack/react-query'
import { useRef, useState, type FormEvent } from 'react'
import { api, errorMessage, useServerSettings } from './api'
import RateDialog from './RateDialog'
import TitleDialog from './TitleDialog'
import { Button, ErrorText, Poster } from './ui'

const languageName = new Intl.DisplayNames(['en'], { type: 'language' })

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

/** The header's search: find any film and see how well it suits you. */
export default function HeaderSearch() {
  const settings = useServerSettings()
  const dialog = useRef<HTMLDialogElement>(null)
  const [open, setOpen] = useState<number | null>(null)
  const [rating, setRating] = useState<number | null>(null)
  if (!settings.data?.tmdb_configured) return null

  return (
    <>
      <Button variant="ghost" aria-label="Search films" title="Search films" className="px-2!" onClick={() => dialog.current?.showModal()}>
        <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden className="size-5">
          <circle cx="8.5" cy="8.5" r="5.5" />
          <path d="m13 13 4.5 4.5" strokeLinecap="round" />
        </svg>
      </Button>
      <dialog
        ref={dialog}
        onClick={(e) => e.target === dialog.current && dialog.current.close()}
        aria-label="Search films"
        className="m-auto mt-[10vh] w-[min(40rem,calc(100vw-2rem))] rounded-2xl border border-white/10 bg-[#11141b] p-5 text-[#e7e9ee] shadow-2xl backdrop:bg-black/70 sm:p-6"
      >
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="font-semibold">Find a film</h2>
          <Button variant="ghost" className="px-2 py-1" onClick={() => dialog.current?.close()}>
            Close
          </Button>
        </div>
        <p className="mb-3 text-sm text-white/55">See how well any film suits your taste, and where to watch it.</p>
        <FilmSearch
          placeholder="Film title…"
          label="Search for a film"
          prompt="Pick a film to see your match"
          autoFocus
          onPick={(tmdbId) => {
            dialog.current?.close()
            setOpen(tmdbId)
          }}
        />
      </dialog>
      <TitleDialog
        tmdbId={open}
        onClose={() => setOpen(null)}
        onRate={(tmdbId) => {
          setOpen(null)
          setRating(tmdbId)
        }}
      />
      <RateDialog tmdbId={rating} onClose={() => setRating(null)} />
    </>
  )
}
