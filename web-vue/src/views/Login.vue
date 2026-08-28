<template>
  <div class="min-h-screen bg-background px-4 py-8">
    <div class="mx-auto flex min-h-[calc(100vh-4rem)] w-full max-w-5xl items-center justify-center">
      <div class="grid w-full overflow-hidden rounded-2xl border border-border bg-card shadow-xl lg:grid-cols-[1.05fr_0.95fr]">
        <section class="hidden bg-foreground p-10 text-background lg:flex lg:flex-col lg:justify-between">
          <div>
            <p class="text-xs font-semibold uppercase tracking-[0.3em] opacity-60">AI WORKSPACE</p>
            <h1 class="mt-8 max-w-sm text-5xl font-semibold leading-tight">把创作工具，放在一个入口里。</h1>
            <p class="mt-6 max-w-md text-sm leading-7 opacity-70">聊天、生图、无限画布和任务记录，共享同一套账户与额度。</p>
          </div>
          <div class="grid grid-cols-3 gap-3 text-xs opacity-70">
            <span class="border-l border-current/30 pl-3">对话</span>
            <span class="border-l border-current/30 pl-3">图像</span>
            <span class="border-l border-current/30 pl-3">任务</span>
          </div>
        </section>

        <section class="p-6 sm:p-10">
          <div class="lg:hidden">
            <p class="text-xs font-semibold uppercase tracking-[0.28em] text-muted-foreground">AI WORKSPACE</p>
          </div>
          <div class="mt-3 text-center lg:mt-0">
            <h2 class="text-3xl font-semibold text-foreground">统一创作入口</h2>
            <p class="mt-2 text-sm text-muted-foreground">登录后继续你的工作。</p>
          </div>

          <form class="mt-8 space-y-4" @submit.prevent="handleUserSubmit">
            <div v-if="isRegistering" class="space-y-2">
              <label for="display-name" class="ui-field-label text-sm font-medium text-foreground">显示名称</label>
              <Input id="display-name" v-model="displayName" size="md" block placeholder="怎么称呼你" :disabled="isLoading" />
            </div>
            <div class="space-y-2">
              <label for="email" class="ui-field-label text-sm font-medium text-foreground">账号（邮箱）</label>
              <Input id="email" v-model="email" type="email" size="md" block placeholder="输入注册邮箱" :disabled="isLoading" />
            </div>
            <div class="space-y-2">
              <label for="user-password" class="ui-field-label text-sm font-medium text-foreground">密码</label>
              <Input id="user-password" v-model="userPassword" type="password" size="md" block placeholder="至少 8 位" :disabled="isLoading" />
            </div>
            <Button type="submit" size="md" variant="primary" block :disabled="isLoading || !email || !userPassword">
              {{ isLoading ? '处理中...' : (isRegistering ? '创建账户' : '登录') }}
            </Button>
            <button type="button" class="block w-full text-center text-sm text-muted-foreground hover:text-foreground" @click="isRegistering = !isRegistering">
              {{ isRegistering ? '已有账户？返回登录' : '还没有账户？立即注册' }}
            </button>
          </form>

          <p class="mt-8 text-center text-xs text-muted-foreground">管理员账号登录后自动进入管理后台，普通账号进入用户工作台。</p>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Button, Input } from 'nanocat-ui'
import { useToast } from '@/composables/useToast'
import { resolveLoginRedirect } from '@/router/routes'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const toast = useToast()

const isRegistering = ref(false)
const email = ref('')
const displayName = ref('')
const userPassword = ref('')
const isLoading = ref(false)

async function finishLogin() {
  await router.replace(resolveLoginRedirect(route.query.redirect, authStore.homeRoute))
}

async function handleUserSubmit() {
  if (!email.value || !userPassword.value) return
  isLoading.value = true
  try {
    const loggedIn = isRegistering.value
      ? await authStore.register(email.value, userPassword.value, displayName.value)
      : await authStore.loginUser(email.value, userPassword.value)
    if (!loggedIn) throw new Error('登录状态未建立，请稍后重试。')
    await finishLogin()
  } catch (error: any) {
    toast.error(error.message || '操作失败，请检查输入。')
  } finally {
    isLoading.value = false
  }
}

</script>
