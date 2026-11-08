# MercaNova — Frontend

React 19 + Vite + TypeScript (strict) + Tailwind 4 + shadcn/ui + TanStack Query.
Design source of truth: [`docs/PLAN.md`](../docs/PLAN.md) §12 (API) and §13 (frontend).

## Run it

```bash
# whole stack (db + backend + frontend)
docker compose up -d --build        # http://localhost:5173

# frontend only, outside Docker (backend must be up on :8000)
cd frontend && npm install && npm run dev
```

Checks: `npx tsc -b && npx oxlint && npx vite build`.

The browser only calls relative `/api/...`. Vite proxies it to `VITE_API_URL`
(`http://localhost:8000` by default, `http://backend:8000` inside compose), so the backend needs no CORS.

## Layout

```
src/
  api/          client.ts (fetch + Bearer token + ApiError; a 401 logs out), types.ts (mirror of the backend contract), endpoints.ts
  components/ui shadcn components (generated; do not hand-edit)
  features/
    auth/       AuthPage (login / register), UserMenu (header; validates the stored token with /auth/me)
    catalog/    CatalogPage (grid + category + pages), ProductDetailPage (tabs: description, specs, stock per warehouse; related), ProductCard / ProductRow / ProductThumb, ProductImage (photo + local fallback), ProductMeta (Price, StockBadge, Rating)
    cart/       useCart (TanStack Query hooks: the cache is the only cart state), CartSheet (drawer), AddToCartButton
    chat/       ChatPanel (+ ChatSidebar login gate), ChatMessageView (cards, comparison, level-3 confirmation, tools used), ConversationHistory, messages.ts
    voice/      useVoiceRecorder (MediaRecorder + AnalyserNode, 30 s cut), useVoiceInput (hold / tap, transcription), VoiceWaveform (live level line), VoiceControls (MicButton, RecordingBar, VoiceHint)
    compare/    ComparisonTable (shared by the chat and the page), ComparePage (/compare?ids=), useComparison
  lib/          session.ts (token in localStorage, useSession), format.ts (prices + i18n dictionary), utils (cn)
  App.tsx       routes: / (catalog), /products/:id, /compare, /login, /register; shop layout = header + page + persistent chat panel
  main.tsx      QueryClientProvider + BrowserRouter + Toaster
```

Types in `api/types.ts` mirror Pydantic models in the backend. When a backend schema changes, update them in the same change.

## Status (updated 2026-11-08)

