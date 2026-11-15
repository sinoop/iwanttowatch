import React, { useMemo, useState } from 'react'
import {
  ActivityIndicator,
  FlatList,
  StyleSheet,
  Text,
  View,
} from 'react-native'
import { useQuery } from '@tanstack/react-query'
import { Ionicons } from '@expo/vector-icons'
import { useServer } from '../context/ServerContext'
import { TvFocusable } from '../components/TvFocusable'
import { TvMovieCard, type TvMovieItem } from '../components/TvMovieCard'

type FilterMode = 'all' | 'jellyfin' | 'streaming' | 'top'

interface DiscoverScreenProps {
  onSelectMovie: (item: TvMovieItem) => void
}

const FILTERS: Array<{ key: FilterMode; label: string }> = [
  { key: 'all', label: 'All Playable' },
  { key: 'jellyfin', label: 'On Jellyfin' },
  { key: 'streaming', label: 'Streaming Services' },
  { key: 'top', label: '80%+ Match' },
]

export function DiscoverScreen({ onSelectMovie }: DiscoverScreenProps) {
  const { client, isConnected, user } = useServer()
  const [filter, setFilter] = useState<FilterMode>('all')

  const { data, isLoading, isRefetching, refetch, error } = useQuery({
    queryKey: ['tv-feed', user?.id],
    queryFn: async () => {
      const res = await client.GET('/api/v1/feed', {
        params: { query: { sort: 'match', limit: 60 } },
      })
      if (res.error) throw new Error(String(res.error))
      return res.data
    },
    enabled: isConnected && !!user,
  })

  const filteredItems = useMemo(() => {
    const items = data?.items ?? []
    if (filter === 'jellyfin') return items.filter((i) => i.availability.on_jellyfin)
    if (filter === 'streaming') return items.filter((i) => i.availability.offers.length > 0)
    if (filter === 'top') return items.filter((i) => i.match >= 80)
    return items
  }, [data?.items, filter])

  return (
    <View style={styles.root}>
      <View style={styles.toolbar}>
        <View style={styles.filterRow}>
          {FILTERS.map((f) => {
            const active = filter === f.key
            return (
              <TvFocusable
                key={f.key}
                onPress={() => setFilter(f.key)}
                borderRadius={999}
                style={[styles.chip, active && styles.chipActive]}
              >
                <Text style={[styles.chipText, active && styles.chipTextActive]}>
                  {f.label}
                </Text>
              </TvFocusable>
            )
          })}
        </View>

        <TvFocusable
          onPress={() => refetch()}
          borderRadius={10}
          style={styles.refreshBtn}
        >
          <Ionicons
            name="refresh"
            size={18}
            color={isRefetching ? '#818cf8' : '#cbd5e1'}
          />
          <Text style={styles.refreshText}>Refresh</Text>
        </TvFocusable>
      </View>

      {isLoading ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color="#818cf8" />
          <Text style={styles.statusText}>Loading your recommendations...</Text>
        </View>
      ) : error ? (
        <View style={styles.center}>
          <Ionicons name="cloud-offline-outline" size={48} color="#f87171" />
          <Text style={styles.statusText}>Could not load feed from server.</Text>
        </View>
      ) : filteredItems.length === 0 ? (
        <View style={styles.center}>
          <Ionicons name="film-outline" size={48} color="#64748b" />
          <Text style={styles.statusText}>No matching movies found for this filter.</Text>
        </View>
      ) : (
        <FlatList
          data={filteredItems}
          keyExtractor={(item) => String(item.tmdb_id)}
          numColumns={4}
          contentContainerStyle={styles.grid}
          renderItem={({ item, index }) => (
            <TvMovieCard
              item={item}
              onSelect={onSelectMovie}
              hasTVPreferredFocus={index === 0}
            />
          )}
        />
      )}
    </View>
  )
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    paddingHorizontal: 26,
    paddingTop: 18,
  },
  toolbar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 10,
    marginBottom: 14,
  },
  filterRow: {
    flexDirection: 'row',
    gap: 10,
  },
  chip: {
    paddingHorizontal: 18,
    paddingVertical: 9,
    backgroundColor: '#111827',
    borderWidth: 2,
    borderColor: '#1f2937',
  },
  chipActive: {
    backgroundColor: '#312e81',
    borderColor: '#6366f1',
  },
  chipText: {
    color: '#94a3b8',
    fontSize: 15,
    fontWeight: '600',
  },
  chipTextActive: {
    color: '#e0e7ff',
    fontWeight: '700',
  },
  refreshBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 16,
    paddingVertical: 9,
    backgroundColor: '#111827',
    borderWidth: 2,
    borderColor: '#1f2937',
  },
  refreshText: {
    color: '#cbd5e1',
    fontSize: 15,
    fontWeight: '600',
  },
  grid: {
    paddingBottom: 40,
  },
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
  },
  statusText: {
    color: '#94a3b8',
    fontSize: 18,
  },
})
