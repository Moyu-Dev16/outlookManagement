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

page.on('framenavigated', async (frame) => {
  if (frame !== page.mainFrame()) return
  const url = frame.url()
  log(`navigated: ${url}`)
  if (url.includes('oauth=success') || url.includes('oauth=failed')) {
    log('OAuth callback reached, closing browser soon')
    setTimeout(async () => {
      await context.close()
    }, 3000)
  }
})
