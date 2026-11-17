import { test, expect } from '@playwright/test';
test('draft filters, cross-page selection, detail navigation and split', async ({ page }) => {
  await page.goto('/');
  await page.locator('#observations-tab').click();
  await expect(page.locator('.sheet-table tbody tr')).toHaveCount(15);
  await page.locator('#flight-movement').selectOption('departure');
  await page.locator('#flight-next').click();
  await expect(page.locator('.sheet-table tbody tr')).toHaveCount(3);
  await page.getByRole('checkbox', { name: '选择本页航班', exact: true }).check();
  await page.locator('#flight-prev').click();
  await page.getByRole('checkbox', { name: '选择本页航班', exact: true }).check();
  await expect(page.locator('.sheet-selected-count')).toHaveText('已选 18 条');
  await page.getByRole('button', { name: '过滤', exact: true }).click();
  await expect(page.locator('.sheet-table tbody tr')).toHaveCount(9);
  page.once('dialog', dialog => void dialog.accept());
  await page.getByRole('button', { name: '匹配所选航班', exact: true }).click();
  await expect(page.locator('#match-progress-text')).toContainText('等待 0 · 运行 0', { timeout: 20000 });

  await page.getByRole('button', { name: '详情', exact: true }).first().click();
  await expect(page.locator('#observations-view')).toBeVisible();
  await page.getByRole('button', { name: '在地图中定位', exact: true }).first().click();
  await expect(page.locator('#map-view')).toBeVisible();
  const map = page.locator('#map-view');const bounds = await map.boundingBox();
  if (!bounds) throw new Error('Map bounds missing');
  await page.locator('#observations-tab').dragTo(map, { targetPosition: { x: bounds.width * .8, y: bounds.height * .4 } });
  await expect(page.locator('#map-view')).toBeVisible();
  await expect(page.locator('#flight-sheet')).toBeVisible();
});
