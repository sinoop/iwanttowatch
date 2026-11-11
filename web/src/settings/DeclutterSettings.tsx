import type { DeclutterCandidateItem } from '@iwanttowatch/api-client'
import { useState } from 'react'
import { Link } from 'react-router'
import {
  errorMessage,
  useDeclutterCandidates,
  useDeleteDeclutterCandidates,
  useIgnoreDeclutterCandidate,
  useServerSettings,
} from '../api'
import TitleDialog from '../TitleDialog'
import { Button, ErrorText, Poster } from '../ui'

const CATEGORY_OPTIONS = [
  { id: 'all', label: 'All Candidates', color: 'text-white/70 bg-white/10 border-white/20' },
  { id: 'unplayable', label: 'Unplayable in Jellyfin', color: 'text-purple-400 bg-purple-500/10 border-purple-500/20' },
  { id: 'disliked', label: 'Watched & Disliked', color: 'text-rose-400 bg-rose-500/10 border-rose-500/20' },
  { id: 'abandoned', label: 'Abandoned Play', color: 'text-amber-400 bg-amber-500/10 border-amber-500/20' },
  { id: 'redundant_streamable', label: 'Streaming Redundant', color: 'text-indigo-400 bg-indigo-500/10 border-indigo-500/20' },
  { id: 'low_match', label: 'Low Taste Match', color: 'text-sky-400 bg-sky-500/10 border-sky-500/20' },
] as const

