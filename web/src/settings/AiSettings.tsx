import type { Me, ServerSettings } from '@iwanttowatch/api-client'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, errorMessage } from '../api'
import { Button, ErrorText, Field } from '../ui'

type Provider = ServerSettings['llm']['order'][number]

const PROVIDER_LABELS: Record<Provider, string> = {
  ollama: 'Ollama (local)',
  gemini: 'Gemini (Google)',
  openai: 'OpenAI-compatible',
  claude: 'Claude (Anthropic)',
}
const ORDINALS = ['1st', '2nd', '3rd', '4th']

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

export function AiSettings({ me, settings }: { me: Me; settings: ServerSettings }) {
  return (
    <div className="space-y-6">
      <div id="ai-writing" className="scroll-mt-6">
        <LlmSection me={me} settings={settings} />
      </div>
      <div id="ai-activity" className="scroll-mt-6">
        <LlmActivity />
      </div>
    </div>
  )
}

function LlmSection({ me, settings }: { me: Me; settings: ServerSettings }) {
  const queryClient = useQueryClient()
  const llm = settings.llm
  const modelOf = (p: Provider) =>
    (p === 'ollama'
      ? llm.ollama_model
      : p === 'gemini'
        ? llm.gemini_model
        : p === 'openai'
          ? llm.openai_model
          : llm.claude_model) ?? ''
  const defaultModelOf = (p: Provider) =>
    p === 'gemini'
      ? llm.default_gemini_model
      : p === 'openai'
        ? llm.default_openai_model
        : p === 'claude'
          ? llm.default_claude_model
          : ''
  const [provider, setProvider] = useState<Provider>(
    (['gemini', 'ollama', 'openai', 'claude'] as const).find((p) => !llm.order.includes(p)) ?? llm.order[0],
  )
  const [ollamaUrl, setOllamaUrl] = useState(llm.ollama_url ?? '')
  const [openaiUrl, setOpenaiUrl] = useState(llm.openai_base_url ?? llm.default_openai_url)
  const [model, setModel] = useState(modelOf(provider))
  const [geminiKey, setGeminiKey] = useState('')
  const [openaiKey, setOpenaiKey] = useState('')
  const [claudeKey, setClaudeKey] = useState('')
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
          openai_base_url: provider === 'openai' ? openaiUrl || null : null,
          openai_api_key: provider === 'openai' ? openaiKey || null : null,
          claude_api_key: provider === 'claude' ? claudeKey || null : null,
        },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => {
      saved(data)
      setGeminiKey('')
      setOpenaiKey('')
      setClaudeKey('')
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
    setModel(modelOf(value))
    save.reset()
  }
  const inUse = llm.order.includes(provider)

  return (
    <section className="rounded-xl border border-white/10 p-5">
      <div className="flex items-center justify-between gap-4">
        <h2 className="font-semibold text-white">AI writing</h2>
        <span
          className={`rounded-full px-2.5 py-0.5 text-xs ${
            llm.order.length > 0 ? 'bg-emerald-500/15 text-emerald-300' : 'bg-white/10 text-white/60'
          }`}
        >
          {llm.order.length === 0 ? 'Off' : llm.order.map((p) => PROVIDER_LABELS[p].split(' ')[0]).join(' → ')}
        </span>
      </div>
      <p className="mt-2 text-sm text-white/60">
        Optional. An LLM sums up each user’s taste on their My Profile page, reviews the top of each feed with what
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
                    <span className="flex-1 text-white">
                      {PROVIDER_LABELS[p]} <span className="text-white/45">· {modelOf(p) || defaultModelOf(p)}</span>
                    </span>
                    {llm.order.length > 1 && n > 0 && (
                      <button
                        type="button"
                        aria-label={`Move ${PROVIDER_LABELS[p]} up`}
                        title="Move up"
                        disabled={change.isPending}
                        onClick={() => {
                          const next = [...llm.order]
                          ;[next[n - 1], next[n]] = [next[n], next[n - 1]]
                          change.mutate({ order: next })
                        }}
                        className="rounded px-2 py-0.5 text-white/60 hover:bg-white/10 hover:text-white disabled:opacity-40"
                      >
                        ↑
                      </button>
                    )}
                    {llm.order.length > 1 && n < llm.order.length - 1 && (
                      <button
                        type="button"
                        aria-label={`Move ${PROVIDER_LABELS[p]} down`}
                        title="Move down"
                        disabled={change.isPending}
                        onClick={() => {
                          const next = [...llm.order]
                          ;[next[n], next[n + 1]] = [next[n + 1], next[n]]
                          change.mutate({ order: next })
                        }}
                        className="rounded px-2 py-0.5 text-white/60 hover:bg-white/10 hover:text-white disabled:opacity-40"
                      >
                        ↓
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
              {(['ollama', 'gemini', 'openai', 'claude'] as const).map((p) => (
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
            {provider === 'openai' && (
              <>
                <p className="text-sm text-white/55">
                  Works with OpenAI, Groq (free tier), OpenRouter (free models), Mistral, or a local LM Studio server.
                </p>
                <Field
                  label="Base URL"
                  placeholder={llm.default_openai_url}
                  hint={`Default: ${llm.default_openai_url}. For Groq use https://api.groq.com/openai/v1; for OpenRouter use https://openrouter.ai/api/v1.`}
                  value={openaiUrl}
                  onChange={(e) => setOpenaiUrl(e.target.value)}
                />
                <Field
                  label="API key"
                  type="password"
                  autoComplete="off"
                  placeholder={llm.openai_configured ? 'Saved; leave blank to keep it' : ''}
                  value={openaiKey}
                  onChange={(e) => setOpenaiKey(e.target.value)}
                  required={!llm.openai_configured}
                />
                <Field
                  label="Model"
                  placeholder={llm.default_openai_model}
                  hint={`Leave blank to use ${llm.default_openai_model}.`}
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                />
              </>
            )}
            {provider === 'claude' && (
              <>
                <p className="text-sm text-white/55">
                  Uses Anthropic’s Claude Messages API.
                </p>
                <Field
                  label="Anthropic API key"
                  type="password"
                  autoComplete="off"
                  placeholder={llm.claude_configured ? 'Saved; leave blank to keep it' : ''}
                  hint="Create one at console.anthropic.com."
                  value={claudeKey}
                  onChange={(e) => setClaudeKey(e.target.value)}
                  required={!llm.claude_configured}
                />
                <Field
                  label="Model"
                  placeholder={llm.default_claude_model}
                  hint={`Leave blank to use ${llm.default_claude_model}.`}
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

function LlmActivity() {
  const [page, setPage] = useState(1)
  const activity = useQuery({
    queryKey: ['llm-calls', page],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/settings/llm/calls', {
        params: { query: { page, limit: 10 } },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    placeholderData: (previous) => previous,
  })
  const data = activity.data
  const currentPage = data?.page ?? page
  const totalPages = data?.total_pages ?? 1

  return (
    <section className="rounded-xl border border-white/10 p-5">
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-semibold text-white">AI activity</h2>
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
        Every request iWantToWatch sent to the AI in the last 24 hours, with the exact prompt and reply.
      </p>
      {activity.error && (
        <div className="mt-3">
          <ErrorText>{activity.error.message}</ErrorText>
        </div>
      )}
      {data && (
        <>
          <p className="mt-4 text-sm" aria-label="AI call counts">
            <span className="font-medium text-white">{data.last_hour}</span>
            <span className="text-white/60"> in the last hour · </span>
            <span className="font-medium text-white">{data.last_day}</span>
            <span className="text-white/60"> in the last day</span>
            {data.failed_last_day > 0 && (
              <span className="text-red-300"> · {data.failed_last_day} failed</span>
            )}
          </p>
          {data.calls.length === 0 ? (
            <p className="mt-3 text-sm text-white/50">No AI calls in the last 24 hours.</p>
          ) : (
            <>
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
                        <span className="font-medium text-white">{PURPOSES[call.purpose] ?? call.purpose}</span>
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
              {totalPages > 1 && (
                <div className="mt-4 flex items-center justify-between text-sm">
                  <span className="text-white/60">
                    Page {currentPage} of {totalPages}
                  </span>
                  <div className="flex gap-2">
                    <Button
                      variant="ghost"
                      className="border border-white/10 px-3 py-1 text-xs"
                      onClick={() => setPage(Math.max(1, currentPage - 1))}
                      disabled={currentPage <= 1 || activity.isFetching}
                    >
                      Previous
                    </Button>
                    <Button
                      variant="ghost"
                      className="border border-white/10 px-3 py-1 text-xs"
                      onClick={() => setPage(Math.min(totalPages, currentPage + 1))}
                      disabled={currentPage >= totalPages || activity.isFetching}
                    >
                      Next
                    </Button>
                  </div>
                </div>
              )}
            </>
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
