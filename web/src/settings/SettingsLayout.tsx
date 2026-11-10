import type { Me } from '@iwanttowatch/api-client'
import { type ReactNode } from 'react'
import { NavLink } from 'react-router'
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

interface NavSectionItem {
  id: string
  to: string
  label: string
  icon: ReactNode
  badge?: ReactNode
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
  const tmdbMissing = settings.data && !settings.data.tmdb_configured
  const llmActive = (settings.data?.llm.order.length ?? 0) > 0

  const personalItems: NavSectionItem[] = [
    { id: 'profile', to: '/settings/profile', label: 'My Profile', icon: <UserIcon /> },
    { id: 'imports', to: '/settings/imports', label: 'Import & Export', icon: <ImportIcon /> },
    { id: 'streaming', to: '/settings/streaming', label: 'Streaming Services', icon: <TvIcon /> },
    { id: 'household', to: '/settings/household', label: 'Household', icon: <HouseholdIcon /> },
  ]

  const adminItems: NavSectionItem[] = [
    {
      id: 'integrations',
      to: '/settings/integrations',
      label: 'Integrations',
      icon: <PlugIcon />,
      badge: tmdbMissing ? (
        <span className="size-2 rounded-full bg-amber-400" title="TMDb API key required" />
      ) : undefined,
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
    },
    {
      id: 'declutter',
      to: '/settings/declutter',
      label: 'Declutter',
      icon: <TrashIcon />,
    },
    { id: 'system', to: '/settings/system', label: 'System', icon: <ServerIcon /> },
  ]

  const allVisibleItems = me.is_admin ? [...personalItems, ...adminItems] : personalItems

  return (
    <div className="md:flex md:items-start md:gap-8 lg:gap-10">
      {/* Mobile horizontal tab rail */}
      <div className="md:hidden -mx-4 mb-6 flex overflow-x-auto border-b border-white/10 px-4 pb-3 scrollbar-none gap-2">
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

      {/* Desktop Left Sidebar (Radarr style) */}
      <aside className="hidden md:block w-56 shrink-0 lg:w-60">
        <div className="sticky top-6 space-y-6">
          <div>
            <p className="px-3 mb-2 text-xs font-semibold uppercase tracking-wider text-white/40">Personal</p>
            <nav className="space-y-1">
              {personalItems.map((item) => (
                <NavLink
                  key={item.id}
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
              ))}
            </nav>
          </div>

          {me.is_admin && (
            <div className="border-t border-white/10 pt-4">
              <p className="px-3 mb-2 text-xs font-semibold uppercase tracking-wider text-white/40">Server Admin</p>
              <nav className="space-y-1">
                {adminItems.map((item) => (
                  <NavLink
                    key={item.id}
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
                ))}
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
