import React from 'react'
import { StyleSheet, Text, View } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { TvFocusable } from './TvFocusable'

export type TvTab = 'discover' | 'shortlist' | 'together' | 'settings'

interface TopNavProps {
  activeTab: TvTab
  onSelectTab: (tab: TvTab) => void
  userName?: string | null
}

const NAV_ITEMS: Array<{
  key: TvTab
  label: string
  icon: React.ComponentProps<typeof Ionicons>['name']
}> = [
  { key: 'discover', label: 'Discover', icon: 'sparkles' },
  { key: 'shortlist', label: 'Shortlist', icon: 'bookmark' },
  { key: 'together', label: 'Watch Together', icon: 'people' },
  { key: 'settings', label: 'Settings', icon: 'settings' },
]

export function TopNav({ activeTab, onSelectTab, userName }: TopNavProps) {
  return (
    <View style={styles.bar}>
      <View style={styles.brand}>
        <Ionicons name="tv" size={24} color="#818cf8" />
        <Text style={styles.brandText}>iWantToWatch</Text>
      </View>

      <View style={styles.tabs}>
        {NAV_ITEMS.map((item) => {
          const active = activeTab === item.key
          return (
            <TvFocusable
              key={item.key}
              onPress={() => onSelectTab(item.key)}
              borderRadius={10}
              focusScale={1.06}
              style={[styles.tab, active && styles.tabActive]}
            >
              <Ionicons
                name={item.icon}
                size={18}
                color={active ? '#ffffff' : '#94a3b8'}
              />
              <Text style={[styles.tabText, active && styles.tabTextActive]}>
                {item.label}
              </Text>
            </TvFocusable>
          )
        })}
      </View>

      <View style={styles.userPill}>
        <Ionicons name="person-circle-outline" size={20} color="#cbd5e1" />
        <Text style={styles.userText}>{userName || 'Guest'}</Text>
      </View>
    </View>
  )
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 36,
    paddingVertical: 18,
    backgroundColor: '#0b1120',
    borderBottomWidth: 1,
    borderBottomColor: '#1e293b',
  },
  brand: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  brandText: {
    color: '#f8fafc',
    fontSize: 22,
    fontWeight: '800',
    letterSpacing: -0.3,
  },
  tabs: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  tab: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 18,
    paddingVertical: 10,
    backgroundColor: '#111827',
    borderWidth: 2,
    borderColor: '#1f2937',
  },
  tabActive: {
    backgroundColor: '#4f46e5',
    borderColor: '#6366f1',
  },
  tabText: {
    color: '#94a3b8',
    fontSize: 16,
    fontWeight: '600',
  },
  tabTextActive: {
    color: '#ffffff',
    fontWeight: '700',
  },
  userPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 999,
    backgroundColor: '#111827',
    borderWidth: 1,
    borderColor: '#1f2937',
  },
  userText: {
    color: '#e2e8f0',
    fontSize: 15,
    fontWeight: '600',
  },
})
