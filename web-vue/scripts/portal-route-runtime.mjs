import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const routes = await readFile(path.join(root, 'src', 'router', 'routes.ts'), 'utf8')
const auth = await readFile(path.join(root, 'src', 'api', 'auth.ts'), 'utf8')
const shell = await readFile(path.join(root, 'src', 'layouts', 'AppShell.vue'), 'utf8')

const requiredRoutes = ['/chat', '/image', '/canvas', '/tasks', '/account', '/wallet', '/admin']
for (const route of requiredRoutes) {
  const sourcePath = route === '/admin' ? route : route.slice(1)
  if (!routes.includes(`path: '${sourcePath}'`)) throw new Error(`Missing portal route: ${route}`)
}
for (const route of ['/admin/accounts', '/admin/settings', '/admin/proxy', '/admin/logs', '/admin/audit']) {
  if (!shell.includes(`path: '${route}'`)) throw new Error(`Missing admin navigation route: ${route}`)
}
if (!auth.includes("'/api/auth/login'")) throw new Error('User login API is not wired')
if (!auth.includes("'/api/auth/register'")) throw new Error('User registration API is not wired')
if (!shell.includes("path: '/admin/audit'")) throw new Error('Admin audit navigation route is not wired')
if (!routes.includes("redirect: '/admin'")) throw new Error('Admin compatibility redirect is not wired')
if (!shell.includes('v-if="authStore.isAdmin"') || !shell.includes("label: '版本更新'")) {
  throw new Error('Admin-only update entry is not guarded')
}

console.log(`portal route contract passed (${requiredRoutes.length} user/admin routes)`)
