import * as Linking from 'expo-linking'

export interface LaunchResult {
  launched: boolean
  label: string
  message?: string
}

export interface ProviderBrand {
  color: string
  shortLabel: string
}

interface ProviderLauncher {
  match: (normalizedName: string) => boolean
  buildUrls: (encodedTitle: string) => string[]
  brand: ProviderBrand
}

const TV_PROVIDER_LAUNCHERS: ProviderLauncher[] = [
  {
    match: (n) => n.includes('netflix'),
    buildUrls: (q) => [
      `nflx://www.netflix.com/search?q=${q}`,
      `https://www.netflix.com/search?q=${q}`,
    ],
    brand: { color: '#dc2626', shortLabel: 'Netflix' },
  },
  {
    match: (n) => n.includes('prime') || n.includes('amazon'),
    buildUrls: (q) => [
      `primevideo://search?query=${q}`,
      `https://app.primevideo.com/search?phrase=${q}`,
    ],
    brand: { color: '#0284c7', shortLabel: 'Prime Video' },
  },
  {
    match: (n) => n.includes('hotstar') || n.includes('jiohotstar'),
    buildUrls: (q) => [
      `hotstar://search?q=${q}`,
      `disneyplus://search?q=${q}`,
      `https://www.hotstar.com/in/explore?search_query=${q}`,
    ],
    brand: { color: '#2563eb', shortLabel: 'JioHotstar' },
  },
  {
    match: (n) => n.includes('disney'),
    buildUrls: (q) => [
      `disneyplus://search?q=${q}`,
      `https://www.disneyplus.com/search?q=${q}`,
    ],
    brand: { color: '#1d4ed8', shortLabel: 'Disney+' },
  },
  {
    match: (n) => n.includes('apple'),
    buildUrls: (q) => [
      `videos://search?q=${q}`,
      `https://tv.apple.com/search?term=${q}`,
    ],
    brand: { color: '#334155', shortLabel: 'Apple TV+' },
  },
  {
    match: (n) => n.includes('mubi'),
    buildUrls: (q) => [
      `mubi://search?q=${q}`,
      `https://mubi.com/en/search?query=${q}`,
    ],
    brand: { color: '#0f766e', shortLabel: 'MUBI' },
  },
  {
    match: (n) => n.includes('crunchyroll'),
    buildUrls: (q) => [
      `crunchyroll://search?q=${q}`,
      `https://www.crunchyroll.com/search?q=${q}`,
    ],
    brand: { color: '#ea580c', shortLabel: 'Crunchyroll' },
  },
  {
    match: (n) => n.includes('youtube'),
    buildUrls: (q) => [
      `vnd.youtube://results?search_query=${q}`,
      `https://www.youtube.com/results?search_query=${q}`,
    ],
    brand: { color: '#b91c1c', shortLabel: 'YouTube' },
  },
  {
    match: (n) => n.includes('sonyliv'),
    buildUrls: (q) => [
      `sonyliv://search?q=${q}`,
      `https://www.sonyliv.com/search?query=${q}`,
    ],
    brand: { color: '#4f46e5', shortLabel: 'SonyLIV' },
  },
  {
    match: (n) => n.includes('zee5'),
    buildUrls: (q) => [
      `zee5://search?q=${q}`,
      `https://www.zee5.com/search?q=${q}`,
    ],
    brand: { color: '#7c3aed', shortLabel: 'ZEE5' },
  },
  {
    match: (n) => n.includes('plex'),
    buildUrls: (q) => [
      `plex://search?query=${q}`,
      `https://app.plex.tv/desktop/#!/search?query=${q}`,
    ],
    brand: { color: '#ca8a04', shortLabel: 'Plex' },
  },
  {
    match: (n) => n.includes('tubi'),
    buildUrls: (q) => [
      `tubitv://search?q=${q}`,
      `https://tubitv.com/search/${q}`,
    ],
    brand: { color: '#9333ea', shortLabel: 'Tubi' },
  },
]

export function getProviderBrand(providerName: string): ProviderBrand {
  const normalized = providerName.toLowerCase()
  if (normalized.includes('jellyfin')) {
    return { color: '#7c3aed', shortLabel: 'Jellyfin' }
  }
  const found = TV_PROVIDER_LAUNCHERS.find((p) => p.match(normalized))
  return found ? found.brand : { color: '#475569', shortLabel: providerName }
}

async function tryOpenUrl(url: string): Promise<boolean> {
  try {
    const isCustomScheme = url.includes('://') && !url.startsWith('http')
    if (isCustomScheme) {
      const supported = await Linking.canOpenURL(url)
      if (!supported) return false
    }
    await Linking.openURL(url)
    return true
  } catch {
    return false
  }
}

/**
 * Extract Jellyfin item ID from a server-generated web URL like:
 * https://jf.example.com/web/index.html#!/details?id=abc123&serverId=xyz
 */
function extractJellyfinItemId(jellyfinUrl?: string | null): string | null {
  if (!jellyfinUrl) return null
  const match = jellyfinUrl.match(/[?&]id=([^&]+)/)
  return match ? decodeURIComponent(match[1]) : null
}

/**
 * Directly launch a movie in the Jellyfin Android TV app (or web fallback).
 */
export async function launchJellyfinMovie({
  jellyfinUrl,
  title,
}: {
  jellyfinUrl?: string | null
  title: string
}): Promise<LaunchResult> {
  const itemId = extractJellyfinItemId(jellyfinUrl)
  const candidates: string[] = []

  if (itemId) {
    candidates.push(`jellyfin://details?id=${encodeURIComponent(itemId)}`)
  }
  if (jellyfinUrl) {
    candidates.push(jellyfinUrl)
  }

  for (const url of candidates) {
    if (await tryOpenUrl(url)) {
      return { launched: true, label: 'Jellyfin' }
    }
  }

  return {
    launched: false,
    label: 'Jellyfin',
    message: `Could not open Jellyfin on this TV for "${title}". Make sure Jellyfin for Android TV is installed.`,
  }
}

/**
 * Directly launch a movie on the selected streaming service on Android TV.
 * Tries native TV app deep-link schemes first, then universal HTTPS app links,
 * and finally the JustWatch/TMDb fallback URL.
 */
export async function launchStreamingService({
  providerName,
  title,
  fallbackUrl,
}: {
  providerName: string
  title: string
  fallbackUrl?: string | null
}): Promise<LaunchResult> {
  const normalized = providerName.toLowerCase()
  const encodedTitle = encodeURIComponent(title)

  const launcher = TV_PROVIDER_LAUNCHERS.find((p) => p.match(normalized))
  const candidates = launcher ? launcher.buildUrls(encodedTitle) : []

  if (fallbackUrl) {
    candidates.push(fallbackUrl)
  }

  for (const url of candidates) {
    if (await tryOpenUrl(url)) {
      return { launched: true, label: providerName }
    }
  }

  return {
    launched: false,
    label: providerName,
    message: `Could not launch ${providerName} on this TV. Make sure the ${providerName} app is installed.`,
  }
}
