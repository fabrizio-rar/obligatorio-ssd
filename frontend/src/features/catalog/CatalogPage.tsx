import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ChevronLeftIcon, ChevronRightIcon } from 'lucide-react'
import { useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'

import { getCategories, getProducts } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { translateCategory } from '@/lib/format'

import { ProductCard } from './ProductCard'

/**
 * Catalog (RF-01): active products only, paginated, filtered by category.
 * The API only filters by category today (docs/PLAN.md §12); search is done through the chat.
 */
export function CatalogPage() {
  const [params, setParams] = useSearchParams()
  const category = params.get('category')
  const page = Math.max(1, Number(params.get('page')) || 1)

  const categories = useQuery({ queryKey: ['categories'], queryFn: getCategories, staleTime: Infinity })
  // A category typed in the URL that does not exist: FastAPI would answer a 422 without our error format
  const unknownCategory =
    category !== null && categories.data !== undefined && !categories.data.some((c) => c.name === category)
  const products = useQuery({
    queryKey: ['products', category, page],
    queryFn: () => getProducts(category, page),
    placeholderData: keepPreviousData,
    enabled: category === null || (categories.data !== undefined && !unknownCategory),
  })

  // ?page= beyond the last page (old link, or the catalog shrank): go back to the first one
  const lastPage = products.data?.total_pages ?? 0
  useEffect(() => {
    if (lastPage >= 1 && page > lastPage) {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          next.delete('page')
          return next
        },
        { replace: true },
      )
    }
  }, [lastPage, page, setParams])

  function goTo(next: { category?: string | null; page?: number }) {
    const nextCategory = next.category === undefined ? category : next.category
    const nextParams = new URLSearchParams()
    if (nextCategory) nextParams.set('category', nextCategory)
    if (next.page && next.page > 1) nextParams.set('page', String(next.page))
    setParams(nextParams)
    window.scrollTo({ top: 0 })
  }

  // keepPreviousData would keep showing the last grid under an unknown category
  const data = unknownCategory ? undefined : products.data
  const totalPages = data?.total_pages ?? 1

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap gap-2" role="group" aria-label="Categorías">
        <Button size="sm" variant={category ? 'outline' : 'default'} onClick={() => goTo({ category: null })}>
          Todo
        </Button>
        {categories.data?.map((c) => (
          <Button
            key={c.category_id}
            size="sm"
            variant={category === c.name ? 'default' : 'outline'}
            onClick={() => goTo({ category: c.name })}
          >
            {translateCategory(c.name)}
            <span className="text-xs opacity-60">{c.product_count}</span>
          </Button>
        ))}
      </div>

      <div className="flex items-baseline justify-between">
        <h1 className="text-xl font-semibold">
          {category && !unknownCategory ? translateCategory(category) : 'Todos los productos'}
        </h1>
        {data && <p className="text-sm text-muted-foreground">{data.total} productos</p>}
      </div>

      {unknownCategory && (
        <div className="flex flex-col items-start gap-2 rounded-lg border p-4 text-sm">
          <p>No existe la categoría “{category}”.</p>
          <Button variant="outline" size="sm" onClick={() => goTo({ category: null })}>
            Ver todos los productos
          </Button>
        </div>
      )}

      {products.isError && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm">
          <p>{products.error.message}</p>
          <Button variant="outline" size="sm" className="mt-2" onClick={() => products.refetch()}>
            Reintentar
          </Button>
        </div>
      )}

      <div className="grid grid-cols-[repeat(auto-fill,minmax(14rem,1fr))] gap-4">
        {products.isPending &&
          !unknownCategory &&
          Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-80 rounded-xl" />)}
        {data?.items.map((product) => <ProductCard key={product.product_id} product={product} />)}
      </div>

      {data && data.total === 0 && <p className="text-muted-foreground">No hay productos en esta categoría.</p>}

      {totalPages > 1 && (
        <nav className="flex items-center justify-center gap-3" aria-label="Paginación">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => goTo({ page: page - 1 })}>
            <ChevronLeftIcon data-icon="inline-start" />
            Anterior
          </Button>
          <span className="text-sm text-muted-foreground tabular-nums">
            Página {page} de {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= totalPages}
            onClick={() => goTo({ page: page + 1 })}
          >
            Siguiente
            <ChevronRightIcon data-icon="inline-end" />
          </Button>
        </nav>
      )}
    </div>
  )
}
