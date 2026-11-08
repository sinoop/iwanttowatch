import type { Me } from '@iwanttowatch/api-client'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { NavLink, Outlet } from 'react-router'
import { api, errorMessage, useServerSettings } from './api'
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
  const isChild = me.parent_id !== null
  const children = useQuery({
    queryKey: ['children'],
    queryFn: async () => (await api.GET('/api/v1/children')).data ?? [],
    enabled: !isChild,
  })
  const pin = useQuery({
    queryKey: ['parent-pin'],
    queryFn: async () => (await api.GET('/api/v1/me/parent-pin')).data,
    enabled: !isChild,
  })
  const refreshProfile = (next: Me | undefined) => {
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
  const logout = useMutation({
    mutationFn: () => api.POST('/api/v1/auth/logout'),
    onSuccess: () => queryClient.setQueryData(['me'], null),
  })
  const navItems = isChild ? NAV.filter((item) => item.to !== '/settings') : NAV
  // Switching needs a parent PIN to come back; Settings explains how to set one.
  const kids = pin.data?.pin_set ? (children.data ?? []) : []

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
          <HeaderSearch maxCertificate={me.max_certificate ?? null} />
          <span className="flex items-center gap-1.5 text-white/75">
            {me.display_name}
            {me.max_certificate && (
              <span className="rounded bg-accent/15 px-1.5 py-0.5 text-xs font-medium text-accent-strong">
                {me.max_certificate}
              </span>
            )}
          </span>
          {!isChild &&
            kids.map((child) => (
              <Button
                key={child.id}
                variant="ghost"
                className="border border-white/10 px-2.5 py-1 text-xs"
                onClick={() => switchChild.mutate(child.id)}
                disabled={switchChild.isPending}
              >
                Switch to {child.name} ({child.max_certificate})
              </Button>
            ))}
          {isChild && <ExitChild onExit={refreshProfile} />}
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

function ExitChild({ onExit }: { onExit: (parent: Me) => void }) {
  const [open, setOpen] = useState(false)
  const [pin, setPin] = useState('')
  const exit = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST('/api/v1/children/exit', { body: { pin } })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: onExit,
    onError: () => setPin(''),
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (pin) exit.mutate()
  }

  if (!open) {
    return (
      <Button variant="ghost" className="border border-white/10 px-2.5 py-1 text-xs" onClick={() => setOpen(true)}>
        Exit child profile
      </Button>
    )
  }
  return (
    <form onSubmit={submit} className="flex flex-wrap items-center gap-2">
      <input
        type="password"
        inputMode="numeric"
        autoComplete="off"
        autoFocus
        aria-label="Parent PIN"
        placeholder="Parent PIN"
        maxLength={8}
        value={pin}
        onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))}
        className="w-28 rounded-lg border border-white/10 bg-[#11141b] px-2.5 py-1 text-xs text-white outline-none focus:border-accent"
      />
      <Button type="submit" className="px-2.5 py-1 text-xs" disabled={!pin || exit.isPending}>
        Exit
      </Button>
      <Button type="button" variant="ghost" className="px-2 py-1 text-xs" onClick={() => setOpen(false)}>
        Cancel
      </Button>
      {exit.error && (
        <span role="alert" className="text-xs text-red-300">
          {exit.error.message}
        </span>
      )}
    </form>
  )
}
