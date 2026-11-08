import type { Reaction, TitleReaction } from '@iwanttowatch/api-client'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api, errorMessage, REACTIONS } from './api'
import { Button, ErrorText, Poster } from './ui'

const MAX_TAGS = 3
const MAX_NOTE = 200

type TagOption = TitleReaction['liked_tags'][number]

/** Netflix-style rating: Didn't like / Liked / Loved, then up to three tags and a note saying why. */
export default function RateDialog({ tmdbId, onClose }: { tmdbId: number | null; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    if (tmdbId !== null) dialog.current?.showModal()
    else dialog.current?.close()
  }, [tmdbId])

  return (
    <dialog
      ref={dialog}
      onClose={onClose}
      onClick={(e) => e.target === dialog.current && dialog.current.close()}
      aria-label="Rate this film"
      className="m-auto w-[min(32rem,calc(100vw-2rem))] rounded-2xl border border-white/10 bg-[#11141b] p-0 text-[#e7e9ee] shadow-2xl backdrop:bg-black/70"
    >
      {tmdbId !== null && <RateForm key={tmdbId} tmdbId={tmdbId} onDone={() => dialog.current?.close()} />}
    </dialog>
  )
}

function RateForm({ tmdbId, onDone }: { tmdbId: number; onDone: () => void }) {
  const queryClient = useQueryClient()
  const key = ['reaction', tmdbId]
  const state = useQuery({
    queryKey: key,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/titles/{tmdb_id}/reaction', {
        params: { path: { tmdb_id: tmdbId } },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
  })
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['ratings'] })
    queryClient.invalidateQueries({ queryKey: ['persona'] })
    // Rated films leave the feed and group picks.
    queryClient.invalidateQueries({ queryKey: ['feed'] })
    queryClient.invalidateQueries({ queryKey: ['together'] })
  }
  const save = useMutation({
    mutationFn: async (body: { reaction: Reaction; tags: string[]; note: string }) => {
      const { data, error } = await api.PUT('/api/v1/titles/{tmdb_id}/reaction', {
        params: { path: { tmdb_id: tmdbId } },
        body,
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    // Show the choice at once; the server's answer replaces it.
    onMutate: (body) =>
      queryClient.setQueryData<TitleReaction>(key, (old) => old && { ...old, ...body }),
    onSuccess: (data) => {
      queryClient.setQueryData(key, data)
      refresh()
    },
    onError: () => queryClient.invalidateQueries({ queryKey: key }),
  })
  const remove = useMutation({
    mutationFn: () =>
      api.DELETE('/api/v1/titles/{tmdb_id}/reaction', { params: { path: { tmdb_id: tmdbId } } }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: key })
      refresh()
      onDone()
    },
  })

  const film = state.data
  const [note, setNote] = useState<string | null>(null)
  const [more, setMore] = useState(false)
  // The note being typed, or the saved one until the user edits it.
  const draft = note ?? film?.note ?? ''
  if (state.error) {
    return (
      <div className="space-y-4 p-6">
        <ErrorText>{state.error.message}</ErrorText>
        <Button variant="ghost" onClick={onDone}>
          Close
        </Button>
      </div>
    )
  }
  if (!film) return <p className="p-6 text-sm text-white/50">Loading…</p>

  const positive = film.reaction !== 'disliked'
  const options = positive ? film.liked_tags : film.disliked_tags
  const group = (name: TagOption['group']) => options.filter((t) => t.group === name)
  const extra = group('more')
  const showMore = more || extra.some((t) => film.tags.includes(t.id))
  const choose = (reaction: Reaction) => {
    // Tags only carry over while the answer stays on the same side; the note always does.
    const sameSide = (reaction === 'disliked') === (film.reaction === 'disliked')
    save.mutate({ reaction, tags: sameSide ? film.tags : [], note: draft })
  }
  const toggle = (tag: string) => {
    if (!film.reaction) return
    const tags = film.tags.includes(tag) ? film.tags.filter((t) => t !== tag) : [...film.tags, tag]
    save.mutate({ reaction: film.reaction, tags, note: draft })
  }
  const saveNote = () => {
    if (film.reaction && draft.trim() !== (film.note ?? '')) {
      save.mutate({ reaction: film.reaction, tags: film.tags, note: draft })
    }
  }
  const chips = (tags: TagOption[]) => (
    <div className="mt-2 flex flex-wrap gap-2">
      {tags.map((tag) => {
        const selected = film.tags.includes(tag.id)
        const full = !selected && film.tags.length >= MAX_TAGS
        return (
          <button
            key={tag.id}
            type="button"
            aria-pressed={selected}
            disabled={full}
            onClick={() => toggle(tag.id)}
            className={`rounded-full border px-3 py-1 text-sm transition-colors focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-35 ${
              selected
                ? 'border-accent bg-accent/15 text-accent-strong'
                : 'border-white/10 text-white/65 hover:border-white/25 hover:text-white'
            }`}
          >
            {tag.label}
          </button>
        )
      })}
    </div>
  )

  return (
    <div className="p-5 sm:p-6">
      <div className="flex gap-4">
        <div className="w-16 shrink-0">
          <Poster path={film.poster_path} title={film.title} />
        </div>
        <div className="min-w-0">
          <h2 className="text-lg font-semibold">{film.title}</h2>
          <p className="text-sm text-white/50">
            {[film.year, film.original_title !== film.title ? film.original_title : null]
              .filter(Boolean)
              .join(' · ')}
          </p>
          <p className="mt-2 text-sm text-white/70">How was it?</p>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-2" role="radiogroup" aria-label="Your rating">
        {REACTIONS.map((r) => {
          const selected = film.reaction === r.value
          return (
            <button
              key={r.value}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => choose(r.value)}
              className={`flex flex-col items-center gap-1.5 rounded-xl border px-2 py-3 text-sm transition-colors focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:outline-none ${
                selected
                  ? 'border-accent bg-accent/15 text-accent-strong'
                  : 'border-white/10 text-white/70 hover:border-white/30 hover:text-white'
              }`}
            >
              <ReactionIcon reaction={r.value} className="size-6" />
              {r.label}
            </button>
          )
        })}
      </div>

      {film.reaction && (
        <fieldset className="mt-5">
          <legend className="text-sm font-medium">
            {positive ? 'What did you like most?' : 'What didn’t work?'}{' '}
            <span className="font-normal text-white/45">
              Optional, up to {MAX_TAGS}
            </span>
          </legend>
          {chips(group('core'))}
          {group('suggested').length > 0 && (
            <>
              <p className="mt-3 text-xs text-white/45">Suggested for this film</p>
              {chips(group('suggested'))}
            </>
          )}
          {showMore ? (
            <>
              <p className="mt-3 text-xs text-white/45">More</p>
              {chips(extra)}
            </>
          ) : (
            <button
              type="button"
              onClick={() => setMore(true)}
              className="mt-3 text-sm text-white/55 underline-offset-2 hover:text-white hover:underline"
            >
              More tags ({extra.length})
            </button>
          )}
        </fieldset>
      )}

      {film.reaction && (
        <label className="mt-5 block">
          <span className="text-sm font-medium">
            Anything else? <span className="font-normal text-white/45">Optional</span>
          </span>
          <textarea
            value={draft}
            onChange={(e) => setNote(e.target.value)}
            onBlur={saveNote}
            maxLength={MAX_NOTE}
            rows={2}
            placeholder={positive ? 'What made it work for you?' : 'What put you off?'}
            className="mt-2 block w-full resize-none rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm placeholder:text-white/30 focus:border-accent/60 focus:outline-none"
          />
          <span className="mt-1 flex justify-between text-xs text-white/40">
            <span>Helps the AI understand your taste.</span>
            <span>
              {draft.length}/{MAX_NOTE}
            </span>
          </span>
        </label>
      )}

      {(save.error || remove.error) && (
        <div className="mt-4">
          <ErrorText>{(save.error ?? remove.error)?.message}</ErrorText>
        </div>
      )}

      <div className="mt-6 flex items-center justify-between gap-3">
        {film.reaction ? (
          <Button variant="ghost" onClick={() => remove.mutate()} disabled={remove.isPending}>
            Remove rating
          </Button>
        ) : (
          <span />
        )}
        <Button onClick={onDone}>Done</Button>
      </div>
    </div>
  )
}

const THUMB_UP =
  'M7 10v12M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z'

/** Thumb down, thumb up, or two thumbs up, as on Netflix. */
export function ReactionIcon({ reaction, className = '' }: { reaction: Reaction; className?: string }) {
  const stroke = { fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' } as const
  if (reaction === 'loved') {
    return (
      <svg viewBox="0 0 32 24" className={className} aria-hidden="true" style={{ aspectRatio: '4 / 3' }}>
        <path d={THUMB_UP} {...stroke} className="opacity-50" transform="translate(1 0)" />
        {/* The front thumb is filled with the page colour so it hides the one behind. */}
        <path d={THUMB_UP} {...stroke} fill="var(--thumb-bg, #11141b)" transform="translate(9 0)" />
      </svg>
    )
  }
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      <path d={THUMB_UP} {...stroke} transform={reaction === 'disliked' ? 'rotate(180 12 12)' : undefined} />
    </svg>
  )
}
