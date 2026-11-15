import React, { useEffect, useState } from 'react'
import { ActivityIndicator, FlatList, StyleSheet, Text, View } from 'react-native'
import { useQuery } from '@tanstack/react-query'
import { Ionicons } from '@expo/vector-icons'
import { useServer } from '../context/ServerContext'
import { TvFocusable } from '../components/TvFocusable'
import { TvMovieCard, type TvMovieItem } from '../components/TvMovieCard'

interface TogetherScreenProps {
  onSelectMovie: (item: TvMovieItem) => void
}

export function TogetherScreen({ onSelectMovie }: TogetherScreenProps) {
  const { client, isConnected, user } = useServer()
  const [selectedUsers, setSelectedUsers] = useState<number[]>([])
  const [selectedGuests, setSelectedGuests] = useState<number[]>([])

  const { data: options } = useQuery({
    queryKey: ['tv-together-options', user?.id],
    queryFn: async () => {
      const res = await client.GET('/api/v1/together')
      if (!res.data) throw new Error('Could not load household options')
      return res.data
    },
    enabled: isConnected && !!user,
  })

  // Default to current user selected once options load
  useEffect(() => {
    if (user && selectedUsers.length === 0) {
      setSelectedUsers([user.id])
    }
  }, [user, selectedUsers.length])

  const { data: picks, isLoading } = useQuery({
    queryKey: ['tv-together-picks', selectedUsers, selectedGuests],
    queryFn: async () => {
      const res = await client.GET('/api/v1/together/picks', {
        params: {
          query: {
            users: selectedUsers,
            guests: selectedGuests,
            available_only: true,
            limit: 40,
          },
        },
      })
      if (!res.data) throw new Error('Could not load household options')
      return res.data
    },
    enabled: isConnected && !!user && selectedUsers.length + selectedGuests.length > 0,
  })

  const toggleUser = (id: number) => {
    setSelectedUsers((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    )
  }

  const toggleGuest = (id: number) => {
    setSelectedGuests((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    )
  }

  const items = picks?.items ?? []

  return (
    <View style={styles.root}>
      <View style={styles.peopleBar}>
        <Text style={styles.label}>Who is watching tonight?</Text>
        <View style={styles.chips}>
          {(options?.household ?? []).map((person) => {
            const active = selectedUsers.includes(person.id)
            return (
              <TvFocusable
                key={`u-${person.id}`}
                onPress={() => toggleUser(person.id)}
                borderRadius={999}
                style={[styles.personChip, active && styles.personChipActive]}
              >
                <Ionicons
                  name={active ? 'checkmark-circle' : 'person-outline'}
                  size={16}
                  color={active ? '#e0e7ff' : '#94a3b8'}
                />
                <Text style={[styles.chipText, active && styles.chipTextActive]}>
                  {person.name}
                </Text>
              </TvFocusable>
            )
          })}

          {(options?.guests ?? []).map((guest) => {
            const active = selectedGuests.includes(guest.id)
            return (
              <TvFocusable
                key={`g-${guest.id}`}
                onPress={() => toggleGuest(guest.id)}
                borderRadius={999}
                style={[styles.personChip, active && styles.personChipActive]}
              >
                <Ionicons
                  name={active ? 'checkmark-circle' : 'sparkles-outline'}
                  size={16}
                  color={active ? '#e0e7ff' : '#94a3b8'}
                />
                <Text style={[styles.chipText, active && styles.chipTextActive]}>
                  {guest.name} (Guest)
                </Text>
              </TvFocusable>
            )
          })}
        </View>
      </View>

      {selectedUsers.length + selectedGuests.length === 0 ? (
        <View style={styles.center}>
          <Ionicons name="people-outline" size={48} color="#64748b" />
          <Text style={styles.statusText}>
            Select at least one person above to get group picks.
          </Text>
        </View>
      ) : isLoading ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color="#818cf8" />
          <Text style={styles.statusText}>Finding movies everyone will enjoy...</Text>
        </View>
      ) : items.length === 0 ? (
        <View style={styles.center}>
          <Ionicons name="film-outline" size={48} color="#64748b" />
          <Text style={styles.statusText}>No playable group picks found.</Text>
        </View>
      ) : (
        <FlatList
          data={items}
          keyExtractor={(item) => String(item.tmdb_id)}
          numColumns={4}
          contentContainerStyle={styles.grid}
          renderItem={({ item, index }) => (
            <TvMovieCard
              item={item}
              onSelect={onSelectMovie}
              hasTVPreferredFocus={index === 0}
            />
          )}
        />
      )}
    </View>
  )
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    paddingHorizontal: 26,
    paddingTop: 18,
  },
  peopleBar: {
    paddingHorizontal: 10,
    marginBottom: 14,
    gap: 10,
  },
  label: {
    color: '#cbd5e1',
    fontSize: 16,
    fontWeight: '700',
  },
  chips: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  personChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 16,
    paddingVertical: 9,
    backgroundColor: '#111827',
    borderWidth: 2,
    borderColor: '#1f2937',
  },
  personChipActive: {
    backgroundColor: '#312e81',
    borderColor: '#6366f1',
  },
  chipText: {
    color: '#94a3b8',
    fontSize: 15,
    fontWeight: '600',
  },
  chipTextActive: {
    color: '#e0e7ff',
    fontWeight: '700',
  },
  grid: {
    paddingBottom: 40,
  },
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
  },
  statusText: {
    color: '#94a3b8',
    fontSize: 18,
  },
})
