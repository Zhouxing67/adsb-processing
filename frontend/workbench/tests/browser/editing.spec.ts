import { test, expect } from '@playwright/test';
test('property edit, undo, sidebar visibility and reload', async ({ page }) => {
  const requests: string[] = [];
  page.on('request', request => requests.push(new URL(request.url()).pathname));
  await page.goto('/');
  await expect(page.getByRole('button', { name: '编辑图', exact: true })).toBeVisible();
  await expect(page.locator('#observations-tab')).toHaveCount(0);
  await expect(page.locator('#flight-table-root')).toHaveCount(0);
  expect(requests).not.toContain('/api/flights');
  await page.getByRole('button', { name: '编辑图', exact: true }).click();
  await page.getByRole('button', { name: '搜索', exact: true }).click();
  await page.locator('#search-stand-ref').fill('A01');
  await page.locator('#search-stand-button').click();
  await expect(page.locator('[data-property="ref"]')).toHaveValue('A01');
  await expect(page.locator('.studio-inspector')).toBeVisible();
  await expect(page.locator('#map-view > #details')).toBeVisible();
  await page.getByRole('button', { name: '切换右侧栏', exact: true }).click();
  await expect(page.locator('.studio-inspector')).toBeHidden();
  await expect(page.locator('#map-view > #details')).toBeVisible();
  await page.getByRole('button', { name: '切换右侧栏', exact: true }).click();
  await page.locator('[data-property="name"]').fill('Updated Stand');
  await page.locator('#save-properties').click();
  await expect(page.getByRole('button', { name: '撤销', exact: true })).toBeEnabled();
  await expect.poll(async () => (await (await page.request.get('/api/state')).json()).edges.features[0].properties.name).toBe('Updated Stand');
  await page.getByRole('button', { name: '撤销', exact: true }).click();
  await expect.poll(async () => (await (await page.request.get('/api/state')).json()).edges.features[0].properties.name).toBe('Stand A');
  await page.getByRole('button', { name: '切换左侧栏', exact: true }).click();
  await expect(page.locator('#left-rail')).toBeHidden();
  await page.getByRole('button', { name: '切换左侧栏', exact: true }).click();
  await expect(page.locator('#left-rail')).toBeVisible();
  await page.reload();
  await expect(page.getByRole('button', { name: '编辑图', exact: true })).toBeVisible();
});


test('delete node opens half-edge pairing in the right rail', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '编辑图', exact: true }).click();
  await page.getByRole('menuitem', { name: '删除 / 简化' }).click();
  await page.getByRole('checkbox', { name: '图节点 (2)', exact: true }).check();
  const nodes = page.locator('.leaflet-nodes-pane .leaflet-interactive');
  await expect(nodes.first()).toBeVisible();
  await nodes.first().click({ force: true });
  await expect(page.locator('body > #details')).toBeVisible();
  await expect(page.locator('#details h2')).toHaveText('半边配对');
  await expect(page.locator('#details')).not.toHaveClass(/property-popup/);
  const panel = await page.locator('#details').boundingBox();
  const map = await page.locator('#map-view').boundingBox();
  expect(panel!.x).toBeGreaterThanOrEqual(map!.x + map!.width - 1);
});


test('stand overlay toggles independently and retains visibility on refresh', async ({ page }) => {
  await page.goto('/');
  const stand = page.getByRole('checkbox', { name: '停机位 (1)', exact: true });
  const edges = page.getByRole('checkbox', { name: '派生边 (0)', exact: true });
  const paths = page.locator('.leaflet-edges-pane path');
  await expect(stand).toBeChecked();
  await expect(paths).toHaveCount(1);
  await edges.uncheck();
  await expect(paths).toHaveCount(1);
  await stand.uncheck();
  await expect(paths).toHaveCount(0);
  await edges.check();
  await expect(paths).toHaveCount(0);
  await page.getByRole('button', { name: '编辑图', exact: true }).click();
  await expect(stand).not.toBeChecked();
  await stand.check();
  await expect(paths).toHaveCount(1);
});
