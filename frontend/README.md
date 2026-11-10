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
    catalog/    CatalogPage (grid + category + pages), CatalogFiltersBar (brand, price, stock), ProductDetailPage (tabs: description, specs, stock per warehouse; related), ProductCard / ProductRow / ProductThumb, ProductImage (photo + local fallback), ProductMeta (Price, StockBadge, Rating)
    cart/       useCart (TanStack Query hooks: the cache is the only cart state), CartSheet (drawer), AddToCartButton
    chat/       ChatPanel (+ ChatSidebar login gate), ChatMessageView (cards, comparison, level-3 confirmation, tools used), ConversationHistory, messages.ts
    voice/      useVoiceRecorder (MediaRecorder + AnalyserNode, 30 s cut), useVoiceInput (hold / tap, transcription), VoiceWaveform (live level line), VoiceControls (MicButton, RecordingBar, VoiceHint)
    compare/    ComparisonTable (shared by the chat and the page), ComparePage (/compare?ids=), useComparison
  lib/          session.ts (token in localStorage, useSession), format.ts (prices + i18n dictionary), utils (cn)
  App.tsx       routes: / (catalog), /products/:id, /compare, /checkout, /orders, /orders/:code, /login, /register; shop layout = header + page + persistent chat panel
  main.tsx      QueryClientProvider + BrowserRouter + Toaster
