import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { getProductCards } from '@/api/endpoints'
import { MIN_COMPARE, type AgentResponse, type PendingAction } from '@/api/types'
import { Button, buttonVariants } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useCart, useClearCart, useRemoveFromCart } from '@/features/cart/useCart'
import { ProductRow, ProductThumb } from '@/features/catalog/ProductCard'
import { ProductImage } from '@/features/catalog/ProductImage'
import { ComparisonTable } from '@/features/compare/ComparisonTable'
import { compareUrl, useComparison } from '@/features/compare/useComparison'

import type { ChatMessage, ConfirmationState } from './messages'

interface Props {
  message: ChatMessage
  busy: boolean
  /** Text to send again: set for the last answer when it is an error (transport or type "error"). */
  retryText: string | null
  onRetry: (text: string) => void
  onConfirmation: (state: ConfirmationState) => void
}

export function ChatMessageView({ message, busy, retryText, onRetry, onConfirmation }: Props) {
  if (message.role === 'user') {
    return (
      <div className="ml-8 self-end rounded-2xl rounded-br-sm bg-linear-to-br from-indigo-600 to-violet-600 px-3 py-2 text-sm whitespace-pre-wrap text-white shadow-sm">
        {message.text}
      </div>
    )
  }

  const retry = retryText !== null && (
    <Button variant="outline" size="sm" className="w-fit" disabled={busy} onClick={() => onRetry(retryText)}>
      Reintentar
    </Button>
  )

  if (message.role === 'error') {
    return (
      <div className="mr-8 flex flex-col gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm">
        <p>{message.text}</p>
        {retry}
      </div>
    )
  }

  // The tools the agent used are not shown: they are internal (tool_call_logs, scripts.chat --verbose)
  const { response, confirmation } = message
  const question = response.clarifying_question
  return (
    <div className="mr-8 flex flex-col gap-2 rounded-2xl rounded-bl-sm bg-secondary px-3 py-2 text-sm">
      <AssistantText text={response.message} />
      {question && !response.message.includes(question) && <p className="font-medium">{question}</p>}
      <ResponseProducts response={response} />
      {response.pending_confirmation && confirmation && (
        <ConfirmationCard pending={response.pending_confirmation} state={confirmation} onResolve={onConfirmation} />
      )}
      {response.type === 'error' && retry}
    </div>
  )
}

/**
 * The model writes light Markdown: **bold** and "- " list items. Render just that, as React nodes
 * (no HTML is injected), and keep the line breaks.
 */
function AssistantText({ text }: { text: string }) {
  const withBullets = text.replace(/^(\s*)[-*] /gm, '$1• ')
  const parts = withBullets.split(/(\*\*[^*\n]+\*\*)/g)
  return (
    <p className="whitespace-pre-wrap">
      {parts.map((part, i) =>
        part.length > 4 && part.startsWith('**') && part.endsWith('**') ? (
          <strong key={i}>{part.slice(2, -2)}</strong>
        ) : (
          part
        ),
      )}
    </p>
  )
}

/**
 * Images in the chat live only inside product cards, never in the text: the model never writes or
 * picks image URLs. Cards are fetched by ID from the API (AGENTS.md rule 11), so photo, price and
 * stock are today's, also when an old conversation is reopened.
 * - error: no products.
 * - comparison: the table, with one photo per column.
 * - cart_update: small thumbnails of what was added or changed.
 * - recommendation / info / clarification: a card per product_id, in the agent's order.
 * The product of a pending confirmation is shown in the confirmation card, not twice.
 */
function ResponseProducts({ response }: { response: AgentResponse }) {
  if (response.type === 'error') return null
  const compared = response.comparison_ids.length >= MIN_COMPARE ? response.comparison_ids : []
  const pendingId = response.pending_confirmation?.product_id ?? null
  const cardIds = response.product_ids.filter((id) => !compared.includes(id) && id !== pendingId)
  return (
    <>
      {compared.length > 0 && <ChatComparison ids={compared} />}
      {cardIds.length > 0 && <ChatProductCards ids={cardIds} small={response.type === 'cart_update'} />}
    </>
  )
}

