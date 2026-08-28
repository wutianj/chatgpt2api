<template>
  <div class="space-y-5">
    <div>
      <p class="text-xs uppercase tracking-[0.22em] text-muted-foreground">WALLET</p>
      <h1 class="mt-2 text-3xl font-semibold text-foreground">余额与套餐</h1>
      <p class="mt-2 text-sm text-muted-foreground">额度、订单和兑换记录统一在这里管理。</p>
    </div>

    <div class="grid gap-5 lg:grid-cols-[0.8fr_1.2fr]">
      <PagePanel class="!rounded-xl">
        <p class="text-xs uppercase tracking-[0.18em] text-muted-foreground">当前余额</p>
        <p class="mt-4 text-4xl font-semibold tabular-nums text-foreground">{{ formatCredits(wallet?.balance_units || 0) }}</p>
        <div class="mt-8 border-t border-border pt-5">
          <label for="redeem-code" class="text-sm font-medium text-foreground">兑换码</label>
          <div class="mt-2 flex gap-2">
            <Input id="redeem-code" v-model="code" block placeholder="输入兑换码" :disabled="redeeming" />
            <Button size="sm" variant="primary" :disabled="redeeming || !code.trim()" @click="redeem">
              {{ redeeming ? '兑换中...' : '兑换' }}
            </Button>
          </div>
        </div>
      </PagePanel>

      <PagePanel class="!rounded-xl">
        <PanelHeader title="额度套餐" align="start" />
        <div v-if="plans.length" class="mt-4 grid gap-3 sm:grid-cols-3">
          <div v-for="plan in plans" :key="plan.id" class="border border-border p-4">
            <p class="text-sm font-semibold text-foreground">{{ plan.name }}</p>
            <p class="mt-4 text-2xl font-semibold text-foreground">{{ formatPrice(plan.price_units) }}</p>
            <p class="mt-1 text-xs text-muted-foreground">{{ formatCredits(plan.credits_units) }}</p>
            <Button
              size="sm"
              variant="outline"
              block
              class="mt-4"
              :disabled="creatingOrderId === plan.id"
              @click="createOrder(plan.id)"
            >
              {{ creatingOrderId === plan.id ? '创建中...' : '创建订单' }}
            </Button>
          </div>
        </div>
        <StateBlock v-else compact dashed title="套餐加载中" />
      </PagePanel>
    </div>

    <PagePanel class="!rounded-xl">
      <PanelHeader title="我的订单" align="start">
        <template #actions>
          <Button size="sm" variant="outline" :disabled="loadingOrders" @click="loadOrders">刷新</Button>
        </template>
      </PanelHeader>
      <PageLoadingState v-if="loadingOrders" class="mt-4" title="正在读取订单" compact />
      <StateBlock v-else-if="!orders.length" class="mt-4" compact dashed title="暂无订单" description="创建订单后，管理员会在确认收款后为你到账。" />
      <div v-else class="mt-3 divide-y divide-border">
        <div v-for="order in orders" :key="order.id" class="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div class="min-w-0">
            <p class="truncate text-sm font-medium text-foreground">{{ order.plan_name }} · {{ formatPrice(order.amount_units) }}</p>
            <p class="mt-1 text-xs text-muted-foreground">{{ order.id }} · {{ formatDate(order.created_at) }}</p>
          </div>
          <span class="shrink-0 text-xs" :class="orderStatusClass(order.status)">{{ orderStatusLabel(order.status) }}</span>
        </div>
      </div>
    </PagePanel>

    <PagePanel class="!rounded-xl">
      <PanelHeader title="当前计费" align="start" />
      <div v-if="pricing" class="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <div v-for="item in pricingItems" :key="item.label" class="border border-border p-4">
          <p class="text-xs text-muted-foreground">{{ item.label }}</p>
          <p v-if="item.available" class="mt-2 text-lg font-semibold text-foreground">{{ formatCredits(item.cost) }} / 次</p>
          <p v-else class="mt-2 text-lg font-semibold text-muted-foreground">暂不支持</p>
        </div>
      </div>
      <StateBlock v-else compact dashed title="计费规则加载中" />
    </PagePanel>

    <PagePanel class="!rounded-xl">
      <PanelHeader title="余额流水" align="start" />
      <StateBlock v-if="!wallet?.ledger.length" compact dashed title="暂无流水" description="兑换或充值后会显示在这里。" />
      <div v-else class="mt-2 divide-y divide-border">
        <div v-for="item in wallet.ledger" :key="item.id" class="flex items-center justify-between gap-4 py-3">
          <div>
            <p class="text-sm text-foreground">{{ ledgerLabel(item.entry_type) }}</p>
            <p class="mt-1 text-xs text-muted-foreground">{{ formatDate(item.created_at) }}</p>
          </div>
          <div class="text-right">
            <p class="text-sm font-semibold tabular-nums" :class="item.amount_units >= 0 ? 'text-emerald-600' : 'text-foreground'">
              {{ formatLedgerAmount(item.amount_units) }}
            </p>
            <p class="mt-1 text-xs text-muted-foreground">余额 {{ formatCredits(item.balance_after) }}</p>
          </div>
        </div>
      </div>
    </PagePanel>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Button, Input } from 'nanocat-ui'
