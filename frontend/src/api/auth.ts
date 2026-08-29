import { api, clearSessionToken, setSessionToken } from './client'

export interface AuthUser {
  id: string
  email: string
  name: string
  is_demo: boolean
}

interface AuthResponse { token: string; user: AuthUser }

function remember(response: AuthResponse) {
  setSessionToken(response.token)
  return response.user
}

export async function register(input: { name: string; email: string; password: string }) {
  return remember(await api<AuthResponse>('/api/v1/auth/register', { method: 'POST', body: JSON.stringify(input) }))
}

export async function login(input: { email: string; password: string }) {
  return remember(await api<AuthResponse>('/api/v1/auth/login', { method: 'POST', body: JSON.stringify(input) }))
}

export async function enterDemo() {
  return remember(await api<AuthResponse>('/api/v1/auth/demo', { method: 'POST' }))
}

export async function getMe() { return api<AuthUser>('/api/v1/auth/me') }

export async function logout() {
  try {
    await api<void>('/api/v1/auth/logout', { method: 'POST' })
  } finally {
    clearSessionToken()
  }
}
