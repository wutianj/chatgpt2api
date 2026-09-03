<template>
  <div class="space-y-5">
    <div class="flex flex-wrap items-end justify-between gap-3">
      <div><p class="text-xs uppercase tracking-[0.22em] text-muted-foreground">ACTIVITY</p><h1 class="mt-2 text-3xl font-semibold text-foreground">我的任务</h1><p class="mt-2 text-sm text-muted-foreground">只显示当前账户创建的任务。</p></div>
      <Button size="sm" variant="outline" :disabled="loading" @click="loadTasks">刷新</Button>
    </div>
    <PagePanel class="!rounded-xl">
      <PageLoadingState v-if="loading" title="正在加载任务" description="读取你的最近活动。" />
      <StateBlock v-else-if="errorMessage" title="任务读取失败" :description="errorMessage"><Button size="sm" variant="outline" root-class="mt-4" @click="loadTasks">重试</Button></StateBlock>
      <StateBlock v-else-if="items.length === 0" title="还没有任务" description="从聊天或生图页面开始一次创作。" />
      <div v-else class="divide-y divide-border">
        <div v-for="task in items" :key="task.id" class="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between">
          <div class="min-w-0"><div class="flex flex-wrap items-center gap-2"><span class="text-sm font-semibold text-foreground">{{ task.request.prompt || task.task_type }}</span><span class="border border-border px-2 py-0.5 text-xs text-muted-foreground">{{ task.status }}</span></div><p class="mt-1 text-xs text-muted-foreground">{{ task.model }} · {{ formatDate(task.created_at) }}</p></div>
          <Button v-if="isActive(task.status)" size="sm" variant="outline" :disabled="busyId === task.id" @click="cancelTask(task.id)">{{ busyId === task.id ? '处理中...' : '取消任务' }}</Button>
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
import { tasksApi, type UserTask } from '@/api/tasks'
import { useToast } from '@/composables/useToast'

const toast = useToast()
const items = ref<UserTask[]>([])
const loading = ref(true)
const errorMessage = ref('')
const busyId = ref('')

async function loadTasks() {
  loading.value = true
  errorMessage.value = ''
  try { items.value = (await tasksApi.list()).items } catch (error: any) { errorMessage.value = error.message || '暂时无法读取任务。' } finally { loading.value = false }
}

function isActive(status: string) { return ['queued', 'running', 'pending'].includes(status) }
function formatDate(value: string | null) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '--' }

async function cancelTask(taskId: string) {
  busyId.value = taskId
  try { const result = await tasksApi.cancel(taskId); items.value = items.value.map(item => item.id === taskId ? result.item : item); toast.success('任务已取消') } catch (error: any) { toast.error(error.message || '取消失败') } finally { busyId.value = '' }
}

onMounted(loadTasks)
</script>
