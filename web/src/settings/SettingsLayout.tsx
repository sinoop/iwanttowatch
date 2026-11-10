import type { Me } from '@iwanttowatch/api-client'
import { useEffect, type ReactNode } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router'
import { useServerSettings } from '../api'

export function UserIcon({ className = 'size-4' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  )
}

export function ImportIcon({ className = 'size-4' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  )
}

export function TvIcon({ className = 'size-4' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect width="20" height="15" x="2" y="7" rx="2" ry="2" />
      <polyline points="17 2 12 7 7 2" />
    </svg>
  )
}

export function HouseholdIcon({ className = 'size-4' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  )
}

export function PlugIcon({ className = 'size-4' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22v-5" />
      <path d="M9 8V2" />
      <path d="M15 8V2" />
      <path d="M18 8v5a6 6 0 0 1-12 0V8z" />
    </svg>
  )
}

export function SparklesIcon({ className = 'size-4' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z" />
      <path d="M5 3v4" />
      <path d="M3 5h4" />
    </svg>
  )
}

export function ServerIcon({ className = 'size-4' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect width="20" height="8" x="2" y="2" rx="2" ry="2" />
      <rect width="20" height="8" x="2" y="14" rx="2" ry="2" />
      <line x1="6" x2="6.01" y1="6" y2="6" />
      <line x1="6" x2="6.01" y1="18" y2="18" />
    </svg>
  )
}

export function TrashIcon({ className = 'size-4' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 6h18" />
      <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" />
      <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
      <line x1="10" x2="10" y1="11" y2="17" />
      <line x1="14" x2="14" y1="11" y2="17" />
    </svg>
  )
}

