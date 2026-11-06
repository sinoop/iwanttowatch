import type { GroupItem, GuestProfile, Me, TogetherOptions } from '@iwanttowatch/api-client'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent, type ReactNode } from 'react'
import { Link } from 'react-router'
import { api, errorMessage, facts } from './api'
import RateDialog from './RateDialog'
import { WatchBadges } from './Streaming'
import TitleDialog, { Chips, MatchBadge } from './TitleDialog'
import { Button, ErrorText, Field, Poster } from './ui'

const chip = (selected: boolean) =>
  `inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm transition-colors focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:outline-none ${
    selected
      ? 'border-accent bg-accent/15 text-accent-strong'
      : 'border-white/10 text-white/65 hover:border-white/25 hover:text-white'
  }`

export default function Together({ me }: { me: Me }) {
  const options = useQuery({
    queryKey: ['together', 'options'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/together')
      if (error) throw new Error(errorMessage(error))
      return data
    },
  })
  // Who's watching, as "user:1" / "guest:3"; everyone at home until changed.
  const [chosen, setChosen] = useState<Set<string> | null>(null)
  const [availableOnly, setAvailableOnly] = useState(true)
  const [open, setOpen] = useState<number | null>(null)
  const [rating, setRating] = useState<number | null>(null)

  const household = options.data?.household ?? []
  const guests = options.data?.guests ?? []
  const everyoneHome = new Set(household.map((p) => `user:${p.id}`))
  const selected = chosen ?? everyoneHome
  const users = household.filter((p) => selected.has(`user:${p.id}`)).map((p) => p.id)
  const guestIds = guests.filter((g) => selected.has(`guest:${g.id}`)).map((g) => g.id)
  const toggle = (key: string) => {
    const next = new Set(selected)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    setChosen(next)
  }
  const wholeHousehold = household.length > 0 && household.every((p) => selected.has(`user:${p.id}`))

  const picks = useQuery({
    queryKey: ['together', 'picks', users, guestIds, availableOnly],
    enabled: options.isSuccess && users.length + guestIds.length > 0,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/together/picks', {
        params: { query: { users, guests: guestIds, available_only: availableOnly } },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    placeholderData: (previous) => previous,
  })

  return (
    <>
      <h1 className="text-2xl font-semibold">Watch together</h1>
      <p className="mt-1 max-w-prose text-white/60">
        Pick who’s watching. iWantToWatch looks for films none of you has seen that everyone is likely to enjoy,
        on your Jellyfin server or your streaming services.
      </p>

      <section className="mt-6" aria-label="Who's watching">
        <h2 className="text-sm font-medium text-white/80">Who’s watching</h2>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {household.length > 1 && (
            <button
              type="button"
              aria-pressed={wholeHousehold}
              onClick={() => {
                const next = new Set(selected)
                for (const key of everyoneHome) {
                  if (wholeHousehold) next.delete(key)
                  else next.add(key)
                }
                setChosen(next)
              }}
              className={chip(wholeHousehold)}
            >
              Household
            </button>
          )}
          {household.map((p) => (
            <button
              key={p.id}
              type="button"
              aria-pressed={selected.has(`user:${p.id}`)}
              onClick={() => toggle(`user:${p.id}`)}
              className={chip(selected.has(`user:${p.id}`))}
            >
              {p.id === me.id ? `${p.name} (you)` : p.name}
            </button>
          ))}
          {guests.map((g) => (
            <GuestChip key={g.id} guest={g} selected={selected.has(`guest:${g.id}`)} onToggle={() => toggle(`guest:${g.id}`)} />
          ))}
          <AddFriend onAdded={(g) => setChosen(new Set([...selected, `guest:${g.id}`]))} />
        </div>
      </section>

      <label className="mt-5 flex w-fit cursor-pointer items-center gap-2 text-sm">
        <button
          type="button"
          role="switch"
          aria-checked={availableOnly}
          onClick={() => setAvailableOnly(!availableOnly)}
          className={`relative h-5 w-9 rounded-full transition-colors focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:outline-none ${
            availableOnly ? 'bg-accent' : 'bg-white/20'
          }`}
        >
          <span
            className={`absolute top-0.5 left-0.5 size-4 rounded-full bg-white transition-transform ${
              availableOnly ? 'translate-x-4' : ''
            }`}
          />
        </button>
        Available to watch
      </label>

      {(options.error || picks.error) && (
        <div className="mt-6">
          <ErrorText>{(options.error ?? picks.error)?.message}</ErrorText>
        </div>
      )}
      {users.length + guestIds.length === 0 ? (
        <Empty>Pick at least one person.</Empty>
      ) : picks.isPending ? (
        <p className="mt-6 text-sm text-white/50">Finding films for everyone…</p>
      ) : picks.data?.items.length === 0 ? (
        <Empty>
          No picks yet. Each person’s films come from their{' '}
          <Link to="/" className="text-accent underline-offset-2 hover:underline">
            Discover
          </Link>{' '}
          feed, so it needs to be built first
          {availableOnly ? ', and the films must be on your Jellyfin server or services' : ''}.
        </Empty>
      ) : (
        <ul className="mt-6 grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-3 lg:grid-cols-4" aria-label="Group picks">
          {picks.data?.items.map((item) => (
            <GroupCard key={item.tmdb_id} item={item} onOpen={() => setOpen(item.tmdb_id)} />
          ))}
        </ul>
      )}

      {options.data && <ShareTaste share={options.data.share} />}

      <TitleDialog
        tmdbId={open}
        onClose={() => setOpen(null)}
        onRate={(id) => {
          setOpen(null)
          setRating(id)
        }}
      />
      <RateDialog tmdbId={rating} onClose={() => setRating(null)} />
    </>
  )
}

