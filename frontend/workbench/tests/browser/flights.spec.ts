import { test, expect } from '@playwright/test';
test('draft filters, cross-page selection, detail navigation and split', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('.sheet-table tbody tr')).toHaveCount(15);
  await page.locator('#observations-tab').click();
  await expect(page.locator('#flight-sheet')).toBeVisible();
  await expect(page.getByRole('button', { name: '编辑图', exact: true })).toHaveCount(0);
  await page.locator('#flight-movement').selectOption('departure');
  await page.locator('#flight-next').click();
  await expect(page.locator('.sheet-table tbody tr')).toHaveCount(3);
  await page.getByRole('checkbox', { name: '选择本页航班', exact: true }).check();
  await page.locator('#flight-prev').click();
  await expect(page.locator('.sheet-table tbody tr')).toHaveCount(15);
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

test('stand search, multiple selections, empty stands and inclusive dates', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('.sheet-table tbody tr')).toHaveCount(15);
  await page.locator('#observations-tab').click();
  await expect(page.locator('#flight-sheet')).toBeVisible();

  const picker = page.locator('#flight-stands');
  await picker.locator('summary').click();
  const search = page.getByRole('searchbox', { name: '搜索机位' });
  await search.fill('a01');
  await picker.getByRole('checkbox', { name: 'A01', exact: true }).check();
  await search.fill('D02');
  await picker.getByRole('checkbox', { name: 'D02', exact: true }).check();
  await search.press('Escape');
  await page.evaluate(() => {
    const showPicker = HTMLInputElement.prototype.showPicker;
    HTMLInputElement.prototype.showPicker = function () {
      showPicker.call(this);
      this.dataset.pickerOpened = 'true';
    };
  });
  await page.getByRole('button', { name: '起始日期', exact: true }).click();
  await expect(page.locator('#flight-start-date')).toHaveAttribute('data-picker-opened', 'true');
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: '终止日期', exact: true }).click();
  await expect(page.locator('#flight-end-date')).toHaveAttribute('data-picker-opened', 'true');
  await page.keyboard.press('Escape');
  await page.locator('#flight-start-date').fill('2024-01-01');
  await page.locator('#flight-end-date').fill('2024-01-01');
  await expect(page.getByRole('button', { name: '起始日期 2024-01-01' })).toBeVisible();
  await page.getByRole('button', { name: '过滤', exact: true }).click();
  await expect(page.locator('.sheet-table tbody tr')).toHaveCount(2);
  await expect(page.locator('.stand-cell')).toHaveText(['A01', 'D02']);
  await page.getByRole('button', { name: '全部结果' }).click();
  await expect(page.locator('.sheet-selected-count')).toHaveText('已选 2 条');

  await page.getByRole('button', { name: '重置', exact: true }).click();
  await expect(page.getByRole('button', { name: '起始日期', exact: true })).toBeVisible();
  await picker.locator('summary').click();
  await picker.getByRole('checkbox', { name: '空机位', exact: true }).check();
  await page.getByRole('button', { name: '过滤', exact: true }).click();
  await expect(page.locator('#sheet-page-summary')).toContainText('16 条');

  await page.locator('#flight-start-date').fill('2024-01-02');
  await page.locator('#flight-end-date').fill('2024-01-01');
  await page.getByRole('button', { name: '过滤', exact: true }).click();
  await expect(page.locator('#flight-query-error')).toBeVisible();
});
