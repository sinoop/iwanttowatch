import type { ImportJob } from '@iwanttowatch/api-client'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { api, errorMessage, useImports, useServerSettings } from '../api'
import { Button, ErrorText } from '../ui'

const SOURCE_NAMES: Record<string, string> = {
  imdb: 'IMDb',
  letterboxd: 'Letterboxd',
  netflix: 'Netflix',
}

export function ImportExportSettings() {
  const settings = useServerSettings()
  const tmdbReady = settings.data?.tmdb_configured === true

  return (
    <div className="space-y-6">
      <ImportRatingsSection tmdbReady={tmdbReady} />
      <YourDataSection tmdbReady={tmdbReady} />
    </div>
  )
}

function ImportRatingsSection({ tmdbReady }: { tmdbReady: boolean }) {
  const queryClient = useQueryClient()
  const imports = useImports()
  const input = useRef<HTMLInputElement>(null)
  const [error, setError] = useState<string | null>(null)

  const upload = useMutation({
    mutationFn: async (file: File) => {
      const body = new FormData()
      body.append('file', file)
      const { data, error } = await api.POST('/api/v1/imports', {
        body: body as unknown as { file: string },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onMutate: () => setError(null),
    onError: (e) => setError(e.message),
    onSettled: () => {
      if (input.current) input.current.value = ''
      queryClient.invalidateQueries({ queryKey: ['imports'] })
    },
  })

  // When a job finishes or fails, refresh the ratings it added.
  const statuses = (imports.data ?? []).map((job) => `${job.id}:${job.status}`).join()
  useEffect(() => {
    queryClient.invalidateQueries({ queryKey: ['ratings'] })
    queryClient.invalidateQueries({ queryKey: ['persona'] })
  }, [statuses, queryClient])

  return (
    <section className="rounded-xl border border-white/10 p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-prose text-sm text-white/60">
          <h2 className="text-base font-semibold text-white">Import ratings</h2>
          <p className="mt-1">
            Import your ratings and watch history. Importing again later only adds what changed.
          </p>
          <ul className="mt-3 list-disc space-y-1.5 pl-5">
            <li>
              <span className="text-white/80">IMDb:</span> open Your Ratings, then use the menu to
              export <code className="text-white/80">ratings.csv</code>.
            </li>
            <li>
              <span className="text-white/80">Letterboxd:</span> Settings → Data → Export your data,
              then upload the ZIP file as it is.
            </li>
            <li>
              <span className="text-white/80">Netflix:</span> Account → Profiles → your profile →
              Viewing activity, then Download all. It has no ratings, so films only count as
              watched; series are skipped.
            </li>
          </ul>
        </div>
        <div>
          <input
            ref={input}
            type="file"
            accept=".csv,.zip"
            className="hidden"
            aria-label="Export file"
            onChange={(e) => e.target.files?.[0] && upload.mutate(e.target.files[0])}
          />
          <Button
            onClick={() => input.current?.click()}
            disabled={!tmdbReady || upload.isPending}
            title={tmdbReady ? undefined : 'Add a TMDb API key in Integrations first'}
          >
            {upload.isPending ? 'Uploading…' : 'Choose file'}
          </Button>
        </div>
      </div>
      {!tmdbReady && (
        <p className="mt-4 text-sm text-amber-300">
          Add a TMDb API key in{' '}
          <Link to="/settings/integrations" className="underline">
            Integrations
          </Link>{' '}
          before importing.
        </p>
      )}
      {error && (
        <div className="mt-4">
          <ErrorText>{error}</ErrorText>
        </div>
      )}
      {imports.data && imports.data.length > 0 && (
        <ul className="mt-5 divide-y divide-white/5 border-t border-white/10">
          {imports.data.map((job) => (
            <ImportRow key={job.id} job={job} />
          ))}
        </ul>
      )}
    </section>
  )
}

function ImportRow({ job }: { job: ImportJob }) {
  const queryClient = useQueryClient()
  const retry = useMutation({
    mutationFn: () => api.POST('/api/v1/imports/{job_id}/retry', { params: { path: { job_id: job.id } } }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['imports'] }),
  })
  const { pending, matched, review, skipped } = job.counts
  const total = pending + matched + review + skipped
  const done = total - pending
  const active = job.status === 'pending' || job.status === 'running'

  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 py-3 text-sm">
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium text-white">
          {SOURCE_NAMES[job.source] ?? job.source}{' '}
          <span className="font-normal text-white/45">{job.filename}</span>
        </p>
        <p className="text-white/55">
          {active
            ? `Matching ${done} of ${total}…`
            : `${matched} matched · ${review} to review · ${skipped} skipped`}
        </p>
        {active && (
          <div className="mt-2 h-1 w-full max-w-xs overflow-hidden rounded bg-white/10">
            <div
              className="h-full bg-accent transition-[width]"
              style={{ width: `${total ? (done / total) * 100 : 0}%` }}
            />
          </div>
        )}
        {job.status === 'failed' && <p className="mt-1 text-red-300">{job.error}</p>}
      </div>
      {job.status === 'failed' && (
        <Button variant="ghost" onClick={() => retry.mutate()} disabled={retry.isPending}>
          Retry
        </Button>
      )}
      {review > 0 && !active && (
        <Link
          to={`/taste/imports/${job.id}`}
          className="rounded-lg border border-accent/40 px-3 py-1.5 font-medium text-accent hover:bg-accent/10"
        >
          Review {review}
        </Link>
      )}
    </li>
  )
}

function YourDataSection({ tmdbReady }: { tmdbReady: boolean }) {
  const queryClient = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const restore = useMutation({
    mutationFn: async (file: File) => {
      const body = new FormData()
      body.append('file', file)
      const { data, error } = await api.POST('/api/v1/me/import', {
        body: body as unknown as { file: string },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: () => {
      for (const key of ['me', 'ratings', 'feed', 'persona', 'availability']) {
        queryClient.invalidateQueries({ queryKey: [key] })
      }
    },
    onSettled: () => {
      if (input.current) input.current.value = ''
    },
  })
  const done = restore.data

  return (
    <section className="rounded-xl border border-white/10 p-5">
      <h2 className="font-semibold text-white">Your data</h2>
      <p className="mt-2 text-sm text-white/60">
        Download your ratings, watches, favourites, feedback, and streaming settings as one file, to keep a
        backup or move to another iWantToWatch server.
      </p>
      <a
        href="/api/v1/me/export"
        download
        className="mt-4 inline-block rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-black hover:bg-accent-strong focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:outline-none"
      >
        Export my data
      </a>

      <h3 className="mt-6 text-sm font-medium text-white/80">Restore from an export</h3>
      <p className="mt-1 text-sm text-white/60">
        Adds the file’s ratings and feedback to your account; where both have the same film, the file wins. Your
        country, languages, and streaming services are set from the file too.
      </p>
      <input
        ref={input}
        type="file"
        accept=".json,application/json"
        className="hidden"
        aria-label="iWantToWatch export file"
        onChange={(e) => e.target.files?.[0] && restore.mutate(e.target.files[0])}
      />
      <Button
        variant="ghost"
        className="mt-3 border border-white/10"
        onClick={() => input.current?.click()}
        disabled={!tmdbReady || restore.isPending}
        title={tmdbReady ? undefined : 'Add a TMDb API key in Integrations first'}
      >
        {restore.isPending ? 'Restoring…' : 'Choose export file'}
      </Button>
      {!tmdbReady && (
        <p className="mt-2 text-sm text-amber-300">
          Restoring needs a TMDb API key. Add one in{' '}
          <Link to="/settings/integrations" className="underline">
            Integrations
          </Link>
          .
        </p>
      )}
      {restore.error && (
        <div className="mt-3">
          <ErrorText>{restore.error.message}</ErrorText>
        </div>
      )}
      {done && (
        <p role="status" className="mt-3 text-sm text-emerald-300">
          Restored {done.entries} {done.entries === 1 ? 'rating or watch' : 'ratings and watches'} and {done.feedback}{' '}
          {done.feedback === 1 ? 'feedback choice' : 'feedback choices'}
          {done.skipped > 0 ? `; ${done.skipped} TMDb no longer has were skipped` : ''}. Your feed is being rebuilt.
        </p>
      )}
    </section>
  )
}