function Empty({ children }: { children: ReactNode }) {
  return <div className="mt-6 rounded-xl border border-dashed border-white/15 p-6 text-sm text-white/60">{children}</div>
}

function GroupCard({ item, onOpen }: { item: GroupItem; onOpen: () => void }) {
  return (
    <li className="flex flex-col">
      <button
        type="button"
        onClick={onOpen}
        className="group relative block rounded-lg text-left focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:outline-none"
        aria-label={`${item.title}, ${item.match}% for the group`}
      >
        <Poster path={item.poster_path} title={item.title} className="transition-shadow group-hover:ring-2 group-hover:ring-accent" />
        <MatchBadge match={item.match} className="absolute top-2 left-2 shadow-lg shadow-black/50" />
      </button>
      <h2 className="mt-2 text-sm leading-snug font-medium">{item.title}</h2>
      <p className="text-xs text-white/50">{facts(item).join(' · ')}</p>
      <WatchBadges availability={item.availability} />
      <ul className="mt-2 flex flex-wrap gap-1" aria-label="Match for each person">
        {item.matches.map((m) => (
          <li
            key={m.key}
            className={`rounded px-1.5 py-0.5 text-[11px] leading-4 ${
              m.match >= 60 ? 'bg-white/8 text-white/75' : 'bg-red-500/15 text-red-200'
            }`}
          >
            {m.name} {m.match}%
          </li>
        ))}
      </ul>
      <Chips genres={item.genres.slice(0, 3 - item.moods.length)} moods={item.moods} className="mt-2" />
      {item.reasons[0] && <p className="mt-1.5 line-clamp-2 text-xs text-white/50">{item.reasons[0]}</p>}
    </li>
  )
}

function GuestChip({ guest, selected, onToggle }: { guest: GuestProfile; selected: boolean; onToggle: () => void }) {
  const queryClient = useQueryClient()
  const remove = useMutation({
    mutationFn: () => api.DELETE('/api/v1/guests/{guest_id}', { params: { path: { guest_id: guest.id } } }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['together'] }),
  })
  return (
    <span className="inline-flex items-center">
      <button
        type="button"
        aria-pressed={selected}
        onClick={onToggle}
        title={guest.error ? `Last refresh failed: ${guest.error}` : `Friend, ${guest.ratings} ratings shared`}
        className={`${chip(selected)} rounded-r-none border-r-0`}
      >
        {guest.name}
        <span className="text-xs opacity-60">friend</span>
      </button>
      <button
        type="button"
        aria-label={`Remove ${guest.name}`}
        onClick={() => remove.mutate()}
        disabled={remove.isPending}
        className={`${chip(selected)} rounded-l-none px-2`}
      >
        ×
      </button>
    </span>
  )
}

function AddFriend({ onAdded }: { onAdded: (guest: GuestProfile) => void }) {
  const queryClient = useQueryClient()
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [link, setLink] = useState('')
  const add = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST('/api/v1/guests', { body: { name, link: link.trim() } })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (guest) => {
      queryClient.setQueryData<TogetherOptions>(['together', 'options'], (old) =>
        old && { ...old, guests: [...old.guests, guest] },
      )
      onAdded(guest)
      setAdding(false)
      setName('')
      setLink('')
    },
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    add.mutate()
  }
  if (!adding) {
    return (
      <button type="button" onClick={() => setAdding(true)} className={`${chip(false)} border-dashed`}>
        + Add a friend
      </button>
    )
  }
  return (
    <form onSubmit={submit} className="mt-2 w-full max-w-xl space-y-3 rounded-xl border border-white/10 p-4">
      <p className="text-sm text-white/60">
        Ask a friend on another iWantToWatch server for their share link (Watch together → Share your taste).
      </p>
      <Field label="Name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={64} />
      <Field
        label="Share link"
        value={link}
        onChange={(e) => setLink(e.target.value)}
        required
        placeholder="https://…/api/v1/shared/…"
      />
      {add.error && <ErrorText>{add.error.message}</ErrorText>}
      <div className="flex gap-2">
        <Button type="submit" disabled={add.isPending}>
          {add.isPending ? 'Adding…' : 'Add friend'}
        </Button>
        <Button type="button" variant="ghost" onClick={() => setAdding(false)}>
          Cancel
        </Button>
      </div>
    </form>
  )
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
    <section className="mt-12 max-w-xl rounded-xl border border-white/10 p-5">
      <h2 className="font-semibold">Share your taste</h2>
      <p className="mt-2 text-sm text-white/60">
        Friends on other iWantToWatch servers can add you to their group picks with this link. It shares only which
        films you’ve seen and how much you liked them, not your name or account. Revoke it any time.
      </p>
      {link ? (
        <>
          <div className="mt-4 flex gap-2">
            <input
              readOnly
              value={link}
              aria-label="Your share link"
              onFocus={(e) => e.target.select()}
              className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-white/80 outline-none focus:border-accent"
            />
            <Button
              onClick={() => {
                void navigator.clipboard?.writeText(link)
                setCopied(true)
              }}
            >
              {copied ? 'Copied' : 'Copy'}
            </Button>
          </div>
          <div className="mt-2 flex gap-2">
            <Button variant="ghost" className="px-2" onClick={() => create.mutate()} disabled={create.isPending}>
              New link
            </Button>
            <Button variant="ghost" className="px-2" onClick={() => revoke.mutate()} disabled={revoke.isPending}>
              Revoke
            </Button>
          </div>
        </>
      ) : (
        <Button className="mt-4" onClick={() => create.mutate()} disabled={create.isPending}>
          Create share link
        </Button>
      )}
    </section>
  )
}
