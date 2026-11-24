import { expect, test } from '@playwright/test';

test('flight catalogue, selection, matching, detail and map are React-owned', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '航班', exact: true }).click();
  await expect(page.locator('.sheet-table tbody tr')).toHaveCount(15);
  await page.getByPlaceholder('航班号 / ID').fill('F01');
  await page.getByRole('button', { name: '过滤', exact: true }).click();
  await expect(page.locator('.sheet-table tbody tr')).toHaveCount(1);
  await page.locator('.sheet-table tbody [role="checkbox"]').first().click();
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
  await page.locator('.selected-chip').first().hover();
  await page.locator('.selected-chip').getByRole('switch', { name: /轨迹/ }).click();
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
  await expect(page.getByText('搜索: F00')).toBeVisible();
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
  const splitDragger = page.getByTestId('workspace-split-handle');
  await expect(splitDragger).toBeVisible();
  const splitBox = await splitDragger.boundingBox();
  const firstPanel = page.locator('.workspace-pane').first();
  const widthBefore = await firstPanel.evaluate(element => element.getBoundingClientRect().width);
  expect(splitBox).not.toBeNull();
  await page.mouse.move(splitBox!.x + splitBox!.width / 2, splitBox!.y + splitBox!.height / 2);
  await page.mouse.down();
  await page.mouse.move(splitBox!.x + 80, splitBox!.y + splitBox!.height / 2);
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
  await expect(page.getByTestId('workspace-split-handle')).toBeVisible();
});

test('map sidebar can isolate one displayed flight and restore all flights', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '航班', exact: true }).click();
  await page.locator('.sheet-table tbody [role="checkbox"]').nth(0).click();
  await page.locator('.sheet-table tbody [role="checkbox"]').nth(1).click();
  await page.getByRole('button', { name: '所选加入地图', exact: true }).click();
  await expect(page.locator('.flight-map-label')).toHaveCount(2);
  const firstChip = page.locator('.selected-chip').first();
  await firstChip.hover();
  const isolate = page.locator('.flight-isolate-action').first();
  await isolate.click();
  await expect(isolate).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('.flight-map-label')).toHaveCount(1);
  await isolate.click();
  await expect(page.locator('.flight-map-label')).toHaveCount(2);
});

test('match one flight directly from the map sidebar', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '航班', exact: true }).click();
  await page.getByRole('button', { name: '加入地图', exact: true }).first().click();
  await page.getByRole('button', { name: '地图', exact: true }).click();
  const chip = page.locator('.selected-chip').first();
  const match = chip.getByRole('button', { name: /^匹配路径 / });
  const submitted = page.waitForRequest(request => request.method() === 'POST' && new URL(request.url()).pathname === '/api/matches');
  await match.click();
  expect((await submitted).postDataJSON().flight_keys).toHaveLength(1);
  // The fixture has no runway. The failed result must reach the map and allow retry.
  await expect(match).toHaveAttribute('title', /上次匹配失败/);
  await expect(match).toBeEnabled();
  await expect(page.locator('.map-view')).toBeVisible();
});

test('all filtered flights can be displayed without a ten-flight cap', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '航班', exact: true }).click();
  const detailRequests: string[] = [];
  page.on('request', request => {
    const pathname = new URL(request.url()).pathname;
    if (/^\/api\/flights\/[^/]+$/.test(pathname)) detailRequests.push(pathname);
  });
  await page.getByRole('checkbox', { name: '选择全部结果', exact: true }).click();
  await expect(page.getByText('已选 18 条')).toBeVisible();
  await page.getByRole('button', { name: '所选加入地图', exact: true }).click();
  await expect(page.locator('.map-selection .selected-chip')).toHaveCount(18);
  expect(detailRequests).toHaveLength(0);
});

test('cross-page select all excludes flights outside the filter', async ({ page }) => {
  const matching = await (await page.request.get('/api/flight-selection?q=F0')).json();
  const outside = await (await page.request.get('/api/flight-selection?q=F17')).json();
  const selection = [...matching.flight_keys.slice(0, -1), ...outside.flight_keys];
  await page.addInitScript(keys => {
    sessionStorage.setItem('airport-flight-workbench:default', JSON.stringify({
      filters: { query: 'F0' }, matchSelection: keys,
    }));
  }, selection);
  await page.route('**/api/flights?**', route => {
    const url = new URL(route.request().url());
    url.searchParams.set('page_size', '5');
    return route.continue({ url: url.toString() });
  });
  await page.goto('/');
  await page.getByRole('button', { name: '航班', exact: true }).click();
  await expect(page.getByRole('checkbox', { name: '选择本页航班' })).toBeChecked();
  const selectAll = page.getByRole('checkbox', { name: '选择全部结果' });
  await expect(selectAll).not.toBeChecked();
  await selectAll.click();
  await expect(page.getByText('已选 11 条')).toBeVisible();
  await expect(selectAll).toBeChecked();
});

test('selection and map display survive paging and reload', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '航班', exact: true }).click();
  await page.locator('.sheet-table tbody [role="checkbox"]').first().click();
  await page.getByRole('button', { name: '下一页', exact: true }).click();
  await expect(page.locator('.sheet-table tbody tr')).toHaveCount(3);
  await page.locator('.sheet-table tbody [role="checkbox"]').first().click();
  await expect(page.getByText('已选 2 条')).toBeVisible();
  await page.getByRole('button', { name: '所选加入地图', exact: true }).click();
  await expect(page.locator('.map-selection .selected-chip')).toHaveCount(2);
  await page.reload();
  await expect(page.getByRole('button', { name: '航班', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '航班', exact: true }).click();
  await expect(page.getByText('已选 2 条')).toBeVisible();
  await expect(page.locator('.map-selection .selected-chip')).toHaveCount(2);
});

