/** Thin fetch wrapper. Backend errors have the shape {"ok": false, "error": {code, message, details}}. */
import { getSession, setSession } from '@/lib/session'

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
  const session = getSession()
  // FormData (audio upload): the browser sets the multipart Content-Type with its boundary
  const isForm = init.body instanceof FormData
  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      ...init,
      headers: {
        ...(isForm ? {} : { 'Content-Type': 'application/json' }),
        ...(session ? { Authorization: `Bearer ${session.token}` } : {}),
        ...init.headers,
      },
    })
  } catch {
    throw new ApiError(0, 'NETWORK', 'No se pudo conectar con el servidor. ¿Está levantado el backend?')
  }

  if (!response.ok) {
    // Expired or revoked token: drop the session so the UI asks to log in again.
    // (A wrong password on /auth/login is also a 401, but it is sent without a session.)
    // Only if it is still the same session: a late 401 must not log out a newer login.
    if (response.status === 401 && session && getSession()?.token === session.token) setSession(null)
    const body = (await response.json().catch(() => ({}))) as ErrorBody
    throw new ApiError(
      response.status,
      body.error?.code ?? 'UNKNOWN',
      body.error?.message ?? `Error inesperado (${response.status})`,
      body.error?.details,
    )
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}
