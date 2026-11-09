import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeftIcon, HistoryIcon, MessageSquarePlusIcon, PanelRightCloseIcon } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { toast } from 'sonner'

import { ApiError } from '@/api/client'
import { LogoMark } from '@/components/brand/Logo'
import { getConversationMessages, getHealth, sendChatMessage } from '@/api/endpoints'
import { Button, buttonVariants } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Textarea } from '@/components/ui/textarea'
import { CART_KEY } from '@/features/cart/useCart'
import { MicButton, RecordingBar, VoiceHint } from '@/features/voice/VoiceControls'
import { useVoiceInput } from '@/features/voice/useVoiceInput'
import { useSession } from '@/lib/session'

import { ChatMessageView } from './ChatMessageView'
import { ConversationHistory } from './ConversationHistory'
import { fromHistory, type ChatMessage, type ConfirmationState } from './messages'

/** Side panel: the assistant needs a login (POST /api/chat requires it). */
export function ChatSidebar({ minimized, onMinimize }: { minimized: boolean; onMinimize: () => void }) {
  const session = useSession()
  const location = useLocation()
  if (session) return <ChatPanel key={session.username} minimized={minimized} onMinimize={onMinimize} />
  return (
    <div className="relative flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
      <div className="absolute top-3 right-3">
        <MinimizeButton onClick={onMinimize} />
      </div>
      <LogoMark className="size-12" />
      <h2 className="font-semibold">Asistente MercaNova</h2>
      <p className="text-sm text-muted-foreground">
        Iniciá sesión para que el asistente te ayude a elegir, comparar y armar tu carrito.
      </p>
      <Link to="/login" state={{ from: location.pathname + location.search }} className={buttonVariants()}>
        Iniciar sesión
      </Link>
    </div>
  )
}

function MinimizeButton({ onClick }: { onClick: () => void }) {
  return (
    <Button variant="ghost" size="icon-sm" onClick={onClick} aria-label="Minimizar el asistente" title="Minimizar">
      <PanelRightCloseIcon />
    </Button>
  )
}

/** Three dots that rise in turn, like someone typing (respects prefers-reduced-motion). */
function TypingIndicator() {
  return (
    <div
      role="status"
      aria-label="El asistente está escribiendo"
      className="mr-8 flex w-fit items-center gap-1 rounded-2xl rounded-bl-sm bg-secondary px-3 py-3"
    >
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="typing-dot size-1.5 rounded-full bg-primary/70"
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </div>
  )
}

