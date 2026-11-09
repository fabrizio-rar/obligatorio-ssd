import { MinusIcon, PlusIcon, ShoppingCartIcon, Trash2Icon } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { MAX_QUANTITY_PER_ITEM, type Cart, type CartItem } from '@/api/types'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { ProductImage } from '@/features/catalog/ProductImage'
import { formatPrice } from '@/lib/format'

import { useCart, useClearCart, useRemoveFromCart, useSetCartQuantity } from './useCart'

/** Header button with the item count, and the cart drawer (RF-09/10). */
export function CartSheet() {
  const [open, setOpen] = useState(false)
  const cart = useCart()
  const count = cart.data?.item_count ?? 0

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger
        render={
          <Button
            variant="ghost"
            className="relative border border-white/15 bg-white/10 text-white hover:bg-white/20 hover:text-white"
            aria-label={`Carrito: ${count} productos`}
          >
            <ShoppingCartIcon data-icon="inline-start" />
            Carrito
            {count > 0 && (
              <Badge className="ml-1 h-5 min-w-5 bg-fuchsia-500 px-1.5 text-white">{count}</Badge>
            )}
          </Button>
        }
      />
      <SheetContent className="w-full gap-0 sm:max-w-md">
        <SheetHeader className="border-b">
          <SheetTitle>Tu carrito</SheetTitle>
          <SheetDescription>
            {count === 0 ? 'Todavía no agregaste productos.' : `${count} ${count === 1 ? 'unidad' : 'unidades'}`}
          </SheetDescription>
        </SheetHeader>

        {cart.isPending && (
          <div className="flex flex-col gap-3 p-4">
            <Skeleton className="h-20" />
            <Skeleton className="h-20" />
          </div>
        )}
        {cart.isError && <p className="p-4 text-sm text-destructive">{cart.error.message}</p>}
        {cart.data && cart.data.items.length > 0 && (
          <>
            <ScrollArea className="min-h-0 flex-1">
              <ul className="flex flex-col">
                {cart.data.items.map((item) => (
                  <li key={item.product_id} className="border-b p-4">
                    <CartLine item={item} onNavigate={() => setOpen(false)} />
                  </li>
                ))}
              </ul>
            </ScrollArea>
            <CartSummary cart={cart.data} onCheckout={() => setOpen(false)} />
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}

const ISSUE_TEXT: Record<CartItem['issues'][number], (item: CartItem) => string> = {
  INACTIVE: () => 'Discontinuado: quitalo para poder comprar.',
  OUT_OF_STOCK: () => 'Sin stock: quitalo para poder comprar.',
  INSUFFICIENT_STOCK: (item) => `Solo quedan ${item.available}: tocá “−” para bajar a ${item.available}.`,
}

function CartLine({ item, onNavigate }: { item: CartItem; onNavigate: () => void }) {
  const setQuantity = useSetCartQuantity()
  const remove = useRemoveFromCart()
  const busy = setQuantity.isPending || remove.isPending
  const maxQuantity = Math.min(MAX_QUANTITY_PER_ITEM, item.available)
  // The backend checks the NEW quantity against the stock: when the cart has more than what is
  // left, "−" goes straight to the available amount (3 → 1), not one by one (3 → 2 would fail)
  const overStock = item.quantity > item.available
  const minusTarget = overStock ? item.available : item.quantity - 1
  const canDecrease = item.active && item.available > 0 && minusTarget >= 1

  return (
    <div className="flex gap-3">
      {/* Never show the photo of an inactive product: the category icon instead */}
      <ProductImage
        src={item.active ? item.image_url : null}
        alt={item.name}
        category={item.category}
        className="size-16 shrink-0 rounded-md border"
      />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <Link
          to={`/products/${item.product_id}`}
          onClick={onNavigate}
          className="truncate font-medium hover:underline"
        >
          {item.name}
        </Link>
        <p className="text-xs text-muted-foreground">
          {item.brand} · {formatPrice(item.unit_price, item.currency)} c/u
          {item.discount_percent > 0 && (
            <span className="ml-1 whitespace-nowrap line-through">{formatPrice(item.list_price, item.currency)}</span>
          )}
        </p>
        {item.issues.map((issue) => (
          <p key={issue} className="text-xs font-medium text-destructive">
            {ISSUE_TEXT[issue](item)}
          </p>
        ))}
        <div className="mt-1 flex items-center gap-1">
          <Button
            variant="outline"
            size="icon"
            className="size-7"
            aria-label={overStock ? `Bajar a ${item.available}` : 'Restar uno'}
            title={overStock ? `Bajar a ${item.available}` : undefined}
            disabled={busy || !canDecrease}
            onClick={() => setQuantity.mutate({ productId: item.product_id, quantity: minusTarget })}
          >
            <MinusIcon />
          </Button>
          <span className="w-8 text-center text-sm tabular-nums">{item.quantity}</span>
          <Button
            variant="outline"
            size="icon"
            className="size-7"
            aria-label="Sumar uno"
            disabled={busy || item.quantity >= maxQuantity || !item.active}
            onClick={() => setQuantity.mutate({ productId: item.product_id, quantity: item.quantity + 1 })}
          >
            <PlusIcon />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="ml-auto text-muted-foreground"
            disabled={busy}
            onClick={() => remove.mutate(item.product_id)}
          >
            <Trash2Icon data-icon="inline-start" />
            Quitar
          </Button>
        </div>
      </div>
      <p className="shrink-0 text-sm font-medium tabular-nums">{formatPrice(item.line_total, item.currency)}</p>
    </div>
  )
}

function CartSummary({ cart, onCheckout }: { cart: Cart; onCheckout: () => void }) {
  const navigate = useNavigate()
  const clear = useClearCart()
  const [confirmOpen, setConfirmOpen] = useState(false)

  return (
    <SheetFooter className="border-t">
      <div className="flex items-baseline justify-between">
        <span className="text-sm text-muted-foreground">Total (IVA incluido)</span>
        <span className="text-lg font-semibold tabular-nums">{formatPrice(cart.total, cart.currency)}</span>
      </div>
      {!cart.can_checkout && (
        <p className="text-xs text-destructive">Resolvé los avisos de arriba para poder comprar.</p>
      )}
      <Button
        size="lg"
        disabled={!cart.can_checkout}
        onClick={() => {
          onCheckout()
          navigate('/checkout')
        }}
      >
        Continuar al checkout
      </Button>
      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogTrigger render={<Button variant="ghost" disabled={clear.isPending} />}>
          Vaciar carrito
        </AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>¿Vaciar el carrito?</AlertDialogTitle>
            <AlertDialogDescription>Se quitan todos estos productos:</AlertDialogDescription>
          </AlertDialogHeader>
          <ul className="flex flex-col gap-1 text-sm">
            {cart.items.map((item) => (
              <li key={item.product_id} className="flex justify-between gap-2">
                <span className="truncate">
                  {item.name} × {item.quantity}
                </span>
                <span className="tabular-nums">{formatPrice(item.line_total, item.currency)}</span>
              </li>
            ))}
          </ul>
          <Separator />
          <p className="flex justify-between text-sm font-medium">
            <span>Total</span>
            <span className="tabular-nums">{formatPrice(cart.total, cart.currency)}</span>
          </p>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                setConfirmOpen(false)
                clear.mutate()
              }}
            >
              Vaciar carrito
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </SheetFooter>
  )
}