test('stand and date range filters default to dataset bounds and validate before committing', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '航班', exact: true }).click();
  await page.getByRole('button', { name: /更多筛选/ }).click();
  const dateRangeButton = page.getByRole('button', { name: '日期范围' });
  await expect(dateRangeButton).toContainText(/\d{4}-\d{2}-\d{2} 至 \d{4}-\d{2}-\d{2}/);
  await dateRangeButton.click();
  await expect(page.getByRole('button', { name: '恢复全部日期', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '确定', exact: true }).click();
  await page.getByRole('checkbox', { name: '空机位', exact: true }).click();
  await page.getByRole('button', { name: '应用', exact: true }).click();
  await expect(page.locator('.sheet-table tbody tr')).toHaveCount(15);
  await expect(page.getByText('机位: 空机位')).toBeVisible();
  await page.getByRole('button', { name: /更多筛选/ }).click();
  await page.getByLabel('最小观测点数').fill('20');
  await page.getByLabel('最大观测点数').fill('10');
  await page.getByRole('button', { name: '应用', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('最小观测点数不得大于最大观测点数');
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

test('recommend a stand for an empty arrival and save the selected candidate', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '航班', exact: true }).click();
  await page.getByPlaceholder('航班号 / ID').fill('F02');
  await page.getByRole('button', { name: '过滤', exact: true }).click();
  const row = page.locator('.sheet-table tbody tr').filter({ hasText: 'F02' });
  await row.getByRole('button', { name: '选择机位', exact: true }).click();
  const editor = page.getByRole('dialog', { name: '编辑 F02 机位' });
  await editor.getByRole('button', { name: '推荐机位' }).click();
  await expect(editor.getByText('高置信度')).toBeVisible();
  await editor.getByRole('radio', { name: 'A01' }).check();
  await editor.getByRole('button', { name: '取消' }).click();
  await row.getByRole('button', { name: '选择机位', exact: true }).click();
  await editor.getByRole('button', { name: '推荐机位' }).click();
  await editor.getByRole('radio', { name: 'A01' }).check();
  await editor.getByRole('button', { name: '保存' }).click();
  await expect(row.getByRole('button', { name: 'A01', exact: true })).toBeVisible();
});

test('max points draft does not auto-fetch and advanced popover supports multi-select and chips', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '航班', exact: true }).click();
  await expect(page.locator('.sheet-table tbody tr')).toHaveCount(15);
  let flightRequests = 0;
  page.on('request', request => {
    if (new URL(request.url()).pathname === '/api/flights') flightRequests += 1;
  });
  await page.getByRole('button', { name: /更多筛选/ }).click();
  const maxInput = page.getByLabel('最大观测点数');
  await maxInput.fill('');
  await maxInput.fill('50');
  await page.waitForTimeout(150);
  expect(flightRequests).toBe(0);
  await maxInput.fill('');
  await page.getByRole('checkbox', { name: '空机位', exact: true }).click();
  await page.getByRole('checkbox', { name: 'A01', exact: true }).click();
  await page.getByRole('button', { name: '应用', exact: true }).click();
  await expect(page.getByText('机位: 空机位, A01')).toBeVisible();
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
  const zoomOut = page.locator('.leaflet-control-zoom-out');
  for (let i = 0; i < 10; i += 1) {
    await zoomOut.click();
  }
  await expect(zoomOut).not.toHaveClass(/leaflet-disabled/);
});

test('full-screen flight table auto-collapses right rail and restores it on map view', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('.right-rail')).toBeVisible();
  await page.getByRole('button', { name: '航班', exact: true }).click();
  await expect(page.locator('.right-rail')).toHaveCount(0);
  await page.getByRole('button', { name: '地图', exact: true }).click();
  await expect(page.locator('.right-rail')).toBeVisible();
});

test('split view keeps filter controls unclipped within narrow pane', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '地图', exact: true }).dragTo(page.locator('.workspace'), { targetPosition: { x: 120, y: 240 } });
  const sheet = page.locator('#flight-sheet');
  const filterBtn = page.getByRole('button', { name: '过滤', exact: true });
  await expect(filterBtn).toBeVisible();
  const [sheetBox, btnBox] = await Promise.all([sheet.boundingBox(), filterBtn.boundingBox()]);
  expect(sheetBox).not.toBeNull();
  expect(btnBox).not.toBeNull();
  expect(btnBox!.x + btnBox!.width).toBeLessThanOrEqual(sheetBox!.x + sheetBox!.width + 1);
});

test('clicking a flight on map highlights sidebar item, opens detail from sidebar, and resizes list height', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '航班', exact: true }).click();
  await page.getByRole('button', { name: '加入地图', exact: true }).first().click();
  await page.getByRole('button', { name: '地图', exact: true }).click();
  await page.locator('.flight-map-label').first().click();
  await expect(page.locator('.map-selection .selected-chip').first()).toHaveAttribute('data-highlighted', 'true');
  const listResizer = page.getByRole('separator', { name: '调整地图展示列表高度' });
  await listResizer.focus();
  await listResizer.press('ArrowDown');
  await expect(listResizer).toHaveAttribute('aria-valuenow', '63');
  await page.locator('.map-selection .selected-chip').first().getByRole('button', { name: '详情', exact: true }).click();
  await expect(page.locator('.observations-view')).toBeVisible();
});
