import { useQuery } from '@tanstack/react-query'
import {
  BanIcon,
  CheckIcon,
  ChevronRightIcon,
  MapPinIcon,
  PackageIcon,
  RotateCcwIcon,
  ShieldCheckIcon,
  SparklesIcon,
  StarIcon,
  type LucideIcon,
} from 'lucide-react'
import { createElement, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'

import { ApiError } from '@/api/client'
import { getProduct } from '@/api/endpoints'
import type { ProductDetail, RelatedProduct, SpecValue } from '@/api/types'
import { Button, buttonVariants } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { AddToCartButton } from '@/features/cart/AddToCartButton'
import { formatPrice, translateCategory, translateSpecGroup, translateSubcategory, translateUseCase } from '@/lib/format'
import { cn } from '@/lib/utils'

import { categoryIcon } from './categoryArt'
import { ProductCard } from './ProductCard'
import { ProductImage } from './ProductImage'
import { StockBadge } from './ProductMeta'

/** Product detail (RF-01): specs, stock per warehouse and related products, from GET /api/products/{id}. */
export function ProductDetailPage() {
  const { productId = '' } = useParams()
  const product = useQuery({ queryKey: ['product', productId], queryFn: () => getProduct(productId) })

  if (product.isPending) {
    return (
      <div className="grid gap-6 rounded-2xl border bg-card p-6 md:grid-cols-2">
        <Skeleton className="aspect-square rounded-xl" />
        <div className="flex flex-col gap-3">
          <Skeleton className="h-8 w-2/3" />
          <Skeleton className="h-5 w-1/3" />
          <Skeleton className="h-24" />
        </div>
      </div>
    )
  }

  if (product.isError) {
    const notFound = product.error instanceof ApiError && product.error.status === 404
    return (
      <div className="flex flex-col items-start gap-3">
        <p>{notFound ? 'No encontramos ese producto.' : product.error.message}</p>
        <div className="flex gap-2">
          {!notFound && (
            <Button variant="outline" onClick={() => product.refetch()}>
              Reintentar
            </Button>
          )}
          <Link to="/" className={buttonVariants({ variant: 'outline' })}>
            Volver al catálogo
          </Link>
        </div>
      </div>
    )
  }

  const p = product.data
  const discontinued = p.status === 'discontinued'
  // The dataset has "None" as a placeholder in some key_features
  const features = p.key_features.filter((f) => f && f !== 'None')

  return (
    <div className="flex flex-col gap-6">
      <nav className="flex items-center gap-1 text-sm text-muted-foreground" aria-label="Ruta">
        <Link to="/" className="hover:text-primary">
          Catálogo
        </Link>
        <ChevronRightIcon className="size-3.5" />
        <Link to={`/?category=${encodeURIComponent(p.category)}`} className="hover:text-primary">
          {translateCategory(p.category)}
        </Link>
        <ChevronRightIcon className="size-3.5" />
        <span className="truncate text-foreground">{p.name}</span>
      </nav>

      {/* Main card, a 2x2 grid on large screens: row 1 = image | info + price (the image stretches
          to the height of the info, so both end at the same line); row 2 = highlights | perks */}
      <section className="grid gap-x-8 gap-y-5 rounded-2xl border bg-card p-6 shadow-xs lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
        <ProductImage
          src={discontinued ? null : p.image_url}
          alt={p.name}
          category={p.category}
          className="aspect-square w-full rounded-xl lg:aspect-auto lg:h-full lg:min-h-80"
        />
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Link
              to={`/?category=${encodeURIComponent(p.category)}`}
              className="inline-flex items-center gap-1.5 rounded-full bg-accent px-3 py-1 text-xs font-medium text-accent-foreground hover:bg-accent/70"
            >
              {createElement(categoryIcon(p.category), { className: 'size-3.5' })}
              {translateCategory(p.category)} · {translateSubcategory(p.subcategory)}
            </Link>
            <span className="text-xs text-muted-foreground">SKU {p.sku}</span>
          </div>

          <div className="flex flex-col gap-1">
            <h1 className="text-3xl font-semibold tracking-tight">{p.name}</h1>
            {p.brand && (
              <p className="text-sm text-muted-foreground">
                Marca{' '}
                <Link to={`/?brand=${encodeURIComponent(p.brand)}`} className="font-medium text-primary hover:underline">
                  {p.brand}
                </Link>
              </p>
            )}
          </div>

          <Stars rating={p.rating} reviews={p.review_count} />
          {p.short_description && <p className="text-muted-foreground">{p.short_description}</p>}

          {discontinued ? (
            <div className="flex items-start gap-2 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm">
              <BanIcon className="mt-0.5 size-4 shrink-0 text-destructive" />
              <p>
                Este producto está discontinuado y ya no se vende.
                {p.alternatives.length > 0 && ' Mirá las alternativas de abajo.'}
              </p>
            </div>
          ) : (
            <PurchaseBox product={p} />
          )}

        </div>
        {features.length > 0 && !discontinued && (
          <div className="rounded-xl bg-secondary/60 p-4">
            <h2 className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
              <SparklesIcon className="size-4 text-primary" />
              Lo destacado
            </h2>
            <ul className="grid gap-1.5 text-sm sm:grid-cols-2">
              {features.map((f) => (
                <li key={f} className="flex items-start gap-1.5">
                  <CheckIcon className="mt-0.5 size-4 shrink-0 text-emerald-600" />
                  {f}
                </li>
              ))}
            </ul>
          </div>
        )}
        {!discontinued && (
          <div className="lg:col-start-2">
            <Perks product={p} />
          </div>
        )}
      </section>

      {!discontinued && (
        <section className="rounded-2xl border bg-card p-6 shadow-xs">
          <Tabs defaultValue="description">
            <TabsList className="h-10 w-full">
              <TabsTrigger value="description">Descripción</TabsTrigger>
              <TabsTrigger value="specs">Especificaciones</TabsTrigger>
              <TabsTrigger value="stock">Stock por sucursal</TabsTrigger>
            </TabsList>
            <TabsContent value="description" className="pt-5">
              <Description product={p} />
            </TabsContent>
            <TabsContent value="specs" className="pt-5">
              <Specs specs={p.specs} />
            </TabsContent>
            <TabsContent value="stock" className="pt-5">
              <StockByWarehouse product={p} />
            </TabsContent>
          </Tabs>
        </section>
      )}

      <Related title="Alternativas" subtitle="Productos parecidos con stock" items={p.alternatives} />
      <Related title="Accesorios" subtitle="Van bien con este producto" items={p.accessories} />
      <Related title="Se compran juntos" subtitle="Lo que otros clientes suman" items={p.often_bought_with} />
    </div>
  )
}

/** Five stars filled by the rating (to the half), plus the number and the reviews. */
function Stars({ rating, reviews }: { rating: string | null; reviews: number | null }) {
  if (rating === null) return null
  const value = Number(rating)
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="flex" aria-hidden="true">
        {[1, 2, 3, 4, 5].map((i) => {
          const fill = Math.max(0, Math.min(1, value - (i - 1)))
          return (
            <span key={i} className="relative size-4">
              <StarIcon className="absolute size-4 text-amber-200" fill="currentColor" strokeWidth={0} />
              <span className="absolute inset-0 overflow-hidden" style={{ width: `${Math.round(fill * 2) * 50}%` }}>
                <StarIcon className="size-4 text-amber-400" fill="currentColor" strokeWidth={0} />
              </span>
            </span>
          )
        })}
      </span>
      <span className="font-medium">{value.toFixed(1)}</span>
      {reviews !== null && <span className="text-muted-foreground">({reviews.toLocaleString('es-UY')} opiniones)</span>}
    </div>
  )
}

