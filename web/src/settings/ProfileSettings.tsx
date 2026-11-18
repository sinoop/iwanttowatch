import type { Me, TogetherOptions } from '@iwanttowatch/api-client'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { api, copyToClipboard, errorMessage } from '../api'
import { JellyfinAccount } from '../JellyfinSettings'
import { Button, ErrorText, Field } from '../ui'

const THIS_YEAR = new Date().getFullYear()
const COMMON_LANGUAGES = [
  'ml',
  'en',
  'hi',
  'ta',
  'te',
  'kn',
  'bn',
  'mr',
  'ko',
  'ja',
  'fr',
  'es',
  'it',
  'de',
  'zh',
  'ar',
  'pt',
  'ru',
]
const languageName = new Intl.DisplayNames(['en'], { type: 'language' })

function displayLanguage(code: string): string {
  try {
    return languageName.of(code) ?? code.toUpperCase()
  } catch {
    return code.toUpperCase()
  }
}

export function ProfileSettings({
  me,
  subsection = 'languages',
}: {
  me: Me
  subsection?: string
}) {
  if (subsection === 'default-feed') {
    return (
      <div className="space-y-6">
        <DefaultContentFilter me={me} />
        <RecentlyAddedDays me={me} />
        <ContinueWatchingPreference me={me} />
      </div>
    )
  }
  if (subsection === 'birth-year') {
    return <BirthYear me={me} />
  }
  if (subsection === 'jellyfin-account') {
    return <JellyfinAccount />
  }
  if (subsection === 'taste-profile' && !me.is_child) {
    return <TastePersonaCard />
  }
  if (subsection === 'share-taste' && !me.is_child) {
    return <ShareTasteSection />
  }
  return <LanguagePreferences me={me} />
}

