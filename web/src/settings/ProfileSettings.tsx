import type { Me, TogetherOptions } from '@iwanttowatch/api-client'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { api, copyToClipboard, errorMessage } from '../api'
import { JellyfinAccount } from '../JellyfinSettings'
import { Button, ErrorText, Field } from '../ui'

const THIS_YEAR = new Date().getFullYear()

export function ProfileSettings({ me }: { me: Me }) {
  return (
    <div className="space-y-6">
      <BirthYear me={me} />
      <JellyfinAccount />
      {!me.is_child && <TastePersonaCard />}
      {!me.is_child && <ShareTasteSection />}
    </div>
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