function PurchaseBox({ product: p }: { product: ProductDetail }) {
  if (p.current_price === null || p.list_price === null || p.currency === null) return null
  const available = p.available ?? 0
  const discount = p.discount_percent ?? 0
  const saving = Number(p.list_price) - Number(p.current_price)
  return (
    <div className="flex flex-col gap-4 rounded-xl border bg-linear-to-br from-white to-secondary/50 p-5">
      <div className="flex flex-col gap-1">
        {discount > 0 && (
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground line-through tabular-nums">{formatPrice(p.list_price, p.currency)}</span>
            <span className="rounded-full bg-rose-100 px-2 py-0.5 text-xs font-semibold text-rose-700">-{discount}%</span>
          </div>
        )}
        <p className="text-4xl font-semibold tracking-tight tabular-nums">{formatPrice(p.current_price, p.currency)}</p>
        <p className="text-xs text-muted-foreground">
          IVA incluido
          {discount > 0 && saving > 0 && (
            <span className="ml-2 font-medium text-emerald-700">Ahorrás {formatPrice(saving, p.currency)}</span>
          )}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        {p.stock_status && <StockBadge available={available} status={p.stock_status} />}
        {available > 0 && <span className="text-muted-foreground">{available} unidades entre todas las sucursales</span>}
      </div>
      <AddToCartButton size="lg" className="h-11 w-full text-base" productId={p.product_id} name={p.name} available={available} />
    </div>
  )
}

/** Warranty and returns, from the product's data (stock per branch has its own tab). */
function Perks({ product: p }: { product: ProductDetail }) {
  const perks: { icon: LucideIcon; title: string; detail: string }[] = []
  if (p.warranty_months !== null)
    perks.push({ icon: ShieldCheckIcon, title: 'Garantía', detail: `${p.warranty_months} meses` })
  if (p.return_days !== null) perks.push({ icon: RotateCcwIcon, title: 'Devolución', detail: `${p.return_days} días` })
  return (
    <ul className="grid gap-2 sm:grid-cols-2">
      {perks.map(({ icon: Icon, title, detail }) => (
        <li key={title} className="flex items-center gap-2.5 rounded-xl border bg-card p-3">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-accent text-primary">
            <Icon className="size-4.5" />
          </span>
          <span className="leading-tight">
            <span className="block text-xs text-muted-foreground">{title}</span>
            <span className="text-sm font-medium">{detail}</span>
          </span>
        </li>
      ))}
    </ul>
  )
}

