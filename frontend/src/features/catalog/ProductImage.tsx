import { useState } from 'react'

import { cn } from '@/lib/utils'

import { CATEGORY_ART, DEFAULT_ART } from './categoryArt'


/**
 * The dataset has no real photos: every image_url is a placehold.co placeholder (a grey box with
 * the SKU), which carries no information and is unreadable as a thumbnail. Those are drawn as
 * "no photo"; a real URL, if the dataset ever has one, is shown as is.
 */
function isPlaceholder(src: string): boolean {
  try {
    return new URL(src).hostname === 'placehold.co'
  } catch {
    return true // not a valid URL: nothing to show
  }
}

/**
 * Product photo. The URL always comes from the API (DB), never from the model's text.
 * Without a usable photo (placeholder, no URL, or it fails to load: offline, docs/PLAN.md §2.1)
 * it draws a local illustration for the category, so it also works without internet.
 */
export function ProductImage({
  src,
  alt,
  category,
  className,
}: {
  src: string | null | undefined
  alt: string
  category?: string | null
  className?: string
}) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null)

  if (!src || isPlaceholder(src) || failedSrc === src) {
    const { icon: Icon, tone } = CATEGORY_ART[category ?? ''] ?? DEFAULT_ART
    return (
      <div
        role="img"
        aria-label={alt}
        className={cn('flex items-center justify-center bg-linear-to-br', tone, className)}
      >
        <Icon className="size-1/2 max-h-24 max-w-24" strokeWidth={1.25} />
      </div>
    )
  }
  return (
    <img
      src={src}
      alt={alt}
      loading="lazy"
      onError={() => setFailedSrc(src)}
      className={cn('bg-muted object-cover', className)}
    />
  )
}
