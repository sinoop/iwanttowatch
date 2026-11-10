import type { ChildProfile, InviteOut, Me } from '@iwanttowatch/api-client'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, copyToClipboard, errorMessage } from '../api'
import { Button, ErrorText, Field } from '../ui'

const CURRENT_YEAR = new Date().getFullYear()

export function HouseholdSettings({ me }: { me: Me }) {
  return (
    <div className="space-y-6">
      {me.is_admin && (
        <div id="invites" className="scroll-mt-6">
          <HouseholdInvites />
        </div>
      )}
      <div id="child-profiles" className="scroll-mt-6">
        <ChildProfilesSection me={me} />
      </div>
    </div>
  )
}

function HouseholdInvites() {
  const queryClient = useQueryClient()
  const invites = useQuery({
    queryKey: ['invites'],
    queryFn: async () => (await api.GET('/api/v1/invites')).data ?? [],
  })
  const [name, setName] = useState('')
  const create = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST('/api/v1/invites', { body: { name: name.trim() || null } })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: () => {
      setName('')
      queryClient.invalidateQueries({ queryKey: ['invites'] })
    },
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    create.mutate()
  }

  return (
    <section className="rounded-xl border border-white/10 p-5">
      <h2 className="font-semibold text-white">Household invites</h2>
      <p className="mt-2 text-sm text-white/60">
        Invite someone to set up their own account, with their own ratings and picks. Each link
        works once, for a week. People with a Jellyfin account on this server can sign in with it
        instead.
      </p>
      {invites.data && invites.data.length > 0 && (
        <ul className="mt-4 divide-y divide-white/10 border-y border-white/10">
          {invites.data.map((invite) => (
            <InviteRow key={invite.id} invite={invite} />
          ))}
        </ul>
      )}
      <form onSubmit={submit} className="mt-4 flex flex-wrap items-end gap-3">
        <div className="min-w-44 flex-1">
          <Field
            label="Who is it for? (optional)"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={128}
            placeholder="e.g. Asha"
          />
        </div>
        <Button type="submit" disabled={create.isPending}>
          {create.isPending ? 'Creating…' : 'Create invite link'}
        </Button>
      </form>
      {create.error && (
        <div className="mt-3">
          <ErrorText>{create.error.message}</ErrorText>
        </div>
      )}
    </section>
  )
}

function InviteRow({ invite }: { invite: InviteOut }) {
  const queryClient = useQueryClient()
  const [copied, setCopied] = useState(false)
  const link = `${window.location.origin}/invite/${invite.token}`
  const revoke = useMutation({
    mutationFn: async () => {
      await api.DELETE('/api/v1/invites/{invite_id}', { params: { path: { invite_id: invite.id } } })
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['invites'] }),
  })
  const expires = new Date(invite.expires_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })

  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-2 py-3 text-sm">
      <div className="min-w-0 flex-1">
        <p className="font-medium text-white">{invite.name ?? 'Anyone with the link'}</p>
        <p className="truncate text-xs text-white/45" title={link}>
          Until {expires} · {link}
        </p>
      </div>
      <Button
        variant="ghost"
        className="border border-white/10 px-2 py-1 text-xs"
        onClick={() => {
          void copyToClipboard(link).then((ok) => {
            if (ok) setCopied(true)
          })
        }}
      >
        {copied ? 'Link copied' : 'Copy link'}
      </Button>
      <Button variant="ghost" className="px-2 py-1 text-xs text-white/60 hover:text-red-300" onClick={() => revoke.mutate()} disabled={revoke.isPending}>
        Revoke
      </Button>
    </li>
  )
}

