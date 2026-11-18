import type { Me } from '@iwanttowatch/api-client'
import { useState, type ReactNode } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router'
import { useServerSettings } from '../api'
import { segmentedTabClass } from '../tabs'
import { SegmentedCapsule } from '../ui'
import {
  SETTINGS_SECTIONS,
  buildSearchEntries,
  defaultPathForSection,
  visibleSubpages,
} from './settingsCatalog'

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

export function SearchIcon({ className = 'size-4' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8" />
      <path d="m21 21-4.3-4.3" />
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
  to: string
  badge?: ReactNode
}

interface NavSectionItem {
  id: string
  sectionPath: string
  to: string
  label: string
  icon: ReactNode
  badge?: ReactNode
  subItems?: SubMenuItem[]
}

const SECTION_ICONS: Record<string, ReactNode> = {
  profile: <UserIcon />,
  imports: <ImportIcon />,
  streaming: <TvIcon />,
  household: <HouseholdIcon />,
  integrations: <PlugIcon />,
  ai: <SparklesIcon />,
  declutter: <TrashIcon />,
  system: <ServerIcon />,
}

export function SettingsLayout({
  me,
  parentTitle,
  title,
  description,
  children,
}: {
  me: Me
  parentTitle?: string
  title: string
  description?: string
  children: ReactNode
}) {
  const settings = useServerSettings()
  const location = useLocation()
  const navigate = useNavigate()
  const [searchQuery, setSearchQuery] = useState('')

  const tmdbConfigured = settings.data?.tmdb_configured ?? false
  const jellyfinConnected = settings.data?.jellyfin.url !== null && settings.data?.jellyfin.url !== undefined
  const radarrConnected =
    Boolean(settings.data?.radarr.configured) &&
    settings.data?.radarr.url !== null &&
    settings.data?.radarr.url !== undefined
  const imdbEnabled = settings.data?.imdb.enabled ?? false
  const llmActive = (settings.data?.llm.order.length ?? 0) > 0
  const mcpEnabled = settings.data?.mcp_enabled ?? false

  const subBadge = (sectionId: string, subId: string): ReactNode | undefined => {
    if (sectionId === 'integrations') {
      if (subId === 'tmdb') {
        return <StatusBadge status={tmdbConfigured ? 'Connected' : 'Missing'} variant={tmdbConfigured ? 'green' : 'amber'} />
      }
      if (subId === 'jellyfin') {
        return <StatusBadge status={jellyfinConnected ? 'Connected' : 'Not connected'} variant={jellyfinConnected ? 'green' : 'neutral'} />
      }
      if (subId === 'radarr') {
        return <StatusBadge status={radarrConnected ? 'Connected' : 'Not connected'} variant={radarrConnected ? 'green' : 'neutral'} />
      }
      if (subId === 'imdb') {
        return <StatusBadge status={imdbEnabled ? 'On' : 'Off'} variant={imdbEnabled ? 'green' : 'neutral'} />
      }
    }
    if (sectionId === 'ai' && subId === 'ai-writing') {
      return <StatusBadge status={llmActive ? 'On' : 'Off'} variant={llmActive ? 'green' : 'neutral'} />
    }
    if (sectionId === 'system' && subId === 'mcp') {
      return <StatusBadge status={mcpEnabled ? 'On' : 'Off'} variant={mcpEnabled ? 'green' : 'neutral'} />
    }
    return undefined
  }

  const sectionBadge = (sectionId: string): ReactNode | undefined => {
    if (sectionId === 'integrations' && !tmdbConfigured) {
      return <span className="size-2 rounded-full bg-amber-400" title="TMDb API key required" />
    }
    if (sectionId === 'ai') {
      return (
        <span
          className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
            llmActive ? 'bg-emerald-500/15 text-emerald-300' : 'bg-white/10 text-white/50'
          }`}
        >
          {llmActive ? 'On' : 'Off'}
        </span>
      )
    }
    return undefined
  }

  const opts = { isAdmin: me.is_admin, isChild: me.is_child }

  const toNavItem = (section: (typeof SETTINGS_SECTIONS)[number]): NavSectionItem => {
    const subs = visibleSubpages(section, opts)
    return {
      id: section.id,
      sectionPath: `/settings/${section.id}`,
      to: defaultPathForSection(section, opts),
      label: section.title,
      icon: SECTION_ICONS[section.id] ?? <ServerIcon />,
      badge: sectionBadge(section.id),
      subItems:
        subs.length > 0
          ? subs.map((sub) => ({
              id: sub.id,
              label: sub.label,
              to: `/settings/${section.id}/${sub.id}`,
              badge: subBadge(section.id, sub.id),
            }))
          : undefined,
    }
  }

  const personalItems = SETTINGS_SECTIONS.filter((s) => s.group === 'personal').map(toNavItem)
  const adminItems = SETTINGS_SECTIONS.filter((s) => s.group === 'admin').map(toNavItem)
  const allVisibleItems = me.is_admin ? [...personalItems, ...adminItems] : personalItems

  const isPathInSection = (sectionPath: string) =>
    location.pathname === sectionPath || location.pathname.startsWith(`${sectionPath}/`)

  const currentActiveItem = allVisibleItems.find((item) => isPathInSection(item.sectionPath))

  const normalizedQuery = searchQuery.trim().toLowerCase()
  const searchResults = normalizedQuery
    ? buildSearchEntries(opts).filter((entry) =>
        normalizedQuery
          .split(/\s+/)
          .every((token) => entry.searchText.includes(token)),
      )
    : []

  const jumpTo = (to: string) => {
    void navigate(to)
    setSearchQuery('')
  }

  const searchBox = (
    <div className="relative">
      <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-white/40" />
      <input
        type="search"
        value={searchQuery}
        onChange={(e) => setSearchQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            setSearchQuery('')
          } else if (e.key === 'Enter' && searchResults.length > 0) {
            e.preventDefault()
            jumpTo(searchResults[0].to)
          }
        }}
        placeholder="Search settings…"
        aria-label="Search settings"
        className="w-full rounded-lg border border-white/10 bg-black/30 py-2 pr-8 pl-8 text-xs text-white placeholder-white/40 outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/30"
      />
      {searchQuery && (
        <button
          type="button"
          onClick={() => setSearchQuery('')}
          aria-label="Clear settings search"
          className="absolute top-1/2 right-2 -translate-y-1/2 rounded px-1 text-xs text-white/45 hover:text-white"
        >
          ✕
        </button>
      )}
    </div>
  )

  const searchResultsList = normalizedQuery ? (
    <div className="rounded-xl border border-white/10 bg-[#10141d] p-1.5 shadow-lg">
      {searchResults.length === 0 ? (
        <p className="px-2.5 py-3 text-xs text-white/50">No matching settings found.</p>
      ) : (
        <ul className="max-h-72 space-y-1 overflow-y-auto">
          {searchResults.map((entry) => {
            const active = location.pathname === entry.to
            return (
              <li key={entry.to}>
                <button
                  type="button"
                  onClick={() => jumpTo(entry.to)}
                  className={`w-full rounded-lg px-2.5 py-2 text-left transition-colors ${
                    active
                      ? 'bg-accent/15 text-accent-strong'
                      : 'text-white/80 hover:bg-white/5 hover:text-white'
                  }`}
                >
                  <span className="block text-[10px] font-medium uppercase tracking-wider text-white/45">
                    {entry.sectionTitle}
                  </span>
                  <span className="block text-xs font-semibold">{entry.title}</span>
                  <span className="mt-0.5 block text-[11px] text-white/50 line-clamp-1">
                    {entry.description}
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  ) : null

  return (
    <div className="md:flex md:items-start md:gap-8 lg:gap-10">
      {/* Mobile Search Bar */}
      <div className="md:hidden mb-3 space-y-2">
        {searchBox}
        {searchResultsList}
      </div>

      {/* Mobile horizontal tab rail */}
      <div className="md:hidden -mx-4 mb-4 overflow-x-auto px-4 pb-2 scrollbar-none">
        <SegmentedCapsule role="tablist" aria-label="Settings sections">
          {allVisibleItems.map((item) => {
            const active = isPathInSection(item.sectionPath)
            return (
              <NavLink
                key={item.id}
                to={item.to}
                className={() =>
                  segmentedTabClass({
                    active,
                    size: 'xs',
                    className: 'shrink-0',
                  })
                }
              >
                {item.icon}
                <span>{item.label}</span>
                {item.badge}
              </NavLink>
            )
          })}
        </SegmentedCapsule>
      </div>

      {/* Mobile secondary sub-menu pill rail */}
      {currentActiveItem?.subItems && (
        <div className="md:hidden -mx-4 -mt-2 mb-6 flex overflow-x-auto border-b border-white/5 px-4 pb-2.5 scrollbar-none gap-2">
          {currentActiveItem.subItems.map((sub) => (
            <NavLink
              key={sub.id}
              to={sub.to}
              className={({ isActive }) =>
                `flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors ${
                  isActive
                    ? 'border-accent bg-accent/15 text-accent-strong font-medium'
                    : 'border-white/10 bg-white/[0.03] text-white/75 hover:border-white/20 hover:text-white'
                }`
              }
            >
              <span>{sub.label}</span>
              {sub.badge}
            </NavLink>
          ))}
        </div>
      )}

      {/* Desktop Left Sidebar */}
      <aside className="hidden md:block w-60 shrink-0 lg:w-64">
        <div className="sticky top-6 space-y-5">
          {searchBox}
          {searchResultsList}

          {!normalizedQuery && (
            <>
              <div>
                <p className="px-3 mb-2 text-xs font-semibold uppercase tracking-wider text-white/40">Personal</p>
                <nav className="space-y-1">
                  {personalItems.map((item) => {
                    const isSectionActive = isPathInSection(item.sectionPath)
                    return (
                      <div key={item.id}>
                        <NavLink
                          to={item.to}
                          className={() =>
                            `flex items-center justify-between gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                              isSectionActive
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

                        {item.subItems && isSectionActive && (
                          <div className="ml-5 mt-1 space-y-0.5 border-l border-white/10 pl-2.5">
                            {item.subItems.map((sub) => (
                              <NavLink
                                key={sub.id}
                                to={sub.to}
                                className={({ isActive }) =>
                                  `flex items-center justify-between gap-2 rounded-md px-2 py-1.5 text-xs transition-colors ${
                                    isActive
                                      ? 'text-accent font-semibold bg-accent/10'
                                      : 'text-white/60 hover:bg-white/5 hover:text-white'
                                  }`
                                }
                              >
                                <span className="truncate">{sub.label}</span>
                                {sub.badge}
                              </NavLink>
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
                      const isSectionActive = isPathInSection(item.sectionPath)
                      const showSubItems = item.subItems && (isSectionActive || item.id === 'integrations')

                      return (
                        <div key={item.id}>
                          <NavLink
                            to={item.to}
                            className={() =>
                              `flex items-center justify-between gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                                isSectionActive
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

                          {showSubItems && item.subItems && (
                            <div className="ml-5 mt-1 space-y-0.5 border-l border-white/10 pl-2.5">
                              {item.subItems.map((sub) => (
                                <NavLink
                                  key={sub.id}
                                  to={sub.to}
                                  className={({ isActive }) =>
                                    `flex items-center justify-between gap-2 rounded-md px-2 py-1.5 text-xs transition-colors ${
                                      isSectionActive && isActive
                                        ? 'text-accent font-semibold bg-accent/10'
                                        : 'text-white/60 hover:bg-white/5 hover:text-white'
                                    }`
                                  }
                                >
                                  <span className="truncate">{sub.label}</span>
                                  {sub.badge}
                                </NavLink>
                              ))}
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </nav>
                </div>
              )}
            </>
          )}
        </div>
      </aside>

      {/* Main settings content panel */}
      <div className="min-w-0 flex-1 max-w-4xl">
        <div className="mb-6">
          {parentTitle && (
            <p className="mb-1 text-xs font-medium uppercase tracking-wider text-white/45">
              {parentTitle}
            </p>
          )}
          <h1 className="text-2xl font-semibold tracking-tight text-white">{title}</h1>
          {description && <p className="mt-1 text-sm text-white/60">{description}</p>}
        </div>
        {children}
      </div>
    </div>
  )
}
