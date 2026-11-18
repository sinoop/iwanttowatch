export type SettingsGroup = 'personal' | 'admin'

export interface SettingsSubpageMeta {
  id: string
  label: string
  description: string
  keywords: string[]
  adminOnly?: boolean
  hideForChild?: boolean
}

export interface SettingsSectionMeta {
  id: string
  group: SettingsGroup
  title: string
  description: string
  keywords: string[]
  adminOnly?: boolean
  subpages?: SettingsSubpageMeta[]
}

export const SETTINGS_SECTIONS: SettingsSectionMeta[] = [
  {
    id: 'profile',
    group: 'personal',
    title: 'My Profile',
    description: 'Manage your preferred languages, default Discover feed, birth year, Jellyfin link, and taste sharing.',
    keywords: ['profile', 'account', 'preferences', 'personal'],
    subpages: [
      {
        id: 'languages',
        label: 'Languages',
        description: 'Order the film languages included in your recommendations and In Theatres discovery.',
        keywords: ['language', 'languages', 'regional', 'malayalam', 'hindi', 'tamil', 'iso', 'order', 'in theatres'],
      },
      {
        id: 'default-feed',
        label: 'Default Feed',
        description: 'Set your default Discover category, recently added streaming window, and Continue Watching shelf.',
        keywords: ['default feed', 'content', 'movies only', 'stand-up', 'concerts', 'recently added', 'streaming window', 'continue watching', 'shelf', 'discover'],
      },
      {
        id: 'birth-year',
        label: 'Birth Year',
        description: 'Adjust how older films released before your birth year are weighted in matches.',
        keywords: ['birth year', 'age', 'era', 'decade', 'older films'],
      },
      {
        id: 'jellyfin-account',
        label: 'Jellyfin Account',
        description: 'Link your personal Jellyfin account to sync watch history and favourites.',
        keywords: ['jellyfin', 'account', 'link', 'sign in', 'watch history', 'favourites'],
      },
      {
        id: 'taste-profile',
        label: 'Taste Profile',
        description: 'View and regenerate your AI-written taste summary.',
        keywords: ['taste profile', 'persona', 'ai summary', 'brief'],
        hideForChild: true,
      },
      {
        id: 'share-taste',
        label: 'Share Your Taste',
        description: 'Download a portable taste card or create a revocable link for Watch together.',
        keywords: ['share', 'taste card', 'link', 'watch together', 'friends'],
        hideForChild: true,
      },
    ],
  },
  {
    id: 'imports',
    group: 'personal',
    title: 'Import & Export',
    description: 'Import ratings from IMDb, Letterboxd, or Netflix, or export and restore your account data.',
    keywords: ['import', 'export', 'data'],
    subpages: [
      {
        id: 'import-ratings',
        label: 'Import Ratings',
        description: 'Upload IMDb ratings.csv, Letterboxd export ZIP, or Netflix viewing history.',
        keywords: ['import', 'imdb', 'letterboxd', 'netflix', 'csv', 'zip', 'ratings', 'history'],
      },
      {
        id: 'your-data',
        label: 'Your Data',
        description: 'Export all of your ratings and feedback as JSON or restore from a previous export.',
        keywords: ['export', 'restore', 'json', 'download', 'backup', 'your data'],
      },
    ],
  },
  {
    id: 'streaming',
    group: 'personal',
    title: 'Streaming Services',
    description: 'Choose your region and select the streaming providers you have access to.',
    keywords: ['streaming', 'services', 'providers', 'region', 'country', 'netflix', 'prime', 'disney', 'rent', 'buy'],
  },
  {
    id: 'household',
    group: 'personal',
    title: 'Household',
    description: 'Manage household member invite links and child profiles.',
    keywords: ['household', 'family', 'members'],
    subpages: [
      {
        id: 'invites',
        label: 'Household Invites',
        description: 'Create and revoke one-time invite links for new household members.',
        keywords: ['invites', 'invite link', 'add user', 'household', 'member'],
        adminOnly: true,
      },
      {
        id: 'child-profiles',
        label: 'Child Profiles',
        description: 'Create and manage age-filtered child profiles for your region.',
        keywords: ['child', 'kids', 'profiles', 'certificate', 'age limit', 'parental'],
      },
    ],
  },
  {
    id: 'integrations',
    group: 'admin',
    title: 'Integrations',
    description: 'Connect metadata providers, media servers, Radarr acquisition, and external rating datasets.',
    keywords: ['integrations', 'servers', 'connectors'],
    adminOnly: true,
    subpages: [
      {
        id: 'tmdb',
        label: 'TMDb',
        description: 'Configure your The Movie Database API key for film metadata and availability.',
        keywords: ['tmdb', 'api key', 'metadata', 'the movie database'],
      },
      {
        id: 'jellyfin',
        label: 'Jellyfin',
        description: 'Connect your Jellyfin server URL, API key, library sync, and webhook.',
        keywords: ['jellyfin', 'server', 'webhook', 'library', 'sync', 'api key'],
      },
      {
        id: 'radarr',
        label: 'Radarr',
        description: 'Connect Radarr, configure language root folders, Acquisition Radar, and background auto-downloads.',
        keywords: [
          'radarr',
          'acquisition radar',
          'auto-download',
          'automatic downloads',
          'hdd',
          'free space',
          'disk',
          'match %',
          'weekly cap',
          'vote floor',
          'released only',
          'quality profile',
          'root folder',
          'shortlist',
        ],
      },
      {
        id: 'imdb',
        label: 'IMDb',
        description: 'Enable daily public IMDb ratings and vote counts on film cards and scoring.',
        keywords: ['imdb', 'ratings', 'dataset', 'votes', 'public rating'],
      },
    ],
  },
  {
    id: 'ai',
    group: 'admin',
    title: 'AI & LLM',
    description: 'Configure AI writing providers (Gemini, Ollama, OpenAI-compatible, Claude) and inspect call logs.',
    keywords: ['ai', 'llm'],
    adminOnly: true,
    subpages: [
      {
        id: 'ai-writing',
        label: 'AI Writing',
        description: 'Configure Ollama, Gemini, OpenAI-compatible, or Claude providers, priority order, and web search.',
        keywords: ['ai writing', 'llm', 'ollama', 'gemini', 'openai', 'openrouter', 'claude', 'groq', 'searxng', 'web search', 'model', 'fallback'],
      },
      {
        id: 'ai-activity',
        label: 'AI Activity',
        description: 'Inspect recent LLM prompts, replies, latency, and errors.',
        keywords: ['ai activity', 'llm calls', 'prompts', 'replies', 'logs', 'history'],
      },
    ],
  },
  {
    id: 'declutter',
    group: 'admin',
    title: 'Declutter',
    description: 'Taste-driven library pruning: reclaim storage by safely removing disliked, abandoned, redundant, and cold movies.',
    keywords: ['declutter', 'prune', 'delete', 'storage', 'reclaim', 'low quality', 'disliked', 'abandoned', 'redundant', 'low match'],
    adminOnly: true,
  },
  {
    id: 'system',
    group: 'admin',
    title: 'System',
    description: 'Server logs, performance profiling, database compaction, backups, and MCP debugging access.',
    keywords: ['system', 'maintenance', 'admin'],
    adminOnly: true,
    subpages: [
      {
        id: 'logs',
        label: 'Server Logs',
        description: 'View and filter live in-app server and uvicorn logs.',
        keywords: ['server logs', 'logging', 'errors', 'warnings', 'uvicorn'],
      },
      {
        id: 'profiling',
        label: 'Profiling',
        description: 'Toggle per-request timing logs for movie popup and Radarr latency diagnostics.',
        keywords: ['profiling', 'timing', 'latency', 'performance', 'debug'],
      },
      {
        id: 'compaction',
        label: 'Compaction',
        description: 'Prune unreferenced cached metadata and run SQLite VACUUM.',
        keywords: ['compaction', 'vacuum', 'sqlite', 'database size', 'orphans', 'prune'],
      },
      {
        id: 'mcp',
        label: 'Debugging (MCP)',
        description: 'Manage the read-only Model Context Protocol server token.',
        keywords: ['mcp', 'debugging', 'token', 'model context protocol'],
      },
      {
        id: 'backups',
        label: 'Server Backups',
        description: 'Create, inspect, and download SQLite database backups.',
        keywords: ['backups', 'sqlite', 'snapshot', 'restore', 'download'],
      },
    ],
  },
]