function ChildProfilesSection({ me }: { me: Me }) {
  const queryClient = useQueryClient()
  const children = useQuery({
    queryKey: ['children'],
    queryFn: async () => (await api.GET('/api/v1/children')).data ?? [],
  })
  const currentYear = CURRENT_YEAR
  const [name, setName] = useState('')
  const [birthYear, setBirthYear] = useState(String(currentYear - 8))

  const refresh = () => {
    for (const key of ['children', 'together']) queryClient.invalidateQueries({ queryKey: [key] })
  }
  const parsedYear = Number(birthYear)
  const validYear = Number.isInteger(parsedYear) && parsedYear >= 1900 && parsedYear <= currentYear
  const create = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST('/api/v1/children', {
        body: { name: name.trim(), birth_year: parsedYear },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: () => {
      setName('')
      refresh()
    },
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (name.trim() && validYear) create.mutate()
  }

  return (
    <section className="rounded-xl border border-white/10 p-5">
      <h2 className="font-semibold text-white">Child profiles</h2>
      <p className="mt-2 text-sm text-white/60">
        Create a household profile for each child with their birth year. Their birth year sets the
        default certificate filter for {me.region} on Discover (and in Watch together groups that
        include them), and any adult in the household can switch to a child profile or assign
        films to them.
      </p>
      {children.data && children.data.length > 0 && (
        <ul className="mt-4 divide-y divide-white/10 border-y border-white/10">
          {children.data.map((child) => (
            <ChildRow key={child.id} child={child} currentYear={currentYear} onChanged={refresh} />
          ))}
        </ul>
      )}
      <form onSubmit={submit} className="mt-4 flex flex-wrap items-end gap-3">
        <div className="min-w-44 flex-1">
          <Field
            label="Child’s name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            maxLength={64}
            placeholder="e.g. Kabir"
          />
        </div>
        <div className="w-32">
          <Field
            label="Birth year"
            type="number"
            min={1900}
            max={currentYear}
            value={birthYear}
            onChange={(e) => setBirthYear(e.target.value)}
            required
          />
        </div>
        <Button type="submit" disabled={create.isPending || !name.trim() || !validYear}>
          {create.isPending ? 'Adding…' : 'Add child'}
        </Button>
      </form>
      {create.error && (
        <div className="mt-3">
          <ErrorText>{create.error.message}</ErrorText>
        </div>
      )}
    </section>
  )
}

function ChildRow({
  child,
  currentYear,
  onChanged,
}: {
  child: ChildProfile
  currentYear: number
  onChanged: () => void
}) {
  const queryClient = useQueryClient()
  const [birthYear, setBirthYear] = useState(String(child.birth_year))
  const update = useMutation({
    mutationFn: async (birth_year: number) => {
      const { data, error } = await api.PUT('/api/v1/children/{child_id}', {
        params: { path: { child_id: child.id } },
        body: { name: child.name, birth_year },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: onChanged,
  })
  const switchTo = useMutation({
    mutationFn: async () =>
      (await api.POST('/api/v1/children/{child_id}/switch', { params: { path: { child_id: child.id } } })).data,
    onSuccess: (next) => {
      if (next) queryClient.setQueryData(['me'], next)
      for (const key of ['feed', 'ratings', 'persona', 'together', 'title']) {
        queryClient.invalidateQueries({ queryKey: [key] })
      }
    },
  })
  const remove = useMutation({
    mutationFn: () => api.DELETE('/api/v1/children/{child_id}', { params: { path: { child_id: child.id } } }),
    onSuccess: onChanged,
  })
  const saveYear = (value: string) => {
    setBirthYear(value)
    const parsed = Number(value)
    if (Number.isInteger(parsed) && parsed >= 1900 && parsed <= currentYear && parsed !== child.birth_year) {
      update.mutate(parsed)
    }
  }

  return (
    <li className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm">
      <div className="flex items-center gap-2">
        <span className="font-medium text-white">{child.name}</span>
        {child.max_certificate && (
          <span className="rounded bg-accent/15 px-1.5 py-0.5 text-xs font-medium text-accent-strong">
            {child.max_certificate}
          </span>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1.5 text-xs text-white/60">
          <span>Born</span>
          <input
            type="number"
            aria-label={`Birth year for ${child.name}`}
            min={1900}
            max={currentYear}
            value={birthYear}
            onChange={(e) => saveYear(e.target.value)}
            disabled={update.isPending}
            className="w-20 rounded-lg border border-white/10 bg-[#11141b] px-2 py-1 text-xs text-white outline-none focus:border-accent"
          />
        </label>
        <Button
          variant="ghost"
          className="border border-white/10 px-2.5 py-1 text-xs"
          onClick={() => switchTo.mutate()}
          disabled={switchTo.isPending}
        >
          Switch
        </Button>
        <Button
          variant="ghost"
          className="px-2.5 py-1 text-xs text-white/60 hover:text-red-300"
          onClick={() => remove.mutate()}
          disabled={remove.isPending}
        >
          Remove
        </Button>
      </div>
    </li>
  )
}
