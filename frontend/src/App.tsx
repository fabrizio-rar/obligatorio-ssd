import { Link, Navigate, Outlet, Route, Routes } from 'react-router-dom'

import { AuthPage } from '@/features/auth/AuthPage'
import { UserMenu } from '@/features/auth/UserMenu'
import { CartSheet } from '@/features/cart/CartSheet'
import { CatalogPage } from '@/features/catalog/CatalogPage'
import { ProductDetailPage } from '@/features/catalog/ProductDetailPage'
import { ChatSidebar } from '@/features/chat/ChatPanel'
import { ComparePage } from '@/features/compare/ComparePage'
import { useSession } from '@/lib/session'

export default function App() {
  return (
    <Routes>
      <Route element={<ShopLayout />}>
        <Route index element={<CatalogPage />} />
        <Route path="products/:productId" element={<ProductDetailPage />} />
        <Route path="compare" element={<ComparePage />} />
      </Route>
      <Route path="login" element={<AuthPage mode="login" />} />
      <Route path="register" element={<AuthPage mode="register" />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

/** Header + page + persistent chat panel (docs/PLAN.md §13). The chat keeps its state across pages. */
function ShopLayout() {
  const session = useSession()
  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center justify-between gap-4 border-b px-6 py-3">
        <Link to="/" className="text-lg font-bold">
          MercaNova
        </Link>
        <div className="flex items-center gap-3">
          {session && <CartSheet />}
          <UserMenu />
        </div>
      </header>
      <main className="flex min-h-0 flex-1">
        <section className="min-w-0 flex-1 overflow-auto p-6">
          <Outlet />
        </section>
        <aside className="w-full max-w-md shrink-0 border-l">
          <ChatSidebar />
        </aside>
      </main>
    </div>
  )
}
