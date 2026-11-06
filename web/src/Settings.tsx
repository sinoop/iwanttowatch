import type { Me, ServerSettings } from '@iwanttowatch/api-client'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRef, useState, type FormEvent } from 'react'
import { api, errorMessage, useServerSettings } from './api'
import { JellyfinAccount, JellyfinServer } from './JellyfinSettings'
import { StreamingSettings } from './Streaming'
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
      {settings.data?.tmdb_configured && <StreamingSettings me={me} />}
      <BirthYear me={me} />
      {settings.data && <ImdbSection me={me} settings={settings.data} />}
      {settings.data && <LlmSection me={me} settings={settings.data} />}
      <YourData tmdbReady={settings.data?.tmdb_configured === true} />
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
        page, and suggests films from their ratings and what they liked or disliked about them; its picks
        are marked “AI pick” in the feed. Recommendations work without it.
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

/** Download everything the user has told iWantToWatch, or restore it from such a file. */
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
    <section className="mt-6 max-w-xl rounded-xl border border-white/10 p-5">
      <div className="flex items-center justify-between gap-4">
        <h2 className="font-semibold">IMDb ratings</h2>
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

const THIS_YEAR = new Date().getFullYear()

function BirthYear({ me }: { me: Me }) {
  const queryClient = useQueryClient()
  const [year, setYear] = useState(me.birth_year?.toString() ?? '')
  const save = useMutation({
    mutationFn: async (birth_year: number | null) => {
      const { data, error } = await api.PUT('/api/v1/me/profile', { body: { birth_year } })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['me'], data)
      setYear(data.birth_year?.toString() ?? '')
      // The feed shows that it's re-ranking and refreshes itself.
      for (const key of ['feed', 'together']) queryClient.invalidateQueries({ queryKey: [key] })
    },
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate(year ? Number(year) : null)
  }

  return (
    <section className="mt-6 max-w-xl rounded-xl border border-white/10 p-5">
      <h2 className="font-semibold">Birth year</h2>
      <p className="mt-2 text-sm text-white/60">
        Optional. Films from before you were born get a slightly lower match, more the older they are, unless you’ve
        liked films that old. It stays on this server: it isn’t sent to the AI or included in shared taste links.
      </p>
      <form onSubmit={submit} className="mt-4 flex items-end gap-3">
        <div className="w-36">
          <Field
            label="Year"
            type="number"
            inputMode="numeric"
            min={1900}
            max={THIS_YEAR}
            placeholder="e.g. 1990"
            value={year}
            onChange={(e) => setYear(e.target.value)}
          />
        </div>
        <Button type="submit" disabled={save.isPending || year === (me.birth_year?.toString() ?? '')}>
          Save
        </Button>
        {me.birth_year != null && (
          <Button variant="ghost" onClick={() => save.mutate(null)} disabled={save.isPending}>
            Remove
          </Button>
        )}
      </form>
      {save.error && (
        <div className="mt-3">
          <ErrorText>{save.error.message}</ErrorText>
        </div>
      )}
      {save.isSuccess && (
        <p role="status" className="mt-3 text-sm text-emerald-300">
          {save.data.birth_year ? 'Saved.' : 'Removed.'} Your feed will re-rank in a few seconds.
        </p>
      )}
    </section>
  )
}

function YourData({ tmdbReady }: { tmdbReady: boolean }) {
  const queryClient = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const restore = useMutation({
    mutationFn: async (file: File) => {
      const body = new FormData()
      body.append('file', file)
      // openapi-fetch sends FormData as-is, letting the browser set the multipart boundary.
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
    <section className="mt-6 max-w-xl rounded-xl border border-white/10 p-5">
      <h2 className="font-semibold">Your data</h2>
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
        title={tmdbReady ? undefined : 'Add a TMDb API key first'}
      >
        {restore.isPending ? 'Restoring…' : 'Choose export file'}
      </Button>
      {!tmdbReady && <p className="mt-2 text-sm text-amber-300">Restoring needs a TMDb API key on this server.</p>}
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
