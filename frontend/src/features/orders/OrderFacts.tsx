import { CreditCardIcon, StoreIcon, TruckIcon, UserIcon, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import type { Order } from '@/api/types'
import { PAYMENT_LABELS } from '@/lib/format'
import { cn } from '@/lib/utils'

/**
 * Delivery, payment and customer of an order, as three tiles. Shared by the confirmation dialog
 * and the order page, so what the user confirms looks exactly like what they get.
 */
export function OrderFacts({ order, className }: { order: Order; className?: string }) {
  const pickup = order.delivery_method === 'PICKUP'
  const address = order.shipping_address
  const branch = order.pickup_warehouse
  return (
    <div className={cn('grid gap-2 sm:grid-cols-3', className)}>
      <Fact icon={pickup ? StoreIcon : TruckIcon} title={pickup ? 'Retiro en sucursal' : 'Envío a domicilio'}>
        {pickup ? (
          <>
            <Main>{branch?.name ?? 'Sucursal'}</Main>
            <Sub>{[branch?.city, branch?.department].filter(Boolean).join(', ')}</Sub>
          </>
        ) : (
          <>
            <Main>{address?.street}</Main>
            <Sub>{[address?.city, address?.department].filter(Boolean).join(', ')}</Sub>
          </>
        )}
      </Fact>
      <Fact icon={CreditCardIcon} title="Pago">
        <Main>{PAYMENT_LABELS[order.payment_method] ?? order.payment_method}</Main>
      </Fact>
      <Fact icon={UserIcon} title="A nombre de">
        <Main>{order.customer_name}</Main>
        <Sub>{order.email}</Sub>
      </Fact>
    </div>
  )
}

function Fact({ icon: Icon, title, children }: { icon: LucideIcon; title: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5 rounded-xl border bg-card p-3">
      <span className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <span className="flex size-6 items-center justify-center rounded-md bg-accent text-primary">
          <Icon className="size-3.5" />
        </span>
        {title}
      </span>
      <span className="min-w-0 leading-tight">{children}</span>
    </div>
  )
}

const Main = ({ children }: { children: ReactNode }) => (
  <span className="block truncate text-sm font-semibold">{children}</span>
)
const Sub = ({ children }: { children: ReactNode }) => (
  <span className="block truncate text-xs text-muted-foreground">{children}</span>
)
