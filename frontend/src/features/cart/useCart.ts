/**
 * The cart lives only in the TanStack Query cache (AGENTS.md: no duplicated cart state).
 * Every mutation returns the updated cart, so it is written straight into the cache.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { addToCart, clearCart, getCart, removeFromCart, setCartQuantity } from '@/api/endpoints'
import type { Cart } from '@/api/types'
import { useSession } from '@/lib/session'

/** Prefix of every cart query: invalidate it when the agent changes the cart (ui_actions). */
export const CART_KEY = ['cart'] as const

function useCartKey() {
  const session = useSession()
  return [...CART_KEY, session?.username ?? null] as const
}

export function useCart() {
  const session = useSession()
  const key = useCartKey()
  return useQuery({ queryKey: key, queryFn: getCart, enabled: session !== null })
}

/** Shared handlers: store the returned cart, or show the backend message and refetch the cart. */
function useCartCache() {
  const queryClient = useQueryClient()
  const key = useCartKey()
  return {
    store: (cart: Cart) => queryClient.setQueryData(key, cart),
    fail: (error: Error) => {
      toast.error(error.message)
      // An OUT_OF_STOCK or INACTIVE error means the cart we show may be stale
      void queryClient.invalidateQueries({ queryKey: CART_KEY })
    },
  }
}

export function useAddToCart() {
  const { store, fail } = useCartCache()
  return useMutation({
    mutationFn: ({ productId, quantity = 1 }: { productId: string; quantity?: number }) =>
      addToCart(productId, quantity),
    onSuccess: store,
    onError: fail,
  })
}

export function useSetCartQuantity() {
  const { store, fail } = useCartCache()
  return useMutation({
    mutationFn: ({ productId, quantity }: { productId: string; quantity: number }) =>
      setCartQuantity(productId, quantity),
    onSuccess: store,
    onError: fail,
  })
}

export function useRemoveFromCart() {
  const { store, fail } = useCartCache()
  return useMutation({ mutationFn: removeFromCart, onSuccess: store, onError: fail })
}

export function useClearCart() {
  const { store, fail } = useCartCache()
  return useMutation({ mutationFn: clearCart, onSuccess: store, onError: fail })
}
