import React, { useState } from 'react'
import {
  StyleSheet,
  View,
  FlatList,
  Text,
  ActivityIndicator,
  RefreshControl,
  TouchableOpacity,
} from 'react-native'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { FeedItem } from '@iwanttowatch/api-client'
import { useServer } from '../context/ServerContext'
import { MovieCard } from '../components/MovieCard'
import { OfflineBanner } from '../components/OfflineBanner'
import { MovieDetailModal } from './MovieDetailModal'
import { Ionicons } from '@expo/vector-icons'

export function ShortlistScreen() {
  const { client, isConnected, user } = useServer()
  const queryClient = useQueryClient()
  const [selectedFilm, setSelectedFilm] = useState<FeedItem | null>(null)

  const {
    data: shortlistData,
    isLoading,
    isRefetching,
    refetch,
    error,
  } = useQuery({
    queryKey: ['shortlist', user?.id],
    queryFn: async () => {
      const res = await client.GET('/api/v1/feed', {
        params: { query: { shortlist: true } },
      })
      if (res.error) throw new Error(String(res.error))
      return res.data
    },
    enabled: isConnected && !!user,
  })

  const removeShortlistMutation = useMutation({
    mutationFn: async (tmdbId: number) => {
      await client.DELETE('/api/v1/titles/{tmdb_id}/shortlist', {
        params: { path: { tmdb_id: tmdbId } },
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['shortlist'] })
      queryClient.invalidateQueries({ queryKey: ['feed'] })
    },
  })

  const feedbackMutation = useMutation({
    mutationFn: async ({
      tmdbId,
      kind,
    }: {
      tmdbId: number
      kind: 'up' | 'down' | 'dismissed' | 'snoozed'
    }) => {
      await client.PUT('/api/v1/titles/{tmdb_id}/feedback', {
        params: { path: { tmdb_id: tmdbId } },
        body: { kind },
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['shortlist'] })
      queryClient.invalidateQueries({ queryKey: ['feed'] })
    },
  })

  if (!isConnected || !user) {
    return (
      <View style={styles.centerContainer}>
        <Ionicons name="bookmark-outline" size={56} color="#64748b" />
        <Text style={styles.emptyTitle}>Your Shortlist</Text>
        <Text style={styles.emptySubtitle}>
          Connect to your server and sign in to view films you have saved to watch tonight.
        </Text>
      </View>
    )
  }

  if (isLoading && !shortlistData) {
    return (
      <View style={styles.centerContainer}>
        <ActivityIndicator size="large" color="#38bdf8" />
        <Text style={styles.loadingText}>Loading shortlist...</Text>
      </View>
    )
  }

  if (error && !shortlistData) {
    return (
      <View style={styles.centerContainer}>
        <Ionicons name="alert-circle-outline" size={48} color="#ef4444" />
        <Text style={styles.emptyTitle}>Could not load shortlist</Text>
        <Text style={styles.emptySubtitle}>
          {error instanceof Error ? error.message : 'Unknown error'}
        </Text>
        <TouchableOpacity style={styles.retryBtn} onPress={() => { void refetch() }}>
          <Text style={styles.retryBtnText}>Try Again</Text>
        </TouchableOpacity>
      </View>
    )
  }

  const items = shortlistData?.items || []

  return (
    <View style={styles.container}>
      <OfflineBanner error={error} onRetry={() => { void refetch() }} />
      <FlatList
        data={items}
        keyExtractor={(item) => String(item.tmdb_id)}
        renderItem={({ item }) => (
          <MovieCard
            item={item}
            isShortlisted={true}
            onFeedback={(tmdbId, kind) => feedbackMutation.mutate({ tmdbId, kind })}
            onToggleShortlist={(tmdbId) => removeShortlistMutation.mutate(tmdbId)}
            onPressDetail={setSelectedFilm}
          />
        )}
        contentContainerStyle={styles.listContent}
        refreshControl={
          <RefreshControl
            refreshing={isRefetching}
            onRefresh={() => { void refetch() }}
            tintColor="#38bdf8"
            colors={['#38bdf8']}
          />
        }
        ListEmptyComponent={
          <View style={styles.centerContainer}>
            <Ionicons name="bookmark-outline" size={48} color="#64748b" />
            <Text style={styles.emptyTitle}>No films shortlisted yet</Text>
            <Text style={styles.emptySubtitle}>
              Tap the Shortlist button on any recommendation card in Discover to save it for tonight.
            </Text>
          </View>
        }
      />

      <MovieDetailModal
        item={selectedFilm}
        visible={!!selectedFilm}
        onClose={() => setSelectedFilm(null)}
      />
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0b1120',
  },
  listContent: {
    paddingVertical: 10,
  },
  centerContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 24,
    backgroundColor: '#0b1120',
  },
  loadingText: {
    marginTop: 12,
    fontSize: 14,
    color: '#94a3b8',
  },
  emptyTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: '#f8fafc',
    marginTop: 14,
    textAlign: 'center',
  },
  emptySubtitle: {
    fontSize: 14,
    color: '#94a3b8',
    marginTop: 8,
    textAlign: 'center',
    lineHeight: 20,
    maxWidth: 320,
  },
  retryBtn: {
    backgroundColor: '#2563eb',
    paddingVertical: 10,
    paddingHorizontal: 20,
    borderRadius: 8,
    marginTop: 16,
  },
  retryBtnText: {
    color: '#ffffff',
    fontSize: 14,
    fontWeight: '600',
  },
})
