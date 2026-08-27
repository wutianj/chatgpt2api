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
        新窗口打开
      </Button>
    </div>

    <PagePanel v-if="canvasHref" class="min-h-0 flex-1 !rounded-xl !p-2 sm:!p-3">
      <iframe
        :src="canvasHref"
        title="无限画布"
        class="h-full min-h-[32rem] w-full rounded-lg border border-border bg-background"
        referrerpolicy="same-origin"
      ></iframe>
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
const loading = ref(false)
const loadError = ref('')

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
