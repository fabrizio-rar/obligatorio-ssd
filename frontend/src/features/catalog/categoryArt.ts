/** Icon and gradient per category: the photo fallback and the catalog chips. */
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

/** Icon and colors per category (full class names, so Tailwind includes them). */
export const CATEGORY_ART: Record<string, { icon: LucideIcon; tone: string }> = {
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
export const DEFAULT_ART = { icon: PackageIcon, tone: 'from-neutral-50 to-neutral-100 text-neutral-500' }

/** The category's icon (also used by the catalog's category chips). */
export function categoryIcon(category: string | null | undefined): LucideIcon {
  return (CATEGORY_ART[category ?? ''] ?? DEFAULT_ART).icon
}
