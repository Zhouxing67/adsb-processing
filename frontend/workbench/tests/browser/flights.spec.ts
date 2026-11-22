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
  await page.getByRole('button', { name: '确认提交', exact: true }).click();
  await expect(page.getByRole('button', { name: '匹配所选航班', exact: true })).toBeEnabled({ timeout: 20_000 });
  await page.getByRole('button', { name: '详情', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'F01' })).toBeVisible();
  await expect(page.locator('.observations-content tbody tr')).toHaveCount(3);
  await page.getByRole('button', { name: '航班列表', exact: false }).click();
  await page.getByRole('button', { name: '加入地图', exact: true }).first().click();
  await expect(page.getByRole('button', { name: '移出地图', exact: true }).first()).toBeVisible();
  await page.getByRole('button', { name: '地图', exact: true }).click();
  await expect(page.locator('#map canvas')).not.toHaveCount(0);
  await expect(page.locator('.flight-map-label')).toHaveCount(1);
  await page.locator('.selected-chip label').filter({ hasText: '轨迹' }).getByRole('checkbox').uncheck();
  await expect(page.locator('.flight-map-label')).toHaveCount(0);
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

test('flight mode restores topology, drag split view and resizable rails', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /拓扑检查/ }).click();
  await expect(page.getByRole('heading', { name: '拓扑概览' })).toBeVisible();
  const workspace = page.locator('.workspace');
  await page.getByRole('button', { name: '地图', exact: true }).dragTo(workspace, { targetPosition: { x: 120, y: 240 } });
  await expect(page.locator('.map-view')).toBeVisible();
  await expect(page.locator('#flight-sheet')).toBeVisible();
  const splitDragger = page.locator('.ant-splitter-bar-dragger');
  await expect(splitDragger).toBeVisible();
  const splitBox = await splitDragger.boundingBox();
  const firstPanel = page.locator('.workspace-pane').first();
  const widthBefore = await firstPanel.evaluate(element => element.getBoundingClientRect().width);
  expect(splitBox).not.toBeNull();
  await page.mouse.move(splitBox.x + splitBox.width / 2, splitBox.y + splitBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(splitBox.x + 80, splitBox.y + splitBox.height / 2);
  await page.mouse.up();
  await expect.poll(() => firstPanel.evaluate(element => element.getBoundingClientRect().width)).toBeGreaterThan(widthBefore + 50);
  await expect.poll(() => page.evaluate(() => Number(localStorage.getItem('airport-workbench.map-split-width')))).toBeGreaterThan(50);
  const leftRail = page.getByRole('separator', { name: '调整左侧栏宽度' });
  await leftRail.focus();
  await leftRail.press('ArrowRight');
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--left-sidebar-width').trim())).toBe('312px');
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--right-sidebar-width').trim())).toBe('304px');
});

test('observation records can be split with the map by dragging the tab', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '航班', exact: true }).click();
  await page.getByRole('button', { name: '详情', exact: true }).first().click();
  await page.getByRole('button', { name: '观测记录', exact: true }).dragTo(page.locator('.workspace'), { targetPosition: { x: 700, y: 240 } });
  await expect(page.locator('.map-view')).toBeVisible();
  await expect(page.locator('.observations-view')).toBeVisible();
  await expect(page.locator('.ant-splitter-bar-dragger')).toBeVisible();
});

test('map sidebar can isolate one displayed flight and restore all flights', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '航班', exact: true }).click();
  await page.locator('.sheet-table tbody input[type=checkbox]').nth(0).check();
  await page.locator('.sheet-table tbody input[type=checkbox]').nth(1).check();
  await page.getByRole('button', { name: '所选加入地图', exact: true }).click();
  await expect(page.locator('.flight-map-label')).toHaveCount(2);
  const isolate = page.locator('.flight-isolate-action').first();
  await isolate.click();
  await expect(isolate).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('.flight-map-label')).toHaveCount(1);
  await isolate.click();
  await expect(page.locator('.flight-map-label')).toHaveCount(2);
});

test('all filtered flights can be displayed without a ten-flight cap', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '航班', exact: true }).click();
  const detailRequests: string[] = [];
  page.on('request', request => {
    const pathname = new URL(request.url()).pathname;
    if (/^\/api\/flights\/[^/]+$/.test(pathname)) detailRequests.push(pathname);
  });
  await page.getByRole('checkbox', { name: '选择全部结果', exact: true }).check();
  await expect(page.getByText('已选 18 条')).toBeVisible();
  await page.getByRole('button', { name: '所选加入地图', exact: true }).click();
  await expect(page.locator('.map-selection .selected-chip')).toHaveCount(18);
  expect(detailRequests).toHaveLength(0);
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
  await page.getByLabel('终止日期').fill('2024-01-01');
  await page.getByRole('button', { name: '过滤', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('起始日期不得晚于终止日期');
});

test('stand editing only accepts a catalogue option or empty stand', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '航班', exact: true }).click();
  await page.locator('.sheet-table tbody tr').first().locator('.stand-edit-trigger').click();
  const editor = page.getByRole('dialog', { name: /编辑 F\d+ 机位/ });
  await expect(editor).toBeVisible();
  await expect(editor.getByRole('radio', { name: '空机位' })).toBeVisible();
  await expect(editor.getByRole('radio', { name: 'D02' })).toBeVisible();
  await editor.getByRole('radio', { name: 'A01' }).check();
  await editor.getByRole('button', { name: '保存', exact: true }).click();
  await expect(page.locator('.sheet-table tbody tr').first().getByRole('button', { name: 'A01' })).toBeVisible();
});

test('max points draft does not auto-fetch and stand picker supports multi-select', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '航班', exact: true }).click();
  await expect(page.locator('.sheet-table tbody tr')).toHaveCount(15);
  let flightRequests = 0;
  page.on('request', request => {
    if (new URL(request.url()).pathname === '/api/flights') flightRequests += 1;
  });
  const maxInput = page.getByLabel('最大观测点数');
  await maxInput.fill('');
  await maxInput.fill('50');
  await page.waitForTimeout(150);
  expect(flightRequests).toBe(0);
  await page.locator('summary').filter({ hasText: '机位' }).click();
  await page.getByRole('checkbox', { name: '空机位' }).check();
  await expect(page.locator('.stand-options-panel')).toBeVisible();
  await page.getByRole('checkbox', { name: 'A01' }).check();
  await expect(page.locator('summary').filter({ hasText: '已选 2 个机位' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('.stand-options-panel')).not.toBeVisible();
});

test('locating an observation in split view preserves the observation table', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '航班', exact: true }).click();
  await page.getByRole('button', { name: '详情', exact: true }).first().click();
  await page.getByRole('button', { name: '观测记录', exact: true }).dragTo(page.locator('.workspace'), { targetPosition: { x: 700, y: 240 } });
  await expect(page.locator('.observations-view')).toBeVisible();
  await page.getByRole('button', { name: '在地图中定位' }).first().click();
  await expect(page.locator('.observations-view')).toBeVisible();
  await expect(page.locator('.flight-status-toast')).toContainText('已在地图中定位观测点');
});
