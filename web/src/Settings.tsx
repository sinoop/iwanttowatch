import type { Backups, ChildProfile, InviteOut, Me, ServerSettings } from '@iwanttowatch/api-client'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState, type FormEvent } from 'react'
import { api, copyToClipboard, errorMessage, useServerSettings } from './api'
import { JellyfinAccount, JellyfinServer } from './JellyfinSettings'
import { RadarrServer } from './RadarrSettings'
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
      {me.is_admin && <Household />}
      {settings.data && me.is_admin && <JellyfinServer settings={settings.data} />}
      <JellyfinAccount />
      {settings.data && me.is_admin && <RadarrServer settings={settings.data} />}
      {settings.data?.tmdb_configured && <StreamingSettings me={me} />}
      <BirthYear me={me} />
      <ChildProfiles me={me} />
      {settings.data && <ImdbSection me={me} settings={settings.data} />}
      {settings.data && <LlmSection me={me} settings={settings.data} />}
      {settings.data && me.is_admin && <LlmActivity />}
      {settings.data && me.is_admin && <McpSection enabled={settings.data.mcp_enabled} />}
      {me.is_admin && <ServerBackups />}
      <YourData tmdbReady={settings.data?.tmdb_configured === true} />
    </>
  )
}

type Provider = ServerSettings['llm']['order'][number]

const PROVIDER_LABELS: Record<Provider, string> = { ollama: 'Ollama (local)', gemini: 'Gemini (Google)' }
const ORDINALS = ['1st', '2nd']

