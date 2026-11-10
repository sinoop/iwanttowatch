import React, { useState } from 'react'
import {
  Modal,
  StyleSheet,
  Text,
  View,
  ScrollView,
  Image,
  TouchableOpacity,
  ActivityIndicator,
} from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import type { FeedItem } from '@iwanttowatch/api-client'
import { useServer } from '../context/ServerContext'
import { openStreamingProvider } from '../utils/linking'

interface MovieDetailModalProps {
  item: FeedItem | null
  visible: boolean
  onClose: () => void
}

export function MovieDetailModal({ item, visible, onClose }: MovieDetailModalProps) {
  const { client } = useServer()
  const [isTriggeringRadarr, setIsTriggeringRadarr] = useState(false)
  const [radarrStatus, setRadarrStatus] = useState<string | null>(null)

  if (!item) return null

  const posterUrl = item.poster_path
    ? `https://image.tmdb.org/t/p/w500${item.poster_path}`
    : null

  const handleDownloadRadarr = async () => {
    setIsTriggeringRadarr(true)
    setRadarrStatus(null)
    try {
      // POST to Radarr trigger endpoint
      const res = await client.POST('/api/v1/titles/{tmdb_id}/radarr', {
        params: { path: { tmdb_id: item.tmdb_id } },
      })
      if (res.data) {
        setRadarrStatus('Download queued in Radarr!')
      } else {
        setRadarrStatus('Radarr not configured or request failed')
      }
    } catch (err) {
      setRadarrStatus(err instanceof Error ? err.message : 'Download failed')
    } finally {
      setIsTriggeringRadarr(false)
    }
  }

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <View style={styles.overlay}>
        <View style={styles.sheet}>
          <View style={styles.header}>
            <Text style={styles.headerTitle} numberOfLines={1}>
              {item.title}
            </Text>
            <TouchableOpacity onPress={onClose} style={styles.closeBtn}>
              <Ionicons name="close" size={24} color="#94a3b8" />
            </TouchableOpacity>
          </View>

          <ScrollView contentContainerStyle={styles.content}>
            <View style={styles.heroRow}>
              {posterUrl ? (
                <Image source={{ uri: posterUrl }} style={styles.poster} resizeMode="cover" />
              ) : null}
              <View style={styles.heroMeta}>
                <Text style={styles.title}>{item.title}</Text>
                {item.original_title && item.original_title !== item.title ? (
                  <Text style={styles.originalTitle}>{item.original_title}</Text>
                ) : null}

                <View style={styles.metaRow}>
                  {item.year ? <Text style={styles.metaText}>{item.year}</Text> : null}
                  {item.runtime ? (
                    <Text style={styles.metaText}> • {item.runtime} mins</Text>
                  ) : null}
                  {item.certificate ? (
                    <Text style={styles.certBadge}>{item.certificate}</Text>
                  ) : null}
                </View>

                <View style={styles.matchContainer}>
                  <Text style={styles.matchPercent}>{item.match}% Taste Match</Text>
                </View>
              </View>
            </View>

            {/* Reasons */}
            {item.reasons && item.reasons.length > 0 ? (
              <View style={styles.section}>
                <Text style={styles.sectionHeading}>Why you might like this</Text>
                {item.reasons.map((r, i) => (
                  <Text key={i} style={styles.reasonText}>
                    • {r}
                  </Text>
                ))}
              </View>
            ) : null}

            {/* Where to Watch */}
            <View style={styles.section}>
              <Text style={styles.sectionHeading}>Where to Play Tonight</Text>
              <View style={styles.providersContainer}>
                {item.availability.on_jellyfin ? (
                  <TouchableOpacity
                    style={[styles.providerBtn, styles.jellyfinBtn]}
                    onPress={() =>
                      openStreamingProvider('Jellyfin', item.title, item.availability.link)
                    }
                  >
                    <Ionicons name="play-circle" size={18} color="#ffffff" />
                    <Text style={styles.providerBtnText}>Play on Jellyfin</Text>
                  </TouchableOpacity>
                ) : null}

                {item.availability.offers?.map((offer, idx) => (
                  <TouchableOpacity
                    key={`${offer.name}-${idx}`}
                    style={styles.providerBtn}
                    onPress={() =>
                      openStreamingProvider(offer.name, item.title, item.availability.link)
                    }
                  >
                    <Ionicons name="open-outline" size={16} color="#38bdf8" />
                    <Text style={styles.providerBtnText}>Watch on {offer.name}</Text>
                  </TouchableOpacity>
                ))}
              </View>
            </View>

            {/* Radarr trigger option */}
            <View style={styles.section}>
              <Text style={styles.sectionHeading}>Media Acquisition</Text>
              <TouchableOpacity
                style={[styles.btn, styles.radarrBtn]}
                onPress={handleDownloadRadarr}
                disabled={isTriggeringRadarr}
              >
                {isTriggeringRadarr ? (
                  <ActivityIndicator color="#ffffff" size="small" />
                ) : (
                  <>
                    <Ionicons name="cloud-download-outline" size={18} color="#ffffff" />
                    <Text style={styles.btnText}>Download via Radarr</Text>
                  </>
                )}
              </TouchableOpacity>
              {radarrStatus ? (
                <Text style={styles.radarrStatusText}>{radarrStatus}</Text>
              ) : null}
            </View>
          </ScrollView>
        </View>
      </View>
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
    maxHeight: '85%',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#1e293b',
  },
  headerTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: '#f8fafc',
    flex: 1,
  },
  closeBtn: {
    padding: 4,
  },
  content: {
    padding: 16,
    paddingBottom: 32,
  },
  heroRow: {
    flexDirection: 'row',
    marginBottom: 16,
  },
  poster: {
    width: 110,
    height: 165,
    borderRadius: 8,
  },
  heroMeta: {
    flex: 1,
    marginLeft: 14,
    justifyContent: 'center',
  },
  title: {
    fontSize: 18,
    fontWeight: '800',
    color: '#f8fafc',
  },
  originalTitle: {
    fontSize: 13,
    color: '#94a3b8',
    marginTop: 2,
    fontStyle: 'italic',
  },
  metaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 6,
    gap: 4,
  },
  metaText: {
    fontSize: 13,
    color: '#cbd5e1',
  },
  certBadge: {
    fontSize: 11,
    fontWeight: '700',
    color: '#94a3b8',
    borderWidth: 1,
    borderColor: '#475569',
    paddingHorizontal: 4,
    borderRadius: 3,
    marginLeft: 4,
  },
  matchContainer: {
    marginTop: 10,
    alignSelf: 'flex-start',
    backgroundColor: 'rgba(16, 185, 129, 0.15)',
    borderWidth: 1,
    borderColor: '#10b981',
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  matchPercent: {
    color: '#10b981',
    fontWeight: '700',
    fontSize: 12,
  },
  section: {
    marginTop: 16,
    borderTopWidth: 1,
    borderTopColor: '#1e293b',
    paddingTop: 14,
  },
  sectionHeading: {
    fontSize: 14,
    fontWeight: '700',
    color: '#e2e8f0',
    marginBottom: 8,
  },
  reasonText: {
    fontSize: 13,
    color: '#38bdf8',
    lineHeight: 18,
    marginBottom: 4,
  },
  providersContainer: {
    gap: 8,
  },
  providerBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: '#1e293b',
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#334155',
  },
  jellyfinBtn: {
    backgroundColor: '#9333ea',
    borderColor: '#a855f7',
  },
  providerBtnText: {
    color: '#ffffff',
    fontSize: 14,
    fontWeight: '600',
  },
  btn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    borderRadius: 8,
    paddingVertical: 12,
  },
  radarrBtn: {
    backgroundColor: '#0284c7',
  },
  btnText: {
    color: '#ffffff',
    fontWeight: '600',
    fontSize: 14,
  },
  radarrStatusText: {
    fontSize: 12,
    color: '#38bdf8',
    marginTop: 6,
    textAlign: 'center',
  },
})
