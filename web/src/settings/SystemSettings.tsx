import type { Backups, ServerSettings } from '@iwanttowatch/api-client'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, copyToClipboard, errorMessage } from '../api'
import { Button, ErrorText } from '../ui'

export function SystemSettings({ settings }: { settings: ServerSettings }) {
  return (
    <div className="space-y-6">
      <McpSection enabled={settings.mcp_enabled} />
      <ServerBackups />
    </div>
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
