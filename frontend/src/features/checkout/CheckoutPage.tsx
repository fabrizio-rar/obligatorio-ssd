import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangleIcon, LockIcon, PackageIcon, StoreIcon, TruckIcon, type LucideIcon } from 'lucide-react'
import { useState, type FormEvent, type ReactNode } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { ApiError } from '@/api/client'
import { createCheckout, getCheckoutOptions } from '@/api/endpoints'
import type { CheckoutOptions, CheckoutRequest, DeliveryMethod, Order, PaymentMethod } from '@/api/types'
import { Button, buttonVariants } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { CART_KEY, useCart } from '@/features/cart/useCart'
import { ProductImage } from '@/features/catalog/ProductImage'
import { formatPrice, PAYMENT_LABELS, URUGUAY_DEPARTMENTS } from '@/lib/format'
import { useSession } from '@/lib/session'
import { cn } from '@/lib/utils'

import { ConfirmOrderDialog } from './ConfirmOrderDialog'

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

interface Form {
  customer_name: string
  email: string
  delivery_method: DeliveryMethod
  street: string
  city: string
  department: string
  pickup_warehouse_id: string
  payment_method: PaymentMethod
}

type Errors = Partial<Record<keyof Form, string>>

const EMPTY: Form = {
  customer_name: '',
  email: '',
  delivery_method: 'SHIPPING',
  street: '',
  city: '',
  department: '',
  pickup_warehouse_id: '',
  payment_method: 'CARD',
}

/** Same rules as CheckoutRequest in the backend (which validates again). */
function validate(form: Form): Errors {
  const errors: Errors = {}
  if (form.customer_name.trim().length < 2) errors.customer_name = 'Ingresá tu nombre'
  if (!EMAIL_RE.test(form.email.trim())) errors.email = 'Ingresá un email válido'
  if (form.delivery_method === 'SHIPPING') {
    if (form.street.trim().length < 3) errors.street = 'Ingresá la calle y el número'
    if (form.city.trim().length < 2) errors.city = 'Ingresá la ciudad o localidad'
    if (!form.department) errors.department = 'Elegí el departamento'
  } else if (!form.pickup_warehouse_id) {
    errors.pickup_warehouse_id = 'Elegí una sucursal'
  }
  return errors
}

function toRequest(form: Form): CheckoutRequest {
  const shipping = form.delivery_method === 'SHIPPING'
  return {
    customer_name: form.customer_name.trim(),
    email: form.email.trim(),
    delivery_method: form.delivery_method,
    shipping_address: shipping
      ? { street: form.street.trim(), city: form.city.trim(), department: form.department }
      : null,
    pickup_warehouse_id: shipping ? null : form.pickup_warehouse_id,
    payment_method: form.payment_method,
  }
}

/** Backend 422 fields ("shipping_address.street") → our form fields. */
function fieldErrors(error: ApiError): Errors {
  const fields = (error.details.fields ?? []) as { field: string; message: string }[]
  const errors: Errors = {}
  for (const { field, message } of fields) {
    const key = field.replace('shipping_address.', '') as keyof Form
    if (key in EMPTY) errors[key] = message
  }
  return errors
}

/**
 * Checkout (RF-11, docs/PLAN.md §13): customer data, delivery (home or a branch that has the
 * whole cart), simulated payment. "Revisar compra" creates the PENDING order (quoted prices) and
 * opens the confirmation dialog; only its button buys (POST /orders/{id}/confirm).
 */
export function CheckoutPage() {
  const session = useSession()
  const location = useLocation()

  if (!session) {
    return (
      <div className="mx-auto flex max-w-md flex-col items-center gap-3 rounded-2xl border bg-card p-8 text-center">
        <LockIcon className="size-8 text-primary" />
        <h1 className="text-lg font-semibold">Iniciá sesión para comprar</h1>
        <Link to="/login" state={{ from: location.pathname }} className={buttonVariants()}>
          Iniciar sesión
        </Link>
      </div>
    )
  }
  // A new navigation (e.g. the chat's "Ir al checkout" with another prefill) starts a fresh form
  return <Checkout key={location.key} prefill={readPrefill(location.state)} />
}

/** From the chat's checkout card (start_checkout): delivery method and branch, both editable. */
function readPrefill(state: unknown): Partial<Form> {
  const prefill = (state as { prefill?: { delivery_method?: DeliveryMethod | null; pickup_warehouse_id?: string | null } } | null)
    ?.prefill
  if (!prefill) return {}
  return {
    ...(prefill.delivery_method ? { delivery_method: prefill.delivery_method } : {}),
    ...(prefill.pickup_warehouse_id ? { delivery_method: 'PICKUP' as const, pickup_warehouse_id: prefill.pickup_warehouse_id } : {}),
  }
}

