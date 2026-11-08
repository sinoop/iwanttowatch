import type { Ballot, BallotFilm } from '@iwanttowatch/api-client'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, errorMessage } from './api'
import { WatchBadges } from './Streaming'
import { Button, ErrorText, Field, Poster } from './ui'

type Choice = 'yes' | 'maybe' | 'no' | 'seen'

const CHOICES: { value: Choice; label: string }[] = [
  { value: 'yes', label: 'Yes' },
  { value: 'maybe', label: 'Maybe' },
  { value: 'no', label: 'No' },
  { value: 'seen', label: 'Seen it' },
]

/** The page guests open from a vote link: no account, just a first name and a vote per film. */
export default function Vote({ token }: { token: string }) {
  const storageKey = `iwanttowatch-voter-${token}`
  const [voter, setVoter] = useState(() => localStorage.getItem(storageKey))
  const queryClient = useQueryClient()
  const key = ['vote', token, voter]
  const ballot = useQuery({
    queryKey: key,
    queryFn: async () => {
      const { data, error, response } = await api.GET('/api/v1/vote/{token}', {
        params: { path: { token }, header: { 'x-voter': voter } },
      })
      if (response.status === 404) return null
      if (error) throw new Error(errorMessage(error))
      return data
    },
  })
  const cast = useMutation({
    mutationFn: async ({ tmdbId, choice }: { tmdbId: number; choice: Choice }) => {
      const { error } = await api.PUT('/api/v1/vote/{token}/votes/{tmdb_id}', {
        params: { path: { token, tmdb_id: tmdbId }, header: { 'x-voter': voter } },
        body: { choice },
      })
      if (error) throw new Error(errorMessage(error))
    },
    // Show the vote at once; a failure reloads the ballot.
    onMutate: ({ tmdbId, choice }) =>
      queryClient.setQueryData<Ballot | null>(key, (old) => old && { ...old, votes: { ...old.votes, [tmdbId]: choice } }),
    onError: () => queryClient.invalidateQueries({ queryKey: key }),
  })

  const joined = (voterToken: string) => {
    localStorage.setItem(storageKey, voterToken)
    setVoter(voterToken)
  }

  return (
    <main className="mx-auto max-w-2xl px-4 py-8 sm:px-6">
      <h1 className="text-2xl font-semibold">Movie night vote</h1>
      {ballot.isPending ? (
        <p className="mt-4 text-sm text-white/50">Loading…</p>
      ) : ballot.error ? (
        <div className="mt-4">
          <ErrorText>{ballot.error.message}</ErrorText>
        </div>
      ) : !ballot.data ? (
        <p className="mt-4 text-white/60">This vote has ended, or the link is wrong. Ask your host for a new one.</p>
      ) : !voter ? (
        <Join token={token} expiresAt={ballot.data.expires_at} onJoined={joined} />
      ) : (
        <>
          <p className="mt-1 text-white/60">
            Vote on each film; your host sees the results. You’ve voted on {Object.keys(ballot.data.votes).length} of{' '}
            {ballot.data.films.length}.
          </p>
          {cast.error && (
            <div className="mt-4">
              <ErrorText>{cast.error.message}</ErrorText>
            </div>
          )}
          <ul className="mt-6 space-y-4" aria-label="Films to vote on">
            {ballot.data.films.map((film) => (
              <FilmVote
                key={film.tmdb_id}
                film={film}
                choice={ballot.data!.votes[film.tmdb_id] as Choice | undefined}
                onVote={(choice) => cast.mutate({ tmdbId: film.tmdb_id, choice })}
              />
            ))}
          </ul>
          {ballot.data.can_add && <AddFilm token={token} voter={voter} />}
          <p className="mt-8 text-xs text-white/40">
            Open until {new Date(ballot.data.expires_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}.
            Your name and votes are deleted when the vote ends.
          </p>
        </>
      )}
    </main>
  )
}

function Join({ token, expiresAt, onJoined }: { token: string; expiresAt: string; onJoined: (voter: string) => void }) {
  const [name, setName] = useState('')
  const join = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST('/api/v1/vote/{token}/join', {
        params: { path: { token } },
        body: { name },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => onJoined(data.voter_token),
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    join.mutate()
  }
  return (
    <form onSubmit={submit} className="mt-4 max-w-sm space-y-4">
      <p className="text-white/60">
        Help pick tonight’s film. No account needed: enter your first name, then vote yes, maybe, or no on each film.
      </p>
      <Field label="Your first name" value={name} onChange={(e) => setName(e.target.value)} maxLength={32} required autoFocus />
      {join.error && <ErrorText>{join.error.message}</ErrorText>}
      <Button type="submit" disabled={join.isPending}>
        Start voting
      </Button>
      <p className="text-xs text-white/40">
        Open until {new Date(expiresAt).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}.
      </p>
    </form>
  )
}

function FilmVote({ film, choice, onVote }: { film: BallotFilm; choice: Choice | undefined; onVote: (choice: Choice) => void }) {
  const details = [
    film.year,
    film.runtime ? `${Math.floor(film.runtime / 60)}h ${film.runtime % 60}m` : null,
    film.genres.slice(0, 2).join(', ') || null,
  ].filter(Boolean)
  return (
    <li className="flex gap-3 rounded-xl border border-white/10 p-3">
      <div className="w-16 shrink-0 sm:w-20">
        <Poster path={film.poster_path} title={film.title} />
      </div>
      <div className="min-w-0 flex-1">
        <h2 className="leading-snug font-medium">{film.title}</h2>
        {film.original_title !== film.title && <p className="text-xs text-white/50">{film.original_title}</p>}
        <p className="text-xs text-white/50">{details.join(' · ')}</p>
        <WatchBadges availability={film.availability} />
        <div className="mt-2 grid grid-cols-4 gap-1.5" role="radiogroup" aria-label={`Your vote on ${film.title}`}>
          {CHOICES.map((c) => (
            <button
              key={c.value}
              type="button"
              role="radio"
              aria-checked={choice === c.value}
              onClick={() => onVote(c.value)}
              className={`rounded-lg border px-1 py-1.5 text-sm transition-colors focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:outline-none ${
                choice === c.value
                  ? c.value === 'no'
                    ? 'border-red-400/60 bg-red-500/15 text-red-200'
                    : 'border-accent bg-accent/15 text-accent-strong'
                  : 'border-white/10 text-white/65 hover:border-white/25 hover:text-white'
              }`}
            >
              {c.label}
            </button>
          ))}
        </div>
      </div>
    </li>
  )
}

function AddFilm({ token, voter }: { token: string; voter: string }) {
  const queryClient = useQueryClient()
  const [query, setQuery] = useState('')
  const [submitted, setSubmitted] = useState('')
  const results = useQuery({
    queryKey: ['vote-search', token, submitted],
    enabled: submitted.length >= 2,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/vote/{token}/search', {
        params: { path: { token }, query: { query: submitted } },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
  })
  const add = useMutation({
    mutationFn: async (tmdbId: number) => {
      const { error } = await api.POST('/api/v1/vote/{token}/films/{tmdb_id}', {
        params: { path: { token, tmdb_id: tmdbId }, header: { 'x-voter': voter } },
      })
      if (error) throw new Error(errorMessage(error))
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vote', token] })
      queryClient.invalidateQueries({ queryKey: ['vote-search', token] })
    },
  })
  return (
    <section className="mt-8 rounded-xl border border-white/10 p-4">
      <h2 className="text-sm font-medium">Add a film</h2>
      <p className="mt-1 text-xs text-white/50">Only films your host can play are listed.</p>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          setSubmitted(query.trim())
        }}
        className="mt-3 flex gap-2"
      >
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search for a film"
          aria-label="Search for a film"
          className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent/30"
        />
        <Button type="submit" variant="ghost" className="border border-white/10">
          Search
        </Button>
      </form>
      {(results.error || add.error) && (
        <div className="mt-3">
          <ErrorText>{(results.error ?? add.error)?.message}</ErrorText>
        </div>
      )}
      {results.data && (
        <ul className="mt-3 space-y-2">
          {results.data.length === 0 && <li className="text-sm text-white/50">Nothing your host can play matches that.</li>}
          {results.data.map((r) => (
            <li key={r.tmdb_id} className="flex items-center gap-3 text-sm">
              <span className="flex-1">
                {r.title} {r.year && <span className="text-white/45">({r.year})</span>}
              </span>
              {r.on_ballot ? (
                <span className="text-xs text-white/45">On the ballot</span>
              ) : (
                <Button variant="ghost" className="border border-white/10 px-3 py-1" disabled={add.isPending} onClick={() => add.mutate(r.tmdb_id)}>
                  Add
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
