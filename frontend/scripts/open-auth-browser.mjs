import { chromium } from 'playwright'

const [, , authUrl, profileDir, proxyJson = '{}'] = process.argv

if (!authUrl || !profileDir) {
  console.error('Usage: node open-auth-browser.mjs <auth-url> <profile-dir> [proxy-json]')
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

const context = await chromium.launchPersistentContext(profileDir, {
  headless: false,
  proxy,
  viewport: { width: 1280, height: 860 },
})

const page = context.pages()[0] || await context.newPage()
await page.goto(authUrl)

page.on('framenavigated', async (frame) => {
  if (frame !== page.mainFrame()) return
  const url = frame.url()
  if (url.includes('oauth=success') || url.includes('oauth=failed')) {
    setTimeout(async () => {
      await context.close()
    }, 3000)
  }
})
