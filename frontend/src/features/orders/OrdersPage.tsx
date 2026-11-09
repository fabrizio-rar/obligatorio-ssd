import { useQuery } from '@tanstack/react-query'
import { ChevronRightIcon, PackageIcon, StoreIcon, TruckIcon } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'

import { getOrders } from '@/api/endpoints'
import { buttonVariants } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDateTime, formatPrice } from '@/lib/format'
import { useSession } from '@/lib/session'

/** "Mis órdenes" (RF-16): the user's purchases, newest first (GET /api/orders). */
export function OrdersPage() {
  const session = useSession()
  const location = useLocation()
  const orders = useQuery({ queryKey: ['orders', 'list'], queryFn: () => getOrders(50), enabled: session !== null })

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

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-5">
      <h1 className="text-2xl font-semibold tracking-tight">Mis órdenes</h1>
      {orders.isPending && <Skeleton className="h-48 rounded-2xl" />}
      {orders.isError && <p className="text-sm text-destructive">{orders.error.message}</p>}
      {orders.data?.items.length === 0 && (
        <div className="flex flex-col items-center gap-3 rounded-2xl border bg-card p-10 text-center">
          <PackageIcon className="size-10 text-primary" />
          <p className="font-medium">Todavía no hiciste ninguna compra</p>
          <Link to="/" className={buttonVariants()}>
            Ir al catálogo
          </Link>
        </div>
      )}
      <ul className="flex flex-col gap-3">
        {orders.data?.items.map((o) => {
          const Icon = o.delivery_method === 'PICKUP' ? StoreIcon : TruckIcon
          const more = o.item_count - o.product_names.length
          return (
            <li key={o.order_id}>
              <Link
                to={`/orders/${o.code}`}
                className="group flex items-center gap-4 rounded-2xl border bg-card p-4 shadow-xs transition-colors hover:border-primary/40"
              >
                <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-accent text-primary">
                  <Icon className="size-5" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-baseline gap-x-2">
                    <span className="font-semibold">{o.code}</span>
                    <span className="text-xs text-muted-foreground">
                      {o.confirmed_at ? formatDateTime(o.confirmed_at) : formatDateTime(o.created_at)}
                    </span>
                  </span>
                  <span className="block truncate text-sm text-muted-foreground">
                    {o.product_names.join(', ')}
                    {more > 0 && ` y ${more} más`} · {o.item_count} {o.item_count === 1 ? 'unidad' : 'unidades'} ·{' '}
                    {o.delivery_method === 'PICKUP' ? 'Retiro' : 'Envío'}
                  </span>
                </span>
                <span className="font-semibold tabular-nums">{formatPrice(o.total, o.currency)}</span>
                <ChevronRightIcon className="size-4 text-muted-foreground group-hover:text-primary" />
              </Link>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
