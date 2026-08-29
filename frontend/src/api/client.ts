import { runtimeApiBaseUrl } from './runtimeConfig'

const configuredBase = runtimeApiBaseUrl || import.meta.env.VITE_API_BASE_URL?.trim()
const rawBase = configuredBase || (import.meta.env.PROD ? window.location.origin : 'http://localhost:8000')
export const API_BASE = rawBase.replace(/\/$/, '')
const TOKEN_KEY = 'thermasite:session'

export function getSessionToken() { return localStorage.getItem(TOKEN_KEY) }
export function setSessionToken(token: string) { localStorage.setItem(TOKEN_KEY, token) }
export function clearSessionToken() { localStorage.removeItem(TOKEN_KEY) }

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: 'omit',
    headers: {
      'Content-Type': 'application/json',
      ...(getSessionToken() ? { Authorization: `Bearer ${getSessionToken()}` } : {}),
      ...init?.headers,
    },
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    throw new ApiError(response.status, payload?.error?.message || payload?.detail || response.statusText)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export function artifactUrl(path?: string) {
  if (!path) return undefined
  return path.startsWith('http') ? path : `${API_BASE}${path}`
}
