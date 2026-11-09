import { StarIcon } from 'lucide-react'

import type { StockStatus } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { formatPrice, translateStockStatus } from '@/lib/format'
import { cn } from '@/lib/utils'

/** Current price, plus the list price struck through when there is a discount. */
export function Price({
  current,
  list,
  discountPercent,
  currency,
  className,
}: {
  current: string
  list: string
  discountPercent: number
  currency: string
  className?: string
}) {
  return (
    <div className={cn('flex flex-wrap items-baseline gap-x-2', className)}>
      <span className="text-lg font-semibold tracking-tight tabular-nums">{formatPrice(current, currency)}</span>
      {discountPercent > 0 && (
        <>
          <span className="text-xs text-muted-foreground line-through tabular-nums">
            {formatPrice(list, currency)}
          </span>
          <Badge className="bg-rose-100 text-rose-700">-{discountPercent}%</Badge>
        </>
      )}
    </div>
  )
}

/** "Sin stock", "Quedan N" (1–2 units) or "En stock" (docs/PLAN.md §13). */
export function StockBadge({ available, status }: { available: number; status: StockStatus }) {
  if (available <= 0) return <Badge className="bg-neutral-100 text-neutral-600">Sin stock</Badge>
  if (status === 'Low stock') return <Badge className="bg-amber-100 text-amber-800">Quedan {available}</Badge>
  return <Badge className="bg-emerald-100 text-emerald-700">{translateStockStatus(status)}</Badge>
}

export function Rating({ rating, reviews }: { rating: string | null; reviews: number | null }) {
  if (rating === null) return null
  return (
    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
      <StarIcon className="size-3 fill-amber-400 text-amber-400" />
      {Number(rating).toFixed(1)}
      {reviews !== null && <span>({reviews.toLocaleString('es-UY')})</span>}
    </span>
  )
}
