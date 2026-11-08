import { useQuery } from '@tanstack/react-query'
import { ChevronRightIcon } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'

import { ApiError } from '@/api/client'
import { getProduct } from '@/api/endpoints'
import type { ProductDetail, RelatedProduct, SpecValue } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { AddToCartButton } from '@/features/cart/AddToCartButton'
import { translateCategory, translateSpecGroup, translateSubcategory, translateUseCase } from '@/lib/format'

import { ProductCard } from './ProductCard'
import { ProductImage } from './ProductImage'
import { Price, Rating, StockBadge } from './ProductMeta'

/** Product detail (RF-01): specs, stock per warehouse and related products, from GET /api/products/{id}. */
export function ProductDetailPage() {
  const { productId = '' } = useParams()
  const product = useQuery({ queryKey: ['product', productId], queryFn: () => getProduct(productId) })

  if (product.isPending) {
    return (
      <div className="grid gap-6 md:grid-cols-2">
        <Skeleton className="aspect-[4/3] rounded-xl" />
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

  return (
    <div className="flex flex-col gap-8">
      <nav className="flex items-center gap-1 text-sm text-muted-foreground" aria-label="Ruta">
        <Link to="/" className="hover:underline">
          Catálogo
        </Link>
        <ChevronRightIcon className="size-3.5" />
        <Link to={`/?category=${encodeURIComponent(p.category)}`} className="hover:underline">
          {translateCategory(p.category)}
        </Link>
        <ChevronRightIcon className="size-3.5" />
        <span className="truncate text-foreground">{p.name}</span>
      </nav>

      <div className="grid gap-6 md:grid-cols-2">
        <ProductImage
          src={discontinued ? null : p.image_url}
          alt={p.name}
          category={p.category}
          className="aspect-[4/3] w-full rounded-xl border"
        />
        <div className="flex flex-col gap-3">
          <p className="text-sm text-muted-foreground">
            {translateCategory(p.category)} · {translateSubcategory(p.subcategory)} · SKU {p.sku}
          </p>
          <h1 className="text-2xl font-semibold">{p.name}</h1>
          {p.brand && <p className="text-muted-foreground">{p.brand}</p>}
          <Rating rating={p.rating} reviews={p.review_count} />
          {p.short_description && <p>{p.short_description}</p>}

          {discontinued ? (
            <p className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm">
              Este producto está discontinuado y ya no se vende.
              {p.alternatives.length > 0 && ' Mirá las alternativas de abajo.'}
            </p>
          ) : (
            <PurchaseBox product={p} />
          )}

          <ul className="text-sm text-muted-foreground">
            {p.warranty_months !== null && <li>Garantía: {p.warranty_months} meses</li>}
            {p.return_days !== null && <li>Devolución: {p.return_days} días</li>}
            {p.color && <li>Color: {p.color}</li>}
          </ul>
        </div>
      </div>

      {!discontinued && (
        <Tabs defaultValue="description">
          <TabsList>
            <TabsTrigger value="description">Descripción</TabsTrigger>
            <TabsTrigger value="specs">Especificaciones</TabsTrigger>
            <TabsTrigger value="stock">Stock por sucursal</TabsTrigger>
          </TabsList>
          <TabsContent value="description" className="pt-4">
            <Description product={p} />
          </TabsContent>
          <TabsContent value="specs" className="pt-4">
            <Specs specs={p.specs} />
          </TabsContent>
          <TabsContent value="stock" className="pt-4">
            <StockByWarehouse product={p} />
          </TabsContent>
        </Tabs>
      )}

      <Related title="Alternativas" items={p.alternatives} />
      <Related title="Accesorios" items={p.accessories} />
      <Related title="Se compran juntos" items={p.often_bought_with} />
    </div>
  )
}

function PurchaseBox({ product: p }: { product: ProductDetail }) {
  if (p.current_price === null || p.list_price === null || p.currency === null) return null
  const available = p.available ?? 0
  return (
    <div className="flex flex-col gap-3 rounded-lg border p-4">
      <Price
        className="text-xl"
        current={p.current_price}
        list={p.list_price}
        discountPercent={p.discount_percent ?? 0}
        currency={p.currency}
      />
      <p className="text-xs text-muted-foreground">IVA incluido</p>
      <div className="flex items-center gap-3">
        {p.stock_status && <StockBadge available={available} status={p.stock_status} />}
        {available > 0 && (
          <span className="text-sm text-muted-foreground">{available} disponibles entre todas las sucursales</span>
        )}
      </div>
      <AddToCartButton size="lg" className="w-fit" productId={p.product_id} name={p.name} available={available} />
    </div>
  )
}

function Description({ product: p }: { product: ProductDetail }) {
  // The dataset has "None" as a placeholder in some key_features
  const features = p.key_features.filter((f) => f && f !== 'None')
  return (
    <div className="flex max-w-3xl flex-col gap-4 text-sm">
      {p.description && <p className="leading-relaxed">{p.description}</p>}
      {features.length > 0 && (
        <div>
          <h3 className="mb-1 font-medium">Características</h3>
          <ul className="list-inside list-disc">
            {features.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        </div>
      )}
      {p.recommended_for.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-medium">Ideal para:</span>
          {p.recommended_for.map((u) => (
            <Badge key={u} variant="secondary">
              {translateUseCase(u)}
            </Badge>
          ))}
        </div>
      )}
      {p.not_recommended_for.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-medium">No recomendado para:</span>
          {p.not_recommended_for.map((u) => (
            <Badge key={u} variant="outline">
              {translateUseCase(u)}
            </Badge>
          ))}
        </div>
      )}
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
    <div className="grid max-w-3xl gap-6 md:grid-cols-2">
      {[...groups].map(([group, values]) => (
        <div key={group}>
          <h3 className="mb-1 text-sm font-medium">{translateSpecGroup(group)}</h3>
          <Table>
            <TableBody>
              {values.map((s) => (
                <TableRow key={s.name}>
                  <TableCell className="text-muted-foreground">{s.name}</TableCell>
                  <TableCell className={s.available ? '' : 'text-muted-foreground'}>{s.value}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ))}
    </div>
  )
}

function StockByWarehouse({ product: p }: { product: ProductDetail }) {
  return (
    <Table className="max-w-2xl">
      <TableHeader>
        <TableRow>
          <TableHead>Sucursal</TableHead>
          <TableHead>Ciudad</TableHead>
          <TableHead className="text-right">Disponibles</TableHead>
          <TableHead>Retiro</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {p.stock_by_warehouse.map((w) => (
          <TableRow key={w.warehouse_id}>
            <TableCell>{w.name}</TableCell>
            <TableCell className="text-muted-foreground">{w.city ?? '—'}</TableCell>
            <TableCell className="text-right tabular-nums">{w.available}</TableCell>
            <TableCell>{w.pickup_enabled ? 'Sí' : 'No'}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function Related({ title, items }: { title: string; items: RelatedProduct[] }) {
  if (items.length === 0) return null
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-lg font-semibold">{title}</h2>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(14rem,1fr))] gap-4">
        {items.map((item) => (
          <ProductCard key={item.product_id} product={item} />
        ))}
      </div>
    </section>
  )
}
