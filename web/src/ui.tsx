import { useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode } from 'react'

export function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <img src="/favicon.svg" alt="" className="size-8" />
      <span className="text-lg font-semibold tracking-tight">iWantToWatch</span>
    </div>
  )
}

/** Centered card used by the first-run and sign-in screens. */
export function AuthCard({ children }: { children: ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-12">
      <div className="w-full max-w-md">
        <div className="mb-8">
          <Logo />
        </div>
        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-6 shadow-2xl shadow-black/40 sm:p-8">
          {children}
        </div>
      </div>
    </main>
  )
}

export function Field({
  label,
  hint,
  ...input
}: { label: string; hint?: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-white/80">{label}</span>
      <input
        className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm outline-none placeholder:text-white/30 focus:border-accent focus:ring-2 focus:ring-accent/30"
        {...input}
      />
      {hint && <span className="mt-1 block text-xs text-white/45">{hint}</span>}
    </label>
  )
}

export function Button({
  variant = 'primary',
  className = '',
  ...props
}: { variant?: 'primary' | 'ghost' } & ButtonHTMLAttributes<HTMLButtonElement>) {
  const styles =
    variant === 'primary'
      ? 'bg-accent text-black hover:bg-accent-strong'
      : 'text-white/70 hover:bg-white/5 hover:text-white'
  return (
    <button
      className={`rounded-lg px-4 py-2 text-sm font-semibold transition-colors focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${className}`}
      {...props}
    />
  )
}

export function ErrorText({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-300">
      {children}
    </p>
  )
}

const POSTER_BASE = 'https://image.tmdb.org/t/p/w185'

/** A 2:3 movie poster from TMDb, showing the title when there is no image or it fails to load. */
export function Poster({ path, title, className = '' }: { path: string | null; title: string; className?: string }) {
  const [failed, setFailed] = useState(false)
  return (
    <div className={`aspect-[2/3] overflow-hidden rounded-lg bg-white/5 ${className}`}>
      {path && !failed ? (
        <img
          src={POSTER_BASE + path}
          alt=""
          loading="lazy"
          className="h-full w-full object-cover"
          onError={() => setFailed(true)}
        />
      ) : (
        <span className="flex h-full items-center justify-center p-2 text-center text-xs text-white/40">
          {title}
        </span>
      )}
    </div>
  )
}

/** Segmented capsule container for top menus, tab switches, and section navigators. */
export function SegmentedCapsule({
  children,
  className = '',
  role,
  'aria-label': ariaLabel,
}: {
  children: ReactNode
  className?: string
  role?: string
  'aria-label'?: string
}) {
  return (
    <div
      role={role}
      aria-label={ariaLabel}
      className={`inline-flex items-center gap-1.5 rounded-2xl border border-white/10 bg-white/[0.04] p-1.5 shadow-lg shadow-black/20 backdrop-blur-md ${className}`}
    >
      {children}
    </div>
  )
}


