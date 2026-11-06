import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, errorMessage } from './api'
import { AuthCard, Button, ErrorText, Field } from './ui'

export default function Login() {
  const queryClient = useQueryClient()
  const setup = useQuery({
    queryKey: ['setup'],
    queryFn: async () => (await api.GET('/api/v1/setup')).data ?? null,
  })
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const login = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST('/api/v1/auth/login', {
        body: { username, password },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (me) => queryClient.setQueryData(['me'], me),
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    login.mutate()
  }

  return (
    <AuthCard>
      <h1 className="text-xl font-semibold">Sign in</h1>
      <p className="mt-1 text-sm text-white/55">
        {setup.data?.jellyfin_login
          ? 'Use your iWantToWatch account, or your Jellyfin username and password.'
          : 'Welcome back. Your next favourite film is waiting.'}
      </p>
      <form onSubmit={submit} className="mt-6 space-y-4">
        <Field
          label="Username"
          autoComplete="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          required
          autoFocus
        />
        <Field
          label="Password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        {login.error && <ErrorText>{login.error.message}</ErrorText>}
        <Button type="submit" className="w-full" disabled={login.isPending}>
          {login.isPending ? 'Signing in…' : 'Sign in'}
        </Button>
      </form>
    </AuthCard>
  )
}
