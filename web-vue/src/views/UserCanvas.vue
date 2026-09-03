<template>
  <div class="flex min-h-0 flex-1 flex-col gap-4 p-4 sm:p-6">
    <div class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <p class="text-xs uppercase tracking-[0.22em] text-muted-foreground">CANVAS</p>
        <h1 class="mt-2 text-3xl font-semibold text-foreground">无限画布</h1>
        <p class="mt-2 text-sm text-muted-foreground">在统一账户下继续整理灵感、图片和提示词。</p>
      </div>
      <Button v-if="canvasHref" size="sm" variant="outline" @click="openCanvas">
        <Icon icon="lucide:external-link" class="h-4 w-4" />
        外置打开
      </Button>
    </div>

    <div v-if="canvasHref" class="flex flex-wrap items-center justify-between gap-3">
      <div class="inline-flex rounded-lg border border-border bg-muted/30 p-1" role="tablist" aria-label="画布模式">
        <button
          type="button"
          role="tab"
          :aria-selected="canvasMode === 'embedded'"
          :class="modeButtonClass(canvasMode === 'embedded')"
          @click="canvasMode = 'embedded'"
        >
          <Icon icon="lucide:panels-top-left" class="h-4 w-4" />
          内置无限画布
        </button>
        <button
          type="button"
          role="tab"
          :aria-selected="canvasMode === 'external'"
          :class="modeButtonClass(canvasMode === 'external')"
          @click="canvasMode = 'external'"
        >
          <Icon icon="lucide:external-link" class="h-4 w-4" />
          外置无限画布
        </button>
      </div>
      <p class="text-xs text-muted-foreground">
        {{ canvasMode === 'embedded' ? '在当前门户内使用' : '跳转到 canvas.n9k2m.shop' }}
      </p>
    </div>

    <PagePanel v-if="canvasHref && canvasMode === 'embedded'" class="min-h-0 flex-1 !rounded-xl !p-2 sm:!p-3">
      <iframe
        :src="canvasHref"
        title="内置无限画布"
        class="h-full min-h-[32rem] w-full rounded-lg border border-border bg-background"
        referrerpolicy="same-origin"
      ></iframe>
    </PagePanel>
    <PagePanel v-else-if="canvasHref" class="min-h-0 flex-1 !rounded-xl">
      <div class="flex min-h-[32rem] flex-col items-center justify-center px-6 text-center">
        <div class="flex h-14 w-14 items-center justify-center rounded-2xl border border-border bg-muted/40">
          <Icon icon="lucide:external-link" class="h-6 w-6 text-muted-foreground" />
        </div>
        <h2 class="mt-5 text-lg font-semibold text-foreground">外置无限画布</h2>
        <p class="mt-2 max-w-md text-sm leading-6 text-muted-foreground">
          使用独立窗口打开之前部署的无限画布，登录状态和当前接口配置会自动带入。
        </p>
        <Button class="mt-5" size="sm" @click="openCanvas">
          <Icon icon="lucide:external-link" class="h-4 w-4" />
          打开 canvas.n9k2m.shop
        </Button>
      </div>
    </PagePanel>
    <PagePanel v-else class="!rounded-xl">
      <StateBlock
        :title="loadError ? '画布暂时不可用' : '画布服务尚未配置'"
        :description="loadError || '请联系管理员配置画布地址，配置完成后会自动出现在这里。'"
      >
        <Button size="sm" variant="outline" root-class="mt-4" :disabled="loading" @click="load">
          <Icon icon="lucide:refresh-cw" class="h-4 w-4" />
          {{ loading ? '读取中...' : '重新读取' }}
        </Button>
      </StateBlock>
    </PagePanel>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Icon } from '@iconify/vue'
import { Button } from 'nanocat-ui'
import PagePanel from '@/components/ai/PagePanel.vue'
import StateBlock from '@/components/ai/StateBlock.vue'
import { buildThirdPartyHref, settingsApi } from '@/api/settings'
import { usePublicRuntimeConfig } from '@/composables/usePublicRuntimeConfig'

const { apiBaseUrl, thirdPartyApps, loadPublicRuntimeConfig } = usePublicRuntimeConfig()
const canvasHref = ref('')
const canvasMode = ref<'embedded' | 'external'>('embedded')
const loading = ref(false)
const loadError = ref('')

function modeButtonClass(active: boolean) {
  return [
    'inline-flex min-h-9 items-center gap-2 rounded-md px-3 text-sm transition-colors',
    active
      ? 'bg-background text-foreground shadow-sm'
      : 'text-muted-foreground hover:bg-background/70 hover:text-foreground',
  ]
}

async function load() {
  loading.value = true
  loadError.value = ''
  canvasHref.value = ''
  try {
    await loadPublicRuntimeConfig(true)
    const app = thirdPartyApps.value?.infinite_canvas
    if (!app?.enabled || !app.url.trim()) return
    const session = await settingsApi.createCanvasSession()
    canvasHref.value = buildThirdPartyHref(app.url, apiBaseUrl.value, session.access_token)
  } catch (error: any) {
    loadError.value = error.message || '无法创建画布会话，请稍后重试。'
  } finally {
    loading.value = false
  }
}

function openCanvas() {
  if (canvasHref.value) window.open(canvasHref.value, '_blank', 'noopener,noreferrer')
}

onMounted(load)
</script>