const LEGACY_HASH_TO_SUBPAGE: Record<string, Record<string, string>> = {
  profile: {
    languages: 'languages',
    'content-filter': 'default-feed',
    'recently-added-days': 'default-feed',
    'continue-watching': 'default-feed',
    'birth-year': 'birth-year',
    'jellyfin-account': 'jellyfin-account',
    'taste-profile': 'taste-profile',
    'share-taste': 'share-taste',
  },
  imports: {
    'import-ratings': 'import-ratings',
    'your-data': 'your-data',
  },
  household: {
    invites: 'invites',
    'child-profiles': 'child-profiles',
  },
  integrations: {
    tmdb: 'tmdb',
    jellyfin: 'jellyfin',
    radarr: 'radarr',
    imdb: 'imdb',
  },
  ai: {
    'ai-writing': 'ai-writing',
    'ai-activity': 'ai-activity',
  },
  system: {
    logs: 'logs',
    profiling: 'profiling',
    compaction: 'compaction',
    mcp: 'mcp',
    backups: 'backups',
  },
}

export function visibleSubpages(
  section: SettingsSectionMeta,
  opts: { isAdmin: boolean; isChild: boolean },
): SettingsSubpageMeta[] {
  if (!section.subpages) return []
  return section.subpages.filter((sub) => {
    if (sub.adminOnly && !opts.isAdmin) return false
    if (sub.hideForChild && opts.isChild) return false
    return true
  })
}

