<template>
  <article class="proxy-group-card" :class="{ 'proxy-group-card--disabled': !group.enabled }">
    <header class="proxy-group-card__header">
      <div class="proxy-group-card__identity">
        <div class="proxy-group-card__eyebrow">
          <span class="proxy-group-card__status-dot" :class="group.enabled ? 'proxy-group-card__status-dot--on' : 'proxy-group-card__status-dot--off'" />
          <span>{{ group.enabled ? '已启用' : '已停用' }}</span>
          <span v-if="isDefault" class="proxy-group-card__tag">默认出口</span>
          <span v-if="group.references.length" class="proxy-group-card__tag proxy-group-card__tag--muted">已绑定 {{ group.references.length }}</span>
        </div>
        <div class="proxy-group-card__title-line">
          <h3 class="proxy-group-card__title">{{ displayName }}</h3>
          <button
            type="button"
            class="proxy-group-card__icon-button"
            title="复制代理组引用"
            aria-label="复制代理组引用"
            @click="emit('copy-reference', group)"
          >
            <Icon icon="lucide:copy" class="h-3.5 w-3.5" />
          </button>
        </div>
        <p class="proxy-group-card__meta">
          <code>{{ group.id }}</code>
          <span>·</span>
          <span>{{ strategyLabel }}</span>
        </p>
        <p v-if="group.notes" class="proxy-group-card__notes">{{ group.notes }}</p>
      </div>

      <div class="proxy-group-card__actions">
        <Button
          size="sm"
          variant="outline"
          :disabled="savingGroupId === group.id"
          @click="emit('edit', group)"
        >
          <Icon icon="lucide:sliders-horizontal" class="h-3.5 w-3.5" />
          编辑节点
        </Button>
        <FloatingActionMenu
          label="更多"
          :items="actionItems"
          :disabled="testingKey === `group:${group.id}:all` || savingGroupId === group.id || deletingGroupId === group.id"
          align="right"
          size="sm"
          trigger-class="h-8 justify-center px-2.5 text-xs"
          :trigger-width="64"
          @select="handleAction"
        />
      </div>
    </header>

    <div class="proxy-group-card__stats" aria-label="代理组概览">
      <div class="proxy-group-card__stat">
        <span>节点</span>
        <strong>{{ group.nodes.length }}</strong>
      </div>
      <div class="proxy-group-card__stat">
        <span>启用</span>
        <strong>{{ enabledNodeCount }} / {{ group.nodes.length }}</strong>
      </div>
      <div class="proxy-group-card__stat">
        <span>图片并发</span>
        <strong>{{ concurrencySummary }}</strong>
      </div>
      <div class="proxy-group-card__stat">
        <span>组状态</span>
        <strong :class="groupHealthClass">{{ groupHealthLabel }}</strong>
      </div>
    </div>

    <section class="proxy-group-card__nodes">
      <div class="proxy-group-card__section-heading">
        <div>
          <p class="proxy-group-card__section-title">节点出口</p>
          <p class="proxy-group-card__section-copy">每个节点可单独设置图片并发</p>
        </div>
        <span class="proxy-group-card__section-count">{{ enabledNodeCount }} 个启用</span>
      </div>

      <div class="proxy-group-card__node-grid">
        <article
          v-for="node in group.nodes"
          :key="node.id"
          class="proxy-node-card"
          :class="{ 'proxy-node-card--disabled': !node.enabled }"
        >
          <div class="proxy-node-card__header">
            <div class="min-w-0">
              <p class="proxy-node-card__name">{{ node.name || node.id }}</p>
              <p class="proxy-node-card__id">{{ node.id }}</p>
            </div>
            <span class="proxy-node-card__enabled" :class="node.enabled ? 'proxy-node-card__enabled--on' : 'proxy-node-card__enabled--off'">
              {{ node.enabled ? '启用' : '停用' }}
            </span>
          </div>
          <p class="proxy-node-card__url" :title="node.url">{{ maskedUrl(node.url) || '未设置代理地址' }}</p>

          <div v-if="editingNodeId !== node.id" class="proxy-node-card__footer">
            <div class="proxy-node-card__details">
              <span class="proxy-node-card__concurrency">图片并发 <strong>{{ formatConcurrency(node.image_concurrency_limit) }}</strong></span>
              <span class="proxy-node-card__health" :class="nodeTestClass(group, node)">
                {{ nodeTestSummary(group, node) }}
              </span>
            </div>
            <button
              type="button"
              class="proxy-node-card__edit-button"
              title="修改图片并发"
              :aria-label="`修改 ${node.name || node.id} 的图片并发`"
              :disabled="savingGroupId === group.id"
              @click="openConcurrencyEditor(node)"
            >
              <Icon icon="lucide:pencil" class="h-3.5 w-3.5" />
            </button>
          </div>

          <div v-else class="proxy-node-card__edit-row">
            <label class="proxy-node-card__edit-field">
              <span>图片并发</span>
              <Input
                :model-value="draftConcurrency"
                type="number"
                min="0"
                max="10000"
                step="1"
                aria-label="图片并发"
                @update:model-value="draftConcurrency = String($event)"
              />
            </label>
            <Button size="xs" variant="primary" :disabled="savingGroupId === group.id" @click="saveConcurrency(node)">
              保存
            </Button>
            <button
              type="button"
              class="proxy-node-card__icon-button"
              title="取消编辑"
              aria-label="取消编辑"
              @click="closeConcurrencyEditor"
            >
              <Icon icon="lucide:x" class="h-3.5 w-3.5" />
            </button>
          </div>
        </article>
      </div>
    </section>

    <footer class="proxy-group-card__footer">
      <span class="proxy-group-card__footer-label">代理组引用</span>
      <button
        type="button"
        class="proxy-group-card__reference"
        :title="`复制 ${reference}`"
        @click="emit('copy-reference', group)"
      >
        <code>{{ reference }}</code>
        <Icon icon="lucide:copy" class="h-3.5 w-3.5 shrink-0" />
      </button>
    </footer>
  </article>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Icon } from '@iconify/vue'
