import { useMutation, useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, errorMessage } from './api'
import { AuthCard, Button, ErrorText, Field } from './ui'

/** The page a new household member opens from an admin's invite link. */
export default function Invite({ token }: { token: string }) {
  const invite = useQuery({
    queryKey: ['invite', token],
    queryFn: async () => {
      const { data, error, response } = await api.GET('/api/v1/invites/{token}', {
        params: { path: { token } },
      })
      if (response.status === 404) return null
      if (error) throw new Error(errorMessage(error))
      return data
    },
  })
  const [displayName, setDisplayName] = useState<string | null>(null)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const name = displayName ?? invite.data?.name ?? ''
  const accept = useMutation({
    mutationFn: async () => {
      const { error } = await api.POST('/api/v1/invites/{token}/accept', {
        params: { path: { token } },
        body: { username, display_name: name.trim(), password },
      })
      if (error) throw new Error(errorMessage(error))
    },
    // A fresh load leaves the invite path and opens the app as the new member.
    onSuccess: () => window.location.replace('/'),
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    accept.mutate()
  }

  if (invite.isPending) return null
  return (
    <AuthCard>
      {invite.error ? (
        <ErrorText>{invite.error.message}</ErrorText>
      ) : !invite.data ? (
        <>
          <h1 className="text-xl font-semibold">This invite has expired</h1>
          <p className="mt-2 text-sm text-white/55">
            It was used already, revoked, or is more than a week old. Ask whoever sent it for a new
            link, or{' '}
            <a href="/" className="text-accent underline-offset-2 hover:underline">
              sign in
            </a>{' '}
            if you have an account.
          </p>
        </>
      ) : (
        <>
          <h1 className="text-xl font-semibold">{invite.data.invited_by} invited you</h1>
          <p className="mt-1 text-sm text-white/55">
            Set up your iWantToWatch account to get film picks that match your taste.
            {invite.data.jellyfin_login && (
              <>
                {' '}
                Have a Jellyfin account on this server?{' '}
                <a href="/" className="text-accent underline-offset-2 hover:underline">
                  Sign in with it
                </a>{' '}
                instead.
              </>
            )}
          </p>
          <form onSubmit={submit} className="mt-6 space-y-4">
            <Field
              label="Your name"
              value={name}
              onChange={(e) => setDisplayName(e.target.value)}
              required
              maxLength={128}
              autoFocus={!name}
            />
            <Field
              label="Username"
              hint="Letters, numbers, dots, dashes, and underscores."
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              maxLength={64}
              pattern="[A-Za-z0-9_.\-]+"
              autoFocus={!!name}
            />
            <Field
              label="Password"
              hint="At least 8 characters."
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
            />
            {accept.error && <ErrorText>{accept.error.message}</ErrorText>}
            <Button type="submit" className="w-full" disabled={accept.isPending}>
              {accept.isPending ? 'Setting up…' : 'Create account'}
            </Button>
          </form>
        </>
      )}
    </AuthCard>
  )
}
