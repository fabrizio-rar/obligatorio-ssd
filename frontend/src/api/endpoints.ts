import { api } from './client'
import type {
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

export const getProducts = (category: string | null, page: number) => {
  const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) })
  if (category) params.set('category', category)
  return api<ProductPage>(`/products?${params}`)
}

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
