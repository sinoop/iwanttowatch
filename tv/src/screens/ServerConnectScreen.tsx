import React, { useState } from 'react'
import {
  ActivityIndicator,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { useServer } from '../context/ServerContext'
import { TvFocusable } from '../components/TvFocusable'

export function ServerConnectScreen() {
  const { serverUrl, isConnected, setServerUrl, login, error } = useServer()
  const [urlInput, setUrlInput] = useState(serverUrl || 'http://192.168.1.100:8080')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)
  const [step, setStep] = useState<'server' | 'login'>(isConnected ? 'login' : 'server')

  const handleConnect = async () => {
    setBusy(true)
    setLocalError(null)
    const ok = await setServerUrl(urlInput)
    setBusy(false)
    if (ok) {
      setStep('login')
    } else {
      setLocalError('Could not reach iWantToWatch server at that URL.')
    }
  }

  const handleLogin = async () => {
    if (!username.trim()) {
      setLocalError('Enter your Jellyfin or local username.')
      return
    }
    setBusy(true)
    setLocalError(null)
    const ok = await login(username.trim(), password)
    setBusy(false)
    if (!ok) {
      setLocalError('Sign in failed. Check your username and password.')
    }
  }

  const displayError = localError || error

  return (
    <View style={styles.root}>
      <View style={styles.card}>
        <View style={styles.header}>
          <Ionicons name="tv" size={40} color="#818cf8" />
          <View>
            <Text style={styles.title}>iWantToWatch TV</Text>
            <Text style={styles.subtitle}>
              {step === 'server'
                ? 'Connect to your self-hosted iWantToWatch server'
                : `Sign in to ${serverUrl}`}
            </Text>
          </View>
        </View>

        {displayError ? (
          <View style={styles.errorBox}>
            <Ionicons name="warning-outline" size={20} color="#fca5a5" />
            <Text style={styles.errorText}>{displayError}</Text>
          </View>
        ) : null}

        {step === 'server' ? (
          <View style={styles.form}>
            <Text style={styles.label}>Server URL</Text>
            <TextInput
              style={styles.input}
              value={urlInput}
              onChangeText={setUrlInput}
              placeholder="http://192.168.1.100:8080"
              placeholderTextColor="#64748b"
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="url"
            />
            <TvFocusable
              onPress={handleConnect}
              hasTVPreferredFocus
              disabled={busy}
              style={styles.primaryBtn}
            >
              {busy ? (
                <ActivityIndicator color="#ffffff" />
              ) : (
                <Text style={styles.primaryBtnText}>Connect to Server</Text>
              )}
            </TvFocusable>
          </View>
        ) : (
          <View style={styles.form}>
            <Text style={styles.label}>Username (Jellyfin or Local)</Text>
            <TextInput
              style={styles.input}
              value={username}
              onChangeText={setUsername}
              placeholder="Username"
              placeholderTextColor="#64748b"
              autoCapitalize="none"
              autoCorrect={false}
            />

            <Text style={styles.label}>Password</Text>
            <TextInput
              style={styles.input}
              value={password}
              onChangeText={setPassword}
              placeholder="Password"
              placeholderTextColor="#64748b"
              secureTextEntry
            />

            <View style={styles.actions}>
              <TvFocusable
                onPress={handleLogin}
                hasTVPreferredFocus
                disabled={busy}
                style={[styles.primaryBtn, { flex: 1 }]}
              >
                {busy ? (
                  <ActivityIndicator color="#ffffff" />
                ) : (
                  <Text style={styles.primaryBtnText}>Sign In</Text>
                )}
              </TvFocusable>

              <TvFocusable
                onPress={() => setStep('server')}
                style={styles.secondaryBtn}
              >
                <Text style={styles.secondaryBtnText}>Change Server</Text>
              </TvFocusable>
            </View>
          </View>
        )}
      </View>
    </View>
  )
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: '#090d16',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 48,
  },
  card: {
    width: '100%',
    maxWidth: 640,
    backgroundColor: '#111827',
    borderRadius: 20,
    borderWidth: 1,
    borderColor: '#1f2937',
    padding: 36,
    gap: 24,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 16,
  },
  title: {
    color: '#f8fafc',
    fontSize: 28,
    fontWeight: '800',
  },
  subtitle: {
    color: '#94a3b8',
    fontSize: 16,
    marginTop: 4,
  },
  errorBox: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    backgroundColor: 'rgba(127, 29, 29, 0.4)',
    borderWidth: 1,
    borderColor: '#ef4444',
    borderRadius: 12,
    padding: 14,
  },
  errorText: {
    color: '#fecaca',
    fontSize: 15,
    flex: 1,
  },
  form: {
    gap: 14,
  },
  label: {
    color: '#cbd5e1',
    fontSize: 15,
    fontWeight: '600',
  },
  input: {
    backgroundColor: '#0f172a',
    borderWidth: 2,
    borderColor: '#334155',
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 14,
    color: '#f8fafc',
    fontSize: 18,
  },
  actions: {
    flexDirection: 'row',
    gap: 14,
    marginTop: 8,
  },
  primaryBtn: {
    backgroundColor: '#4f46e5',
    borderRadius: 12,
    paddingVertical: 16,
    paddingHorizontal: 24,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 2,
    borderColor: '#6366f1',
  },
  primaryBtnText: {
    color: '#ffffff',
    fontSize: 18,
    fontWeight: '700',
  },
  secondaryBtn: {
    backgroundColor: '#1e293b',
    borderRadius: 12,
    paddingVertical: 16,
    paddingHorizontal: 22,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 2,
    borderColor: '#334155',
  },
  secondaryBtnText: {
    color: '#e2e8f0',
    fontSize: 16,
    fontWeight: '600',
  },
})
