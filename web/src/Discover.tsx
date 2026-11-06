import type { Me } from '@iwanttowatch/api-client'
import { Link } from 'react-router'
import { useServerSettings } from './api'

const regionName = new Intl.DisplayNames(['en'], { type: 'region' })
const languageName = new Intl.DisplayNames(['en'], { type: 'language' })

export default function Discover({ me }: { me: Me }) {
  const settings = useServerSettings()
  const tmdbMissing = settings.data && !settings.data.tmdb_configured

  return (
    <>
      <h1 className="text-2xl font-semibold">Welcome, {me.display_name}</h1>
      <p className="mt-2 max-w-prose text-white/60">
        Your discovery feed will appear here once iWantToWatch can learn your taste from Jellyfin and
        your IMDb or Letterboxd ratings.
      </p>
      {tmdbMissing ? (
        <NextStep to="/settings" action="Open Settings">
          {me.is_admin
            ? 'First, add a free TMDb API key so iWantToWatch can look up movies.'
            : 'Ask your admin to add a TMDb API key so iWantToWatch can look up movies.'}
        </NextStep>
      ) : (
        <NextStep to="/taste" action="Import ratings">
          Import your IMDb or Letterboxd history to teach iWantToWatch your taste.
        </NextStep>
      )}
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
    </>
  )
}

function NextStep({ to, action, children }: { to: string; action: string; children: string }) {
  return (
    <div className="mt-8 flex flex-wrap items-center justify-between gap-4 rounded-xl border border-accent/30 bg-accent/5 p-4">
      <p className="text-sm">{children}</p>
      <Link
        to={to}
        className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-black hover:bg-accent-strong"
      >
        {action}
      </Link>
    </div>
  )
}
