import React, { useEffect, useState } from 'react'
import { StyleSheet, View, Text, TouchableOpacity } from 'react-native'
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StatusBar } from 'expo-status-bar'
import { Ionicons } from '@expo/vector-icons'
import { ServerProvider } from './src/context/ServerContext'
import { Header } from './src/components/Header'
import { ServerSetupModal } from './src/components/ServerSetupModal'
import { FeedScreen } from './src/screens/FeedScreen'
import { ShortlistScreen } from './src/screens/ShortlistScreen'
import { SettingsScreen } from './src/screens/SettingsScreen'
import { hydrateQueryCache, subscribeQueryPersistence } from './src/utils/queryPersistence'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 minutes
      gcTime: 1000 * 60 * 60 * 24 * 7, // 7 days for offline cache
      networkMode: 'offlineFirst',
      retry: 1,
    },
  },
})

type Tab = 'discover' | 'shortlist' | 'settings'

function MainContent() {
  const [activeTab, setActiveTab] = useState<Tab>('discover')
  const [serverModalVisible, setServerModalVisible] = useState(false)

  useEffect(() => {
    void hydrateQueryCache(queryClient)
    return subscribeQueryPersistence(queryClient)
  }, [])

  return (
    <SafeAreaView style={styles.safeArea} edges={['top', 'left', 'right']}>
      <StatusBar style="light" />
      <Header onOpenServerModal={() => setServerModalVisible(true)} />

      <View style={styles.content}>
        {activeTab === 'discover' && (
          <FeedScreen onOpenServerModal={() => setServerModalVisible(true)} />
        )}
        {activeTab === 'shortlist' && <ShortlistScreen />}
        {activeTab === 'settings' && (
          <SettingsScreen onOpenServerModal={() => setServerModalVisible(true)} />
        )}
      </View>

      {/* Bottom Tab Bar */}
      <View style={styles.tabBar}>
        <TouchableOpacity
          style={styles.tabItem}
          onPress={() => setActiveTab('discover')}
          activeOpacity={0.7}
        >
          <Ionicons
            name={activeTab === 'discover' ? 'compass' : 'compass-outline'}
            size={22}
            color={activeTab === 'discover' ? '#38bdf8' : '#94a3b8'}
          />
          <Text
            style={[
              styles.tabLabel,
              activeTab === 'discover' ? styles.tabLabelActive : null,
            ]}
          >
            Discover
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={styles.tabItem}
          onPress={() => setActiveTab('shortlist')}
          activeOpacity={0.7}
        >
          <Ionicons
            name={activeTab === 'shortlist' ? 'bookmark' : 'bookmark-outline'}
            size={22}
            color={activeTab === 'shortlist' ? '#38bdf8' : '#94a3b8'}
          />
          <Text
            style={[
              styles.tabLabel,
              activeTab === 'shortlist' ? styles.tabLabelActive : null,
            ]}
          >
            Shortlist
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={styles.tabItem}
          onPress={() => setActiveTab('settings')}
          activeOpacity={0.7}
        >
          <Ionicons
            name={activeTab === 'settings' ? 'cog' : 'cog-outline'}
            size={22}
            color={activeTab === 'settings' ? '#38bdf8' : '#94a3b8'}
          />
          <Text
            style={[
              styles.tabLabel,
              activeTab === 'settings' ? styles.tabLabelActive : null,
            ]}
          >
            Settings
          </Text>
        </TouchableOpacity>
      </View>

      <ServerSetupModal
        visible={serverModalVisible}
        onClose={() => setServerModalVisible(false)}
      />
    </SafeAreaView>
  )
}

export default function App() {
  return (
    <SafeAreaProvider>
      <QueryClientProvider client={queryClient}>
        <ServerProvider>
          <MainContent />
        </ServerProvider>
      </QueryClientProvider>
    </SafeAreaProvider>
  )
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: '#0f172a',
  },
  content: {
    flex: 1,
    backgroundColor: '#0b1120',
  },
  tabBar: {
    flexDirection: 'row',
    backgroundColor: '#0f172a',
    borderTopWidth: 1,
    borderTopColor: '#1e293b',
    paddingVertical: 8,
    paddingBottom: 12,
  },
  tabItem: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 3,
  },
  tabLabel: {
    fontSize: 11,
    color: '#94a3b8',
    fontWeight: '500',
  },
  tabLabelActive: {
    color: '#38bdf8',
    fontWeight: '700',
  },
})