function LanguagePreferences({ me }: { me: Me }) {
  const queryClient = useQueryClient()
  const [languages, setLanguages] = useState<string[]>(me.languages ?? [])
  const [customCode, setCustomCode] = useState('')
  const [codeError, setCodeError] = useState<string | null>(null)

  const save = useMutation({
    mutationFn: async (nextLanguages: string[]) => {
      const { data, error } = await api.PUT('/api/v1/me/profile', {
        body: { languages: nextLanguages },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['me'], data)
      setLanguages(data.languages ?? [])
      for (const key of ['feed', 'together']) queryClient.invalidateQueries({ queryKey: [key] })
    },
  })

  const dirty = JSON.stringify(languages) !== JSON.stringify(me.languages ?? [])
  const availableQuickAdd = COMMON_LANGUAGES.filter((code) => !languages.includes(code))

  const addLanguage = (code: string) => {
    const normalized = code.trim().toLowerCase()
    if (!/^[a-z]{2,3}$/.test(normalized)) {
      setCodeError('Enter a 2- or 3-letter ISO language code (e.g. ml, en, ja).')
      return
    }
    setCodeError(null)
    if (!languages.includes(normalized)) {
      setLanguages((current) => [...current, normalized])
    }
    setCustomCode('')
  }

  const removeLanguage = (code: string) => {
    setLanguages((current) => current.filter((c) => c !== code))
  }

  const moveLanguage = (index: number, delta: -1 | 1) => {
    setLanguages((current) => {
      const target = index + delta
      if (target < 0 || target >= current.length) return current
      const next = [...current]
      const [item] = next.splice(index, 1)
      next.splice(target, 0, item)
      return next
    })
  }

  const submitCustom = (event: FormEvent) => {
    event.preventDefault()
    addLanguage(customCode)
  }

  return (
    <section className="rounded-xl border border-white/10 p-5">
      <h2 className="font-semibold text-white">Languages</h2>
      <p className="mt-2 text-sm text-white/60">
        Order the languages you watch by preference. These languages are included in your recommendations and in
        “In Theatres” discovery so regional cinema isn’t drowned out by global popularity.
      </p>

      {languages.length > 0 ? (
        <ol className="mt-4 space-y-2" aria-label="Preferred languages">
          {languages.map((code, index) => {
            const label = displayLanguage(code)
            return (
              <li
                key={code}
                className="flex items-center justify-between gap-3 rounded-lg border border-white/10 bg-black/30 px-3 py-2"
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <span className="w-5 text-xs font-medium text-white/40">{index + 1}.</span>
                  <span className="truncate text-sm font-medium text-white">{label}</span>
                  <span className="rounded bg-white/10 px-1.5 py-0.5 font-mono text-xs text-white/60">{code}</span>
                </div>
                <div className="flex items-center gap-1">
                  <Button
                    type="button"
                    variant="ghost"
                    className="px-2 py-1 text-xs"
                    onClick={() => moveLanguage(index, -1)}
                    disabled={index === 0 || save.isPending}
                    aria-label={`Move ${label} up`}
                  >
                    ↑
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    className="px-2 py-1 text-xs"
                    onClick={() => moveLanguage(index, 1)}
                    disabled={index === languages.length - 1 || save.isPending}
                    aria-label={`Move ${label} down`}
                  >
                    ↓
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    className="px-2 py-1 text-xs text-white/60 hover:text-red-300"
                    onClick={() => removeLanguage(code)}
                    disabled={save.isPending}
                    aria-label={`Remove ${label}`}
                  >
                    Remove
                  </Button>
                </div>
              </li>
            )
          })}
        </ol>
      ) : (
        <p className="mt-4 text-sm text-white/50">
          No preferred languages selected yet. Add languages below to include them in your feeds.
        </p>
      )}

      {availableQuickAdd.length > 0 && (
        <div className="mt-4">
          <p className="mb-2 text-xs font-medium text-white/60">Quick add</p>
          <div className="flex flex-wrap gap-2">
            {availableQuickAdd.map((code) => (
              <button
                key={code}
                type="button"
                onClick={() => addLanguage(code)}
                disabled={save.isPending || languages.length >= 20}
                className="rounded-full border border-white/10 px-3 py-1 text-xs text-white/75 transition-colors hover:border-accent/60 hover:text-white disabled:opacity-40"
              >
                + {displayLanguage(code)}
              </button>
            ))}
          </div>
        </div>
      )}

      <form onSubmit={submitCustom} className="mt-4 flex flex-wrap items-end gap-2">
        <div className="w-44">
          <Field
            label="Add by ISO code"
            placeholder="e.g. pa, gu, tr"
            maxLength={3}
            value={customCode}
            onChange={(e) => {
              setCustomCode(e.target.value)
              if (codeError) setCodeError(null)
            }}
          />
        </div>
        <Button type="submit" variant="ghost" disabled={!customCode.trim() || save.isPending || languages.length >= 20}>
          Add
        </Button>
      </form>
      {codeError && (
        <div className="mt-2">
          <ErrorText>{codeError}</ErrorText>
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Button
          type="button"
          onClick={() => save.mutate(languages)}
          disabled={!dirty || save.isPending}
        >
          {save.isPending ? 'Saving…' : 'Save'}
        </Button>
        {dirty && (
          <Button
            type="button"
            variant="ghost"
            onClick={() => setLanguages(me.languages ?? [])}
            disabled={save.isPending}
          >
            Reset
          </Button>
        )}
        {save.isSuccess && !dirty && (
          <span role="status" className="text-sm text-emerald-300">
            Saved. Your feeds will refresh with your updated languages.
          </span>
        )}
      </div>
      {save.error && (
        <div className="mt-3">
          <ErrorText>{save.error.message}</ErrorText>
        </div>
      )}
    </section>
  )
}

function DefaultContentFilter({ me }: { me: Me }) {
  const queryClient = useQueryClient()
  const [contentType, setContentType] = useState(me.default_content_type ?? 'movies')
  const save = useMutation({
    mutationFn: async (default_content_type: string) => {
      const { data, error } = await api.PUT('/api/v1/me/profile', { body: { default_content_type } })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['me'], data)
      setContentType(data.default_content_type ?? 'movies')
      for (const key of ['feed', 'together']) queryClient.invalidateQueries({ queryKey: [key] })
    },
  })

  return (
    <section className="rounded-xl border border-white/10 p-5">
      <h2 className="font-semibold text-white">Default feed content</h2>
      <p className="mt-2 text-sm text-white/60">
        Choose what category Discover displays by default. “Movies only” excludes stand-up comedy specials, concerts,
        making-of featurettes, and short films. You can still switch categories at any time using the Discover filter bar.
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <select
          value={contentType}
          onChange={(e) => {
            const val = e.target.value
            setContentType(val)
            save.mutate(val)
          }}
          disabled={save.isPending}
          className="rounded-lg border border-white/10 bg-black/30 px-3 py-1.5 text-sm text-white outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-accent/30"
        >
          <option value="movies">Movies only (exclude stand-up, concerts, shorts)</option>
          <option value="standup">Stand-up comedy</option>
          <option value="concerts">Concerts &amp; Live</option>
          <option value="all">All content</option>
        </select>
        {save.isPending && <span className="text-xs text-white/50">Saving…</span>}
        {save.isSuccess && <span className="text-xs text-emerald-300">Saved.</span>}
      </div>
      {save.error && (
        <div className="mt-3">
          <ErrorText>{save.error.message}</ErrorText>
        </div>
      )}
    </section>
  )
}

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
      for (const key of ['feed', 'together']) queryClient.invalidateQueries({ queryKey: [key] })
    },
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate(year ? Number(year) : null)
  }

  return (
    <section className="rounded-xl border border-white/10 p-5">
      <h2 className="font-semibold text-white">Birth year</h2>
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

function TastePersonaCard() {
  const queryClient = useQueryClient()
  const persona = useQuery({
    queryKey: ['persona'],
    queryFn: async () => (await api.GET('/api/v1/me/persona')).data ?? null,
    refetchInterval: (query) => (query.state.data?.refreshing ? 2000 : false),
  })
  const write = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST('/api/v1/me/persona')
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => queryClient.setQueryData(['persona'], data),
  })
  const p = persona.data
  if (persona.isPending) {
    return (
      <section className="rounded-xl border border-white/10 p-5 text-sm text-white/60">
        Loading taste profile…
      </section>
    )
  }
  if (!p) return null
  const writing = write.isPending || p.refreshing
  const enough = p.current_ratings >= p.min_ratings
  const newRatings = p.current_ratings - p.based_on_ratings

  if (!p.text && p.refreshing) {
    return (
      <section className="rounded-xl border border-dashed border-white/15 p-5 text-sm text-white/60">
        Summing up your taste…
      </section>
    )
  }

  if (!p.text) {
    return (
      <section className="rounded-xl border border-dashed border-white/15 p-5 text-sm text-white/60">
        <h2 className="mb-2 font-semibold text-white">Taste profile</h2>
        {!p.llm_configured ? (
          <p>
            Connect Ollama or Gemini in{' '}
            <Link to="/settings/ai" className="text-accent underline-offset-2 hover:underline">
              AI &amp; LLM
            </Link>{' '}
            to get a short AI-written summary of your taste.
          </p>
        ) : !enough ? (
          <p>Rate at least {p.min_ratings} movies and iWantToWatch will sum up your taste.</p>
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span>Ready to sum up your taste.</span>
            <Button onClick={() => write.mutate()} disabled={write.isPending}>
              {write.isPending ? 'Writing…' : 'Sum up my taste'}
            </Button>
          </div>
        )}
        {write.error && (
          <div className="mt-3">
            <ErrorText>{write.error.message}</ErrorText>
          </div>
        )}
      </section>
    )
  }

  return (
    <section className="rounded-xl border border-accent/25 bg-gradient-to-br from-accent/10 to-transparent p-5 sm:p-6">
      <div className="flex items-center justify-between gap-4">
        <p className="text-xs font-medium tracking-wide text-accent uppercase">Your taste in brief</p>
        <span className="rounded-full bg-accent/20 px-2.5 py-0.5 text-xs font-medium text-accent-strong">
          AI Summary
        </span>
      </div>
      <p className={`mt-3 max-w-prose text-lg leading-relaxed ${writing ? 'opacity-50' : ''}`}>{p.text}</p>
      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-white/50">
        <span>
          Based on {p.based_on_ratings} ratings
          {newRatings > 0 && ` · ${newRatings} new since`}
        </span>
        {p.llm_configured && (
          <Button variant="ghost" onClick={() => write.mutate()} disabled={writing}>
            {writing ? 'Writing… a local model can take a minute' : 'Write a new one'}
          </Button>
        )}
      </div>
      {write.error && (
        <div className="mt-3">
          <ErrorText>{write.error.message}</ErrorText>
        </div>
      )}
    </section>
  )
}

