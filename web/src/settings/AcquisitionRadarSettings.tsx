import type { AutoDownloadConfig, RadarItem } from '@iwanttowatch/api-client'
import { useState } from 'react'
import { Link } from 'react-router'
import {
  errorMessage,
  formatReleaseDate,
  useRadarAutoDownload,
  useRadarMissing,
  useRadarQueue,
  useRunRadarAutoDownload,
  useServerSettings,
  useUpdateRadarAutoDownload,
} from '../api'
import TitleDialog, { Chips, DownloadIcon, ImdbBadge, MatchBadge } from '../TitleDialog'
import { Button, ErrorText, Poster } from '../ui'

export function RadarIcon({ className = 'size-4' }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M19.07 4.93a10 10 0 0 0-14.14 0" />
      <path d="M16.24 7.76a6 6 0 0 0-8.49 0" />
      <circle cx="12" cy="12" r="2" />
      <path d="m13.41 10.59 5.66-5.66" />
    </svg>
  )
}

export function AcquisitionRadarSettings() {
  const settings = useServerSettings()
  const radarrConfigured = settings.data?.radarr.configured ?? false

  const [minMatchMissing, setMinMatchMissing] = useState<number>(75)
  const [scope, setScope] = useState<'user' | 'group'>('user')
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [actionSuccess, setActionSuccess] = useState<string | null>(null)
  const [openedTitleId, setOpenedTitleId] = useState<number | null>(null)

  const missingQuery = useRadarMissing(minMatchMissing, scope, true)
  const queueMutation = useRadarQueue()

  const autoDownloadQuery = useRadarAutoDownload(true)
  const updateAutoDownload = useUpdateRadarAutoDownload()
  const runAutoDownload = useRunRadarAutoDownload()

  const [autoDraft, setAutoDraft] = useState<Partial<AutoDownloadConfig>>({})
  const serverCfg = autoDownloadQuery.data?.config
  const autoEnabled = autoDraft.enabled ?? serverCfg?.enabled ?? false
  const autoMinMatch = autoDraft.min_match ?? serverCfg?.min_match ?? 85
  const autoMinFreeGb = autoDraft.min_free_space_gb ?? serverCfg?.min_free_space_gb ?? 20
  const autoWeeklyLimit = autoDraft.weekly_limit ?? serverCfg?.weekly_limit ?? 3
  const autoMinVotes = autoDraft.min_votes ?? serverCfg?.min_votes ?? 500
  const autoReleasedOnly = autoDraft.released_only ?? serverCfg?.released_only ?? true

  const setAutoEnabled = (enabled: boolean) => setAutoDraft((prev) => ({ ...prev, enabled }))
  const setAutoMinMatch = (min_match: number) => setAutoDraft((prev) => ({ ...prev, min_match }))
  const setAutoMinFreeGb = (min_free_space_gb: number) =>
    setAutoDraft((prev) => ({ ...prev, min_free_space_gb }))
  const setAutoWeeklyLimit = (weekly_limit: number) =>
    setAutoDraft((prev) => ({ ...prev, weekly_limit }))
  const setAutoMinVotes = (min_votes: number) => setAutoDraft((prev) => ({ ...prev, min_votes }))
  const setAutoReleasedOnly = (released_only: boolean) =>
    setAutoDraft((prev) => ({ ...prev, released_only }))

  const currentData = missingQuery.data
  const isLoading = missingQuery.isLoading
  const error = missingQuery.error

  const autoData = autoDownloadQuery.data
  const rootFolders = autoData?.root_folders ?? currentData?.root_folders ?? []
  const minFreeFormatted =
    autoData?.min_free_space_formatted ?? currentData?.min_free_space_formatted ?? null
  const hasSufficientSpace = autoData?.has_sufficient_space ?? true

  const rawItems: RadarItem[] = currentData?.items ?? []
  const filteredItems = rawItems.filter((item) => {
    if (!searchQuery.trim()) return true
    const q = searchQuery.toLowerCase().trim()
    return (
      item.title.toLowerCase().includes(q) ||
      item.original_title.toLowerCase().includes(q) ||
      item.original_language.toLowerCase().includes(q) ||
      item.genres.some((g) => g.toLowerCase().includes(q))
    )
  })

  const unqueuedItems = filteredItems.filter((i) => i.radarr_status === 'to_request')
  const allUnqueuedSelected =
    unqueuedItems.length > 0 && unqueuedItems.every((i) => selectedIds.includes(i.tmdb_id))

  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id]))
  }

  const handleSelectAll = () => {
    if (selectedIds.length > 0) {
      setSelectedIds([])
    } else {
      setSelectedIds(unqueuedItems.map((i) => i.tmdb_id))
    }
  }

  const handleBatchQueue = async (ids: number[]) => {
    if (ids.length === 0) return
    try {
      const res = await queueMutation.mutateAsync({ tmdbIds: ids })
      setActionSuccess(`Queued ${res.requested_count} movie(s) into Radarr download queue!`)
      setSelectedIds((prev) => prev.filter((id) => !ids.includes(id)))
    } catch {
      // Captured by mutation
    }
  }

  const handleSingleQueue = (item: RadarItem) => {
    void handleBatchQueue([item.tmdb_id])
  }

  const handleSaveAutoDownload = async () => {
    try {
      await updateAutoDownload.mutateAsync({
        enabled: autoEnabled,
        min_match: Math.max(50, Math.min(100, autoMinMatch)),
        min_free_space_gb: Math.max(0, autoMinFreeGb),
        weekly_limit: Math.max(1, Math.min(100, autoWeeklyLimit)),
        min_votes: Math.max(0, autoMinVotes),
        released_only: autoReleasedOnly,
      })
      setActionSuccess(
        autoEnabled
          ? `Saved automatic downloader settings (≥ ${autoMinMatch}% match, ≥ ${autoMinFreeGb} GB free space).`
          : 'Saved automatic downloader settings (currently disabled).',
      )
    } catch {
      // Captured by mutation
    }
  }

  const handleRunAutoDownloadNow = async () => {
    try {
      await updateAutoDownload.mutateAsync({
        enabled: autoEnabled,
        min_match: Math.max(50, Math.min(100, autoMinMatch)),
        min_free_space_gb: Math.max(0, autoMinFreeGb),
        weekly_limit: Math.max(1, Math.min(100, autoWeeklyLimit)),
        min_votes: Math.max(0, autoMinVotes),
        released_only: autoReleasedOnly,
      })
      const res = await runAutoDownload.mutateAsync()
      setActionSuccess(`Auto-downloader run complete: ${res.detail}`)
    } catch {
      // Captured by mutation
    }
  }

  return (
    <div className="space-y-6">
      {/* Acquisition Radar Header / KPI Banner */}
      <section className="relative overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-br from-white/[0.04] to-transparent p-6 shadow-xl backdrop-blur-sm">
        <div className="flex flex-col gap-6 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <span className="flex size-7 items-center justify-center rounded-lg bg-accent/20 text-accent font-bold text-sm">
                <RadarIcon className="size-4" />
              </span>
              <h2 className="text-xl font-bold text-white tracking-tight">Acquisition Radar</h2>
            </div>
            <p className="mt-1.5 max-w-xl text-sm text-white/60 leading-relaxed">
              Intelligent media acquisition: find high-match recommendations missing from your streaming services,
              and queue them for automatic download in Radarr.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {minFreeFormatted && (
              <div
                className={`rounded-xl border px-4 py-2.5 text-right ${
                  hasSufficientSpace
                    ? 'border-emerald-500/20 bg-emerald-500/10'
                    : 'border-amber-500/30 bg-amber-500/15'
                }`}
              >
                <span
                  className={`block text-[10px] font-medium uppercase tracking-wider ${
                    hasSufficientSpace ? 'text-emerald-300/80' : 'text-amber-300'
                  }`}
                >
                  Remaining HDD Space
                </span>
                <span
                  className={`text-xl font-bold tabular-nums ${
                    hasSufficientSpace ? 'text-emerald-300' : 'text-amber-200'
                  }`}
                >
                  {minFreeFormatted}
                </span>
              </div>
            )}

            <div className="rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-right">
              <span className="block text-[10px] font-medium uppercase tracking-wider text-white/50">
                Missing from Streaming
              </span>
              <span className="text-xl font-bold text-white tabular-nums">
                {rawItems.length}
              </span>
            </div>

            <div className="rounded-xl border border-accent/20 bg-accent/10 px-4 py-2.5 text-right">
              <span className="block text-[10px] font-medium uppercase tracking-wider text-accent-strong">
                To Request
              </span>
              <span className="text-xl font-bold text-accent tabular-nums">
                {unqueuedItems.length}
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* Radarr Warning Banner if not configured */}
      {!radarrConfigured && (
        <div className="flex flex-col gap-3 rounded-xl border border-amber-500/20 bg-amber-500/10 p-4 text-sm sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <span className="text-xl">⚠️</span>
            <div>
              <p className="font-semibold text-amber-200">Radarr is not connected</p>
              <p className="text-xs text-amber-200/70">
                Connect your Radarr instance in Settings to enable automated downloads and file status detection.
              </p>
            </div>
          </div>
          <Link
            to="/settings/integrations#radarr"
            className="shrink-0 rounded-lg bg-amber-400 px-3 py-1.5 text-xs font-semibold text-black transition hover:bg-amber-300"
          >
            Connect Radarr →
          </Link>
        </div>
      )}

      {/* Automatic Background Downloader & Storage Guardrails */}
      <section className="rounded-2xl border border-white/10 bg-white/[0.02] p-5 backdrop-blur-sm space-y-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2.5">
              <h3 className="text-base font-semibold text-white">
                Automatic Background Downloads
              </h3>
              <span
                className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium ${
                  autoEnabled
                    ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/25'
                    : 'bg-white/10 text-white/55'
                }`}
              >
                {autoEnabled ? `Active · ≥ ${autoMinMatch}% Match` : 'Off'}
              </span>
              {autoData && (
                <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-0.5 text-[11px] text-white/60">
                  {autoData.downloads_this_week} / {autoWeeklyLimit} downloaded this week
                </span>
              )}
            </div>
            <p className="mt-1 text-xs text-white/55">
              Autonomously queues top unstreamable recommendations into Radarr after feed updates,
              guarded by your match threshold, remaining HDD free space, weekly download cap, and vote floor.
            </p>
          </div>

          <label className="inline-flex items-center gap-2.5 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={autoEnabled}
              onChange={(e) => setAutoEnabled(e.target.checked)}
              className="size-4 rounded border-white/20 bg-black/50 text-accent focus:ring-accent"
            />
            <span className="text-xs font-medium text-white">Enable auto-downloads</span>
          </label>
        </div>

        {/* Root Folder Free Disk Space Indicators */}
        {rootFolders.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 rounded-xl border border-white/10 bg-black/25 px-3.5 py-2.5 text-xs">
            <span className="font-medium text-white/60">Radarr HDD Free Space:</span>
            {rootFolders.map((folder) => {
              const freeBytes = folder.free_space_bytes
              const minBytes = autoMinFreeGb * 1024 * 1024 * 1024
              const isLow = autoMinFreeGb > 0 && freeBytes != null && freeBytes < minBytes
              return (
                <span
                  key={folder.path}
                  className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 font-mono text-[11px] ${
                    isLow
                      ? 'border-amber-500/35 bg-amber-500/15 text-amber-200'
                      : 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300'
                  }`}
                >
                  <span>{folder.path}</span>
                  <span className="font-sans font-semibold">
                    {folder.free_space_formatted ?? 'Unknown'} free
                  </span>
                  {isLow && <span title={`Below ${autoMinFreeGb} GB minimum`}>⚠️</span>}
                </span>
              )
            })}
          </div>
        )}

        {/* Controls Grid */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <label className="block rounded-xl border border-white/10 bg-[#12161f]/80 p-3">
            <span className="block text-[11px] font-medium text-white/60">
              Auto-Download Match %
            </span>
            <div className="mt-1.5 flex items-center gap-2">
              <input
                type="number"
                min={50}
                max={100}
                value={autoMinMatch}
                onChange={(e) => setAutoMinMatch(Number(e.target.value))}
                className="w-20 rounded-lg border border-white/15 bg-black/40 px-2.5 py-1 text-sm font-semibold text-white focus:border-accent focus:outline-none"
              />
              <span className="text-xs text-white/50">% min (50–100)</span>
            </div>
          </label>

          <label className="block rounded-xl border border-white/10 bg-[#12161f]/80 p-3">
            <span className="block text-[11px] font-medium text-white/60">
              Min Remaining HDD Space
            </span>
            <div className="mt-1.5 flex items-center gap-2">
              <input
                type="number"
                min={0}
                max={100000}
                value={autoMinFreeGb}
                onChange={(e) => setAutoMinFreeGb(Number(e.target.value))}
                className="w-20 rounded-lg border border-white/15 bg-black/40 px-2.5 py-1 text-sm font-semibold text-white focus:border-accent focus:outline-none"
              />
              <span className="text-xs text-white/50">GB free required</span>
            </div>
          </label>

          <label className="block rounded-xl border border-white/10 bg-[#12161f]/80 p-3">
            <span className="block text-[11px] font-medium text-white/60">
              Weekly Download Cap
            </span>
            <div className="mt-1.5 flex items-center gap-2">
              <input
                type="number"
                min={1}
                max={100}
                value={autoWeeklyLimit}
                onChange={(e) => setAutoWeeklyLimit(Number(e.target.value))}
                className="w-20 rounded-lg border border-white/15 bg-black/40 px-2.5 py-1 text-sm font-semibold text-white focus:border-accent focus:outline-none"
              />
              <span className="text-xs text-white/50">movies / week</span>
            </div>
          </label>

          <label className="block rounded-xl border border-white/10 bg-[#12161f]/80 p-3">
            <span className="block text-[11px] font-medium text-white/60">
              Minimum Vote Floor
            </span>
            <div className="mt-1.5 flex items-center gap-2">
              <input
                type="number"
                min={0}
                max={1000000}
                step={50}
                value={autoMinVotes}
                onChange={(e) => setAutoMinVotes(Number(e.target.value))}
                className="w-24 rounded-lg border border-white/15 bg-black/40 px-2.5 py-1 text-sm font-semibold text-white focus:border-accent focus:outline-none"
              />
              <span className="text-xs text-white/50">votes</span>
            </div>
          </label>

          <label className="flex items-center gap-2.5 rounded-xl border border-white/10 bg-[#12161f]/80 p-3 cursor-pointer">
            <input
              type="checkbox"
              checked={autoReleasedOnly}
              onChange={(e) => setAutoReleasedOnly(e.target.checked)}
              className="size-4 rounded border-white/20 bg-black/50 text-accent focus:ring-accent"
            />
            <div>
              <span className="block text-xs font-medium text-white">Released only</span>
              <span className="block text-[11px] text-white/50">
                Digital/physical only (no CAM rips)
              </span>
            </div>
          </label>
        </div>

        {(updateAutoDownload.error || runAutoDownload.error) && (
          <ErrorText>
            {errorMessage(updateAutoDownload.error ?? runAutoDownload.error)}
          </ErrorText>
        )}

        <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
          <div className="text-xs text-white/50">
            {autoData?.last_run ? (
              <span>
                Last run: <strong className="text-white/75">{autoData.last_run.detail}</strong>
              </span>
            ) : (
              <span>Has not run automatically yet.</span>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="ghost"
              disabled={updateAutoDownload.isPending || runAutoDownload.isPending || !radarrConfigured}
              onClick={() => void handleRunAutoDownloadNow()}
              className="text-xs px-3 py-1.5"
            >
              {runAutoDownload.isPending ? 'Running…' : 'Run Auto-Downloader Now'}
            </Button>
            <Button
              variant="primary"
              disabled={updateAutoDownload.isPending}
              onClick={() => void handleSaveAutoDownload()}
              className="text-xs px-3 py-1.5"
            >
              {updateAutoDownload.isPending ? 'Saving…' : 'Save Auto-Download Settings'}
            </Button>
          </div>
        </div>
      </section>

      {/* Action Success Alert */}
      {actionSuccess && (
        <div className="flex items-center justify-between rounded-xl border border-emerald-500/30 bg-emerald-500/15 p-4 text-sm text-emerald-200">
          <div className="flex items-center gap-2">
            <span>✓</span>
            <span>{actionSuccess}</span>
          </div>
          <button
            type="button"
            onClick={() => setActionSuccess(null)}
            className="text-xs text-emerald-300 hover:text-white cursor-pointer"
          >
            Dismiss
          </button>
        </div>
      )}

      {error && <ErrorText>{errorMessage(error)}</ErrorText>}

      {/* Filter and Batch Action Bar */}
      <div className="flex flex-col gap-4 rounded-xl border border-white/10 bg-white/[0.02] p-4 backdrop-blur-sm sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-3">
          {/* Minimum Match Selector */}
          <div className="flex items-center gap-2 text-xs">
            <span className="text-white/50">Min Match:</span>
            <select
              value={minMatchMissing}
              onChange={(e) => setMinMatchMissing(Number(e.target.value))}
              className="rounded-lg border border-white/10 bg-[#12161f] px-2.5 py-1.5 text-xs text-white focus:border-accent focus:outline-none"
            >
              <option value={65}>≥ 65% Match</option>
              <option value={70}>≥ 70% Match</option>
              <option value={75}>≥ 75% Match (Recommended)</option>
              <option value={80}>≥ 80% Match</option>
              <option value={85}>≥ 85% Match</option>
              <option value={90}>≥ 90% Match</option>
            </select>
          </div>

          {/* Scope Toggle for Missing from Streaming */}
          <div className="flex items-center gap-2 text-xs">
            <span className="text-white/50">Scope:</span>
            <select
              value={scope}
              onChange={(e) => setScope(e.target.value as 'user' | 'group')}
              className="rounded-lg border border-white/10 bg-[#12161f] px-2.5 py-1.5 text-xs text-white focus:border-accent focus:outline-none"
            >
              <option value="user">My Recommendations</option>
              <option value="group">Household Group</option>
            </select>
          </div>

          {/* Search Box */}
          <input
            type="search"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Filter title or language..."
            className="rounded-lg border border-white/10 bg-[#12161f] px-3 py-1.5 text-xs text-white placeholder-white/40 focus:border-accent focus:outline-none"
          />
        </div>

        {/* Batch Queue Controls */}
        <div className="flex flex-wrap items-center gap-2">
          {unqueuedItems.length > 0 && (
            <Button
              variant="ghost"
              onClick={handleSelectAll}
              className="text-xs px-3 py-1.5"
            >
              {selectedIds.length > 0
                ? allUnqueuedSelected
                  ? 'Deselect All'
                  : 'Clear Selection'
                : `Select All To Queue (${unqueuedItems.length})`}
            </Button>
          )}

          {selectedIds.length > 0 && (
            <Button
              variant="primary"
              disabled={queueMutation.isPending || !radarrConfigured}
              onClick={() => handleBatchQueue(selectedIds)}
              className="text-xs px-3 py-1.5"
            >
              <DownloadIcon className="mr-1.5 size-3.5 inline" />
              {queueMutation.isPending
                ? 'Queueing…'
                : `Queue Selected (${selectedIds.length})`}
            </Button>
          )}

          {selectedIds.length === 0 && unqueuedItems.length > 0 && (
            <button
              type="button"
              disabled={queueMutation.isPending || !radarrConfigured}
              onClick={() => handleBatchQueue(unqueuedItems.map((i) => i.tmdb_id))}
              className="rounded-lg border border-white/15 bg-white/5 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-white/10 disabled:opacity-50 cursor-pointer"
            >
              <DownloadIcon className="mr-1.5 size-3.5 inline" />
              {`Queue All Missing (${unqueuedItems.length})`}
            </button>
          )}
        </div>
      </div>

      {/* Loading Skeleton */}
      {isLoading && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3, 4, 5, 6].map((n) => (
            <div key={n} className="h-44 animate-pulse rounded-xl border border-white/5 bg-white/[0.02]" />
          ))}
        </div>
      )}

      {/* Empty State */}
      {!isLoading && filteredItems.length === 0 && (
        <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-white/10 p-12 text-center">
          <span className="text-3xl">🎯</span>
          <p className="mt-3 text-base font-medium text-white">
            No missing unstreamable recommendations found
          </p>
          <p className="mt-1 text-xs text-white/50 max-w-sm">
            All of your high-match movies are either available to stream on your active subscriptions or already in your Jellyfin library.
          </p>
        </div>
      )}

      {/* Movie Cards Grid */}
      {!isLoading && filteredItems.length > 0 && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filteredItems.map((item) => {
            const isSelected = selectedIds.includes(item.tmdb_id)
            const isToQueue = item.radarr_status === 'to_request'
            const isDownloaded = item.radarr_status === 'downloaded'
            const isDownloading = item.radarr_status === 'downloading'

            return (
              <div
                key={item.tmdb_id}
                className={`group relative flex flex-col justify-between overflow-hidden rounded-xl border transition-all ${
                  isSelected
                    ? 'border-accent/40 bg-accent/[0.05] shadow-lg shadow-accent/10'
                    : 'border-white/10 bg-[#0e121a]/80 hover:border-white/20'
                }`}
              >
                <div className="flex gap-3.5 p-3.5">
                  {/* Select Checkbox */}
                  {isToQueue && (
                    <div className="absolute top-2.5 left-2.5 z-10">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => toggleSelect(item.tmdb_id)}
                        className="size-4 rounded border-white/20 bg-black/60 text-accent focus:ring-accent focus:ring-offset-0"
                      />
                    </div>
                  )}

                  {/* Poster Thumbnail */}
                  <div
                    onClick={() => setOpenedTitleId(item.tmdb_id)}
                    className="relative shrink-0 cursor-pointer overflow-hidden rounded-lg shadow-md transition-transform group-hover:scale-[1.02]"
                  >
                    <Poster
                      path={item.poster_path}
                      title={item.title}
                      className="h-28 w-20 object-cover"
                    />
                  </div>

                  {/* Movie Info */}
                  <div className="flex min-w-0 flex-1 flex-col justify-between">
                    <div>
                      <div className="flex items-start justify-between gap-1.5">
                        <button
                          type="button"
                          onClick={() => setOpenedTitleId(item.tmdb_id)}
                          className="min-w-0 text-left font-semibold text-white text-sm hover:text-accent transition-colors line-clamp-1"
                          title={item.title}
                        >
                          {item.title}
                        </button>
                      </div>

                      <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-white/50">
                        {(item.release_date || item.year) && (
                          <span>{formatReleaseDate(item.release_date, item.year)}</span>
                        )}
                        {item.status && <span>· {item.status}</span>}
                        {item.original_language && (
                          <span className="uppercase">{item.original_language}</span>
                        )}
                        {item.runtime && <span>{item.runtime}m</span>}
                      </div>

                      {/* Taste Reason */}
                      {item.reasons.length > 0 && (
                        <p className="mt-1.5 text-[11px] text-accent-strong line-clamp-2 leading-tight">
                          💡 {item.reasons[0]}
                        </p>
                      )}

                      {/* Genre Chips */}
                      {item.genres.length > 0 && (
                        <Chips genres={item.genres} moods={[]} max={2} className="mt-1.5" />
                      )}
                    </div>

                    {/* Match & IMDb Badges Row */}
                    <div className="mt-2 flex items-center gap-2">
                      <MatchBadge match={item.match_pct} className="scale-85 origin-left" />
                      {item.imdb && (
                        <ImdbBadge
                          imdb={{ id: item.imdb.id, rating: item.imdb.rating, votes: item.imdb.votes }}
                          className="scale-85 origin-left"
                        />
                      )}
                    </div>
                  </div>
                </div>

                {/* Footer Status and Quick Action Bar */}
                <div className="flex items-center justify-between border-t border-white/5 bg-white/[0.015] px-3.5 py-2 text-xs">
                  {/* Status Indicator */}
                  <div>
                    {isDownloaded ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-medium text-emerald-300">
                        ✓ Downloaded
                      </span>
                    ) : isDownloading ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium text-amber-300">
                        ⏳ Downloading
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded-full bg-white/10 px-2 py-0.5 text-[10px] font-medium text-white/50">
                        Not in Radarr
                      </span>
                    )}
                  </div>

                  {/* Action Buttons */}
                  <div className="flex items-center gap-1.5">
                    {isToQueue ? (
                      <button
                        type="button"
                        disabled={queueMutation.isPending || !radarrConfigured}
                        onClick={() => handleSingleQueue(item)}
                        className="inline-flex items-center gap-1 rounded-lg bg-accent/20 px-2.5 py-1 text-[11px] font-medium text-accent-strong hover:bg-accent/30 transition-colors disabled:opacity-50"
                      >
                        <DownloadIcon className="size-3" />
                        Download
                      </button>
                    ) : item.radarr_url ? (
                      <a
                        href={item.radarr_url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 text-[11px] text-white/45 hover:text-white transition-colors"
                      >
                        Radarr ↗
                      </a>
                    ) : null}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Film Detail Modal */}
      <TitleDialog tmdbId={openedTitleId} onClose={() => setOpenedTitleId(null)} />
    </div>
  )
}
