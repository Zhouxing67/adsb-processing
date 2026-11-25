import { expect, test } from '@playwright/test';

test('graph editor is a single React application and edits properties', async ({ page }) => {
  const requests: string[] = [];
  page.on('request', request => requests.push(new URL(request.url()).pathname));
  await page.goto('/');
  await expect(page.getByText('2 节点 · 1 边')).toBeVisible();
  await page.getByRole('button', { name: '编辑图', exact: true }).click();
  await expect(page.getByRole('navigation', { name: '编辑工具' })).toBeVisible();
  await expect(page.getByRole('button', { name: /删除 \/ 简化/ })).toBeVisible();
  expect(requests).not.toContain('/api/flights');
  await page.getByRole('button', { name: /搜索/ }).click();
  await page.getByPlaceholder('节点 ID 或完整边 ID').fill('1—2 · 0');
  await page.getByRole('button', { name: '选中', exact: true }).click();
  await expect(page.locator('.details')).toBeVisible();
  await page.locator('.property-form label').filter({ hasText: 'name' }).locator('input').fill('Updated Stand');
  await page.getByRole('button', { name: '保存属性', exact: true }).click();
  await expect(page.getByRole('button', { name: /撤销/ })).toBeEnabled();
  await expect.poll(async () => (await (await page.request.get('/api/state')).json()).edges.features[0].properties.name).toBe('Updated Stand');
  await page.getByRole('button', { name: /撤销/ }).click();
  await expect.poll(async () => (await (await page.request.get('/api/state')).json()).edges.features[0].properties.name).toBe('Stand A');
});

test('topology panel and inspector layer controls remain available', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /拓扑检查/ }).click();
  await expect(page.getByRole('heading', { name: '拓扑概览' })).toBeVisible();
  await page.getByRole('button', { name: '编辑图', exact: true }).click();
  await expect(page.getByRole('heading', { name: '拓扑概览' })).toBeVisible();
  await expect(page.getByRole('navigation', { name: '编辑工具' })).toBeVisible();
  await expect(page.getByRole('radio', { name: '无底图（精细编辑）' })).toBeChecked();
  await expect(page.getByRole('checkbox', { name: /图节点/ })).not.toBeChecked();
  await page.getByRole('button', { name: /开启相邻边辨色/ }).click();
  await expect(page.getByRole('button', { name: /关闭相邻边辨色/ })).toBeVisible();
});

test('merge workflow exposes backend candidates in a React dialog', async ({ page }) => {
  const requests: string[] = [];
  page.on('request', request => requests.push(new URL(request.url()).pathname));
  await page.goto('/');
  await page.getByRole('button', { name: '编辑图', exact: true }).click();
  await page.getByRole('button', { name: /合并重合节点/ }).click();
  await page.getByRole('button', { name: '重复节点候选', exact: true }).click();
  await expect(page.getByRole('heading', { name: '疑似重复图节点' })).toBeVisible();
  expect(requests).toContain('/api/merge-candidates');
  await page.getByRole('button', { name: /查看/ }).click();
  await expect(page.getByRole('heading', { name: '疑似重复图节点' })).not.toBeVisible();
});

test('editing auto-opens collapsed right rail on selection and guards empty search', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '切换右侧栏', exact: true }).click();
  await expect(page.locator('.right-rail')).toHaveCount(0);
  await page.getByRole('button', { name: /搜索/ }).click();
  await page.getByRole('button', { name: '选中', exact: true }).click();
  await expect(page.locator('.status')).toContainText('请输入节点 ID 或边 ID');
  await expect(page.locator('.details')).toHaveCount(0);
  await page.getByPlaceholder('节点 ID 或完整边 ID').fill('1—2 · 0');
  await page.getByRole('button', { name: '选中', exact: true }).click();
  await expect(page.locator('.details')).toBeVisible();
  await expect(page.locator('.property-form').getByRole('combobox')).toBeVisible();
});

test('direct map click selects both edges and top-pane nodes without pointer interception', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('checkbox', { name: /图节点/ }).click();
  const nodePath = page.locator('.leaflet-nodes-pane svg path.leaflet-interactive').first();
  await expect(nodePath).toBeVisible();
  await nodePath.click();
  await expect(page.locator('.details')).toBeVisible();
  await page.getByRole('button', { name: '关闭要素详情' }).click();
  const mapBox = await page.locator('#map').boundingBox();
  expect(mapBox).not.toBeNull();
  await page.mouse.click(mapBox!.x + mapBox!.width / 2, mapBox!.y + mapBox!.height / 2);
  await expect(page.locator('.details')).toContainText('1—2 · 0');
});
