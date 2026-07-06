import { test, expect } from '@playwright/test'

test.describe('Dashboard', () => {
  test('loads without errors', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('text=Sindio')).toBeVisible()
  })

  test('metrics endpoint responds', async ({ page }) => {
    const response = await page.request.get('/api/v1/dashboard/metrics?system=power')
    expect(response.ok()).toBeTruthy()
  })
})