function ShareTasteSection() {
  const options = useQuery({
    queryKey: ['together', 'options'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/together')
      if (error) throw new Error(errorMessage(error))
      return data
    },
  })
  const share = options.data?.share
  if (!share) return null

  return <ShareTaste share={share} />
}

function ShareTaste({ share }: { share: TogetherOptions['share'] }) {
  const queryClient = useQueryClient()
  const [copied, setCopied] = useState(false)
  const done = () => {
    setCopied(false)
    queryClient.invalidateQueries({ queryKey: ['together', 'options'] })
  }
  const create = useMutation({ mutationFn: () => api.POST('/api/v1/me/share'), onSettled: done })
  const revoke = useMutation({ mutationFn: () => api.DELETE('/api/v1/me/share'), onSettled: done })
  const link = share.token ? `${window.location.origin}/api/v1/shared/${share.token}` : null

  return (
    <section className="rounded-xl border border-white/10 p-5">
      <h2 className="font-semibold text-white">Share your taste</h2>
      <p className="mt-2 text-sm text-white/60">
        Friends on other iWantToWatch servers can add you to their group picks. Both ways share only which films you’ve
        seen and how much you liked them, not your name or account.
      </p>

      <h3 className="mt-5 text-sm font-medium text-white/80">Taste card</h3>
      <p className="mt-1 text-sm text-white/60">
        A small file to send by WhatsApp or email. Works from any home network; send a new one when you’ve rated more.
        Once sent, it can’t be revoked.
      </p>
      <a
        href="/api/v1/me/taste-card"
        download
        className="mt-3 inline-block rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-black hover:bg-accent-strong focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:outline-none"
      >
        Download taste card
      </a>

      <h3 className="mt-6 text-sm font-medium text-white/80">Share link</h3>
      <p className="mt-1 text-sm text-white/60">
        Stays up to date and can be revoked any time, but your friend’s server must be able to reach this one, such as
        through a domain or Tailscale.
      </p>
      {link ? (
        <>
          <div className="mt-3 flex gap-2">
            <input
              readOnly
              value={link}
              aria-label="Your share link"
              onFocus={(e) => e.target.select()}
              className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-white/80 outline-none focus:border-accent"
            />
            <Button
              onClick={() => {
                void copyToClipboard(link).then((ok) => {
                  if (ok) setCopied(true)
                })
              }}
            >
              {copied ? 'Copied' : 'Copy'}
            </Button>
          </div>
          <div className="mt-2 flex gap-2">
            <Button variant="ghost" className="px-2 text-xs" onClick={() => create.mutate()} disabled={create.isPending}>
              New link
            </Button>
            <Button variant="ghost" className="px-2 text-xs text-white/60 hover:text-red-300" onClick={() => revoke.mutate()} disabled={revoke.isPending}>
              Revoke
            </Button>
          </div>
        </>
      ) : (
        <div className="mt-3">
          <Button onClick={() => create.mutate()} disabled={create.isPending}>
            {create.isPending ? 'Creating…' : 'Create share link'}
          </Button>
        </div>
      )}
    </section>
  )
}