### Done
- [x] Scaffold: Vite, TS strict, Tailwind 4, shadcn/ui, TanStack Query, sonner, react-router, `@/` alias.
- [x] Docker: `frontend` service in `docker-compose.yml` (Vite dev server on `:5173`, hot reload over `src/`).
- [x] **Login / register (N3)**: token from `POST /api/auth/login` kept in localStorage and sent as `Authorization: Bearer`; a 401 with a session drops it and the UI asks to log in again. Register logs in right after. Client-side checks mirror the backend rules (username 3–30 `[a-z0-9._-]`, password ≥ 6). Catalog is public; chat and cart need a login.
- [x] **Catalog + detail (N4, RF-01)**: grid with category chips and pagination (state in the URL: `?category=&page=`), discounted price struck through, "Sin stock" / "Quedan N" badges. Detail with description, specs grouped, stock per warehouse, alternatives / accessories / often bought with; discontinued products show only alternatives.
- [x] **Cart (N5, RF-09/10)**: drawer with +/− (capped at 10 and at the available stock), remove, clear with a confirmation that lists products, quantities and total; per-item issues (`INACTIVE`, `OUT_OF_STOCK`, `INSUFFICIENT_STOCK`); backend errors as toasts. The cart only lives in the TanStack cache.
- [x] **Chat (N11)**: product cards rendered from `GET /api/products?ids=` (AGENTS.md rule 11), **comparison table** (`comparison_ids` → `GET /api/products/compare`: compact in the chat with only the rows that differ, full on `/compare?ids=` with "Solo diferencias" and add-to-cart cards), clarifying question, suggested-reply chips, retry on transient errors, `ui_actions: refresh_cart` refreshes the cart badge, **level-3 confirmation card** (`pending_confirmation`: the button calls `DELETE /api/cart/items/{id}` or `DELETE /api/cart`, never the agent), "ver tools usadas", **conversation history** (`/api/conversations*`) and "Nueva".
- [x] **Images**: only inside product cards, never in the chat text (the model never writes image URLs). By answer type: `recommendation` / `info` / `clarification` → a card per `product_ids` (in order); `cart_update` → small thumbnails; level-3 confirmation → thumbnails of the cart items involved; `comparison` → a photo per column (`products[i].image_url`); `error` → no products, only "Reintentar". The dataset has **no real photos**: every `image_url` is a `placehold.co` placeholder (a grey box with the SKU, unreadable as a thumbnail). `ProductImage` treats those as "no photo" and draws a local illustration per category (colored background + icon), which is also the fallback when there is no URL or it fails to load (offline, `docs/PLAN.md` §2.1). A real URL, if the dataset ever has one, is shown as is. Inactive products never show their photo (the cart drawer uses the illustration).
- [x] **Voice 🎤 (N12, RF-08)**: hold the button to talk and release to finish (`docs/PLAN.md` §11), or tap to start and tap again (the first time the browser asks for the mic permission). `MediaRecorder` (webm/opus; mp4 on Safari), cut at 30 s, Esc cancels. While recording, the input becomes a bar with a **live level line** (scrolling history of the last seconds from an `AnalyserNode`): flat when no audio arrives, bars when it does; after 1.5 s of silence it warns "No llega audio". `POST /api/transcribe` (multipart) puts the text in the input, editable, never sent by itself. A recording where the meter heard nothing is **not sent** (the model invents text from silence). Clear messages for denied permission, no microphone and mic in use. Disabled when `stt_enabled` is false. Code: `features/voice/`.
- [x] Assistant text: light Markdown from the model (`**bold**`, `- ` items) rendered as React nodes (no HTML injected).
- [x] `GET /api/health` polled: chat disabled with a message without `OPENAI_API_KEY`; banner when the backend is unreachable (RNF-04).
- [x] i18n dictionary (`lib/format.ts`): categories, subcategories, stock states, use cases and spec groups. Product names and spec values stay in English.

### Not done yet
Waiting for backend endpoints (do not build against guesses; follow `docs/PLAN.md` §12 when they land):
1. **Checkout (N6)**: shipping vs pickup, pickup branches with availability, simulated payment, summary, confirmation modal, `PRICE_CHANGED` / `OUT_OF_STOCK` handling. Needs `/api/checkout*`, `/api/orders/{id}/confirm`. The cart drawer has a disabled "Continuar al checkout" button as a placeholder.
2. **Confirmation screen + order history (N7)**: needs `/api/orders*`.
3. Extras: `undo_token` toast (E3), checkout prefill from the chat (E4), SSE progress (E2).

Frontend-only, can be done any time:
- Translate spec attribute names (only groups are translated today).
- Small screens: the chat panel is always visible (desktop-first prototype).

### Gaps in the API found while building the UI (for the backend owners)
- `GET /api/products` only filters by category; §13 also lists brand, price and in-stock filters.
- The level-3 `summary` formats amounts as `USD 359.88` while the UI uses `USD 359,88`.
- `POST /api/transcribe` returns invented text for audio without speech (silence → "…un producto que se llame Kairo Dock", a beep → "Claro, ¿qué buscas?"). The UI skips silent recordings, but noise still gets through as editable text.
- The comparison's fixed rows come pre-formatted in English (`36 months`, `4.6 (2581 reviews)`); the UI translates those two suffixes and formats the price from `products[i].current_price`.

### Known limitations / notes
- No tests for the frontend yet (the project has no E2E requirement; backend tests are the priority, `docs/PLAN.md` §16).
- The Docker image runs the Vite **dev server** (fine for a local prototype, not a production build).
- `src/components/ui/*` is generated by shadcn (`npx shadcn@latest add <component>`); it imports `cn` from the `cn` package by design of the current shadcn version. Added in this step: label, tabs, table, alert-dialog.
