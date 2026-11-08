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
      <span className="font-semibold tabular-nums">{formatPrice(current, currency)}</span>
      {discountPercent > 0 && (
        <>
          <span className="text-xs text-muted-foreground line-through tabular-nums">
            {formatPrice(list, currency)}
          </span>
          <Badge variant="destructive">-{discountPercent}%</Badge>
        </>
      )}
    </div>
  )
}

/** "Sin stock", "Quedan N" (1–2 units) or "En stock" (docs/PLAN.md §13). */
export function StockBadge({ available, status }: { available: number; status: StockStatus }) {
  if (available <= 0) return <Badge variant="outline">Sin stock</Badge>
  if (status === 'Low stock') return <Badge variant="secondary">Quedan {available}</Badge>
  return <Badge variant="secondary">{translateStockStatus(status)}</Badge>
}

export function Rating({ rating, reviews }: { rating: string | null; reviews: number | null }) {
  if (rating === null) return null
  return (
    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
      <StarIcon className="size-3 fill-current" />
      {Number(rating).toFixed(1)}
      {reviews !== null && <span>({reviews.toLocaleString('es-UY')})</span>}
    </span>
  )
}
