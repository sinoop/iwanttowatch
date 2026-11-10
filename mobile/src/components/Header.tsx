import React from 'react'
import { StyleSheet, Text, View, TouchableOpacity } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { useServer } from '../context/ServerContext'

interface HeaderProps {
  onOpenServerModal: () => void
}

export function Header({ onOpenServerModal }: HeaderProps) {
  const { user, isConnected, serverUrl } = useServer()

  return (
    <View style={styles.container}>
      <View style={styles.titleRow}>
        <Text style={styles.logoText}>iWantToWatch</Text>
        <TouchableOpacity style={styles.serverBadge} onPress={onOpenServerModal} activeOpacity={0.7}>
          <View style={[styles.statusDot, isConnected ? styles.dotConnected : styles.dotDisconnected]} />
          <Text style={styles.serverHost} numberOfLines={1}>
            {serverUrl ? serverUrl.replace(/^https?:\/\//, '') : 'No server'}
          </Text>
          <Ionicons name="settings-outline" size={16} color="#94a3b8" style={styles.settingsIcon} />
        </TouchableOpacity>
      </View>

      {user ? (
        <View style={styles.userRow}>
          <Text style={styles.welcomeText}>
            Hi, <Text style={styles.userName}>{user.display_name || user.username}</Text>
          </Text>
          {user.is_admin ? <Text style={styles.adminBadge}>Admin</Text> : null}
        </View>
      ) : null}
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: '#0f172a',
    paddingHorizontal: 16,
    paddingTop: 12,
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#1e293b',
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  logoText: {
    fontSize: 20,
    fontWeight: '700',
    color: '#f8fafc',
    letterSpacing: -0.5,
  },
  serverBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#1e293b',
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 20,
    maxWidth: '55%',
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: 6,
  },
  dotConnected: {
    backgroundColor: '#10b981',
  },
  dotDisconnected: {
    backgroundColor: '#ef4444',
  },
  serverHost: {
    fontSize: 12,
    color: '#cbd5e1',
    flexShrink: 1,
  },
  settingsIcon: {
    marginLeft: 6,
  },
  userRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 6,
    gap: 8,
  },
  welcomeText: {
    fontSize: 13,
    color: '#94a3b8',
  },
  userName: {
    color: '#38bdf8',
    fontWeight: '600',
  },
  adminBadge: {
    fontSize: 10,
    color: '#e2e8f0',
    backgroundColor: '#334155',
    paddingHorizontal: 6,
    paddingVertical: 1,
    borderRadius: 4,
    textTransform: 'uppercase',
    fontWeight: '700',
  },
})