function StatusBadge({
  status,
  variant = 'neutral',
}: {
  status: string
  variant?: 'green' | 'amber' | 'neutral'
}) {
  const color =
    variant === 'green'
      ? 'bg-emerald-500/15 text-emerald-300'
      : variant === 'amber'
        ? 'bg-amber-500/15 text-amber-300'
        : 'bg-white/10 text-white/50'

  return <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium leading-none ${color}`}>{status}</span>
}

interface SubMenuItem {
  id: string
  label: string
  href: string
  badge?: ReactNode
}

interface NavSectionItem {
  id: string
  to: string
  label: string
  icon: ReactNode
  badge?: ReactNode
  subItems?: SubMenuItem[]
}

export function SettingsLayout({
  me,
  title,
  description,
  children,
}: {
  me: Me
  title: string
  description?: string
  children: ReactNode
}) {
  const settings = useServerSettings()
  const location = useLocation()
  const navigate = useNavigate()
  const activeHash = location.hash.replace('#', '')

  const tmdbConfigured = settings.data?.tmdb_configured ?? false
  const jellyfinConnected = settings.data?.jellyfin.url !== null && settings.data?.jellyfin.url !== undefined
  const radarrConnected =
    Boolean(settings.data?.radarr.configured) &&
    settings.data?.radarr.url !== null &&
    settings.data?.radarr.url !== undefined
  const imdbEnabled = settings.data?.imdb.enabled ?? false
  const llmActive = (settings.data?.llm.order.length ?? 0) > 0
  const mcpEnabled = settings.data?.mcp_enabled ?? false

  useEffect(() => {
    const hash = location.hash.replace('#', '')
    if (hash) {
      const el = document.getElementById(hash)
      if (el) {
        el.scrollIntoView({ behavior: 'smooth' })
      }
    }
  }, [location.pathname, location.hash])

  const scrollToId = (id: string, targetPath: string) => {
    if (location.pathname === targetPath) {
      const el = document.getElementById(id)
      if (el) {
        el.scrollIntoView({ behavior: 'smooth' })
        window.history.replaceState(null, '', `${targetPath}#${id}`)
      }
    } else {
      void navigate(`${targetPath}#${id}`)
    }
  }

  const personalItems: NavSectionItem[] = [
    {
      id: 'profile',
      to: '/settings/profile',
      label: 'My Profile',
      icon: <UserIcon />,
      subItems: [
        { id: 'birth-year', label: 'Birth Year', href: '/settings/profile#birth-year' },
        { id: 'jellyfin-account', label: 'Jellyfin Account', href: '/settings/profile#jellyfin-account' },
        { id: 'taste-profile', label: 'Taste Profile', href: '/settings/profile#taste-profile' },
        { id: 'share-taste', label: 'Share Your Taste', href: '/settings/profile#share-taste' },
      ],
    },
    {
      id: 'imports',
      to: '/settings/imports',
      label: 'Import & Export',
      icon: <ImportIcon />,
      subItems: [
        { id: 'import-ratings', label: 'Import Ratings', href: '/settings/imports#import-ratings' },
        { id: 'your-data', label: 'Your Data', href: '/settings/imports#your-data' },
      ],
    },
    { id: 'streaming', to: '/settings/streaming', label: 'Streaming Services', icon: <TvIcon /> },
    {
      id: 'household',
      to: '/settings/household',
      label: 'Household',
      icon: <HouseholdIcon />,
      subItems: [
        ...(me.is_admin ? [{ id: 'invites', label: 'Household Invites', href: '/settings/household#invites' }] : []),
        { id: 'child-profiles', label: 'Child Profiles', href: '/settings/household#child-profiles' },
      ],
    },
  ]

  const adminItems: NavSectionItem[] = [
    {
      id: 'integrations',
      to: '/settings/integrations',
      label: 'Integrations',
      icon: <PlugIcon />,
      badge: !tmdbConfigured ? (
        <span className="size-2 rounded-full bg-amber-400" title="TMDb API key required" />
      ) : undefined,
      subItems: [
        {
          id: 'tmdb',
          label: 'TMDb',
          href: '/settings/integrations#tmdb',
          badge: <StatusBadge status={tmdbConfigured ? 'Connected' : 'Missing'} variant={tmdbConfigured ? 'green' : 'amber'} />,
        },
        {
          id: 'jellyfin',
          label: 'Jellyfin',
          href: '/settings/integrations#jellyfin',
          badge: (
            <StatusBadge
              status={jellyfinConnected ? 'Connected' : 'Not connected'}
              variant={jellyfinConnected ? 'green' : 'neutral'}
            />
          ),
        },
        {
          id: 'radarr',
          label: 'Radarr',
          href: '/settings/integrations#radarr',
          badge: (
            <StatusBadge
              status={radarrConnected ? 'Connected' : 'Not connected'}
              variant={radarrConnected ? 'green' : 'neutral'}
            />
          ),
        },
        {
          id: 'imdb',
          label: 'IMDb',
          href: '/settings/integrations#imdb',
          badge: <StatusBadge status={imdbEnabled ? 'On' : 'Off'} variant={imdbEnabled ? 'green' : 'neutral'} />,
        },
      ],
    },
    {
      id: 'ai',
      to: '/settings/ai',
      label: 'AI & LLM',
      icon: <SparklesIcon />,
      badge: (
        <span
          className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
            llmActive ? 'bg-emerald-500/15 text-emerald-300' : 'bg-white/10 text-white/50'
          }`}
        >
          {llmActive ? 'On' : 'Off'}
        </span>
      ),
      subItems: [
        {
          id: 'ai-writing',
          label: 'AI Writing',
          href: '/settings/ai#ai-writing',
          badge: <StatusBadge status={llmActive ? 'On' : 'Off'} variant={llmActive ? 'green' : 'neutral'} />,
        },
        { id: 'ai-activity', label: 'AI Activity', href: '/settings/ai#ai-activity' },
      ],
    },
    {
      id: 'declutter',
      to: '/settings/declutter',
      label: 'Declutter',
      icon: <TrashIcon />,
    },
    {
      id: 'system',
      to: '/settings/system',
      label: 'System',
      icon: <ServerIcon />,
      subItems: [
        {
          id: 'mcp',
          label: 'Debugging (MCP)',
          href: '/settings/system#mcp',
          badge: <StatusBadge status={mcpEnabled ? 'On' : 'Off'} variant={mcpEnabled ? 'green' : 'neutral'} />,
        },
        { id: 'backups', label: 'Server Backups', href: '/settings/system#backups' },
      ],
    },
  ]

  const allVisibleItems = me.is_admin ? [...personalItems, ...adminItems] : personalItems
  const currentActiveItem = allVisibleItems.find((item) => location.pathname.startsWith(item.to))

  return (
    <div className="md:flex md:items-start md:gap-8 lg:gap-10">
      {/* Mobile horizontal tab rail */}
      <div className="md:hidden -mx-4 mb-4 flex overflow-x-auto border-b border-white/10 px-4 pb-3 scrollbar-none gap-2">
        {allVisibleItems.map((item) => (
          <NavLink
            key={item.id}
            to={item.to}
            className={({ isActive }) =>
              `flex shrink-0 items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-accent text-black font-semibold shadow-sm'
                  : 'bg-white/5 text-white/70 hover:bg-white/10 hover:text-white'
              }`
            }
          >
            {item.icon}
            <span>{item.label}</span>
            {item.badge}
          </NavLink>
        ))}
      </div>

      {/* Mobile secondary sub-menu pill rail */}
      {currentActiveItem?.subItems && (
        <div className="md:hidden -mx-4 -mt-2 mb-6 flex overflow-x-auto border-b border-white/5 px-4 pb-2.5 scrollbar-none gap-2">
          {currentActiveItem.subItems.map((sub) => (
            <a
              key={sub.id}
              href={sub.href}
              onClick={(e) => {
                e.preventDefault()
                scrollToId(sub.id, currentActiveItem.to)
              }}
              className={`flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors ${
                activeHash === sub.id
                  ? 'border-accent bg-accent/15 text-accent-strong font-medium'
                  : 'border-white/10 bg-white/[0.03] text-white/75 hover:border-white/20 hover:text-white'
              }`}
            >
              <span>{sub.label}</span>
              {sub.badge}
            </a>
          ))}
        </div>
      )}

      {/* Desktop Left Sidebar (Radarr style with Submenus) */}
      <aside className="hidden md:block w-60 shrink-0 lg:w-64">
        <div className="sticky top-6 space-y-6">
          <div>
            <p className="px-3 mb-2 text-xs font-semibold uppercase tracking-wider text-white/40">Personal</p>
            <nav className="space-y-1">
              {personalItems.map((item) => {
                const isSectionActive = location.pathname.startsWith(item.to)
                return (
                  <div key={item.id}>
                    <NavLink
                      to={item.to}
                      className={({ isActive }) =>
                        `flex items-center justify-between gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                          isActive
                            ? 'border-l-2 border-accent bg-accent/15 pl-2.5 text-accent-strong font-semibold'
                            : 'text-white/70 hover:bg-white/5 hover:text-white'
                        }`
                      }
                    >
                      <span className="flex min-w-0 items-center gap-2.5">
                        {item.icon}
                        <span className="truncate">{item.label}</span>
                      </span>
                      {item.badge}
                    </NavLink>

                    {/* Sub-menu items: shown when section is active */}
                    {item.subItems && isSectionActive && (
                      <div className="ml-5 mt-1 space-y-0.5 border-l border-white/10 pl-2.5">
                        {item.subItems.map((sub) => (
                          <a
                            key={sub.id}
                            href={sub.href}
                            onClick={(e) => {
                              e.preventDefault()
                              scrollToId(sub.id, item.to)
                            }}
                            className={`flex items-center justify-between gap-2 rounded-md px-2 py-1.5 text-xs transition-colors ${
                              activeHash === sub.id
                                ? 'text-accent font-semibold bg-accent/10'
                                : 'text-white/60 hover:bg-white/5 hover:text-white'
                            }`}
                          >
                            <span className="truncate">{sub.label}</span>
                            {sub.badge}
                          </a>
                        ))}
                      </div>
                    )}
                  </div>
                )
              })}
            </nav>
          </div>

          {me.is_admin && (
            <div className="border-t border-white/10 pt-4">
              <p className="px-3 mb-2 text-xs font-semibold uppercase tracking-wider text-white/40">Server Admin</p>
              <nav className="space-y-1">
                {adminItems.map((item) => {
                  const isSectionActive = location.pathname.startsWith(item.to)
                  // For Integrations, show sub-menu items so admin sees connectivity at all times
                  const showSubItems = item.subItems && (isSectionActive || item.id === 'integrations')

                  return (
                    <div key={item.id}>
                      <NavLink
                        to={item.to}
                        className={({ isActive }) =>
                          `flex items-center justify-between gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                            isActive
                              ? 'border-l-2 border-accent bg-accent/15 pl-2.5 text-accent-strong font-semibold'
                              : 'text-white/70 hover:bg-white/5 hover:text-white'
                          }`
                        }
                      >
                        <span className="flex min-w-0 items-center gap-2.5">
                          {item.icon}
                          <span className="truncate">{item.label}</span>
                        </span>
                        {item.badge}
                      </NavLink>

                      {/* Sub-menu items with status badges */}
                      {showSubItems && item.subItems && (
                        <div className="ml-5 mt-1 space-y-0.5 border-l border-white/10 pl-2.5">
                          {item.subItems.map((sub) => (
                            <a
                              key={sub.id}
                              href={sub.href}
                              onClick={(e) => {
                                e.preventDefault()
                                scrollToId(sub.id, item.to)
                              }}
                              className={`flex items-center justify-between gap-2 rounded-md px-2 py-1.5 text-xs transition-colors ${
                                isSectionActive && activeHash === sub.id
                                  ? 'text-accent font-semibold bg-accent/10'
                                  : 'text-white/60 hover:bg-white/5 hover:text-white'
                              }`}
                            >
                              <span className="truncate">{sub.label}</span>
                              {sub.badge}
                            </a>
                          ))}
                        </div>
                      )}
                    </div>
                  )
                })}
              </nav>
            </div>
          )}
        </div>
      </aside>

      {/* Main settings content panel */}
      <div className="min-w-0 flex-1 max-w-3xl">
        <div className="mb-6">
          <h1 className="text-2xl font-semibold tracking-tight text-white">{title}</h1>
          {description && <p className="mt-1 text-sm text-white/60">{description}</p>}
        </div>
        {children}
      </div>
    </div>
  )
}
