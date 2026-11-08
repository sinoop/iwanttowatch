import type { GroupItem, GuestProfile, Me, TogetherOptions, VoteSessionOut } from '@iwanttowatch/api-client'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent, type ReactNode } from 'react'
import { Link } from 'react-router'
import { renderSVG } from 'uqr'
import { api, errorMessage, facts, watchOnQuery, type WatchOn } from './api'
import RateDialog from './RateDialog'
import { PlatformFilter, WatchBadges } from './Streaming'
import TitleDialog, { BookmarkIcon, Chips, MatchBadge } from './TitleDialog'
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
  const [watchOn, setWatchOn] = useState<WatchOn>('anywhere')
  const [shortlistOnly, setShortlistOnly] = useState(false)
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
    queryKey: ['together', 'picks', users, guestIds, watchOn, shortlistOnly],
    enabled: options.isSuccess && users.length + guestIds.length > 0,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/together/picks', {
        params: {
          query: { users, guests: guestIds, ...watchOnQuery(watchOn), shortlist: shortlistOnly || undefined },
        },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    placeholderData: (previous) => previous,
  })
  const queryClient = useQueryClient()
  const shortlist = useMutation({
    mutationFn: async ({ tmdbId, save }: { tmdbId: number; save: boolean }) => {
      const params = { params: { path: { tmdb_id: tmdbId } } }
      const { error } = save
        ? await api.PUT('/api/v1/together/shortlist/{tmdb_id}', params)
        : await api.DELETE('/api/v1/together/shortlist/{tmdb_id}', params)
      if (error) throw new Error(errorMessage(error))
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['together', 'picks'] }),
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
              {p.max_certificate && <span className="text-xs opacity-60">{p.max_certificate}</span>}
            </button>
          ))}
          {guests.map((g) => (
            <GuestChip key={g.id} guest={g} selected={selected.has(`guest:${g.id}`)} onToggle={() => toggle(`guest:${g.id}`)} />
          ))}
          {me.parent_id === null && <AddFriend onAdded={(g) => setChosen(new Set([...selected, `guest:${g.id}`]))} />}
        </div>
      </section>

      {picks.data && (
        <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-3">
          <button
            type="button"
            aria-pressed={shortlistOnly}
            onClick={() => setShortlistOnly(!shortlistOnly)}
            title="Films anyone at home saved for watching together"
            className={chip(shortlistOnly)}
          >
            <BookmarkIcon filled={shortlistOnly} className="size-3.5" />
            Group shortlist ({picks.data.shortlist_count})
          </button>
          <PlatformFilter platforms={picks.data.platforms} value={watchOn} onChange={setWatchOn} />
        </div>
      )}

      {me.parent_id === null && <GuestVote users={users} />}

      {(options.error || picks.error || shortlist.error) && (
        <div className="mt-6">
          <ErrorText>{(options.error ?? picks.error ?? shortlist.error)?.message}</ErrorText>
        </div>
      )}
      {users.length + guestIds.length === 0 ? (
        <Empty>Pick at least one person.</Empty>
      ) : picks.isPending ? (
        <p className="mt-6 text-sm text-white/50">Finding films for everyone…</p>
      ) : picks.data?.items.length === 0 && shortlistOnly && picks.data.shortlist_count === 0 ? (
        <Empty>
          Nothing on the group shortlist yet. Anyone at home can save a film with the bookmark on a card here, to
          choose from together later.
        </Empty>
      ) : picks.data?.items.length === 0 ? (
        <Empty>
          No picks yet. Each person’s films come from their{' '}
          <Link to="/" className="text-accent underline-offset-2 hover:underline">
            Discover
          </Link>{' '}
          feed, so it needs to be built first
          {Array.isArray(watchOn)
            ? ', and the films must be on the platforms you chose'
            : watchOn === 'anywhere'
              ? ', and the films must be on your Jellyfin server or services'
              : ''}
          .
        </Empty>
      ) : (
        <ul className="mt-6 grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-3 lg:grid-cols-4" aria-label="Group picks">
          {picks.data?.items.map((item) => (
            <GroupCard
              key={item.tmdb_id}
              item={item}
              onOpen={() => setOpen(item.tmdb_id)}
              onShortlist={() => shortlist.mutate({ tmdbId: item.tmdb_id, save: item.shortlisted_by === null })}
              busy={shortlist.isPending && shortlist.variables.tmdbId === item.tmdb_id}
            />
          ))}
        </ul>
      )}

      {options.data && me.parent_id === null && <ShareTaste share={options.data.share} />}

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

