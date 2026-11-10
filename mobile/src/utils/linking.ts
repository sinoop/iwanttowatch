import * as Linking from 'expo-linking'

/**
 * Open a streaming provider app via deep link or web fallback.
 */
export async function openStreamingProvider(providerName: string, filmTitle: string, fallbackUrl?: string | null): Promise<void> {
  const normalized = providerName.toLowerCase()
  const encodedTitle = encodeURIComponent(filmTitle)

  let candidateUrl = fallbackUrl

  if (normalized.includes('netflix')) {
    candidateUrl = `nflx://search?q=${encodedTitle}`
  } else if (normalized.includes('prime') || normalized.includes('amazon')) {
    candidateUrl = `primevideo://search?query=${encodedTitle}`
  } else if (normalized.includes('disney') || normalized.includes('hotstar')) {
    candidateUrl = `disneyplus://search?q=${encodedTitle}`
  } else if (normalized.includes('apple')) {
    candidateUrl = `videos://search?q=${encodedTitle}`
  }

  if (candidateUrl && candidateUrl.includes('://') && !candidateUrl.startsWith('http')) {
    try {
      const canOpen = await Linking.canOpenURL(candidateUrl)
      if (canOpen) {
        await Linking.openURL(candidateUrl)
        return
      }
    } catch {
      // Fall through to fallback web URL
    }
  }

  if (fallbackUrl) {
    try {
      await Linking.openURL(fallbackUrl)
    } catch {
      // Link couldn't be opened
    }
  }
}
