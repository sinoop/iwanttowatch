import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import Home from './Home'
import Login from './Login'
import SetupWizard from './SetupWizard'

export default function App() {
  const setup = useQuery({
    queryKey: ['setup'],
    queryFn: async () => (await api.GET('/api/v1/setup')).data ?? null,
  })
  const me = useQuery({
    queryKey: ['me'],
    enabled: setup.data?.complete === true,
    // A 401 means "signed out", not an error.
    queryFn: async () => (await api.GET('/api/v1/me')).data ?? null,
  })

  if (setup.isPending || (setup.data?.complete && me.isPending)) return null
  if (!setup.data) {
    return (
      <p className="p-8 text-sm text-white/60">iWantToWatch server is unreachable. Is it running?</p>
    )
  }
  if (!setup.data.complete) return <SetupWizard />
  if (!me.data) return <Login />
  return <Home me={me.data} />
}
