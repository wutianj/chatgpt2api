<template>
  <div class="space-y-5">
    <div class="flex flex-wrap items-end justify-between gap-3"><div><p class="text-xs uppercase tracking-[0.22em] text-muted-foreground">ADMIN · USERS</p><h1 class="mt-2 text-3xl font-semibold text-foreground">用户管理</h1><p class="mt-2 text-sm text-muted-foreground">查看注册用户状态和余额，所有调整都会进入余额流水。</p></div><Button size="sm" variant="outline" :disabled="loading" @click="load">刷新</Button></div>
    <PagePanel class="!rounded-xl">
      <PageLoadingState v-if="loading" title="正在读取用户" />
      <StateBlock v-else-if="errorMessage" title="用户读取失败" :description="errorMessage"><Button size="sm" variant="outline" root-class="mt-4" @click="load">重试</Button></StateBlock>
      <StateBlock v-else-if="!users.length" title="还没有注册用户" description="用户完成注册后会显示在这里。" />
      <div v-else class="overflow-x-auto"><table class="w-full min-w-[900px] text-left text-sm"><thead class="border-b border-border text-xs text-muted-foreground"><tr><th class="px-3 py-3 font-medium">用户</th><th class="px-3 py-3 font-medium">余额</th><th class="px-3 py-3 font-medium">最近调用</th><th class="px-3 py-3 font-medium">状态</th><th class="px-3 py-3 font-medium">操作</th></tr></thead><tbody class="divide-y divide-border"><tr v-for="user in users" :key="user.id"><td class="px-3 py-4"><p class="font-medium text-foreground">{{ user.display_name }}</p><p class="mt-1 text-xs text-muted-foreground">{{ user.email }}</p></td><td class="px-3 py-4 tabular-nums text-foreground">{{ formatCredits(user.balance_units) }}</td><td class="px-3 py-4 text-xs text-muted-foreground"><p>{{ user.usage_count }} 次</p><p class="mt-1">{{ formatDateTime(user.last_used_at) }}</p></td><td class="px-3 py-4 text-xs" :class="user.enabled ? 'text-emerald-600' : 'text-muted-foreground'">{{ user.enabled ? '启用' : '已禁用' }}</td><td class="px-3 py-4"><div class="flex items-center gap-2"><Input v-model="creditAmounts[user.id]" size="sm" class="w-28" placeholder="额度" /><Button size="sm" variant="outline" :disabled="busyId === user.id" @click="credit(user)">{{ busyId === user.id ? '...' : '加额度' }}</Button><Button size="sm" variant="outline" :disabled="busyId === user.id" @click="toggle(user)">{{ user.enabled ? '禁用' : '启用' }}</Button></div></td></tr></tbody></table></div>
    </PagePanel>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Button, Input } from 'nanocat-ui'
import PageLoadingState from '@/components/ai/PageLoadingState.vue'
import PagePanel from '@/components/ai/PagePanel.vue'
import StateBlock from '@/components/ai/StateBlock.vue'
import { adminPortalApi, type AdminUser } from '@/api/adminPortal'
import { formatCredits } from '@/api/billing'
import { useToast } from '@/composables/useToast'

const toast = useToast()
const users = ref<AdminUser[]>([])
const loading = ref(true)
const errorMessage = ref('')
const busyId = ref('')
const creditAmounts = reactive<Record<string, string>>({})

async function load() { loading.value = true; errorMessage.value = ''; try { users.value = (await adminPortalApi.users()).items } catch (error: any) { errorMessage.value = error.message || '暂时无法读取用户。' } finally { loading.value = false } }
async function credit(user: AdminUser) { const amount = Number(creditAmounts[user.id]); if (!Number.isInteger(amount) || amount <= 0) { toast.error('请输入正整数额度'); return }; busyId.value = user.id; try { const result = await adminPortalApi.creditUser(user.id, amount, '管理员充值'); Object.assign(user, result); creditAmounts[user.id] = ''; toast.success('额度已增加') } catch (error: any) { toast.error(error.message || '充值失败') } finally { busyId.value = '' } }
async function toggle(user: AdminUser) { busyId.value = user.id; try { const result = await adminPortalApi.setUserEnabled(user.id, !user.enabled); Object.assign(user, result); toast.success(result.enabled ? '用户已启用' : '用户已禁用') } catch (error: any) { toast.error(error.message || '状态更新失败') } finally { busyId.value = '' } }
function formatDateTime(value: string | null) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '暂无调用' }
onMounted(load)
</script>
