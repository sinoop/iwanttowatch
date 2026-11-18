import type { Me } from '@iwanttowatch/api-client'
import { Link, Navigate, useLocation, useParams } from 'react-router'
import { useServerSettings } from './api'
import { AiSettings } from './settings/AiSettings'
import { DeclutterSettings } from './settings/DeclutterSettings'
import { HouseholdSettings } from './settings/HouseholdSettings'
import { ImportExportSettings } from './settings/ImportExportSettings'
import { IntegrationsSettings } from './settings/IntegrationsSettings'
import { ProfileSettings } from './settings/ProfileSettings'
import { SettingsLayout } from './settings/SettingsLayout'
import { SystemSettings } from './settings/SystemSettings'
import {
  SETTINGS_SECTIONS,
  defaultPathForSection,
  resolveLegacyHashPath,
  visibleSubpages,
} from './settings/settingsCatalog'
import { StreamingSettings } from './Streaming'

export default function Settings({ me }: { me: Me }) {
  const { section = 'profile', subsection } = useParams<{
    section?: string
    subsection?: string
  }>()
  const location = useLocation()
  const settings = useServerSettings()

  if (section === 'radar') {
    return (
      <Navigate
        to={me.is_admin ? '/settings/integrations/radarr' : '/settings/profile/languages'}
        replace
      />
    )
  }

  const sectionMeta = SETTINGS_SECTIONS.find((s) => s.id === section)
  if (!sectionMeta) {
    return <Navigate to="/settings/profile/languages" replace />
  }

  if (sectionMeta.adminOnly && !me.is_admin) {
    return <Navigate to="/settings/profile/languages" replace />
  }

  const opts = { isAdmin: me.is_admin, isChild: me.is_child }

  if (location.hash) {
    const legacyTarget = resolveLegacyHashPath(sectionMeta.id, location.hash)
    if (legacyTarget) {
      return <Navigate to={legacyTarget} replace />
    }
  }

  const subs = visibleSubpages(sectionMeta, opts)
  const activeSub = subsection ? subs.find((s) => s.id === subsection) : undefined

  if (subs.length > 0 && !activeSub) {
    return <Navigate to={defaultPathForSection(sectionMeta, opts)} replace />
  }

  if (subs.length === 0 && subsection) {
    return <Navigate to={`/settings/${sectionMeta.id}`} replace />
  }

  const pageTitle = activeSub ? activeSub.label : sectionMeta.title
  const pageParent = activeSub ? sectionMeta.title : undefined
  const pageDescription = activeSub ? activeSub.description : sectionMeta.description

  return (
    <SettingsLayout
      me={me}
      parentTitle={pageParent}
      title={pageTitle}
      description={pageDescription}
    >
      {sectionMeta.id === 'profile' && (
        <ProfileSettings me={me} subsection={activeSub?.id} />
      )}
      {sectionMeta.id === 'imports' && (
        <ImportExportSettings subsection={activeSub?.id} />
      )}
      {sectionMeta.id === 'streaming' && (
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
                  <Link
                    to="/settings/integrations/tmdb"
                    className="text-accent underline-offset-2 hover:underline"
                  >
                    Connect TMDb in Integrations →
                  </Link>
                </p>
              )}
            </div>
          )}
        </>
      )}
      {sectionMeta.id === 'household' && (
        <HouseholdSettings me={me} subsection={activeSub?.id} />
      )}
      {sectionMeta.id === 'integrations' && settings.data && (
        <IntegrationsSettings
          me={me}
          settings={settings.data}
          subsection={activeSub?.id}
        />
      )}
      {sectionMeta.id === 'ai' && settings.data && (
        <AiSettings me={me} settings={settings.data} subsection={activeSub?.id} />
      )}
      {sectionMeta.id === 'declutter' && <DeclutterSettings />}
      {sectionMeta.id === 'system' && settings.data && (
        <SystemSettings settings={settings.data} subsection={activeSub?.id} />
      )}
    </SettingsLayout>
  )
}
