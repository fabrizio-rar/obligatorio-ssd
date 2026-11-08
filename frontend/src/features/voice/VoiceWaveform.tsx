import { useEffect, useRef } from 'react'

import { cn } from '@/lib/utils'

const GAIN = 3 // normal speech barely moves the raw signal: amplify it so the bars are visible
const SILENCE_RMS = 0.012 // below this the mic is not picking up a voice
const SILENCE_MS = 1500 // how long without sound before warning
const SAMPLE_EVERY_MS = 40 // one bar every 40 ms (~2-3 s of history across the bar)
const BAR_STEP = 3 // px per bar (2 px bar + 1 px gap)

/**
 * Live level line of the microphone, like a voice recorder: a scrolling history of the last
 * seconds. Silence is a flat line; speech grows bars that move to the left, so it is obvious
 * whether audio is arriving. Reports long silences and the first sound to the parent.
 */
export function VoiceWaveform({
  analyser,
  onSilenceChange,
  onSound,
  className,
}: {
  analyser: AnalyserNode
  onSilenceChange: (silent: boolean) => void
  onSound: () => void
  className?: string
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas?.getContext('2d')
    if (!canvas || !ctx) return
    const samples = new Uint8Array(analyser.fftSize)
    const color = getComputedStyle(canvas).color // currentColor: follows the theme
    const levels: number[] = []
    let lastSample = 0
    let lastSound = performance.now()
    let silent = false
    let heard = false
    let frame = 0

    const draw = (now: number) => {
      const ratio = window.devicePixelRatio || 1
      const width = canvas.clientWidth
      const height = canvas.clientHeight
      if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
        canvas.width = Math.round(width * ratio)
        canvas.height = Math.round(height * ratio)
      }
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0)

      if (now - lastSample >= SAMPLE_EVERY_MS) {
        lastSample = now
        analyser.getByteTimeDomainData(samples)
        let energy = 0
        let peak = 0
        for (const sample of samples) {
          const value = (sample - 128) / 128
          energy += value * value
          peak = Math.max(peak, Math.abs(value))
        }
        if (Math.sqrt(energy / samples.length) > SILENCE_RMS) {
          lastSound = now
          if (!heard) {
            heard = true
            onSound()
          }
        }
        levels.push(Math.min(1, peak * GAIN))
        const maxBars = Math.max(1, Math.floor(width / BAR_STEP))
        if (levels.length > maxBars) levels.splice(0, levels.length - maxBars)
      }
      const isSilent = now - lastSound > SILENCE_MS
      if (isSilent !== silent) {
        silent = isSilent
        onSilenceChange(isSilent)
      }

      // Newest bar on the right; empty history = the flat line
      const middle = height / 2
      ctx.clearRect(0, 0, width, height)
      ctx.fillStyle = color
      ctx.globalAlpha = 0.25
      ctx.fillRect(0, middle - 0.5, width, 1)
      ctx.globalAlpha = 1
      for (let i = 0; i < levels.length; i++) {
        const x = width - (levels.length - i) * BAR_STEP
        const half = Math.max(0.75, levels[i] * (middle - 1))
        ctx.beginPath()
        ctx.roundRect(x, middle - half, BAR_STEP - 1, half * 2, 1)
        ctx.fill()
      }
      frame = requestAnimationFrame(draw)
    }

    frame = requestAnimationFrame(draw)
    return () => {
      cancelAnimationFrame(frame)
      onSilenceChange(false)
    }
  }, [analyser, onSilenceChange, onSound])

  return <canvas ref={canvasRef} aria-hidden className={cn('h-8 w-full text-primary', className)} />
}
