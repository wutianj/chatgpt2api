<template>
  <div class="space-y-5">
    <div class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <p class="text-xs uppercase tracking-[0.22em] text-muted-foreground">ADMIN · ORDERS</p>
        <h1 class="mt-2 text-3xl font-semibold text-foreground">订单与兑换码</h1>
        <p class="mt-2 text-sm text-muted-foreground">订单状态只能由支付回调或管理员操作推进，所有动作都会记录审计。</p>
      </div>
      <Button size="sm" variant="outline" :disabled="loadingOrders" @click="loadOrders">刷新订单</Button>
    </div>

    <div class="grid gap-5 lg:grid-cols-[minmax(0,0.75fr)_minmax(0,1.25fr)]">
      <PagePanel class="!rounded-xl">
        <PanelHeader title="生成兑换码" align="start" />
        <div class="mt-5 space-y-4">
          <label class="block text-sm font-medium text-foreground">
            选择套餐
            <select v-model="selectedPlan" class="mt-2 block h-10 w-full border border-border bg-background px-3 text-sm text-foreground">
              <option v-for="plan in plans" :key="plan.id" :value="plan.id">{{ plan.name }} · {{ formatCredits(plan.credits_units) }}</option>
            </select>
          </label>
          <label class="block text-sm font-medium text-foreground">
            生成数量
            <Input v-model="count" type="number" min="1" max="50" size="md" block class="mt-2" />
          </label>
          <Button size="md" variant="primary" block :disabled="creating || !selectedPlan" @click="createCodes">
            {{ creating ? '生成中...' : '生成兑换码' }}
          </Button>
          <div class="border-t border-border pt-4">
            <label for="disable-code" class="block text-sm font-medium text-foreground">禁用未使用兑换码</label>
            <div class="mt-2 flex gap-2">
              <Input id="disable-code" v-model="disableCode" block placeholder="输入需要撤销的兑换码" :disabled="disabling" />
              <Button size="sm" variant="outline" :disabled="disabling || !disableCode.trim()" @click="disableRedeemCode">禁用</Button>
            </div>
          </div>
        </div>
      </PagePanel>

      <PagePanel class="!rounded-xl">
        <PanelHeader title="本次生成结果" align="start" />
        <StateBlock v-if="!codes.length" class="mt-4" compact dashed title="暂时没有新兑换码" description="生成后只在这里显示一次，请及时保存。" />
        <div v-else class="mt-4 space-y-2">
          <code v-for="code in codes" :key="code" class="block break-all border border-border bg-muted/40 px-3 py-2 text-sm text-foreground">{{ code }}</code>
          <Button size="sm" variant="outline" @click="copyCodes">复制全部</Button>
        </div>
      </PagePanel>
    </div>

    <PagePanel class="!rounded-xl">
      <div class="flex flex-col gap-3 border-b border-border pb-4 sm:flex-row sm:items-center">
        <PanelHeader title="用户订单" align="start" class="min-w-0 flex-1" />
        <div class="flex flex-wrap gap-2">
          <Input v-model="keyword" size="sm" placeholder="订单号 / 邮箱" class="w-44" @keyup.enter="loadOrders" />
          <select v-model="statusFilter" class="h-9 border border-border bg-background px-2 text-xs text-foreground" @change="loadOrders">
            <option value="">全部状态</option>
            <option value="pending">待处理</option>
            <option value="paid">已到账</option>
            <option value="failed">已失败</option>
            <option value="refunded">已退款</option>
            <option value="expired">已过期</option>
          </select>
        </div>
      </div>
      <PageLoadingState v-if="loadingOrders" class="mt-4" title="正在读取订单" compact />
      <StateBlock v-else-if="!orders.length" class="mt-4" compact dashed title="暂无匹配订单" description="用户创建订单后会显示在这里。" />
      <div v-else class="mt-2 divide-y divide-border">
        <div v-for="order in orders" :key="order.id" class="flex flex-col gap-3 py-4 xl:flex-row xl:items-center xl:justify-between">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <p class="text-sm font-semibold text-foreground">{{ order.plan_name }} · {{ formatPrice(order.amount_units) }}</p>
              <span class="text-xs" :class="orderStatusClass(order.status)">{{ orderStatusLabel(order.status) }}</span>
            </div>
            <p class="mt-1 break-all text-xs text-muted-foreground">{{ order.id }} · {{ order.user_email || order.user_id }} · {{ formatDate(order.created_at) }}</p>
          </div>
          <div class="flex shrink-0 flex-wrap gap-2">
            <Button v-if="order.status === 'pending'" size="sm" variant="primary" :disabled="busyId === order.id" @click="changeStatus(order, 'paid')">确认到账</Button>
            <Button v-if="order.status === 'pending'" size="sm" variant="outline" :disabled="busyId === order.id" @click="changeStatus(order, 'failed')">标记失败</Button>
            <Button v-if="order.status === 'paid'" size="sm" variant="outline" :disabled="busyId === order.id" @click="changeStatus(order, 'refunded')">退款并扣回额度</Button>
          </div>
        </div>
      </div>
    </PagePanel>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Button, Input } from 'nanocat-ui'
