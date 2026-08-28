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
            兑换码类型
            <select v-model="redeemMode" class="mt-2 block h-10 w-full border border-border bg-background px-3 text-sm text-foreground">
              <option value="plan">套餐兑换码</option>
              <option value="custom">自定义点数兑换码</option>
            </select>
          </label>
          <label v-if="redeemMode === 'plan'" class="block text-sm font-medium text-foreground">
            选择套餐
            <select v-model="selectedPlan" class="mt-2 block h-10 w-full border border-border bg-background px-3 text-sm text-foreground">
              <option v-for="plan in enabledPlans" :key="plan.id" :value="plan.id">{{ plan.name }} · {{ formatCredits(plan.credits_units) }}</option>
            </select>
          </label>
          <label v-else class="block text-sm font-medium text-foreground">
            自定义点数
            <Input v-model="customCredits" type="number" min="1" max="1000000000" size="md" block class="mt-2" />
            <span class="mt-1 block text-xs font-normal text-muted-foreground">兑换后直接增加到用户余额，可自由填写。</span>
          </label>
          <label class="block text-sm font-medium text-foreground">
            生成数量
            <Input v-model="count" type="number" min="1" max="50" size="md" block class="mt-2" />
          </label>
          <Button size="md" variant="primary" block :disabled="creating || !canCreateCodes" @click="createCodes">
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
    </div>

    <PagePanel class="!rounded-xl">
      <div class="flex flex-wrap items-end justify-between gap-3 border-b border-border pb-4">
        <PanelHeader title="套餐设置" align="start" />
        <span class="text-xs text-muted-foreground">修改只影响新订单，历史订单保留原金额</span>
      </div>
      <StateBlock v-if="!plans.length" class="mt-4" compact dashed title="暂无套餐" description="默认套餐会在首次读取时创建。" />
      <div v-else class="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <div v-for="plan in plans" :key="plan.id" class="border border-border p-4">
          <div class="flex items-center justify-between gap-3">
            <p class="text-xs uppercase tracking-[0.18em] text-muted-foreground">{{ plan.id }}</p>
            <label class="flex items-center gap-2 text-xs text-muted-foreground">
              <input v-model="plan.enabled" type="checkbox" class="h-4 w-4 accent-foreground" />
              上架
            </label>
          </div>
          <label class="mt-4 block text-sm font-medium text-foreground">
            套餐名称
            <Input v-model="plan.name" size="sm" block class="mt-2" />
          </label>
          <div class="mt-3 grid grid-cols-2 gap-3">
            <label class="block text-sm font-medium text-foreground">
              价格（分）
              <Input v-model="plan.price_units" type="number" min="1" size="sm" block class="mt-2" />
            </label>
            <label class="block text-sm font-medium text-foreground">
              额度（点）
              <Input v-model="plan.credits_units" type="number" min="1" size="sm" block class="mt-2" />
            </label>
          </div>
          <label class="mt-3 block text-sm font-medium text-foreground">
            有效期（天，0 为永久）
            <Input v-model="plan.validity_days" type="number" min="0" size="sm" block class="mt-2" />
          </label>
          <Button
            size="sm"
            variant="outline"
            block
            class="mt-4"
            :disabled="savingPlanId === plan.id"
            @click="savePlan(plan)"
          >
            {{ savingPlanId === plan.id ? '保存中...' : '保存套餐' }}
          </Button>
        </div>
      </div>
    </PagePanel>

    <PagePanel class="!rounded-xl">
      <div class="flex flex-wrap items-end justify-between gap-3 border-b border-border pb-4">
        <PanelHeader title="调用计费设置" align="start" />
        <span class="text-xs text-muted-foreground">1K、2K 生图按实际尺寸计费；4K 可配置但当前关闭</span>
      </div>
      <PageLoadingState v-if="!pricingDraft" class="mt-4" title="正在读取计费设置" compact />
      <div v-else class="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <label v-for="field in pricingFields" :key="field.key" class="block text-sm font-medium text-foreground">
          {{ field.label }}
          <Input v-model="pricingDraft[field.key]" type="number" min="1" size="sm" block class="mt-2" />
        </label>
        <label class="flex items-center gap-2 self-end pb-2 text-sm font-medium text-foreground">
          <input v-model="pricingDraft.image_4k_enabled" type="checkbox" class="h-4 w-4 accent-foreground" />
          开放 4K 生图
        </label>
        <div class="sm:col-span-2 xl:col-span-4">
          <Button size="sm" variant="primary" :disabled="savingPricing" @click="savePricing">
            {{ savingPricing ? '保存中...' : '保存计费设置' }}
          </Button>
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
import { computed, onMounted, ref } from 'vue'
import { Button, Input } from 'nanocat-ui'
import PageLoadingState from '@/components/ai/PageLoadingState.vue'
import PagePanel from '@/components/ai/PagePanel.vue'
import PanelHeader from '@/components/ai/PanelHeader.vue'
import StateBlock from '@/components/ai/StateBlock.vue'
import { adminPortalApi } from '@/api/adminPortal'
import { formatCredits, formatPrice, type Order, type OrderStatus, type Plan, type Pricing } from '@/api/billing'
import { useToast } from '@/composables/useToast'

