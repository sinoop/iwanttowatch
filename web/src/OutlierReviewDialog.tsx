import type { OutlierTitle, Reaction } from '@iwanttowatch/api-client'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api, errorMessage, refreshAfterReaction } from './api'
import { ReactionBadge, ReactionIcon } from './RateDialog'
import { MatchBadge } from './TitleDialog'
import { Button, ErrorText, Poster } from './ui'

const MAX_TAGS = 3
const languageName = new Intl.DisplayNames(['en'], { type: 'language' })

export default function OutlierReviewDialog({
  isOpen,
  onClose,
  onSelectFilm,
}: {
  isOpen: boolean
  onClose: () => void
  onSelectFilm?: (tmdbId: number) => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const queryClient = useQueryClient()

  const handleClose = () => {
    queryClient.invalidateQueries({ queryKey: ['outlier-ratings'] })
    queryClient.invalidateQueries({ queryKey: ['ratings'] })
    queryClient.invalidateQueries({ queryKey: ['taste-summary'] })
    queryClient.invalidateQueries({ queryKey: ['persona'] })
    queryClient.invalidateQueries({ queryKey: ['feed'] })
    onClose()
  }

  useEffect(() => {
    if (isOpen) dialog.current?.showModal()
    else dialog.current?.close()
  }, [isOpen])

  return (
    <dialog
      ref={dialog}
      onClose={handleClose}
      onClick={(e) => e.target === dialog.current && handleClose()}
      aria-label="Review Outliers"
      className="m-auto w-[min(38rem,calc(100vw-2rem))] rounded-2xl border border-white/10 bg-[#11141b] p-0 text-[#e7e9ee] shadow-2xl backdrop:bg-black/75"
    >
      {isOpen && <OutlierReviewContent onClose={handleClose} onSelectFilm={onSelectFilm} />}
    </dialog>
  )
}

function OutlierReviewContent({
  onClose,
  onSelectFilm,
}: {
  onClose: () => void
  onSelectFilm?: (tmdbId: number) => void
}) {
  const outliersQuery = useQuery({
    queryKey: ['outlier-ratings'],
    queryFn: async () => (await api.GET('/api/v1/ratings/outliers')).data,
    refetchOnWindowFocus: false,
  })

  if (outliersQuery.isLoading) {
    return (
      <div className="flex flex-col items-center justify-center p-12 text-center">
        <span className="size-6 animate-spin rounded-full border-2 border-accent border-t-transparent" />
        <p className="mt-4 text-sm text-white/60">Scanning for taste deviations and outliers…</p>
      </div>
    )
  }

  const initialItems = outliersQuery.data?.items ?? []
  const totalCount = outliersQuery.data?.total ?? initialItems.length

  if (initialItems.length === 0) {
    return (
      <div className="p-8 text-center">
        <span className="text-4xl">🎉</span>
        <h2 className="mt-3 text-lg font-semibold text-white">No Taste Outliers Found</h2>
        <p className="mx-auto mt-2 max-w-sm text-sm text-white/60">
          Your ratings align closely with our recommender’s predictions, and all your top favorites have clear feedback!
        </p>
        <div className="mt-6">
          <Button onClick={onClose}>Done</Button>
        </div>
      </div>
    )
  }

  return (
    <OutlierReviewSession
      initialItems={initialItems}
      totalCount={totalCount}
      onClose={onClose}
      onSelectFilm={onSelectFilm}
    />
  )
}

function OutlierReviewSession({
  initialItems,
  totalCount,
  onClose,
  onSelectFilm,
}: {
  initialItems: OutlierTitle[]
  totalCount: number
  onClose: () => void
  onSelectFilm?: (tmdbId: number) => void
}) {
  const [items, setItems] = useState<OutlierTitle[]>(initialItems)
  const [index, setIndex] = useState(0)

  const current: OutlierTitle | undefined = items[index]

  const handleItemUpdated = (tmdbId: number, reaction: Reaction, tags: string[]) => {
    setItems((prev) =>
      prev.map((it) => (it.tmdb_id === tmdbId ? { ...it, reaction, tags } : it)),
    )
  }

  const handleNext = () => {
    if (index < items.length - 1) {
      setIndex((i) => i + 1)
    } else {
      onClose()
    }
  }

  const handlePrev = () => {
    if (index > 0) setIndex((i) => i - 1)
  }

  if (!current) return null

  return (
    <div className="flex flex-col p-5 sm:p-6">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-white/10 pb-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-base font-bold text-white">Review Outliers</span>
            <span className="rounded-full bg-accent/20 px-2.5 py-0.5 text-xs font-semibold text-accent-strong">
              {index + 1} of {items.length}
            </span>
            {totalCount > items.length && (
              <span className="rounded-full bg-white/10 px-2 py-0.5 text-xs text-white/60">
                Top {items.length} of {totalCount} total
              </span>
            )}
          </div>
          <p className="mt-0.5 text-xs text-white/50">
            {totalCount > items.length
              ? `Reviewing the top ${items.length} most divergent ratings in this batch.`
              : 'Ratings that differed widely from what our recommender calculated.'}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg p-1.5 text-white/50 hover:bg-white/10 hover:text-white cursor-pointer"
          aria-label="Close"
        >
          ✕
        </button>
      </div>

      <OutlierCard
        key={current.tmdb_id}
        item={current}
        index={index}
        total={items.length}
        totalCount={totalCount}
        onPrev={handlePrev}
        onNext={handleNext}
        onItemUpdated={handleItemUpdated}
        onSelectFilm={onSelectFilm}
      />
    </div>
  )
}

function OutlierCard({
  item,
  index,
  total,
  totalCount,
  onPrev,
  onNext,
  onItemUpdated,
  onSelectFilm,
}: {
  item: OutlierTitle
  index: number
  total: number
  totalCount: number
  onPrev: () => void
  onNext: () => void
  onItemUpdated: (tmdbId: number, reaction: Reaction, tags: string[]) => void
  onSelectFilm?: (tmdbId: number) => void
}) {
  const queryClient = useQueryClient()
  const [activeReaction, setActiveReaction] = useState<Reaction>((item.reaction as Reaction) || 'liked')
  const [activeTags, setActiveTags] = useState<string[]>(item.tags || [])
  const [statusMessage, setStatusMessage] = useState<string | null>(null)
  const [isConfirmed, setIsConfirmed] = useState(false)
  const [isCleared, setIsCleared] = useState(false)

  const showOriginal = item.original_title && item.original_title !== item.title
  const isPositive = activeReaction !== 'disliked'
  const tagOptions = isPositive ? item.liked_tags : item.disliked_tags

  const clearRatingMutation = useMutation({
    mutationFn: async () => {
      const { error } = await api.POST('/api/v1/titles/{tmdb_id}/clear-rating', {
        params: { path: { tmdb_id: item.tmdb_id } },
      })
      if (error) throw new Error(errorMessage(error))
    },
    onSuccess: () => {
      refreshAfterReaction(queryClient, item.tmdb_id)
      setIsCleared(true)
      setIsConfirmed(true)
      setStatusMessage('Rating cleared! Kept as watched.')
      setTimeout(() => setStatusMessage(null), 3000)
    },
  })

  const confirmMutation = useMutation({
    mutationFn: async () => {
      const { error } = await api.POST('/api/v1/ratings/outliers/{tmdb_id}/confirm', {
        params: { path: { tmdb_id: item.tmdb_id } },
      })
      if (error) throw new Error(errorMessage(error))
    },
  })

  const saveMutation = useMutation({
    mutationFn: async ({
      reaction,
      tags,
    }: {
      reaction: Reaction
      tags: string[]
    }) => {
      const { data, error } = await api.PUT('/api/v1/titles/{tmdb_id}/reaction', {
        params: { path: { tmdb_id: item.tmdb_id } },
        body: { reaction, tags, note: item.note ?? '' },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (_, vars) => {
      // Refresh general ratings cache, but avoid invalidating outlier-ratings during active review session
      refreshAfterReaction(queryClient, item.tmdb_id)
      onItemUpdated(item.tmdb_id, vars.reaction, vars.tags)
    },
  })

  const handleSetReaction = (reaction: Reaction) => {
    setActiveReaction(reaction)
    const nextPositive = reaction !== 'disliked'
    const allowedTags = nextPositive ? item.liked_tags : item.disliked_tags
    const nextTags = activeTags.filter((t) => allowedTags.some((at) => at.id === t))
    setActiveTags(nextTags)
    saveMutation.mutate({ reaction, tags: nextTags })
  }

  const handleConfirmOpinion = (reaction: Reaction, message = 'Opinion confirmed!') => {
    setIsConfirmed(true)
    setStatusMessage(message)
    setTimeout(() => setStatusMessage(null), 3000)
    confirmMutation.mutate()
    handleSetReaction(reaction)
  }

  const handleToggleTag = (tagId: string) => {
    const next = activeTags.includes(tagId)
      ? activeTags.filter((t) => t !== tagId)
      : activeTags.length < MAX_TAGS
      ? [...activeTags, tagId]
      : activeTags
    setActiveTags(next)
    saveMutation.mutate({ reaction: activeReaction, tags: next })
    confirmMutation.mutate()
    setIsConfirmed(true)
    setStatusMessage('Saved tags!')
    setTimeout(() => setStatusMessage(null), 2500)
  }

  return (
    <>
      {/* Movie info card */}
      <div className="mt-4 flex gap-4 rounded-xl border border-white/10 bg-white/[0.02] p-4">
        <div className="w-16 shrink-0 sm:w-20">
          <button
            type="button"
            onClick={() => onSelectFilm?.(item.tmdb_id)}
            className="group block w-full cursor-pointer focus-visible:outline-none"
          >
            <Poster
              path={item.poster_path}
              title={item.title}
              className="group-hover:ring-2 group-hover:ring-accent/70"
            />
          </button>
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <div>
              <button
                type="button"
                onClick={() => onSelectFilm?.(item.tmdb_id)}
                className="text-left font-semibold text-white hover:text-accent cursor-pointer truncate block"
                title={item.title}
              >
                {item.title}
              </button>
              <p className="text-xs text-white/50">
                {[item.year, showOriginal ? item.original_title : languageName.of(item.original_language)]
                  .filter(Boolean)
                  .join(' · ')}
              </p>
            </div>
            {statusMessage && (
              <span className="flex items-center gap-1 rounded-md bg-emerald-500/20 px-2 py-0.5 text-xs font-medium text-emerald-300 animate-fade-in">
                <span>✓</span>
                <span>{statusMessage}</span>
              </span>
            )}
          </div>

          {item.genres.length > 0 && (
            <p className="mt-1 text-xs text-white/40 truncate">{item.genres.join(', ')}</p>
          )}

          {/* Side by side comparison */}
          <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
            <div className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5">
              <span className="text-white/50">Predicted match:</span>
              <MatchBadge match={item.predicted_match} className="scale-75 origin-left" />
            </div>

            <div className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5">
              <span className="text-white/50">You rated:</span>
              {isCleared ? (
                <span className="text-xs text-white/50 italic">Cleared (Kept watched)</span>
              ) : (
                <>
                  <ReactionBadge reaction={activeReaction} size="xs" />
                  <span className="font-semibold text-white">({item.user_rating.toFixed(1)}/10)</span>
                </>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Question Context Banner */}
      <div className="mt-4">
        {item.outlier_type === 'loved_rewatch' ? (
          <div className="rounded-xl border border-accent/30 bg-accent/10 p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm font-semibold text-accent-strong">
                <span>❤️ Rewatch check</span>
              </div>
              {isConfirmed && (
                <span className="flex items-center gap-1 rounded-full bg-emerald-500/20 px-2 py-0.5 text-xs font-medium text-emerald-300">
                  <span>✓</span>
                  <span>Confirmed</span>
                </span>
              )}
            </div>
            <p className="mt-1 text-sm text-white/90">
              You marked this movie <strong>Loved</strong>, but our recommender expected a{' '}
              <strong>{item.predicted_match}% match</strong>.
            </p>
            <p className="mt-2 text-sm font-medium text-white">
              Would you really watch this movie again?
            </p>
            <div className="mt-3 flex flex-wrap gap-2.5">
              <Button
                variant={activeReaction === 'liked' ? 'primary' : 'ghost'}
                className={`text-xs py-2 ${
                  activeReaction === 'liked'
                    ? 'border-accent bg-accent/20 text-accent font-semibold'
                    : 'border-white/15 bg-white/5 text-white/80 hover:bg-white/10'
                }`}
                onClick={() => handleConfirmOpinion('liked', 'Rating changed to Liked!')}
              >
                <ReactionIcon reaction="liked" className="h-3.5" />
                <span>No, once was enough (Change to Liked)</span>
              </Button>
              <Button
                variant={activeReaction === 'loved' ? 'primary' : 'ghost'}
                className={`text-xs py-2 ${
                  activeReaction === 'loved'
                    ? 'border-emerald-500/50 bg-emerald-500/20 text-emerald-300 font-semibold'
                    : 'border-white/15 bg-white/5 text-white/80 hover:bg-white/10'
                }`}
                onClick={() => handleConfirmOpinion('loved', 'Opinion confirmed! Kept Loved.')}
              >
                <ReactionIcon reaction="loved" className="h-3.5" />
                <span>Yes, I'd watch it again! (Keep Loved)</span>
              </Button>
            </div>
            <div className="mt-3.5 flex items-center justify-between border-t border-white/10 pt-2.5">
              <span className="text-xs text-white/50">Don't remember this movie?</span>
              <button
                type="button"
                onClick={() => clearRatingMutation.mutate()}
                disabled={clearRatingMutation.isPending || isCleared}
                className="cursor-pointer text-xs font-medium text-white/70 hover:text-rose-300 underline decoration-white/20 underline-offset-2 transition-colors disabled:opacity-50"
              >
                {isCleared ? '✓ Rating cleared (kept watched)' : 'Clear rating, keep as watched'}
              </button>
            </div>
          </div>
        ) : item.outlier_type === 'predicted_dislike_user_liked' ? (
          <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm font-semibold text-amber-300">
                <span>⚡ Unexpected favorite</span>
              </div>
              {isConfirmed && (
                <span className="flex items-center gap-1 rounded-full bg-emerald-500/20 px-2 py-0.5 text-xs font-medium text-emerald-300">
                  <span>✓</span>
                  <span>Confirmed</span>
                </span>
              )}
            </div>
            <p className="mt-1 text-sm text-white/90">
              Our recommender thought this wouldn't suit your taste (predicted{' '}
              <strong>{item.predicted_match}% match</strong>), but your rating is <strong>Liked</strong>.
            </p>
            <p className="mt-2 text-sm font-medium text-white">
              Did you genuinely enjoy it, or should it be a Disliked movie?
            </p>
            <div className="mt-3 flex flex-wrap gap-2.5">
              <Button
                variant={activeReaction === 'disliked' ? 'primary' : 'ghost'}
                className={`text-xs py-2 ${
                  activeReaction === 'disliked'
                    ? 'border-red-500/50 bg-red-500/20 text-red-300 font-semibold'
                    : 'border-white/15 bg-white/5 text-white/80 hover:bg-white/10'
                }`}
                onClick={() => handleConfirmOpinion('disliked', 'Lowered to Didn’t like!')}
              >
                <ReactionIcon reaction="disliked" className="h-3.5" />
                <span>Actually, didn't like it (Lower to Didn't like)</span>
              </Button>
              <Button
                variant={activeReaction === 'liked' ? 'primary' : 'ghost'}
                className={`text-xs py-2 ${
                  activeReaction === 'liked'
                    ? 'border-accent bg-accent/20 text-accent font-semibold'
                    : 'border-white/15 bg-white/5 text-white/80 hover:bg-white/10'
                }`}
                onClick={() => handleConfirmOpinion('liked', 'Opinion confirmed! Kept Liked.')}
              >
                <ReactionIcon reaction="liked" className="h-3.5" />
                <span>I genuinely liked it (Keep Liked)</span>
              </Button>
            </div>
            <div className="mt-3.5 flex items-center justify-between border-t border-white/10 pt-2.5">
              <span className="text-xs text-white/50">Don't remember this movie?</span>
              <button
                type="button"
                onClick={() => clearRatingMutation.mutate()}
                disabled={clearRatingMutation.isPending || isCleared}
                className="cursor-pointer text-xs font-medium text-white/70 hover:text-rose-300 underline decoration-white/20 underline-offset-2 transition-colors disabled:opacity-50"
              >
                {isCleared ? '✓ Rating cleared (kept watched)' : 'Clear rating, keep as watched'}
              </button>
            </div>
          </div>
        ) : (
          <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm font-semibold text-rose-300">
                <span>💔 Unexpected dislike</span>
              </div>
              {isConfirmed && (
                <span className="flex items-center gap-1 rounded-full bg-emerald-500/20 px-2 py-0.5 text-xs font-medium text-emerald-300">
                  <span>✓</span>
                  <span>Confirmed</span>
                </span>
              )}
            </div>
            <p className="mt-1 text-sm text-white/90">
              Based on your taste in similar movies, we predicted a strong{' '}
              <strong>{item.predicted_match}% match</strong>, but you disliked it.
            </p>
            <p className="mt-2 text-sm font-medium text-white">
              Tell us what went wrong so we know what to avoid:
            </p>
            <div className="mt-3 flex flex-wrap gap-2.5">
              <Button
                variant={activeReaction === 'disliked' ? 'primary' : 'ghost'}
                className={`text-xs py-2 ${
                  activeReaction === 'disliked'
                    ? 'border-red-500/50 bg-red-500/20 text-red-300 font-semibold'
                    : 'border-white/15 bg-white/5 text-white/80 hover:bg-white/10'
                }`}
                onClick={() => handleConfirmOpinion('disliked', 'Opinion confirmed! Kept Didn’t like.')}
              >
                <ReactionIcon reaction="disliked" className="h-3.5" />
                <span>Confirm Didn't like (select reasons below)</span>
              </Button>
              <Button
                variant={activeReaction === 'liked' ? 'primary' : 'ghost'}
                className={`text-xs py-2 ${
                  activeReaction === 'liked'
                    ? 'border-accent bg-accent/20 text-accent font-semibold'
                    : 'border-white/15 bg-white/5 text-white/80 hover:bg-white/10'
                }`}
                onClick={() => handleConfirmOpinion('liked', 'Raised to Liked!')}
              >
                <ReactionIcon reaction="liked" className="h-3.5" />
                <span>I actually liked it (Raise to Liked)</span>
              </Button>
            </div>
            <div className="mt-3.5 flex items-center justify-between border-t border-white/10 pt-2.5">
              <span className="text-xs text-white/50">Don't remember this movie?</span>
              <button
                type="button"
                onClick={() => clearRatingMutation.mutate()}
                disabled={clearRatingMutation.isPending || isCleared}
                className="cursor-pointer text-xs font-medium text-white/70 hover:text-rose-300 underline decoration-white/20 underline-offset-2 transition-colors disabled:opacity-50"
              >
                {isCleared ? '✓ Rating cleared (kept watched)' : 'Clear rating, keep as watched'}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Tags section */}
      {isCleared ? (
        <div className="mt-5 rounded-xl border border-white/10 bg-white/[0.02] p-4 text-center">
          <p className="text-xs text-white/60">
            Rating removed from taste modeling. Film remains marked as watched in your library.
          </p>
        </div>
      ) : (
        <div className="mt-5 rounded-xl border border-white/10 bg-white/[0.02] p-4">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold uppercase tracking-wider text-white/70">
              {isPositive ? 'What worked best for you?' : 'What didn’t work?'}
            </p>
            <span className="text-xs text-white/40">
              {activeTags.length} of {MAX_TAGS} selected
            </span>
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            {tagOptions.map((tag) => {
              const selected = activeTags.includes(tag.id)
              return (
                <button
                  key={tag.id}
                  type="button"
                  onClick={() => handleToggleTag(tag.id)}
                  disabled={!selected && activeTags.length >= MAX_TAGS}
                  className={`cursor-pointer rounded-full border px-3 py-1 text-xs transition-colors focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-30 ${
                    selected
                      ? isPositive
                        ? 'border-accent bg-accent/20 font-semibold text-accent-strong'
                        : 'border-red-500 bg-red-500/20 font-semibold text-red-200'
                      : 'border-white/10 text-white/70 hover:border-white/25 hover:text-white'
                  }`}
                >
                  {tag.label}
                </button>
              )
            })}
          </div>
        </div>
      )}

      {saveMutation.error && (
        <div className="mt-3">
          <ErrorText>{saveMutation.error.message}</ErrorText>
        </div>
      )}

      {/* Navigation Footer */}
      <div className="mt-6 flex items-center justify-between border-t border-white/10 pt-4">
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            onClick={onPrev}
            disabled={index === 0}
            className="text-xs py-1.5"
          >
            ← Previous
          </Button>
          <Button
            variant="ghost"
            onClick={onNext}
            className="text-xs py-1.5 text-white/60 hover:text-white"
          >
            Skip
          </Button>
        </div>

        <div className="flex items-center gap-2">
          <Button onClick={onNext} className="text-xs py-1.5">
            {index < total - 1
              ? 'Next Outlier →'
              : totalCount > total
              ? `Finish Batch (${total} of ${totalCount})`
              : 'Finish & Close'}
          </Button>
        </div>
      </div>
    </>
  )
}