import { Button, Input } from 'nanocat-ui'
import type { ProxyGroup, ProxyNode } from '@/api/proxy'
import FloatingActionMenu from '@/components/ai/FloatingActionMenu.vue'
import { proxyGroupActionItems, proxyGroupReference } from './proxyView'

const props = defineProps<{
  group: ProxyGroup
  isDefault?: boolean
  testingKey: string
  savingGroupId: string
  deletingGroupId: string
  nodeTestSummary: (group: ProxyGroup, node: ProxyNode) => string
  nodeTestClass: (group: ProxyGroup, node: ProxyNode) => string
}>()

const emit = defineEmits<{
  (e: 'copy-reference', group: ProxyGroup): void
  (e: 'edit', group: ProxyGroup): void
  (e: 'save-concurrency', group: ProxyGroup, node: ProxyNode, limit: number): void
  (e: 'action', group: ProxyGroup, action: string): void
}>()

const editingNodeId = ref('')
const draftConcurrency = ref('')

const displayName = computed(() => props.group.name || props.group.id)
const reference = computed(() => proxyGroupReference(props.group))
const enabledNodeCount = computed(() => props.group.nodes.filter((node) => node.enabled).length)
const strategyLabel = computed(() => {
  if (props.group.strategy === 'round_robin') return '轮询'
  if (props.group.strategy === 'time_window') return `按时间轮换 · ${props.group.rotation_interval_minutes} 分钟`
  return '请求随机'
})
const concurrencySummary = computed(() => {
  const values = props.group.nodes.map((node) => Math.max(0, Number(node.image_concurrency_limit || 0)))
  if (!values.length) return '-'
  if (values.every((value) => value === values[0])) return formatConcurrency(values[0])
  return `${Math.min(...values)}-${Math.max(...values)}`
})
const groupHealthLabel = computed(() => {
  if (props.group.health.state === 'healthy') return '可用'
  if (props.group.health.state === 'unhealthy') return '异常'
  return '待检测'
})
const groupHealthClass = computed(() => {
  if (props.group.health.state === 'healthy') return 'proxy-group-card__stat-value--good'
  if (props.group.health.state === 'unhealthy') return 'proxy-group-card__stat-value--bad'
  return 'proxy-group-card__stat-value--muted'
})
const actionItems = computed(() => proxyGroupActionItems(
  props.group,
  props.testingKey,
  props.savingGroupId,
  props.deletingGroupId,
))

function formatConcurrency(value: unknown) {
  const limit = Math.max(0, Number(value || 0))
  return limit > 0 ? String(limit) : '不限'
}

