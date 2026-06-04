<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  importAccounts,
  importProxies,
  listAccounts,
  listFolders,
  listMessages,
  listProxies,
  startOAuth,
  startPlaywrightOAuth,
  syncAccount,
  syncAccountViaImap,
  validateActiveProxies,
} from './api'

const sample = 'account1@outlook.com----password----totp-secret\naccount2@outlook.com----password----totp-secret'
const importText = ref(sample)
const proxyText = ref('')
const accounts = ref([])
const proxies = ref([])
const folders = ref([])
const messages = ref([])
const selectedAccountId = ref(null)
const selectedFolderId = ref(null)
const loading = ref(false)
const notice = ref('')
const error = ref('')

const selectedAccount = computed(() =>
  accounts.value.find((account) => account.id === selectedAccountId.value)
)

async function run(action, successText) {
  loading.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = await action()
    notice.value = successText || '操作完成'
    return result
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function refreshAccounts() {
  accounts.value = await listAccounts()
  if (!selectedAccountId.value && accounts.value.length) {
    selectedAccountId.value = accounts.value[0].id
    await loadMailbox()
  }
}

async function refreshProxies() {
  proxies.value = await listProxies()
}

async function submitImport() {
  await run(async () => {
    const result = await importAccounts(importText.value)
    await refreshAccounts()
    return result
  }, '账号已导入')
}

async function submitProxyImport() {
  await run(async () => {
    await importProxies(proxyText.value, 'http')
    await refreshProxies()
  }, '代理池已导入')
}

async function validateProxies() {
  const result = await run(async () => {
    const validation = await validateActiveProxies()
    await refreshProxies()
    return validation
  }, '代理验证完成')
  if (result) {
    notice.value = `代理验证完成：可用 ${result.valid}，不可用 ${result.invalid}`
  }
}

async function authorize(account) {
  const result = await run(() => startOAuth(account.id), '正在打开授权页面')
  if (result?.url) {
    window.location.href = result.url
  }
}

async function authorizeWithPlaywright(account) {
  await run(
    () => startPlaywrightOAuth(account.id),
    '已启动 Playwright 授权窗口，将随机使用一个可用代理'
  )
}

async function sync(account) {
  await run(async () => {
    await syncAccount(account.id)
    await refreshAccounts()
    await loadMailbox()
  }, '同步完成')
}

async function syncImap(account) {
  await run(async () => {
    await syncAccountViaImap(account.id)
    await refreshAccounts()
    await loadMailbox()
  }, 'IMAP 同步完成')
}

async function loadMailbox() {
  if (!selectedAccountId.value) return
  folders.value = await listFolders(selectedAccountId.value)
  messages.value = await listMessages(selectedAccountId.value, selectedFolderId.value)
}

async function selectAccount(account) {
  selectedAccountId.value = account.id
  selectedFolderId.value = null
  await loadMailbox()
}

async function selectFolder(folder) {
  selectedFolderId.value = folder?.id || null
  messages.value = await listMessages(selectedAccountId.value, selectedFolderId.value)
}

onMounted(async () => {
  const params = new URLSearchParams(window.location.search)
  if (params.get('oauth') === 'success') notice.value = '授权成功，可以同步邮件了'
  if (params.get('oauth') === 'failed') error.value = '授权失败，请检查后端配置或账号状态'
  await Promise.all([refreshAccounts(), refreshProxies()])
})
</script>

<template>
  <main class="shell">
    <aside class="sidebar">
      <div class="brand">
        <h1>Outlook 管理器</h1>
        <span>本机版 MVP</span>
      </div>

      <section class="panel">
        <div class="panel-title">账号导入</div>
        <textarea v-model="importText" spellcheck="false" />
        <button class="primary" :disabled="loading" @click="submitImport">导入账号</button>
      </section>

      <section class="panel account-panel">
        <div class="panel-title">账号</div>
        <button
          v-for="account in accounts"
          :key="account.id"
          class="account-row"
          :class="{ active: account.id === selectedAccountId }"
          @click="selectAccount(account)"
        >
          <span>{{ account.email }}</span>
          <small>{{ account.status }}</small>
        </button>
      </section>

      <section class="panel proxy-panel">
        <div class="panel-title">代理池</div>
        <textarea v-model="proxyText" spellcheck="false" />
        <div class="proxy-actions">
          <button :disabled="loading" @click="submitProxyImport">导入代理</button>
          <button :disabled="loading" @click="validateProxies">验证代理</button>
          <span>{{ proxies.length }} 个代理</span>
        </div>
        <div class="proxy-list">
          <div v-for="proxy in proxies.slice(0, 5)" :key="proxy.id" class="proxy-row">
            <span>{{ proxy.host }}:{{ proxy.port }}</span>
            <small>{{ proxy.status }}</small>
          </div>
        </div>
      </section>
    </aside>

    <section class="workspace">
      <header class="topbar">
        <div>
          <h2>{{ selectedAccount?.email || '选择一个账号' }}</h2>
          <p>Graph OAuth 持久化登录，IMAP/App Password 后续兼容。</p>
        </div>
        <div v-if="selectedAccount" class="actions">
          <button :disabled="loading" @click="authorize(selectedAccount)">授权</button>
          <button :disabled="loading" @click="authorizeWithPlaywright(selectedAccount)">
            Playwright 授权
          </button>
          <button class="primary" :disabled="loading" @click="sync(selectedAccount)">同步</button>
          <button :disabled="loading" @click="syncImap(selectedAccount)">IMAP 试同步</button>
        </div>
      </header>

      <div v-if="notice" class="notice">{{ notice }}</div>
      <div v-if="error" class="error">{{ error }}</div>

      <div class="mail-layout">
        <nav class="folders">
          <button :class="{ active: selectedFolderId === null }" @click="selectFolder(null)">
            全部邮件
          </button>
          <button
            v-for="folder in folders"
            :key="folder.id"
            :class="{ active: selectedFolderId === folder.id }"
            @click="selectFolder(folder)"
          >
            <span>{{ folder.display_name }}</span>
            <small>{{ folder.unread_count }}/{{ folder.total_count }}</small>
          </button>
        </nav>

        <section class="messages">
          <article v-for="message in messages" :key="message.id" class="message">
            <div class="message-head">
              <strong :class="{ unread: !message.is_read }">{{ message.subject || '(无主题)' }}</strong>
              <time>{{ message.received_at || '' }}</time>
            </div>
            <div class="sender">{{ message.sender || '未知发件人' }}</div>
            <p>{{ message.snippet }}</p>
          </article>
          <div v-if="!messages.length" class="empty">暂无邮件，授权并同步后会显示在这里。</div>
        </section>
      </div>
    </section>
  </main>
</template>
