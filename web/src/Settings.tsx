import type { Me } from '@iwanttowatch/api-client'
import { Link, Navigate, useParams } from 'react-router'
import { useServerSettings } from './api'
import { AiSettings } from './settings/AiSettings'
import { HouseholdSettings } from './settings/HouseholdSettings'
import { ImportExportSettings } from './settings/ImportExportSettings'
import { IntegrationsSettings } from './settings/IntegrationsSettings'
import { ProfileSettings } from './settings/ProfileSettings'
import { SettingsLayout } from './settings/SettingsLayout'
import { SystemSettings } from './settings/SystemSettings'
import { StreamingSettings } from './Streaming'

const VALID_SECTIONS = ['profile', 'imports', 'streaming', 'household', 'integrations', 'ai', 'system'] as const
type ValidSection = (typeof VALID_SECTIONS)[number]

const SECTION_META: Record<ValidSection, { title: string; description: string; adminOnly?: boolean }> = {
  profile: {
    title: 'My Profile',
    description: 'Manage your birth year, linked Jellyfin account, AI taste profile, and sharing.',
  },
  imports: {
    title: 'Import & Export',
    description: 'Import ratings from IMDb, Letterboxd, or Netflix, or export and restore your account data.',
  },
  streaming: {
    title: 'Streaming Services',
    description: 'Choose your region and select the streaming providers you have access to.',
  },
  household: {
    title: 'Household',
    description: 'Manage household member invite links and child profiles.',
  },
  integrations: {
    title: 'Integrations',
    description: 'Connect metadata providers, media servers, and external rating datasets.',
    adminOnly: true,
  },
  ai: {
    title: 'AI & LLM',
    description: 'Configure AI writing providers (Gemini or Ollama), fallback priority, and inspect call logs.',
    adminOnly: true,
  },
  system: {
    title: 'System',
    description: 'Database backups and read-only MCP server debugging access.',
    adminOnly: true,
  },
}

export default function Settings({ me }: { me: Me }) {
  const { section = 'profile' } = useParams<{ section?: string }>()
  const settings = useServerSettings()

  if (!VALID_SECTIONS.includes(section as ValidSection)) {
    return <Navigate to="/settings/profile" replace />
  }

  const currentSection = section as ValidSection
  const meta = SECTION_META[currentSection]

  if (meta.adminOnly && !me.is_admin) {
    return <Navigate to="/settings/profile" replace />
  }

  return (
    <SettingsLayout me={me} title={meta.title} description={meta.description}>
      {currentSection === 'profile' && <ProfileSettings me={me} />}
      {currentSection === 'imports' && <ImportExportSettings />}
      {currentSection === 'streaming' && (
        <>
          {settings.data?.tmdb_configured ? (
            <div className="-mt-6">
              <StreamingSettings me={me} />
            </div>
          ) : (
            <div className="rounded-xl border border-dashed border-white/15 p-6 text-sm text-white/60">
              <p>Streaming availability requires a connected TMDb API key.</p>
              {me.is_admin && (
                <p className="mt-2">
                  <Link to="/settings/integrations" className="text-accent underline-offset-2 hover:underline">
                    Connect TMDb in Integrations →
                  </Link>
                </p>
              )}
            </div>
          )}
        </>
      )}
      {currentSection === 'household' && <HouseholdSettings me={me} />}
      {currentSection === 'integrations' && settings.data && (
        <IntegrationsSettings me={me} settings={settings.data} />
      )}
      {currentSection === 'ai' && settings.data && <AiSettings me={me} settings={settings.data} />}
      {currentSection === 'system' && settings.data && <SystemSettings settings={settings.data} />}
    </SettingsLayout>
  )
}
