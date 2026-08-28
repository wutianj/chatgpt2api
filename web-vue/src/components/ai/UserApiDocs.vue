<template>
  <PagePanel class="!rounded-xl">
    <PanelHeader title="API 对接文档" align="start">
      <template #actions>
        <Button size="sm" variant="outline" @click="copyText(openAIBaseUrl)">复制 Base URL</Button>
      </template>
    </PanelHeader>
    <p class="mt-1 text-sm text-muted-foreground">
      使用你创建的 API Key 接入 OpenAI 兼容接口。示例中的 Key 只保存在当前页面内。
    </p>

    <div class="mt-4 grid gap-3 md:grid-cols-2">
      <div class="border border-border p-4">
        <p class="text-xs text-muted-foreground">服务地址</p>
        <p class="mt-2 break-all font-mono text-xs text-foreground">{{ serviceBaseUrl }}</p>
        <Button size="xs" variant="outline" class="mt-3" @click="copyText(serviceBaseUrl)">复制</Button>
      </div>
      <div class="border border-border p-4">
        <p class="text-xs text-muted-foreground">Base URL（OpenAI）</p>
        <p class="mt-2 break-all font-mono text-xs text-foreground">{{ openAIBaseUrl }}</p>
        <Button size="xs" variant="outline" class="mt-3" @click="copyText(openAIBaseUrl)">复制</Button>
      </div>
    </div>

    <div class="mt-4">
      <label for="user-api-doc-key" class="text-sm font-medium text-foreground">用于示例的 API Key</label>
      <Input
        id="user-api-doc-key"
        v-model="apiKey"
        type="password"
        block
        class="mt-2"
        placeholder="粘贴刚创建的 API Key，或留空查看占位示例"
      />
      <p class="mt-1 text-xs text-muted-foreground">不会上传或保存到浏览器；刷新页面后需要重新填写。</p>
    </div>

    <div class="mt-4 border border-border p-4">
      <p class="text-xs text-muted-foreground">请求头</p>
      <p class="mt-2 break-all font-mono text-xs text-foreground">Authorization: Bearer {{ displayApiKey }}</p>
      <Button size="xs" variant="outline" class="mt-3" @click="copyText(`Authorization: Bearer ${displayApiKey}`)">复制</Button>
    </div>

    <div class="mt-5">
      <p class="text-sm font-medium text-foreground">常用接口</p>
      <div class="mt-3 space-y-2">
        <details
          v-for="item in apiDocItems"
          :key="item.path"
          class="rounded-lg border border-border px-4 py-3"
        >
          <summary class="flex cursor-pointer list-none items-center justify-between gap-3">
            <span class="min-w-0">
              <span class="block text-sm font-medium text-foreground">{{ item.title }}</span>
              <span class="mt-1 block truncate font-mono text-xs text-muted-foreground">{{ item.method }} {{ item.path }}</span>
            </span>
            <span class="shrink-0 text-xs text-muted-foreground">展开</span>
          </summary>
          <div class="mt-3 space-y-2">
            <p class="text-xs leading-5 text-muted-foreground">{{ item.description }}</p>
            <pre class="overflow-auto whitespace-pre-wrap break-all rounded-lg bg-zinc-950 px-3 py-3 text-xs leading-5 text-zinc-100">{{ item.example }}</pre>
            <Button size="xs" variant="outline" @click="copyText(item.example)">复制示例</Button>
          </div>
        </details>
      </div>
    </div>

    <div class="mt-4 border border-amber-300/70 bg-amber-50 p-4 text-xs leading-5 text-amber-900">
      图片生成：`1024x1024` 等 1K 尺寸按 1K 计费，`2048x2048` 等 2K 尺寸按 2K 计费；4K 当前暂不支持。
    </div>
  </PagePanel>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Button, Input } from 'nanocat-ui'
import PagePanel from '@/components/ai/PagePanel.vue'
import PanelHeader from '@/components/ai/PanelHeader.vue'
import { buildApiDocItems } from '@/views/settings/settingsView'
import { useToast } from '@/composables/useToast'

const props = defineProps<{ revealedKey?: string }>()
const toast = useToast()
const apiKey = ref('')
const serviceBaseUrl = window.location.origin
const openAIBaseUrl = `${serviceBaseUrl.replace(/\/$/, '')}/v1`
const displayApiKey = computed(() => apiKey.value.trim() || '<你的 API Key>')
const apiDocItems = computed(() => buildApiDocItems(serviceBaseUrl, displayApiKey.value))

watch(() => props.revealedKey, (value) => {
  if (value) apiKey.value = value
}, { immediate: true })

async function copyText(value: string) {
  try {
    await navigator.clipboard.writeText(value)
    toast.success('已复制')
  } catch {
    toast.error('复制失败，请手动复制')
  }
}
</script>
