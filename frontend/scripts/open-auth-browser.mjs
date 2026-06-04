import { chromium } from 'playwright'

const [, , authUrl, profileDir] = process.argv

if (!authUrl || !profileDir) {
  console.error('Usage: node open-auth-browser.mjs <auth-url> <profile-dir>')
  process.exit(1)
}

const context = await chromium.launchPersistentContext(profileDir, {
  headless: false,
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
