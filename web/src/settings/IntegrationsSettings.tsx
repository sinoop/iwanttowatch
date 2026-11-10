import type { Me, ServerSettings } from '@iwanttowatch/api-client'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, errorMessage } from '../api'
import { JellyfinServer } from '../JellyfinSettings'
import { RadarrServer } from '../RadarrSettings'
import { Button, ErrorText, Field } from '../ui'

export function IntegrationsSettings({ me, settings }: { me: Me; settings: ServerSettings }) {
  return (
    <div className="space-y-6">
      <TmdbSection me={me} settings={settings} />
      <JellyfinServer settings={settings} />
      <RadarrServer settings={settings} />
      <ImdbSection me={me} settings={settings} />
    </div>
  )
}

function TmdbSection({ me, settings }: { me: Me; settings: ServerSettings }) {
  const queryClient = useQueryClient()
  const [apiKey, setApiKey] = useState('')
  const save = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.PUT('/api/v1/settings/tmdb', { body: { api_key: apiKey } })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['settings'], data)
      setApiKey('')
    },
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate()
  }
  const configured = settings.tmdb_configured

  return (
    <section className="rounded-xl border border-white/10 p-5">
      <div className="flex items-center justify-between gap-4">
        <h2 className="font-semibold text-white">TMDb</h2>
        <span
          className={`rounded-full px-2.5 py-0.5 text-xs ${
            configured ? 'bg-emerald-500/15 text-emerald-300' : 'bg-white/10 text-white/60'
          }`}
        >
          {configured ? 'Connected' : 'Not connected'}
        </span>
      </div>
      <p className="mt-2 text-sm text-white/60">
        iWantToWatch uses The Movie Database for movie details and to match your imported ratings.
        Create a free account, then copy the API key or the API Read Access Token from{' '}
        <a
          className="text-accent underline-offset-2 hover:underline"
          href="https://www.themoviedb.org/settings/api"
          target="_blank"
          rel="noreferrer"
        >
          themoviedb.org/settings/api
        </a>
        .
      </p>
      {me.is_admin ? (
        <form onSubmit={submit} className="mt-4 space-y-3">
          <Field
            label={configured ? 'Replace API key' : 'API key'}
            type="password"
            autoComplete="off"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            required
            minLength={16}
          />
          {save.error && <ErrorText>{save.error.message}</ErrorText>}
          {save.isSuccess && <p className="text-sm text-emerald-300">Key checked and saved.</p>}
          <Button type="submit" disabled={save.isPending}>
            {save.isPending ? 'Checking…' : 'Check and save'}
          </Button>
        </form>
      ) : (
        <p className="mt-4 text-sm text-white/50">Only an admin can change this.</p>
      )}
    </section>
  )
}

function ImdbSection({ me, settings }: { me: Me; settings: ServerSettings }) {
  const queryClient = useQueryClient()
  const { imdb } = settings
  const save = useMutation({
    mutationFn: async (enabled: boolean) => {
      const { data, error } = await api.PUT('/api/v1/settings/imdb', { body: { enabled } })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['settings'], data)
      for (const key of ['feed', 'together']) queryClient.invalidateQueries({ queryKey: [key] })
    },
  })

  return (
    <section className="rounded-xl border border-white/10 p-5">
      <div className="flex items-center justify-between gap-4">
        <h2 className="font-semibold text-white">IMDb ratings</h2>
        <span
          className={`rounded-full px-2.5 py-0.5 text-xs ${
            imdb.enabled ? 'bg-emerald-500/15 text-emerald-300' : 'bg-white/10 text-white/60'
          }`}
        >
          {imdb.enabled ? 'On' : 'Off'}
        </span>
      </div>
      <p className="mt-2 text-sm text-white/60">
        Judge how good films are by IMDb’s ratings, which have far more votes than TMDb’s, and show them on cards. The
        server downloads IMDb’s free ratings file once a day. IMDb allows this for personal, non-commercial use only.
      </p>
      {imdb.enabled && (
        <p className="mt-2 text-sm text-white/60">
          {imdb.updated_at
            ? `${imdb.rated_films.toLocaleString()} films rated · downloaded ${new Date(imdb.updated_at).toLocaleString()}`
            : 'Downloading with the next feed update…'}
        </p>
      )}
      {imdb.error && <p className="mt-2 text-sm text-amber-300">{imdb.error}</p>}
      {me.is_admin ? (
        <div className="mt-4">
          <Button
            variant={imdb.enabled ? 'ghost' : 'primary'}
            className={imdb.enabled ? 'border border-white/10' : ''}
            onClick={() => save.mutate(!imdb.enabled)}
            disabled={save.isPending}
          >
            {imdb.enabled ? 'Stop using IMDb ratings' : 'Use IMDb ratings'}
          </Button>
          {save.error && (
            <div className="mt-3">
              <ErrorText>{save.error.message}</ErrorText>
            </div>
          )}
        </div>
      ) : (
        <p className="mt-4 text-sm text-white/50">Only an admin can change this.</p>
      )}
    </section>
  )
}