function Description({ product: p }: { product: ProductDetail }) {
  const facts: [string, string | null][] = [
    ['Marca', p.brand],
    ['Color', p.color],
    ['Peso', p.weight_kg ? `${p.weight_kg} kg` : null],
    ['Dimensiones', p.dimensions_cm ? `${p.dimensions_cm} cm` : null],
  ]
  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
      <div className="flex flex-col gap-5 text-sm">
        {p.description && <p className="leading-relaxed">{p.description}</p>}
        {p.recommended_for.length > 0 && (
          <UseCases title="Ideal para" uses={p.recommended_for} icon={CheckIcon} tone="bg-emerald-50 text-emerald-700 ring-emerald-200" />
        )}
        {p.not_recommended_for.length > 0 && (
          <UseCases title="No recomendado para" uses={p.not_recommended_for} icon={BanIcon} tone="bg-rose-50 text-rose-700 ring-rose-200" />
        )}
      </div>
      <dl className="h-fit divide-y rounded-xl border text-sm">
        {facts
          .filter((f): f is [string, string] => f[1] !== null)
          .map(([label, value]) => (
            <div key={label} className="flex justify-between gap-4 px-4 py-2.5">
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="text-right font-medium">{value}</dd>
            </div>
          ))}
      </dl>
    </div>
  )
}

function UseCases({ title, uses, icon: Icon, tone }: { title: string; uses: string[]; icon: LucideIcon; tone: string }) {
  return (
    <div className="flex flex-col gap-2">
      <h3 className="font-medium">{title}</h3>
      <ul className="flex flex-wrap gap-1.5">
        {uses.map((u) => (
          <li key={u} className={cn('inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium ring-1', tone)}>
            <Icon className="size-3.5" />
            {translateUseCase(u)}
          </li>
        ))}
      </ul>
    </div>
  )
}

function Specs({ specs }: { specs: SpecValue[] }) {
  if (specs.length === 0) return <p className="text-sm text-muted-foreground">Sin especificaciones cargadas.</p>
  const groups = new Map<string, SpecValue[]>()
  for (const spec of specs) {
    const key = spec.group ?? 'Otros'
    groups.set(key, [...(groups.get(key) ?? []), spec])
  }
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {[...groups].map(([group, values]) => (
        <div key={group} className="overflow-hidden rounded-xl border">
          <h3 className="bg-secondary/70 px-4 py-2 text-sm font-semibold text-secondary-foreground">
            {translateSpecGroup(group)}
          </h3>
          <dl className="divide-y text-sm">
            {values.map((s) => (
              <div key={s.name} className="flex justify-between gap-4 px-4 py-2.5">
                <dt className="text-muted-foreground">{s.name}</dt>
                <dd className={cn('text-right font-medium', !s.available && 'font-normal text-muted-foreground')}>
                  {s.value}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      ))}
    </div>
  )
}

function StockByWarehouse({ product: p }: { product: ProductDetail }) {
  return (
    <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
      {p.stock_by_warehouse.map((w) => (
        <li key={w.warehouse_id} className="flex items-center gap-3 rounded-xl border p-3">
          <span
            className={cn(
              'flex size-9 shrink-0 items-center justify-center rounded-lg',
              w.available > 0 ? 'bg-emerald-50 text-emerald-700' : 'bg-neutral-100 text-neutral-500',
            )}
          >
            <MapPinIcon className="size-4.5" />
          </span>
          <span className="min-w-0 flex-1 leading-tight">
            <span className="block truncate text-sm font-medium">{w.name}</span>
            <span className="text-xs text-muted-foreground">
              {w.city ?? '—'}
              {w.pickup_enabled ? ' · Retiro disponible' : ' · Sin retiro'}
            </span>
          </span>
          <StockCount available={w.available} />
        </li>
      ))}
    </ul>
  )
}

function StockCount({ available }: { available: number }): ReactNode {
  if (available <= 0) return <span className="text-sm text-muted-foreground">Sin stock</span>
  return (
    <span className="flex items-center gap-1 text-sm font-medium tabular-nums">
      <PackageIcon className="size-4 text-emerald-600" />
      {available}
    </span>
  )
}

function Related({ title, subtitle, items }: { title: string; subtitle: string; items: RelatedProduct[] }) {
  if (items.length === 0) return null
  return (
    <section className="flex flex-col gap-3">
      <div>
        <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
        <p className="text-sm text-muted-foreground">{subtitle}</p>
      </div>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(14rem,1fr))] gap-4">
        {items.map((item) => (
          <ProductCard key={item.product_id} product={item} />
        ))}
      </div>
    </section>
  )
}