const toast = useToast()
const plans = ref<Plan[]>([])
const pricingDraft = ref<Pricing | null>(null)
const selectedPlan = ref('')
const redeemMode = ref<'plan' | 'custom'>('plan')
const customCredits = ref('1000')
const count = ref('1')
const codes = ref<string[]>([])
const disableCode = ref('')
const creating = ref(false)
const disabling = ref(false)
const orders = ref<Order[]>([])
const loadingOrders = ref(false)
const busyId = ref('')
const savingPlanId = ref('')
const savingPricing = ref(false)
const keyword = ref('')
const statusFilter = ref('')
const enabledPlans = computed(() => plans.value.filter((plan) => plan.id !== 'custom' && plan.enabled !== false))
const canCreateCodes = computed(() => redeemMode.value === 'plan'
  ? Boolean(selectedPlan.value)
  : Number.isInteger(Number(customCredits.value)) && Number(customCredits.value) > 0 && Number(customCredits.value) <= 1_000_000_000)
const pricingFields = [
  { key: 'chat_cost_units', label: '对话（点 / 次）' },
  { key: 'image_1k_cost_units', label: '生图 1K（点 / 次）' },
  { key: 'image_2k_cost_units', label: '生图 2K（点 / 次）' },
  { key: 'image_4k_cost_units', label: '生图 4K（点 / 次）' },
  { key: 'search_cost_units', label: '搜索（点 / 次）' },
  { key: 'file_cost_units', label: '文件任务（点 / 次）' },
] as const

async function loadPlans() {
  try {
    plans.value = (await adminPortalApi.adminPlans()).items.map((plan) => ({ ...plan, enabled: plan.enabled !== false }))
    selectedPlan.value = enabledPlans.value[0]?.id || ''
  }
  catch (error: any) { toast.error(error.message || '套餐加载失败') }
}
async function loadPricing() {
  try { pricingDraft.value = await adminPortalApi.pricing() }
  catch (error: any) { toast.error(error.message || '计费设置加载失败') }
}
async function savePlan(plan: Plan) {
  savingPlanId.value = plan.id
  try {
    const updated = await adminPortalApi.updatePlan({
      ...plan,
      price_units: Math.max(1, Math.trunc(Number(plan.price_units) || 0)),
      credits_units: Math.max(1, Math.trunc(Number(plan.credits_units) || 0)),
      validity_days: Math.max(0, Math.trunc(Number(plan.validity_days) || 0)),
      enabled: plan.enabled !== false,
    })
    plans.value = plans.value.map((item) => item.id === updated.id ? updated : item)
    selectedPlan.value = enabledPlans.value.some((item) => item.id === selectedPlan.value) ? selectedPlan.value : (enabledPlans.value[0]?.id || '')
    toast.success('套餐设置已保存')
  } catch (error: any) { toast.error(error.message || '套餐保存失败') }
  finally { savingPlanId.value = '' }
}
async function savePricing() {
  if (!pricingDraft.value) return
  savingPricing.value = true
  try {
    const draft = pricingDraft.value
    pricingDraft.value = await adminPortalApi.updatePricing({
      chat_cost_units: Math.max(1, Math.trunc(Number(draft.chat_cost_units) || 0)),
      image_1k_cost_units: Math.max(1, Math.trunc(Number(draft.image_1k_cost_units) || 0)),
      image_2k_cost_units: Math.max(1, Math.trunc(Number(draft.image_2k_cost_units) || 0)),
      image_4k_cost_units: Math.max(1, Math.trunc(Number(draft.image_4k_cost_units) || 0)),
      image_4k_enabled: Boolean(draft.image_4k_enabled),
      search_cost_units: Math.max(1, Math.trunc(Number(draft.search_cost_units) || 0)),
      file_cost_units: Math.max(1, Math.trunc(Number(draft.file_cost_units) || 0)),
    })
    toast.success('计费设置已保存')
  } catch (error: any) { toast.error(error.message || '计费设置保存失败') }
  finally { savingPricing.value = false }
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
  try {
    const credits = redeemMode.value === 'custom' ? Math.trunc(Number(customCredits.value)) : undefined
    const result = await adminPortalApi.createRedeemCodes(
      redeemMode.value === 'custom' ? 'custom' : selectedPlan.value,
      Math.max(1, Math.min(50, Number(count.value) || 1)),
      credits,
    )
    codes.value = result.codes
    toast.success(`已生成 ${result.codes.length} 个兑换码`)
  }
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

onMounted(() => { void loadPlans(); void loadPricing(); void loadOrders() })
</script>
