import type { Backups, components, ServerSettings } from '@iwanttowatch/api-client'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, copyToClipboard, errorMessage } from '../api'
import { Button, ErrorText } from '../ui'

export function SystemSettings({ settings }: { settings: ServerSettings }) {
  return (
    <div className="space-y-6">
      <div id="logs" className="scroll-mt-6">
        <ServerLogsSection />
      </div>
      <div id="profiling" className="scroll-mt-6">
        <ProfilingSection enabled={settings.profiling_enabled ?? false} />
      </div>
      <div id="compaction" className="scroll-mt-6">
        <DatabaseCompactionSection settings={settings} />
      </div>
      <div id="mcp" className="scroll-mt-6">
        <McpSection enabled={settings.mcp_enabled} />
      </div>
      <div id="backups" className="scroll-mt-6">
        <ServerBackups />
      </div>
    </div>
  )
}

type LogLevel = 'ALL' | 'INFO' | 'WARNING' | 'ERROR'

function ServerLogsSection() {
  const queryClient = useQueryClient()
  const [level, setLevel] = useState<LogLevel>('ALL')
  const [search, setSearch] = useState('')
  const [copied, setCopied] = useState(false)

  const logs = useQuery({
    queryKey: ['server-logs', level, search],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/settings/logs', {
        params: {
          query: {
            level,
            search: search.trim() || undefined,
            limit: 200,
          },
        },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    placeholderData: (previous) => previous,
  })

  const clear = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.DELETE('/api/v1/settings/logs')
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['server-logs', level, search], data)
      queryClient.invalidateQueries({ queryKey: ['server-logs'] })
    },
  })

  const entries = logs.data?.entries ?? []
  const total = logs.data?.total ?? 0
  const error = logs.error ?? clear.error

  const copyLogs = () => {
    const text = entries
      .map((e) => `${e.timestamp} [${e.level}] ${e.logger}: ${e.message}`)
      .join('\n')
    void copyToClipboard(text).then((ok) => {
      if (ok) {
        setCopied(true)
        setTimeout(() => setCopied(false), 2000)
      }
    })
  }

  return (
    <section className="rounded-xl border border-white/10 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <h2 className="font-semibold text-white">Server logs</h2>
          <span className="rounded-full bg-white/10 px-2.5 py-0.5 text-xs text-white/70 tabular-nums">
            {total} {total === 1 ? 'entry' : 'entries'}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {entries.length > 0 && (
            <>
              <Button
                variant="ghost"
                className="border border-white/10 px-2.5 py-1 text-xs"
                onClick={copyLogs}
              >
                {copied ? 'Copied' : 'Copy'}
              </Button>
              <Button
                variant="ghost"
                className="border border-white/10 px-2.5 py-1 text-xs"
                onClick={() => clear.mutate()}
                disabled={clear.isPending}
              >
                Clear
              </Button>
            </>
          )}
          <Button
            variant="ghost"
            className="border border-white/10 px-2.5 py-1 text-xs"
            onClick={() => void logs.refetch()}
            disabled={logs.isFetching}
          >
            {logs.isFetching ? 'Refreshing…' : 'Refresh'}
          </Button>
        </div>
      </div>
      <p className="mt-2 text-sm text-white/60">
        Recent container and application logs (newest first, up to 500 entries kept in memory). Filter by severity or
        search by module and message.
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-2.5">
        <select
          aria-label="Log severity filter"
          value={level}
          onChange={(e) => setLevel(e.target.value as LogLevel)}
          className="rounded-lg border border-white/10 bg-black/30 px-3 py-1.5 text-sm text-white outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-accent/30"
        >
          <option value="ALL">All levels</option>
          <option value="INFO">Info & above</option>
          <option value="WARNING">Warnings & errors</option>
          <option value="ERROR">Errors only</option>
        </select>
        <input
          type="search"
          aria-label="Search server logs"
          placeholder="Filter by message or logger (e.g. jellyfin, feed, PROFILE)…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="min-w-[220px] flex-1 rounded-lg border border-white/10 bg-black/30 px-3 py-1.5 text-sm text-white placeholder:text-white/35 outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-accent/30"
        />
      </div>
      {error && (
        <div className="mt-3">
          <ErrorText>{error.message}</ErrorText>
        </div>
      )}
      {entries.length === 0 ? (
        <p className="mt-4 text-sm text-white/50">No matching log entries.</p>
      ) : (
        <div className="mt-4 max-h-96 overflow-y-auto rounded-lg border border-white/10 bg-black/40 p-3 font-mono text-xs">
          <ul className="divide-y divide-white/5">
            {entries.map((entry) => {
              const badgeColor =
                entry.level === 'ERROR' || entry.level === 'CRITICAL'
                  ? 'bg-red-500/20 text-red-300'
                  : entry.level === 'WARNING'
                    ? 'bg-amber-500/20 text-amber-300'
                    : 'bg-white/10 text-white/65'
              const shortLogger = entry.logger.replace(/^iwanttowatch\./, '')
              return (
                <li key={entry.id} className="py-1.5 first:pt-0 last:pb-0">
                  <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                    <span
                      className="shrink-0 text-white/40 tabular-nums"
                      title={new Date(entry.timestamp).toLocaleString()}
                    >
                      {new Date(entry.timestamp).toLocaleTimeString(undefined, {
                        hour: '2-digit',
                        minute: '2-digit',
                        second: '2-digit',
                      })}
                    </span>
                    <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold ${badgeColor}`}>
                      {entry.level}
                    </span>
                    <span className="shrink-0 text-white/45">{shortLogger}</span>
                    <span className="min-w-0 flex-1 whitespace-pre-wrap break-words text-white/85">
                      {entry.message}
                    </span>
                  </div>
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </section>
  )
}

function ProfilingSection({ enabled }: { enabled: boolean }) {
  const queryClient = useQueryClient()
  const toggle = useMutation({
    mutationFn: async (next: boolean) => {
      const { data, error } = await api.PUT('/api/v1/settings/profiling', {
        body: { enabled: next },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['settings'], data)
    },
  })

  return (
    <section className="rounded-xl border border-white/10 p-5">
      <div className="flex items-center justify-between gap-4">
        <h2 className="font-semibold text-white">Performance profiling</h2>
        <span
          className={`rounded-full px-2.5 py-0.5 text-xs ${
            enabled ? 'bg-emerald-500/15 text-emerald-300' : 'bg-white/10 text-white/60'
          }`}
        >
          {enabled ? 'On' : 'Off'}
        </span>
      </div>
      <p className="mt-2 text-sm text-white/60">
        Log per-step timing breakdowns (<code className="text-white/80">PROFILE GET /api/v1/titles/…</code>) to
        server logs when opening movie details, so you can measure TMDb, IMDb, availability, taste
        scoring, and Radarr latency. Off by default for production.
      </p>
      <div className="mt-4 flex gap-2">
        <Button
          variant={enabled ? 'ghost' : 'primary'}
          onClick={() => toggle.mutate(!enabled)}
          disabled={toggle.isPending}
        >
          {enabled ? 'Turn off' : 'Turn on'}
        </Button>
      </div>
      {toggle.error && (
        <div className="mt-3">
          <ErrorText>{toggle.error.message}</ErrorText>
        </div>
      )}
    </section>
  )
}

function McpSection({ enabled }: { enabled: boolean }) {
  const queryClient = useQueryClient()
  const [key, setKey] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const url = `${window.location.origin}/mcp`
  const create = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST('/api/v1/settings/mcp')
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => {
      setKey(data.key)
      setCopied(false)
      queryClient.invalidateQueries({ queryKey: ['settings'] })
    },
  })
  const remove = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.DELETE('/api/v1/settings/mcp')
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => {
      setKey(null)
      queryClient.setQueryData(['settings'], data)
    },
  })
  const config = key
    ? JSON.stringify({ iwanttowatch: { url, headers: { Authorization: `Bearer ${key}` } } }, null, 2)
    : ''

  return (
    <section className="rounded-xl border border-white/10 p-5">
      <div className="flex items-center justify-between gap-4">
        <h2 className="font-semibold text-white">Debugging (MCP)</h2>
        <span
          className={`rounded-full px-2.5 py-0.5 text-xs ${
            enabled ? 'bg-emerald-500/15 text-emerald-300' : 'bg-white/10 text-white/60'
          }`}
        >
          {enabled ? 'On' : 'Off'}
        </span>
      </div>
      <p className="mt-2 text-sm text-white/60">
        A read-only MCP server at <code className="text-white/80">{url}</code> lets an AI assistant
        look into why a film is or isn’t in someone’s feed: feed builds, scores and reasons,
        availability, and the AI log. It shows everyone’s ratings, so keep the key private. It can’t
        change anything.
      </p>
      {key && (
        <div className="mt-4">
          <p className="text-sm text-white/80">
            Add this to your MCP client’s servers. The key is shown only now.
          </p>
          <pre className="mt-2 overflow-x-auto rounded-lg bg-black/40 p-3 text-xs text-white/80">{config}</pre>
          <Button
            variant="ghost"
            className="mt-2 border border-white/10 px-2 py-1 text-xs"
            onClick={() => {
              void copyToClipboard(config).then((ok) => {
                if (ok) setCopied(true)
              })
            }}
          >
            {copied ? 'Copied' : 'Copy'}
          </Button>
        </div>
      )}
      <div className="mt-4 flex gap-2">
        <Button onClick={() => create.mutate()} disabled={create.isPending}>
          {enabled ? 'Replace key' : 'Create key'}
        </Button>
        {enabled && (
          <Button variant="ghost" onClick={() => remove.mutate()} disabled={remove.isPending}>
            Turn off
          </Button>
        )}
      </div>
      {(create.error ?? remove.error) && (
        <div className="mt-3">
          <ErrorText>{(create.error ?? remove.error)!.message}</ErrorText>
        </div>
      )}
    </section>
  )
}

function ServerBackups() {
  const queryClient = useQueryClient()
  const backups = useQuery({
    queryKey: ['backups'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/backups')
      if (error) throw new Error(errorMessage(error))
      return data
    },
  })
  const create = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST('/api/v1/backups')
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => queryClient.setQueryData<Backups>(['backups'], data),
  })
  const info = backups.data
  const error = backups.error ?? create.error

  return (
    <section className="rounded-xl border border-white/10 p-5">
      <h2 className="font-semibold text-white">Server backups</h2>
      <p className="mt-2 text-sm text-white/60">
        A copy of the whole database, with everyone’s ratings and settings, is saved every day and before each
        upgrade{info ? `; the newest ${info.keep} are kept in ` : '.'}
        {info && <code className="text-white/80">{info.folder}</code>}
        {info && '.'} To keep them on another disk, mount it there or set{' '}
        <code className="text-white/80">IWANTTOWATCH_BACKUP_DIR</code>. To restore, stop iWantToWatch and put a copy in
        place of <code className="text-white/80">iwanttowatch.db</code>.
      </p>
      {info && info.backups.length > 0 && (
        <ul className="mt-4 divide-y divide-white/5 text-sm">
          {info.backups.map((b) => (
            <li key={b.name} className="flex items-center justify-between gap-3 py-2">
              <span className="text-white">
                {new Date(b.created_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}
                {b.name.includes('before-upgrade') && <span className="ml-2 text-xs text-white/45">before upgrade</span>}
              </span>
              <span className="flex items-center gap-3">
                <span className="text-xs text-white/45">{formatSize(b.size)}</span>
                <a
                  href={`/api/v1/backups/${b.name}`}
                  download
                  className="text-accent underline-offset-2 hover:underline"
                >
                  Download
                </a>
              </span>
            </li>
          ))}
        </ul>
      )}
      {info && info.backups.length === 0 && <p className="mt-4 text-sm text-white/50">No backups yet.</p>}
      <Button className="mt-4" onClick={() => create.mutate()} disabled={create.isPending}>
        {create.isPending ? 'Backing up…' : 'Back up now'}
      </Button>
      {error && (
        <div className="mt-3">
          <ErrorText>{error.message}</ErrorText>
        </div>
      )}
    </section>
  )
}

function formatSize(bytes: number) {
  return bytes >= 1_000_000 ? `${(bytes / 1_000_000).toFixed(1)} MB` : `${Math.ceil(bytes / 1000)} kB`
}

function DatabaseCompactionSection({ settings }: { settings: ServerSettings }) {
  const queryClient = useQueryClient()
  const enabled = settings.db_compact_enabled ?? false
  const days = settings.db_compact_days ?? 30
  const [lastResult, setLastResult] = useState<components['schemas']['CompactionResultOut'] | null>(null)

  const update = useMutation({
    mutationFn: async (body: { enabled?: boolean; retention_days?: number }) => {
      const { data, error } = await api.PUT('/api/v1/settings/compaction', { body })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['settings'], data)
    },
  })

  const runNow = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST('/api/v1/settings/compaction/run')
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => {
      setLastResult(data)
      queryClient.invalidateQueries({ queryKey: ['settings'] })
    },
  })

  const error = update.error ?? runNow.error

  return (
    <section className="rounded-xl border border-white/10 p-5">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <h2 className="font-semibold text-white">Database compaction</h2>
          {(settings.db_size_bytes ?? 0) > 0 && (
            <span className="rounded-full bg-white/10 px-2.5 py-0.5 text-xs text-white/70">
              {formatSize(settings.db_size_bytes ?? 0)}
            </span>
          )}
        </div>
        <span
          className={`rounded-full px-2.5 py-0.5 text-xs ${
            enabled ? 'bg-emerald-500/15 text-emerald-300' : 'bg-white/10 text-white/60'
          }`}
        >
          {enabled ? 'Auto daily' : 'Manual only'}
        </span>
      </div>
      <p className="mt-2 text-sm text-white/60">
        Prunes unreferenced cached movie metadata, stale availability rows, and expired API cache entries older than
        the retention window, then runs SQLite <code className="text-white/80">VACUUM</code> to reclaim disk space.
        Movies in any user’s ratings, library, shortlist, or active feeds are never removed.
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <select
          aria-label="Retention window"
          value={days}
          onChange={(e) => update.mutate({ retention_days: Number(e.target.value) })}
          disabled={update.isPending}
          className="rounded-lg border border-white/10 bg-black/30 px-3 py-1.5 text-sm text-white outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-accent/30"
        >
          <option value={7}>Keep 7 days</option>
          <option value={14}>Keep 14 days</option>
          <option value={30}>Keep 30 days (default)</option>
          <option value={90}>Keep 90 days</option>
        </select>
        <Button
          variant={enabled ? 'ghost' : 'primary'}
          onClick={() => update.mutate({ enabled: !enabled })}
          disabled={update.isPending}
        >
          {enabled ? 'Turn off auto-compact' : 'Turn on auto-compact'}
        </Button>
        <Button
          variant="ghost"
          onClick={() => runNow.mutate()}
          disabled={runNow.isPending}
        >
          {runNow.isPending ? 'Compacting…' : 'Compact now'}
        </Button>
      </div>
      {settings.db_compact_last_at && (
        <p className="mt-3 text-xs text-white/45">
          Last compacted{' '}
          {new Date(settings.db_compact_last_at).toLocaleString(undefined, {
            dateStyle: 'medium',
            timeStyle: 'short',
          })}
        </p>
      )}
      {lastResult && (
        <p className="mt-2 text-xs text-emerald-300">
          Removed {lastResult.titles_removed} titles, {lastResult.availability_removed} availability rows,{' '}
          {lastResult.cache_removed} expired cache entries ({formatSize(lastResult.size_before)} →{' '}
          {formatSize(lastResult.size_after)}).
        </p>
      )}
      {error && (
        <div className="mt-3">
          <ErrorText>{error.message}</ErrorText>
        </div>
      )}
    </section>
  )
}
