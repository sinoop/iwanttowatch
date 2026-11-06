import type { Me, TitleAvailability } from '@iwanttowatch/api-client'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, errorMessage } from './api'
import { Button, ErrorText } from './ui'

const LOGO_BASE = 'https://image.tmdb.org/t/p/w92'
const SHOWN_AT_FIRST = 18

export function JustWatchCredit({ className = '' }: { className?: string }) {
  return (
    <span className={className}>
      Streaming availability data from{' '}
      <a href="https://www.justwatch.com" target="_blank" rel="noreferrer" className="underline-offset-2 hover:underline">
        JustWatch
      </a>
      .
    </span>
  )
}

/** Each person's region and the streaming services they pay for. */
export function StreamingSettings({ me }: { me: Me }) {
  const queryClient = useQueryClient()
  const [showAll, setShowAll] = useState(false)
  const [filter, setFilter] = useState('')
  const regions = useQuery({
    queryKey: ['streaming-regions'],
    queryFn: async () => (await api.GET('/api/v1/streaming/regions')).data ?? [],
    staleTime: Infinity,
  })
  const providers = useQuery({
    queryKey: ['streaming-providers', me.region],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/streaming/providers', { params: { query: { region: me.region } } })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    staleTime: Infinity,
  })
  const save = useMutation({
    mutationFn: async (body: { region: string; subscriptions: number[] }) => {
      const { data, error } = await api.PUT('/api/v1/me/streaming', { body })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    // Show the change at once; the server's answer replaces it.
    onMutate: (body) => queryClient.setQueryData(['me'], { ...me, ...body }),
    onSuccess: (data) => queryClient.setQueryData(['me'], data),
    onError: () => queryClient.setQueryData(['me'], me),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['availability'] }),
  })
  const toggle = (id: number) =>
    save.mutate({
      region: me.region,
      subscriptions: me.subscriptions.includes(id)
        ? me.subscriptions.filter((s) => s !== id)
        : [...me.subscriptions, id],
    })

  const all = providers.data ?? []
  const query = filter.trim().toLowerCase()
  const shown = showAll
    ? all.filter((p) => p.name.toLowerCase().includes(query))
    : all.filter((p, i) => i < SHOWN_AT_FIRST || me.subscriptions.includes(p.provider_id))

  return (
    <section className="mt-6 max-w-xl rounded-xl border border-white/10 p-5">
      <div className="flex items-center justify-between gap-4">
        <h2 className="font-semibold">Your streaming services</h2>
        <span className="rounded-full bg-white/10 px-2.5 py-0.5 text-xs text-white/60">
          {me.subscriptions.length} selected
        </span>
      </div>
      <p className="mt-2 text-sm text-white/60">
        Pick the services you pay for. Films on them, on your Jellyfin server, or free to stream count as
        available to watch. Renting and buying don’t.
      </p>
      <label className="mt-4 block text-sm">
        <span className="mb-1.5 block font-medium text-white/80">Country</span>
        <select
          value={me.region}
          onChange={(e) => save.mutate({ region: e.target.value, subscriptions: me.subscriptions })}
          className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 outline-none focus:border-accent focus:ring-2 focus:ring-accent/30"
        >
          {!regions.data?.some((r) => r.code === me.region) && <option value={me.region}>{me.region}</option>}
          {regions.data?.map((r) => (
            <option key={r.code} value={r.code}>
              {r.name}
            </option>
          ))}
        </select>
      </label>
      {save.error && (
        <div className="mt-3">
          <ErrorText>{save.error.message}</ErrorText>
        </div>
      )}
      {providers.error && (
        <div className="mt-3">
          <ErrorText>{providers.error.message}</ErrorText>
        </div>
      )}
      {showAll && (
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Find a service…"
          aria-label="Find a streaming service"
          className="mt-4 w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm outline-none placeholder:text-white/35 focus:border-accent focus:ring-2 focus:ring-accent/30"
        />
      )}
      <ul className="mt-4 flex flex-wrap gap-2" aria-label="Streaming services">
        {shown.map((p) => {
          const on = me.subscriptions.includes(p.provider_id)
          return (
            <li key={p.provider_id}>
              <button
                type="button"
                aria-pressed={on}
                onClick={() => toggle(p.provider_id)}
                className={`flex items-center gap-2 rounded-full border py-1 pr-3 pl-1 text-sm transition-colors focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:outline-none ${
                  on
                    ? 'border-accent bg-accent/15 text-accent-strong'
                    : 'border-white/10 text-white/65 hover:border-white/25 hover:text-white'
                }`}
              >
                <ProviderLogo path={p.logo_path} name={p.name} className="size-6" />
                {p.name}
              </button>
            </li>
          )
        })}
      </ul>
      {all.length > SHOWN_AT_FIRST && (
        <Button variant="ghost" className="mt-3 px-2" onClick={() => setShowAll(!showAll)}>
          {showAll ? 'Show fewer' : `Show all ${all.length}`}
        </Button>
      )}
      <JustWatchCredit className="mt-4 block text-xs text-white/40" />
    </section>
  )
}

function ProviderLogo({ path, name, className = '' }: { path: string | null; name: string; className?: string }) {
  const [failed, setFailed] = useState(false)
  return path && !failed ? (
    <img
      src={LOGO_BASE + path}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
      className={`shrink-0 rounded-md ${className}`}
    />
  ) : (
    <span
      aria-hidden
      className={`flex shrink-0 items-center justify-center rounded-md bg-white/15 text-[10px] font-semibold text-white/80 ${className}`}
    >
      {name.slice(0, 1)}
    </span>
  )
}

/** "On Jellyfin" and the logos of services the user can play a title on. */
export function WatchBadges({ availability }: { availability: TitleAvailability | undefined }) {
  if (!availability || (!availability.on_jellyfin && availability.offers.length === 0)) return null
  const checked =
    availability.stale && availability.checked_at
      ? ` (last checked ${new Date(availability.checked_at).toLocaleDateString()})`
      : ''
  return (
    <ul className="mt-1.5 flex flex-wrap items-center gap-1" aria-label="Where to watch">
      {availability.on_jellyfin && (
        <li className="rounded bg-violet-500/20 px-1.5 py-0.5 text-[11px] leading-4 font-medium text-violet-200">
          Jellyfin
        </li>
      )}
      {availability.offers.map((offer) => (
        <li key={offer.provider_id} title={`On ${offer.name}${offer.kind === 'flatrate' ? '' : ' (free)'}${checked}`}>
          <ProviderLogo
            path={offer.logo_path}
            name={offer.name}
            className={`size-5 ${availability.stale ? 'opacity-50' : ''}`}
          />
          <span className="sr-only">On {offer.name}</span>
        </li>
      ))}
    </ul>
  )
}
