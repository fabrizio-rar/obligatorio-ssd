import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ChevronLeftIcon, ChevronRightIcon, LayoutGridIcon, type LucideIcon } from 'lucide-react'
import { type ReactNode, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'

import {
  type CatalogFilters,
  getBrands,
  getCategories,
  getProducts,
  PRODUCT_SORTS,
  type ProductSort,
} from '@/api/endpoints'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { translateCategory } from '@/lib/format'
import { cn } from '@/lib/utils'

import { CatalogFiltersBar } from './CatalogFiltersBar'
import { ProductCard } from './ProductCard'
import { categoryIcon } from './categoryArt'

const SORT_LABELS: Record<ProductSort, string> = {
  default: 'Categoría',
  name_asc: 'Nombre: A - Z',
  name_desc: 'Nombre: Z - A',
  price_asc: 'Precio: menor a mayor',
  price_desc: 'Precio: mayor a menor',
}

/** ?sort= from the URL; an unknown value falls back to the default order. */
function sortParam(value: string | null): ProductSort {
  return PRODUCT_SORTS.find((s) => s === value) ?? 'default'
}

/** ?min_price= / ?max_price= from the URL: a number ≥ 0, anything else is ignored. */
function priceParam(value: string | null): number | null {
  if (value === null || value.trim() === '') return null
  const n = Number(value)
  return Number.isFinite(n) && n >= 0 ? n : null
}

/**
 * Catalog (RF-01): active products only, paginated, filtered by category, brand, price range and
 * stock (docs/PLAN.md §12). All the state is in the URL. Free-text search is done through the chat.
 */
export function CatalogPage() {
  const [params, setParams] = useSearchParams()
  const category = params.get('category')
  const page = Math.max(1, Number(params.get('page')) || 1)
  let minPrice = priceParam(params.get('min_price'))
  let maxPrice = priceParam(params.get('max_price'))
  if (minPrice !== null && maxPrice !== null && minPrice > maxPrice) [minPrice, maxPrice] = [maxPrice, minPrice]
  const filters: CatalogFilters = {
    category,
    brand: params.get('brand') || null,
    minPrice,
    maxPrice,
    inStock: params.get('in_stock') === 'true',
    sort: sortParam(params.get('sort')),
  }

  const categories = useQuery({ queryKey: ['categories'], queryFn: getCategories, staleTime: Infinity })
  // A category typed in the URL that does not exist: FastAPI would answer a 422 without our error format
  const unknownCategory =
    category !== null && categories.data !== undefined && !categories.data.some((c) => c.name === category)
  const products = useQuery({
    queryKey: ['products', filters, page],
    queryFn: () => getProducts(filters, page),
    placeholderData: keepPreviousData,
    enabled: category === null || (categories.data !== undefined && !unknownCategory),
  })
  const brands = useQuery({
    queryKey: ['brands', category],
    queryFn: () => getBrands(category),
    staleTime: Infinity,
    enabled: !unknownCategory,
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

  /** Any change of category or filter goes back to page 1. Changing the category keeps the price
   * and stock filters but drops the brand (it may not exist in the new category). */
  function goTo(next: Partial<CatalogFilters> & { page?: number }) {
    const f: CatalogFilters = {
      ...filters,
      ...(next.category !== undefined && next.category !== category ? { brand: null } : {}),
      ...next,
    }
    const nextParams = new URLSearchParams()
    if (f.category) nextParams.set('category', f.category)
    if (f.brand) nextParams.set('brand', f.brand)
    if (f.minPrice !== null) nextParams.set('min_price', String(f.minPrice))
    if (f.maxPrice !== null) nextParams.set('max_price', String(f.maxPrice))
    if (f.inStock) nextParams.set('in_stock', 'true')
    if (f.sort !== 'default') nextParams.set('sort', f.sort)
    if (next.page && next.page > 1) nextParams.set('page', String(next.page))
    setParams(nextParams)
    window.scrollTo({ top: 0 })
  }

  const hasFilters = filters.brand !== null || minPrice !== null || maxPrice !== null || filters.inStock
  const clearFilters = () => goTo({ brand: null, minPrice: null, maxPrice: null, inStock: false })

  // keepPreviousData would keep showing the last grid under an unknown category
  const data = unknownCategory ? undefined : products.data
  const totalPages = data?.total_pages ?? 1

  return (
    <div className="flex flex-col gap-5">

      <div className="flex flex-wrap gap-2" role="group" aria-label="Categorías">
        <CategoryChip active={!category} onClick={() => goTo({ category: null })} icon={LayoutGridIcon}>
          Todo
        </CategoryChip>
        {categories.data?.map((c) => (
          <CategoryChip
            key={c.category_id}
            active={category === c.name}
            onClick={() => goTo({ category: c.name })}
            icon={categoryIcon(c.name)}
          >
            {translateCategory(c.name)}
            <span className="text-xs opacity-60">{c.product_count}</span>
          </CategoryChip>
        ))}
      </div>

      {!unknownCategory && (
        <CatalogFiltersBar filters={filters} brands={brands.data} onChange={goTo} onClear={clearFilters} />
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold tracking-tight">
          {category && !unknownCategory ? translateCategory(category) : 'Todos los productos'}
        </h2>
        <div className="flex items-center gap-4">
          {data && <p className="text-sm text-muted-foreground">{data.total} productos</p>}
          {/* Not a filter: "Limpiar filtros" keeps it */}
          <div className="flex items-center gap-2">
            <Label htmlFor="catalog-sort" className="text-muted-foreground">
              Ordenar por
            </Label>
            <select
              id="catalog-sort"
              className="h-8 rounded-lg border border-input bg-background px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
              value={filters.sort}
              onChange={(e) => goTo({ sort: sortParam(e.target.value) })}
            >
              {PRODUCT_SORTS.map((s) => (
                <option key={s} value={s}>
                  {SORT_LABELS[s]}
                </option>
              ))}
            </select>
          </div>
        </div>
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

      {data && data.total === 0 && (
        <div className="flex flex-col items-start gap-2 text-muted-foreground">
          <p>{hasFilters ? 'No hay productos con estos filtros.' : 'No hay productos en esta categoría.'}</p>
          {hasFilters && (
            <Button variant="outline" size="sm" onClick={clearFilters}>
              Limpiar filtros
            </Button>
          )}
        </div>
      )}

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

function CategoryChip({
  active,
  icon: Icon,
  onClick,
  children,
}: {
  active: boolean
  icon: LucideIcon
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        'inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-sm font-medium transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50',
        active
          ? 'border-transparent bg-primary text-primary-foreground shadow-sm shadow-primary/30'
          : 'border-border bg-card text-foreground hover:border-primary/40 hover:bg-accent hover:text-accent-foreground',
      )}
    >
      <Icon className="size-4" />
      {children}
    </button>
  )
}
