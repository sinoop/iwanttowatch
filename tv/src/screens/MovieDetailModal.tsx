import React, { useState } from 'react'
import {
  ActivityIndicator,
  Image,
  Modal,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { FeedbackKind } from '@iwanttowatch/api-client'
import { useServer } from '../context/ServerContext'
import { TvFocusable } from '../components/TvFocusable'
import type { TvMovieItem } from '../components/TvMovieCard'
import {
  getProviderBrand,
  launchJellyfinMovie,
  launchStreamingService,
} from '../utils/tvLaunching'

interface MovieDetailModalProps {
  item: TvMovieItem | null
  visible: boolean
  onClose: () => void
}

export function MovieDetailModal({ item, visible, onClose }: MovieDetailModalProps) {
  const { client } = useServer()
  const queryClient = useQueryClient()
  const [launchNotice, setLaunchNotice] = useState<string | null>(null)
  const [shortlistedOverride, setShortlistedOverride] = useState<boolean | null>(null)

  const tmdbId = item?.tmdb_id ?? null

  const { data: detail, isLoading: detailLoading } = useQuery({
    queryKey: ['tv-title-detail', tmdbId],
    queryFn: async () => {
      if (!tmdbId) return null
      const res = await client.GET('/api/v1/titles/{tmdb_id}', {
        params: { path: { tmdb_id: tmdbId } },
      })
      if (res.error) throw new Error(String(res.error))
      return res.data
    },
    enabled: visible && tmdbId !== null,
  })

  const feedbackMutation = useMutation({
    mutationFn: async (kind: FeedbackKind) => {
      if (!tmdbId) return
      await client.PUT('/api/v1/titles/{tmdb_id}/feedback', {
        params: { path: { tmdb_id: tmdbId } },
        body: { kind },
      })
    },
    onSuccess: (_, kind) => {
      queryClient.invalidateQueries({ queryKey: ['tv-feed'] })
      queryClient.invalidateQueries({ queryKey: ['tv-shortlist'] })
      queryClient.invalidateQueries({ queryKey: ['tv-together-picks'] })
      if (kind === 'dismissed' || kind === 'seen') {
        onClose()
      } else {
        setLaunchNotice(kind === 'up' ? 'Marked as Liked' : 'Marked as Disliked')
      }
    },
  })

  const isShortlisted =
    shortlistedOverride ??
    detail?.shortlisted ??
    (item && 'shortlisted' in item ? item.shortlisted : false)

  const shortlistMutation = useMutation({
    mutationFn: async () => {
      if (!tmdbId) return
      if (isShortlisted) {
        await client.DELETE('/api/v1/titles/{tmdb_id}/shortlist', {
          params: { path: { tmdb_id: tmdbId } },
        })
      } else {
        await client.PUT('/api/v1/titles/{tmdb_id}/shortlist', {
          params: { path: { tmdb_id: tmdbId } },
        })
      }
    },
    onMutate: () => {
      setShortlistedOverride(!isShortlisted)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tv-feed'] })
      queryClient.invalidateQueries({ queryKey: ['tv-shortlist'] })
      queryClient.invalidateQueries({ queryKey: ['tv-title-detail', tmdbId] })
    },
  })

  if (!item) return null

  const title = detail?.title ?? item.title
  const originalTitle = detail?.original_title ?? item.original_title
  const posterPath = detail?.poster_path ?? item.poster_path
  const posterUrl = posterPath ? `https://image.tmdb.org/t/p/w500${posterPath}` : null
  const availability = detail?.availability ?? item.availability
  const jellyfinUrl = detail?.jellyfin_url ?? null
  const match = detail?.match ?? item.match
  const reasons = detail?.reasons ?? item.reasons

  // Deduplicate streaming offers by provider_id
  const uniqueOffers = availability.offers.filter(
    (offer, idx, arr) =>
      arr.findIndex((o) => o.provider_id === offer.provider_id) === idx,
  )

  const handleLaunchJellyfin = async () => {
    setLaunchNotice('Launching Jellyfin...')
    const result = await launchJellyfinMovie({ jellyfinUrl, title })
    setLaunchNotice(result.launched ? 'Opened in Jellyfin' : result.message || 'Launch failed')
  }

  const handleLaunchProvider = async (providerName: string) => {
    setLaunchNotice(`Launching ${providerName}...`)
    const result = await launchStreamingService({
      providerName,
      title,
      fallbackUrl: availability.link,
    })
    setLaunchNotice(
      result.launched ? `Opened in ${providerName}` : result.message || 'Launch failed',
    )
  }

  const hasFirstService = availability.on_jellyfin || uniqueOffers.length > 0

  return (
    <Modal visible={visible} animationType="fade" transparent onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={styles.panel}>
          <View style={styles.topBar}>
            <Text style={styles.topTitle} numberOfLines={1}>
              {title}
            </Text>
            <TvFocusable
              onPress={onClose}
              hasTVPreferredFocus={!hasFirstService}
              borderRadius={10}
              style={styles.closeBtn}
            >
              <Ionicons name="close" size={24} color="#e2e8f0" />
              <Text style={styles.closeText}>Back</Text>
            </TvFocusable>
          </View>

          <ScrollView contentContainerStyle={styles.scrollBody}>
            <View style={styles.heroRow}>
              {posterUrl ? (
                <Image source={{ uri: posterUrl }} style={styles.poster} resizeMode="cover" />
              ) : (
                <View style={styles.posterFallback}>
                  <Ionicons name="film-outline" size={64} color="#475569" />
                </View>
              )}

              <View style={styles.heroInfo}>
                <Text style={styles.movieTitle}>{title}</Text>
                {originalTitle && originalTitle !== title ? (
                  <Text style={styles.originalTitle}>{originalTitle}</Text>
                ) : null}

                <View style={styles.metaPills}>
                  {match !== null ? (
                    <View style={styles.matchPill}>
                      <Text style={styles.matchPillText}>{match}% Match</Text>
                    </View>
                  ) : null}
                  {item.imdb?.rating ? (
                    <View style={styles.imdbPill}>
                      <Text style={styles.imdbPillText}>
                        IMDb {item.imdb.rating.toFixed(1)}
                      </Text>
                    </View>
                  ) : null}
                  {item.year ? <Text style={styles.metaText}>{item.year}</Text> : null}
                  {item.runtime ? (
                    <Text style={styles.metaText}>{item.runtime} min</Text>
                  ) : null}
                  {item.certificate ? (
                    <Text style={styles.certText}>{item.certificate}</Text>
                  ) : null}
                </View>

                {item.genres.length > 0 ? (
                  <Text style={styles.genresText}>{item.genres.join(' • ')}</Text>
                ) : null}

                {/* Direct Service Launchers */}
                <View style={styles.section}>
                  <Text style={styles.sectionLabel}>Watch Now — Select Service to Launch</Text>
                  <View style={styles.serviceRow}>
                    {availability.on_jellyfin ? (
                      <TvFocusable
                        onPress={handleLaunchJellyfin}
                        hasTVPreferredFocus
                        borderRadius={12}
                        style={[styles.launchBtn, { backgroundColor: '#7c3aed' }]}
                      >
                        <Ionicons name="play-circle" size={22} color="#ffffff" />
                        <Text style={styles.launchBtnText}>Play on Jellyfin</Text>
                      </TvFocusable>
                    ) : null}

                    {uniqueOffers.map((offer, idx) => {
                      const brand = getProviderBrand(offer.name)
                      return (
                        <TvFocusable
                          key={offer.provider_id}
                          onPress={() => handleLaunchProvider(offer.name)}
                          hasTVPreferredFocus={!availability.on_jellyfin && idx === 0}
                          borderRadius={12}
                          style={[styles.launchBtn, { backgroundColor: brand.color }]}
                        >
                          <Ionicons name="tv-outline" size={20} color="#ffffff" />
                          <Text style={styles.launchBtnText}>
                            Watch on {brand.shortLabel}
                          </Text>
                        </TvFocusable>
                      )
                    })}

                    {!availability.on_jellyfin && uniqueOffers.length === 0 ? (
                      <Text style={styles.noServiceText}>
                        No active streaming or Jellyfin source found for this title.
                      </Text>
                    ) : null}
                  </View>

                  {launchNotice ? (
                    <Text style={styles.noticeText}>{launchNotice}</Text>
                  ) : null}
                </View>

                {/* Quick Feedback Actions */}
                <View style={styles.actionRow}>
                  <TvFocusable
                    onPress={() => shortlistMutation.mutate()}
                    borderRadius={10}
                    style={[
                      styles.actionBtn,
                      isShortlisted && styles.actionBtnActive,
                    ]}
                  >
                    <Ionicons
                      name={isShortlisted ? 'bookmark' : 'bookmark-outline'}
                      size={18}
                      color="#f8fafc"
                    />
                    <Text style={styles.actionBtnText}>
                      {isShortlisted ? 'Shortlisted' : 'Shortlist'}
                    </Text>
                  </TvFocusable>

                  <TvFocusable
                    onPress={() => feedbackMutation.mutate('up')}
                    borderRadius={10}
                    style={styles.actionBtn}
                  >
                    <Ionicons name="thumbs-up-outline" size={18} color="#4ade80" />
                    <Text style={styles.actionBtnText}>Like</Text>
                  </TvFocusable>

                  <TvFocusable
                    onPress={() => feedbackMutation.mutate('down')}
                    borderRadius={10}
                    style={styles.actionBtn}
                  >
                    <Ionicons name="thumbs-down-outline" size={18} color="#f87171" />
                    <Text style={styles.actionBtnText}>Dislike</Text>
                  </TvFocusable>

                  <TvFocusable
                    onPress={() => feedbackMutation.mutate('seen')}
                    borderRadius={10}
                    style={styles.actionBtn}
                  >
                    <Ionicons name="checkmark-done-outline" size={18} color="#38bdf8" />
                    <Text style={styles.actionBtnText}>Watched</Text>
                  </TvFocusable>

                  <TvFocusable
                    onPress={() => feedbackMutation.mutate('dismissed')}
                    borderRadius={10}
                    style={styles.actionBtn}
                  >
                    <Ionicons name="eye-off-outline" size={18} color="#94a3b8" />
                    <Text style={styles.actionBtnText}>Dismiss</Text>
                  </TvFocusable>
                </View>
              </View>
            </View>

            {/* Details: Overview, Reasons, Credits */}
            {detailLoading ? (
              <View style={styles.loadingRow}>
                <ActivityIndicator color="#818cf8" />
                <Text style={styles.loadingText}>Loading full details...</Text>
              </View>
            ) : null}

            {detail?.overview ? (
              <View style={styles.detailBlock}>
                <Text style={styles.blockTitle}>Overview</Text>
                <Text style={styles.overviewText}>{detail.overview}</Text>
              </View>
            ) : null}

            {detail?.explanation || reasons.length > 0 ? (
              <View style={styles.detailBlock}>
                <Text style={styles.blockTitle}>Why It Suits You</Text>
                {detail?.explanation ? (
                  <Text style={styles.overviewText}>{detail.explanation}</Text>
                ) : null}
                {reasons.map((r, i) => (
                  <Text key={i} style={styles.reasonItem}>
                    • {r}
                  </Text>
                ))}
              </View>
            ) : null}

            {detail && (detail.directors.length > 0 || detail.cast.length > 0) ? (
              <View style={styles.detailBlock}>
                <Text style={styles.blockTitle}>Cast & Crew</Text>
                {detail.directors.length > 0 ? (
                  <Text style={styles.creditLine}>
                    Directed by: {detail.directors.map((d) => d.name).join(', ')}
                  </Text>
                ) : null}
                {detail.cast.length > 0 ? (
                  <Text style={styles.creditLine}>
                    Starring: {detail.cast.slice(0, 8).map((c) => c.name).join(', ')}
                  </Text>
                ) : null}
              </View>
            ) : null}
          </ScrollView>
        </View>
      </View>
    </Modal>
  )
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(5, 8, 16, 0.94)',
    padding: 32,
  },
  panel: {
    flex: 1,
    backgroundColor: '#0f172a',
    borderRadius: 20,
    borderWidth: 1,
    borderColor: '#1e293b',
    overflow: 'hidden',
  },
  topBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 28,
    paddingVertical: 16,
    backgroundColor: '#0b1120',
    borderBottomWidth: 1,
    borderBottomColor: '#1e293b',
  },
  topTitle: {
    color: '#94a3b8',
    fontSize: 18,
    fontWeight: '600',
    flex: 1,
    marginRight: 16,
  },
  closeBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: '#1e293b',
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderWidth: 2,
    borderColor: '#334155',
  },
  closeText: {
    color: '#f8fafc',
    fontSize: 16,
    fontWeight: '600',
  },
  scrollBody: {
    padding: 32,
    gap: 24,
  },
  heroRow: {
    flexDirection: 'row',
    gap: 32,
  },
  poster: {
    width: 240,
    height: 360,
    borderRadius: 14,
    backgroundColor: '#1e293b',
  },
  posterFallback: {
    width: 240,
    height: 360,
    borderRadius: 14,
    backgroundColor: '#1e293b',
    alignItems: 'center',
    justifyContent: 'center',
  },
  heroInfo: {
    flex: 1,
    gap: 14,
  },
  movieTitle: {
    color: '#f8fafc',
    fontSize: 34,
    fontWeight: '800',
  },
  originalTitle: {
    color: '#94a3b8',
    fontSize: 18,
    fontStyle: 'italic',
  },
  metaPills: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 12,
  },
  matchPill: {
    backgroundColor: '#312e81',
    borderWidth: 1,
    borderColor: '#6366f1',
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  matchPillText: {
    color: '#e0e7ff',
    fontSize: 15,
    fontWeight: '800',
  },
  imdbPill: {
    backgroundColor: 'rgba(245, 158, 11, 0.18)',
    borderWidth: 1,
    borderColor: '#f59e0b',
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  imdbPillText: {
    color: '#fcd34d',
    fontSize: 15,
    fontWeight: '700',
  },
  metaText: {
    color: '#cbd5e1',
    fontSize: 16,
    fontWeight: '600',
  },
  certText: {
    color: '#e2e8f0',
    fontSize: 14,
    fontWeight: '700',
    borderWidth: 1,
    borderColor: '#475569',
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  genresText: {
    color: '#94a3b8',
    fontSize: 16,
  },
  section: {
    gap: 10,
    marginTop: 4,
  },
  sectionLabel: {
    color: '#cbd5e1',
    fontSize: 14,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.8,
  },
  serviceRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 12,
  },
  launchBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: 22,
    paddingVertical: 14,
    borderWidth: 2,
    borderColor: 'rgba(255,255,255,0.2)',
  },
  launchBtnText: {
    color: '#ffffff',
    fontSize: 17,
    fontWeight: '700',
  },
  noServiceText: {
    color: '#94a3b8',
    fontSize: 15,
  },
  noticeText: {
    color: '#a5b4fc',
    fontSize: 15,
    fontWeight: '600',
  },
  actionRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
    marginTop: 6,
  },
  actionBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: '#1e293b',
    paddingHorizontal: 16,
    paddingVertical: 11,
    borderWidth: 2,
    borderColor: '#334155',
  },
  actionBtnActive: {
    backgroundColor: '#4f46e5',
    borderColor: '#6366f1',
  },
  actionBtnText: {
    color: '#f8fafc',
    fontSize: 15,
    fontWeight: '600',
  },
  loadingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  loadingText: {
    color: '#94a3b8',
    fontSize: 15,
  },
  detailBlock: {
    backgroundColor: '#111827',
    borderRadius: 14,
    borderWidth: 1,
    borderColor: '#1f2937',
    padding: 20,
    gap: 8,
  },
  blockTitle: {
    color: '#f8fafc',
    fontSize: 18,
    fontWeight: '700',
  },
  overviewText: {
    color: '#cbd5e1',
    fontSize: 16,
    lineHeight: 24,
  },
  reasonItem: {
    color: '#a5b4fc',
    fontSize: 15,
    lineHeight: 22,
  },
  creditLine: {
    color: '#cbd5e1',
    fontSize: 15,
    lineHeight: 22,
  },
})
