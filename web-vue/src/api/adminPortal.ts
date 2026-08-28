import apiClient from './client'
import type { Order, Plan, Pricing } from './billing'

export type PricingUpdate = Omit<Pricing, 'image_cost_units'>

export interface AdminUser {
  id: string
  email: string
  display_name: string
  role: string
  enabled: boolean
  balance_units: number
  usage_count: number
  last_used_at: string | null
  created_at: string
  last_login_at: string | null
}

export interface AuditLogItem {
  id: string
  actor_id: string
  actor_role: string
  action: string
  target_type: string
  target_id: string | null
  metadata: Record<string, unknown>
  created_at: string | null
}

export const adminPortalApi = {
  users: (limit = 200) => apiClient.get<never, { items: AdminUser[] }>('/api/admin/users', { params: { limit } }),
  creditUser: (userId: string, amountUnits: number, note: string) => apiClient.post<{ amount_units: number; note: string }, AdminUser>(`/api/admin/users/${encodeURIComponent(userId)}/credit`, { amount_units: amountUnits, note }),
  setUserEnabled: (userId: string, enabled: boolean) => apiClient.post<{ enabled: boolean }, AdminUser>(`/api/admin/users/${encodeURIComponent(userId)}/enabled`, { enabled }),
  plans: () => apiClient.get<never, { items: Plan[] }>('/api/plans'),
  adminPlans: () => apiClient.get<never, { items: Plan[] }>('/api/admin/plans'),
  updatePlan: (plan: Plan) => apiClient.put<Plan, Plan>(`/api/admin/plans/${encodeURIComponent(plan.id)}`, plan),
  pricing: () => apiClient.get<never, Pricing>('/api/admin/pricing'),
  updatePricing: (pricing: PricingUpdate) => apiClient.put<PricingUpdate, Pricing>('/api/admin/pricing', pricing),
  createRedeemCodes: (planId: string, count: number, creditsUnits?: number) => apiClient.post<{ plan_id: string; count: number; credits_units?: number }, { plan_id: string; codes: string[] }>('/api/admin/redeem-codes', { plan_id: planId, count, ...(creditsUnits === undefined ? {} : { credits_units: creditsUnits }) }),
  disableRedeemCode: (code: string) => apiClient.post<{ code: string }, { id: string; status: string }>('/api/admin/redeem-codes/disable', { code }),
  orders: (status?: string, keyword = '') => apiClient.get<never, { items: Order[] }>('/api/admin/orders', { params: { status: status || undefined, keyword: keyword || undefined } }),
  updateOrderStatus: (orderId: string, status: 'paid' | 'failed' | 'refunded') => apiClient.post<{ status: string }, Order>(`/api/admin/orders/${encodeURIComponent(orderId)}/status`, { status }),
  audit: (action?: string) => apiClient.get<never, { items: AuditLogItem[] }>('/api/admin/audit', { params: { action: action || undefined } }),
}
