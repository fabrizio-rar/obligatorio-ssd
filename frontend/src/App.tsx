import { ChatPanel } from '@/features/chat/ChatPanel'

export default function App() {
  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center justify-between border-b px-6 py-3">
        <span className="text-lg font-bold">MercaNova</span>
        {/* Search, cart badge and user menu arrive with their endpoints. */}
      </header>
      <main className="flex min-h-0 flex-1">
        <section className="flex-1 overflow-auto p-6">
          <p className="text-muted-foreground">El catálogo se muestra acá (pendiente de GET /api/products).</p>
        </section>
        <aside className="w-full max-w-md border-l">
          <ChatPanel />
        </aside>
      </main>
    </div>
  )
}
