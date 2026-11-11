import type { Reaction, TitleReaction } from '@iwanttowatch/api-client'
import { useEffect, useRef, useState } from 'react'
import { useReaction } from './api'
import { Button, ErrorText, Poster } from './ui'

const MAX_TAGS = 5
const PRIMARY_MAX = 3
const CAVEAT_MAX = 2
const MAX_NOTE = 200

type TagOption = TitleReaction['liked_tags'][number]

/** Rating dialog: Watched, Didn't like, Liked, Loved, then tags and note. */
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
      className="m-auto max-h-[90vh] w-[min(32rem,calc(100vw-2rem))] overflow-y-auto rounded-2xl border border-white/10 bg-[#11141b] p-0 text-[#e7e9ee] shadow-2xl backdrop:bg-black/70"
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
          <p className="text-sm text-white/50">{film.year}</p>
          <p className="mt-2 text-sm text-white/70">How was it?</p>
        </div>
      </div>

      <div className="mt-4">
        <RatingHeaderDock tmdbId={tmdbId} />
        <SentimentTagsCard tmdbId={tmdbId} className="mt-3" />
      </div>

      {remove.error && (
        <div className="mt-4">
          <ErrorText>{remove.error.message}</ErrorText>
        </div>
      )}

      <div className="mt-6 flex items-center justify-between gap-3">
        {film.reaction || film.watched ? (
          <Button
            variant="ghost"
            onClick={() => remove.mutate(undefined, { onSuccess: onDone })}
            disabled={remove.isPending}
          >
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
export function TagChip({
  tag,
  selected,
  disabled,
  isCaveat = false,
  onClick,
}: {
  tag: TagOption
  selected: boolean
  disabled: boolean
  isCaveat?: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      disabled={disabled}
      onClick={onClick}
      className={`rounded-full border px-3 py-1 text-xs transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent/60 disabled:cursor-not-allowed disabled:opacity-35 ${
        selected
          ? isCaveat
            ? 'border-amber-400/60 bg-amber-400/15 text-amber-200'
            : 'border-accent bg-accent/15 text-accent-strong'
          : 'border-white/10 bg-white/5 text-white/65 hover:border-white/25 hover:text-white'
      }`}
    >
      {tag.label}
    </button>
  )
}

const RATING_OPTIONS: Array<{
  value: Reaction | 'watched'
  label: string
  activeClass: string
  hoverClass: string
  pillClass: string
}> = [
  {
    value: 'watched',
    label: 'Watched',
    activeClass: 'border-sky-500 bg-sky-500/25 text-sky-300 ring-1 ring-sky-500/50',
    hoverClass: 'hover:border-sky-500/50 hover:bg-sky-500/10 hover:text-sky-300',
    pillClass: 'border-sky-500/30 bg-sky-500/15 text-sky-300 hover:bg-sky-500/25',
  },
  {
    value: 'disliked',
    label: 'Didn’t like',
    activeClass: 'border-rose-500 bg-rose-500/25 text-rose-300 ring-1 ring-rose-500/50',
    hoverClass: 'hover:border-rose-500/50 hover:bg-rose-500/10 hover:text-rose-300',
    pillClass: 'border-rose-500/30 bg-rose-500/15 text-rose-300 hover:bg-rose-500/25',
  },
  {
    value: 'liked',
    label: 'Liked',
    activeClass: 'border-amber-500 bg-amber-500/25 text-amber-300 ring-1 ring-amber-500/50',
    hoverClass: 'hover:border-amber-500/50 hover:bg-amber-500/10 hover:text-amber-300',
    pillClass: 'border-amber-500/30 bg-amber-500/15 text-amber-300 hover:bg-amber-500/25',
  },
  {
    value: 'loved',
    label: 'Loved',
    activeClass: 'border-emerald-500 bg-emerald-500/25 text-emerald-300 ring-1 ring-emerald-500/50',
    hoverClass: 'hover:border-emerald-500/50 hover:bg-emerald-500/10 hover:text-emerald-300',
    pillClass: 'border-emerald-500/30 bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25',
  },
]

/**
 * Compact rating dock for the header:
 * - Unrated: shows 4 small icon buttons: Watched, Didn't like, Liked, Loved.
 * - Rated/Watched: collapses to a single color-coded pill. Clicking it expands to all 4 choices and a clear button.
 */
export function RatingHeaderDock({ tmdbId, className = '' }: { tmdbId: number; className?: string }) {
  const { film, save, remove } = useReaction(tmdbId)
  const [isExpanded, setIsExpanded] = useState(false)
  const dockRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!isExpanded) return
    const handleClickOutside = (e: MouseEvent) => {
      if (dockRef.current && !dockRef.current.contains(e.target as Node)) {
        setIsExpanded(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [isExpanded])

  const currentValue: Reaction | 'watched' | null =
    film?.reaction ?? (film?.watched ? 'watched' : null)

  const handleSelect = (choice: Reaction | 'watched') => {
    if (choice === currentValue) {
      // Toggle off / unrate
      remove.mutate()
      setIsExpanded(false)
      return
    }
    if (choice === 'watched') {
      save.mutate({ reaction: null, watched: true, tags: [], note: '' })
    } else {
      save.mutate({
        reaction: choice,
        watched: true,
        tags: film?.tags ?? [],
        note: film?.note ?? '',
      })
    }
    setIsExpanded(false)
  }

  // Collapsed state: single color-coded pill
  if (currentValue !== null && !isExpanded) {
    const activeOpt = RATING_OPTIONS.find((o) => o.value === currentValue) ?? RATING_OPTIONS[0]
    return (
      <div className={`inline-flex items-center ${className}`}>
        <button
          type="button"
          onClick={() => setIsExpanded(true)}
          title={`Rated: ${activeOpt.label}. Click to change or remove.`}
          aria-label={`Rated: ${activeOpt.label}. Click to change or remove.`}
          className={`group inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold shadow-sm transition-all focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent ${activeOpt.pillClass}`}
        >
          <ReactionIcon reaction={activeOpt.value} className="size-3.5" />
          <span>{activeOpt.label}</span>
          <svg
            viewBox="0 0 20 20"
            fill="currentColor"
            className="size-3 text-white/50 transition-transform group-hover:text-white"
            aria-hidden="true"
          >
            <path
              fillRule="evenodd"
              d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z"
              clipRule="evenodd"
            />
          </svg>
        </button>
      </div>
    )
  }

  // Expanded dock or unrated state: 4 small icon buttons
  return (
    <div
      ref={dockRef}
      className={`inline-flex items-center gap-1 rounded-full border border-white/10 bg-[#161a23] p-1 shadow-md ${className}`}
      role="radiogroup"
      aria-label="Rate or mark as watched"
    >
      {RATING_OPTIONS.map((opt) => {
        const selected = currentValue === opt.value
        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={!film}
            title={opt.label}
            aria-label={opt.label}
            onClick={() => handleSelect(opt.value)}
            className={`flex size-7 items-center justify-center rounded-full border transition-all focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent sm:size-8 ${
              selected
                ? `${opt.activeClass}`
                : `border-transparent text-white/60 ${opt.hoverClass}`
            }`}
          >
            <ReactionIcon reaction={opt.value} className="size-4" />
          </button>
        )
      })}
      {currentValue !== null && (
        <button
          type="button"
          onClick={() => {
            remove.mutate()
            setIsExpanded(false)
          }}
          title="Remove rating"
          aria-label="Remove rating"
          className="flex size-7 items-center justify-center rounded-full text-white/40 transition-colors hover:bg-rose-500/15 hover:text-rose-400 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-rose-500 sm:size-8"
        >
          <svg viewBox="0 0 20 20" fill="currentColor" className="size-3.5" aria-hidden="true">
            <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
          </svg>
        </button>
      )}
    </div>
  )
}

/**
 * Split Sentiment Card: "− The Bad" & "+ The Good".
 * Shows top ~5 applicable tags per side, with toggle to show all available tags.
 */
export function SentimentTagsCard({ tmdbId, className = '' }: { tmdbId: number; className?: string }) {
  const { film, error, save } = useReaction(tmdbId)
  const [note, setNote] = useState<string | null>(null)
  const [showNote, setShowNote] = useState(false)
  const [showAllTags, setShowAllTags] = useState(false)

  if (!film?.reaction) return null

  const draft = note ?? film.note ?? ''
  const isPositiveReaction = film.reaction !== 'disliked'
  const maxPrimary = PRIMARY_MAX // 3
  const maxCaveat = CAVEAT_MAX // 2

  // Disliked: Primary is Bad (max 3), Caveat is Good (max 2)
  // Liked/Loved: Primary is Good (max 3), Caveat is Bad (max 2)
  const badLimit = isPositiveReaction ? maxCaveat : maxPrimary
  const goodLimit = isPositiveReaction ? maxPrimary : maxCaveat

  const badOptions = film.disliked_tags
  const goodOptions = film.liked_tags

  const badSelected = film.tags.filter((id) => badOptions.some((t) => t.id === id))
  const goodSelected = film.tags.filter((id) => goodOptions.some((t) => t.id === id))
  const totalSelected = film.tags.length

  const getVisibleTags = (options: TagOption[]) => {
    if (showAllTags) return options
    const coreAndSuggested = options.filter((t) => t.group === 'core' || t.group === 'suggested')
    // Always include any tags the user already has selected
    const selectedMore = options.filter((t) => t.group === 'more' && film.tags.includes(t.id))
    const combined = [...coreAndSuggested, ...selectedMore]
    return Array.from(new Map(combined.map((t) => [t.id, t])).values())
  }

  const visibleBad = getVisibleTags(badOptions)
  const visibleGood = getVisibleTags(goodOptions)

  const hiddenCount =
    badOptions.length - visibleBad.length + (goodOptions.length - visibleGood.length)

  const toggleTag = (tagId: string) => {
    if (!film.reaction) return
    const isSelected = film.tags.includes(tagId)
    const newTags = isSelected ? film.tags.filter((t) => t !== tagId) : [...film.tags, tagId]
    save.mutate({ reaction: film.reaction, tags: newTags, note: draft })
  }

  const saveNoteText = () => {
    if (film.reaction && draft.trim() !== (film.note ?? '')) {
      save.mutate({ reaction: film.reaction, tags: film.tags, note: draft })
    }
  }

  const isNoteOpen = showNote || Boolean(film.note)

  return (
    <div className={`rounded-xl border border-white/10 bg-white/[0.02] p-4 ${className}`}>
      {/* 2-column split header and chips */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {/* Left column: − The Bad */}
        <div>
          <div className="flex items-center justify-between border-b border-white/5 pb-1.5">
            <span className="text-xs font-semibold text-rose-300">− The Bad</span>
            <span className="text-[11px] tabular-nums text-white/40">
              {badSelected.length}/{badLimit}
            </span>
          </div>
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            {visibleBad.map((tag) => {
              const selected = film.tags.includes(tag.id)
              const disabled =
                !selected && (totalSelected >= MAX_TAGS || badSelected.length >= badLimit)
              return (
                <button
                  key={tag.id}
                  type="button"
                  aria-pressed={selected}
                  disabled={disabled}
                  onClick={() => toggleTag(tag.id)}
                  className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-rose-500/60 disabled:cursor-not-allowed disabled:opacity-35 ${
                    selected
                      ? 'border-rose-500/60 bg-rose-500/20 font-medium text-rose-200'
                      : 'border-white/10 bg-white/5 text-white/70 hover:border-rose-500/30 hover:text-white'
                  }`}
                >
                  <span className="font-bold text-rose-400">{selected ? '✓' : '−'}</span>
                  <span>{tag.label}</span>
                </button>
              )
            })}
          </div>
        </div>

        {/* Right column: + The Good */}
        <div>
          <div className="flex items-center justify-between border-b border-white/5 pb-1.5">
            <span className="text-xs font-semibold text-emerald-300">+ The Good</span>
            <span className="text-[11px] tabular-nums text-white/40">
              {goodSelected.length}/{goodLimit}
            </span>
          </div>
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            {visibleGood.map((tag) => {
              const selected = film.tags.includes(tag.id)
              const disabled =
                !selected && (totalSelected >= MAX_TAGS || goodSelected.length >= goodLimit)
              return (
                <button
                  key={tag.id}
                  type="button"
                  aria-pressed={selected}
                  disabled={disabled}
                  onClick={() => toggleTag(tag.id)}
                  className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-emerald-500/60 disabled:cursor-not-allowed disabled:opacity-35 ${
                    selected
                      ? 'border-emerald-500/60 bg-emerald-500/20 font-medium text-emerald-200'
                      : 'border-white/10 bg-white/5 text-white/70 hover:border-emerald-500/30 hover:text-white'
                  }`}
                >
                  <span className="font-bold text-emerald-400">{selected ? '✓' : '+'}</span>
                  <span>{tag.label}</span>
                </button>
              )
            })}
          </div>
        </div>
      </div>

      {/* Bottom bar: Note trigger and Show All tags toggle */}
      <div className="mt-3.5 flex items-center justify-between border-t border-white/5 pt-2.5 text-xs">
        {!isNoteOpen ? (
          <button
            type="button"
            onClick={() => setShowNote(true)}
            className="font-medium text-white/60 transition-colors hover:text-white"
          >
            + Add a note
          </button>
        ) : (
          <span className="font-medium text-white/40">Your note</span>
        )}

        {hiddenCount > 0 && !showAllTags && (
          <button
            type="button"
            onClick={() => setShowAllTags(true)}
            className="text-white/50 transition-colors hover:text-white"
          >
            Show all tags ({hiddenCount}) ▾
          </button>
        )}
        {showAllTags && (
          <button
            type="button"
            onClick={() => setShowAllTags(false)}
            className="text-white/50 transition-colors hover:text-white"
          >
            Show fewer tags ▴
          </button>
        )}
      </div>

      {/* Note input if open */}
      {isNoteOpen && (
        <div className="mt-2.5">
          <textarea
            value={draft}
            onChange={(e) => setNote(e.target.value)}
            onBlur={saveNoteText}
            maxLength={MAX_NOTE}
            rows={2}
            placeholder={isPositiveReaction ? 'What made it work for you?' : 'What put you off?'}
            className="block w-full resize-none rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs text-white placeholder:text-white/30 focus:border-accent/60 focus:outline-none"
          />
          <div className="mt-1 flex justify-between text-[11px] text-white/40">
            <span>Helps the AI understand your taste</span>
            <span>
              {draft.length}/{MAX_NOTE}
            </span>
          </div>
        </div>
      )}

      {error && <div className="mt-2 text-xs text-rose-400">{error.message}</div>}
    </div>
  )
}

/** RatePicker combined component for backwards compatibility. */
export function RatePicker({
  tmdbId,
  className = '',
}: {
  tmdbId: number
  compact?: boolean
  className?: string
  onRemoved?: () => void
}) {
  return (
    <div className={className}>
      <RatingHeaderDock tmdbId={tmdbId} />
      <SentimentTagsCard tmdbId={tmdbId} className="mt-3" />
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

/** Eye (watched), Thumb down (disliked), Thumb up (liked), or Heart (loved). */
export function ReactionIcon({ reaction, className = '' }: { reaction: Reaction | 'watched'; className?: string }) {
  const stroke = { fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' } as const
  if (reaction === 'watched') {
    return (
      <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
        <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" {...stroke} />
        <circle cx="12" cy="12" r="3" {...stroke} />
      </svg>
    )
  }
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

/** Standard pill badge for a 4-scale personal rating reaction. */
export function ReactionBadge({
  reaction,
  label,
  className = '',
  size = 'sm',
}: {
  reaction: Reaction | 'watched'
  label?: string
  className?: string
  size?: 'xs' | 'sm'
}) {
  const styles: Record<Reaction | 'watched', { badge: string; defaultLabel: string }> = {
    loved: {
      badge: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300',
      defaultLabel: 'Loved',
    },
    liked: {
      badge: 'border-amber-500/20 bg-amber-500/10 text-amber-300',
      defaultLabel: 'Liked',
    },
    disliked: {
      badge: 'border-rose-500/20 bg-rose-500/10 text-rose-300',
      defaultLabel: 'Didn’t like',
    },
    watched: {
      badge: 'border-sky-500/20 bg-sky-500/10 text-sky-300',
      defaultLabel: 'Watched',
    },
  }
  const config = styles[reaction]
  const text = label !== undefined ? label : config.defaultLabel
  const iconSize = size === 'xs' ? 'size-3' : 'size-3.5'
  const padding = size === 'xs' ? 'px-1.5 py-0.5 text-[11px]' : 'px-2 py-0.5 text-xs'

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md border font-medium ${config.badge} ${padding} ${className}`}
    >
      <ReactionIcon reaction={reaction} className={iconSize} />
      {text ? <span>{text}</span> : null}
    </span>
  )
}
