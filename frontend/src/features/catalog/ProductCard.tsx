import { Link } from 'react-router-dom'

import type { ProductCard as ProductCardData } from '@/api/types'
import { Card, CardContent, CardFooter } from '@/components/ui/card'
import { AddToCartButton } from '@/features/cart/AddToCartButton'
import { formatPrice, translateCategory, translateSubcategory } from '@/lib/format'

import { ProductImage } from './ProductImage'
import { Price, Rating, StockBadge } from './ProductMeta'

/** Catalog grid card. Every field comes from the API (price, stock and image from the DB). */
export function ProductCard({ product }: { product: ProductCardData }) {
  return (
    <Card className="h-full gap-3 pt-0">
      <Link to={`/products/${product.product_id}`} className="block overflow-hidden rounded-t-xl">
        <ProductImage
          src={product.image_url}
          alt={product.name}
          category={product.category}
          className="aspect-[4/3] w-full"
        />
      </Link>
      <CardContent className="flex flex-1 flex-col gap-1.5">
        <p className="text-xs text-muted-foreground">
          {translateCategory(product.category)} · {translateSubcategory(product.subcategory)}
        </p>
        <Link to={`/products/${product.product_id}`} className="font-medium leading-snug hover:underline">
          {product.name}
        </Link>
        <p className="text-xs text-muted-foreground">{product.brand}</p>
        <Rating rating={product.rating} reviews={product.review_count} />
        <Price
          className="mt-auto pt-1"
          current={product.current_price}
          list={product.list_price}
          discountPercent={product.discount_percent}
          currency={product.currency}
        />
      </CardContent>
      <CardFooter className="justify-between gap-2">
        <StockBadge available={product.available} status={product.stock_status} />
        <AddToCartButton productId={product.product_id} name={product.name} available={product.available} />
      </CardFooter>
    </Card>
  )
}

/** Row for the chat panel (AGENTS.md rule 11: cards are rendered from the API, by ID). */
export function ProductRow({ product }: { product: ProductCardData }) {
  return (
    <div className="flex gap-3 rounded-lg border bg-background p-2">
      <Link to={`/products/${product.product_id}`} className="shrink-0">
        <ProductImage
          src={product.image_url}
          alt={product.name}
          category={product.category}
          className="size-16 rounded-md"
        />
      </Link>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <Link to={`/products/${product.product_id}`} className="truncate text-sm font-medium hover:underline">
          {product.name}
        </Link>
        {/* The dataset has repeated names (e.g. two "Kairo Drive Pro 2TB"): this line tells them apart */}
        <p className="truncate text-xs text-muted-foreground">
          {product.brand} · {translateSubcategory(product.subcategory)} · SKU {product.sku}
        </p>
        <Price
          className="text-sm"
          current={product.current_price}
          list={product.list_price}
          discountPercent={product.discount_percent}
          currency={product.currency}
        />
        <div className="flex items-center justify-between gap-2">
          <StockBadge available={product.available} status={product.stock_status} />
          <AddToCartButton
            size="xs"
            productId={product.product_id}
            name={product.name}
            available={product.available}
          />
        </div>
      </div>
    </div>
  )
}

/** Small thumbnail for cart_update answers: what the agent just added or changed. */
export function ProductThumb({ product }: { product: ProductCardData }) {
  return (
    <Link
      to={`/products/${product.product_id}`}
      className="flex items-center gap-2 rounded-lg border bg-background p-1.5 pr-3 hover:bg-muted/50"
    >
      <ProductImage
        src={product.image_url}
        alt={product.name}
        category={product.category}
        className="size-10 shrink-0 rounded"
      />
      <span className="min-w-0">
        <span className="block truncate text-xs font-medium">{product.name}</span>
        <span className="block text-xs text-muted-foreground tabular-nums">
          {formatPrice(product.current_price, product.currency)}
        </span>
      </span>
    </Link>
  )
}
