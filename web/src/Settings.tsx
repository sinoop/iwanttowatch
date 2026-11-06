import type { Me } from '@iwanttowatch/api-client'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, errorMessage, useServerSettings } from './api'
import { Button, ErrorText, Field } from './ui'

export default function Settings({ me }: { me: Me }) {
  const queryClient = useQueryClient()
  const settings = useServerSettings()
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
  const configured = settings.data?.tmdb_configured

  return (
    <>
      <h1 className="text-2xl font-semibold">Settings</h1>
      <section className="mt-8 max-w-xl rounded-xl border border-white/10 p-5">
        <div className="flex items-center justify-between gap-4">
          <h2 className="font-semibold">TMDb</h2>
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
    </>
  )
}
