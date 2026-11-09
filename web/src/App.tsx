import { useQuery } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router'
import { api } from './api'
import Discover from './Discover'
import Invite from './Invite'
import Login from './Login'
import Review from './Review'
import Settings from './Settings'
import SetupWizard from './SetupWizard'
import Shell from './Shell'
import Taste from './Taste'
import Together from './Together'
import Vote from './Vote'

// Guests open a vote link, and new members an invite link, without an account, so both
// skip setup and sign-in.
const voteToken = window.location.pathname.match(/^\/vote\/([\w-]+)\/?$/)?.[1]
const inviteToken = window.location.pathname.match(/^\/invite\/([\w-]+)\/?$/)?.[1]

export default function App() {
  if (voteToken) return <Vote token={voteToken} />
  if (inviteToken) return <Invite token={inviteToken} />
  return <Main />
}

function Main() {
  const setup = useQuery({
    queryKey: ['setup'],
    queryFn: async () => (await api.GET('/api/v1/setup')).data ?? null,
  })
  // Fetched alongside setup rather than after it: one round trip less on every load.
  // Before setup it is a 401, like being signed out.
  const me = useQuery({
    queryKey: ['me'],
    // A 401 means "signed out", not an error.
    queryFn: async () => (await api.GET('/api/v1/me')).data ?? null,
  })

  if (setup.isPending || me.isPending) return null
  if (!setup.data) {
    return (
      <p className="p-8 text-sm text-white/60">iWantToWatch server is unreachable. Is it running?</p>
    )
  }
  if (!setup.data.complete) return <SetupWizard />
  if (!me.data) return <Login />
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Shell me={me.data} />}>
          <Route index element={<Discover me={me.data} />} />
          <Route path="together" element={<Together me={me.data} />} />
          <Route path="taste" element={<Taste me={me.data} />} />
          {!me.data.is_child && (
            <>
              <Route path="taste/imports/:jobId" element={<Review />} />
              <Route path="settings" element={<Settings me={me.data} />} />
            </>
          )}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
