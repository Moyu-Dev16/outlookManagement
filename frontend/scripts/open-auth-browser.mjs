import { chromium } from 'playwright'

const [, , authUrl, profileDir, proxyJson = '{}', metaJson = '{}'] = process.argv

if (!authUrl || !profileDir) {
  console.error('Usage: node open-auth-browser.mjs <auth-url> <profile-dir> [proxy-json] [meta-json]')
  process.exit(1)
}

let proxy = undefined
try {
  const parsed = JSON.parse(proxyJson)
  if (parsed.server) {
    proxy = parsed
  }
} catch {
  proxy = undefined
}

let meta = {}
try {
  meta = JSON.parse(metaJson)
} catch {
  meta = {}
}

function log(message) {
  const prefix = meta.email ? `[${meta.email}]` : '[oauth]'
  console.log(`${new Date().toISOString()} ${prefix} ${message}`)
  if (meta.apiBase && meta.sessionId) {
    fetch(`${meta.apiBase}/api/oauth/microsoft/sessions/${encodeURIComponent(meta.sessionId)}/logs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
    }).catch(() => {})
  }
}

function safeUrlForLog(rawUrl) {
  try {
    const url = new URL(rawUrl)
    if (url.searchParams.has('code')) url.searchParams.set('code', '[redacted]')
    if (url.searchParams.has('state')) url.searchParams.set('state', '[redacted]')
    return url.toString()
  } catch {
    return rawUrl
  }
}

async function fillFirstVisible(page, selectors, value, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    for (const selector of selectors) {
      const locator = page.locator(selector).first()
      try {
        if (await locator.isVisible({ timeout: 500 })) {
          await locator.click()
          await locator.fill(value)
          return true
        }
      } catch {}
    }
    await page.waitForTimeout(400)
  }
  return false
}

async function clickFirstVisible(page, selectors, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    for (const selector of selectors) {
      const locator = page.locator(selector).first()
      try {
        if (await locator.isVisible({ timeout: 500 })) {
          await locator.click()
          return true
        }
      } catch {}
    }
    await page.waitForTimeout(400)
  }
  return false
}

async function clickByText(page, texts, timeoutMs = 8000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    for (const text of texts) {
      const locator = page.getByText(text, { exact: false }).first()
      try {
        if (await locator.isVisible({ timeout: 500 })) {
          await locator.click()
          return true
        }
      } catch {}
    }
    await page.waitForTimeout(400)
  }
  return false
}

async function pageText(page) {
  try {
    return await page.locator('body').innerText({ timeout: 1500 })
  } catch {
    return ''
  }
}

async function handleEmailVerificationChoice(page) {
  const text = await pageText(page)
  const lowered = text.toLowerCase()
  const looksLikePrompt =
    lowered.includes('verify your email') ||
    text.includes('验证你的电子邮件') ||
    lowered.includes('send code') ||
    text.includes('发送验证码')

  if (!looksLikePrompt) return false
  log('detected Microsoft email verification prompt')
  if (await clickByText(page, ['使用密码', 'Use your password', 'Use password', '使用你的密码'], 5000)) {
    log('clicked password fallback on email verification prompt')
    await page.waitForTimeout(1200)
    return true
  }
  log('email verification prompt requires manual handling')
  return true
}

async function handleSecurityInfoConfirm(page) {
  const text = await pageText(page)
  const lowered = text.toLowerCase()
  const looksLikePrompt =
    text.includes('你的安全信息仍然准确吗') ||
    lowered.includes('security info') ||
    lowered.includes('is your security info still accurate')

  if (!looksLikePrompt) return false
  log('detected Microsoft security-info confirmation prompt')
  if (await clickByText(page, ['看起来不错', 'Looks good', 'Looks good!', '正确', 'Yes'], 5000)) {
    log('clicked security-info confirmation')
    await page.waitForTimeout(1200)
    return true
  }
  log('security-info confirmation requires manual handling')
  return true
}

async function handleCommonMicrosoftPrompts(page, rounds = 8) {
  for (let index = 0; index < rounds; index += 1) {
    let handled = false
    if (await handleSecurityInfoConfirm(page)) handled = true
    if (await handleEmailVerificationChoice(page)) handled = true

    const clicked = await clickFirstVisible(
      page,
      [
        'input[value="Yes"]',
        'button:has-text("Yes")',
        'button:has-text("Accept")',
        'input[value="Accept"]',
        'button:has-text("同意")',
        'button:has-text("接受")',
      ],
      1200,
    )
    if (clicked) {
      handled = true
      log('clicked a common Microsoft prompt button')
      await page.waitForTimeout(1200)
    }

    if (!handled) break
  }
}

log('launching Playwright OAuth browser')

const context = await chromium.launchPersistentContext(profileDir, {
  headless: false,
  proxy,
  viewport: { width: 1280, height: 860 },
})

const page = context.pages()[0] || await context.newPage()
await page.goto(authUrl, { waitUntil: 'domcontentloaded', timeout: 45000 })
log('Microsoft OAuth page opened')

if (meta.email) {
  const filledEmail = await fillFirstVisible(
    page,
    ['input[type="email"]', 'input[name="loginfmt"]'],
    meta.email,
    5000,
  )
  if (filledEmail) {
    log('filled email field')
    await clickFirstVisible(page, ['input[type="submit"]', 'button[type="submit"]'], 5000)
    await page.waitForTimeout(1200)
  }
}

handleCommonMicrosoftPrompts(page, 12).catch((error) => log(`prompt helper stopped: ${error.message}`))

page.on('framenavigated', async (frame) => {
  if (frame !== page.mainFrame()) return
  const url = frame.url()
  log(`navigated: ${safeUrlForLog(url)}`)
  handleCommonMicrosoftPrompts(page, 4).catch((error) => log(`prompt helper stopped: ${error.message}`))
  if (url.includes('oauth=success') || url.includes('oauth=failed')) {
    log('OAuth callback reached, closing browser soon')
    setTimeout(async () => {
      await context.close()
    }, 3000)
  }
})
