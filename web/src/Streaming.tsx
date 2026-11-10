import type { Me, PlatformCount, TitleAvailability } from '@iwanttowatch/api-client'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api, errorMessage, type WatchOn } from './api'
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
    mutationFn: async (body: { region: string; subscriptions: number[]; show_rent_buy?: boolean }) => {
      const { data, error } = await api.PUT('/api/v1/me/streaming', {
        body: { show_rent_buy: me.show_rent_buy, ...body },
      })
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
      show_rent_buy: me.show_rent_buy,
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
        Pick the services you pay for. Films on them or on your Jellyfin server count as available to watch.
        Free services show only when you pick one in the feed’s filter. Renting and buying don’t count.
      </p>
      <label className="mt-4 block text-sm">
        <span className="mb-1.5 block font-medium text-white/80">Country</span>
        <select
          value={me.region}
          onChange={(e) =>
            save.mutate({ region: e.target.value, subscriptions: me.subscriptions, show_rent_buy: me.show_rent_buy })
          }
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
      <label className="mt-4 flex cursor-pointer select-none items-center gap-2.5 text-sm">
        <input
          type="checkbox"
          checked={me.show_rent_buy}
          onChange={(e) =>
            save.mutate({
              region: me.region,
              subscriptions: me.subscriptions,
              show_rent_buy: e.target.checked,
            })
          }
          className="size-4 rounded border-white/20 bg-black/40 text-accent focus:ring-accent/40"
        />
        <span className="text-white/80">Show Buy and Rent options in film details</span>
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

export function ProviderLogo({ path, name, className = '' }: { path: string | null; name: string; className?: string }) {
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

const JELLYFIN_PATH =
  'M12 .002C8.826.002-1.398 18.537.16 21.666c1.56 3.129 22.14 3.094 23.682 0S15.177 0 12 0zm7.76 18.949c-1.008 2.028-14.493 2.05-15.514 0C3.224 16.9 9.92 4.755 12.003 4.755c2.081 0 8.77 12.166 7.759 14.196zM12 9.198c-1.054 0-4.446 6.15-3.93 7.189c.518 1.04 7.348 1.027 7.86 0c.511-1.027-2.874-7.19-3.93-7.19z'

/** Official Jellyfin brand logo badge. */
export function JellyfinLogo({ className = 'size-5' }: { className?: string }) {
  return (
    <span
      aria-hidden
      title="Jellyfin"
      className={`inline-flex shrink-0 items-center justify-center rounded-md bg-gradient-to-tr from-[#00a4dc] to-[#aa5cc3] text-white shadow-xs ${className}`}
    >
      <svg viewBox="0 0 24 24" className="size-[70%] fill-current" aria-hidden="true">
        <path d={JELLYFIN_PATH} />
      </svg>
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
        <li title="On Jellyfin">
          <JellyfinLogo className="size-5" />
          <span className="sr-only">On Jellyfin</span>
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

function PlatformStackIcon({
  item,
}: {
  item: { key: string; name: string; logo_path: string | null }
}) {
  if (item.key === 'jellyfin') {
    return (
      <span title="Jellyfin" className="inline-flex rounded-full ring-2 ring-[#0c0e13]">
        <JellyfinLogo className="size-5 rounded-full!" />
      </span>
    )
  }
  return (
    <span title={item.name} className="inline-flex rounded-full ring-2 ring-[#0c0e13]">
      <ProviderLogo path={item.logo_path} name={item.name} className="size-5 rounded-full!" />
    </span>
  )
}

/** Dropdown filter for Jellyfin and each service the listed films can be played on, with stacked icons. */
export function PlatformFilter({
  platforms,
  value,
  onChange,
}: {
  platforms: PlatformCount[]
  value: WatchOn
  onChange: (value: WatchOn) => void
}) {
  const [open, setOpen] = useState(false)
  const [showFree, setShowFree] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onPointerDown = (e: PointerEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setOpen(false)
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('pointerdown', onPointerDown)
    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('pointerdown', onPointerDown)
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  const chosen = Array.isArray(value) ? value : []
  // Free services can run to dozens, so they wait behind a toggle unless one is chosen.
  const free = platforms.filter((p) => p.free)
  const shown = [
    ...platforms.filter((p) => !p.free || showFree || chosen.includes(p.key)),
    // Keep a chosen platform visible even when nothing listed is on it any more.
    ...chosen
      .filter((key) => !platforms.some((p) => p.key === key))
      .map((key) => ({ key, name: key === 'jellyfin' ? 'Jellyfin' : 'Service', logo_path: null, count: 0 })),
  ]
  const toggle = (key: string) => {
    const next = chosen.includes(key) ? chosen.filter((k) => k !== key) : [...chosen, key]
    onChange(next.length ? next : 'anywhere')
  }

  const byKey = new Map(shown.map((p) => [p.key, p]))
  const activePlatforms = Array.isArray(value)
    ? chosen.map((k) => byKey.get(k) ?? { key: k, name: k === 'jellyfin' ? 'Jellyfin' : 'Service', logo_path: null, count: 0 })
    : value === 'anywhere'
      ? platforms.filter((p) => !p.free)
      : []

  const label =
    value === 'anywhere'
      ? 'Available to me'
      : value === 'everything'
        ? 'Include unavailable'
        : activePlatforms.length === 1
          ? activePlatforms[0].name
          : `${activePlatforms.length} platforms`

  return (
    <div ref={menuRef} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Where to watch: ${label}`}
        onClick={() => setOpen((v) => !v)}
        className={`inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm transition-colors focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:outline-none ${
          Array.isArray(value) || value === 'everything'
            ? 'border-accent/60 bg-accent/10 text-accent-strong'
            : 'border-white/10 bg-black/30 text-white/80 hover:border-white/25 hover:text-white'
        }`}
      >
        {activePlatforms.length > 0 && (
          <span className="flex items-center -space-x-1.5" aria-hidden>
            {activePlatforms.slice(0, 4).map((p) => (
              <PlatformStackIcon key={p.key} item={p} />
            ))}
            {activePlatforms.length > 4 && (
              <span className="flex size-5 items-center justify-center rounded-full bg-white/15 text-[10px] font-medium text-white/85 ring-2 ring-[#0c0e13]">
                +{activePlatforms.length - 4}
              </span>
            )}
          </span>
        )}
        <span>{label}</span>
        <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden className="size-4 text-white/50">
          <path
            fillRule="evenodd"
            d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z"
            clipRule="evenodd"
          />
        </svg>
      </button>
      {open && (
        <div
          role="menu"
          aria-label="Where to watch"
          className="absolute left-0 z-20 mt-1.5 max-h-80 w-64 overflow-y-auto rounded-xl border border-white/10 bg-[#151922] p-1.5 shadow-2xl shadow-black/70"
        >
          <button
            type="button"
            role="menuitemradio"
            aria-checked={value === 'anywhere'}
            onClick={() => onChange('anywhere')}
            className={`flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-sm transition-colors ${
              value === 'anywhere' ? 'bg-accent/15 text-accent-strong' : 'text-white/75 hover:bg-white/5 hover:text-white'
            }`}
          >
            <span>Available to me</span>
            {value === 'anywhere' && <span aria-hidden>✓</span>}
          </button>
          <button
            type="button"
            role="menuitemradio"
            aria-checked={value === 'everything'}
            onClick={() => onChange('everything')}
            className={`flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-sm transition-colors ${
              value === 'everything' ? 'bg-accent/15 text-accent-strong' : 'text-white/75 hover:bg-white/5 hover:text-white'
            }`}
          >
            <span>Include unavailable</span>
            {value === 'everything' && <span aria-hidden>✓</span>}
          </button>
          {(shown.length > 0 || free.length > 0) && <div className="my-1 border-t border-white/10" />}
          {shown.map((p) => {
            const on = chosen.includes(p.key)
            return (
              <button
                key={p.key}
                type="button"
                role="menuitemcheckbox"
                aria-checked={on}
                onClick={() => toggle(p.key)}
                className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-sm transition-colors ${
                  on ? 'bg-accent/15 text-accent-strong' : 'text-white/75 hover:bg-white/5 hover:text-white'
                }`}
              >
                {p.key === 'jellyfin' ? (
                  <JellyfinLogo className="size-4 rounded" />
                ) : (
                  <ProviderLogo path={p.logo_path} name={p.name} className="size-4 rounded" />
                )}
                <span className="min-w-0 flex-1 truncate">{p.name}</span>
                <span className="text-xs opacity-60">{p.count}</span>
                {on && <span aria-hidden>✓</span>}
              </button>
            )
          })}
          {free.length > 0 && (
            <button
              type="button"
              onClick={() => setShowFree(!showFree)}
              className="mt-1 w-full rounded-lg border border-dashed border-white/15 px-2.5 py-1.5 text-left text-xs text-white/60 hover:border-white/30 hover:text-white"
            >
              {showFree ? 'Hide free services' : `Show free services (${free.length})`}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