function ChatPanel({ minimized, onMinimize }: { minimized: boolean; onMinimize: () => void }) {
  const queryClient = useQueryClient()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [view, setView] = useState<'chat' | 'history'>('chat')
  const [draft, setDraft] = useState('')
  const nextId = useRef(1)
  const bottomRef = useRef<HTMLDivElement>(null)
  const newId = () => `live-${nextId.current++}`

  const health = useQuery({ queryKey: ['health'], queryFn: getHealth, refetchInterval: 30_000 })
  const chatDisabled = health.data?.chat_enabled === false
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // Voice only fills the input: the user reviews the text and sends it (docs/PLAN.md §11)
  const onTranscribed = useCallback((text: string) => {
    setDraft((prev) => (prev.trim() ? `${prev.trim()} ${text}` : text))
    requestAnimationFrame(() => {
      const input = inputRef.current
      input?.focus()
      input?.setSelectionRange(input.value.length, input.value.length)
    })
  }, [])
  const voice = useVoiceInput(onTranscribed)
  const voiceBusy = voice.status !== 'idle'

  // The input grows with its text (a long message or a voice transcription) up to ~6 lines,
  // then scrolls vertically: never horizontally.
  useLayoutEffect(() => {
    const input = inputRef.current
    if (!input) return
    input.style.height = 'auto'
    input.style.height = `${input.scrollHeight}px`
  }, [draft, voice.status]) // the textarea remounts after a recording

  const send = useMutation({
    mutationFn: (text: string) => sendChatMessage(text, conversationId),
    onSuccess: (turn) => {
      const { response } = turn
      setConversationId(turn.conversation_id)
      setMessages((prev) => [
        ...prev,
        {
          id: newId(),
          role: 'assistant',
          response,
          tools: turn.meta.tools_used,
          confirmation: response.pending_confirmation ? 'pending' : null,
        },
      ])
      // The agent changed the cart: refresh the badge and the drawer (docs/PLAN.md §13)
      if (response.ui_actions.includes('refresh_cart')) void queryClient.invalidateQueries({ queryKey: CART_KEY })
      void queryClient.invalidateQueries({ queryKey: ['conversations'] })
    },
    onError: (error, text) => {
      const apiError = error instanceof ApiError ? error : null
      const message = apiError?.message ?? 'Ocurrió un error inesperado.'
      toast.error(message)
      setMessages((prev) => [
        ...prev,
        { id: newId(), role: 'error', text: message, retryText: apiError?.retryable ? text : null },
      ])
    },
  })

  const open = useMutation({
    mutationFn: getConversationMessages,
    onSuccess: (conversation) => {
      setMessages(fromHistory(conversation))
      setConversationId(conversation.conversation_id)
      setView('chat')
    },
    onError: (error) => toast.error(error.message),
  })

  const micDisabledReason = chatDisabled
    ? 'El asistente no está disponible'
    : health.data?.stt_enabled === false
      ? 'La voz no está disponible: falta configurar OPENAI_API_KEY en el backend'
      : send.isPending
        ? 'Esperá la respuesta del asistente'
        : null

  // New message, a turn starts, back from the history, or the panel is opened again
  useEffect(() => {
    if (!minimized) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, send.isPending, view, minimized])

  function submit(text: string) {
    const clean = text.trim()
    if (!clean || send.isPending || chatDisabled) return
    setMessages((prev) => [...prev, { id: newId(), role: 'user', text: clean }])
    setDraft('')
    send.mutate(clean)
  }

  /** Retry: the user's bubble is already in the panel, so only send the text again. */
  function resend(text: string) {
    if (send.isPending || chatDisabled) return
    send.mutate(text)
  }

  /** Only the last message offers "Reintentar": a failed request, or an answer of type "error". */
  function retryTextFor(message: ChatMessage, index: number): string | null {
    if (index !== messages.length - 1) return null
    if (message.role === 'error') return message.retryText
    if (message.role === 'assistant' && message.response.type === 'error') {
      const lastUser = messages
        .slice(0, index)
        .findLast((m): m is Extract<ChatMessage, { role: 'user' }> => m.role === 'user')
      return lastUser?.text ?? null
    }
    return null
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    submit(draft)
  }

  /** Enter sends, Shift+Enter adds a new line (not while composing an accent with an IME). */
  function onInputKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      submit(draft)
    }
  }

  function newConversation() {
    setMessages([])
    setConversationId(null) // the next POST /api/chat without conversation_id creates one
    setView('chat')
  }

  function setConfirmation(messageId: string, state: ConfirmationState) {
    setMessages((prev) =>
      prev.map((m) => (m.id === messageId && m.role === 'assistant' ? { ...m, confirmation: state } : m)),
    )
  }

  const lastAssistant = messages.findLast((m) => m.role === 'assistant')
  const suggestions = lastAssistant?.role === 'assistant' ? lastAssistant.response.suggested_replies : []

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between gap-2 border-b bg-linear-to-r from-indigo-50 via-violet-50 to-fuchsia-50 px-4 py-3">
        <div className="flex items-center gap-2.5">
          <LogoMark className="size-8" />
          <div className="leading-tight">
            <h2 className="font-semibold">Asistente MercaNova</h2>
            <p className="text-xs text-muted-foreground">Te ayuda a elegir y comparar</p>
          </div>
        </div>
        {/* Locked while a turn is running: its answer belongs to the current conversation */}
        <div className="flex gap-1">
          <Button
            variant={view === 'history' ? 'secondary' : 'ghost'}
            size="sm"
            onClick={() => setView(view === 'history' ? 'chat' : 'history')}
            disabled={send.isPending}
          >
            {view === 'history' ? (
              <>
                <ArrowLeftIcon data-icon="inline-start" />
                Volver al chat
              </>
            ) : (
              <>
                <HistoryIcon data-icon="inline-start" />
                Historial
              </>
            )}
          </Button>
          {/* From the history it always works (it opens an empty chat); in the chat, only if there is something to clear */}
          <Button
            variant="ghost"
            size="sm"
            onClick={newConversation}
            disabled={send.isPending || (view === 'chat' && messages.length === 0)}
          >
            <MessageSquarePlusIcon data-icon="inline-start" />
            Nueva
          </Button>
          <MinimizeButton onClick={onMinimize} />
        </div>
      </div>

      {chatDisabled && (
        <p className="border-b bg-amber-50 px-4 py-2 text-sm text-amber-900">
          El asistente no está disponible: falta configurar OPENAI_API_KEY en el backend.
        </p>
      )}
      {health.isError && (
        <p className="border-b bg-red-50 px-4 py-2 text-sm text-red-900">No se pudo conectar con el backend.</p>
      )}

      {view === 'history' ? (
        <ConversationHistory
          currentId={conversationId}
          loadingId={open.isPending ? (open.variables ?? null) : null}
          onOpen={(id) => open.mutate(id)}
        />
      ) : (
        <>
          <ScrollArea className="min-h-0 flex-1 px-4">
            <div className="flex flex-col gap-3 py-4">
              {messages.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  Contame qué necesitás. Por ejemplo: “Necesito unos auriculares cómodos para videollamadas, hasta
                  USD 200”.
                </p>
              )}
              {messages.map((m, i) => (
                <ChatMessageView
                  key={m.id}
                  message={m}
                  busy={send.isPending}
                  retryText={retryTextFor(m, i)}
                  onRetry={resend}
                  onConfirmation={(state) => setConfirmation(m.id, state)}
                />
              ))}
              {send.isPending && <TypingIndicator />}
              {/* Inside the scroll area, after the last message: scrolling up hides them */}
              {suggestions.length > 0 && !send.isPending && (
                <div className="flex flex-wrap gap-2" aria-label="Respuestas sugeridas">
                  {suggestions.map((s) => (
                    <Button key={s} variant="outline" size="sm" onClick={() => submit(s)}>
                      {s}
                    </Button>
                  ))}
                </div>
              )}
              <div ref={bottomRef} />
            </div>
          </ScrollArea>

          <VoiceHint status={voice.status} silent={voice.silent} />
          <form onSubmit={onSubmit} className="flex items-end gap-2 border-t p-3">
            {voice.status === 'recording' && voice.analyser ? (
              <RecordingBar
                analyser={voice.analyser}
                seconds={voice.seconds}
                silent={voice.silent}
                onSilenceChange={voice.setSilent}
                onSound={voice.onSound}
                onCancel={voice.cancel}
              />
            ) : (
              <Textarea
                ref={inputRef}
                rows={1}
                className="max-h-36 min-h-8 resize-none overflow-y-auto py-1.5"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={onInputKeyDown}
                placeholder={voice.status === 'transcribing' ? 'Transcribiendo…' : 'Escribí tu consulta o usá 🎤…'}
                maxLength={2000}
                disabled={chatDisabled || voiceBusy}
                aria-label="Mensaje para el asistente"
              />
            )}
            <MicButton status={voice.status} disabledReason={micDisabledReason} handlers={voice.buttonHandlers} />
            <Button type="submit" disabled={!draft.trim() || send.isPending || chatDisabled || voiceBusy}>
              Enviar
            </Button>
          </form>
        </>
      )}
    </div>
  )
}
