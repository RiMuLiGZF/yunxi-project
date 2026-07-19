/**
 * 模块管理 E2E 测试
 * @smoke @modules
 *
 * 覆盖场景：
 * 1. 模块列表页面加载
 * 2. 模块卡片显示正确
 * 3. 模块启停操作（mock 后端响应）
 * 4. 模块版本号显示
 */

const { test, expect } = require('../fixtures');

test.describe('模块管理 @smoke @modules', () => {

  test.beforeEach(async ({ authPage, navigate }) => {
    await navigate.toModules();
    await authPage.waitForLoadState('domcontentloaded');
  });

  // ------------------------------------------------------------
  // 测试 1：模块列表页面加载
  // ------------------------------------------------------------
  test('模块列表页面正常加载 - 标题和布局', async ({ authPage }) => {
    const page = authPage;

    // 验证页面标题
    await expect(page).toHaveTitle(/模块/);

    // 验证左侧侧边栏存在（第一个 aside 元素）
    const sidebar = page.locator('aside').first();
    await expect(sidebar).toBeVisible();

    // 验证模块管理标题
    await expect(page.getByText('模块管理').first()).toBeVisible();
  });

  // ------------------------------------------------------------
  // 测试 2：模块卡片列表渲染
  // ------------------------------------------------------------
  test('模块卡片列表 - 显示所有模块', async ({ authPage }) => {
    const page = authPage;

    // 等待模块卡片渲染
    const moduleCards = page.locator('.module-card');

    // 验证至少有模块卡片被渲染（页面有内置 mock 数据）
    await expect(moduleCards.first()).toBeVisible({ timeout: 5000 });

    const cardCount = await moduleCards.count();
    expect(cardCount).toBeGreaterThan(0);
    // 页面内置 8 个模块
    expect(cardCount).toBe(8);
  });

  // ------------------------------------------------------------
  // 测试 3：模块状态标识（通过卡片数量和详情面板验证）
  // ------------------------------------------------------------
  test('模块状态 - 点击模块卡片显示详情面板', async ({ authPage }) => {
    const page = authPage;

    // 等待模块卡片渲染
    await page.locator('.module-card').first().waitFor({ timeout: 5000 });

    // 点击第一个模块卡片
    await page.locator('.module-card').first().click();

    // 验证详情面板出现
    const detailPanel = page.locator('#detail-panel');
    await expect(detailPanel).toBeVisible();

    // 验证详情面板中有状态信息（包含"运行中"或"已停止"）
    const detailText = await detailPanel.textContent();
    expect(detailText).toMatch(/运行中|已停止/);
  });

  // ------------------------------------------------------------
  // 测试 4：模块启停操作
  // ------------------------------------------------------------
  test('模块启停操作 - 启动按钮可点击', async ({ authPage }) => {
    const page = authPage;

    // 等待模块卡片渲染
    await page.locator('.module-card').first().waitFor({ timeout: 5000 });

    // 验证启动按钮存在
    const startButton = page.locator('.action-start').first();
    await expect(startButton).toBeVisible();

    // 点击启动按钮
    await startButton.click();

    // 验证按钮仍然可交互（不会报错导致页面异常）
    await expect(startButton).toBeEnabled();
  });

  // ------------------------------------------------------------
  // 测试 5：模块版本号显示
  // ------------------------------------------------------------
  test('模块版本号 - 正确显示', async ({ authPage }) => {
    const page = authPage;

    // 等待模块卡片渲染
    await page.locator('.module-card').first().waitFor({ timeout: 5000 });

    // 验证模块版本号显示
    const versions = page.locator('.module-version');
    const versionCount = await versions.count();
    expect(versionCount).toBeGreaterThan(0);

    // 第一个版本号应该以 v 开头
    const firstVersion = await versions.first().textContent();
    expect(firstVersion?.trim()).toMatch(/^v/);
  });

});
