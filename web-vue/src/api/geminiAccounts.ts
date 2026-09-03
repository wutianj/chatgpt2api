import apiClient from './client'

export interface GeminiAccount {
  id: string
  name: string
  email: string
  provider: 'gemini'
  auth_type: 'business_cookie' | 'oauth' | 'api_key' | 'service_account' | 'unknown'
  oauth_type: string | null
  tier_id: string | null
  project_id: string | null
  group_id: string
  proxy: string
  concurrency: number
  priority: number
  enabled: boolean
  status: string
  available: boolean
  inflight: number
  success_count: number
  failure_count: number
  cooldown_until: number | null
  cooldown_reason: string
  error_message: string
  created_at: number | null
  last_used_at: number | null
  last_test_at: number | null
  credentials_present: boolean
}

export interface GeminiAccountPayload {
  id?: string
  name?: string
  email?: string
  secure_c_ses?: string
  host_c_oses?: string
  csesidx?: string
  config_id?: string
  credentials?: Record<string, unknown>
  auth_type?: 'business_cookie' | 'oauth' | 'api_key' | 'service_account'
  oauth_type?: string
  tier_id?: string
  project_id?: string
  api_key?: string
  base_url?: string
  location?: string
  service_account_json?: Record<string, unknown> | string
  group_id?: string
  proxy?: string
  concurrency?: number
  priority?: number
  enabled?: boolean
}

export const geminiAccountsApi = {
  list: () => apiClient.get<never, { items: GeminiAccount[]; total: number }>('/api/gemini/accounts'),
  create: (payload: GeminiAccountPayload) => apiClient.post<GeminiAccountPayload, { item: GeminiAccount }>('/api/gemini/accounts', payload),
  import: (records: GeminiAccountPayload[]) => apiClient.post<{ records: GeminiAccountPayload[] }, { added: number; updated: number; failed: number; errors: Array<{ code: string; message: string }> }>('/api/gemini/accounts/import', { records }),
  update: (id: string, payload: Partial<GeminiAccountPayload>) => apiClient.patch<Partial<GeminiAccountPayload>, { item: GeminiAccount }>(`/api/gemini/accounts/${encodeURIComponent(id)}`, payload),
  toggle: (id: string, enabled: boolean) => apiClient.post<{ enabled: boolean }, { item: GeminiAccount }>(`/api/gemini/accounts/${encodeURIComponent(id)}/toggle`, { enabled }),
  test: (id: string) => apiClient.post<never, { status: 'success'; account_id: string; duration_ms: number; message: string }>(`/api/gemini/accounts/${encodeURIComponent(id)}/test`),
  remove: (id: string) => apiClient.delete<never, { deleted: boolean; id: string }>(`/api/gemini/accounts/${encodeURIComponent(id)}`),
  oauthCapabilities: () => apiClient.get<never, { oauth_types: string[]; account_types: string[]; manual_oauth: boolean; import_formats: string[] }>('/api/gemini/oauth/capabilities'),
  authorizeOAuth: (payload: { oauth_type: string; tier_id?: string; project_id?: string; proxy?: string }) => apiClient.post<typeof payload, { auth_url: string; session_id: string; state: string; redirect_uri: string }>('/api/gemini/oauth/authorize', payload),
  exchangeOAuth: (payload: { session_id: string; state: string; code: string; proxy?: string }) => apiClient.post<typeof payload, Record<string, unknown>>('/api/gemini/oauth/exchange', payload),
}
