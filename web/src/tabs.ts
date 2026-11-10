/**
 * Shared styling utilities for Segmented Capsule navigation, tabs, and filters.
 *
 * Provides a consistent glassmorphic segmented capsule aesthetic everywhere:
 * top menus, dialog filmography tabs, and admin/settings category switchers.
 */

export function segmentedTabClass({
  active,
  size = 'md',
  className = '',
}: {
  active: boolean
  size?: 'xs' | 'sm' | 'md'
  className?: string
}): string {
  const sizeStyles =
    size === 'xs'
      ? 'px-3 py-1.5 text-xs gap-1.5'
      : size === 'sm'
        ? 'px-3.5 py-1.5 text-xs sm:text-sm gap-2'
        : 'px-4 py-2 text-sm gap-2'

  return `flex cursor-pointer items-center rounded-xl font-semibold whitespace-nowrap transition-all ${sizeStyles} ${
    active
      ? 'border border-white/15 bg-white/15 text-white shadow-sm'
      : 'border border-transparent text-white/60 hover:bg-white/5 hover:text-white'
  } ${className}`.trim()
}

export function segmentedBadgeClass({
  active,
  variant = 'default',
  size = 'md',
  className = '',
}: {
  active: boolean
  variant?: 'default' | 'accent' | 'danger'
  size?: 'xs' | 'md'
  className?: string
}): string {
  const sizeStyles = size === 'xs' ? 'px-1.5 py-0.2 text-[10px]' : 'px-2 py-0.5 text-[11px]'

  let colorStyles = active ? 'bg-accent text-black' : 'bg-white/10 text-white/60'
  if (variant === 'accent') {
    colorStyles = active
      ? 'border border-accent/50 bg-accent/25 font-semibold text-accent-strong'
      : 'border border-accent/30 bg-accent/15 text-accent'
  } else if (variant === 'danger') {
    colorStyles = active
      ? 'border border-red-500/50 bg-red-500/25 font-semibold text-red-300'
      : 'border border-red-500/30 bg-red-500/15 text-red-400'
  }

  return `rounded-full font-bold leading-none transition-colors ${sizeStyles} ${colorStyles} ${className}`.trim()
}