/** A link guests open on their phone to vote on the picks, and the votes so far. */
function GuestVote({ users }: { users: number[] }) {
  const queryClient = useQueryClient()
  const vote = useQuery({
    queryKey: ['together', 'vote'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/together/vote')
      if (error) throw new Error(errorMessage(error))
      return data ?? null
    },
    // Votes arrive while guests are on their phones.
    refetchInterval: (query) => (query.state.data ? 5000 : false),
  })
  const start = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST('/api/v1/together/vote', { body: { users } })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => queryClient.setQueryData(['together', 'vote'], data),
  })
  const close = useMutation({
    mutationFn: () => api.DELETE('/api/v1/together/vote'),
    onSuccess: () => queryClient.setQueryData(['together', 'vote'], null),
  })
  const error = vote.error ?? start.error ?? close.error
  const session = vote.data

  return (
    <section className="mt-6 rounded-xl border border-white/10 p-4" aria-label="Guest vote">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-medium">Guest vote</h2>
          <p className="mt-0.5 max-w-prose text-xs text-white/50">
            {session
              ? `Open until ${new Date(session.expires_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}. Closing it deletes guests’ names and votes.`
              : 'Friends without an account vote on these picks from their phone: yes, maybe, or no. They see posters and where films stream, nothing about anyone’s taste. The link ends after 24 hours or when you close it.'}
          </p>
        </div>
        {session ? (
          <Button variant="ghost" className="border border-white/10" onClick={() => close.mutate()} disabled={close.isPending}>
            Close vote
          </Button>
        ) : (
          <Button onClick={() => start.mutate()} disabled={start.isPending || users.length === 0 || vote.isPending}>
            {start.isPending ? 'Starting…' : 'Start a guest vote'}
          </Button>
        )}
      </div>
      {error && (
        <div className="mt-3">
          <ErrorText>{error.message}</ErrorText>
        </div>
      )}
      {session && <VoteResults session={session} />}
    </section>
  )
}

// Rows of the tally shown before "Show all".
const TALLY_ROWS = 8

