import React, { useState } from 'react'
import {
  Modal,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  ActivityIndicator,
  ScrollView,
  KeyboardAvoidingView,
  Platform,
} from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { useServer } from '../context/ServerContext'

interface ServerSetupModalProps {
  visible: boolean
  onClose: () => void
}

export function ServerSetupModal({ visible, onClose }: ServerSetupModalProps) {
  const { serverUrl, setServerUrl, isConnected, user, login, logout, error } = useServer()
  const [urlInput, setUrlInput] = useState(serverUrl)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [localMessage, setLocalMessage] = useState<string | null>(null)

  const handleSaveUrl = async () => {
    setIsSubmitting(true)
    setLocalMessage(null)
    try {
      const ok = await setServerUrl(urlInput)
      if (ok) {
        setLocalMessage('Connected to server successfully!')
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleLogin = async () => {
    if (!username.trim() || !password) return
    setIsSubmitting(true)
    setLocalMessage(null)
    try {
      const ok = await login(username.trim(), password)
      if (ok) {
        setUsername('')
        setPassword('')
        setLocalMessage('Logged in successfully!')
        onClose()
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleLogout = async () => {
    setIsSubmitting(true)
    try {
      await logout()
      setLocalMessage('Logged out')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={styles.overlay}
      >
        <View style={styles.sheet}>
          <View style={styles.sheetHeader}>
            <Text style={styles.sheetTitle}>Server & Account</Text>
            <TouchableOpacity onPress={onClose} style={styles.closeBtn}>
              <Ionicons name="close" size={24} color="#94a3b8" />
            </TouchableOpacity>
          </View>

          <ScrollView contentContainerStyle={styles.content}>
            {/* Server Connection Section */}
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>Docker Server Address</Text>
              <Text style={styles.sectionSubtitle}>
                Enter the HTTP/HTTPS address of your running iWantToWatch container.
              </Text>
              <View style={styles.inputRow}>
                <TextInput
                  style={styles.input}
                  value={urlInput}
                  onChangeText={setUrlInput}
                  placeholder="e.g. http://192.168.1.50:8000"
                  placeholderTextColor="#64748b"
                  autoCapitalize="none"
                  autoCorrect={false}
                />
                <TouchableOpacity
                  style={[styles.btn, styles.btnPrimary]}
                  onPress={handleSaveUrl}
                  disabled={isSubmitting}
                >
                  <Text style={styles.btnText}>Test & Connect</Text>
                </TouchableOpacity>
              </View>

              <View style={styles.statusIndicator}>
                <View
                  style={[
                    styles.statusDot,
                    isConnected ? styles.dotConnected : styles.dotDisconnected,
                  ]}
                />
                <Text style={styles.statusText}>
                  {isConnected ? 'Server Online' : 'Not Connected'}
                </Text>
              </View>
            </View>

            {/* Error / Status Messages */}
            {error || localMessage ? (
              <View
                style={[
                  styles.alertBox,
                  error ? styles.alertError : styles.alertSuccess,
                ]}
              >
                <Text style={styles.alertText}>{error || localMessage}</Text>
              </View>
            ) : null}

            {/* Account Section */}
            {user ? (
              <View style={styles.section}>
                <Text style={styles.sectionTitle}>Active Account</Text>
                <View style={styles.userCard}>
                  <Text style={styles.userName}>{user.display_name || user.username}</Text>
                  <Text style={styles.userDetails}>
                    Region: {user.region.toUpperCase()} • Languages: {user.languages.join(', ')}
                  </Text>
                </View>
                <TouchableOpacity
                  style={[styles.btn, styles.btnDanger]}
                  onPress={handleLogout}
                  disabled={isSubmitting}
                >
                  <Text style={styles.btnText}>Sign Out</Text>
                </TouchableOpacity>
              </View>
            ) : isConnected ? (
              <View style={styles.section}>
                <Text style={styles.sectionTitle}>Sign In</Text>
                <Text style={styles.sectionSubtitle}>
                  Sign in with your Jellyfin username/password or local iWantToWatch credentials.
                </Text>

                <TextInput
                  style={[styles.input, styles.formInput]}
                  value={username}
                  onChangeText={setUsername}
                  placeholder="Username"
                  placeholderTextColor="#64748b"
                  autoCapitalize="none"
                  autoCorrect={false}
                />
                <TextInput
                  style={[styles.input, styles.formInput]}
                  value={password}
                  onChangeText={setPassword}
                  placeholder="Password"
                  placeholderTextColor="#64748b"
                  secureTextEntry
                />

                <TouchableOpacity
                  style={[styles.btn, styles.btnPrimary, styles.submitBtn]}
                  onPress={handleLogin}
                  disabled={isSubmitting}
                >
                  {isSubmitting ? (
                    <ActivityIndicator color="#ffffff" size="small" />
                  ) : (
                    <Text style={styles.btnText}>Sign In</Text>
                  )}
                </TouchableOpacity>
              </View>
            ) : null}
          </ScrollView>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  )
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.7)',
    justifyContent: 'flex-end',
  },
  sheet: {
    backgroundColor: '#0f172a',
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    maxHeight: '90%',
    paddingBottom: 24,
  },
  sheetHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#1e293b',
  },
  sheetTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: '#f8fafc',
  },
  closeBtn: {
    padding: 4,
  },
  content: {
    padding: 16,
  },
  section: {
    marginBottom: 24,
  },
  sectionTitle: {
    fontSize: 15,
    fontWeight: '600',
    color: '#e2e8f0',
    marginBottom: 4,
  },
  sectionSubtitle: {
    fontSize: 13,
    color: '#94a3b8',
    marginBottom: 12,
  },
  inputRow: {
    gap: 10,
  },
  input: {
    backgroundColor: '#1e293b',
    borderWidth: 1,
    borderColor: '#334155',
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: '#f8fafc',
    fontSize: 14,
  },
  formInput: {
    marginBottom: 10,
  },
  btn: {
    borderRadius: 8,
    paddingVertical: 12,
    paddingHorizontal: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  btnPrimary: {
    backgroundColor: '#2563eb',
  },
  btnDanger: {
    backgroundColor: '#dc2626',
    marginTop: 8,
  },
  submitBtn: {
    marginTop: 4,
  },
  btnText: {
    color: '#ffffff',
    fontWeight: '600',
    fontSize: 14,
  },
  statusIndicator: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 10,
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
  statusText: {
    fontSize: 13,
    color: '#cbd5e1',
  },
  alertBox: {
    padding: 12,
    borderRadius: 8,
    marginBottom: 16,
  },
  alertError: {
    backgroundColor: 'rgba(239, 68, 68, 0.15)',
    borderColor: '#ef4444',
    borderWidth: 1,
  },
  alertSuccess: {
    backgroundColor: 'rgba(16, 185, 129, 0.15)',
    borderColor: '#10b981',
    borderWidth: 1,
  },
  alertText: {
    fontSize: 13,
    color: '#f8fafc',
  },
  userCard: {
    backgroundColor: '#1e293b',
    padding: 14,
    borderRadius: 8,
    marginBottom: 8,
  },
  userName: {
    fontSize: 16,
    fontWeight: '700',
    color: '#f8fafc',
  },
  userDetails: {
    fontSize: 13,
    color: '#94a3b8',
    marginTop: 4,
  },
})
