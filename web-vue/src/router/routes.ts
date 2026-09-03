import type { RouteRecordRaw } from 'vue-router'

export const appRoutes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/Login.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/debug',
    redirect: { name: 'chat' },
    meta: { requiresAuth: true },
  },
  {
    path: '/',
    component: () => import('@/layouts/AppShell.vue'),
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        name: 'home',
        component: () => import('@/views/UserHome.vue'),
        meta: { requiresUser: true },
      },
      {
        path: 'chat',
        name: 'chat',
        component: () => import('@/views/Studio.vue'),
        meta: { requiresUser: true, workspace: true },
      },
      {
        path: 'image',
        name: 'image',
        component: () => import('@/views/Studio.vue'),
        meta: { requiresUser: true, workspace: true },
      },
      {
        path: 'canvas',
        name: 'canvas',
        component: () => import('@/views/UserCanvas.vue'),
        meta: { requiresUser: true, workspace: true },
      },
      {
        path: 'tasks',
        name: 'tasks',
        component: () => import('@/views/UserTasks.vue'),
        meta: { requiresUser: true },
      },
      {
        path: 'account',
        name: 'account',
        component: () => import('@/views/UserAccount.vue'),
        meta: { requiresUser: true },
      },
      {
        path: 'wallet',
        name: 'wallet',
        component: () => import('@/views/UserWallet.vue'),
        meta: { requiresUser: true },
      },
      {
        path: 'studio',
        redirect: { name: 'chat' },
      },
    ],
  },
  {
    path: '/admin',
    component: () => import('@/layouts/AppShell.vue'),
    meta: { requiresAuth: true, requiresAdmin: true },
    children: [
      {
        path: '',
        name: 'admin-dashboard',
        component: () => import('@/views/Dashboard.vue'),
        meta: { requiredCapability: 'admin_console' },
      },
      {
        path: 'accounts',
        name: 'accounts',
        component: () => import('@/views/Accounts.vue'),
        meta: { requiredCapability: 'admin_console', management: true },
      },
      {
        path: 'gemini-accounts',
        name: 'gemini-accounts',
        component: () => import('@/views/GeminiAccounts.vue'),
        meta: { requiredCapability: 'admin_console', management: true },
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/views/Settings.vue'),
        meta: { requiredCapability: 'admin_console' },
      },
      {
        path: 'proxy',
        name: 'proxy',
        component: () => import('@/views/Proxy.vue'),
        meta: { requiredCapability: 'admin_console' },
      },
      {
        path: 'logs',
        name: 'logs',
        component: () => import('@/views/Logs.vue'),
        meta: { requiredCapability: 'admin_console', management: true },
      },
      {
        path: 'monitor',
        name: 'monitor',
        component: () => import('@/views/Monitor.vue'),
        meta: { requiredCapability: 'admin_console' },
      },
      {
        path: 'gallery',
        name: 'gallery',
        component: () => import('@/views/Gallery.vue'),
        meta: { requiredCapability: 'admin_console', management: true },
      },
      {
        path: 'users',
        name: 'admin-users',
        component: () => import('@/views/AdminUsers.vue'),
        meta: { requiredCapability: 'admin_console', management: true },
      },
      {
        path: 'orders',
        name: 'admin-orders',
        component: () => import('@/views/AdminOrders.vue'),
        meta: { requiredCapability: 'admin_console' },
      },
      {
        path: 'audit',
        name: 'admin-audit',
        component: () => import('@/views/AdminAudit.vue'),
        meta: { requiredCapability: 'admin_console', management: true },
      },
    ],
  },
  { path: '/dashboard', redirect: '/admin' },
  { path: '/accounts', redirect: '/admin/accounts' },
  { path: '/gemini-accounts', redirect: '/admin/gemini-accounts' },
  { path: '/settings', redirect: '/admin/settings' },
  { path: '/proxy', redirect: '/admin/proxy' },
  { path: '/logs', redirect: '/admin/logs' },
  { path: '/monitor', redirect: '/admin/monitor' },
  { path: '/gallery', redirect: '/admin/gallery' },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/',
    meta: { requiresAuth: true },
  },
]

export function matchedRoutesRequireAuth(matched: readonly { meta: { requiresAuth?: boolean } }[]) {
  return matched.some(record => record.meta.requiresAuth !== false)
}

export function resolveLoginRedirect(value: unknown, fallback: string) {
  const candidate = Array.isArray(value) ? value[0] : value
  if (typeof candidate !== 'string') return fallback
  const target = candidate.trim()
  if (!target.startsWith('/') || target.startsWith('//')) return fallback
  if (target === '/login' || target.startsWith('/login?') || target.startsWith('/login#')) return fallback
  return target
}
