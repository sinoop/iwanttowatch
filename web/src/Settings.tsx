import type { Me, ServerSettings } from '@iwanttowatch/api-client'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, errorMessage, useServerSettings } from './api'
import { JellyfinAccount, JellyfinServer } from './JellyfinSettings'
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
      {settings.data && me.is_admin && <JellyfinServer settings={settings.data} />}
      <JellyfinAccount />
      {settings.data && <LlmSection me={me} settings={settings.data} />}
    </>
  )
}

const PROVIDERS = [
  { value: 'none', label: 'None' },
  { value: 'ollama', label: 'Ollama (local)' },
  { value: 'gemini', label: 'Gemini (Google)' },
] as const

function LlmSection({ me, settings }: { me: Me; settings: ServerSettings }) {
  const queryClient = useQueryClient()
  const llm = settings.llm
  const [provider, setProvider] = useState(llm.provider)
  const [ollamaUrl, setOllamaUrl] = useState(llm.ollama_url ?? '')
  const [model, setModel] = useState(llm.model ?? '')
  const [geminiKey, setGeminiKey] = useState('')
  const save = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.PUT('/api/v1/settings/llm', {
        body: {
          provider,
          model: model || null,
          ollama_url: provider === 'ollama' ? ollamaUrl : null,
          gemini_api_key: provider === 'gemini' ? geminiKey || null : null,
        },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['settings'], data)
      queryClient.invalidateQueries({ queryKey: ['persona'] })
      setGeminiKey('')
    },
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate()
  }
  const choose = (value: typeof provider) => {
    setProvider(value)
    // Model names don't carry over between providers.
    setModel(value === llm.provider ? (llm.model ?? '') : '')
    save.reset()
  }
  const status = PROVIDERS.find((p) => p.value === llm.provider)!

  return (
    <section className="mt-6 max-w-xl rounded-xl border border-white/10 p-5">
      <div className="flex items-center justify-between gap-4">
        <h2 className="font-semibold">AI writing</h2>
        <span
          className={`rounded-full px-2.5 py-0.5 text-xs ${
            llm.provider !== 'none' ? 'bg-emerald-500/15 text-emerald-300' : 'bg-white/10 text-white/60'
          }`}
        >
          {llm.provider === 'none' ? 'Off' : `${status.label} · ${llm.model}`}
        </span>
      </div>
      <p className="mt-2 text-sm text-white/60">
        Optional. An LLM writes the “if your taste were a person” sketch on each user’s My taste
        page. Recommendations work without it.
      </p>
      {me.is_admin ? (
        <form onSubmit={submit} className="mt-4 space-y-4">
          <div role="radiogroup" aria-label="LLM provider" className="flex flex-wrap gap-2">
            {PROVIDERS.map((p) => (
              <button
                key={p.value}
                type="button"
                role="radio"
                aria-checked={provider === p.value}
                onClick={() => choose(p.value)}
                className={`rounded-full border px-3 py-1 text-sm transition-colors focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:outline-none ${
                  provider === p.value
                    ? 'border-accent bg-accent/15 text-accent-strong'
                    : 'border-white/10 text-white/65 hover:border-white/25 hover:text-white'
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
          {provider === 'ollama' && (
            <>
              <p className="text-sm text-white/55">
                Runs on your own hardware; nothing leaves your network. Install{' '}
                <a className="text-accent underline-offset-2 hover:underline" href="https://ollama.com" target="_blank" rel="noreferrer">
                  Ollama
                </a>{' '}
                and pull a model first, for example <code className="text-white/80">ollama pull llama3.2:3b</code>.
              </p>
              <Field
                label="Ollama URL"
                placeholder="http://192.168.1.10:11434"
                value={ollamaUrl}
                onChange={(e) => setOllamaUrl(e.target.value)}
                required
              />
              <Field
                label="Model"
                placeholder="llama3.2:3b"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                required
              />
            </>
          )}
          {provider === 'gemini' && (
            <>
              <p className="rounded-lg bg-amber-500/10 px-3 py-2 text-sm text-amber-200">
                Gemini sends a summary of each user’s ratings (film titles, genres, languages, and
                favourite filmmakers) to Google. On Google’s free tier, Google may use this data to
                improve its products.
              </p>
              <Field
                label="Gemini API key"
                type="password"
                autoComplete="off"
                placeholder={llm.gemini_configured ? 'Saved; leave blank to keep it' : ''}
                hint="Create one at aistudio.google.com/apikey."
                value={geminiKey}
                onChange={(e) => setGeminiKey(e.target.value)}
                required={!llm.gemini_configured}
              />
              <Field
                label="Model"
                placeholder={llm.default_gemini_model}
                hint={`Leave blank to use ${llm.default_gemini_model}, which follows Google’s current Flash model.`}
                value={model}
                onChange={(e) => setModel(e.target.value)}
              />
            </>
          )}
          {save.error && <ErrorText>{save.error.message}</ErrorText>}
          {save.isSuccess && (
            <p className="text-sm text-emerald-300">
              {provider === 'none' ? 'AI writing is off.' : 'Test prompt answered; settings saved.'}
            </p>
          )}
          <Button type="submit" disabled={save.isPending}>
            {save.isPending ? 'Testing…' : provider === 'none' ? 'Save' : 'Test and save'}
          </Button>
        </form>
      ) : (
        <p className="mt-4 text-sm text-white/50">Only an admin can change this.</p>
      )}
    </section>
  )
}
