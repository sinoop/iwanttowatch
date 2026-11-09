import type { Me } from '@iwanttowatch/api-client'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet } from 'react-router'
import { api, useChildren, useServerSettings } from './api'
import HeaderSearch from './Search'
import { JustWatchCredit } from './Streaming'
import { Button, Logo } from './ui'

const NAV = [
  { to: '/', label: 'Discover' },
  { to: '/together', label: 'Watch together' },
  { to: '/taste', label: 'My taste' },
  { to: '/settings', label: 'Settings' },
]

export default function Shell({ me }: { me: Me }) {
  const queryClient = useQueryClient()
  const settings = useServerSettings()
  const isChild = me.is_child
  const children = useChildren()
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menuOpen) return
    const onPointerDown = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false)
      }
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMenuOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [menuOpen])

  const refreshProfile = (next: Me | undefined) => {
    setMenuOpen(false)
    if (next) queryClient.setQueryData(['me'], next)
    for (const key of ['feed', 'ratings', 'persona', 'together', 'title']) {
      queryClient.invalidateQueries({ queryKey: [key] })
    }
  }
  const switchChild = useMutation({
    mutationFn: async (childId: number) =>
      (await api.POST('/api/v1/children/{child_id}/switch', { params: { path: { child_id: childId } } })).data,
    onSuccess: refreshProfile,
  })
  const exitChild = useMutation({
    mutationFn: async () => (await api.POST('/api/v1/children/exit')).data,
    onSuccess: refreshProfile,
  })
  const logout = useMutation({
    mutationFn: () => api.POST('/api/v1/auth/logout'),
    onSuccess: () => queryClient.setQueryData(['me'], null),
  })
  const navItems = isChild ? NAV.filter((item) => item.to !== '/settings') : NAV
  const kids = children.data ?? []
  const canSwitch = kids.length > 0 || isChild

  return (
    <div className="min-h-screen">
      <header className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-white/10 px-4 py-3 sm:px-6">
        <Logo />
        <nav className="order-last flex w-full overflow-x-auto sm:order-none sm:w-auto sm:gap-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                `whitespace-nowrap rounded-lg px-2 py-1.5 text-sm transition-colors sm:px-3 ${
                  isActive ? 'bg-white/10 text-white' : 'text-white/60 hover:text-white'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto flex flex-wrap items-center gap-2 text-sm sm:gap-3">
          <HeaderSearch />
          {canSwitch ? (
            <div ref={menuRef} className="relative">
              <button
                type="button"
                aria-expanded={menuOpen}
                aria-haspopup="menu"
                onClick={() => setMenuOpen(!menuOpen)}
                className="flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1.5 text-white/85 transition-colors hover:border-white/25 hover:text-white focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:outline-none"
              >
                <span>{me.display_name}</span>
                {me.max_certificate && (
                  <span className="rounded bg-accent/15 px-1.5 py-0.5 text-xs font-medium text-accent-strong">
                    {me.max_certificate}
                  </span>
                )}
                <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden className="size-3.5 text-white/50">
                  <path d="m5 7.5 5 5 5-5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
              {menuOpen && (
                <div
                  role="menu"
                  aria-label="Switch profile"
                  className="absolute right-0 z-20 mt-1.5 min-w-52 rounded-xl border border-white/10 bg-[#151922] p-1.5 shadow-2xl shadow-black/70"
                >
                  {isChild && (
                    <button
                      type="button"
                      role="menuitem"
                      disabled={exitChild.isPending}
                      onClick={() => exitChild.mutate()}
                      className="flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-2 text-left text-xs font-medium text-accent-strong hover:bg-white/10"
                    >
                      <span>Back to adult profile</span>
                      <span aria-hidden>↩</span>
                    </button>
                  )}
                  {kids.length > 0 && (
                    <p className="px-2.5 pt-1.5 pb-1 text-[11px] font-medium tracking-wide text-white/40 uppercase">
                      Child profiles
                    </p>
                  )}
                  {kids.map((child) => {
                    const active = isChild && me.id === child.id
                    return (
                      <button
                        key={child.id}
                        type="button"
                        role="menuitem"
                        disabled={active || switchChild.isPending}
                        onClick={() => switchChild.mutate(child.id)}
                        className={`flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs transition-colors ${
                          active ? 'bg-accent/15 text-accent-strong' : 'text-white/80 hover:bg-white/10 hover:text-white'
                        }`}
                      >
                        <span className="truncate font-medium">{child.name}</span>
                        <span className="flex items-center gap-1.5">
                          {child.max_certificate && (
                            <span className="rounded bg-white/10 px-1.5 py-0.5 text-[10px] text-white/65">
                              {child.max_certificate}
                            </span>
                          )}
                          {active && <span aria-hidden>✓</span>}
                        </span>
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          ) : (
            <span className="flex items-center gap-1.5 text-white/75">{me.display_name}</span>
          )}
          <Button variant="ghost" onClick={() => logout.mutate()}>
            Sign out
          </Button>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
        <Outlet />
      </main>
      <footer className="mx-auto max-w-5xl px-4 pb-8 text-xs text-white/35 sm:px-6">
        {settings.data && (
          <p className="mb-2">
            <a
              href="https://github.com/sinoop/iwanttowatch/releases"
              target="_blank"
              rel="noreferrer"
              className="underline-offset-2 hover:underline"
            >
              iWantToWatch v{settings.data.version}
            </a>
          </p>
        )}
        This product uses the TMDB API but is not endorsed or certified by TMDB.{' '}
        <JustWatchCredit />
        {settings.data?.imdb.enabled && (
          <>
            {' '}
            Ratings: information courtesy of{' '}
            <a href="https://www.imdb.com" target="_blank" rel="noreferrer" className="underline-offset-2 hover:underline">
              IMDb
            </a>
            . Used with permission.
          </>
        )}
      </footer>
    </div>
  )
}
