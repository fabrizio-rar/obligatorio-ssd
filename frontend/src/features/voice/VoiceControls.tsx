import { Loader2Icon, MicIcon, SquareIcon, XIcon } from 'lucide-react'
import type { KeyboardEvent, PointerEvent } from 'react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

import { MAX_SECONDS } from './useVoiceRecorder'
import type { VoiceStatus } from './useVoiceInput'
import { VoiceWaveform } from './VoiceWaveform'

const clock = (seconds: number) => `0:${String(seconds).padStart(2, '0')}`

/** 🎤 button: hold to talk, or tap to start / tap to finish. Red square while recording. */
export function MicButton({
  status,
  disabledReason,
  handlers,
}: {
  status: VoiceStatus
  disabledReason: string | null
  handlers: {
    onPointerDown: (event: PointerEvent<HTMLButtonElement>) => void
    onPointerUp: () => void
    onKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => void
  }
}) {
  const recording = status === 'recording'
  const label = recording
    ? 'Terminar y transcribir'
    : status === 'transcribing'
      ? 'Transcribiendo…'
      : (disabledReason ?? 'Hablar: mantené apretado, o tocá para empezar y de nuevo para terminar')
  return (
    <Button
      type="button"
      size="icon"
      variant={recording ? 'destructive' : 'outline'}
      className={cn('size-9 shrink-0 touch-none select-none', recording && 'animate-pulse')}
      aria-label={label}
      title={label}
      aria-pressed={recording}
      // Not disabled while recording: it is the way to finish
      disabled={!recording && (disabledReason !== null || status === 'transcribing' || status === 'requesting')}
      {...handlers}
    >
      {status === 'transcribing' || status === 'requesting' ? (
        <Loader2Icon className="animate-spin" />
      ) : recording ? (
        <SquareIcon className="fill-current" />
      ) : (
        <MicIcon />
      )}
    </Button>
  )
}

/** Replaces the text input while recording: red dot, live waveform, time and cancel. */
export function RecordingBar({
  analyser,
  seconds,
  silent,
  onSilenceChange,
  onSound,
  onCancel,
}: {
  analyser: AnalyserNode
  seconds: number
  silent: boolean
  onSilenceChange: (silent: boolean) => void
  onSound: () => void
  onCancel: () => void
}) {
  return (
    <div
      className={cn(
        'flex h-9 min-w-0 flex-1 items-center gap-2 rounded-md border px-2 transition-colors',
        silent ? 'border-amber-300 bg-amber-50' : 'border-destructive/40 bg-destructive/5',
      )}
    >
      <span className="size-2 shrink-0 animate-pulse rounded-full bg-destructive" aria-hidden />
      <VoiceWaveform
        analyser={analyser}
        onSilenceChange={onSilenceChange}
        onSound={onSound}
        className={cn('h-7 min-w-0 flex-1', silent ? 'text-amber-500' : 'text-destructive')}
      />
      <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
        {clock(seconds)} / {clock(MAX_SECONDS)}
      </span>
      <Button type="button" variant="ghost" size="icon" className="size-7" aria-label="Cancelar grabación" onClick={onCancel}>
        <XIcon />
      </Button>
    </div>
  )
}

/** One line above the input that says what is happening (and warns when no sound arrives). */
export function VoiceHint({ status, silent }: { status: VoiceStatus; silent: boolean }) {
  if (status === 'idle') return null
  const text =
    status === 'requesting'
      ? 'Permití el acceso al micrófono para grabar.'
      : status === 'transcribing'
        ? 'Transcribiendo… vas a poder corregir el texto antes de enviarlo.'
        : silent
          ? 'No llega audio: revisá que el micrófono esté conectado y no silenciado.'
          : 'Escuchando… soltá el botón (o tocá ■) para terminar. Esc cancela.'
  return (
    <p
      role="status"
      aria-live="polite"
      className={cn('px-4 pb-1 text-xs', silent && status === 'recording' ? 'text-amber-700' : 'text-muted-foreground')}
    >
      {text}
    </p>
  )
}
