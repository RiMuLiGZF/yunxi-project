/**
 * 首页/入口 E2E 测试
 * @smoke
 *
 * 覆盖场景：
 * 1. 项目主入口页面加载
 * 2. 门户页面加载
 * 3. 导航链接可用
 */

const { test, expect } = require('../fixtures');

test.describe('首页与入口 @smoke', () => {

  // ------------------------------------------------------------
  // 测试 1：主入口页面加载
  // ------------------------------------------------------------
  test('主入口页面 - 正常加载并显示导航链接', async ({ navigate }) => {
    const { page } = test.info();
    // 注意：需要从 test 上下文获取 page，这里使用 base fixture 的 page
  });

  test('主入口页面加载', async ({ page, navigate }) => {
    await navigate.toHome();

    // 验证标题
    await expect(page).toHaveTitle(/云汐工作台/);

    // 验证导航链接存在
    const portalLink = page.locator('a[href="portal/index.html"]');
    await expect(portalLink).toBeVisible();
    await expect(portalLink).toContainText('统一门户');

    const apiDocsLink = page.locator('a[href="portal/api-docs.html"]');
    await expect(apiDocsLink).toBeVisible();

    const startupLink = page.locator('a[href="startup/index.html"]');
    await expect(startupLink).toBeVisible();
  });

  // ------------------------------------------------------------
  // 测试 2：门户页面加载
  // ------------------------------------------------------------
  test('门户页面 - 正常加载', async ({ page, navigate }) => {
    await navigate.toPortal();

    // 验证页面加载成功（不抛 404）
    await expect(page).toHaveTitle(/.+/);
  });

  // ------------------------------------------------------------
  // 测试 3：登录页从首页可到达
  // ------------------------------------------------------------
  test('从首页跳转 - 导航链接可用', async ({ page, navigate }) => {
    await navigate.toHome();

    // 点击统一门户
    await page.click('a[href="portal/index.html"]');

    // 验证页面发生了跳转
    await expect(page.url()).toContain('portal');
  });

});