function maskedUrl(value: unknown) {
  const raw = String(value || '').trim()
  if (!raw) return ''
  return raw.replace(/:\/\/([^/@:]+):([^/@]+)@/, (_match, username) => `://${username}:***@`)
}

function openConcurrencyEditor(node: ProxyNode) {
  editingNodeId.value = node.id
  draftConcurrency.value = String(Math.max(0, Number(node.image_concurrency_limit || 0)))
}

function closeConcurrencyEditor() {
  editingNodeId.value = ''
  draftConcurrency.value = ''
}

function saveConcurrency(node: ProxyNode) {
  const parsed = Number(draftConcurrency.value)
  if (!Number.isFinite(parsed)) return
  const limit = Math.max(0, Math.min(10000, Math.floor(parsed)))
  emit('save-concurrency', props.group, node, limit)
  closeConcurrencyEditor()
}

function handleAction(action: string) {
  emit('action', props.group, action)
}
</script>

<style scoped>
.proxy-group-card {
  overflow: hidden;
  border: 1px solid hsl(var(--border));
  border-radius: 12px;
  background: hsl(var(--card));
  box-shadow: 0 8px 24px hsl(var(--foreground) / 0.045);
}

.proxy-group-card--disabled {
  opacity: 0.78;
}

.proxy-group-card__header,
.proxy-group-card__footer {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 18px;
}

.proxy-group-card__header {
  border-bottom: 1px solid hsl(var(--border));
}

.proxy-group-card__identity {
  min-width: 0;
  flex: 1 1 auto;
}

.proxy-group-card__eyebrow,
.proxy-group-card__meta,
.proxy-group-card__details,
.proxy-group-card__footer,
.proxy-node-card__header,
.proxy-node-card__footer,
.proxy-node-card__edit-row {
  display: flex;
  align-items: center;
}

.proxy-group-card__eyebrow {
  flex-wrap: wrap;
  gap: 7px;
  color: hsl(var(--muted-foreground));
  font-size: 11px;
  line-height: 1.2;
}

.proxy-group-card__status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.proxy-group-card__status-dot--on {
  background: hsl(160 65% 42%);
  box-shadow: 0 0 0 3px hsl(160 65% 42% / 0.12);
}

.proxy-group-card__status-dot--off {
  background: hsl(var(--muted-foreground));
}

.proxy-group-card__tag {
  border: 1px solid hsl(160 55% 74%);
  border-radius: 999px;
  padding: 3px 7px;
  color: hsl(160 55% 32%);
  background: hsl(160 55% 95%);
  font-size: 10px;
}

.proxy-group-card__tag--muted {
  border-color: hsl(var(--border));
  color: hsl(var(--muted-foreground));
  background: hsl(var(--muted) / 0.22);
}

.proxy-group-card__title-line {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 7px;
  margin-top: 9px;
}

.proxy-group-card__title {
  min-width: 0;
  overflow: hidden;
  color: hsl(var(--foreground));
  font-family: "Noto Serif SC", Georgia, serif;
  font-size: 19px;
  font-weight: 700;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.proxy-group-card__icon-button,
.proxy-node-card__edit-button {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: 1px solid hsl(var(--border));
  border-radius: 7px;
  color: hsl(var(--muted-foreground));
  background: hsl(var(--background));
  transition: border-color 140ms ease, color 140ms ease, background 140ms ease;
}

.proxy-group-card__icon-button:hover,
.proxy-node-card__edit-button:hover {
  border-color: hsl(var(--primary));
  color: hsl(var(--foreground));
  background: hsl(var(--muted) / 0.35);
}

.proxy-group-card__icon-button:disabled,
.proxy-node-card__edit-button:disabled {
  opacity: 0.5;
}

.proxy-group-card__meta {
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
  color: hsl(var(--muted-foreground));
  font-size: 11px;
}

.proxy-group-card__meta code,
.proxy-group-card__reference code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
}

.proxy-group-card__notes {
  margin-top: 6px;
  overflow-wrap: anywhere;
  color: hsl(var(--muted-foreground));
  font-size: 12px;
}

.proxy-group-card__actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 8px;
}

.proxy-group-card__stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border-bottom: 1px solid hsl(var(--border));
}

.proxy-group-card__stat {
  min-width: 0;
  padding: 12px 16px;
  border-right: 1px solid hsl(var(--border));
}

.proxy-group-card__stat:last-child {
  border-right: 0;
}

