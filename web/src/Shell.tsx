import type { Me } from '@iwanttowatch/api-client'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { NavLink, Outlet } from 'react-router'
import { api } from './api'
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
  const logout = useMutation({
    mutationFn: () => api.POST('/api/v1/auth/logout'),
    onSuccess: () => queryClient.setQueryData(['me'], null),
  })

  return (
    <div className="min-h-screen">
      <header className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-white/10 px-4 py-3 sm:px-6">
        <Logo />
        <nav className="order-last flex w-full overflow-x-auto sm:order-none sm:w-auto sm:gap-1">
          {NAV.map((item) => (
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
        <div className="ml-auto flex items-center gap-3 text-sm">
          <span className="text-white/60">{me.display_name}</span>
          <Button variant="ghost" onClick={() => logout.mutate()}>
            Sign out
          </Button>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
        <Outlet />
      </main>
      <footer className="mx-auto max-w-5xl px-4 pb-8 text-xs text-white/35 sm:px-6">
        This product uses the TMDB API but is not endorsed or certified by TMDB.{' '}
        <JustWatchCredit />
      </footer>
    </div>
  )
}
