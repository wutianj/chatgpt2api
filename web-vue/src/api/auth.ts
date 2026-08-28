import apiClient, { clearAuthToken, getAuthToken, setAuthToken } from './client'

export type AuthRole = 'admin' | 'user' | 'unknown'
export type AuthCapability = 'admin_console' | 'studio'

export interface AuthSubject {
  id: string
  name: string
  role: AuthRole
}

export interface AuthCapabilities {
  admin_console: boolean
  studio: boolean
}

export interface AuthView {
  schema_version: 1
  authenticated: boolean
  version: string
  subject: AuthSubject | null
  capabilities: AuthCapabilities
  home_route: '/login' | '/' | '/admin' | '/studio'
}

export interface UserLoginRequest {
  email: string
  password: string
}

export interface UserRegisterRequest extends UserLoginRequest {
  display_name?: string
}

export interface RegisteredUser {
  id: string
  email: string
  display_name: string
  role: AuthRole
  enabled: boolean
  created_at: string
  last_login_at: string | null
}

export interface UserSessionResponse {
  authenticated: true
  access_token: string
  user: RegisteredUser
}

export const authApi = {
  async loginUser(data: UserLoginRequest) {
    const session = await apiClient.post<UserLoginRequest, UserSessionResponse>('/api/auth/login', data)
    setAuthToken(session.access_token)
    return session
  },

  async register(data: UserRegisterRequest) {
    const session = await apiClient.post<UserRegisterRequest, UserSessionResponse>('/api/auth/register', data)
    setAuthToken(session.access_token)
    return session
  },

  logout: async () => {
    const token = getAuthToken()
    try {
      if (token) await apiClient.post('/api/auth/logout')
    } finally {
      clearAuthToken()
    }
    return { ok: true }
  },

  checkAuth: () => apiClient.get<never, AuthView>('/auth/status', { timeout: 8000 }),
}
