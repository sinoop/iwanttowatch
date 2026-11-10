import React from 'react'
import {
  StyleSheet,
  Text,
  View,
  Image,
  TouchableOpacity,
} from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import type { FeedItem } from '@iwanttowatch/api-client'
import { openStreamingProvider } from '../utils/linking'

interface MovieCardProps {
  item: FeedItem
  isShortlisted?: boolean
  onFeedback: (tmdbId: number, kind: 'up' | 'down' | 'dismissed' | 'snoozed') => void
  onToggleShortlist: (tmdbId: number) => void
  onPressDetail: (item: FeedItem) => void
}

export function MovieCard({
  item,
  isShortlisted,
  onFeedback,
  onToggleShortlist,
  onPressDetail,
}: MovieCardProps) {
  const posterUrl = item.poster_path
    ? `https://image.tmdb.org/t/p/w342${item.poster_path}`
    : null

  const formatRuntime = (mins: number | null): string => {
    if (!mins) return ''
    const h = Math.floor(mins / 60)
    const m = mins % 60
    return h > 0 ? `${h}h ${m}m` : `${m}m`
  }

  const matchColor =
    item.match >= 85 ? '#10b981' : item.match >= 70 ? '#38bdf8' : '#f59e0b'

  return (
    <View style={styles.card}>
      <TouchableOpacity
        activeOpacity={0.85}
        onPress={() => onPressDetail(item)}
        style={styles.cardMain}
      >
        {/* Poster */}
        <View style={styles.posterContainer}>
          {posterUrl ? (
            <Image source={{ uri: posterUrl }} style={styles.poster} resizeMode="cover" />
          ) : (
            <View style={[styles.poster, styles.posterPlaceholder]}>
              <Ionicons name="film-outline" size={32} color="#475569" />
            </View>
          )}
          <View style={[styles.matchBadge, { backgroundColor: matchColor }]}>
            <Text style={styles.matchText}>{item.match}%</Text>
          </View>
        </View>

        {/* Content */}
        <View style={styles.content}>
          <Text style={styles.title} numberOfLines={2}>
            {item.title}
          </Text>

          <View style={styles.metaRow}>
            {item.year ? <Text style={styles.metaText}>{item.year}</Text> : null}
            {item.runtime ? (
              <>
                <Text style={styles.metaDot}>•</Text>
                <Text style={styles.metaText}>{formatRuntime(item.runtime)}</Text>
              </>
            ) : null}
            {item.original_language && item.original_language !== 'en' ? (
              <>
                <Text style={styles.metaDot}>•</Text>
                <Text style={styles.langBadge}>{item.original_language.toUpperCase()}</Text>
              </>
            ) : null}
          </View>

          {/* AI / Neighbour Reason */}
          {item.reasons && item.reasons.length > 0 ? (
            <Text style={styles.reasonText} numberOfLines={2}>
              💡 {item.reasons[0]}
            </Text>
          ) : null}

          {/* Tags */}
          <View style={styles.tagRow}>
            {item.genres?.slice(0, 2).map((genre) => (
              <View key={genre} style={styles.tagBadge}>
                <Text style={styles.tagText}>{genre}</Text>
              </View>
            ))}
            {item.moods?.slice(0, 2).map((mood) => (
              <View key={mood} style={[styles.tagBadge, styles.moodBadge]}>
                <Text style={[styles.tagText, styles.moodText]}>{mood}</Text>
              </View>
            ))}
          </View>

          {/* Where to Watch */}
          <View style={styles.availabilityRow}>
            {item.availability.on_jellyfin ? (
              <TouchableOpacity
                style={[styles.providerChip, styles.jellyfinChip]}
                onPress={() =>
                  openStreamingProvider('Jellyfin', item.title, item.availability.link)
                }
              >
                <Ionicons name="play-circle" size={14} color="#a855f7" />
                <Text style={styles.jellyfinChipText}>Jellyfin</Text>
              </TouchableOpacity>
            ) : null}

            {item.availability.offers?.map((offer, idx) => (
              <TouchableOpacity
                key={`${offer.name}-${idx}`}
                style={styles.providerChip}
                onPress={() =>
                  openStreamingProvider(offer.name, item.title, item.availability.link)
                }
              >
                <Ionicons name="open-outline" size={12} color="#38bdf8" />
                <Text style={styles.providerChipText} numberOfLines={1}>
                  {offer.name}
                </Text>
              </TouchableOpacity>
            ))}
          </View>
        </View>
      </TouchableOpacity>

      {/* Action Bar */}
      <View style={styles.actionBar}>
        <TouchableOpacity
          style={styles.actionBtn}
          onPress={() => onFeedback(item.tmdb_id, 'up')}
        >
          <Ionicons name="thumbs-up-outline" size={18} color="#94a3b8" />
          <Text style={styles.actionText}>Like</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={styles.actionBtn}
          onPress={() => onFeedback(item.tmdb_id, 'down')}
        >
          <Ionicons name="thumbs-down-outline" size={18} color="#94a3b8" />
          <Text style={styles.actionText}>Dislike</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.actionBtn, isShortlisted ? styles.actionActive : null]}
          onPress={() => onToggleShortlist(item.tmdb_id)}
        >
          <Ionicons
            name={isShortlisted ? 'bookmark' : 'bookmark-outline'}
            size={18}
            color={isShortlisted ? '#f59e0b' : '#94a3b8'}
          />
          <Text style={[styles.actionText, isShortlisted ? styles.actionActiveText : null]}>
            Shortlist
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={styles.actionBtn}
          onPress={() => onFeedback(item.tmdb_id, 'dismissed')}
        >
          <Ionicons name="eye-off-outline" size={18} color="#94a3b8" />
          <Text style={styles.actionText}>Dismiss</Text>
        </TouchableOpacity>
      </View>
    </View>
  )
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: '#1e293b',
    borderRadius: 12,
    marginHorizontal: 16,
    marginVertical: 8,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: '#334155',
  },
  cardMain: {
    flexDirection: 'row',
    padding: 12,
  },
  posterContainer: {
    position: 'relative',
    width: 96,
    height: 144,
    borderRadius: 8,
    overflow: 'hidden',
    backgroundColor: '#0f172a',
  },
  poster: {
    width: '100%',
    height: '100%',
  },
  posterPlaceholder: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  matchBadge: {
    position: 'absolute',
    top: 6,
    left: 6,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 6,
  },
  matchText: {
    color: '#0f172a',
    fontWeight: '800',
    fontSize: 11,
  },
  content: {
    flex: 1,
    marginLeft: 12,
    justifyContent: 'space-between',
  },
  title: {
    fontSize: 16,
    fontWeight: '700',
    color: '#f8fafc',
    lineHeight: 20,
  },
  metaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 4,
  },
  metaText: {
    fontSize: 12,
    color: '#94a3b8',
  },
  metaDot: {
    fontSize: 12,
    color: '#64748b',
    marginHorizontal: 5,
  },
  langBadge: {
    fontSize: 10,
    fontWeight: '700',
    color: '#cbd5e1',
    backgroundColor: '#334155',
    paddingHorizontal: 4,
    paddingVertical: 1,
    borderRadius: 3,
  },
  reasonText: {
    fontSize: 12,
    color: '#38bdf8',
    marginTop: 6,
    fontStyle: 'italic',
  },
  tagRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
    marginTop: 6,
  },
  tagBadge: {
    backgroundColor: '#334155',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  tagText: {
    fontSize: 10,
    color: '#cbd5e1',
    fontWeight: '500',
  },
  moodBadge: {
    backgroundColor: 'rgba(56, 189, 248, 0.15)',
  },
  moodText: {
    color: '#38bdf8',
  },
  availabilityRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
    marginTop: 8,
  },
  providerChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: 'rgba(56, 189, 248, 0.1)',
    borderWidth: 1,
    borderColor: 'rgba(56, 189, 248, 0.3)',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  providerChipText: {
    fontSize: 10,
    color: '#e2e8f0',
    fontWeight: '600',
  },
  jellyfinChip: {
    backgroundColor: 'rgba(168, 85, 247, 0.15)',
    borderColor: 'rgba(168, 85, 247, 0.4)',
  },
  jellyfinChipText: {
    fontSize: 10,
    color: '#d8b4fe',
    fontWeight: '700',
  },
  actionBar: {
    flexDirection: 'row',
    borderTopWidth: 1,
    borderTopColor: '#334155',
    backgroundColor: '#162032',
  },
  actionBtn: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 10,
    gap: 4,
  },
  actionActive: {
    backgroundColor: 'rgba(245, 158, 11, 0.1)',
  },
  actionText: {
    fontSize: 11,
    color: '#94a3b8',
    fontWeight: '500',
  },
  actionActiveText: {
    color: '#f59e0b',
    fontWeight: '700',
  },
})
