<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  deleteAccount,
  deleteProxy,
  exportAuthorizedAccounts,
  getOAuthSession,
  getProxyValidationJob,
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
const importModalOpen = ref(false)
const importMode = ref('accounts')
const authorizedOutput = ref('')
const authorizedOutputCount = ref(0)
const accounts = ref([])
const proxies = ref([])
const folders = ref([])
const messages = ref([])
const selectedAccountId = ref(null)
const selectedFolderId = ref(null)
const loading = ref(false)
const notice = ref('')
const error = ref('')
const proxyValidationJob = ref(null)
const proxyLogs = ref([])
const proxyPolling = ref(false)
const oauthSession = ref(null)
const oauthLogs = ref([])

const selectedAccount = computed(() =>
  accounts.value.find((account) => account.id === selectedAccountId.value)
)

const statusLabels = {
  active: '可用',
  invalid: '不可用',
  reserved: '待验证',
  not_authorized: '未授权',
  authorizing: '授权中',
  authorized: '已授权',
  auth_failed: '授权失败',
  auth_expired: '授权过期',
  imap_synced: 'IMAP 已同步',
  imap_failed: 'IMAP 失败',
  created: '已创建',
  failed: '失败',
}

function statusText(status) {
  return statusLabels[status] || status || '-'
}

const importTitle = computed(() => (importMode.value === 'accounts' ? '导入账号' : '导入代理'))
const importDescription = computed(() =>
  importMode.value === 'accounts'
    ? '格式：邮箱----密码----totp_secret'
    : '格式：host:port:username:password'
)
const importModel = computed({
  get() {
    return importMode.value === 'accounts' ? importText.value : proxyText.value
  },
  set(value) {
    if (importMode.value === 'accounts') {
      importText.value = value
    } else {
      proxyText.value = value
    }
  },
})

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

function openImport(mode) {
  importMode.value = mode
  importModalOpen.value = true
}

function closeImport() {
  importModalOpen.value = false
}

async function submitImport() {
  await run(async () => {
    if (importMode.value === 'accounts') {
      const result = await importAccounts(importText.value)
      await refreshAccounts()
      return result
    }
    const result = await importProxies(proxyText.value, 'http')
    await refreshProxies()
    return result
  }, importMode.value === 'accounts' ? '账号已导入' : '代理池已导入')
  closeImport()
}

async function removeAccount(account) {
  const confirmed = window.confirm(`删除邮箱账号 ${account.email}？`)
  if (!confirmed) return
  await run(async () => {
    await deleteAccount(account.id)
    if (selectedAccountId.value === account.id) {
      selectedAccountId.value = null
      selectedFolderId.value = null
      folders.value = []
      messages.value = []
    }
    await refreshAccounts()
  }, '账号已删除')
}

async function loadAuthorizedOutput(options = {}) {
  if (options.silent) {
    const result = await exportAuthorizedAccounts()
    authorizedOutput.value = result.text || ''
    authorizedOutputCount.value = result.count || 0
    return
  }
  const result = await run(() => exportAuthorizedAccounts(), '授权输出已刷新')
  if (!result) return
  authorizedOutput.value = result.text || ''
  authorizedOutputCount.value = result.count || 0
}

async function copyAuthorizedOutput() {
  if (!authorizedOutput.value) {
    notice.value = '暂无可复制的授权输出'
    return
  }
  await navigator.clipboard.writeText(authorizedOutput.value)
  notice.value = '授权输出已复制'
}

async function removeProxy(proxy) {
  const confirmed = window.confirm(`删除代理 ${proxy.host}:${proxy.port}？`)
  if (!confirmed) return
  await run(async () => {
    await deleteProxy(proxy.id)
    await refreshProxies()
  }, '代理已删除')
}

async function validateProxies() {
  const job = await run(() => validateActiveProxies(), '代理验证已开始')
  if (!job?.id) return

  proxyValidationJob.value = job
  proxyLogs.value = job.logs || []
  proxyPolling.value = true
  pollProxyValidation(job.id)
}

async function pollProxyValidation(jobId) {
  while (proxyPolling.value) {
    await new Promise((resolve) => setTimeout(resolve, 1000))
    try {
      const job = await getProxyValidationJob(jobId)
      proxyValidationJob.value = job
      proxyLogs.value = job.logs || []
      if (job.status === 'completed' || job.status === 'failed') {
        proxyPolling.value = false
        notice.value =
          job.status === 'completed'
            ? `代理验证完成：可用 ${job.valid}，不可用 ${job.invalid}`
            : '代理验证任务失败，请查看日志'
        await refreshProxies()
      }
    } catch (err) {
      proxyPolling.value = false
      error.value = err.message
    }
  }
}

async function refreshProxyValidation() {
  if (!proxyValidationJob.value?.id) return
  await run(async () => {
    const job = await getProxyValidationJob(proxyValidationJob.value.id)
    proxyValidationJob.value = job
    proxyLogs.value = job.logs || []
    await refreshProxies()
    return job
  }, '日志已刷新')
}

async function authorize(account) {
  const result = await run(() => startOAuth(account.id), '正在打开授权页面')
  if (result?.url) {
    window.location.href = result.url
  }
}

async function authorizeWithPlaywright(account) {
  const result = await run(
    () => startPlaywrightOAuth(account.id),
    '已启动 Playwright 授权窗口，请在弹出的浏览器中完成 Microsoft 授权'
  )
  if (result?.session_id) {
    oauthSession.value = {
      id: result.session_id,
      status: 'created',
      email: account.email,
      proxy: result.proxy,
      logs: [],
    }
    oauthLogs.value = []
  }
}