function ContinueWatchingPreference({ me }: { me: Me }) {
  const queryClient = useQueryClient()
  const [enabled, setEnabled] = useState(me.show_continue_watching)
  const save = useMutation({
    mutationFn: async (show_continue_watching: boolean) => {
      const { data, error } = await api.PUT('/api/v1/me/profile', { body: { show_continue_watching } })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['me'], data)
      setEnabled(data.show_continue_watching)
      queryClient.invalidateQueries({ queryKey: ['jellyfin', 'in-progress'] })
    },
  })

  return (
    <section className="rounded-xl border border-white/10 p-5">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="font-semibold text-white">Continue Watching shelf</h2>
          <p className="mt-1 text-sm text-white/60">
            Show movies you are currently watching on Jellyfin in a dedicated shelf on the Discover page.
          </p>
        </div>
        <label className="relative inline-flex cursor-pointer items-center shrink-0">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => {
              const val = e.target.checked
              setEnabled(val)
              save.mutate(val)
            }}
            disabled={save.isPending}
            className="peer sr-only"
          />
          <div className="h-6 w-11 rounded-full bg-white/10 peer-checked:bg-accent peer-focus:ring-2 peer-focus:ring-accent/40 after:absolute after:top-0.5 after:left-[2px] after:h-5 after:w-5 after:rounded-full after:bg-white after:transition-all peer-checked:after:translate-x-full peer-checked:after:border-white" />
        </label>
      </div>
      {save.error && (
        <div className="mt-3">
          <ErrorText>{save.error.message}</ErrorText>
        </div>
      )}
    </section>
  )
}

function RecentlyAddedDays({ me }: { me: Me }) {
  const queryClient = useQueryClient()
  const [days, setDays] = useState(me.recently_added_days ?? 7)
  const save = useMutation({
    mutationFn: async (recently_added_days: number) => {
      const { data, error } = await api.PUT('/api/v1/me/profile', { body: { recently_added_days } })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['me'], data)
      setDays(data.recently_added_days ?? 7)
      queryClient.invalidateQueries({ queryKey: ['feed'] })
    },
  })

  return (
    <section className="rounded-xl border border-white/10 p-5">
      <h2 className="font-semibold text-white">Recently added to streaming window</h2>
      <p className="mt-2 text-sm text-white/60">
        How many days back the “Recently added to streaming” filter on Discover looks for new digital releases.
        Refresh that filter on Discover after changing this to rebuild the list.
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <select
          value={days}
          onChange={(e) => {
            const val = Number(e.target.value)
            setDays(val)
            save.mutate(val)
          }}
          disabled={save.isPending}
          className="rounded-lg border border-white/10 bg-black/30 px-3 py-1.5 text-sm text-white outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-accent/30"
        >
          <option value={3}>Past 3 days</option>
          <option value={7}>Past 7 days (default)</option>
          <option value={14}>Past 14 days</option>
          <option value={30}>Past 30 days</option>
        </select>
        {save.isPending && <span className="text-xs text-white/50">Saving…</span>}
        {save.isSuccess && <span className="text-xs text-emerald-300">Saved.</span>}
      </div>
      {save.error && (
        <div className="mt-3">
          <ErrorText>{save.error.message}</ErrorText>
        </div>
      )}
    </section>
  )
}
