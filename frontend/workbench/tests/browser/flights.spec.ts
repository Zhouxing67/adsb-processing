import { expect, test } from '@playwright/test';

test('flight catalogue, selection, matching, detail and map are React-owned', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '航班', exact: true }).click();
  await expect(page.locator('.sheet-table tbody tr')).toHaveCount(15);
  await page.getByPlaceholder('航班号 / ID').fill('F01');
  await page.getByRole('button', { name: '过滤', exact: true }).click();
  await expect(page.locator('.sheet-table tbody tr')).toHaveCount(1);
  await page.locator('.sheet-table tbody input[type=checkbox]').check();
  await expect(page.getByText('已选 1 条')).toBeVisible();
  await page.getByRole('button', { name: '匹配所选航班', exact: true }).click();
  await expect(page.getByRole('button', { name: '匹配所选航班', exact: true })).toBeEnabled({ timeout: 20_000 });
  await page.getByRole('button', { name: '详情', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'F01' })).toBeVisible();
  await expect(page.locator('.observations-content tbody tr')).toHaveCount(3);
  await page.getByRole('button', { name: '航班列表', exact: false }).click();
  await page.getByRole('button', { name: '加入地图', exact: true }).first().click();
  await expect(page.getByRole('button', { name: '移出地图', exact: true }).first()).toBeVisible();
  await page.getByRole('button', { name: '地图', exact: true }).click();
  await expect(page.locator('#map canvas')).not.toHaveCount(0);
});

test('filter draft is committed explicitly and reset restores catalogue', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '航班', exact: true }).click();
  await expect(page.locator('.sheet-table tbody tr')).toHaveCount(15);
  await page.getByPlaceholder('航班号 / ID').fill('F00');
  await expect(page.locator('.sheet-table tbody tr')).toHaveCount(15);
  await page.getByRole('button', { name: '过滤', exact: true }).click();
  await expect(page.locator('.sheet-table tbody tr')).toHaveCount(1);
  await page.getByRole('button', { name: '重置', exact: true }).click();
  await expect(page.locator('.sheet-table tbody tr')).toHaveCount(15);
});

test('selection and map display survive paging and reload', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '航班', exact: true }).click();
  await page.locator('.sheet-table tbody input[type=checkbox]').first().check();
  await page.getByRole('button', { name: '下一页', exact: true }).click();
  await expect(page.locator('.sheet-table tbody tr')).toHaveCount(3);
  await page.locator('.sheet-table tbody input[type=checkbox]').first().check();
  await expect(page.getByText('已选 2 条')).toBeVisible();
  await page.getByRole('button', { name: '所选加入地图', exact: true }).click();
  await expect(page.locator('.map-selection .selected-chip')).toHaveCount(2);
  await page.reload();
  await expect(page.getByRole('button', { name: '航班', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '航班', exact: true }).click();
  await expect(page.getByText('已选 2 条')).toBeVisible();
  await expect(page.locator('.map-selection .selected-chip')).toHaveCount(2);
});

test('stand/date filters validate before committing', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '航班', exact: true }).click();
  await page.locator('summary').filter({ hasText: '机位' }).click();
  await page.getByRole('checkbox', { name: '空机位' }).check();
  await page.getByRole('button', { name: '过滤', exact: true }).click();
  await expect(page.locator('.sheet-table tbody tr')).toHaveCount(15);
  await page.getByLabel('起始日期').fill('2024-01-02');
  await page.getByLabel('结束日期').fill('2024-01-01');
  await page.getByRole('button', { name: '过滤', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('起始日期不得晚于终止日期');
});
