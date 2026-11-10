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
import { MovieDetailModal } from './MovieDetailModal'
import { Ionicons } from '@expo/vector-icons'

export function FeedScreen({ onOpenServerModal }: { onOpenServerModal: () => void }) {
  const { client, isConnected, user } = useServer()
  const queryClient = useQueryClient()
  const [selectedFilm, setSelectedFilm] = useState<FeedItem | null>(null)
  const [shortlistedIds, setShortlistedIds] = useState<Set<number>>(new Set())

  // Fetch feed
  const {
    data: feedData,
    isLoading,
    isRefetching,
    refetch,
    error,
  } = useQuery({
    queryKey: ['feed', user?.id],
    queryFn: async () => {
      const res = await client.GET('/api/v1/feed', {
        params: { query: { sort: 'match', limit: 30 } },
      })
      if (res.error) throw new Error(String(res.error))
      return res.data
    },
    enabled: isConnected && !!user,
  })

  // Feedback mutation (like, dislike, dismiss)
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
      queryClient.invalidateQueries({ queryKey: ['feed'] })
    },
  })

  // Shortlist toggle mutation
  const shortlistMutation = useMutation({
    mutationFn: async (tmdbId: number) => {
      const isCurrentlyShortlisted = shortlistedIds.has(tmdbId)
      if (isCurrentlyShortlisted) {
        await client.DELETE('/api/v1/titles/{tmdb_id}/shortlist', {
          params: { path: { tmdb_id: tmdbId } },
        })
      } else {
        await client.PUT('/api/v1/titles/{tmdb_id}/shortlist', {
          params: { path: { tmdb_id: tmdbId } },
        })
      }
    },
    onMutate: (tmdbId) => {
      setShortlistedIds((prev) => {
        const next = new Set(prev)
        if (next.has(tmdbId)) next.delete(tmdbId)
        else next.add(tmdbId)
        return next
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['shortlist'] })
      queryClient.invalidateQueries({ queryKey: ['feed'] })
    },
  })

  const handleFeedback = (tmdbId: number, kind: 'up' | 'down' | 'dismissed' | 'snoozed') => {
    feedbackMutation.mutate({ tmdbId, kind })
  }

  const handleToggleShortlist = (tmdbId: number) => {
    shortlistMutation.mutate(tmdbId)
  }

  if (!isConnected || !user) {
    return (
      <View style={styles.centerContainer}>
        <Ionicons name="cloud-offline-outline" size={56} color="#64748b" />
        <Text style={styles.emptyTitle}>
          {!isConnected ? 'Not Connected to Server' : 'Please Sign In'}
        </Text>
        <Text style={styles.emptySubtitle}>
          {!isConnected
            ? 'Connect to your self-hosted iWantToWatch Docker server to load personalized recommendations.'
            : 'Sign in with your Jellyfin credentials to access your taste feed.'}
        </Text>
        <TouchableOpacity style={styles.connectBtn} onPress={onOpenServerModal}>
          <Text style={styles.connectBtnText}>
            {!isConnected ? 'Configure Server' : 'Sign In'}
          </Text>
        </TouchableOpacity>
      </View>
    )
  }

  if (isLoading) {
    return (
      <View style={styles.centerContainer}>
        <ActivityIndicator size="large" color="#38bdf8" />
        <Text style={styles.loadingText}>Ranking recommendations...</Text>
      </View>
    )
  }

  if (error) {
    return (
      <View style={styles.centerContainer}>
        <Ionicons name="alert-circle-outline" size={48} color="#ef4444" />
        <Text style={styles.emptyTitle}>Could not load recommendations</Text>
        <Text style={styles.emptySubtitle}>{error instanceof Error ? error.message : 'Unknown error'}</Text>
        <TouchableOpacity style={styles.connectBtn} onPress={() => { void refetch() }}>
          <Text style={styles.connectBtnText}>Try Again</Text>
        </TouchableOpacity>
      </View>
    )
  }

  const items = feedData?.items || []

  return (
    <View style={styles.container}>
      <FlatList
        data={items}
        keyExtractor={(item) => String(item.tmdb_id)}
        renderItem={({ item }) => (
          <MovieCard
            item={item}
            isShortlisted={shortlistedIds.has(item.tmdb_id)}
            onFeedback={handleFeedback}
            onToggleShortlist={handleToggleShortlist}
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
            <Ionicons name="film-outline" size={48} color="#64748b" />
            <Text style={styles.emptyTitle}>No recommendations right now</Text>
            <Text style={styles.emptySubtitle}>
              Try rating a few more films or adjusting your streaming filters.
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
  connectBtn: {
    backgroundColor: '#2563eb',
    paddingVertical: 12,
    paddingHorizontal: 24,
    borderRadius: 8,
    marginTop: 20,
  },
  connectBtnText: {
    color: '#ffffff',
    fontSize: 15,
    fontWeight: '600',
  },
})
