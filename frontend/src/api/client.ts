/** Thin fetch wrapper. Backend errors have the shape {"ok": false, "error": {code, message, details}}. */

export class ApiError extends Error {
  readonly code: string
  readonly status: number
  readonly details: Record<string, unknown>

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }

  get retryable(): boolean {
    return this.details.retryable === true || this.status >= 500
  }
}

interface ErrorBody {
  error?: { code?: string; message?: string; details?: Record<string, unknown> }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init.headers },
    })
  } catch {
    throw new ApiError(0, 'NETWORK', 'No se pudo conectar con el servidor. ¿Está levantado el backend?')
  }

  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as ErrorBody
    throw new ApiError(
      response.status,
      body.error?.code ?? 'UNKNOWN',
      body.error?.message ?? `Error inesperado (${response.status})`,
      body.error?.details,
    )
  }
  return (await response.json()) as T
}