import PageLoadingState from '@/components/ai/PageLoadingState.vue'
import PagePanel from '@/components/ai/PagePanel.vue'
import PanelHeader from '@/components/ai/PanelHeader.vue'
import StateBlock from '@/components/ai/StateBlock.vue'
import { billingApi, formatCredits, formatLedgerAmount, formatPrice, type Order, type Pricing, type Plan, type WalletView } from '@/api/billing'
import { useToast } from '@/composables/useToast'

const toast = useToast()
const wallet = ref<WalletView | null>(null)
const plans = ref<Plan[]>([])
const pricing = ref<Pricing | null>(null)
const orders = ref<Order[]>([])
const code = ref('')
const redeeming = ref(false)
const creatingOrderId = ref('')
const loadingOrders = ref(false)

const pricingItems = computed(() => pricing.value ? [
  { label: '对话', cost: pricing.value.chat_cost_units, available: true },
  { label: '生图 1K', cost: pricing.value.image_1k_cost_units, available: true },
  { label: '生图 2K', cost: pricing.value.image_2k_cost_units, available: true },
  { label: '生图 4K', cost: pricing.value.image_4k_cost_units, available: pricing.value.image_4k_enabled },
  { label: '搜索', cost: pricing.value.search_cost_units, available: true },
  { label: '文件任务', cost: pricing.value.file_cost_units, available: true },
] : [])

function idempotencyKey(planId: string) {
  const random = typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`
  return `portal-order:${planId}:${random}`
}

async function loadOrders() {
  loadingOrders.value = true
  try { orders.value = (await billingApi.orders()).items } catch (error: any) { toast.error(error.message || '订单加载失败') } finally { loadingOrders.value = false }
}

async function load() {
  try {
    const [walletResult, planResult, pricingResult] = await Promise.all([billingApi.wallet(), billingApi.plans(), billingApi.pricing()])
    wallet.value = walletResult
    plans.value = planResult.items
    pricing.value = pricingResult
    await loadOrders()
  } catch (error: any) { toast.error(error.message || '钱包数据加载失败') }
}

async function createOrder(planId: string) {
  creatingOrderId.value = planId
  try {
    const order = await billingApi.createOrder(planId, idempotencyKey(planId))
    orders.value = [order, ...orders.value.filter(item => item.id !== order.id)]
    toast.success('订单已创建，等待管理员确认')
  } catch (error: any) { toast.error(error.message || '订单创建失败') } finally { creatingOrderId.value = '' }
}

async function redeem() {
  redeeming.value = true
  try { const result = await billingApi.redeem(code.value); toast.success(`${result.plan.name}已到账`); code.value = ''; await load() }
  catch (error: any) { toast.error(error.message || '兑换失败') }
  finally { redeeming.value = false }
}

function ledgerLabel(type: string) {
  return type === 'redeem' ? '兑换码到账' : type === 'credit' || type === 'admin_credit' ? '余额充值' : type === 'order_credit' ? '订单到账' : type === 'order_refund' ? '订单退款' : type === 'refund' ? '调用退款' : type
}
function orderStatusLabel(status: Order['status']) { return ({ created: '待处理', pending: '待支付', paid: '已到账', failed: '已失败', refunded: '已退款', expired: '已过期' })[status] }
function orderStatusClass(status: Order['status']) { return status === 'paid' ? 'text-emerald-600' : status === 'failed' || status === 'expired' ? 'text-muted-foreground' : status === 'refunded' ? 'text-amber-600' : 'text-foreground' }
function formatDate(value: string | null) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '--' }

onMounted(load)
</script>
