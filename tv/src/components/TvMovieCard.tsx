import React from 'react'
import { Image, StyleSheet, Text, View } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import type { FeedItem, GroupItem } from '@iwanttowatch/api-client'
import { TvFocusable } from './TvFocusable'
import { getProviderBrand } from '../utils/tvLaunching'

export type TvMovieItem = FeedItem | GroupItem

interface TvMovieCardProps {
  item: TvMovieItem
  onSelect: (item: TvMovieItem) => void
  hasTVPreferredFocus?: boolean
  cardWidth?: number
}

export function TvMovieCard({
  item,
  onSelect,
  hasTVPreferredFocus = false,
  cardWidth = 210,
}: TvMovieCardProps) {
  const posterUrl = item.poster_path
    ? `https://image.tmdb.org/t/p/w342${item.poster_path}`
    : null

  const seenProviders = new Set<string>()
  const badges: Array<{ label: string; color: string }> = []

  if (item.availability.on_jellyfin) {
    badges.push({ label: 'Jellyfin', color: '#7c3aed' })
  }
  for (const offer of item.availability.offers) {
    const brand = getProviderBrand(offer.name)
    if (!seenProviders.has(brand.shortLabel) && badges.length < 3) {
      seenProviders.add(brand.shortLabel)
      badges.push({ label: brand.shortLabel, color: brand.color })
    }
  }

  const posterHeight = Math.round(cardWidth * 1.48)

  return (
    <TvFocusable
      onPress={() => onSelect(item)}
      hasTVPreferredFocus={hasTVPreferredFocus}
      borderRadius={14}
      focusScale={1.05}
      style={[styles.card, { width: cardWidth }]}
    >
      <View style={[styles.posterWrap, { height: posterHeight }]}>
        {posterUrl ? (
          <Image source={{ uri: posterUrl }} style={styles.poster} resizeMode="cover" />
        ) : (
          <View style={styles.posterPlaceholder}>
            <Ionicons name="film-outline" size={44} color="#475569" />
          </View>
        )}

        <View style={styles.matchBadge}>
          <Text style={styles.matchText}>{item.match}%</Text>
        </View>

        {'shortlisted' in item && item.shortlisted ? (
          <View style={styles.shortlistBadge}>
            <Ionicons name="bookmark" size={14} color="#fef08a" />
          </View>
        ) : null}

        {item.imdb?.rating ? (
          <View style={styles.imdbBadge}>
            <Text style={styles.imdbText}>IMDb {item.imdb.rating.toFixed(1)}</Text>
          </View>
        ) : null}
      </View>

      <View style={styles.meta}>
        <Text style={styles.title} numberOfLines={1}>
          {item.title}
        </Text>
        <Text style={styles.subtitle} numberOfLines={1}>
          {item.year ?? '—'}
          {item.runtime ? ` • ${item.runtime}m` : ''}
          {item.genres.length > 0 ? ` • ${item.genres[0]}` : ''}
        </Text>

        {badges.length > 0 ? (
          <View style={styles.badgeRow}>
            {badges.map((b) => (
              <View key={b.label} style={[styles.providerPill, { backgroundColor: b.color }]}>
                <Text style={styles.providerText} numberOfLines={1}>
                  {b.label}
                </Text>
              </View>
            ))}
          </View>
        ) : null}
      </View>
    </TvFocusable>
  )
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: '#111827',
    borderRadius: 14,
    borderWidth: 2,
    borderColor: '#1f2937',
    overflow: 'hidden',
    margin: 10,
  },
  posterWrap: {
    width: '100%',
    backgroundColor: '#0f172a',
    position: 'relative',
  },
  poster: {
    width: '100%',
    height: '100%',
  },
  posterPlaceholder: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  matchBadge: {
    position: 'absolute',
    top: 10,
    left: 10,
    backgroundColor: 'rgba(15, 23, 42, 0.9)',
    borderWidth: 1,
    borderColor: '#4f46e5',
    borderRadius: 8,
    paddingHorizontal: 8,
    paddingVertical: 4,
  },
  matchText: {
    color: '#c7d2fe',
    fontSize: 13,
    fontWeight: '800',
  },
  shortlistBadge: {
    position: 'absolute',
    top: 10,
    right: 10,
    backgroundColor: 'rgba(15, 23, 42, 0.9)',
    borderRadius: 8,
    padding: 5,
  },
  imdbBadge: {
    position: 'absolute',
    bottom: 8,
    right: 8,
    backgroundColor: 'rgba(15, 23, 42, 0.88)',
    borderRadius: 6,
    paddingHorizontal: 6,
    paddingVertical: 3,
  },
  imdbText: {
    color: '#fbbf24',
    fontSize: 11,
    fontWeight: '700',
  },
  meta: {
    padding: 12,
    gap: 4,
  },
  title: {
    color: '#f8fafc',
    fontSize: 16,
    fontWeight: '700',
  },
  subtitle: {
    color: '#94a3b8',
    fontSize: 13,
  },
  badgeRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 5,
    marginTop: 6,
  },
  providerPill: {
    borderRadius: 6,
    paddingHorizontal: 7,
    paddingVertical: 3,
  },
  providerText: {
    color: '#ffffff',
    fontSize: 11,
    fontWeight: '700',
  },
})