/** Compact comparison (only the rows that differ) + link to the full table on /compare. */
function ChatComparison({ ids }: { ids: string[] }) {
  const comparison = useComparison(ids)

  if (comparison.isPending) return <Skeleton className="h-40" />
  if (comparison.isError) {
    return <p className="text-xs text-destructive">No se pudo armar la comparación: {comparison.error.message}</p>
  }
  return (
    <div className="flex flex-col gap-1.5">
      <ComparisonTable comparison={comparison.data} onlyDifferences compact />
      <Link to={compareUrl(ids)} className={buttonVariants({ variant: 'outline', size: 'sm', className: 'w-fit' })}>
        Ver comparación completa
      </Link>
    </div>
  )
}

/** Cards from GET /api/products?ids= (same order; inactive and unknown IDs are omitted by the API). */
function ChatProductCards({ ids, small }: { ids: string[]; small: boolean }) {
  const cards = useQuery({ queryKey: ['product-cards', ids.join(',')], queryFn: () => getProductCards(ids) })

  if (cards.isPending) {
    return (
      <div className="flex flex-col gap-2">
        {ids.slice(0, 3).map((id) => (
          <Skeleton key={id} className={small ? 'h-12' : 'h-20'} />
        ))}
      </div>
    )
  }
  if (cards.isError) {
    return (
      <p className="text-xs text-destructive">
        No se pudieron cargar los productos.{' '}
        <button type="button" className="underline" onClick={() => cards.refetch()}>
          Reintentar
        </button>
      </p>
    )
  }
  if (small) {
    return (
      <div className="flex flex-wrap gap-2">
        {cards.data.items.map((product) => (
          <ProductThumb key={product.product_id} product={product} />
        ))}
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-2">
      {cards.data.items.map((product) => (
        <ProductRow key={product.product_id} product={product} />
      ))}
    </div>
  )
}

const MAX_THUMBS = 4

/**
 * Level-3 confirmation (remove an item / clear the cart). The summary is built by the backend with
 * DB data (action, product, quantity, price, new total); the thumbnails come from the cart (DB) and
 * the button calls the REST API directly: the agent never runs these actions.
 */
function ConfirmationCard({
  pending,
  state,
  onResolve,
}: {
  pending: PendingAction
  state: ConfirmationState
  onResolve: (state: ConfirmationState) => void
}) {
  const cart = useCart()
  const remove = useRemoveFromCart()
  const clear = useClearCart()
  const running = remove.isPending || clear.isPending
  const isClear = pending.action === 'clear_cart'
  const items = (cart.data?.items ?? []).filter((i) => isClear || i.product_id === pending.product_id)

  function confirm() {
    const done = { onSuccess: () => onResolve('done') }
    if (isClear) clear.mutate(undefined, done)
    else if (pending.product_id) remove.mutate(pending.product_id, done)
  }

  return (
    <div className="flex flex-col gap-2 rounded-lg border bg-background p-3">
      <div className="flex items-start gap-3">
        {items.length > 0 && (
          <div className="flex shrink-0 items-center gap-1">
            {items.slice(0, MAX_THUMBS).map((item) => (
              <ProductImage
                key={item.product_id}
                src={item.active ? item.image_url : null}
                alt={item.name}
                category={item.category}
                className="size-12 rounded-md border"
              />
            ))}
            {items.length > MAX_THUMBS && (
              <span className="text-xs text-muted-foreground">+{items.length - MAX_THUMBS}</span>
            )}
          </div>
        )}
        <p className="font-medium">{pending.summary}</p>
      </div>
      {state === 'pending' && (
        <div className="flex gap-2">
          <Button size="sm" variant="outline" disabled={running} onClick={() => onResolve('cancelled')}>
            Cancelar
          </Button>
          <Button size="sm" variant="destructive" disabled={running} onClick={confirm}>
            {running ? 'Un momento…' : isClear ? 'Vaciar carrito' : 'Quitar'}
          </Button>
        </div>
      )}
      {state === 'done' && <p className="text-xs text-muted-foreground">Hecho: el carrito ya está actualizado.</p>}
      {state === 'cancelled' && <p className="text-xs text-muted-foreground">Cancelado: no se cambió nada.</p>}
      {state === 'stale' && (
        <p className="text-xs text-muted-foreground">De una conversación anterior: si querés, hacelo desde el carrito.</p>
      )}
    </div>
  )
}
