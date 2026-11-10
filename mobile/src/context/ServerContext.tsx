import React, { createContext, useContext, useEffect, useState, useMemo, useCallback } from 'react'
import AsyncStorage from '@react-native-async-storage/async-storage'
import { createApiClient, type Me } from '@iwanttowatch/api-client'

interface ServerContextValue {
  serverUrl: string
  setServerUrl: (url: string) => Promise<boolean>
  client: ReturnType<typeof createApiClient>
  user: Me | null
  isConnected: boolean
  isLoading: boolean
  error: string | null
  login: (username: string, password: string) => Promise<boolean>
  logout: () => Promise<void>
  refreshUser: () => Promise<void>
}

const SERVER_URL_KEY = '@iwanttowatch:server_url'
const DEFAULT_SERVER_URL = 'http://localhost:8000'

const ServerContext = createContext<ServerContextValue | null>(null)

export function ServerProvider({ children }: { children: React.ReactNode }) {
  const [serverUrl, setInternalServerUrl] = useState<string>('')
  const [user, setUser] = useState<Me | null>(null)
  const [isConnected, setIsConnected] = useState<boolean>(false)
  const [isLoading, setIsLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)

  // Clean trailing slashes
  const normalizedBaseUrl = useMemo(() => {
    return (serverUrl || '').trim().replace(/\/+$/, '')
  }, [serverUrl])

  const client = useMemo(() => {
    return createApiClient(normalizedBaseUrl)
  }, [normalizedBaseUrl])

  const refreshUser = useCallback(async () => {
    if (!normalizedBaseUrl) {
      setUser(null)
      setIsConnected(false)
      return
    }

    try {
      const { data, error: apiError } = await client.GET('/api/v1/me')
      if (data) {
        setUser(data)
        setIsConnected(true)
        setError(null)
      } else if (apiError) {
        // Connected to server, but unauthorized / not logged in
        setUser(null)
        setIsConnected(true)
        setError(null)
      }
    } catch (err) {
      setIsConnected(false)
      setUser(null)
      setError(err instanceof Error ? err.message : 'Cannot connect to server')
    }
  }, [client, normalizedBaseUrl])

  // Load saved server URL on mount
  useEffect(() => {
    async function init() {
      try {
        const savedUrl = await AsyncStorage.getItem(SERVER_URL_KEY)
        if (savedUrl) {
          setInternalServerUrl(savedUrl)
        } else {
          setInternalServerUrl(DEFAULT_SERVER_URL)
        }
      } catch {
        setInternalServerUrl(DEFAULT_SERVER_URL)
      } finally {
        setIsLoading(false)
      }
    }
    init()
  }, [])

  // Verify connection when serverUrl changes
  useEffect(() => {
    if (serverUrl) {
      refreshUser()
    }
  }, [serverUrl, refreshUser])

  const setServerUrl = async (url: string): Promise<boolean> => {
    const cleaned = url.trim().replace(/\/+$/, '')
    try {
      const tempClient = createApiClient(cleaned)
      const res = await tempClient.GET('/api/v1/setup')
      if (res.data !== undefined) {
        await AsyncStorage.setItem(SERVER_URL_KEY, cleaned)
        setInternalServerUrl(cleaned)
        setIsConnected(true)
        setError(null)
        await refreshUser()
        return true
      }
      setError('Invalid iWantToWatch server endpoint')
      return false
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not reach server')
      return false
    }
  }

  const login = async (username: string, password: string): Promise<boolean> => {
    try {
      setError(null)
      const { data, error: loginErr } = await client.POST('/api/v1/auth/login', {
        body: { username, password },
      })
      if (data) {
        setUser(data)
        setIsConnected(true)
        return true
      }
      setError(loginErr ? String(loginErr) : 'Login failed')
      return false
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
      return false
    }
  }

  const logout = async () => {
    try {
      await client.POST('/api/v1/auth/logout')
    } catch {
      // Ignore logout network errors
    } finally {
      setUser(null)
    }
  }

  return (
    <ServerContext.Provider
      value={{
        serverUrl: normalizedBaseUrl,
        setServerUrl,
        client,
        user,
        isConnected,
        isLoading,
        error,
        login,
        logout,
        refreshUser,
      }}
    >
      {children}
    </ServerContext.Provider>
  )
}

export function useServer(): ServerContextValue {
  const ctx = useContext(ServerContext)
  if (!ctx) {
    throw new Error('useServer must be used within a ServerProvider')
  }
  return ctx
}