function Checkout({ prefill }: { prefill: Partial<Form> }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const cart = useCart()
  // The options (subtotal, shipping cost, branches that cover the cart) depend on the cart: the
  // key carries its contents, so any change (the drawer, the chat's refresh_cart) refetches them
  const cartSignature = cart.data?.items.map((i) => `${i.product_id}:${i.quantity}`).join(',') ?? null
  const options = useQuery({
    queryKey: ['checkout-options', cartSignature],
    queryFn: getCheckoutOptions,
    enabled: cartSignature !== null,
    placeholderData: keepPreviousData, // no skeleton flash while it refetches
    retry: false,
  })
  const [form, setForm] = useState<Form>({ ...EMPTY, ...prefill })
  const [errors, setErrors] = useState<Errors>({})
  const [order, setOrder] = useState<Order | null>(null)
  const [problem, setProblem] = useState<string | null>(null)

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: CART_KEY })
    void queryClient.invalidateQueries({ queryKey: ['checkout-options'] })
  }

  const review = useMutation({
    mutationFn: createCheckout,
    onSuccess: (created) => {
      setProblem(null)
      setOrder(created)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === 'INVALID_INPUT') {
        setErrors(fieldErrors(error))
        return
      }
      setProblem(error.message)
      refresh()
    },
  })

  function set<K extends keyof Form>(key: K, value: Form[K]) {
    setForm((prev) => {
      const next = { ...prev, [key]: value }
      // Cash is only for pickup
      if (key === 'delivery_method' && value === 'SHIPPING' && next.payment_method === 'CASH_ON_PICKUP') {
        next.payment_method = 'CARD'
      }
      return next
    })
    setErrors((prev) => ({ ...prev, [key]: undefined }))
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    const found = validate(form)
    setErrors(found)
    if (Object.keys(found).length === 0) review.mutate(toRequest(form))
  }

  if (options.isPending || cart.isPending) {
    return (
      <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <Skeleton className="h-[32rem] rounded-2xl" />
        <Skeleton className="h-80 rounded-2xl" />
      </div>
    )
  }

  if (options.isError) {
    const code = options.error instanceof ApiError ? options.error.code : null
    return (
      <div className="mx-auto flex max-w-md flex-col items-center gap-3 rounded-2xl border bg-card p-8 text-center">
        <PackageIcon className="size-8 text-primary" />
        <h1 className="text-lg font-semibold">
          {code === 'EMPTY_CART' ? 'Tu carrito está vacío' : 'No podés comprar todavía'}
        </h1>
        <p className="text-sm text-muted-foreground">
          {code === 'EMPTY_CART'
            ? 'Agregá productos desde el catálogo o pedíselos al asistente.'
            : options.error.message}
        </p>
        <Link to="/" className={buttonVariants({ variant: 'outline' })}>
          Ir al catálogo
        </Link>
      </div>
    )
  }

  const opts = options.data
  const shippingCost = form.delivery_method === 'SHIPPING' ? Number(opts.shipping.cost) : 0
  const total = Number(opts.subtotal) + shippingCost

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold tracking-tight">Finalizar compra</h1>

      {problem && (
        <div role="alert" className="flex items-start gap-2 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm">
          <AlertTriangleIcon className="mt-0.5 size-4 shrink-0 text-destructive" />
          <p>{problem}</p>
        </div>
      )}

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="flex flex-col gap-6">
          <Step number={1} title="Tus datos">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field id="customer_name" label="Nombre y apellido" error={errors.customer_name}>
                <Input
                  id="customer_name"
                  autoComplete="name"
                  value={form.customer_name}
                  onChange={(e) => set('customer_name', e.target.value)}
                  aria-invalid={!!errors.customer_name}
                />
              </Field>
              <Field id="email" label="Email" error={errors.email}>
                <Input
                  id="email"
                  type="email"
                  autoComplete="email"
                  value={form.email}
                  onChange={(e) => set('email', e.target.value)}
                  aria-invalid={!!errors.email}
                />
              </Field>
            </div>
          </Step>

          <Step number={2} title="Entrega">
            <div className="grid gap-3 sm:grid-cols-2" role="radiogroup" aria-label="Método de entrega">
              <ChoiceCard
                icon={TruckIcon}
                title="Envío a domicilio"
                detail={
                  Number(opts.shipping.cost) === 0
                    ? 'Gratis'
                    : `${formatPrice(opts.shipping.cost)} · gratis desde ${formatPrice(opts.shipping.free_from)}`
                }
                selected={form.delivery_method === 'SHIPPING'}
                onSelect={() => set('delivery_method', 'SHIPPING')}
              />
              <ChoiceCard
                icon={StoreIcon}
                title="Retiro en sucursal"
                detail={pickupDetail(opts.pickup.filter((p) => p.can_fulfill).length)}
                selected={form.delivery_method === 'PICKUP'}
                onSelect={() => set('delivery_method', 'PICKUP')}
              />
            </div>

            {form.delivery_method === 'SHIPPING' ? (
              <div className="grid gap-4 sm:grid-cols-2">
                <Field id="street" label="Calle y número" error={errors.street} className="sm:col-span-2">
                  <Input
                    id="street"
                    autoComplete="street-address"
                    value={form.street}
                    onChange={(e) => set('street', e.target.value)}
                    aria-invalid={!!errors.street}
                  />
                </Field>
                <Field id="city" label="Ciudad o localidad" error={errors.city}>
                  <Input
                    id="city"
                    autoComplete="address-level2"
                    value={form.city}
                    onChange={(e) => set('city', e.target.value)}
                    aria-invalid={!!errors.city}
                  />
                </Field>
                <Field id="department" label="Departamento" error={errors.department}>
                  <select
                    id="department"
                    value={form.department}
                    onChange={(e) => set('department', e.target.value)}
                    aria-invalid={!!errors.department}
                    className="h-8 w-full rounded-lg border border-input bg-background px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 aria-invalid:border-destructive"
                  >
                    <option value="">Elegí…</option>
                    {URUGUAY_DEPARTMENTS.map((d) => (
                      <option key={d} value={d}>
                        {d}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
            ) : (
              <PickupList
                options={opts}
                value={form.pickup_warehouse_id}
                error={errors.pickup_warehouse_id}
                onChange={(id) => set('pickup_warehouse_id', id)}
              />
            )}
          </Step>

          <Step number={3} title="Pago">
            <p className="-mt-2 text-sm text-muted-foreground">
              Es una compra ficticia: no se cobra nada ni se piden datos de tarjeta.
            </p>
            <div className="grid gap-3 sm:grid-cols-3" role="radiogroup" aria-label="Método de pago">
              {opts.payment_methods.map((method) => {
                const cashWithShipping = method === 'CASH_ON_PICKUP' && form.delivery_method === 'SHIPPING'
                return (
                  <ChoiceCard
                    key={method}
                    title={PAYMENT_LABELS[method] ?? method}
                    detail={cashWithShipping ? 'Solo con retiro en sucursal' : undefined}
                    selected={form.payment_method === method}
                    disabled={cashWithShipping}
                    onSelect={() => set('payment_method', method)}
                  />
                )
              })}
            </div>
          </Step>
        </div>

        <aside className="flex flex-col gap-4 rounded-2xl border bg-card p-5 shadow-xs lg:sticky lg:top-0">
          <h2 className="font-semibold">Tu pedido</h2>
          <ul className="flex flex-col gap-3">
            {cart.data?.items.map((item) => (
              <li key={item.product_id} className="flex items-center gap-3 text-sm">
                <ProductImage
                  src={item.image_url}
                  alt={item.name}
                  category={item.category}
                  className="size-12 shrink-0 rounded-lg"
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{item.name}</span>
                  <span className="text-xs text-muted-foreground">
                    {item.quantity} × {formatPrice(item.unit_price, item.currency)}
                  </span>
                </span>
                <span className="font-medium tabular-nums">{formatPrice(item.line_total, item.currency)}</span>
              </li>
            ))}
          </ul>
          <dl className="flex flex-col gap-1.5 border-t pt-4 text-sm">
            <Row label="Subtotal" value={formatPrice(opts.subtotal, opts.currency)} />
            <Row label="Envío" value={shippingCost === 0 ? 'Gratis' : formatPrice(shippingCost, opts.currency)} />
            <div className="mt-1 flex items-baseline justify-between border-t pt-3">
              <dt className="font-semibold">Total</dt>
              <dd className="text-xl font-semibold tracking-tight tabular-nums">{formatPrice(total, opts.currency)}</dd>
            </div>
            <p className="text-right text-xs text-muted-foreground">IVA incluido</p>
          </dl>
          <Button type="submit" size="lg" className="h-11 w-full text-base" disabled={review.isPending}>
            {review.isPending ? 'Preparando el resumen…' : 'Revisar compra'}
          </Button>
          <p className="text-center text-xs text-muted-foreground">
            En el próximo paso revisás todo y confirmás. Hasta entonces no se compra nada.
          </p>
        </aside>
      </div>

      {order && (
        <ConfirmOrderDialog
          order={order}
          onOrderChange={setOrder}
          onClose={(reason) => {
            setOrder(null)
            if (reason) {
              setProblem(reason)
              refresh()
            }
          }}
          onConfirmed={(confirmed) => {
            void queryClient.invalidateQueries({ queryKey: CART_KEY })
            void queryClient.invalidateQueries({ queryKey: ['products'] })
            void queryClient.invalidateQueries({ queryKey: ['product'] })
            void queryClient.invalidateQueries({ queryKey: ['orders'] })
            queryClient.removeQueries({ queryKey: ['checkout-options'] })
            navigate(`/orders/${confirmed.code}`, { state: { justConfirmed: true } })
          }}
        />
      )}
    </form>
  )
}

function pickupDetail(branches: number): string {
  if (branches === 0) return 'Ninguna sucursal tiene todo tu carrito'
  return `Gratis · ${branches === 1 ? '1 sucursal tiene' : `${branches} sucursales tienen`} todo tu carrito`
}

function Step({ number, title, children }: { number: number; title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-4 rounded-2xl border bg-card p-5 shadow-xs">
      <h2 className="flex items-center gap-2.5 font-semibold">
        <span className="flex size-6 items-center justify-center rounded-full bg-primary text-xs text-primary-foreground">
          {number}
        </span>
        {title}
      </h2>
      {children}
    </section>
  )
}

function Field({
  id,
  label,
  error,
  className,
  children,
}: {
  id: string
  label: string
  error?: string
  className?: string
  children: ReactNode
}) {
  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <Label htmlFor={id}>{label}</Label>
      {children}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  )
}