function LlmSection({ me, settings }: { me: Me; settings: ServerSettings }) {
  const queryClient = useQueryClient()
  const llm = settings.llm
  const modelOf = (p: Provider) => (p === 'ollama' ? llm.ollama_model : llm.gemini_model) ?? ''
  const [provider, setProvider] = useState<Provider>(
    (['gemini', 'ollama'] as const).find((p) => !llm.order.includes(p)) ?? llm.order[0],
  )
  const [ollamaUrl, setOllamaUrl] = useState(llm.ollama_url ?? '')
  const [model, setModel] = useState(modelOf(provider))
  const [geminiKey, setGeminiKey] = useState('')
  const saved = (data: ServerSettings) => {
    queryClient.setQueryData(['settings'], data)
    queryClient.invalidateQueries({ queryKey: ['persona'] })
  }
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
      saved(data)
      setGeminiKey('')
    },
  })
  const change = useMutation({
    mutationFn: async (action: { order: Provider[] } | { remove: Provider }) => {
      const { data, error } =
        'order' in action
          ? await api.PUT('/api/v1/settings/llm/order', { body: { order: action.order } })
          : await api.DELETE('/api/v1/settings/llm/{provider}', { params: { path: { provider: action.remove } } })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: saved,
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate()
  }
  const choose = (value: Provider) => {
    setProvider(value)
    // Each provider keeps its own model.
    setModel(modelOf(value))
    save.reset()
  }
  const inUse = llm.order.includes(provider)

  return (
    <section className="mt-6 max-w-xl rounded-xl border border-white/10 p-5">
      <div className="flex items-center justify-between gap-4">
        <h2 className="font-semibold">AI writing</h2>
        <span
          className={`rounded-full px-2.5 py-0.5 text-xs ${
            llm.order.length > 0 ? 'bg-emerald-500/15 text-emerald-300' : 'bg-white/10 text-white/60'
          }`}
        >
          {llm.order.length === 0 ? 'Off' : llm.order.map((p) => PROVIDER_LABELS[p].split(' ')[0]).join(' → ')}
        </span>
      </div>
      <p className="mt-2 text-sm text-white/60">
        Optional. An LLM sums up each user’s taste on their My taste page, reviews the top of each feed with what
        they liked or disliked about films, suggests a few films of its own, picks mood tags, and answers “Why
        this?”. Recommendations work without it.
      </p>
      {me.is_admin ? (
        <>
          {llm.order.length > 0 && (
            <div className="mt-4">
              <h3 className="text-sm font-medium text-white/80">Order</h3>
              <ol className="mt-2 space-y-2">
                {llm.order.map((p, n) => (
                  <li key={p} className="flex items-center gap-3 rounded-lg border border-white/10 px-3 py-2 text-sm">
                    <span className="w-8 text-xs text-white/45">{ORDINALS[n]}</span>
                    <span className="flex-1">
                      {PROVIDER_LABELS[p]} <span className="text-white/45">· {modelOf(p) || llm.default_gemini_model}</span>
                    </span>
                    {llm.order.length > 1 && (
                      <button
                        type="button"
                        aria-label={n === 0 ? `Ask ${PROVIDER_LABELS[p]} second` : `Ask ${PROVIDER_LABELS[p]} first`}
                        title={n === 0 ? 'Move down' : 'Move up'}
                        disabled={change.isPending}
                        onClick={() => change.mutate({ order: [...llm.order].reverse() })}
                        className="rounded px-2 py-0.5 text-white/60 hover:bg-white/10 hover:text-white disabled:opacity-40"
                      >
                        {n === 0 ? '↓' : '↑'}
                      </button>
                    )}
                    <button
                      type="button"
                      disabled={change.isPending}
                      onClick={() => change.mutate({ remove: p })}
                      className="rounded px-2 py-0.5 text-xs text-white/60 hover:bg-white/10 hover:text-white disabled:opacity-40"
                    >
                      Turn off
                    </button>
                  </li>
                ))}
              </ol>
              <p className="mt-2 text-xs text-white/45">
                {llm.order.length > 1
                  ? 'The first is always asked first. If it fails, for example at Gemini’s free daily limit or with Ollama switched off, the second answers.'
                  : 'Set up the other provider too and it answers whenever this one fails.'}
              </p>
              {change.error && <ErrorText>{change.error.message}</ErrorText>}
            </div>
          )}
          <form onSubmit={submit} className="mt-5 space-y-4">
            <h3 className="text-sm font-medium text-white/80">Set up a provider</h3>
            <div role="radiogroup" aria-label="LLM provider" className="flex flex-wrap gap-2">
              {(['ollama', 'gemini'] as const).map((p) => (
                <button
                  key={p}
                  type="button"
                  role="radio"
                  aria-checked={provider === p}
                  onClick={() => choose(p)}
                  className={`rounded-full border px-3 py-1 text-sm transition-colors focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:outline-none ${
                    provider === p
                      ? 'border-accent bg-accent/15 text-accent-strong'
                      : 'border-white/10 text-white/65 hover:border-white/25 hover:text-white'
                  }`}
                >
                  {PROVIDER_LABELS[p]}
                  {llm.order.includes(p) && <span className="ml-1.5 text-xs opacity-60">in use</span>}
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
            {save.isSuccess && <p className="text-sm text-emerald-300">Test prompt answered; settings saved.</p>}
            <Button type="submit" disabled={save.isPending}>
              {save.isPending ? 'Testing…' : inUse ? 'Test and save' : 'Test and add'}
            </Button>
          </form>
        </>
      ) : (
        <p className="mt-4 text-sm text-white/50">Only an admin can change this.</p>
      )}
    </section>
  )
}

/** Download everything the user has told iWantToWatch, or restore it from such a file. */
const PURPOSES: Record<string, string> = {
  suggestions: 'Feed ideas',
  persona: 'Taste summary',
  themes: 'Themes note',
  moods: 'Mood tags',
  why: 'Why this?',
  ask: 'Ask',
  check: 'Held-out check',
  test: 'Settings test',
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
    <section className="mt-6 max-w-xl rounded-xl border border-white/10 p-5">
      <div className="flex items-center justify-between gap-4">
        <h2 className="font-semibold">Debugging (MCP)</h2>
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

function LlmActivity() {
  const activity = useQuery({
    queryKey: ['llm-calls'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/settings/llm/calls', { params: { query: { limit: 50 } } })
      if (error) throw new Error(errorMessage(error))
      return data
    },
  })
  const data = activity.data

  return (
    <section className="mt-6 max-w-3xl rounded-xl border border-white/10 p-5">
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-semibold">AI activity</h2>
        <Button
          variant="ghost"
          className="border border-white/10 px-2.5 py-1 text-xs"
          onClick={() => activity.refetch()}
          disabled={activity.isFetching}
        >
          Refresh
        </Button>
      </div>
      <p className="mt-2 text-sm text-white/60">
        Every request iWantToWatch sends to the AI, with the exact prompt and reply. The newest 200 are kept.
      </p>
      {activity.error && (
        <div className="mt-3">
          <ErrorText>{activity.error.message}</ErrorText>
        </div>
      )}
      {data && (
        <>
          <p className="mt-4 text-sm" aria-label="AI call counts">
            <span className="font-medium">{data.last_hour}</span>
            <span className="text-white/60"> in the last hour · </span>
            <span className="font-medium">{data.last_day}</span>
            <span className="text-white/60"> in the last day</span>
            {data.failed_last_day > 0 && (
              <span className="text-red-300"> · {data.failed_last_day} failed</span>
            )}
          </p>
          {data.calls.length === 0 ? (
            <p className="mt-3 text-sm text-white/50">No AI calls yet.</p>
          ) : (
            <ul className="mt-3 divide-y divide-white/10 border-y border-white/10">
              {data.calls.map((call) => (
                <li key={call.id}>
                  <details className="group py-2.5 text-sm">
                    <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-3 gap-y-1">
                      <span className="text-white/45 tabular-nums">
                        {new Date(call.created_at).toLocaleString(undefined, {
                          month: 'short',
                          day: 'numeric',
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </span>
                      <span className="font-medium">{PURPOSES[call.purpose] ?? call.purpose}</span>
                      {call.user && <span className="text-white/60">for {call.user}</span>}
                      <span className="text-white/45">{call.model}</span>
                      <span className="text-white/45 tabular-nums">{(call.duration_ms / 1000).toFixed(1)} s</span>
                      <span
                        className={`ml-auto rounded px-1.5 py-0.5 text-xs ${
                          call.error ? 'bg-red-500/15 text-red-300' : 'bg-emerald-500/15 text-emerald-300'
                        }`}
                      >
                        {call.error ? 'Failed' : 'OK'}
                      </span>
                    </summary>
                    <div className="mt-3 space-y-3">
                      <LlmText label="System prompt" text={call.system} />
                      <LlmText label="Prompt" text={call.prompt} />
                      {call.error ? (
                        <LlmText label="Error" text={call.error} />
                      ) : (
                        <LlmText label="Reply" text={call.reply ?? ''} />
                      )}
                    </div>
                  </details>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  )
}

function LlmText({ label, text }: { label: string; text: string }) {
  return (
    <div>
      <p className="mb-1 text-xs font-medium uppercase tracking-wide text-white/45">{label}</p>
      <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-black/30 p-3 font-mono text-xs text-white/80">
        {text}
      </pre>
    </div>
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
            placeholder="e.g. 1985"
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

function Household() {
  const queryClient = useQueryClient()
  const invites = useQuery({
    queryKey: ['invites'],
    queryFn: async () => (await api.GET('/api/v1/invites')).data ?? [],
  })
  const [name, setName] = useState('')
  const create = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST('/api/v1/invites', { body: { name: name.trim() || null } })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: () => {
      setName('')
      queryClient.invalidateQueries({ queryKey: ['invites'] })
    },
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    create.mutate()
  }

  return (
    <section className="mt-6 max-w-xl rounded-xl border border-white/10 p-5">
      <h2 className="font-semibold">Household</h2>
      <p className="mt-2 text-sm text-white/60">
        Invite someone to set up their own account, with their own ratings and picks. Each link
        works once, for a week. People with a Jellyfin account on this server can sign in with it
        instead.
      </p>
      {invites.data && invites.data.length > 0 && (
        <ul className="mt-4 divide-y divide-white/10 border-y border-white/10">
          {invites.data.map((invite) => (
            <InviteRow key={invite.id} invite={invite} />
          ))}
        </ul>
      )}
      <form onSubmit={submit} className="mt-4 flex flex-wrap items-end gap-3">
        <div className="min-w-44 flex-1">
          <Field
            label="Who is it for? (optional)"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={128}
            placeholder="e.g. Asha"
          />
        </div>
        <Button type="submit" disabled={create.isPending}>
          {create.isPending ? 'Creating…' : 'Create invite link'}
        </Button>
      </form>
      {create.error && (
        <div className="mt-3">
          <ErrorText>{create.error.message}</ErrorText>
        </div>
      )}
    </section>
  )
}

function InviteRow({ invite }: { invite: InviteOut }) {
  const queryClient = useQueryClient()
  const [copied, setCopied] = useState(false)
  const link = `${window.location.origin}/invite/${invite.token}`
  const revoke = useMutation({
    mutationFn: async () => {
      await api.DELETE('/api/v1/invites/{invite_id}', { params: { path: { invite_id: invite.id } } })
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['invites'] }),
  })
  const expires = new Date(invite.expires_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })

  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-2 py-3 text-sm">
      <div className="min-w-0 flex-1">
        <p className="font-medium">{invite.name ?? 'Anyone with the link'}</p>
        <p className="truncate text-xs text-white/45" title={link}>
          Until {expires} · {link}
        </p>
      </div>
      <Button
        variant="ghost"
        className="border border-white/10 px-2 py-1 text-xs"
        onClick={() => {
          void copyToClipboard(link).then((ok) => {
            if (ok) setCopied(true)
          })
        }}
      >
        {copied ? 'Link copied' : 'Copy link'}
      </Button>
      <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => revoke.mutate()} disabled={revoke.isPending}>
        Revoke
      </Button>
    </li>
  )
}

const CURRENT_YEAR = new Date().getFullYear()

function ChildProfiles({ me }: { me: Me }) {
  const queryClient = useQueryClient()
  const children = useQuery({
    queryKey: ['children'],
    queryFn: async () => (await api.GET('/api/v1/children')).data ?? [],
  })
  const currentYear = CURRENT_YEAR
  const [name, setName] = useState('')
  const [birthYear, setBirthYear] = useState(String(currentYear - 8))

  const refresh = () => {
    for (const key of ['children', 'together']) queryClient.invalidateQueries({ queryKey: [key] })
  }
  const parsedYear = Number(birthYear)
  const validYear = Number.isInteger(parsedYear) && parsedYear >= 1900 && parsedYear <= currentYear
  const create = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST('/api/v1/children', {
        body: { name: name.trim(), birth_year: parsedYear },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: () => {
      setName('')
      refresh()
    },
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (name.trim() && validYear) create.mutate()
  }

  return (
    <section className="mt-6 max-w-xl rounded-xl border border-white/10 p-5">
      <h2 className="font-semibold">Child profiles</h2>
      <p className="mt-2 text-sm text-white/60">
        Create a household profile for each child with their birth year. Their birth year sets the
        default certificate filter for {me.region} on Discover (and in Watch together groups that
        include them), and any adult in the household can switch to a child profile or assign
        films to them.
      </p>
      {children.data && children.data.length > 0 && (
        <ul className="mt-4 divide-y divide-white/10 border-y border-white/10">
          {children.data.map((child) => (
            <ChildRow key={child.id} child={child} currentYear={currentYear} onChanged={refresh} />
          ))}
        </ul>
      )}
      <form onSubmit={submit} className="mt-4 flex flex-wrap items-end gap-3">
        <div className="min-w-44 flex-1">
          <Field
            label="Child’s name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            maxLength={64}
            placeholder="e.g. Kabir"
          />
        </div>
        <div className="w-32">
          <Field
            label="Birth year"
            type="number"
            min={1900}
            max={currentYear}
            value={birthYear}
            onChange={(e) => setBirthYear(e.target.value)}
            required
          />
        </div>
        <Button type="submit" disabled={create.isPending || !name.trim() || !validYear}>
          {create.isPending ? 'Adding…' : 'Add child'}
        </Button>
      </form>
      {create.error && (
        <div className="mt-3">
          <ErrorText>{create.error.message}</ErrorText>
        </div>
      )}
    </section>
  )
}

function ChildRow({
  child,
  currentYear,
  onChanged,
}: {
  child: ChildProfile
  currentYear: number
  onChanged: () => void
}) {
  const queryClient = useQueryClient()
  const [birthYear, setBirthYear] = useState(String(child.birth_year))
  const update = useMutation({
    mutationFn: async (birth_year: number) => {
      const { data, error } = await api.PUT('/api/v1/children/{child_id}', {
        params: { path: { child_id: child.id } },
        body: { name: child.name, birth_year },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: onChanged,
  })
  const switchTo = useMutation({
    mutationFn: async () =>
      (await api.POST('/api/v1/children/{child_id}/switch', { params: { path: { child_id: child.id } } })).data,
    onSuccess: (next) => {
      if (next) queryClient.setQueryData(['me'], next)
      for (const key of ['feed', 'ratings', 'persona', 'together', 'title']) {
        queryClient.invalidateQueries({ queryKey: [key] })
      }
    },
  })
  const remove = useMutation({
    mutationFn: () => api.DELETE('/api/v1/children/{child_id}', { params: { path: { child_id: child.id } } }),
    onSuccess: onChanged,
  })
  const saveYear = (value: string) => {
    setBirthYear(value)
    const parsed = Number(value)
    if (Number.isInteger(parsed) && parsed >= 1900 && parsed <= currentYear && parsed !== child.birth_year) {
      update.mutate(parsed)
    }
  }

  return (
    <li className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm">
      <div className="flex items-center gap-2">
        <span className="font-medium">{child.name}</span>
        {child.max_certificate && (
          <span className="rounded bg-accent/15 px-1.5 py-0.5 text-xs font-medium text-accent-strong">
            {child.max_certificate}
          </span>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1.5 text-xs text-white/60">
          <span>Born</span>
          <input
            type="number"
            aria-label={`Birth year for ${child.name}`}
            min={1900}
            max={currentYear}
            value={birthYear}
            onChange={(e) => saveYear(e.target.value)}
            disabled={update.isPending}
            className="w-20 rounded-lg border border-white/10 bg-[#11141b] px-2 py-1 text-xs text-white outline-none focus:border-accent"
          />
        </label>
        <Button
          variant="ghost"
          className="border border-white/10 px-2.5 py-1 text-xs"
          onClick={() => switchTo.mutate()}
          disabled={switchTo.isPending}
        >
          Switch
        </Button>
        <Button
          variant="ghost"
          className="px-2.5 py-1 text-xs text-white/60 hover:text-red-300"
          onClick={() => remove.mutate()}
          disabled={remove.isPending}
        >
          Remove
        </Button>
      </div>
    </li>
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
    <section className="mt-6 max-w-xl rounded-xl border border-white/10 p-5">
      <h2 className="font-semibold">Server backups</h2>
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
              <span>
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