async function refreshOAuthSession() {
  if (!oauthSession.value?.id) return
  await run(async () => {
    const session = await getOAuthSession(oauthSession.value.id)
    oauthSession.value = session
    oauthLogs.value = session.logs || []
    await refreshAccounts()
    await loadAuthorizedOutput()
    return session
  }, '授权日志已刷新')
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
  await Promise.all([refreshAccounts(), refreshProxies(), loadAuthorizedOutput({ silent: true })])
})
</script>

<template>
  <main class="shell">
    <aside class="sidebar">
      <div class="brand">
        <h1>Outlook 管理器</h1>
        <span>本机版 MVP</span>
      </div>

      <section class="quick-actions">
        <button class="primary" :disabled="loading" @click="openImport('accounts')">导入账号</button>
        <button :disabled="loading" @click="openImport('proxies')">导入代理</button>
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
          <small>{{ statusText(account.status) }}</small>
        </button>
      </section>

      <section class="panel proxy-panel">
        <div class="panel-title">代理池</div>
        <div class="proxy-actions">
          <button :disabled="loading || proxyPolling" @click="validateProxies">验证代理</button>
          <span>{{ proxies.length }} 个代理</span>
        </div>
        <div v-if="proxyValidationJob" class="proxy-progress">
          <span>{{ proxyValidationJob.status }}</span>
          <span>
            {{ proxyValidationJob.checked }}/{{ proxyValidationJob.total }}
            可用 {{ proxyValidationJob.valid }} / 不可用 {{ proxyValidationJob.invalid }}
          </span>
          <button :disabled="loading" @click="refreshProxyValidation">刷新日志</button>
        </div>
        <div v-if="proxyLogs.length" class="log-panel">
          <div v-for="(log, index) in proxyLogs" :key="index" class="log-line">
            <time>{{ log.time }}</time>
            <span>{{ log.message }}</span>
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

      <section class="output-section">
        <div class="section-head">
          <h3>授权输出</h3>
          <span>{{ authorizedOutputCount }} 个已授权账号</span>
        </div>
        <div class="output-body">
          <textarea
            v-model="authorizedOutput"
            readonly
            spellcheck="false"
            placeholder="授权成功后会生成：user@hotmail.com----密码----client_id----refresh_token"
          />
          <div class="output-actions">
            <button :disabled="loading" @click="loadAuthorizedOutput">刷新输出</button>
            <button class="primary" :disabled="loading" @click="copyAuthorizedOutput">复制全部</button>
          </div>
        </div>
      </section>

      <section v-if="oauthSession" class="auth-log-section">
        <div class="section-head">
          <h3>Playwright 授权</h3>
          <span>{{ oauthSession.email }} · {{ statusText(oauthSession.status) }}</span>
        </div>
        <div class="auth-log-body">
          <div class="auth-meta">
            <span>Session: {{ oauthSession.id }}</span>
            <span>代理: {{ oauthSession.proxy?.server || '未使用代理' }}</span>
            <button :disabled="loading" @click="refreshOAuthSession">刷新授权日志</button>
          </div>
          <div v-if="oauthLogs.length" class="log-panel wide-log-panel">
            <div v-for="(log, index) in oauthLogs" :key="index" class="log-line">
              <time>{{ log.time }}</time>
              <span>{{ log.message }}</span>
            </div>
          </div>
        </div>
      </section>

      <section class="management-grid">
        <div class="management-section">
          <div class="section-head">
            <h3>邮箱列表</h3>
            <span>{{ accounts.length }} 个账号</span>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>邮箱</th>
                  <th>状态</th>
                  <th>授权方式</th>
                  <th>最近同步</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="account in accounts"
                  :key="account.id"
                  :class="{ selected: account.id === selectedAccountId }"
                  @click="selectAccount(account)"
                >
                  <td class="strong-cell">{{ account.email }}</td>
                  <td><span class="status-pill" :data-status="account.status">{{ statusText(account.status) }}</span></td>
                  <td>{{ account.auth_mode }}</td>
                  <td>{{ account.last_sync_at || '-' }}</td>
                  <td class="row-actions">
                    <button @click.stop="removeAccount(account)">删除</button>
                  </td>
                </tr>
                <tr v-if="!accounts.length">
                  <td colspan="5" class="empty-cell">暂无账号</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div class="management-section">
          <div class="section-head">
            <h3>代理列表</h3>
            <span>{{ proxies.length }} 个代理</span>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>代理</th>
                  <th>类别</th>
                  <th>状态</th>
                  <th>用户名</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="proxy in proxies" :key="proxy.id">
                  <td class="mono-cell">{{ proxy.host }}:{{ proxy.port }}</td>
                  <td>{{ proxy.type }}</td>
                  <td><span class="status-pill" :data-status="proxy.status">{{ statusText(proxy.status) }}</span></td>
                  <td>{{ proxy.username || '-' }}</td>
                  <td class="row-actions">
                    <button @click="removeProxy(proxy)">删除</button>
                  </td>
                </tr>
                <tr v-if="!proxies.length">
                  <td colspan="5" class="empty-cell">暂无代理</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

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

    <div v-if="importModalOpen" class="modal-backdrop" @click.self="closeImport">
      <section class="modal">
        <div class="modal-head">
          <div>
            <h3>{{ importTitle }}</h3>
            <p>{{ importDescription }}</p>
          </div>
          <button class="icon-button" @click="closeImport">×</button>
        </div>
        <textarea v-model="importModel" spellcheck="false" />
        <div class="modal-actions">
          <button @click="closeImport">取消</button>
          <button class="primary" :disabled="loading" @click="submitImport">确认导入</button>
        </div>
      </section>
    </div>
  </main>
</template>
