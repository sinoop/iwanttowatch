import AsyncStorage from '@react-native-async-storage/async-storage'
import type { QueryClient } from '@tanstack/react-query'

const STORAGE_KEY = 'iwanttowatch.queryCache.v1'
const MAX_AGE_MS = 1000 * 60 * 60 * 24 * 7 // 7 days
const PERSISTED_ROOT_KEYS = new Set(['feed', 'shortlist'])

interface PersistedEntry {
  queryKey: readonly unknown[]
  data: unknown
  updatedAt: number
}

/**
 * Hydrate cached feed/shortlist queries from AsyncStorage and persist updates.
 */
export async function hydrateQueryCache(queryClient: QueryClient): Promise<void> {
  try {
    const raw = await AsyncStorage.getItem(STORAGE_KEY)
    if (!raw) return
    const entries = JSON.parse(raw) as PersistedEntry[]
    const now = Date.now()
    for (const entry of entries) {
      if (now - entry.updatedAt <= MAX_AGE_MS && entry.data !== undefined) {
        queryClient.setQueryData(entry.queryKey, entry.data, { updatedAt: entry.updatedAt })
      }
    }
  } catch {
    // Ignore corrupt cache entries on startup.
  }
}

export function subscribeQueryPersistence(queryClient: QueryClient): () => void {
  let timer: ReturnType<typeof setTimeout> | null = null

  const save = async () => {
    try {
      const now = Date.now()
      const entries: PersistedEntry[] = []
      for (const query of queryClient.getQueryCache().getAll()) {
        const root = query.queryKey[0]
        if (typeof root !== 'string' || !PERSISTED_ROOT_KEYS.has(root)) continue
        if (query.state.status !== 'success' || query.state.data === undefined) continue
        if (now - query.state.dataUpdatedAt > MAX_AGE_MS) continue
        entries.push({
          queryKey: query.queryKey,
          data: query.state.data,
          updatedAt: query.state.dataUpdatedAt,
        })
      }
      await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(entries))
    } catch {
      // Ignore storage write errors.
    }
  }

  const unsubscribe = queryClient.getQueryCache().subscribe((event) => {
    if (event.type !== 'updated') return
    const root = event.query.queryKey[0]
    if (typeof root !== 'string' || !PERSISTED_ROOT_KEYS.has(root)) return
    if (event.query.state.status !== 'success') return
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      void save()
    }, 500)
  })

  return () => {
    if (timer) clearTimeout(timer)
    unsubscribe()
  }
}
