import { expect, test } from '@playwright/test'

const accounts = [
  {
    id: 1,
    email: 'demo@outlook.com',
    auth_mode: 'graph_oauth',
    status: 'not_authorized',
    proxy_id: null,
    last_sync_at: null,
    last_error: null,
    created_at: '2026-06-05 00:00:00',
  },
]

test.beforeEach(async ({ page }) => {
  let imported = false

  await page.route('**/api/accounts', async (route) => {
    await route.fulfill({
      json: imported ? accounts : [],
    })
  })

  await page.route('**/api/accounts/import', async (route) => {
    imported = true
    await route.fulfill({
      json: { parsed: 1, created: 1, updated: 0 },
    })
  })

  await page.route('**/api/proxies', async (route) => {
    await route.fulfill({ json: [] })
  })

  await page.route('**/api/proxies/import', async (route) => {
    await route.fulfill({
      json: { parsed: 2, created: 2, updated: 0 },
    })
  })

  await page.route('**/api/accounts/1/folders', async (route) => {
    await route.fulfill({
      json: [
        {
          id: 10,
          account_id: 1,
          provider_folder_id: 'inbox',
          display_name: 'Inbox',
          well_known_name: 'inbox',
          unread_count: 1,
          total_count: 2,
          synced_at: '2026-06-05 00:00:00',
        },
      ],
    })
  })

  await page.route('**/api/accounts/1/messages**', async (route) => {
    await route.fulfill({
      json: [
        {
          id: 100,
          account_id: 1,
          folder_id: 10,
          sender: 'sender@example.com',
          subject: 'Hello Outlook',
          snippet: 'Message preview',
          received_at: '2026-06-05T00:00:00Z',
          is_read: false,
        },
      ],
    })
  })

  await page.route('**/api/imap/accounts/1/sync', async (route) => {
    await route.fulfill({
      json: { mode: 'imap_app_password', folders: 1, messages: 1 },
    })
  })

  await page.route('**/api/sync/accounts/1', async (route) => {
    await route.fulfill({
      json: { folders: 1, messages: 1 },
    })
  })
})

test('imports an account and displays synced mailbox data', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'Outlook 管理器' })).toBeVisible()
  await page.getByRole('button', { name: '导入账号' }).click()

  await expect(page.getByRole('button', { name: /demo@outlook\.com/ })).toBeVisible()
  await expect(page.getByText('not_authorized')).toBeVisible()

  await page.getByRole('button', { name: 'IMAP 试同步' }).click()

  await expect(page.getByText('IMAP 同步完成')).toBeVisible()
  await expect(page.getByRole('button', { name: /Inbox/ })).toBeVisible()
  await expect(page.getByText('Hello Outlook')).toBeVisible()
  await expect(page.getByText('Message preview')).toBeVisible()
})
