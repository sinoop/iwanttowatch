import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, errorMessage } from './api'
import { AuthCard, Button, ErrorText, Field } from './ui'

// Common starting points; the API accepts any ISO 3166-1 region.
const REGIONS = ['IN', 'US', 'GB', 'CA', 'AU', 'AE', 'SG', 'MY', 'DE', 'FR', 'JP', 'KR']
const LANGUAGES = ['ml', 'en', 'hi', 'ta', 'te', 'kn', 'bn', 'mr', 'ko', 'ja', 'fr', 'es', 'it', 'zh']
const regionName = new Intl.DisplayNames(['en'], { type: 'region' })
const languageName = new Intl.DisplayNames(['en'], { type: 'language' })

export default function SetupWizard() {
  const queryClient = useQueryClient()
  const [step, setStep] = useState<1 | 2>(1)
  const [account, setAccount] = useState({ display_name: '', username: '', password: '', confirm: '' })
  const [region, setRegion] = useState('IN')
  const [languages, setLanguages] = useState<string[]>([])

  const setup = useMutation({
    mutationFn: async () => {
      const { confirm: _, ...admin } = account
      const { data, error } = await api.POST('/api/v1/setup', {
        body: { ...admin, region, languages },
      })
      if (error) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (me) => {
      queryClient.setQueryData(['me'], me)
      queryClient.setQueryData(['setup'], { complete: true, jellyfin_login: false })
    },
  })

  const passwordsDiffer = account.confirm !== '' && account.confirm !== account.password
  const next = (event: FormEvent) => {
    event.preventDefault()
    if (!passwordsDiffer) setStep(2)
  }
  const finish = (event: FormEvent) => {
    event.preventDefault()
    setup.mutate()
  }
  const toggleLanguage = (code: string) =>
    setLanguages((current) =>
      current.includes(code) ? current.filter((c) => c !== code) : [...current, code],
    )

  return (
    <AuthCard>
      <p className="text-xs font-medium tracking-wide text-accent uppercase">Step {step} of 2</p>
      {step === 1 ? (
        <form onSubmit={next} className="mt-2 space-y-4">
          <div>
            <h1 className="text-xl font-semibold">Create the admin account</h1>
            <p className="mt-1 text-sm text-white/55">
              This account manages the server. Household members can sign in with Jellyfin later.
            </p>
          </div>
          <Field
            label="Your name"
            value={account.display_name}
            onChange={(e) => setAccount({ ...account, display_name: e.target.value })}
            required
            autoFocus
          />
          <Field
            label="Username"
            autoComplete="username"
            pattern="[A-Za-z0-9_.\-]+"
            title="Letters, numbers, dots, dashes, and underscores"
            value={account.username}
            onChange={(e) => setAccount({ ...account, username: e.target.value })}
            required
          />
          <Field
            label="Password"
            type="password"
            autoComplete="new-password"
            minLength={8}
            hint="At least 8 characters."
            value={account.password}
            onChange={(e) => setAccount({ ...account, password: e.target.value })}
            required
          />
          <Field
            label="Confirm password"
            type="password"
            autoComplete="new-password"
            value={account.confirm}
            onChange={(e) => setAccount({ ...account, confirm: e.target.value })}
            required
          />
          {passwordsDiffer && <ErrorText>Passwords don’t match.</ErrorText>}
          <Button type="submit" className="w-full">
            Continue
          </Button>
        </form>
      ) : (
        <form onSubmit={finish} className="mt-2 space-y-5">
          <div>
            <h1 className="text-xl font-semibold">Where and what do you watch?</h1>
            <p className="mt-1 text-sm text-white/55">
              Your region decides which streaming catalogues apply. Languages keep regional cinema in
              your recommendations. You can change both later.
            </p>
          </div>
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-white/80">Region</span>
            <select
              value={region}
              onChange={(e) => setRegion(e.target.value)}
              className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent/30"
            >
              {REGIONS.map((code) => (
                <option key={code} value={code}>
                  {regionName.of(code)}
                </option>
              ))}
            </select>
          </label>
          <fieldset>
            <legend className="mb-2 text-sm font-medium text-white/80">Languages you watch</legend>
            <div className="flex flex-wrap gap-2">
              {LANGUAGES.map((code) => {
                const selected = languages.includes(code)
                return (
                  <button
                    key={code}
                    type="button"
                    aria-pressed={selected}
                    onClick={() => toggleLanguage(code)}
                    className={`rounded-full border px-3 py-1 text-sm transition-colors focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:outline-none ${
                      selected
                        ? 'border-accent bg-accent/15 text-accent-strong'
                        : 'border-white/10 text-white/65 hover:border-white/25 hover:text-white'
                    }`}
                  >
                    {languageName.of(code)}
                  </button>
                )
              })}
            </div>
          </fieldset>
          {setup.error && <ErrorText>{setup.error.message}</ErrorText>}
          <div className="flex gap-2">
            <Button type="button" variant="ghost" onClick={() => setStep(1)}>
              Back
            </Button>
            <Button type="submit" className="flex-1" disabled={setup.isPending}>
              {setup.isPending ? 'Setting up…' : 'Finish setup'}
            </Button>
          </div>
        </form>
      )}
    </AuthCard>
  )
}
