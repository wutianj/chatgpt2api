import apiClient from './client'

export interface UserProfile {
  id: string
  email: string
  display_name: string
  role: 'user' | 'admin' | 'unknown'
  enabled: boolean
  created_at: string
  last_login_at: string | null
}

export interface UserKey {
  id: string
  name: string
  role: 'user' | 'admin'
  enabled: boolean
  created_at: string | null
  last_used_at: string | null
}

export interface UsageRecord {
  id: string
  task_id: string | null
  reference_type: string
  reference_id: string
  endpoint: string | null
  model: string | null
  units: number
  amount_units: number
  status: 'reserved' | 'completed' | 'refunded'
  created_at: string | null
  updated_at: string | null
}

export const userApi = {
  profile: () => apiClient.get<never, { user: UserProfile }>('/api/user/profile'),
  listKeys: () => apiClient.get<never, { items: UserKey[] }>('/api/user/keys'),
  createKey: (name: string) => apiClient.post<{ name: string }, { item: UserKey; raw_key: string }>('/api/user/keys', { name }),
  revokeKey: (keyId: string) => apiClient.delete<never, { deleted_id: string }>(`/api/user/keys/${encodeURIComponent(keyId)}`),
  usage: (limit = 50) => apiClient.get<never, { items: UsageRecord[] }>('/api/user/usage', { params: { limit } }),
}
