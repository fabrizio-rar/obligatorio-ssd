import { api } from './client'
import type { ChatTurn, Health } from './types'

export const getHealth = () => api<Health>('/health')

export const sendChatMessage = (message: string, conversationId: string | null) =>
  api<ChatTurn>('/chat', {
    method: 'POST',
    body: JSON.stringify({ message, conversation_id: conversationId }),
  })
