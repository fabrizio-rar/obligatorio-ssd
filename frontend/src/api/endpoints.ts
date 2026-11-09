import { api } from './client'
import type {
  Brand,
  Cart,
  Category,
  ChatTurn,
  Comparison,
  ConversationList,
  ConversationMessages,
  Health,
  LoginResult,
  ProductDetail,
  ProductPage,
  Transcription,
  User,
  Warehouse,
} from './types'

export const getHealth = () => api<Health>('/health')

// --- Auth ---
const credentials = (username: string, password: string) => JSON.stringify({ username, password })

export const login = (username: string, password: string) =>
  api<LoginResult>('/auth/login', { method: 'POST', body: credentials(username, password) })

export const register = (username: string, password: string) =>
  api<User>('/auth/register', { method: 'POST', body: credentials(username, password) })

export const logout = () => api<void>('/auth/logout', { method: 'POST' })

export const getMe = () => api<User>('/auth/me')

// --- Catalog (public) ---
export const PAGE_SIZE = 24
export const MAX_CARD_IDS = 20

/** Catalog filters (docs/PLAN.md §12). Prices are the current price in USD, both ends inclusive. */
/** Order of the catalog listing (`?sort=`). "default" = by category, then name. */
export const PRODUCT_SORTS = ['default', 'name_asc', 'name_desc', 'price_asc', 'price_desc'] as const
export type ProductSort = (typeof PRODUCT_SORTS)[number]

export interface CatalogFilters {
  category: string | null
  brand: string | null
  minPrice: number | null
  maxPrice: number | null
  inStock: boolean
  sort: ProductSort
}

export const getProducts = (filters: CatalogFilters, page: number) => {
  const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) })
  if (filters.category) params.set('category', filters.category)
  if (filters.brand) params.set('brand', filters.brand)
  if (filters.minPrice !== null) params.set('min_price', String(filters.minPrice))
  if (filters.maxPrice !== null) params.set('max_price', String(filters.maxPrice))
  if (filters.inStock) params.set('in_stock', 'true')
  if (filters.sort !== 'default') params.set('sort', filters.sort)
  return api<ProductPage>(`/products?${params}`)
}

/** Brands with active products (in the category, if given): the options of the brand filter. */
export const getBrands = (category: string | null) =>
  api<Brand[]>(category ? `/brands?category=${encodeURIComponent(category)}` : '/brands')

/** Cards for the chat: same order as the IDs; inactive and unknown IDs are omitted by the API. */
export const getProductCards = (ids: string[]) =>
  api<ProductPage>(`/products?ids=${encodeURIComponent(ids.slice(0, MAX_CARD_IDS).join(','))}`)

export const getProduct = (productId: string) =>
  api<ProductDetail>(`/products/${encodeURIComponent(productId)}`)

/** Comparison table: same domain function as the agent's compare_products tool. */
export const getComparison = (ids: string[]) =>
  api<Comparison>(`/products/compare?ids=${encodeURIComponent(ids.join(','))}`)

export const getCategories = () => api<Category[]>('/categories')

export const getWarehouses = () => api<Warehouse[]>('/warehouses')

// --- Cart (login required). Every mutation returns the updated cart. ---
const item = (productId: string) => `/cart/items/${encodeURIComponent(productId)}`

export const getCart = () => api<Cart>('/cart')

export const addToCart = (productId: string, quantity = 1) =>
  api<Cart>('/cart/items', { method: 'POST', body: JSON.stringify({ product_id: productId, quantity }) })

export const setCartQuantity = (productId: string, quantity: number) =>
  api<Cart>(item(productId), { method: 'PATCH', body: JSON.stringify({ quantity }) })

export const removeFromCart = (productId: string) => api<Cart>(item(productId), { method: 'DELETE' })

export const clearCart = () => api<Cart>('/cart', { method: 'DELETE' })

// --- Chat (login required) ---
export const sendChatMessage = (message: string, conversationId: string | null) =>
  api<ChatTurn>('/chat', {
    method: 'POST',
    body: JSON.stringify({ message, conversation_id: conversationId }),
  })

// --- Voice (login required). The file name's extension must match the recorded format. ---
const AUDIO_EXTENSIONS: Record<string, string> = { 'audio/webm': 'webm', 'audio/mp4': 'mp4', 'audio/ogg': 'ogg' }

export const transcribeAudio = (audio: Blob) => {
  const type = audio.type.split(';')[0].trim()
  const form = new FormData()
  form.append('file', audio, `mensaje.${AUDIO_EXTENSIONS[type] ?? 'webm'}`)
  return api<Transcription>('/transcribe', { method: 'POST', body: form })
}

export const getConversations = (limit = 20) => api<ConversationList>(`/conversations?limit=${limit}`)

export const getConversationMessages = (conversationId: string) =>
  api<ConversationMessages>(`/conversations/${encodeURIComponent(conversationId)}/messages`)