```

Types in `api/types.ts` mirror Pydantic models in the backend. When a backend schema changes, update them in the same change.

## Status (updated 2026-11-08)

### Done
- [x] Scaffold: Vite, TS strict, Tailwind 4, shadcn/ui, TanStack Query, sonner, react-router, `@/` alias.
- [x] Docker: `frontend` service in `docker-compose.yml` (Vite dev server on `:5173`, hot reload over `src/`).
- [x] **Login / register (N3)**: token from `POST /api/auth/login` kept in localStorage and sent as `Authorization: Bearer`; a 401 with a session drops it and the UI asks to log in again. Register logs in right after. Client-side checks mirror the backend rules (username 3–30 `[a-z0-9._-]`, password ≥ 6). Catalog is public; chat and cart need a login.
- [x] **Catalog + detail (N4, RF-01)**: grid with category chips, a filter bar (brand from `GET /api/brands?category=`, price from/to applied on Enter or blur, "Solo con stock", "Limpiar filtros"), "Ordenar por" (category, name A - Z / Z - A, price low to high / high to low; kept by "Limpiar filtros") and pagination (all in the URL: `?category=&brand=&min_price=&max_price=&in_stock=true&sort=&page=`; any change goes back to page 1, changing the category drops the brand), discounted price struck through, "Sin stock" / "Quedan N" badges. Detail with description, specs grouped, stock per warehouse, alternatives / accessories / often bought with; discontinued products show only alternatives.
- [x] **Cart (N5, RF-09/10)**: drawer with +/− (capped at 10 and at the available stock), remove, clear with a confirmation that lists products, quantities and total; per-item issues (`INACTIVE`, `OUT_OF_STOCK`, `INSUFFICIENT_STOCK`); backend errors as toasts. The cart only lives in the TanStack cache.
- [x] **Chat (N11)**: product cards rendered from `GET /api/products?ids=` (AGENTS.md rule 11), **comparison table** (`comparison_ids` → `GET /api/products/compare`: compact in the chat with only the rows that differ, full on `/compare?ids=` with "Solo diferencias" and add-to-cart cards), clarifying question, suggested-reply chips, retry on transient errors, `ui_actions: refresh_cart` refreshes the cart badge, **level-3 confirmation card** (`pending_confirmation`: the button calls `DELETE /api/cart/items/{id}` or `DELETE /api/cart`, never the agent), **conversation history** (`/api/conversations*`) and "Nueva".
- [x] **Images**: only inside product cards, never in the chat text (the model never writes image URLs). By answer type: `recommendation` / `info` / `clarification` → a card per `product_ids` (in order); `cart_update` → small thumbnails; level-3 confirmation → thumbnails of the cart items involved; `comparison` → a photo per column (`products[i].image_url`); `error` → no products, only "Reintentar". The dataset has **no real photos**: every `image_url` is a `placehold.co` placeholder (a grey box with the SKU, unreadable as a thumbnail). `ProductImage` treats those as "no photo" and draws a local illustration per category (colored background + icon), which is also the fallback when there is no URL or it fails to load (offline, `docs/PLAN.md` §2.1). A real URL, if the dataset ever has one, is shown as is. Inactive products never show their photo (the cart drawer uses the illustration).
- [x] **Voice 🎤 (N12, RF-08)**: hold the button to talk and release to finish (`docs/PLAN.md` §11), or tap to start and tap again (the first time the browser asks for the mic permission). `MediaRecorder` (webm/opus; mp4 on Safari), cut at 30 s, Esc cancels. While recording, the input becomes a bar with a **live level line** (scrolling history of the last seconds from an `AnalyserNode`): flat when no audio arrives, bars when it does; after 1.5 s of silence it warns "No llega audio". `POST /api/transcribe` (multipart) puts the text in the input, editable, never sent by itself. A recording where the meter heard nothing is **not sent** (the model invents text from silence). Clear messages for denied permission, no microphone and mic in use. Disabled when `stt_enabled` is false. Code: `features/voice/`.
- [x] **Checkout (N6, RF-11/12)**: `/checkout` (`features/checkout/`), login required, empty cart → message. Three steps: customer data; delivery (home: street, city, department select; pickup: branches from `GET /api/checkout/options`, the ones without the whole cart disabled with "Falta: X (hay N de M)"); simulated payment (cash only with pickup). Side summary with shipping cost (free from the threshold) and total; the options query is keyed by the cart contents, so a change from the drawer or the chat (`refresh_cart`) recalculates subtotal, shipping and branches. Client validation mirrors the backend, and a 422 `details.fields` lands next to each input. "Revisar compra" → `POST /api/checkout` (pending order) → `ConfirmOrderDialog` (action, products with thumbnails, quantities, unit price, shipping, total, and `orders/OrderFacts`: delivery, payment and customer as three tiles, the same ones the order page shows). Closing it cancels the pending order. `PRICE_CHANGED` keeps it open with the new price highlighted ("Confirmar con el precio nuevo"); other 409s close it and show why, refreshing cart and options. After buying: cart, products and orders queries are invalidated (the stock shown is the new one).
- [x] **Checkout from the chat (start_checkout)**: when `response.checkout` is set (filled by the backend, never by the model) the answer shows a "Listo para el checkout" card (units, delivery, subtotal, shipping, total) with an **"Ir al checkout"** button. It navigates to `/checkout` with `state.prefill` (delivery method and branch, editable); the address is typed in the form. A new navigation starts a fresh form (`key={location.key}`). The card is saved with the conversation, so it shows again from the history.
- [x] **Orders (N7, RF-14/16)**: `/orders` ("Mis órdenes" in the header) and `/orders/:code`, which is also the confirmation screen right after buying ("¡Gracias por tu compra!", where each item ships from). Dates come in UTC and are shown in the user's time zone.
- [x] **Product detail layout**: a main card with the image, "Lo destacado" (key features with checks), category chip, brand linking to the catalog filtered by brand, five-star rating, a purchase box (big price, struck list price, "Ahorrás" from list − current, stock, full-width add button) and two perks from the data (warranty, returns). Full-width tabs in a second card: description with "Ideal para" / "No recomendado para" chips and a facts table (brand, color, weight, dimensions), specs as one card per group, stock as one tile per branch.
- [x] **Brand and look**: MercaNova logo (`components/brand/Logo.tsx`: gradient square with a four-point "nova" star + wordmark; same mark as the favicon: `public/favicon.svg`, plus `favicon-32x32.png` and `apple-touch-icon.png` for browsers without SVG favicons; `public/` is mounted in compose, so icon changes need no rebuild), indigo → violet → fuchsia palette in the theme tokens (`index.css`) on a soft lavender page, dark gradient header, category chips with icons (`catalog/categoryArt.ts`), cards that lift on hover, colored badges (in stock emerald, low amber, discount rose), chat bubbles with the brand gradient and a branded login page.
- [x] **Chat panel UX**: the tools the agent used are NOT shown to the user (internal detail; they stay in `tool_call_logs`, `meta.tools_used` and `scripts.chat --verbose`). every conversation opens with a greeting bubble from the assistant ("¡Hola, {usuario}! Soy el asistente de MercaNova. ¿En qué te puedo ayudar hoy?"; fixed UI text, no model call, not saved). can be minimized to a thin strip on the right ("Asistente" button to reopen) so the catalog uses the whole width; it is only hidden, so the conversation survives, and the choice is remembered in localStorage. Suggested replies are rendered after the last message inside the scroll area, so they disappear when scrolling up. The message box grows with its text (up to ~6 lines, then scrolls vertically, never horizontally), handy to review a voice transcription; Enter sends, Shift+Enter adds a line. While a turn runs, a "typing" bubble with three animated dots (opacity only with `prefers-reduced-motion`).
- [x] Assistant text: light Markdown from the model (`**bold**`, `- ` items) rendered as React nodes (no HTML injected).
- [x] `GET /api/health` polled: chat disabled with a message without `OPENAI_API_KEY`; banner when the backend is unreachable (RNF-04).
- [x] i18n dictionary (`lib/format.ts`): categories, subcategories, stock states, use cases and spec groups. Product names and spec values stay in English.

### Not done yet
1. Extras: `undo_token` toast (E3), SSE progress (E2), address prefill from the chat (E4, decided not to for now).

Frontend-only, can be done any time:
- Translate spec attribute names (only groups are translated today).
- Small screens: the chat panel is always visible (desktop-first prototype).

### Gaps in the API found while building the UI (for the backend owners)
- `POST /api/transcribe` returns invented text for audio without speech (silence → "…un producto que se llame Kairo Dock", a beep → "Claro, ¿qué buscas?"). The UI skips silent recordings, but noise still gets through as editable text.
- The comparison's fixed rows come pre-formatted in English (`36 months`, `4.6 (2581 reviews)`); the UI translates those two suffixes and formats the price from `products[i].current_price`.

### Known limitations / notes
- No tests for the frontend yet (the project has no E2E requirement; backend tests are the priority, `docs/PLAN.md` §16).
- The Docker image runs the Vite **dev server** (fine for a local prototype, not a production build).
- `src/components/ui/*` is generated by shadcn (`npx shadcn@latest add <component>`); it imports `cn` from the `cn` package by design of the current shadcn version. Added in this step: label, tabs, table, alert-dialog.
