import {
  CableIcon,
  HardDriveIcon,
  HeadphonesIcon,
  KeyboardIcon,
  LaptopIcon,
  MonitorIcon,
  MouseIcon,
  PackageIcon,
  PrinterIcon,
  RouterIcon,
  SpeakerIcon,
  TabletIcon,
  WebcamIcon,
  type LucideIcon,
} from 'lucide-react'
import { useState } from 'react'

import { cn } from '@/lib/utils'

/** Icon and colors per category (full class names, so Tailwind includes them). */
const CATEGORY_ART: Record<string, { icon: LucideIcon; tone: string }> = {
  Monitors: { icon: MonitorIcon, tone: 'from-sky-50 to-sky-100 text-sky-600' },
  Laptops: { icon: LaptopIcon, tone: 'from-indigo-50 to-indigo-100 text-indigo-600' },
  Headphones: { icon: HeadphonesIcon, tone: 'from-violet-50 to-violet-100 text-violet-600' },
  Keyboards: { icon: KeyboardIcon, tone: 'from-amber-50 to-amber-100 text-amber-600' },
  Mice: { icon: MouseIcon, tone: 'from-emerald-50 to-emerald-100 text-emerald-600' },
  Webcams: { icon: WebcamIcon, tone: 'from-rose-50 to-rose-100 text-rose-600' },
  'Docking Stations': { icon: CableIcon, tone: 'from-slate-50 to-slate-200 text-slate-600' },
  'External Storage': { icon: HardDriveIcon, tone: 'from-teal-50 to-teal-100 text-teal-600' },
  Routers: { icon: RouterIcon, tone: 'from-cyan-50 to-cyan-100 text-cyan-600' },
  Speakers: { icon: SpeakerIcon, tone: 'from-orange-50 to-orange-100 text-orange-600' },
  Printers: { icon: PrinterIcon, tone: 'from-lime-50 to-lime-100 text-lime-700' },
  Tablets: { icon: TabletIcon, tone: 'from-fuchsia-50 to-fuchsia-100 text-fuchsia-600' },
}
const DEFAULT_ART = { icon: PackageIcon, tone: 'from-neutral-50 to-neutral-100 text-neutral-500' }

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
