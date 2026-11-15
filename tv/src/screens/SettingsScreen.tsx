import React from 'react'
import { StyleSheet, Text, View } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { useServer } from '../context/ServerContext'
import { TvFocusable } from '../components/TvFocusable'

export function SettingsScreen() {
  const { serverUrl, user, logout } = useServer()

  return (
    <View style={styles.root}>
      <View style={styles.card}>
        <Text style={styles.heading}>TV Connection & Account</Text>

        <View style={styles.row}>
          <Text style={styles.label}>Server URL</Text>
          <Text style={styles.value}>{serverUrl}</Text>
        </View>

        <View style={styles.row}>
          <Text style={styles.label}>Signed-in User</Text>
          <Text style={styles.value}>{user?.display_name ?? 'Not signed in'}</Text>
        </View>

        <View style={styles.row}>
          <Text style={styles.label}>Region</Text>
          <Text style={styles.value}>{user?.region ?? '—'}</Text>
        </View>

        <TvFocusable
          onPress={() => logout()}
          hasTVPreferredFocus
          borderRadius={12}
          style={styles.logoutBtn}
        >
          <Ionicons name="log-out-outline" size={20} color="#fecaca" />
          <Text style={styles.logoutText}>Sign Out / Switch User or Server</Text>
        </TvFocusable>
      </View>
    </View>
  )
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    padding: 40,
    alignItems: 'center',
  },
  card: {
    width: '100%',
    maxWidth: 720,
    backgroundColor: '#111827',
    borderRadius: 18,
    borderWidth: 1,
    borderColor: '#1f2937',
    padding: 32,
    gap: 20,
  },
  heading: {
    color: '#f8fafc',
    fontSize: 24,
    fontWeight: '800',
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: '#1f2937',
  },
  label: {
    color: '#94a3b8',
    fontSize: 16,
    fontWeight: '600',
  },
  value: {
    color: '#f8fafc',
    fontSize: 16,
    fontWeight: '700',
  },
  logoutBtn: {
    marginTop: 12,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
    backgroundColor: 'rgba(127, 29, 29, 0.5)',
    borderWidth: 2,
    borderColor: '#ef4444',
    paddingVertical: 14,
    paddingHorizontal: 22,
  },
  logoutText: {
    color: '#fecaca',
    fontSize: 16,
    fontWeight: '700',
  },
})
