import type { components } from '@iwanttowatch/api-client'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import { api, errorMessage } from './api'
import { Button, ErrorText } from './ui'

export type ClashHypothesis = components['schemas']['ClashHypothesis']

export function ClashPlayground({
  tmdbId,
  clash,
  hypotheses,
  llmConfigured,
  compact = false,
}: {
  tmdbId: number
  clash: string | null | undefined
  hypotheses: ClashHypothesis[] | undefined
  llmConfigured: boolean
  compact?: boolean
}) {
  const queryClient = useQueryClient()
  const list = hypotheses ?? []

  const ask = useMutation({
    mutationFn: async (refresh: boolean) => {
      const { data, error } = await api.POST('/api/v1/titles/{tmdb_id}/clash', {
        params: { path: { tmdb_id: tmdbId }, query: refresh ? { refresh: true } : undefined },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['title', tmdbId], data)
      queryClient.invalidateQueries({ queryKey: ['against-the-grain'] })
      queryClient.invalidateQueries({ queryKey: ['divergent-ratings'] })
    },
  })

  const answerMutation = useMutation({
    mutationFn: async ({
      hypothesisId,
      answer,
    }: {
      hypothesisId: string
      answer: boolean | null
    }) => {
      const { data, error } = await api.POST('/api/v1/titles/{tmdb_id}/clash/{hypothesis_id}', {
        params: { path: { tmdb_id: tmdbId, hypothesis_id: hypothesisId } },
        body: { answer },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['title', tmdbId] })
      queryClient.invalidateQueries({ queryKey: ['against-the-grain'] })
      queryClient.invalidateQueries({ queryKey: ['divergent-ratings'] })
    },
  })

  if (!clash && list.length === 0) {
    if (!llmConfigured) {
      return (
        <p className="text-xs text-white/40">
          Connect AI in{' '}
          <Link to="/settings" className="underline hover:text-white">
            Settings
          </Link>{' '}
          to train your model on this disagreement.
        </p>
      )
    }
    return (
      <div>
        <Button
          variant="ghost"
          className={
            compact
              ? 'w-full border border-white/10 py-1.5 text-xs hover:bg-white/5'
              : 'border border-accent/30 text-accent-strong px-3 py-1 text-xs hover:bg-accent/10'
          }
          onClick={() => ask.mutate(false)}
          disabled={ask.isPending}
        >
          {ask.isPending ? 'Generating hypotheses…' : '⚡ Why did you disagree? Ask AI'}
        </Button>
        {ask.error && (
          <div className="mt-1.5">
            <ErrorText>{ask.error.message}</ErrorText>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-accent/20 bg-accent/5 p-2.5 text-xs text-white/80">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="text-[11px] font-medium tracking-wide uppercase text-accent-strong">
          ⚡ Model playground
        </span>
        <div className="flex items-center gap-1.5">
          {llmConfigured && (
            <button
              type="button"
              onClick={() => ask.mutate(true)}
              disabled={ask.isPending}
              className="cursor-pointer rounded-full border border-white/10 px-2 py-0.5 text-[10px] text-white/55 hover:border-white/25 hover:text-white disabled:opacity-50"
              title="Generate fresh hypotheses"
            >
              {ask.isPending ? 'Refreshing…' : list.length === 0 ? 'Upgrade to Yes/No' : 'Refresh'}
            </button>
          )}
        </div>
      </div>

      {clash && <p className="leading-relaxed text-white/75">{clash}</p>}

      {list.length > 0 && (
        <ul className="mt-2 space-y-2">
          {list.map((h) => {
            const busy =
              answerMutation.isPending && answerMutation.variables?.hypothesisId === h.id
            return (
              <li
                key={h.id}
                className="rounded-md border border-white/10 bg-black/20 p-2"
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="leading-snug text-white/90">{h.question}</span>
                  <div className="flex shrink-0 items-center gap-1">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        answerMutation.mutate({
                          hypothesisId: h.id,
                          answer: h.answer === true ? null : true,
                        })
                      }
                      className={`cursor-pointer rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors ${
                        h.answer === true
                          ? 'border-emerald-400/60 bg-emerald-500/20 text-emerald-200'
                          : 'border-white/15 text-white/60 hover:border-white/30 hover:text-white'
                      }`}
                    >
                      Yes
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        answerMutation.mutate({
                          hypothesisId: h.id,
                          answer: h.answer === false ? null : false,
                        })
                      }
                      className={`cursor-pointer rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors ${
                        h.answer === false
                          ? 'border-rose-400/60 bg-rose-500/20 text-rose-200'
                          : 'border-white/15 text-white/60 hover:border-white/30 hover:text-white'
                      }`}
                    >
                      No
                    </button>
                  </div>
                </div>
                {h.effect && (
                  <p className="mt-1 text-[11px] text-accent-strong/90">✓ {h.effect}</p>
                )}
              </li>
            )
          })}
        </ul>
      )}

      {(ask.error || answerMutation.error) && (
        <div className="mt-1.5">
          <ErrorText>{ask.error?.message || answerMutation.error?.message}</ErrorText>
        </div>
      )}
    </div>
  )
}
