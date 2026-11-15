import React from 'react'
import { ActivityIndicator, FlatList, StyleSheet, Text, View } from 'react-native'
import { useQuery } from '@tanstack/react-query'
import { Ionicons } from '@expo/vector-icons'
import { useServer } from '../context/ServerContext'
import { TvMovieCard, type TvMovieItem } from '../components/TvMovieCard'

interface ShortlistScreenProps {
  onSelectMovie: (item: TvMovieItem) => void
}

export function ShortlistScreen({ onSelectMovie }: ShortlistScreenProps) {
  const { client, isConnected, user } = useServer()

  const { data, isLoading, error } = useQuery({
    queryKey: ['tv-shortlist', user?.id],
    queryFn: async () => {
      const res = await client.GET('/api/v1/feed', {
        params: { query: { shortlist: true, limit: 60 } },
      })
      if (res.error) throw new Error(String(res.error))
      return res.data
    },
    enabled: isConnected && !!user,
  })

  const items = data?.items ?? []

  if (isLoading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color="#818cf8" />
        <Text style={styles.statusText}>Loading shortlist...</Text>
      </View>
    )
  }

  if (error) {
    return (
      <View style={styles.center}>
        <Ionicons name="cloud-offline-outline" size={48} color="#f87171" />
        <Text style={styles.statusText}>Could not load shortlist.</Text>
      </View>
    )
  }

  if (items.length === 0) {
    return (
      <View style={styles.center}>
        <Ionicons name="bookmark-outline" size={56} color="#64748b" />
        <Text style={styles.emptyTitle}>Your Shortlist is Empty</Text>
        <Text style={styles.statusText}>
          Select any movie in Discover and choose Shortlist to save it for tonight.
        </Text>
      </View>
    )
  }

  return (
    <View style={styles.root}>
      <FlatList
        data={items}
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
    </View>
  )
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    paddingHorizontal: 26,
    paddingTop: 18,
  },
  grid: {
    paddingBottom: 40,
  },
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
    paddingHorizontal: 40,
  },
  emptyTitle: {
    color: '#f8fafc',
    fontSize: 22,
    fontWeight: '700',
  },
  statusText: {
    color: '#94a3b8',
    fontSize: 17,
    textAlign: 'center',
  },
})