function VoteResults({ session }: { session: VoteSessionOut }) {
  const link = `${window.location.origin}/vote/${session.token}`
  const [copied, setCopied] = useState(false)
  const [all, setAll] = useState(false)
  const shown = all ? session.films : session.films.slice(0, TALLY_ROWS)
  const qr = `data:image/svg+xml;utf8,${encodeURIComponent(renderSVG(link, { whiteColor: '#ffffff', blackColor: '#000000' }))}`
  return (
    <div className="mt-4 flex flex-col gap-5 sm:flex-row">
      <div className="shrink-0">
        <img src={qr} alt={`QR code for ${link}`} className="size-36 rounded-lg bg-white p-1.5" />
        <div className="mt-2 flex w-36 flex-col gap-1.5">
          <Button
            variant="ghost"
            className="border border-white/10 px-2 py-1 text-xs"
            onClick={() => {
              navigator.clipboard.writeText(link).then(() => setCopied(true))
            }}
          >
            {copied ? 'Link copied' : 'Copy link'}
          </Button>
          <a href={link} target="_blank" rel="noreferrer" className="text-center text-xs text-accent underline-offset-2 hover:underline">
            Open the guest page
          </a>
        </div>
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm text-white/70">
          {session.voters.length === 0
            ? 'No guests yet. Show them the QR code or send the link.'
            : `${session.voters.length} voting: ${session.voters.join(', ')}`}
        </p>
        <ol className="mt-3 space-y-1.5 text-sm" aria-label="Votes so far, best first">
          {shown.map((film) => (
            <li key={film.tmdb_id} className={`flex flex-wrap items-baseline gap-x-2 ${film.score === null ? 'text-white/35' : ''}`}>
              <span className="w-10 shrink-0 text-right font-medium tabular-nums">{film.score === null ? '–' : `${film.score}%`}</span>
              <span className="min-w-0 flex-1 truncate">
                {film.title} {film.year && <span className="text-white/40">({film.year})</span>}
                {film.added && <span className="ml-1.5 text-xs text-white/40">added by a guest</span>}
              </span>
              <span className="text-xs text-white/50">
                {[
                  film.tally.yes.length && `✓ ${film.tally.yes.join(', ')}`,
                  film.tally.maybe.length && `? ${film.tally.maybe.join(', ')}`,
                  film.tally.no.length && `✗ ${film.tally.no.join(', ')}`,
                  film.tally.seen.length && `seen by ${film.tally.seen.join(', ')}`,
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </span>
            </li>
          ))}
        </ol>
        {session.films.length > TALLY_ROWS && (
          <button type="button" onClick={() => setAll(!all)} className="mt-2 text-xs text-accent underline-offset-2 hover:underline">
            {all ? 'Show fewer' : `Show all ${session.films.length}`}
          </button>
        )}
        <p className="mt-2 text-xs text-white/40">
          Each film’s score averages the votes (yes 100%, maybe 50%, no 0%) with the household’s match counted as one more
          voter. Films a guest has seen go to the end.
        </p>
      </div>
    </div>
  )
}

function Empty({ children }: { children: ReactNode }) {
  return <div className="mt-6 rounded-xl border border-dashed border-white/15 p-6 text-sm text-white/60">{children}</div>
}

function GroupCard({
  item,
  onOpen,
  onShortlist,
  busy,
}: {
  item: GroupItem
  onOpen: () => void
  onShortlist: () => void
  busy: boolean
}) {
  const saved = item.shortlisted_by !== null
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
      <div className="mt-1.5 flex items-center gap-1">
        <button
          type="button"
          title={saved ? 'Remove from the group shortlist' : 'Add to the group shortlist'}
          aria-label={saved ? 'Remove from the group shortlist' : 'Add to the group shortlist'}
          aria-pressed={saved}
          disabled={busy}
          onClick={onShortlist}
          className={`flex size-8 items-center justify-center rounded-full transition-colors focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:outline-none disabled:opacity-40 ${
            saved ? 'bg-accent/15 text-accent-strong' : 'text-white/45 hover:bg-white/10 hover:text-white'
          }`}
        >
          <BookmarkIcon filled={saved} />
        </button>
        {saved && <span className="truncate text-xs text-white/50">Added by {item.shortlisted_by}</span>}
      </div>
      <h2 className="mt-1 text-sm leading-snug font-medium">{item.title}</h2>
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
        title={
          guest.error
            ? `Last refresh failed: ${guest.error}`
            : guest.from_card
              ? `Friend, ${guest.ratings} ratings from a taste card added ${new Date(guest.fetched_at).toLocaleDateString()}; ask for a new card to update it`
              : `Friend, ${guest.ratings} ratings shared`
        }
        className={`${chip(selected)} rounded-r-none border-r-0`}
      >
        {guest.name}
        <span className="text-xs opacity-60">{guest.from_card ? 'card' : 'friend'}</span>
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
  const [by, setBy] = useState<'card' | 'link'>('card')
  const [name, setName] = useState('')
  const [link, setLink] = useState('')
  const [card, setCard] = useState<File | null>(null)
  const add = useMutation({
    mutationFn: async () => {
      if (by === 'link') {
        const { data, error } = await api.POST('/api/v1/guests', { body: { name, link: link.trim() } })
        if (error) throw new Error(errorMessage(error))
        return data
      }
      const body = new FormData()
      body.append('name', name)
      body.append('file', card!)
      // openapi-fetch sends FormData as-is, letting the browser set the multipart boundary.
      const { data, error } = await api.POST('/api/v1/guests/card', {
        body: body as unknown as { name: string; file: string },
      })
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
      setCard(null)
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
        Ask a friend on another iWantToWatch server to send their taste card or share link (Watch together → Share
        your taste).
      </p>
      <div className="flex gap-2" role="radiogroup" aria-label="How your friend shares">
        {(
          [
            ['card', 'Taste card file'],
            ['link', 'Share link'],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={by === value}
            onClick={() => setBy(value)}
            className={chip(by === value)}
          >
            {label}
          </button>
        ))}
      </div>
      <p className="text-xs text-white/45">
        {by === 'card'
          ? 'Works from any home network. It doesn’t update itself; ask for a new card when they’ve rated more.'
          : 'Stays up to date, but only if this server can reach theirs, such as through a domain or Tailscale.'}
      </p>
      <Field label="Name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={64} />
      {by === 'card' ? (
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium text-white/80">Taste card</span>
          <input
            type="file"
            accept=".json,application/json"
            required
            onChange={(e) => setCard(e.target.files?.[0] ?? null)}
            className="block w-full text-sm text-white/70 file:mr-3 file:rounded-lg file:border file:border-white/10 file:bg-white/5 file:px-3 file:py-1.5 file:text-sm file:text-white/80 hover:file:bg-white/10"
          />
        </label>
      ) : (
        <Field
          label="Share link"
          value={link}
          onChange={(e) => setLink(e.target.value)}
          required
          placeholder="https://…/api/v1/shared/…"
        />
      )}
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
        Friends on other iWantToWatch servers can add you to their group picks. Both ways share only which films
        you’ve seen and how much you liked them, not your name or account.
      </p>

      <h3 className="mt-5 text-sm font-medium text-white/80">Taste card</h3>
      <p className="mt-1 text-sm text-white/60">
        A small file to send by WhatsApp or email. Works from any home network; send a new one when you’ve rated
        more. Once sent, it can’t be revoked.
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
        Stays up to date and can be revoked any time, but your friend’s server must be able to reach this one, such
        as through a domain or Tailscale.
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
        <Button
          variant="ghost"
          className="mt-3 border border-white/10"
          onClick={() => create.mutate()}
          disabled={create.isPending}
        >
          Create share link
        </Button>
      )}
    </section>
  )
}