export function DeclutterSettings() {
  const settings = useServerSettings()
  const [selectedCategory, setSelectedCategory] = useState<string>('all')
  const [includeIgnored, setIncludeIgnored] = useState<boolean>(false)
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [confirmModalOpen, setConfirmModalOpen] = useState(false)
  const [deleteFiles, setDeleteFiles] = useState(true)
  const [addImportExclusion, setAddImportExclusion] = useState(false)
  const [actionSuccess, setActionSuccess] = useState<string | null>(null)
  const [openedTitleId, setOpenedTitleId] = useState<number | null>(null)

  const candidates = useDeclutterCandidates(selectedCategory, includeIgnored)
  const deleteMutation = useDeleteDeclutterCandidates()
  const ignoreMutation = useIgnoreDeclutterCandidate()

  const data = candidates.data
  const items = data?.items ?? []
  const radarrConfigured = settings.data?.radarr.configured ?? false
  const jellyfinConfigured =
    Boolean(settings.data?.jellyfin?.url) || (data?.jellyfin_configured ?? false)

  const nonProtected = items.filter((i) => !i.is_protected).map((i) => i.tmdb_id)
  const allSafeSelected =
    nonProtected.length > 0 && nonProtected.every((id) => selectedIds.includes(id))

  const toggleSelect = (tmdbId: number) => {
    setSelectedIds((prev) =>
      prev.includes(tmdbId) ? prev.filter((id) => id !== tmdbId) : [...prev, tmdbId],
    )
  }

  const handleSelectAll = () => {
    if (selectedIds.length > 0) {
      setSelectedIds([])
    } else {
      // Strictly select ONLY safe, non-protected items. Protected items must be explicitly checked individually.
      setSelectedIds(nonProtected)
    }
  }

  const selectedItems = items.filter((i) => selectedIds.includes(i.tmdb_id))
  const selectedBytes = selectedItems.reduce((acc, curr) => acc + curr.size_bytes, 0)
  const selectedFormatted = data ? formatBytes(selectedBytes) : '0 B'

  const handleBatchDelete = async () => {
    if (selectedIds.length === 0) return
    try {
      const res = await deleteMutation.mutateAsync({
        tmdbIds: selectedIds,
        deleteFiles,
        addImportExclusion,
      })
      setActionSuccess(
        `Reclaimed ${res.freed_formatted} by removing ${res.deleted_count} movie(s) from Radarr and disk!`,
      )
      setSelectedIds([])
      setConfirmModalOpen(false)
    } catch {
      // Error is captured in mutation
    }
  }

  const handleSingleDelete = (item: DeclutterCandidateItem) => {
    setSelectedIds([item.tmdb_id])
    setConfirmModalOpen(true)
  }

  const handleToggleIgnore = async (tmdbId: number, currentlyIgnored: boolean) => {
    try {
      await ignoreMutation.mutateAsync({ tmdbId, ignored: !currentlyIgnored })
      setActionSuccess(
        currentlyIgnored
          ? 'Movie restored to declutter analysis.'
          : 'Movie whitelisted. It will not be suggested for deletion.',
      )
    } catch (err) {
      console.error(err)
    }
  }

  return (
    <div className="space-y-6">
      {/* Reclaim KPI Banner */}
      <section className="relative overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-br from-white/[0.04] to-transparent p-6 shadow-xl backdrop-blur-sm">
        <div className="flex flex-col gap-6 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <span className="flex size-7 items-center justify-center rounded-lg bg-accent/20 text-accent font-bold text-sm">
                🧹
              </span>
              <h2 className="text-xl font-bold text-white tracking-tight">Declutter Assistant</h2>
            </div>
            <p className="mt-1.5 max-w-xl text-sm text-white/60 leading-relaxed">
              Identifies movies in your Jellyfin and Radarr storage that you disliked, abandoned, or haven't watched,
              unplayable or missing media files, as well as films now streaming on your subscriptions. Guarded by multi-user household taste protection.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-4 sm:flex-col sm:items-end sm:gap-2">
            <div className="rounded-xl border border-accent/20 bg-accent/10 px-4 py-2.5 text-right">
              <span className="block text-xs font-medium uppercase tracking-wider text-accent-strong">
                Space Reclaimable
              </span>
              <span className="text-2xl font-black text-white sm:text-3xl">
                {data?.reclaimable_formatted ?? '0 B'}
              </span>
            </div>
            {data && data.protected_count > 0 && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-500/15 px-3 py-1 text-xs font-semibold text-amber-300 border border-amber-500/30">
                🛡️ {data.protected_count} household protected
              </span>
            )}
          </div>
        </div>

        {!radarrConfigured && (
          <div className="mt-6 flex items-center justify-between rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-xs text-amber-200">
            <span>
              Radarr is not connected. Connect Radarr to measure exact file sizes on disk and trigger automated file deletions.
            </span>
            <Link
              to="/settings/integrations"
              className="ml-4 shrink-0 rounded-lg bg-amber-500/20 px-3 py-1.5 font-semibold text-amber-100 hover:bg-amber-500/30"
            >
              Connect Radarr →
            </Link>
          </div>
        )}

        {!jellyfinConfigured && radarrConfigured && (
          <div className="mt-4 flex items-center justify-between rounded-xl border border-indigo-500/30 bg-indigo-500/10 p-4 text-xs text-indigo-200">
            <span>
              Jellyfin is not connected. Connect Jellyfin to detect unplayable or missing media files and sync playback history.
            </span>
            <Link
              to="/settings/integrations"
              className="ml-4 shrink-0 rounded-lg bg-indigo-500/20 px-3 py-1.5 font-semibold text-indigo-100 hover:bg-indigo-500/30"
            >
              Connect Jellyfin →
            </Link>
          </div>
        )}
      </section>

      {/* Success Banner */}
      {actionSuccess && (
        <div className="flex items-center justify-between rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4 text-sm text-emerald-200">
          <span>✓ {actionSuccess}</span>
          <button
            type="button"
            onClick={() => setActionSuccess(null)}
            className="text-xs text-emerald-300 hover:text-white"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Category Filter & Options */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/[0.02] p-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 text-xs">
            <label htmlFor="declutter-category-filter" className="font-medium text-white/50">
              Filter by category:
            </label>
            <select
              id="declutter-category-filter"
              value={selectedCategory}
              onChange={(e) => {
                setSelectedCategory(e.target.value)
                setSelectedIds([])
              }}
              className="cursor-pointer rounded-lg border border-white/10 bg-[#12161f] px-3 py-1.5 text-xs font-semibold text-white transition focus:border-accent focus:outline-none"
            >
              {CATEGORY_OPTIONS.map((cat) => {
                const count =
                  cat.id === 'all'
                    ? (data?.total_candidates ?? 0)
                    : (data?.categories_summary[cat.id]?.count ?? 0)
                const formattedBytes =
                  cat.id !== 'all' ? data?.categories_summary[cat.id]?.formatted : null
                const sizeSuffix =
                  formattedBytes && formattedBytes !== '0 B' ? ` · ${formattedBytes}` : ''
                return (
                  <option key={cat.id} value={cat.id} className="bg-[#151922] text-white">
                    {cat.label} ({count}{sizeSuffix})
                  </option>
                )
              })}
            </select>
          </div>

          {selectedCategory !== 'all' && (
            <span
              className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-medium border ${
                CATEGORY_OPTIONS.find((c) => c.id === selectedCategory)?.color ??
                'text-white/70 border-white/10 bg-white/5'
              }`}
            >
              <span>{CATEGORY_OPTIONS.find((c) => c.id === selectedCategory)?.label}</span>
              <button
                type="button"
                onClick={() => {
                  setSelectedCategory('all')
                  setSelectedIds([])
                }}
                className="ml-1 cursor-pointer text-white/40 hover:text-white"
                title="Reset to All Candidates"
                aria-label="Reset to All Candidates"
              >
                ✕
              </button>
            </span>
          )}
        </div>

        <div className="flex items-center gap-3 text-xs text-white/60">
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={includeIgnored}
              onChange={(e) => setIncludeIgnored(e.target.checked)}
              className="size-4 rounded border-white/20 bg-black/40 text-accent focus:ring-accent/40"
            />
            <span>Show whitelisted ({includeIgnored ? 'active' : 'hidden'})</span>
          </label>
        </div>
      </div>

      {/* Bulk Action Bar */}
      {items.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-white/10 bg-white/[0.02] px-4 py-3">
          <div className="flex items-center gap-3 text-sm">
            <input
              type="checkbox"
              checked={allSafeSelected}
              onChange={handleSelectAll}
              disabled={nonProtected.length === 0}
              className="size-4 rounded border-white/20 bg-black/40 text-accent focus:ring-accent/40"
              title={allSafeSelected ? 'Clear selection' : 'Select all safe (unprotected) candidates'}
            />
            <span className="text-white/80">
              {selectedIds.length > 0 ? (
                <>
                  <strong className="text-white">{selectedIds.length}</strong> selected (
                  <span className="text-accent font-semibold">{selectedFormatted}</span>)
                  {selectedItems.some((i) => i.is_protected) && (
                    <span className="ml-2 inline-flex items-center gap-1 rounded bg-amber-500/15 px-2 py-0.5 text-xs text-amber-300 border border-amber-500/30">
                      ⚠️ Includes protected
                    </span>
                  )}
                </>
              ) : (
                <>
                  Select safe candidates to clean{' '}
                  {items.some((i) => i.is_protected) && (
                    <span className="text-xs text-white/40">
                      ({nonProtected.length} safe, {items.length - nonProtected.length} protected excluded)
                    </span>
                  )}
                </>
              )}
            </span>
          </div>

          <div className="flex items-center gap-2">
            {selectedIds.length > 0 && (
              <Button
                variant="ghost"
                onClick={() => setSelectedIds([])}
                className="px-3 py-1.5 text-xs text-white/60 hover:text-white"
              >
                Clear selection
              </Button>
            )}
            <Button
              disabled={selectedIds.length === 0 || !radarrConfigured}
              onClick={() => setConfirmModalOpen(true)}
              className="bg-rose-500 hover:bg-rose-600 text-white text-xs px-3.5 py-1.5 font-semibold"
            >
              Clean selected ({selectedFormatted})
            </Button>
          </div>
        </div>
      )}

      {/* Candidate List */}
      {candidates.isPending ? (
        <div className="flex h-48 items-center justify-center text-sm text-white/50">
          Scanning library and analyzing taste signals…
        </div>
      ) : items.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-white/15 p-12 text-center text-sm text-white/60">
          <span className="block text-4xl mb-3">✨</span>
          <p className="font-semibold text-white">Your library is in great shape!</p>
          <p className="mt-1 text-white/50 max-w-md mx-auto">
            {selectedCategory === 'unplayable'
              ? 'No unplayable or missing items found. All downloaded movies in Radarr are recognized and playable in Jellyfin.'
              : 'No prune candidates found for this category. Movies in your library have positive taste affinity or are cherished by household members.'}
          </p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-1 lg:grid-cols-2">
          {items.map((item) => {
            const isSelected = selectedIds.includes(item.tmdb_id)
            const catMeta = CATEGORY_OPTIONS.find((t) => t.id === item.category)

            return (
              <div
                key={item.tmdb_id}
                className={`relative flex gap-3.5 sm:gap-4 rounded-xl border p-3.5 sm:p-4 transition-all overflow-hidden ${
                  item.is_protected
                    ? 'border-amber-500/30 bg-amber-500/[0.03]'
                    : isSelected
                      ? 'border-accent/40 bg-accent/[0.04]'
                      : 'border-white/10 bg-white/[0.02] hover:border-white/20'
                }`}
              >
                {/* Poster with overlay checkbox */}
                <div className="relative shrink-0 w-16 sm:w-20 self-start">
                  <button
                    type="button"
                    onClick={() => setOpenedTitleId(item.tmdb_id)}
                    className="group block w-full text-left cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded-lg"
                    aria-label={`View details for ${item.title}`}
                  >
                    <Poster
                      path={item.poster_path}
                      title={item.title}
                      className="transition-shadow group-hover:ring-2 group-hover:ring-accent"
                    />
                  </button>
                  <label
                    className="absolute top-1.5 left-1.5 z-10 flex items-center justify-center size-5 rounded bg-black/80 backdrop-blur-sm border border-white/30 cursor-pointer hover:border-white/60 transition-colors shadow-sm"
                    title={isSelected ? 'Deselect movie' : 'Select movie'}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleSelect(item.tmdb_id)}
                      className="size-3.5 rounded border-white/20 bg-black/60 text-accent focus:ring-accent/40"
                    />
                  </label>
                </div>

                <div className="flex min-w-0 flex-1 flex-col justify-between">
                  <div className="min-w-0">
                    {/* Top meta row: Category pill on the left, Reclaimable Size on the right */}
                    <div className="flex items-center justify-between gap-2 mb-1">
                      {catMeta && 'color' in catMeta ? (
                        <span
                          className={`inline-block rounded-md border px-2 py-0.5 text-[10px] font-semibold truncate ${catMeta.color}`}
                        >
                          {catMeta.label}
                        </span>
                      ) : (
                        <span />
                      )}
                      <span className="shrink-0 text-xs font-bold text-accent font-mono">
                        {item.size_formatted}
                      </span>
                    </div>

                    {/* Movie Title: full width, readable, wraps cleanly without clipping */}
                    <h3 className="font-bold text-white text-base leading-snug break-words">
                      <button
                        type="button"
                        onClick={() => setOpenedTitleId(item.tmdb_id)}
                        className="cursor-pointer text-left hover:text-accent transition-colors focus-visible:outline-none focus-visible:underline"
                        title={item.title}
                      >
                        {item.title}
                      </button>
                    </h3>

                    {/* Subtitle details: Year, Language, IMDb badge, Match % */}
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 mt-1 text-xs text-white/50">
                      {item.year && <span>{item.year}</span>}
                      {item.original_language && (
                        <span className="uppercase font-medium">{item.original_language}</span>
                      )}
                      {item.imdb_rating && (
                        <span className="inline-flex items-center gap-1 font-semibold text-amber-400">
                          ★ {item.imdb_rating.toFixed(1)}
                        </span>
                      )}
                      {item.match_pct !== null && (
                        <span className="text-white/70">Match {item.match_pct}%</span>
                      )}
                    </div>

                    {/* Reasons list */}
                    <div className="mt-2.5 space-y-1">
                      {item.reasons.map((reason, idx) => (
                        <p key={idx} className="flex items-start gap-1.5 text-xs text-white/70 leading-relaxed">
                          <span className="text-rose-400 font-bold shrink-0 mt-0.5">•</span>
                          <span className="break-words">{reason}</span>
                        </p>
                      ))}
                    </div>

                    {/* Household Protection Guardrail */}
                    {item.is_protected && (
                      <div className="mt-2.5 rounded-lg border border-amber-500/30 bg-amber-500/10 p-2 text-xs text-amber-200">
                        <div className="flex items-center gap-1.5 font-semibold text-amber-300">
                          <span>🛡️</span>
                          <span>Household Protected</span>
                        </div>
                        <ul className="mt-1 list-disc pl-4 text-[11px] text-amber-100/80 space-y-0.5">
                          {item.protection_reasons.map((pr, idx) => (
                            <li key={idx} className="break-words">{pr}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>

                  {/* Actions */}
                  <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-white/10 pt-3 text-xs">
                    <button
                      type="button"
                      onClick={() => handleToggleIgnore(item.tmdb_id, item.is_ignored)}
                      className="text-white/50 underline-offset-2 hover:text-white hover:underline transition-colors"
                    >
                      {item.is_ignored ? 'Un-whitelist' : 'Keep / Whitelist'}
                    </button>

                    <div className="flex items-center gap-2">
                      <Button
                        variant="ghost"
                        disabled={!radarrConfigured || deleteMutation.isPending}
                        onClick={() => handleSingleDelete(item)}
                        className="px-2.5 py-1 text-xs text-rose-300 hover:bg-rose-500/15 hover:text-rose-100"
                      >
                        Delete from Radarr
                      </Button>
                    </div>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Confirmation Modal */}
      {confirmModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm animate-fade-in">
          <div className="w-full max-w-lg rounded-2xl border border-white/15 bg-[#121216] p-6 shadow-2xl">
            <div className="flex items-center gap-3 text-rose-400">
              <span className="flex size-9 items-center justify-center rounded-xl bg-rose-500/20 text-lg">
                ⚠️
              </span>
              <div>
                <h3 className="text-lg font-bold text-white">Confirm Storage Deletion</h3>
                <p className="text-xs text-white/50">
                  Permanently prune selected media from your server
                </p>
              </div>
            </div>

            <div className="mt-4 rounded-xl border border-rose-500/20 bg-rose-500/10 p-3.5 text-xs text-rose-200 leading-relaxed">
              You are about to remove <strong>{selectedItems.length} movie(s)</strong> and reclaim{' '}
              <strong className="text-white">{selectedFormatted}</strong> of disk space.
            </div>

            {selectedItems.some((i) => i.is_protected) && (
              <div className="mt-3 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-200">
                ⚠️ <strong>Warning:</strong> One or more selected titles are protected because another household
                member shortlisted, favorited, or has a high match for them!
              </div>
            )}

            <div className="mt-4 max-h-48 overflow-y-auto rounded-lg border border-white/10 bg-black/40 p-3 text-xs space-y-1.5 scrollbar-thin">
              {selectedItems.map((item) => (
                <div key={item.tmdb_id} className="flex items-center justify-between gap-2 text-white/80">
                  <span className="truncate">
                    {item.title} {item.year ? `(${item.year})` : ''}
                  </span>
                  <span className="shrink-0 text-white/50 font-mono text-[11px]">
                    {item.size_formatted}
                  </span>
                </div>
              ))}
            </div>

            <div className="mt-4 space-y-2 border-t border-white/10 pt-4 text-xs text-white/70">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={deleteFiles}
                  onChange={(e) => setDeleteFiles(e.target.checked)}
                  className="size-4 rounded border-white/20 bg-black/40 text-rose-500 focus:ring-rose-500/40"
                />
                <span>Delete physical movie files from disk (reclaims storage)</span>
              </label>

              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={addImportExclusion}
                  onChange={(e) => setAddImportExclusion(e.target.checked)}
                  className="size-4 rounded border-white/20 bg-black/40 text-accent focus:ring-accent/40"
                />
                <span>Add to Radarr import exclusion list (prevents re-downloading)</span>
              </label>
            </div>

            {deleteMutation.error && (
              <div className="mt-3">
                <ErrorText>{errorMessage(deleteMutation.error)}</ErrorText>
              </div>
            )}

            <div className="mt-6 flex items-center justify-end gap-3 border-t border-white/10 pt-4">
              <Button
                variant="ghost"
                onClick={() => setConfirmModalOpen(false)}
                disabled={deleteMutation.isPending}
              >
                Cancel
              </Button>
              <Button
                onClick={handleBatchDelete}
                disabled={deleteMutation.isPending}
                className="bg-rose-600 hover:bg-rose-700 text-white font-bold px-4 py-2"
              >
                {deleteMutation.isPending ? 'Deleting…' : `Permanently Delete (${selectedFormatted})`}
              </Button>
            </div>
          </div>
        </div>
      )}
      <TitleDialog tmdbId={openedTitleId} onClose={() => setOpenedTitleId(null)} />
    </div>
  )
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const kb = bytes / 1024
  if (kb < 1024) return `${kb.toFixed(1)} KB`
  const mb = kb / 1024
  if (mb < 1024) return `${mb.toFixed(1)} MB`
  const gb = mb / 1024
  return `${gb.toFixed(1)} GB`
}
