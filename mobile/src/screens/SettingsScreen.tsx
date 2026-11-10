import React from 'react'
import { StyleSheet, Text, View, TouchableOpacity, ScrollView } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { useServer } from '../context/ServerContext'

interface SettingsScreenProps {
  onOpenServerModal: () => void
}

export function SettingsScreen({ onOpenServerModal }: SettingsScreenProps) {
  const { serverUrl, isConnected, user, logout } = useServer()

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      {/* Server Connection Card */}
      <View style={styles.card}>
        <View style={styles.cardHeader}>
          <Text style={styles.cardTitle}>Docker Server Connection</Text>
          <View
            style={[
              styles.statusDot,
              isConnected ? styles.dotConnected : styles.dotDisconnected,
            ]}
          />
        </View>

        <Text style={styles.serverAddress}>{serverUrl || 'No server configured'}</Text>
        <Text style={styles.statusDescription}>
          {isConnected
            ? 'Connected and synchronized with self-hosted server.'
            : 'Unable to reach the server. Ensure Docker is running and Wi-Fi or VPN is active.'}
        </Text>

        <TouchableOpacity style={styles.actionButton} onPress={onOpenServerModal}>
          <Ionicons name="swap-horizontal-outline" size={16} color="#38bdf8" />
          <Text style={styles.actionButtonText}>Change Server or Account</Text>
        </TouchableOpacity>
      </View>

      {/* User Profile Card */}
      {user ? (
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Signed In Profile</Text>
          <View style={styles.infoRow}>
            <Text style={styles.infoLabel}>Username</Text>
            <Text style={styles.infoValue}>{user.username}</Text>
          </View>
          <View style={styles.infoRow}>
            <Text style={styles.infoLabel}>Display Name</Text>
            <Text style={styles.infoValue}>{user.display_name || user.username}</Text>
          </View>
          <View style={styles.infoRow}>
            <Text style={styles.infoLabel}>Region</Text>
            <Text style={styles.infoValue}>{user.region.toUpperCase()}</Text>
          </View>
          <View style={styles.infoRow}>
            <Text style={styles.infoLabel}>Preferred Languages</Text>
            <Text style={styles.infoValue}>{user.languages.join(', ') || 'Any'}</Text>
          </View>
          <View style={styles.infoRow}>
            <Text style={styles.infoLabel}>Role</Text>
            <Text style={styles.infoValue}>
              {user.is_child ? 'Child Profile' : user.is_admin ? 'Household Admin' : 'Member'}
            </Text>
          </View>

          <TouchableOpacity style={[styles.actionButton, styles.logoutBtn]} onPress={logout}>
            <Ionicons name="log-out-outline" size={16} color="#ef4444" />
            <Text style={[styles.actionButtonText, styles.logoutText]}>Sign Out</Text>
          </TouchableOpacity>
        </View>
      ) : null}

      {/* About Card */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>About iWantToWatch</Text>
        <Text style={styles.aboutText}>
          Self-hosted movie recommendations learned from your Jellyfin, IMDb, Letterboxd, and Trakt history.
        </Text>
        <View style={styles.infoRow}>
          <Text style={styles.infoLabel}>App Version</Text>
          <Text style={styles.infoValue}>0.1.1 (Phase 1 Mobile)</Text>
        </View>
        <View style={styles.infoRow}>
          <Text style={styles.infoLabel}>License</Text>
          <Text style={styles.infoValue}>AGPL-3.0-or-later</Text>
        </View>
        <View style={styles.infoRow}>
          <Text style={styles.infoLabel}>Architecture</Text>
          <Text style={styles.infoValue}>React Native + OpenAPI Client</Text>
        </View>
      </View>
    </ScrollView>
  )
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0b1120',
  },
  content: {
    padding: 16,
    gap: 16,
  },
  card: {
    backgroundColor: '#1e293b',
    borderRadius: 12,
    padding: 16,
    borderWidth: 1,
    borderColor: '#334155',
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  cardTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: '#f8fafc',
  },
  statusDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
  },
  dotConnected: {
    backgroundColor: '#10b981',
  },
  dotDisconnected: {
    backgroundColor: '#ef4444',
  },
  serverAddress: {
    fontSize: 14,
    color: '#38bdf8',
    fontWeight: '600',
    marginBottom: 4,
  },
  statusDescription: {
    fontSize: 13,
    color: '#94a3b8',
    lineHeight: 18,
    marginBottom: 14,
  },
  actionButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    backgroundColor: '#0f172a',
    borderWidth: 1,
    borderColor: '#334155',
    paddingVertical: 10,
    borderRadius: 8,
  },
  actionButtonText: {
    fontSize: 13,
    fontWeight: '600',
    color: '#38bdf8',
  },
  logoutBtn: {
    borderColor: 'rgba(239, 68, 68, 0.4)',
    marginTop: 12,
  },
  logoutText: {
    color: '#ef4444',
  },
  infoRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#334155',
  },
  infoLabel: {
    fontSize: 13,
    color: '#94a3b8',
  },
  infoValue: {
    fontSize: 13,
    color: '#f8fafc',
    fontWeight: '500',
  },
  aboutText: {
    fontSize: 13,
    color: '#94a3b8',
    lineHeight: 18,
    marginVertical: 8,
  },
})