.proxy-group-card__stat span {
  display: block;
  color: hsl(var(--muted-foreground));
  font-size: 11px;
}

.proxy-group-card__stat strong {
  display: block;
  overflow: hidden;
  margin-top: 5px;
  color: hsl(var(--foreground));
  font-size: 14px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.proxy-group-card__stat-value--good {
  color: hsl(160 55% 34%) !important;
}

.proxy-group-card__stat-value--bad {
  color: hsl(350 65% 43%) !important;
}

.proxy-group-card__stat-value--muted {
  color: hsl(var(--muted-foreground)) !important;
}

.proxy-group-card__nodes {
  padding: 16px 18px;
}

.proxy-group-card__section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.proxy-group-card__section-title {
  color: hsl(var(--foreground));
  font-size: 13px;
  font-weight: 600;
}

.proxy-group-card__section-copy,
.proxy-group-card__section-count {
  margin-top: 3px;
  color: hsl(var(--muted-foreground));
  font-size: 11px;
}

.proxy-group-card__section-count {
  flex: 0 0 auto;
  margin-top: 0;
  padding-top: 2px;
}

.proxy-group-card__node-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.proxy-node-card {
  min-width: 0;
  padding: 11px 12px;
  border: 1px solid hsl(var(--border));
  border-radius: 8px;
  background: hsl(var(--background));
}

.proxy-node-card--disabled {
  background: hsl(var(--muted) / 0.22);
}

.proxy-node-card__header {
  justify-content: space-between;
  gap: 8px;
}

.proxy-node-card__name {
  overflow: hidden;
  color: hsl(var(--foreground));
  font-size: 12px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.proxy-node-card__id {
  overflow: hidden;
  margin-top: 2px;
  color: hsl(var(--muted-foreground));
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.proxy-node-card__enabled {
  flex: 0 0 auto;
  font-size: 10px;
}

.proxy-node-card__enabled--on {
  color: hsl(160 55% 34%);
}

.proxy-node-card__enabled--off {
  color: hsl(var(--muted-foreground));
}

.proxy-node-card__url {
  overflow: hidden;
  margin-top: 9px;
  color: hsl(var(--muted-foreground));
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 10px;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.proxy-node-card__footer {
  justify-content: space-between;
  gap: 8px;
  margin-top: 10px;
}

.proxy-node-card__details {
  min-width: 0;
  flex-wrap: wrap;
  gap: 8px;
}

.proxy-node-card__concurrency,
.proxy-node-card__health {
  font-size: 11px;
  line-height: 1.3;
}

.proxy-node-card__concurrency {
  color: hsl(var(--foreground));
}

.proxy-node-card__concurrency strong {
  font-weight: 600;
}

.proxy-node-card__health {
  overflow: hidden;
  color: hsl(var(--muted-foreground));
  text-overflow: ellipsis;
  white-space: nowrap;
}

.proxy-node-card__edit-row {
  gap: 6px;
  margin-top: 10px;
}

.proxy-node-card__edit-field {
  display: flex;
  min-width: 0;
  flex: 1 1 auto;
  align-items: center;
  gap: 7px;
  color: hsl(var(--muted-foreground));
  font-size: 11px;
}

.proxy-node-card__edit-field :deep(input) {
  min-width: 0;
}

.proxy-group-card__footer {
  align-items: center;
  border-top: 1px solid hsl(var(--border));
  background: hsl(var(--muted) / 0.12);
}

.proxy-group-card__footer-label {
  flex: 0 0 auto;
  color: hsl(var(--muted-foreground));
  font-size: 11px;
}

.proxy-group-card__reference {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 7px;
  overflow: hidden;
  color: hsl(var(--muted-foreground));
  font-size: 11px;
  text-align: left;
}

.proxy-group-card__reference:hover {
  color: hsl(var(--foreground));
}

.proxy-group-card__reference code {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (min-width: 1280px) {
  .proxy-group-card__node-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .proxy-group-card__header,
  .proxy-group-card__footer {
    flex-direction: column;
    align-items: stretch;
  }

  .proxy-group-card__actions {
    justify-content: flex-end;
  }

  .proxy-group-card__stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .proxy-group-card__stat:nth-child(2) {
    border-right: 0;
  }

  .proxy-group-card__stat:nth-child(-n + 2) {
    border-bottom: 1px solid hsl(var(--border));
  }

  .proxy-group-card__node-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
