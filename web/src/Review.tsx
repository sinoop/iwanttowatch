import type { Candidate, ImportRow } from '@iwanttowatch/api-client'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router'
import { api, errorMessage } from './api'
import { Button, ErrorText, Poster } from './ui'

const languageName = new Intl.DisplayNames(['en'], { type: 'language' })

export default function Review() {
  const jobId = Number(useParams().jobId)
  const rows = useQuery({
    queryKey: ['import-rows', jobId],
    queryFn: async () =>
      (await api.GET('/api/v1/imports/{job_id}/rows', { params: { path: { job_id: jobId } } }))
        .data ?? [],
  })

  return (
    <>
      <Link to="/settings/imports" className="text-sm text-white/55 hover:text-white">
        ← Import & Export
      </Link>
      <h1 className="mt-3 text-2xl font-semibold">Review matches</h1>
      <p className="mt-2 max-w-prose text-white/60">
        These rows matched more than one movie, or none. Pick the right one, search for it, or skip
        it.
      </p>
      {rows.data?.length === 0 && (
        <p className="mt-8 text-sm text-emerald-300">All done. Every row is matched or skipped.</p>
      )}
      <ul className="mt-8 space-y-6">
        {rows.data?.map((row) => (
          <ReviewRow key={row.id} jobId={jobId} row={row} />
        ))}
      </ul>
    </>
  )
}

function ReviewRow({ jobId, row }: { jobId: number; row: ImportRow }) {
  const queryClient = useQueryClient()
  const [query, setQuery] = useState(row.title)
  const [results, setResults] = useState<Candidate[] | null>(null)

  const search = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.GET('/api/v1/catalog/search', { params: { query: { query } } })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: setResults,
  })
  const resolve = useMutation({
    mutationFn: async (tmdbId: number | null) => {
      const { error } = await api.POST('/api/v1/imports/{job_id}/rows/{row_id}/resolve', {
        params: { path: { job_id: jobId, row_id: row.id } },
        body: { tmdb_id: tmdbId },
      })
      if (error) throw new Error(errorMessage(error))
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['import-rows', jobId] })
      queryClient.invalidateQueries({ queryKey: ['imports'] })
      queryClient.invalidateQueries({ queryKey: ['ratings'] })
    },
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    search.mutate()
  }
  const candidates = results ?? row.candidates

  return (
    <li className="rounded-xl border border-white/10 p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <p className="font-semibold">
            {row.title} <span className="font-normal text-white/45">{row.year}</span>
          </p>
          <p className="text-sm text-white/55">
            {row.message}
            {row.rating != null && ` · you rated it ${row.rating}`}
          </p>
        </div>
        <Button variant="ghost" onClick={() => resolve.mutate(null)} disabled={resolve.isPending}>
          Skip
        </Button>
      </div>
      {candidates.length > 0 && (
        <ul className="mt-4 grid grid-cols-3 gap-3 sm:grid-cols-5">
          {candidates.map((c) => (
            <li key={c.tmdb_id}>
              <button
                type="button"
                onClick={() => resolve.mutate(c.tmdb_id)}
                disabled={resolve.isPending}
                className="group w-full rounded-lg text-left focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:outline-none"
              >
                <Poster path={c.poster_path} title={c.title} className="group-hover:ring-2 group-hover:ring-accent" />
                <p className="mt-1.5 truncate text-sm font-medium">{c.title}</p>
                <p className="truncate text-xs text-white/45">
                  {[c.year, languageName.of(c.original_language)].filter(Boolean).join(' · ')}
                </p>
              </button>
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={submit} className="mt-4 flex gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search TMDb"
          className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent/30"
        />
        <Button type="submit" variant="ghost" disabled={search.isPending}>
          Search
        </Button>
      </form>
      {results?.length === 0 && <p className="mt-2 text-sm text-white/50">No movies found.</p>}
      {(search.error || resolve.error) && (
        <div className="mt-3">
          <ErrorText>{(search.error ?? resolve.error)?.message}</ErrorText>
        </div>
      )}
    </li>
  )
}
