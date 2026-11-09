import { BotMessageSquareIcon } from 'lucide-react'
import { useState } from 'react'
import { Link, Navigate, Outlet, Route, Routes } from 'react-router-dom'

import { Logo } from '@/components/brand/Logo'
import { Button } from '@/components/ui/button'

import { AuthPage } from '@/features/auth/AuthPage'
import { UserMenu } from '@/features/auth/UserMenu'
import { CartSheet } from '@/features/cart/CartSheet'
import { CatalogPage } from '@/features/catalog/CatalogPage'
import { ProductDetailPage } from '@/features/catalog/ProductDetailPage'
import { ChatSidebar } from '@/features/chat/ChatPanel'
import { CheckoutPage } from '@/features/checkout/CheckoutPage'
import { ComparePage } from '@/features/compare/ComparePage'
import { OrderDetailPage } from '@/features/orders/OrderDetailPage'
import { OrdersPage } from '@/features/orders/OrdersPage'
import { useSession } from '@/lib/session'

export default function App() {
  return (
    <Routes>
      <Route element={<ShopLayout />}>
        <Route index element={<CatalogPage />} />
        <Route path="products/:productId" element={<ProductDetailPage />} />
        <Route path="compare" element={<ComparePage />} />
        <Route path="checkout" element={<CheckoutPage />} />
        <Route path="orders" element={<OrdersPage />} />
        <Route path="orders/:code" element={<OrderDetailPage />} />
      </Route>
      <Route path="login" element={<AuthPage mode="login" />} />
      <Route path="register" element={<AuthPage mode="register" />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

const CHAT_MINIMIZED_KEY = 'mercanova.chat-minimized'

function readMinimized(): boolean {
  try {
    return localStorage.getItem(CHAT_MINIMIZED_KEY) === 'true'
  } catch {
    return false
  }
}

/**
 * Header + page + persistent chat panel (docs/PLAN.md §13). The chat keeps its state across pages
 * and while minimized: it is only hidden, never unmounted. The choice is remembered per browser.
 */
function ShopLayout() {
  const session = useSession()
  const [minimized, setMinimizedState] = useState(readMinimized)
  const setMinimized = (value: boolean) => {
    setMinimizedState(value)
    try {
      localStorage.setItem(CHAT_MINIMIZED_KEY, String(value))
    } catch {
      // private mode / blocked storage: it just is not remembered
    }
  }

  return (
    <div className="flex h-screen flex-col">
      <header className="relative flex items-center justify-between gap-4 bg-linear-to-r from-indigo-950 via-indigo-900 to-violet-900 px-6 py-3 text-white shadow-md">
        <Link to="/" aria-label="MercaNova: inicio" className="rounded-lg focus-visible:ring-3 focus-visible:ring-white/40 focus-visible:outline-none">
          <Logo tone="light" />
        </Link>
        {/* Brand gradient line under the header */}
        <div className="absolute inset-x-0 bottom-0 h-0.5 bg-linear-to-r from-indigo-400 via-violet-400 to-fuchsia-400" />
        <div className="flex items-center gap-3">
          {session && <CartSheet />}
          <UserMenu />
        </div>
      </header>
      <main className="flex min-h-0 flex-1">
        <section className="min-w-0 flex-1 overflow-auto p-6">
          <Outlet />
        </section>
        <aside className={minimized ? 'shrink-0 border-l bg-card' : 'w-full max-w-md shrink-0 border-l bg-card'}>
          {minimized && (
            <div className="flex h-full flex-col items-center px-2 py-3">
              <Button
                variant="ghost"
                className="h-auto flex-col gap-2 px-2 py-3"
                onClick={() => setMinimized(false)}
                aria-label="Abrir el asistente"
                title="Abrir el asistente"
              >
                <BotMessageSquareIcon className="size-5 text-primary" />
                <span className="text-xs font-medium [writing-mode:vertical-rl]">Asistente</span>
              </Button>
            </div>
          )}
          <div className={minimized ? 'hidden' : 'h-full'}>
            <ChatSidebar minimized={minimized} onMinimize={() => setMinimized(true)} />
          </div>
        </aside>
      </main>
    </div>
  )
}
