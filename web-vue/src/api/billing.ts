import apiClient from './client'

export interface WalletLedgerItem {
  id: string
  entry_type: string
  amount_units: number
  balance_after: number
  reference_type: string | null
  reference_id: string | null
  created_at: string | null
}

export interface WalletView {
  balance_units: number
  ledger: WalletLedgerItem[]
}

export interface Plan {
  id: string
  name: string
  price_units: number
  credits_units: number
  validity_days: number
  enabled?: boolean
}

export interface Pricing {
  chat_cost_units: number
  image_cost_units: number
  image_1k_cost_units: number
  image_2k_cost_units: number
  image_4k_cost_units: number
  image_4k_enabled: boolean
  search_cost_units: number
  file_cost_units: number
}

export type OrderStatus = 'created' | 'pending' | 'paid' | 'failed' | 'refunded' | 'expired'

export interface Order {
  id: string
  user_id: string | null
  user_email: string | null
  plan_id: string
  plan_name: string
  amount_units: number
  credits_units: number
  status: OrderStatus
  provider: string
  provider_order_id: string | null
  checkout_url: string | null
  created_at: string | null
  updated_at: string | null
  paid_at: string | null
  refunded_at: string | null
  expires_at: string | null
}

export const billingApi = {
  wallet: (limit = 50) => apiClient.get<never, WalletView>('/api/wallet', { params: { limit } }),
  plans: () => apiClient.get<never, { items: Plan[] }>('/api/plans'),
  pricing: () => apiClient.get<never, Pricing>('/api/pricing'),
  redeem: (code: string) => apiClient.post<{ code: string }, { plan: Plan; balance_units: number }>('/api/redeem', { code }),
  orders: (status?: OrderStatus) => apiClient.get<never, { items: Order[] }>('/api/orders', { params: status ? { status } : undefined }),
  createOrder: (planId: string, idempotencyKey: string) => apiClient.post<{ plan_id: string; provider: string }, Order>('/api/orders', { plan_id: planId, provider: 'manual' }, { headers: { 'Idempotency-Key': idempotencyKey } }),
}

export function formatCredits(units: number) {
  return `${Math.max(0, Number(units) || 0).toLocaleString('zh-CN')} 点`
}

export function formatLedgerAmount(units: number) {
  const value = Number(units) || 0
  return `${value > 0 ? '+' : ''}${value.toLocaleString('zh-CN')} 点`
}

export function formatPrice(units: number) {
  return `¥${(Math.max(0, Number(units) || 0) / 100).toFixed(2)}`
}
