import type { ServerSettings } from '@iwanttowatch/api-client'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent, type ReactNode } from 'react'
import { api, errorMessage } from './api'
import { Button, ErrorText, Field } from './ui'

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

/** Admin settings for connecting to a Radarr instance. */
export function RadarrServer({ settings }: { settings: ServerSettings }) {
  const queryClient = useQueryClient()
  const radarr = settings.radarr
  const connected = radarr.configured && radarr.url !== null
  const [url, setUrl] = useState(radarr.url ?? '')
  const [apiKey, setApiKey] = useState('')
  const [qualityProfileId, setQualityProfileId] = useState<number | undefined>(radarr.quality_profile_id ?? undefined)
  const [rootFolderPath, setRootFolderPath] = useState<string>(radarr.root_folder_path ?? '')
  const [minAvailability, setMinAvailability] = useState<string>(radarr.minimum_availability ?? 'announced')

  const onSaved = (data: ServerSettings | undefined) => {
    queryClient.setQueryData(['settings'], data)
  }

  const save = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.PUT('/api/v1/settings/radarr', {
        body: {
          url,
          api_key: apiKey || null,
          quality_profile_id: qualityProfileId ?? null,
          root_folder_path: rootFolderPath || null,
          minimum_availability: minAvailability,
        },
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
    mutationFn: async () => (await api.DELETE('/api/v1/settings/radarr')).data,
    onSuccess: (data) => {
      onSaved(data)
      setUrl('')
      setQualityProfileId(undefined)
      setRootFolderPath('')
      save.reset()
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate()
  }

  return (
    <section className="mt-6 max-w-xl rounded-xl border border-white/10 p-5">
      <div className="flex items-center justify-between gap-4">
        <h2 className="font-semibold">Radarr</h2>
        <Badge on={connected}>{connected ? 'Connected' : 'Not connected'}</Badge>
      </div>
      <p className="mt-2 text-sm text-white/60">
        Connects to Radarr to check download status and queue unstreamable movie recommendations directly
        to your home media server. Create an API key in Radarr under Settings → General → Security.
      </p>
      <form onSubmit={submit} className="mt-4 space-y-3">
        <Field
          label="Server URL"
          placeholder="http://192.168.1.10:7878"
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

        {connected && (
          <>
            {radarr.profiles && radarr.profiles.length > 0 && (
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-white/80">Quality profile</span>
                <select
                  value={qualityProfileId ?? radarr.profiles[0]?.id ?? ''}
                  onChange={(e) => setQualityProfileId(Number(e.target.value))}
                  className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-accent focus:ring-2 focus:ring-accent/30"
                >
                  {radarr.profiles.map((p) => (
                    <option key={p.id} value={p.id} className="bg-neutral-900 text-white">
                      {p.name}
                    </option>
                  ))}
                </select>
              </label>
            )}

            {radarr.root_folders && radarr.root_folders.length > 0 && (
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-white/80">Root folder</span>
                <select
                  value={rootFolderPath || radarr.root_folders[0]?.path || ''}
                  onChange={(e) => setRootFolderPath(e.target.value)}
                  className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-accent focus:ring-2 focus:ring-accent/30"
                >
                  {radarr.root_folders.map((f) => (
                    <option key={f.id} value={f.path} className="bg-neutral-900 text-white">
                      {f.path}
                    </option>
                  ))}
                </select>
              </label>
            )}

            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-white/80">Minimum availability</span>
              <select
                value={minAvailability}
                onChange={(e) => setMinAvailability(e.target.value)}
                className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-accent focus:ring-2 focus:ring-accent/30"
              >
                <option value="announced" className="bg-neutral-900 text-white">
                  Announced
                </option>
                <option value="inCinemas" className="bg-neutral-900 text-white">
                  In Cinemas
                </option>
                <option value="released" className="bg-neutral-900 text-white">
                  Released
                </option>
              </select>
            </label>
          </>
        )}

        {radarr.error && <ErrorText>Radarr error: {radarr.error}</ErrorText>}
        {save.error && <ErrorText>{save.error.message}</ErrorText>}

        <div className="flex flex-wrap gap-2">
          <Button type="submit" disabled={save.isPending}>
            {save.isPending ? 'Checking…' : connected ? 'Check and save' : 'Connect'}
          </Button>
          {connected && (
            <Button
              type="button"
              variant="ghost"
              onClick={() => disconnect.mutate()}
              disabled={disconnect.isPending}
            >
              {disconnect.isPending ? 'Disconnecting…' : 'Disconnect'}
            </Button>
          )}
        </div>
      </form>
    </section>
  )
}