function ChoiceCard({
  icon: Icon,
  title,
  detail,
  selected,
  disabled = false,
  onSelect,
}: {
  icon?: LucideIcon
  title: string
  detail?: string
  selected: boolean
  disabled?: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      disabled={disabled}
      onClick={onSelect}
      className={cn(
        'flex min-h-16 items-center gap-3 rounded-xl border p-3 text-left transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50',
        selected ? 'border-primary bg-accent ring-1 ring-primary' : 'hover:border-primary/40 hover:bg-accent/40',
      )}
    >
      {Icon && (
        <span
          className={cn(
            'flex size-9 shrink-0 items-center justify-center rounded-lg',
            selected ? 'bg-primary text-primary-foreground' : 'bg-secondary text-primary',
          )}
        >
          <Icon className="size-4.5" />
        </span>
      )}
      <span className="leading-tight">
        <span className="block text-sm font-medium">{title}</span>
        {detail && <span className="text-xs text-muted-foreground">{detail}</span>}
      </span>
    </button>
  )
}

/** Branches with pickup; the ones that cannot cover the cart are disabled with what is missing. */
function PickupList({
  options,
  value,
  error,
  onChange,
}: {
  options: CheckoutOptions
  value: string
  error?: string
  onChange: (warehouseId: string) => void
}) {
  return (
    <div className="flex flex-col gap-2" role="radiogroup" aria-label="Sucursal de retiro">
      {options.pickup.map((branch) => (
        <button
          key={branch.warehouse_id}
          type="button"
          role="radio"
          aria-checked={value === branch.warehouse_id}
          disabled={!branch.can_fulfill}
          onClick={() => onChange(branch.warehouse_id)}
          className={cn(
            'flex items-center gap-3 rounded-xl border p-3 text-left text-sm transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:bg-muted/50',
            value === branch.warehouse_id
              ? 'border-primary bg-accent ring-1 ring-primary'
              : 'enabled:hover:border-primary/40 enabled:hover:bg-accent/40',
          )}
        >
          <StoreIcon className={cn('size-4.5 shrink-0', branch.can_fulfill ? 'text-primary' : 'text-muted-foreground')} />
          <span className="min-w-0 flex-1 leading-tight">
            <span className={cn('block font-medium', !branch.can_fulfill && 'text-muted-foreground')}>{branch.name}</span>
            <span className="text-xs text-muted-foreground">
              {[branch.city, branch.department].filter(Boolean).join(', ')}
            </span>
            {!branch.can_fulfill && (
              <span className="mt-1 block text-xs text-amber-700">
                Falta:{' '}
                {branch.missing.map((m) => `${m.name} (hay ${m.available} de ${m.requested})`).join(', ')}
              </span>
            )}
          </span>
          {branch.can_fulfill && (
            <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">
              Tiene todo
            </span>
          )}
        </button>
      ))}
      {options.pickup.every((b) => !b.can_fulfill) && (
        <p className="text-sm text-amber-700">
          Ninguna sucursal tiene todo tu carrito: elegí envío a domicilio (se arma entre varias sucursales).
        </p>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="tabular-nums">{value}</dd>
    </div>
  )
}
