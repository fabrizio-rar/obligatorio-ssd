/** Types that mirror the backend contract (docs/PLAN.md §12). Keep in sync with the Pydantic models. */

export interface Health {
  status: 'ok' | 'degraded'
  db: 'ok' | 'unavailable'
  chat_enabled: boolean
}

// backend/app/agent/response_schema.py
export type AgentResponseType = 'recommendation' | 'clarification' | 'info' | 'error'

export interface AgentResponse {
  type: AgentResponseType
  message: string
  product_ids: string[]
  clarifying_question: string | null
  suggested_replies: string[]
}

// backend/app/agent/service.py
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