import PageLoadingState from '@/components/ai/PageLoadingState.vue'
import PagePanel from '@/components/ai/PagePanel.vue'
import PanelHeader from '@/components/ai/PanelHeader.vue'
import StateBlock from '@/components/ai/StateBlock.vue'
import { adminPortalApi } from '@/api/adminPortal'
import { billingApi, formatCredits, formatPrice, type Order, type OrderStatus, type Plan } from '@/api/billing'
import { useToast } from '@/composables/useToast'

const toast = useToast()
const plans = ref<Plan[]>([])
const selectedPlan = ref('')
const count = ref('1')
const codes = ref<string[]>([])
const disableCode = ref('')
const creating = ref(false)
const disabling = ref(false)
const orders = ref<Order[]>([])
const loadingOrders = ref(false)
const busyId = ref('')
const keyword = ref('')
const statusFilter = ref('')

async function loadPlans() {
  try { plans.value = (await billingApi.plans()).items; selectedPlan.value = plans.value[0]?.id || '' }
  catch (error: any) { toast.error(error.message || '套餐加载失败') }
}
async function loadOrders() {
  loadingOrders.value = true
  try { orders.value = (await adminPortalApi.orders(statusFilter.value, keyword.value.trim())).items }
  catch (error: any) { toast.error(error.message || '订单加载失败') }
  finally { loadingOrders.value = false }
}
async function createCodes() {
  creating.value = true
  codes.value = []
  try { const result = await adminPortalApi.createRedeemCodes(selectedPlan.value, Math.max(1, Math.min(50, Number(count.value) || 1))); codes.value = result.codes; toast.success(`已生成 ${result.codes.length} 个兑换码`) }
  catch (error: any) { toast.error(error.message || '生成失败') }
  finally { creating.value = false }
}
async function disableRedeemCode() {
  disabling.value = true
  try { await adminPortalApi.disableRedeemCode(disableCode.value.trim()); disableCode.value = ''; toast.success('兑换码已禁用') }
  catch (error: any) { toast.error(error.message || '兑换码禁用失败') }
  finally { disabling.value = false }
}
async function changeStatus(order: Order, nextStatus: 'paid' | 'failed' | 'refunded') {
  busyId.value = order.id
  try {
    const updated = await adminPortalApi.updateOrderStatus(order.id, nextStatus)
    orders.value = orders.value.map(item => item.id === order.id ? updated : item)
    toast.success(`订单已更新为${orderStatusLabel(updated.status)}`)
  } catch (error: any) { toast.error(error.message || '订单状态更新失败') }
  finally { busyId.value = '' }
}
async function copyCodes() { try { await navigator.clipboard.writeText(codes.value.join('\n')); toast.success('已复制') } catch { toast.error('复制失败，请手动保存') } }
function orderStatusLabel(status: OrderStatus) { return ({ created: '待处理', pending: '待支付', paid: '已到账', failed: '已失败', refunded: '已退款', expired: '已过期' })[status] }
function orderStatusClass(status: OrderStatus) { return status === 'paid' ? 'text-emerald-600' : status === 'failed' || status === 'expired' ? 'text-muted-foreground' : status === 'refunded' ? 'text-amber-600' : 'text-foreground' }
function formatDate(value: string | null) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '--' }

onMounted(() => { void loadPlans(); void loadOrders() })
</script>
