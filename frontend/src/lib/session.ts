/**
 * Login session (token + username), kept in localStorage so a reload keeps the user logged in.
 * A tiny external store: React components read it with useSession(), the API client with getSession().
 */
import { useSyncExternalStore } from 'react'

export interface Session {
  token: string
  username: string
}

const STORAGE_KEY = 'mercanova.session'
const listeners = new Set<() => void>()
let current: Session | null = readStored()

function readStored(): Session | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    if (
      typeof parsed === 'object' &&
      parsed !== null &&
      'token' in parsed &&
      'username' in parsed &&
      typeof parsed.token === 'string' &&
      typeof parsed.username === 'string'
    ) {
      return { token: parsed.token, username: parsed.username }
    }
  } catch {
    // Storage blocked or corrupt value: start logged out
  }
  return null
}

export function getSession(): Session | null {
  return current
}

export function setSession(session: Session | null): void {
  current = session
  try {
    if (session) localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    // Storage blocked: the session still lives in memory until the page reloads
  }
  listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useSession(): Session | null {
  return useSyncExternalStore(subscribe, getSession)
}
