/**
 * Microphone recording for the chat (docs/PLAN.md §11): MediaRecorder + an AnalyserNode that feeds
 * the live waveform. The UI cuts the recording at 30 s (the backend only limits the size).
 */
import { useCallback, useEffect, useRef, useState } from 'react'

export const MAX_SECONDS = 30
// Chrome / Firefox record webm/opus, Safari mp4: all accepted by POST /api/transcribe
const MIME_CANDIDATES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus', 'audio/ogg']

export type RecorderStatus = 'idle' | 'requesting' | 'recording'

interface Recording {
  stream: MediaStream
  recorder: MediaRecorder
  context: AudioContext
  timer: number
  discard: boolean
  stopping: boolean // recorder.stop() already called: onstop will release everything
}

function micErrorMessage(error: unknown): string {
  const name = error instanceof DOMException ? error.name : ''
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return 'Necesito permiso para usar el micrófono: habilitalo en el navegador (ícono a la izquierda de la dirección) y probá de nuevo.'
  }
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'No encontré ningún micrófono conectado.'
  if (name === 'NotReadableError') return 'El micrófono está en uso por otra aplicación.'
  return 'No se pudo acceder al micrófono.'
}

export function useVoiceRecorder({
  onAudio,
  onError,
}: {
  /** analysed: the level meter was really running, so "no sound detected" can be trusted */
  onAudio: (audio: Blob, info: { analysed: boolean }) => void
  onError: (message: string) => void
}) {
  const [status, setStatus] = useState<RecorderStatus>('idle')
  const [seconds, setSeconds] = useState(0)
  const [analyser, setAnalyser] = useState<AnalyserNode | null>(null)
  const recording = useRef<Recording | null>(null)
  const cancelRequested = useRef(false)
  const callbacks = useRef({ onAudio, onError })

  useEffect(() => {
    callbacks.current = { onAudio, onError }
  }, [onAudio, onError])

  const release = useCallback((current: Recording) => {
    window.clearInterval(current.timer)
    current.stream.getTracks().forEach((track) => track.stop()) // turns the browser's mic indicator off
    current.context.close().catch(() => {})
    if (recording.current === current) recording.current = null
    setAnalyser(null)
    setSeconds(0)
    setStatus('idle')
  }, [])

  /** Ends the recording: the audio goes to onAudio, unless it is discarded (cancel). */
  const stop = useCallback(
    (discard: boolean) => {
      if (!recording.current) {
        cancelRequested.current = discard // still asking for the mic permission
        return
      }
      const current = recording.current
      if (current.stopping) return // the 30 s timer and a click can both arrive
      current.discard = discard
      current.stopping = true
      if (current.recorder.state !== 'inactive') current.recorder.stop()
      else release(current)
    },
    [release],
  )

  const start = useCallback(async () => {
    if (recording.current) return
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      callbacks.current.onError('Este navegador no permite grabar audio.')
      return
    }
    cancelRequested.current = false
    setStatus('requesting')
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (error) {
      setStatus('idle')
      callbacks.current.onError(micErrorMessage(error))
      return
    }
    if (cancelRequested.current) {
      stream.getTracks().forEach((track) => track.stop())
      setStatus('idle')
      return
    }

    const mimeType = MIME_CANDIDATES.find((type) => MediaRecorder.isTypeSupported(type))
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
    const chunks: Blob[] = []
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data)
    }

    // Analyser for the live waveform: it only reads the signal, nothing is played back
    const context = new AudioContext()
    // Some browsers create it "suspended" (autoplay policy): then the waveform would stay flat
    if (context.state === 'suspended') context.resume().catch(() => {})
    const node = context.createAnalyser()
    node.fftSize = 1024
    context.createMediaStreamSource(stream).connect(node)

    const startedAt = Date.now()
    const current: Recording = {
      stream,
      recorder,
      context,
      discard: false,
      stopping: false,
      timer: window.setInterval(() => {
        const elapsed = Math.floor((Date.now() - startedAt) / 1000)
        setSeconds(Math.min(elapsed, MAX_SECONDS))
        if (elapsed >= MAX_SECONDS) stop(false) // limit of the UI (docs/PLAN.md §11)
      }, 200),
    }
    recorder.onstop = () => {
      const audio = new Blob(chunks, { type: recorder.mimeType || mimeType || 'audio/webm' })
      const { discard } = current
      const analysed = current.context.state === 'running'
      release(current)
      if (!discard) callbacks.current.onAudio(audio, { analysed })
    }
    recording.current = current
    recorder.start(250) // small chunks, so stopping never loses the last part
    setAnalyser(node)
    setSeconds(0)
    setStatus('recording')
  }, [release, stop])

  // Esc cancels; leaving the page stops the microphone
  useEffect(() => {
    if (status !== 'recording') return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') stop(true)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [status, stop])

  useEffect(
    () => () => {
      const current = recording.current
      if (!current) return
      current.discard = true
      if (current.recorder.state !== 'inactive') current.recorder.stop()
      current.stream.getTracks().forEach((track) => track.stop())
    },
    [],
  )

  return {
    status,
    seconds,
    analyser,
    start,
    finish: useCallback(() => stop(false), [stop]),
    cancel: useCallback(() => stop(true), [stop]),
  }
}
