/**
 * Voice as another way to type (docs/PLAN.md §11): record → POST /api/transcribe → the text goes
 * into the chat input, where the user edits it and sends it. It never talks to the agent.
 *
 * The 🎤 button works both ways:
 * - hold it while speaking and release to finish (the plan's push-to-talk);
 * - or tap to start and tap again to finish (needed the first time, while the browser asks
 *   for the mic permission, and handier on a trackpad).
 */
import { useMutation } from '@tanstack/react-query'
import { useCallback, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import { toast } from 'sonner'

import { transcribeAudio } from '@/api/endpoints'

import { useVoiceRecorder } from './useVoiceRecorder'

const HOLD_MS = 400 // pressed longer than this = push-to-talk: releasing finishes
const MIN_AUDIO_BYTES = 1000 // same minimum as the backend: below it there is no speech

export type VoiceStatus = 'idle' | 'requesting' | 'recording' | 'transcribing'

export function useVoiceInput(onText: (text: string) => void) {
  const [silent, setSilent] = useState(false)
  const pressedAt = useRef<number | null>(null)
  const heard = useRef(false) // did the level meter detect any sound in this recording?

  const transcription = useMutation({
    mutationFn: transcribeAudio,
    onSuccess: (result) => onText(result.text),
    onError: (error) => toast.error(error.message),
  })

  const transcribe = transcription.mutate // stable across renders (TanStack Query)
  const onAudio = useCallback(
    (audio: Blob, { analysed }: { analysed: boolean }) => {
      // A silent recording is not sent: the transcription model invents text from the catalog
      // vocabulary when it gets no speech (seen in tests), and it saves a paid call
      if (analysed && !heard.current) {
        toast.info('No se escuchó tu voz: revisá el micrófono y probá de nuevo.')
        return
      }
      if (audio.size < MIN_AUDIO_BYTES) {
        toast.info('No se grabó nada: mantené apretado 🎤 mientras hablás.')
        return
      }
      transcribe(audio)
    },
    [transcribe],
  )
  const onError = useCallback((message: string) => toast.error(message), [])
  const onSound = useCallback(() => {
    heard.current = true
  }, [])
  const begin = () => {
    heard.current = false
    setSilent(false)
    void recorder.start()
  }
  const recorder = useVoiceRecorder({ onAudio, onError })

  const status: VoiceStatus = transcription.isPending ? 'transcribing' : recorder.status

  const buttonHandlers = {
    onPointerDown: (event: PointerEvent<HTMLButtonElement>) => {
      if (event.button !== 0) return
      event.currentTarget.setPointerCapture(event.pointerId) // keep getting pointerup if it moves away
      if (recorder.status === 'recording') {
        recorder.finish() // second tap
        return
      }
      if (recorder.status === 'idle' && !transcription.isPending) {
        pressedAt.current = performance.now()
        begin()
      }
    },
    onPointerUp: () => {
      const startedAt = pressedAt.current
      pressedAt.current = null
      // Held down: releasing finishes. A quick tap (or the permission prompt) keeps recording.
      if (startedAt !== null && performance.now() - startedAt >= HOLD_MS && recorder.status === 'recording') {
        recorder.finish()
      }
    },
    // Keyboard (Enter / Space): toggle, since there is no "holding" a key press here
    onKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => {
      if (event.key !== 'Enter' && event.key !== ' ') return
      event.preventDefault()
      if (recorder.status === 'recording') recorder.finish()
      else if (recorder.status === 'idle' && !transcription.isPending) begin()
    },
  }

  return {
    status,
    seconds: recorder.seconds,
    analyser: recorder.analyser,
    silent,
    setSilent,
    onSound,
    cancel: recorder.cancel,
    finish: recorder.finish,
    buttonHandlers,
  }
}
