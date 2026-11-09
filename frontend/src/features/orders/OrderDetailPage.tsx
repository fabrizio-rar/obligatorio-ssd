import { useQuery } from '@tanstack/react-query'
import { CheckCircle2Icon, ChevronRightIcon, MapPinIcon } from 'lucide-react'
import { Link, useLocation, useParams } from 'react-router-dom'

import { ApiError } from '@/api/client'
import { getOrder } from '@/api/endpoints'
import type { Order } from '@/api/types'
import { buttonVariants } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ProductImage } from '@/features/catalog/ProductImage'
import { formatDateTime, formatPrice } from '@/lib/format'
import { useSession } from '@/lib/session'

import { OrderFacts } from './OrderFacts'

const STATUS_LABELS: Record<Order['status'], { label: string; tone: string }> = {
  CONFIRMED: { label: 'Confirmada', tone: 'bg-emerald-100 text-emerald-700' },
  PENDING_CONFIRMATION: { label: 'Pendiente de confirmar', tone: 'bg-amber-100 text-amber-800' },
  CANCELLED: { label: 'Cancelada', tone: 'bg-neutral-100 text-neutral-600' },
}

/** One order (RF-14/16): also the confirmation screen right after buying (state.justConfirmed). */
export function OrderDetailPage() {
  const { code = '' } = useParams()
  const session = useSession()
  const location = useLocation()
  const justConfirmed = (location.state as { justConfirmed?: boolean } | null)?.justConfirmed === true
  const order = useQuery({ queryKey: ['orders', code], queryFn: () => getOrder(code), enabled: session !== null })

  if (!session) {
    return (
      <p className="text-sm">
        <Link to="/login" state={{ from: location.pathname }} className="font-medium text-primary hover:underline">
          Iniciá sesión
        </Link>{' '}
        para ver tus órdenes.
      </p>
    )
  }
  if (order.isPending) return <Skeleton className="h-96 rounded-2xl" />
  if (order.isError) {
    const notFound = order.error instanceof ApiError && order.error.status === 404
    return (
      <div className="flex flex-col items-start gap-3">
        <p>{notFound ? 'No encontramos esa orden.' : order.error.message}</p>
        <Link to="/orders" className={buttonVariants({ variant: 'outline' })}>
          Ver mis órdenes
        </Link>
      </div>
    )
  }

  const o = order.data
  const status = STATUS_LABELS[o.status]
  const pickup = o.delivery_method === 'PICKUP'

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      {justConfirmed && o.status === 'CONFIRMED' && (
        <section className="flex flex-col items-center gap-2 rounded-2xl border border-emerald-200 bg-linear-to-br from-emerald-50 to-white p-8 text-center">
          <CheckCircle2Icon className="size-12 text-emerald-600" />
          <h1 className="text-2xl font-semibold tracking-tight">¡Gracias por tu compra!</h1>
          <p className="text-muted-foreground">
            Tu orden <span className="font-semibold text-foreground">{o.code}</span> está confirmada.
          </p>
          <p className="font-medium">
            {pickup
              ? `Lista para retirar en ${o.pickup_warehouse?.name ?? 'la sucursal'}${o.pickup_warehouse?.city ? `, ${o.pickup_warehouse.city}` : ''}.`
              : `Te la enviamos a ${o.shipping_address?.street}, ${o.shipping_address?.city}.`}
          </p>
        </section>
      )}

      <nav className="flex items-center gap-1 text-sm text-muted-foreground" aria-label="Ruta">
        <Link to="/orders" className="hover:text-primary">
          Mis órdenes
        </Link>
        <ChevronRightIcon className="size-3.5" />
        <span className="text-foreground">{o.code}</span>
      </nav>

      <section className="flex flex-col gap-5 rounded-2xl border bg-card p-6 shadow-xs">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold tracking-tight">Orden {o.code}</h2>
            <p className="text-sm text-muted-foreground">
              {o.confirmed_at ? `Confirmada el ${formatDateTime(o.confirmed_at)}` : `Creada el ${formatDateTime(o.created_at)}`}
            </p>
          </div>
          <span className={`rounded-full px-3 py-1 text-xs font-semibold ${status.tone}`}>{status.label}</span>
        </div>

        <OrderFacts order={o} />

        <ul className="flex flex-col divide-y rounded-xl border">
          {o.items.map((item) => (
            <li key={item.product_id} className="flex items-center gap-4 p-4">
              <Link to={`/products/${item.product_id}`} className="shrink-0">
                <ProductImage src={item.image_url} alt={item.name} category={item.category} className="size-16 rounded-lg" />
              </Link>
              <div className="min-w-0 flex-1">
                <Link to={`/products/${item.product_id}`} className="font-semibold hover:text-primary">
                  {item.name}
                </Link>
                <p className="text-xs text-muted-foreground">
                  SKU {item.sku} · {item.quantity} × {formatPrice(item.unit_price, o.currency)}
                </p>
                {item.allocations.length > 0 && (
                  <p className="mt-1 flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
                    <MapPinIcon className="size-3.5" />
                    Sale de: {item.allocations.map((a) => `${a.warehouse_name} (${a.quantity})`).join(', ')}
                  </p>
                )}
              </div>
              <p className="font-semibold tabular-nums">{formatPrice(item.line_total, o.currency)}</p>
            </li>
          ))}
        </ul>

        <dl className="ml-auto flex w-full max-w-xs flex-col gap-1 text-sm">
          <div className="flex justify-between">
            <dt className="text-muted-foreground">Subtotal</dt>
            <dd className="tabular-nums">{formatPrice(o.subtotal, o.currency)}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-muted-foreground">Envío</dt>
            <dd className="tabular-nums">{Number(o.shipping_cost) === 0 ? 'Gratis' : formatPrice(o.shipping_cost, o.currency)}</dd>
          </div>
          <div className="mt-1 flex items-baseline justify-between border-t pt-2">
            <dt className="font-semibold">Total</dt>
            <dd className="text-xl font-semibold tracking-tight tabular-nums">{formatPrice(o.total, o.currency)}</dd>
          </div>
        </dl>
      </section>

      <div className="flex flex-wrap gap-2">
        <Link to="/" className={buttonVariants()}>
          Seguir comprando
        </Link>
        <Link to="/orders" className={buttonVariants({ variant: 'outline' })}>
          Ver mis órdenes
        </Link>
      </div>
    </div>
  )
}