export function defaultPathForSection(
  section: SettingsSectionMeta,
  opts: { isAdmin: boolean; isChild: boolean },
): string {
  const subs = visibleSubpages(section, opts)
  if (subs.length > 0) {
    return `/settings/${section.id}/${subs[0].id}`
  }
  return `/settings/${section.id}`
}

export function resolveLegacyHashPath(
  sectionId: string,
  hash: string,
): string | null {
  const cleanHash = hash.replace(/^#/, '')
  if (!cleanHash) return null
  const target = LEGACY_HASH_TO_SUBPAGE[sectionId]?.[cleanHash]
  return target ? `/settings/${sectionId}/${target}` : null
}

export interface SettingsSearchEntry {
  to: string
  sectionTitle: string
  title: string
  description: string
  searchText: string
}

export function buildSearchEntries(opts: {
  isAdmin: boolean
  isChild: boolean
}): SettingsSearchEntry[] {
  const entries: SettingsSearchEntry[] = []
  for (const section of SETTINGS_SECTIONS) {
    if (section.adminOnly && !opts.isAdmin) continue
    const subs = visibleSubpages(section, opts)
    if (subs.length > 0) {
      for (const sub of subs) {
        entries.push({
          to: `/settings/${section.id}/${sub.id}`,
          sectionTitle: section.title,
          title: sub.label,
          description: sub.description,
          searchText: [
            section.title,
            sub.label,
            sub.description,
            ...section.keywords,
            ...sub.keywords,
          ]
            .join(' ')
            .toLowerCase(),
        })
      }
    } else {
      entries.push({
        to: `/settings/${section.id}`,
        sectionTitle: section.group === 'admin' ? 'Server Admin' : 'Personal',
        title: section.title,
        description: section.description,
        searchText: [section.title, section.description, ...section.keywords].join(' ').toLowerCase(),
      })
    }
  }
  return entries
}
