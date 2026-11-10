import type { Reaction, TitleReaction } from '@iwanttowatch/api-client'
import { useEffect, useRef, useState } from 'react'
import { REACTIONS, useReaction } from './api'
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
  const { film, error, remove } = useReaction(tmdbId)
  if (error) {
    return (
      <div className="space-y-4 p-6">
        <ErrorText>{error.message}</ErrorText>
        <Button variant="ghost" onClick={onDone}>
          Close
        </Button>
      </div>
    )
  }
  if (!film) return <p className="p-6 text-sm text-white/50">Loading…</p>

  return (
    <div className="p-5 sm:p-6">
      <div className="flex gap-4">
        <div className="w-16 shrink-0">
          <Poster path={film.poster_path} title={film.title} />
        </div>
        <div className="min-w-0">
          <h2 className="text-lg font-semibold">{film.title}</h2>
          <p className="text-sm text-white/50">
            {[film.year, film.original_title !== film.title ? film.original_title : null].filter(Boolean).join(' · ')}
          </p>
          <p className="mt-2 text-sm text-white/70">How was it?</p>
        </div>
      </div>

      <RatePicker tmdbId={tmdbId} className="mt-4" />

      {remove.error && (
        <div className="mt-4">
          <ErrorText>{remove.error.message}</ErrorText>
        </div>
      )}

      <div className="mt-6 flex items-center justify-between gap-3">
        {film.reaction ? (
          <Button variant="ghost" onClick={() => remove.mutate(undefined, { onSuccess: onDone })} disabled={remove.isPending}>
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

/** One tag the user can pick for why they liked, or didn't like, a film. */
function TagChip({
  tag,
  selected,
  disabled,
  onClick,
}: {
  tag: TagOption
  selected: boolean
  disabled: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      disabled={disabled}
      onClick={onClick}
      className={`rounded-full border px-3 py-1 text-sm transition-colors focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-35 ${
        selected
          ? 'border-accent bg-accent/15 text-accent-strong'
          : 'border-white/10 text-white/65 hover:border-white/25 hover:text-white'
      }`}
    >
      {tag.label}
    </button>
  )
}

/**
 * The three reactions as buttons, then, once one is chosen, tags and a note. Choosing saves
 * at once and marks the film watched. `compact` lays it out for the film details, where the
 * note stays behind a link until it is wanted.
 */
export function RatePicker({
  tmdbId,
  compact = false,
  className = '',
  onRemoved,
}: {
  tmdbId: number
  compact?: boolean
  className?: string
  onRemoved?: () => void
}) {
  const { film, error, save, remove } = useReaction(tmdbId)
  const [note, setNote] = useState<string | null>(null)
  const [more, setMore] = useState(false)
  const [noting, setNoting] = useState(false)
  // The note being typed, or the saved one until the user edits it.
  const draft = note ?? film?.note ?? ''

  const positive = film?.reaction !== 'disliked'
  const options = film ? (positive ? film.liked_tags : film.disliked_tags) : []
  const group = (name: TagOption['group']) => options.filter((t) => t.group === name)
  const extra = group('more')
  const showMore = more || (film !== undefined && extra.some((t) => film.tags.includes(t.id)))
  const choose = (reaction: Reaction) => {
    // Tags only carry over while the answer stays on the same side; the note always does.
    const tags = film && (reaction === 'disliked') === (film.reaction === 'disliked') ? film.tags : []
    save.mutate({ reaction, tags, note: draft })
  }
  const toggle = (tag: string) => {
    if (!film?.reaction) return
    const tags = film.tags.includes(tag) ? film.tags.filter((t) => t !== tag) : [...film.tags, tag]
    save.mutate({ reaction: film.reaction, tags, note: draft })
  }
  const saveNote = () => {
    if (film?.reaction && draft.trim() !== (film.note ?? '')) {
      save.mutate({ reaction: film.reaction, tags: film.tags, note: draft })
    }
  }
  const chips = (tags: TagOption[]) => (
    <div className="mt-2 flex flex-wrap gap-2">
      {tags.map((tag) => {
        const selected = film?.tags.includes(tag.id) ?? false
        return (
          <TagChip
            key={tag.id}
            tag={tag}
            selected={selected}
            disabled={!selected && (film?.tags.length ?? 0) >= MAX_TAGS}
            onClick={() => toggle(tag.id)}
          />
        )
      })}
    </div>
  )
  const showNote = !compact || noting || draft !== ''
  const failure = error ?? save.error ?? remove.error

  return (
    <div className={className}>
      <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Your rating">
        {REACTIONS.map((r) => {
          const selected = film?.reaction === r.value
          return (
            <button
              key={r.value}
              type="button"
              role="radio"
              aria-checked={selected}
              disabled={!film}
              onClick={() => choose(r.value)}
              className={`flex items-center rounded-xl border text-sm transition-colors focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:outline-none disabled:opacity-50 ${
                compact ? 'justify-center gap-2 px-2 py-2' : 'flex-col gap-1.5 px-2 py-3'
              } ${
                selected
                  ? 'border-accent bg-accent/15 font-medium text-accent-strong'
                  : 'border-white/10 text-white/70 hover:border-white/30 hover:text-white'
              }`}
            >
              <ReactionIcon reaction={r.value} className={compact ? 'size-5' : 'size-6'} />
              {r.label}
            </button>
          )
        })}
      </div>

      {film?.reaction && (
        <fieldset className={compact ? 'mt-3 rounded-xl border border-accent/30 bg-white/[0.02] p-3' : 'mt-5'}>
          <legend className="text-sm font-medium">
            {positive ? 'What did you like most?' : 'What didn’t work?'}{' '}
            <span className="font-normal text-white/45">Optional, up to {MAX_TAGS}</span>
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
          {compact && (
            <div className="mt-3 flex items-center justify-between gap-3 text-sm">
              {showNote ? (
                <span />
              ) : (
                <button
                  type="button"
                  onClick={() => setNoting(true)}
                  className="text-accent-strong underline-offset-2 hover:underline"
                >
                  + Add a note
                </button>
              )}
              <button
                type="button"
                onClick={() => remove.mutate(undefined, { onSuccess: onRemoved })}
                disabled={remove.isPending}
                className="text-white/45 underline-offset-2 hover:text-white hover:underline disabled:opacity-40"
              >
                Remove rating
              </button>
            </div>
          )}
        </fieldset>
      )}

      {film?.reaction && showNote && (
        <label className={compact ? 'mt-3 block' : 'mt-5 block'}>
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

      {failure && (
        <div className="mt-3">
          <ErrorText>{failure.message}</ErrorText>
        </div>
      )}
    </div>
  )
}

/** A film's most common tags as quick taps, for right after rating it. */
export function QuickTags({ tmdbId, onChange }: { tmdbId: number; onChange?: () => void }) {
  const { film, save } = useReaction(tmdbId)
  if (!film?.reaction) return null
  const positive = film.reaction !== 'disliked'
  const tags = (positive ? film.liked_tags : film.disliked_tags).filter((t) => t.group === 'core')
  const toggle = (tag: string) => {
    const chosen = film.tags.includes(tag) ? film.tags.filter((t) => t !== tag) : [...film.tags, tag]
    save.mutate({ reaction: film.reaction!, tags: chosen, note: film.note ?? '' })
    onChange?.()
  }
  return (
    <div>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-xs text-white/50">{positive ? 'What stood out?' : 'What didn’t work?'}</span>
        {tags.map((tag) => {
          const selected = film.tags.includes(tag.id)
          return (
            <TagChip
              key={tag.id}
              tag={tag}
              selected={selected}
              disabled={!selected && film.tags.length >= MAX_TAGS}
              onClick={() => toggle(tag.id)}
            />
          )
        })}
      </div>
      {save.error && (
        <div className="mt-2">
          <ErrorText>{save.error.message}</ErrorText>
        </div>
      )}
    </div>
  )
}

const THUMB_UP =
  'M7 10v12M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z'
const HEART =
  'M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z'

/** Thumb down, thumb up, or heart. */
export function ReactionIcon({ reaction, className = '' }: { reaction: Reaction; className?: string }) {
  const stroke = { fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' } as const
  if (reaction === 'loved') {
    return (
      <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
        <path d={HEART} {...stroke} />
      </svg>
    )
  }
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      <path d={THUMB_UP} {...stroke} transform={reaction === 'disliked' ? 'rotate(180 12 12)' : undefined} />
    </svg>
  )
}

/** Standard pill badge for a 3-scale personal rating reaction. */
export function ReactionBadge({
  reaction,
  label,
  className = '',
  size = 'sm',
}: {
  reaction: Reaction
  label?: string
  className?: string
  size?: 'xs' | 'sm'
}) {
  const styles: Record<Reaction, { badge: string; defaultLabel: string }> = {
    loved: {
      badge: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300',
      defaultLabel: 'Loved',
    },
    liked: {
      badge: 'border-accent/20 bg-accent/10 text-accent',
      defaultLabel: 'Liked',
    },
    disliked: {
      badge: 'border-red-500/20 bg-red-500/10 text-red-300',
      defaultLabel: 'Didn’t like',
    },
  }
  const config = styles[reaction]
  const text = label !== undefined ? label : config.defaultLabel
  const iconSize = size === 'xs' ? 'size-3' : 'size-3.5'
  const padding = size === 'xs' ? 'px-1.5 py-0.2 text-[11px]' : 'px-2 py-0.5 text-xs'

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md border font-medium ${config.badge} ${padding} ${className}`}
    >
      <ReactionIcon reaction={reaction} className={iconSize} />
      {text ? <span>{text}</span> : null}
    </span>
  )
}

