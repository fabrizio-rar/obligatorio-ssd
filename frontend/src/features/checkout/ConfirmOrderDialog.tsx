import { useMutation } from '@tanstack/react-query'
import { AlertTriangleIcon, ShoppingBagIcon } from 'lucide-react'
import { useState } from 'react'

import { ApiError } from '@/api/client'
import { cancelOrder, confirmOrder } from '@/api/endpoints'
import type { Order, PriceChange } from '@/api/types'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { ProductImage } from '@/features/catalog/ProductImage'
import { OrderFacts } from '@/features/orders/OrderFacts'
import { formatPrice } from '@/lib/format'
import { cn } from '@/lib/utils'

/**
 * Human in the loop for the purchase (docs/PLAN.md §13): action, products, quantities, unit
 * price and total, all from the PENDING order the backend quoted. Only "Confirmar compra" buys.
 * A 409 PRICE_CHANGED keeps the dialog open with the new prices highlighted.
 */
export function ConfirmOrderDialog({
  order,
  onOrderChange,
  onClose,
  onConfirmed,
}: {
  order: Order
  onOrderChange: (order: Order) => void
  /** `reason`: why the purchase could not be done (stock, discontinued, cart changed). */
  onClose: (reason?: string) => void
  onConfirmed: (order: Order) => void
}) {
  const [changes, setChanges] = useState<PriceChange[]>([])
  const [notice, setNotice] = useState<string | null>(null)

  const confirm = useMutation({
    mutationFn: () => confirmOrder(order.order_id),
    onSuccess: onConfirmed,
    onError: (error) => {
      if (error instanceof ApiError && error.code === 'PRICE_CHANGED') {
        onOrderChange(error.details.order as Order)
        setChanges(error.details.changes as PriceChange[])
        setNotice(error.message)
        return
      }
      onClose(error.message)
    },
  })

  function cancel() {
    // The pending checkout is dropped; nothing was bought. If it fails, the next checkout replaces it.
    void cancelOrder(order.order_id).catch(() => undefined)
    onClose()
  }

  const changed = new Map(changes.map((c) => [c.product_id, c]))

  return (
    <AlertDialog open onOpenChange={(open) => !open && !confirm.isPending && cancel()}>
      {/* Same variant as the shadcn default (data-[size=default]:sm:max-w-sm) so this one wins */}
      <AlertDialogContent className="data-[size=default]:max-w-[calc(100%-2rem)] data-[size=default]:sm:max-w-2xl">
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2 text-lg font-semibold">
            <ShoppingBagIcon className="size-5 text-primary" />
            Confirmar compra
          </AlertDialogTitle>
          <AlertDialogDescription>Revisá tu pedido: al confirmar se realiza la compra.</AlertDialogDescription>
        </AlertDialogHeader>

        {notice && (
          <div role="alert" className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
            <AlertTriangleIcon className="mt-0.5 size-4 shrink-0" />
            <p>{notice}</p>
          </div>
        )}

        <ul className="flex flex-col divide-y rounded-lg border text-sm">
          {order.items.map((item) => {
            const change = changed.get(item.product_id)
            return (
              <li
                key={item.product_id}
                className={cn('flex items-center gap-3 px-3 py-2.5', change && 'bg-amber-50')}
              >
                <ProductImage
                  src={item.image_url}
                  alt={item.name}
                  category={item.category}
                  className="size-11 shrink-0 rounded-lg"
                />
                <span className="min-w-0 flex-1">
                  <span className="block font-medium">
                    {item.name} × {item.quantity}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    SKU {item.sku} ·{' '}
                    {change && (
                      <span className="mr-1 line-through">{formatPrice(change.old_price, order.currency)}</span>
                    )}
                    <span className={cn(change && 'font-semibold text-amber-800')}>
                      {formatPrice(item.unit_price, order.currency)}
                    </span>{' '}
                    c/u
                  </span>
                </span>
                <span className="shrink-0 font-medium tabular-nums">{formatPrice(item.line_total, order.currency)}</span>
              </li>
            )
          })}
        </ul>

        <dl className="flex flex-col gap-1 text-sm">
          <div className="flex justify-between">
            <dt className="text-muted-foreground">Subtotal</dt>
            <dd className="tabular-nums">{formatPrice(order.subtotal, order.currency)}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-muted-foreground">Envío</dt>
            <dd className="tabular-nums">
              {Number(order.shipping_cost) === 0 ? 'Gratis' : formatPrice(order.shipping_cost, order.currency)}
            </dd>
          </div>
          <div className="mt-1 flex items-baseline justify-between border-t pt-2">
            <dt className="font-semibold">Total (IVA incluido)</dt>
            <dd className="text-xl font-semibold tracking-tight tabular-nums">{formatPrice(order.total, order.currency)}</dd>
          </div>
        </dl>

        <OrderFacts order={order} />

        <AlertDialogFooter>
          {/* Closing the dialog (this button, Esc) cancels the pending checkout: see onOpenChange */}
          <AlertDialogCancel disabled={confirm.isPending}>
            Cancelar
          </AlertDialogCancel>
          <AlertDialogAction disabled={confirm.isPending} onClick={() => confirm.mutate()}>
            {confirm.isPending ? 'Confirmando…' : changes.length > 0 ? 'Confirmar con el precio nuevo' : 'Confirmar compra'}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
