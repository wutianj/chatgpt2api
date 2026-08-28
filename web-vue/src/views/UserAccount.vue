<template>
  <div class="space-y-5">
    <div><p class="text-xs uppercase tracking-[0.22em] text-muted-foreground">ACCOUNT</p><h1 class="mt-2 text-3xl font-semibold text-foreground">账户设置</h1><p class="mt-2 text-sm text-muted-foreground">管理资料和用于 API 客户端的访问密钥。</p></div>
    <div class="grid gap-5 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
      <PagePanel class="!rounded-xl">
        <PanelHeader title="个人资料" align="start" />
        <div v-if="profile" class="mt-5 space-y-4"><div><p class="text-xs text-muted-foreground">显示名称</p><p class="mt-1 text-sm font-medium text-foreground">{{ profile.display_name }}</p></div><div><p class="text-xs text-muted-foreground">邮箱</p><p class="mt-1 break-all text-sm font-medium text-foreground">{{ profile.email }}</p></div><div><p class="text-xs text-muted-foreground">注册时间</p><p class="mt-1 text-sm text-foreground">{{ formatDate(profile.created_at) }}</p></div></div>
        <StateBlock v-else-if="errorMessage" class="mt-4" title="资料读取失败" :description="errorMessage" />
        <PageLoadingState v-else title="正在加载资料" />
      </PagePanel>
      <PagePanel class="!rounded-xl">
        <PanelHeader title="我的 API Key" align="start"><template #actions><Button size="sm" variant="primary" :disabled="creating" @click="createKey">{{ creating ? '创建中...' : '新建 Key' }}</Button></template></PanelHeader>
        <div v-if="newRawKey" class="mt-4 border border-amber-300/70 bg-amber-50 p-4 text-sm text-amber-900"><p class="font-semibold">请立即保存这个 Key</p><p class="mt-1 text-xs">页面不会再次显示完整值。</p><code class="mt-3 block break-all border border-amber-300/70 bg-white p-3 text-xs">{{ newRawKey }}</code><Button size="sm" variant="outline" root-class="mt-3" @click="copyKey">复制 Key</Button></div>
        <StateBlock v-if="!keys.length && !errorMessage" class="mt-4" compact dashed title="还没有 API Key" description="为桌面客户端或自己的应用创建一个。" />
        <div v-else class="mt-4 divide-y divide-border"><div v-for="item in keys" :key="item.id" class="flex items-center justify-between gap-4 py-3"><div class="min-w-0"><p class="truncate text-sm font-medium text-foreground">{{ item.name }}</p><p class="mt-1 text-xs text-muted-foreground">创建于 {{ formatDate(item.created_at) }} · {{ item.enabled ? '启用中' : '已撤销' }}</p></div><Button v-if="item.enabled" size="sm" variant="outline" :disabled="busyId === item.id" @click="revokeKey(item.id)">{{ busyId === item.id ? '处理中...' : '撤销' }}</Button></div></div>
      </PagePanel>
    </div>
    <UserApiDocs :revealed-key="newRawKey" />
    <PagePanel class="!rounded-xl">
      <PanelHeader title="最近用量" align="start" />
      <StateBlock v-if="!usage.length" class="mt-4" compact dashed title="暂无用量记录" description="完成一次对话或生图后会显示预扣和结算状态。" />
      <div v-else class="mt-2 divide-y divide-border">
        <div v-for="item in usage" :key="item.id" class="flex flex-col gap-1 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div><p class="text-sm text-foreground">{{ item.model || item.endpoint || item.reference_type }}</p><p class="mt-1 text-xs text-muted-foreground">{{ item.reference_id }} · {{ formatDateTime(item.created_at) }}</p></div>
          <div class="text-xs" :class="item.status === 'completed' ? 'text-emerald-600' : item.status === 'refunded' ? 'text-amber-600' : 'text-muted-foreground'">{{ usageStatusLabel(item.status) }} · {{ formatCredits(item.amount_units) }}</div>
        </div>
      </div>
    </PagePanel>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Button } from 'nanocat-ui'
import PageLoadingState from '@/components/ai/PageLoadingState.vue'
import PagePanel from '@/components/ai/PagePanel.vue'
import PanelHeader from '@/components/ai/PanelHeader.vue'
import StateBlock from '@/components/ai/StateBlock.vue'
import UserApiDocs from '@/components/ai/UserApiDocs.vue'
import { userApi, type UserKey, type UserProfile, type UsageRecord } from '@/api/user'
import { formatCredits } from '@/api/billing'
import { useToast } from '@/composables/useToast'

const toast = useToast()
const profile = ref<UserProfile | null>(null)
const keys = ref<UserKey[]>([])
const newRawKey = ref('')
const creating = ref(false)
const busyId = ref('')
const errorMessage = ref('')
const usage = ref<UsageRecord[]>([])

function formatDate(value: string | null) { return value ? new Date(value).toLocaleDateString('zh-CN') : '--' }
function formatDateTime(value: string | null) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '--' }
function usageStatusLabel(status: UsageRecord['status']) { return ({ reserved: '预扣中', completed: '已结算', refunded: '已退回' })[status] }
async function load() { try { const [profileResult, keyResult, usageResult] = await Promise.all([userApi.profile(), userApi.listKeys(), userApi.usage(30)]); profile.value = profileResult.user; keys.value = keyResult.items; usage.value = usageResult.items } catch (error: any) { errorMessage.value = error.message || '暂时无法读取账户信息。' } }
async function createKey() { creating.value = true; newRawKey.value = ''; try { const result = await userApi.createKey('我的应用'); keys.value = [result.item, ...keys.value]; newRawKey.value = result.raw_key; toast.success('API Key 已创建') } catch (error: any) { toast.error(error.message || '创建失败') } finally { creating.value = false } }
async function revokeKey(keyId: string) { busyId.value = keyId; try { await userApi.revokeKey(keyId); keys.value = keys.value.map(item => item.id === keyId ? { ...item, enabled: false } : item); toast.success('API Key 已撤销') } catch (error: any) { toast.error(error.message || '撤销失败') } finally { busyId.value = '' } }
async function copyKey() { try { await navigator.clipboard.writeText(newRawKey.value); toast.success('已复制') } catch { toast.error('复制失败，请手动保存') } }
onMounted(load)
</script>
