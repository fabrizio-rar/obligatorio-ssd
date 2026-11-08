import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { getProductCards } from '@/api/endpoints'
import { MAX_COMPARE, MIN_COMPARE } from '@/api/types'
import { Button, buttonVariants } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ProductRow } from '@/features/catalog/ProductCard'
import { translateCategory } from '@/lib/format'

import { ComparisonTable } from './ComparisonTable'
import { useComparison } from './useComparison'

/** /compare?ids=a,b,c — the full comparison table, opened from the chat (RF-06). */
export function ComparePage() {
  const [params] = useSearchParams()
  const ids = [...new Set((params.get('ids') ?? '').split(',').map((id) => id.trim()).filter(Boolean))]
  const validCount = ids.length >= MIN_COMPARE && ids.length <= MAX_COMPARE
  const [onlyDifferences, setOnlyDifferences] = useState(false)

  const comparison = useComparison(validCount ? ids : [])
  // Cards for "Agregar": price and stock straight from the API
  const cards = useQuery({
    queryKey: ['product-cards', ids.join(',')],
    queryFn: () => getProductCards(ids),
    enabled: validCount,
  })

  if (!validCount) {
    return (
      <div className="flex flex-col items-start gap-3">
        <p>
          Para comparar hacen falta entre {MIN_COMPARE} y {MAX_COMPARE} productos de la misma categoría. Pedíselo al
          asistente, por ejemplo: “compará los dos primeros”.
        </p>
        <Link to="/" className={buttonVariants({ variant: 'outline' })}>
          Volver al catálogo
        </Link>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="text-xl font-semibold">
          Comparación{comparison.data && ` · ${translateCategory(comparison.data.category)}`}
        </h1>
        <Button variant="outline" size="sm" onClick={() => setOnlyDifferences(!onlyDifferences)}>
          {onlyDifferences ? 'Mostrar todo' : 'Solo diferencias'}
        </Button>
      </div>

      {cards.data && (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(16rem,1fr))] gap-3">
          {cards.data.items.map((product) => (
            <ProductRow key={product.product_id} product={product} />
          ))}
        </div>
      )}

      {comparison.isPending && <Skeleton className="h-96" />}
      {comparison.isError && (
        <div className="flex flex-col items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm">
          <p>{comparison.error.message}</p>
          <Link to="/" className={buttonVariants({ variant: 'outline', size: 'sm' })}>
            Volver al catálogo
          </Link>
        </div>
      )}
      {comparison.data && <ComparisonTable comparison={comparison.data} onlyDifferences={onlyDifferences} />}
      {comparison.data && (
        <p className="text-xs text-muted-foreground">
          En negrita, lo que cambia entre productos. “N/D” = sin dato; “—” = no corresponde a ese producto.
        </p>
      )}
    </div>
  )
}
