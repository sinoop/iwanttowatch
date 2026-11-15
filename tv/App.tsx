import React, { useState } from 'react'
import { ActivityIndicator, StyleSheet, View } from 'react-native'
import { StatusBar } from 'expo-status-bar'
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ServerProvider, useServer } from './src/context/ServerContext'
import { TopNav, type TvTab } from './src/components/TopNav'
import type { TvMovieItem } from './src/components/TvMovieCard'
import { ServerConnectScreen } from './src/screens/ServerConnectScreen'
import { DiscoverScreen } from './src/screens/DiscoverScreen'
import { ShortlistScreen } from './src/screens/ShortlistScreen'
import { TogetherScreen } from './src/screens/TogetherScreen'
import { SettingsScreen } from './src/screens/SettingsScreen'
import { MovieDetailModal } from './src/screens/MovieDetailModal'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5,
      retry: 1,
    },
  },
})

function TvShell() {
  const { isLoading, isConnected, user } = useServer()
  const [activeTab, setActiveTab] = useState<TvTab>('discover')
  const [selectedMovie, setSelectedMovie] = useState<TvMovieItem | null>(null)

  if (isLoading) {
    return (
      <View style={styles.loadingRoot}>
        <ActivityIndicator size="large" color="#818cf8" />
      </View>
    )
  }

  if (!isConnected || !user) {
    return <ServerConnectScreen />
  }

  return (
    <SafeAreaView style={styles.root}>
      <TopNav activeTab={activeTab} onSelectTab={setActiveTab} userName={user.display_name} />

      <View style={styles.body}>
        {activeTab === 'discover' ? (
          <DiscoverScreen onSelectMovie={setSelectedMovie} />
        ) : activeTab === 'shortlist' ? (
          <ShortlistScreen onSelectMovie={setSelectedMovie} />
        ) : activeTab === 'together' ? (
          <TogetherScreen onSelectMovie={setSelectedMovie} />
        ) : (
          <SettingsScreen />
        )}
      </View>

      <MovieDetailModal
        item={selectedMovie}
        visible={selectedMovie !== null}
        onClose={() => setSelectedMovie(null)}
      />
    </SafeAreaView>
  )
}

export default function App() {
  return (
    <SafeAreaProvider>
      <QueryClientProvider client={queryClient}>
        <ServerProvider>
          <StatusBar style="light" />
          <TvShell />
        </ServerProvider>
      </QueryClientProvider>
    </SafeAreaProvider>
  )
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: '#090d16',
  },
  loadingRoot: {
    flex: 1,
    backgroundColor: '#090d16',
    alignItems: 'center',
    justifyContent: 'center',
  },
  body: {
    flex: 1,
  },
})
