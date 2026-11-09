import type { ServerSettings } from '@iwanttowatch/api-client'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent, type ReactNode } from 'react'
import { api, copyToClipboard, errorMessage } from './api'
import { Button, ErrorText, Field } from './ui'

const relative = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })

function ago(iso: string) {
  const minutes = Math.round((new Date(iso).getTime() - Date.now()) / 60000)
  if (Math.abs(minutes) < 60) return relative.format(minutes, 'minute')
  if (Math.abs(minutes) < 48 * 60) return relative.format(Math.round(minutes / 60), 'hour')
  return relative.format(Math.round(minutes / 1440), 'day')
}

function Badge({ on, children }: { on: boolean; children: ReactNode }) {
  return (
    <span
      className={`rounded-full px-2.5 py-0.5 text-xs ${
        on ? 'bg-emerald-500/15 text-emerald-300' : 'bg-white/10 text-white/60'
      }`}
    >
      {children}
    </span>
  )
}

/** The admin's connection to the household Jellyfin server, with sync status and webhook setup. */
export function JellyfinServer({ settings }: { settings: ServerSettings }) {
  const queryClient = useQueryClient()
  const jellyfin = settings.jellyfin
  const connected = jellyfin.url !== null
  const [url, setUrl] = useState(jellyfin.url ?? '')
  const [apiKey, setApiKey] = useState('')
  const onSaved = (data: ServerSettings | undefined) => {
    queryClient.setQueryData(['settings'], data)
    queryClient.invalidateQueries({ queryKey: ['jellyfin-account'] })
  }
  const save = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.PUT('/api/v1/settings/jellyfin', {
        body: { url, api_key: apiKey || null },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => {
      onSaved(data)
      setApiKey('')
    },
  })
  const disconnect = useMutation({
    mutationFn: async () => (await api.DELETE('/api/v1/settings/jellyfin')).data,
    onSuccess: (data) => {
      onSaved(data)
      setUrl('')
      save.reset()
    },
  })
  const syncNow = useMutation({
    mutationFn: () => api.POST('/api/v1/settings/jellyfin/sync'),
    onSuccess: () => setTimeout(() => queryClient.invalidateQueries({ queryKey: ['settings'] }), 1500),
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate()
  }

  return (
    <section className="mt-6 max-w-xl rounded-xl border border-white/10 p-5">
      <div className="flex items-center justify-between gap-4">
        <h2 className="font-semibold">Jellyfin</h2>
        <Badge on={connected}>{connected ? 'Connected' : 'Not connected'}</Badge>
      </div>
      <p className="mt-2 text-sm text-white/60">
        Reads the movies in your Jellyfin libraries and what each linked person has watched or
        favourited, so you never log a film by hand. Household members can then sign in with their
        Jellyfin username and password. Create an API key in Jellyfin under Dashboard → API Keys.
      </p>
      <form onSubmit={submit} className="mt-4 space-y-3">
        <Field
          label="Server URL"
          placeholder="http://192.168.1.10:8096"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          required
        />
        <Field
          label="API key"
          type="password"
          autoComplete="off"
          placeholder={connected ? 'Saved; leave blank to keep it' : ''}
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          required={!connected}
        />
        {save.error && <ErrorText>{save.error.message}</ErrorText>}
        <div className="flex flex-wrap gap-2">
          <Button type="submit" disabled={save.isPending}>
            {save.isPending ? 'Checking…' : connected ? 'Check and save' : 'Connect'}
          </Button>
          {connected && (
            <Button variant="ghost" type="button" onClick={() => disconnect.mutate()} disabled={disconnect.isPending}>
              Disconnect
            </Button>
          )}
        </div>
      </form>
      {connected && (
        <>
          <SyncStatus settings={settings} onSync={() => syncNow.mutate()} syncing={syncNow.isPending} />
          {jellyfin.webhook_path && <WebhookSetup path={jellyfin.webhook_path} receivedAt={jellyfin.webhook_at} />}
        </>
      )}
    </section>
  )
}

function SyncStatus({ settings, onSync, syncing }: { settings: ServerSettings; onSync: () => void; syncing: boolean }) {
  const j = settings.jellyfin
  return (
    <div className="mt-5 space-y-2 border-t border-white/10 pt-4 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-white/70">
          {j.synced_at ? `Synced ${ago(j.synced_at)}` : 'Not synced yet'} · {j.library_movies} {j.library_movies === 1 ? 'movie' : 'movies'} ·{' '}
          {j.linked_users} {j.linked_users === 1 ? 'person' : 'people'} linked
        </p>
        <Button variant="ghost" onClick={onSync} disabled={syncing}>
          Sync now
        </Button>
      </div>
      {j.error && <ErrorText>{j.error}</ErrorText>}
      {j.unmatched_count > 0 && (
        <details className="text-white/60">
          <summary className="cursor-pointer">
            {j.unmatched_count} {j.unmatched_count === 1 ? 'movie' : 'movies'} couldn’t be matched to TMDb
          </summary>
          <p className="mt-2">
            Give them a TMDb or IMDb ID in Jellyfin (Edit metadata, or a folder name like{' '}
            <code className="text-white/80">Film Name (2015) [tmdbid-12345]</code>), then sync again.
          </p>
          <ul className="mt-2 list-disc pl-5">
            {j.unmatched.map((name) => (
              <li key={name}>{name}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

function WebhookSetup({ path, receivedAt }: { path: string; receivedAt: string | null }) {
  const url = window.location.origin + path
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    if (await copyToClipboard(url)) {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }
  return (
    <details className="mt-4 border-t border-white/10 pt-4 text-sm text-white/60">
      <summary className="cursor-pointer text-white/80">
        Instant updates with the Webhook plugin{' '}
        <span className="text-white/50">
          · {receivedAt ? `last webhook ${ago(receivedAt)}` : 'optional; otherwise changes arrive within 30 minutes'}
        </span>
      </summary>
      <ol className="mt-3 list-decimal space-y-2 pl-5">
        <li>In Jellyfin, open Dashboard → Plugins → Catalog, install Webhook, and restart Jellyfin.</li>
        <li>Open the Webhook plugin and choose Add Generic Destination.</li>
        <li>
          Set Webhook Url to this address. Jellyfin must be able to reach it; if both run in Docker, the host
          name may differ from the one in your browser.
          <div className="mt-2 flex gap-2">
            <code className="min-w-0 flex-1 truncate rounded-lg bg-black/30 px-3 py-2 text-white/80">{url}</code>
            <Button variant="ghost" type="button" onClick={copy}>
              {copied ? 'Copied' : 'Copy'}
            </Button>
          </div>
        </li>
        <li>
          Tick the notification types Item Added, Item Deleted, Playback Stop, and User Data Saved; the item type
          Movies; and Send All Properties. Then save.
        </li>
      </ol>
    </details>
  )
}

/** Each person's link between their iWantToWatch account and their Jellyfin user. */
export function JellyfinAccount() {
  const queryClient = useQueryClient()
  const account = useQuery({
    queryKey: ['jellyfin-account'],
    queryFn: async () => (await api.GET('/api/v1/me/jellyfin')).data ?? null,
    // The first sync runs in the background after linking.
    refetchInterval: (query) => (query.state.data?.linked && query.state.data.library_movies === 0 ? 3000 : false),
  })
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const onChanged = (data: unknown) => {
    queryClient.setQueryData(['jellyfin-account'], data)
    queryClient.invalidateQueries({ queryKey: ['settings'] })
  }
  const link = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.PUT('/api/v1/me/jellyfin', { body: { username, password } })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => {
      onChanged(data)
      setPassword('')
    },
  })
  const unlink = useMutation({
    mutationFn: async () => (await api.DELETE('/api/v1/me/jellyfin')).data,
    onSuccess: onChanged,
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    link.mutate()
  }
  const a = account.data
  if (!a?.server_configured) return null

  return (
    <section className="mt-6 max-w-xl rounded-xl border border-white/10 p-5">
      <div className="flex items-center justify-between gap-4">
        <h2 className="font-semibold">Your Jellyfin account</h2>
        <Badge on={a.linked}>{a.linked ? 'Linked' : 'Not linked'}</Badge>
      </div>
      {a.linked ? (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-sm">
          <p className="text-white/70">
            {a.library_movies === 0
              ? 'Reading your library…'
              : `${a.library_movies} ${a.library_movies === 1 ? 'movie' : 'movies'} in your libraries · ${a.watched} watched · ${a.favorites} ${a.favorites === 1 ? 'favourite' : 'favourites'}`}
          </p>
          {a.can_unlink && (
            <Button variant="ghost" onClick={() => unlink.mutate()} disabled={unlink.isPending}>
              Unlink
            </Button>
          )}
        </div>
      ) : (
        <form onSubmit={submit} className="mt-2 space-y-3">
          <p className="text-sm text-white/60">
            Sign in to Jellyfin once to link it. What you watch and favourite there then syncs automatically;
            iWantToWatch never changes anything in Jellyfin.
          </p>
          <Field
            label="Jellyfin username"
            autoComplete="off"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
          <Field
            label="Jellyfin password"
            type="password"
            autoComplete="off"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {link.error && <ErrorText>{link.error.message}</ErrorText>}
          <Button type="submit" disabled={link.isPending}>
            {link.isPending ? 'Checking…' : 'Link account'}
          </Button>
        </form>
      )}
    </section>
  )
}
