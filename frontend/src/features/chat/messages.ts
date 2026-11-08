import type { AgentResponse, ConversationMessages, StoredMessage } from '@/api/types'

/**
 * State of a level-3 confirmation card (remove / clear): the agent never runs those actions,
 * the user confirms with a button that calls the REST API (docs/PLAN.md §10.4.1).
 * "stale": it comes from a reloaded conversation, so the buttons are not offered again.
 */
export type ConfirmationState = 'pending' | 'done' | 'cancelled' | 'stale'

export type ChatMessage =
  | { id: string; role: 'user'; text: string }
  | {
      id: string
      role: 'assistant'
      response: AgentResponse
      tools: string[]
      confirmation: ConfirmationState | null
    }
  | { id: string; role: 'error'; text: string; retryText: string | null }

/** Messages saved before a field existed come without it: fill in the defaults. */
export function normalizeResponse(raw: StoredMessage['response'], content: string): AgentResponse {
  return {
    type: raw?.type ?? 'info',
    message: raw?.message ?? content,
    product_ids: raw?.product_ids ?? [],
    clarifying_question: raw?.clarifying_question ?? null,
    suggested_replies: raw?.suggested_replies ?? [],
    ui_actions: raw?.ui_actions ?? [],
    pending_confirmation: raw?.pending_confirmation ?? null,
    comparison_ids: raw?.comparison_ids ?? [],
  }
}

/** GET /api/conversations/{id}/messages → the panel's messages. */
export function fromHistory(conversation: ConversationMessages): ChatMessage[] {
  return conversation.messages.map((m): ChatMessage => {
    const id = `history-${m.message_id}`
    if (m.role === 'user') return { id, role: 'user', text: m.content }
    const response = normalizeResponse(m.response, m.content)
    return {
      id,
      role: 'assistant',
      response,
      tools: m.tools.map((t) => t.tool_name),
      confirmation: response.pending_confirmation ? 'stale' : null,
    }
  })
}
