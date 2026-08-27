<template>
  <div class="space-y-5">
    <section class="grid gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(18rem,0.65fr)]">
      <PagePanel class="relative overflow-hidden !rounded-xl bg-foreground text-background">
        <div class="relative z-10 max-w-2xl p-2 sm:p-5">
          <p class="text-xs font-semibold uppercase tracking-[0.28em] opacity-60">AI WORKSPACE</p>
          <h1 class="mt-5 text-3xl font-semibold leading-tight sm:text-5xl">你好，{{ firstName }}。</h1>
          <p class="mt-4 max-w-xl text-sm leading-7 opacity-70">从一个想法开始。聊天、生图和无限画布已经准备好。</p>
          <div class="mt-7 flex flex-wrap gap-2">
            <RouterLink to="/chat" class="inline-flex items-center rounded-lg bg-background px-4 py-2.5 text-sm font-semibold text-foreground transition-opacity hover:opacity-85">开始对话</RouterLink>
            <RouterLink to="/image" class="inline-flex items-center rounded-lg border border-background/25 px-4 py-2.5 text-sm font-medium text-background transition-colors hover:bg-background/10">生成图片</RouterLink>
          </div>
        </div>
      </PagePanel>

      <PagePanel class="!rounded-xl">
        <div class="flex items-start justify-between gap-3">
          <div>
            <p class="text-xs uppercase tracking-[0.18em] text-muted-foreground">可用额度</p>
            <p class="mt-3 text-3xl font-semibold tabular-nums text-foreground">{{ balanceLabel }}</p>
          </div>
          <RouterLink to="/wallet" class="text-sm text-muted-foreground hover:text-foreground">充值</RouterLink>
        </div>
        <div class="mt-8 border-t border-border pt-4 text-xs leading-6 text-muted-foreground">额度会在钱包中统一记录，兑换码到账后立即可用。</div>
      </PagePanel>
    </section>

    <section class="grid gap-5 lg:grid-cols-2">
      <PagePanel class="!rounded-xl">
        <PanelHeader title="快捷入口" align="start" />
        <div class="mt-4 grid gap-2 sm:grid-cols-3">
          <RouterLink v-for="item in shortcuts" :key="item.path" :to="item.path" class="group border border-border p-4 transition-colors hover:border-foreground/40 hover:bg-muted/50">
            <Icon :icon="item.icon" class="h-5 w-5 text-muted-foreground transition-colors group-hover:text-foreground" />
            <p class="mt-5 text-sm font-semibold text-foreground">{{ item.label }}</p>
            <p class="mt-1 text-xs text-muted-foreground">{{ item.description }}</p>
          </RouterLink>
        </div>
      </PagePanel>

      <PagePanel class="!rounded-xl">
        <PanelHeader title="最近任务" align="start">
          <template #actions><RouterLink to="/tasks" class="text-sm text-muted-foreground hover:text-foreground">查看全部</RouterLink></template>
        </PanelHeader>
        <div v-if="loading" class="py-10 text-center text-sm text-muted-foreground">正在读取任务...</div>
        <div v-else-if="loadError" class="py-10 text-center text-sm text-muted-foreground">{{ loadError }}</div>
        <div v-else-if="recentTasks.length === 0" class="py-10 text-center text-sm text-muted-foreground">还没有任务，开始一次创作吧。</div>
        <div v-else class="mt-3 divide-y divide-border">
          <div v-for="task in recentTasks" :key="task.id" class="flex items-center justify-between gap-4 py-3">
            <div class="min-w-0"><p class="truncate text-sm font-medium text-foreground">{{ task.request.prompt || task.task_type }}</p><p class="mt-1 text-xs text-muted-foreground">{{ task.model }}</p></div>
            <span class="shrink-0 text-xs text-muted-foreground">{{ task.status }}</span>
          </div>
        </div>
      </PagePanel>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Icon } from '@iconify/vue'
import PagePanel from '@/components/ai/PagePanel.vue'
import PanelHeader from '@/components/ai/PanelHeader.vue'
import { billingApi, formatCredits, type WalletView } from '@/api/billing'
import { tasksApi, type UserTask } from '@/api/tasks'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const wallet = ref<WalletView | null>(null)
const recentTasks = ref<UserTask[]>([])
const loading = ref(true)
const loadError = ref('')
const firstName = computed(() => authStore.name || '创作者')
const balanceLabel = computed(() => formatCredits(wallet.value?.balance_units || 0))
const shortcuts = [
  { path: '/chat', label: 'AI 对话', description: '继续思考和写作', icon: 'lucide:message-square' },
  { path: '/image', label: 'AI 生图', description: '把描述变成画面', icon: 'lucide:image' },
  { path: '/canvas', label: '无限画布', description: '整理灵感与素材', icon: 'lucide:layout-dashboard' },
]

onMounted(async () => {
  try {
    const [walletResult, taskResult] = await Promise.all([billingApi.wallet(10), tasksApi.list(5)])
    wallet.value = walletResult
    recentTasks.value = taskResult.items
  } catch (error: any) {
    loadError.value = error.message || '暂时无法读取工作台数据。'
  } finally {
    loading.value = false
  }
})
</script>
