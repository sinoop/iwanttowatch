import type { Me } from '@cinematch/api-client'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from './api'
import { Button, Logo } from './ui'

const regionName = new Intl.DisplayNames(['en'], { type: 'region' })
const languageName = new Intl.DisplayNames(['en'], { type: 'language' })

export default function Home({ me }: { me: Me }) {
  const queryClient = useQueryClient()
  const logout = useMutation({
    mutationFn: () => api.POST('/api/v1/auth/logout'),
    onSuccess: () => queryClient.setQueryData(['me'], null),
  })

  return (
    <div className="min-h-screen">
      <header className="flex items-center justify-between border-b border-white/10 px-6 py-4">
        <Logo />
        <div className="flex items-center gap-3 text-sm">
          <span className="text-white/60">{me.display_name}</span>
          <Button variant="ghost" onClick={() => logout.mutate()}>
            Sign out
          </Button>
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-6 py-16">
        <h1 className="text-2xl font-semibold">Welcome, {me.display_name}</h1>
        <p className="mt-2 max-w-prose text-white/60">
          Your discovery feed will appear here once CineMatch can learn your taste from Jellyfin and
          your IMDb or Letterboxd ratings.
        </p>
        <dl className="mt-8 grid gap-4 text-sm sm:grid-cols-2">
          <div className="rounded-xl border border-white/10 p-4">
            <dt className="text-white/50">Region</dt>
            <dd className="mt-1 font-medium">{regionName.of(me.region)}</dd>
          </div>
          <div className="rounded-xl border border-white/10 p-4">
            <dt className="text-white/50">Languages</dt>
            <dd className="mt-1 font-medium">
              {me.languages.length
                ? me.languages.map((code) => languageName.of(code)).join(', ')
                : 'Not set'}
            </dd>
          </div>
        </dl>
      </main>
    </div>
  )
}
