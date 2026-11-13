import React from 'react'
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native'
import { Ionicons } from '@expo/vector-icons'

export function OfflineBanner({
  error,
  onRetry,
}: {
  error: unknown
  onRetry: () => void
}) {
  if (!error) return null
  const message = error instanceof Error ? error.message : 'Unable to reach server'

  return (
    <TouchableOpacity style={styles.banner} onPress={onRetry} activeOpacity={0.8}>
      <Ionicons name="cloud-offline-outline" size={18} color="#fbbf24" />
      <View style={styles.textWrap}>
        <Text style={styles.title}>Offline — showing cached data</Text>
        <Text style={styles.subtitle} numberOfLines={1}>
          {message} · Tap to retry
        </Text>
      </View>
      <Ionicons name="refresh" size={16} color="#fbbf24" />
    </TouchableOpacity>
  )
}

const styles = StyleSheet.create({
  banner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    backgroundColor: 'rgba(245, 158, 11, 0.14)',
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(245, 158, 11, 0.3)',
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  textWrap: {
    flex: 1,
  },
  title: {
    color: '#fde68a',
    fontSize: 13,
    fontWeight: '600',
  },
  subtitle: {
    color: '#fcd34d',
    fontSize: 11,
    opacity: 0.85,
  },
})
