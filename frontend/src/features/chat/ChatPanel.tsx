import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { toast } from 'sonner'

import { ApiError } from '@/api/client'
import { getHealth, sendChatMessage } from '@/api/endpoints'
import type { AgentResponse } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'

type Message =
  | { id: number; role: 'user'; text: string }
  | { id: number; role: 'assistant'; response: AgentResponse }
  | { id: number; role: 'error'; text: string; retryText: string | null }

export function ChatPanel() {
  const [messages, setMessages] = useState<Message[]>([])
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const nextId = useRef(1)
  const bottomRef = useRef<HTMLDivElement>(null)

  const health = useQuery({ queryKey: ['health'], queryFn: getHealth, refetchInterval: 30_000 })
  const chatDisabled = health.data?.chat_enabled === false

  const send = useMutation({
    mutationFn: (text: string) => sendChatMessage(text, conversationId),
    onSuccess: (turn) => {
      setConversationId(turn.conversation_id)
      setMessages((prev) => [...prev, { id: nextId.current++, role: 'assistant', response: turn.response }])
    },
    onError: (error, text) => {
      const apiError = error instanceof ApiError ? error : null
      const message = apiError?.message ?? 'Ocurrió un error inesperado.'
      toast.error(message)
      setMessages((prev) => [
        ...prev,
        { id: nextId.current++, role: 'error', text: message, retryText: apiError?.retryable ? text : null },
      ])
    },
  })

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, send.isPending])

  function submit(text: string) {
    const clean = text.trim()
    if (!clean || send.isPending || chatDisabled) return
    setMessages((prev) => [...prev, { id: nextId.current++, role: 'user', text: clean }])
    setDraft('')
    send.mutate(clean)
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    submit(draft)
  }

  function newConversation() {
    setMessages([])
    setConversationId(null)
  }

  const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant')
  const suggestions = lastAssistant?.role === 'assistant' ? lastAssistant.response.suggested_replies : []

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <h2 className="font-semibold">Asistente MercaNova</h2>
        <Button variant="ghost" size="sm" onClick={newConversation} disabled={messages.length === 0}>
          Nueva conversación
        </Button>
      </div>

      {chatDisabled && (
        <p className="border-b bg-amber-50 px-4 py-2 text-sm text-amber-900">
          El asistente no está disponible: falta configurar OPENAI_API_KEY en el backend.
        </p>
      )}
      {health.isError && (
        <p className="border-b bg-red-50 px-4 py-2 text-sm text-red-900">
          No se pudo conectar con el backend.
        </p>
      )}

      <ScrollArea className="flex-1 px-4">
        <div className="flex flex-col gap-3 py-4">
          {messages.length === 0 && (
            <p className="text-sm text-muted-foreground">
              Contame qué necesitás. Por ejemplo: “Necesito unos auriculares cómodos para videollamadas, hasta
              USD 200”.
            </p>
          )}
          {messages.map((m) => (
            <MessageBubble key={m.id} message={m} onRetry={submit} disabled={send.isPending} />
          ))}
          {send.isPending && <p className="text-sm text-muted-foreground">El asistente está pensando…</p>}
          <div ref={bottomRef} />
        </div>
      </ScrollArea>

      {suggestions.length > 0 && !send.isPending && (
        <div className="flex flex-wrap gap-2 px-4 pb-2">
          {suggestions.map((s) => (
            <Button key={s} variant="outline" size="sm" onClick={() => submit(s)}>
              {s}
            </Button>
          ))}
        </div>
      )}

      <form onSubmit={onSubmit} className="flex gap-2 border-t p-3">
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Escribí tu consulta…"
          maxLength={2000}
          disabled={chatDisabled}
          aria-label="Mensaje para el asistente"
        />
        <Button type="submit" disabled={!draft.trim() || send.isPending || chatDisabled}>
          Enviar
        </Button>
      </form>
    </div>
  )
}

function MessageBubble({
  message,
  onRetry,
  disabled,
}: {
  message: Message
  onRetry: (text: string) => void
  disabled: boolean
}) {
  if (message.role === 'user') {
    return (
      <div className="ml-8 self-end rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground">
        {message.text}
      </div>
    )
  }

  if (message.role === 'error') {
    return (
      <div className="mr-8 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">
        <p>{message.text}</p>
        {message.retryText && (
          <Button
            variant="outline"
            size="sm"
            className="mt-2"
            disabled={disabled}
            onClick={() => onRetry(message.retryText as string)}
          >
            Reintentar
          </Button>
        )}
      </div>
    )
  }

  const { response } = message
  return (
    <div className="mr-8 rounded-lg bg-muted px-3 py-2 text-sm">
      <p className="whitespace-pre-wrap">{response.message}</p>
      {response.product_ids.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {/* TODO: render product cards once GET /api/products?ids= exists (AGENTS.md rule 11). */}
          {response.product_ids.map((id) => (
            <Badge key={id} variant="secondary">
              {id}
            </Badge>
          ))}
        </div>
      )}
    </div>
  )
}
