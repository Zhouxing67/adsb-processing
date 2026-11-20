import { expect, test } from '@playwright/test';

test('graph editor is a single React application and edits properties', async ({ page }) => {
  const requests: string[] = [];
  page.on('request', request => requests.push(new URL(request.url()).pathname));
  await page.goto('/');
  await expect(page.getByText('2 节点 · 1 边')).toBeVisible();
  await expect(page.getByRole('navigation', { name: '编辑工具' })).toBeVisible();
  expect(requests).not.toContain('/api/flights');
  await page.getByRole('button', { name: /搜索/ }).click();
  await page.getByPlaceholder('节点 ID 或边 ID').fill('(1, 2, 0)');
  await page.getByRole('button', { name: '选中', exact: true }).click();
  await expect(page.locator('.details')).toBeVisible();
  await page.locator('.property-form label').filter({ hasText: 'name' }).locator('input').fill('Updated Stand');
  await page.getByRole('button', { name: '保存属性', exact: true }).click();
  await expect(page.getByRole('button', { name: /撤销/ })).toBeEnabled();
  await expect.poll(async () => (await (await page.request.get('/api/state')).json()).edges.features[0].properties.name).toBe('Updated Stand');
  await page.getByRole('button', { name: /撤销/ }).click();
  await expect.poll(async () => (await (await page.request.get('/api/state')).json()).edges.features[0].properties.name).toBe('Stand A');
});

test('topology panel and map layer control remain available', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /拓扑检查/ }).click();
  await expect(page.getByRole('heading', { name: '拓扑概览' })).toBeVisible();
  await expect(page.locator('.leaflet-control-layers')).toBeVisible();
  await page.getByRole('button', { name: /开启相邻边辨色/ }).click();
  await expect(page.getByRole('button', { name: /关闭相邻边辨色/ })).toBeVisible();
});
