import { useId } from 'react'

import { cn } from '@/lib/utils'

/**
 * MercaNova logo: a rounded square with the brand gradient and a four-point "nova" star
 * (plus a small spark), next to the wordmark. Pure SVG + text: no image files to load.
 * `tone="light"` is for dark backgrounds (the header).
 */
export function LogoMark({ className }: { className?: string }) {
  const id = useId()
  const gradient = `${id}-bg`
  const shine = `${id}-shine`
  return (
    <svg viewBox="0 0 40 40" className={cn('size-8 shrink-0', className)} aria-hidden="true">
      <defs>
        <linearGradient id={gradient} x1="0" y1="0" x2="40" y2="40" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#4f46e5" />
          <stop offset="0.55" stopColor="#7c3aed" />
          <stop offset="1" stopColor="#c026d3" />
        </linearGradient>
        <radialGradient id={shine} cx="12" cy="8" r="22" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#fff" stopOpacity="0.35" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </radialGradient>
      </defs>
      <rect width="40" height="40" rx="11" fill={`url(#${gradient})`} />
      <rect width="40" height="40" rx="11" fill={`url(#${shine})`} />
      {/* The nova: a four-point star */}
      <path
        d="M19 8.5c.9 6.6 3.9 9.6 10.5 10.5-6.6.9-9.6 3.9-10.5 10.5-.9-6.6-3.9-9.6-10.5-10.5 6.6-.9 9.6-3.9 10.5-10.5Z"
        fill="#fff"
      />
      <path
        d="M29.5 7c.3 2 1.2 2.9 3.2 3.2-2 .3-2.9 1.2-3.2 3.2-.3-2-1.2-2.9-3.2-3.2 2-.3 2.9-1.2 3.2-3.2Z"
        fill="#fff"
        fillOpacity="0.85"
      />
    </svg>
  )
}

export function Logo({ tone = 'dark', className }: { tone?: 'dark' | 'light'; className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-2.5', className)}>
      <LogoMark />
      <span
        className={cn(
          'text-xl leading-none font-semibold tracking-tight',
          tone === 'light' ? 'text-white' : 'text-foreground',
        )}
      >
        Merca
        <span
          className={cn(
            'font-bold',
            tone === 'light'
              ? 'bg-linear-to-r from-violet-200 to-fuchsia-200 bg-clip-text text-transparent'
              : 'bg-linear-to-r from-indigo-600 to-fuchsia-600 bg-clip-text text-transparent',
          )}
        >
          Nova
        </span>
      </span>
    </span>
  )
}
