import { ShoppingCartIcon } from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { useSession } from '@/lib/session'

import { useAddToCart } from './useCart'

interface Props {
  productId: string
  name: string
  available: number
  size?: 'xs' | 'sm' | 'default' | 'lg'
  className?: string
}

/** Same domain function as the agent's add_to_cart tool, through POST /api/cart/items. */
export function AddToCartButton({ productId, name, available, size = 'sm', className }: Props) {
  const session = useSession()
  const navigate = useNavigate()
  const location = useLocation()
  const add = useAddToCart()

  if (available <= 0) {
    return (
      <Button size={size} variant="outline" className={className} disabled>
        Sin stock
      </Button>
    )
  }

  function onClick() {
    if (!session) {
      toast.info('Iniciá sesión para usar el carrito')
      navigate('/login', { state: { from: location.pathname + location.search } })
      return
    }
    add.mutate({ productId }, { onSuccess: () => toast.success(`Agregado al carrito: ${name}`) })
  }

  return (
    <Button size={size} className={className} onClick={onClick} disabled={add.isPending}>
      <ShoppingCartIcon data-icon="inline-start" />
      {add.isPending ? 'Agregando…' : 'Agregar'}
    </Button>
  )
}
