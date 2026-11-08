import { useQuery } from '@tanstack/react-query'

import { getConversations } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Skeleton } from '@/components/ui/skeleton'

const dateFormat = new Intl.DateTimeFormat('es-UY', { dateStyle: 'short', timeStyle: 'short' })

/** The user's past conversations (GET /api/conversations), most recent first. */
export function ConversationHistory({
  currentId,
  loadingId,
  onOpen,
}: {
  currentId: string | null
  loadingId: string | null
  onOpen: (conversationId: string) => void
}) {
  const conversations = useQuery({ queryKey: ['conversations'], queryFn: () => getConversations() })

  return (
    <ScrollArea className="min-h-0 flex-1 px-4">
      <div className="flex flex-col gap-2 py-4">
        {conversations.isPending && Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-16" />)}
        {conversations.isError && (
          <div className="text-sm">
            <p className="text-destructive">{conversations.error.message}</p>
            <Button variant="outline" size="sm" className="mt-2" onClick={() => conversations.refetch()}>
              Reintentar
            </Button>
          </div>
        )}
        {conversations.data?.items.length === 0 && (
          <p className="text-sm text-muted-foreground">Todavía no tenés conversaciones.</p>
        )}
        {conversations.data?.items.map((c) => (
          <button
            key={c.conversation_id}
            type="button"
            disabled={loadingId !== null}
            onClick={() => onOpen(c.conversation_id)}
            className="flex flex-col gap-0.5 rounded-lg border p-3 text-left text-sm transition-colors hover:bg-muted disabled:opacity-60 data-[current=true]:border-primary"
            data-current={c.conversation_id === currentId}
          >
            <span className="truncate font-medium">{c.title}</span>
            <span className="line-clamp-2 text-xs text-muted-foreground">{c.last_message_preview}</span>
            <span className="text-xs text-muted-foreground">
              {loadingId === c.conversation_id
                ? 'Abriendo…'
                : `${dateFormat.format(new Date(c.last_message_at))} · ${c.message_count} mensajes`}
            </span>
          </button>
        ))}
      </div>
    </ScrollArea>
  )
}
