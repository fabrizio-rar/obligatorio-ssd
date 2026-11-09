/**
 * Types that mirror the backend contract (docs/PLAN.md §12). Keep in sync with the Pydantic models.
 * Decimals arrive as strings ("366.38"): format them with lib/format.ts, never do math with the text.
 */

export interface Health {
  status: 'ok' | 'degraded'
  db: 'ok' | 'unavailable'
  chat_enabled: boolean
  stt_enabled: boolean // POST /api/transcribe available (needs OPENAI_API_KEY)
}

// --- Auth: backend/app/api/auth.py -------------------------------------------------------------
export interface User {
  id: number
  username: string
}

export interface LoginResult {
  token: string
  token_type: string
  expires_in_hours: number
  user: User
}

// --- Catalog: backend/app/domain/catalog.py ----------------------------------------------------
// backend/app/domain/inventory.py (dataset rule: 0 -> Out, 1-2 -> Low, >= 3 -> In stock)
export type StockStatus = 'In stock' | 'Low stock' | 'Out of stock'
export type ProductStatus = 'available' | 'out_of_stock' | 'discontinued'
export type RelationType = 'alternative_to' | 'accessory_for' | 'often_bought_with'

export interface ProductCard {
  product_id: string
  sku: string
  name: string
  brand: string
  category: string
  subcategory: string
  image_url: string | null
  currency: string
  current_price: string
  list_price: string
  discount_percent: number
  available: number
  stock_status: StockStatus
  rating: string | null
  review_count: number | null
}

export interface ProductPage {
  items: ProductCard[]
  page: number
  page_size: number
  total: number
  total_pages: number
}

export interface SpecValue {
  group: string | null
  name: string
  value: string
  available: boolean // false when the dataset has no value ("N/D")
}

export interface WarehouseStock {
  warehouse_id: string
  name: string
  city: string | null
  available: number
  pickup_enabled: boolean
}

export interface RelatedProduct extends ProductCard {
  relation_type: RelationType
  strength: string | null
}

/** GET /api/products/{id}. A discontinued product comes without price or stock, only alternatives. */
export interface ProductDetail {
  product_id: string
  name: string
  sku: string
  category: string
  subcategory: string
  status: ProductStatus
  brand: string | null
  brand_positioning: string | null
  short_description: string | null
  description: string | null
  key_features: string[]
  recommended_for: string[]
  not_recommended_for: string[]
  image_url: string | null
  color: string | null
  weight_kg: string | null
  dimensions_cm: string | null
  warranty_months: number | null
  return_days: number | null
  rating: string | null
  review_count: number | null
  currency: string | null
  current_price: string | null
  list_price: string | null
  discount_percent: number | null
  available: number | null
  stock_status: StockStatus | null
  stock_by_warehouse: WarehouseStock[]
  specs: SpecValue[]
  alternatives: RelatedProduct[]
  accessories: RelatedProduct[]
  often_bought_with: RelatedProduct[]
}

export interface Category {
  category_id: string
  name: string // dataset name in English: it is also the value of ?category=
  subcategories: string[]
  product_count: number
}

export interface Brand {
  brand_id: string
  name: string // also the value of ?brand=
  positioning: string | null
  product_count: number // active products (in the category, when filtered)
}

export interface Warehouse {
  warehouse_id: string
  name: string
  city: string | null
  department: string | null
  pickup_enabled: boolean
  shipping_enabled: boolean
}

// --- Comparison: backend/app/domain/comparison.py (GET /api/products/compare?ids=, 2-4 IDs, same category) ---
export const MIN_COMPARE = 2
export const MAX_COMPARE = 4

export interface ComparedProduct {
  product_id: string
  name: string
  sku: string
  brand: string | null
  subcategory: string
  currency: string | null
  current_price: string | null
  image_url: string | null
}

export interface ComparisonRow {
  group: string // "General" for the fixed rows (Price, Discount...), else the spec group
  attribute: string
  values: string[] // values[i] belongs to products[i] (names can repeat: match by position)
  differs: boolean
}

export interface Comparison {
  category: string
  products: ComparedProduct[]
  rows: ComparisonRow[]
}

// --- Cart: backend/app/domain/cart.py ----------------------------------------------------------
export const MAX_QUANTITY_PER_ITEM = 10

export type CartIssue = 'INACTIVE' | 'OUT_OF_STOCK' | 'INSUFFICIENT_STOCK'

export interface CartItem {
  product_id: string
  sku: string
  name: string
  brand: string
  category: string
  image_url: string | null
  currency: string
  unit_price: string // current price: the cart does not store prices
  list_price: string
  discount_percent: number
  quantity: number
  line_total: string // 0 for an inactive product
  available: number
  stock_status: StockStatus
  active: boolean
  issues: CartIssue[]
}

export interface Cart {
  items: CartItem[]
  item_count: number // sum of quantities (the badge)
  currency: string
  total: string
  can_checkout: boolean // at least one item and no issues
}

// --- Chat: backend/app/agent/response_schema.py and service.py ---------------------------------
export type AgentResponseType = 'recommendation' | 'comparison' | 'clarification' | 'info' | 'cart_update' | 'error'
export type UiAction = 'refresh_cart'

/** Level-3 action (remove or clear): the agent does not run it, the user confirms with a button. */
export interface PendingAction {
  action: 'remove_item' | 'clear_cart'
  product_id: string | null // remove_item only
  summary: string // built by the backend with DB data
}

export interface AgentResponse {
  type: AgentResponseType
  message: string
  product_ids: string[]
  clarifying_question: string | null
  suggested_replies: string[]
  ui_actions: UiAction[]
  pending_confirmation: PendingAction | null
  // Filled by the backend from the last compare_products of the turn: draw the table with GET /api/products/compare
  comparison_ids: string[]
}

export interface TurnMeta {
  steps: number
  stop_reason: string
  tools_used: string[]
  input_tokens: number
  output_tokens: number
  latency_ms: number
  model: string
}

export interface ChatTurn {
  conversation_id: string
  response: AgentResponse
  meta: TurnMeta
}

// --- Voice: backend/app/api/transcribe.py (only transcribes: the text goes to the chat input) ---
export interface Transcription {
  text: string
  model: string
}

// --- Conversations: backend/app/agent/conversations.py -----------------------------------------
export interface ConversationSummary {
  conversation_id: string
  title: string
  created_at: string
  last_message_at: string
  message_count: number
  last_message_preview: string
}

export interface ConversationList {
  items: ConversationSummary[]
  total: number
  limit: number
  offset: number
}

export interface ToolCallSummary {
  step: number
  tool_name: string
  arguments: Record<string, unknown> | null
  is_error: boolean
  error_code: string | null
  latency_ms: number
}

export interface StoredMessage {
  message_id: number
  role: 'user' | 'assistant'
  content: string
  created_at: string
  // The stored AgentResponse. Older messages may lack the fields added later: normalize before use.
  response: Partial<AgentResponse> | null
  tools: ToolCallSummary[]
}

export interface ConversationMessages {
  conversation_id: string
  title: string
  messages: StoredMessage[]
}
