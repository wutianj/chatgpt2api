<template>
  <div class="space-y-5">
    <div class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <p class="text-xs uppercase tracking-[0.22em] text-muted-foreground">ADMIN · AUDIT</p>
        <h1 class="mt-2 text-3xl font-semibold text-foreground">操作审计</h1>
        <p class="mt-2 text-sm text-muted-foreground">记录余额、订单、兑换码和用户状态变更。</p>
      </div>
      <Button size="sm" variant="outline" :disabled="loading" @click="load">刷新</Button>
    </div>
    <PagePanel class="!rounded-xl">
      <PageLoadingState v-if="loading" title="正在读取审计记录" />
      <StateBlock v-else-if="errorMessage" title="审计记录读取失败" :description="errorMessage"><Button size="sm" variant="outline" root-class="mt-4" @click="load">重试</Button></StateBlock>
      <StateBlock v-else-if="!items.length" title="暂无审计记录" description="管理操作发生后会显示在这里。" />
      <div v-else class="divide-y divide-border">
        <div v-for="item in items" :key="item.id" class="flex flex-col gap-2 py-4 sm:flex-row sm:items-start sm:justify-between">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2"><span class="text-sm font-semibold text-foreground">{{ actionLabel(item.action) }}</span><span class="border border-border px-2 py-0.5 text-xs text-muted-foreground">{{ item.target_type }}</span></div>
            <p class="mt-1 break-all text-xs text-muted-foreground">{{ item.target_id || '--' }} · 操作者 {{ item.actor_id }}</p>
          </div>
          <time class="shrink-0 text-xs text-muted-foreground">{{ formatDate(item.created_at) }}</time>
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
import StateBlock from '@/components/ai/StateBlock.vue'
import { adminPortalApi, type AuditLogItem } from '@/api/adminPortal'

const items = ref<AuditLogItem[]>([])
const loading = ref(true)
const errorMessage = ref('')
async function load() { loading.value = true; errorMessage.value = ''; try { items.value = (await adminPortalApi.audit()).items } catch (error: any) { errorMessage.value = error.message || '暂时无法读取审计记录。' } finally { loading.value = false } }
function actionLabel(action: string) { return ({ user_credit: '用户余额增加', user_enabled: '用户启用', user_disabled: '用户禁用', redeem_codes_created: '生成兑换码', order_paid: '订单到账', order_failed: '订单失败', order_refunded: '订单退款' } as Record<string, string>)[action] || action }
function formatDate(value: string | null) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '--' }
onMounted(load)
</script>
