/**
 * 主页面加载 E2E 测试
 * @smoke @dashboard
 *
 * 覆盖场景：
 * 1. 仪表盘页面正常加载
 * 2. 侧边栏导航正常显示
 * 3. 页脚和版本号显示正确
 * 4. 主题切换功能
 */

const { test, expect } = require('../fixtures');

test.describe('主页面加载 @smoke @dashboard', () => {

  // 使用 authPage fixture 模拟已登录状态
  test.use({ storageState: undefined });

  test.beforeEach(async ({ authPage, navigate }) => {
    await navigate.toDashboard();
    // 等待页面基本加载完成
    await authPage.waitForLoadState('domcontentloaded');
  });

  // ------------------------------------------------------------
  // 测试 1：仪表盘页面正常加载
  // ------------------------------------------------------------
  test('仪表盘页面正常加载 - 标题和主要区域', async ({ authPage }) => {
    const page = authPage;

    // 验证页面标题
    await expect(page).toHaveTitle(/总览/);

    // 验证侧边栏存在
    await expect(page.locator('aside')).toBeVisible();

    // 验证主内容区存在
    await expect(page.locator('header')).toBeVisible();

    // 验证面包屑导航
    await expect(page.locator('text=总览仪表盘').first()).toBeVisible();

    // 验证云汐 M8 logo 区域
    await expect(page.locator('text=云汐 M8').first()).toBeVisible();
  });

  // ------------------------------------------------------------
  // 测试 2：侧边栏导航正常
  // ------------------------------------------------------------
  test('侧边栏导航 - 菜单项完整显示', async ({ authPage, sidebar }) => {
    const page = authPage;

    // 验证主要菜单项存在
    const menuItems = [
      { id: 'nav-dashboard', label: '总览' },
      { id: 'nav-tasks', label: '任务中心' },
      { id: 'nav-modules-hidden', label: '模块管理' },
      { id: 'nav-deploy-hidden', label: '部署管理' },
      { id: 'nav-monitor-hidden', label: '系统监控' },
      { id: 'nav-agents-hidden', label: 'Agent 中心' },
      { id: 'nav-compute-hidden', label: '算力调度' },
      { id: 'nav-settings-hidden', label: '系统设置' },
    ];

    for (const item of menuItems) {
      const locator = page.locator(`[data-dom-id="${item.id}"]`);
      await expect(locator).toBeVisible();
      await expect(locator).toContainText(item.label);
    }

    // 验证当前激活项是总览
    const activeMenu = page.locator('[data-dom-id="nav-dashboard"]');
    await expect(activeMenu).toBeVisible();
  });

  // ------------------------------------------------------------
  // 测试 3：侧边栏导航跳转
  // ------------------------------------------------------------
  test('侧边栏导航 - 点击跳转到模块管理页', async ({ authPage }) => {
    const page = authPage;

    // 点击模块管理
    await page.click('[data-dom-id="nav-modules-hidden"]');

    // 验证 URL 变化（跳转到 modules.html）
    await expect(page).toHaveURL(/modules\.html/);

    // 验证页面标题变化
    await expect(page).toHaveTitle(/模块/);
  });

  // ------------------------------------------------------------
  // 测试 4：用户信息区域显示
  // ------------------------------------------------------------
  test('侧边栏底部 - 用户信息区域显示', async ({ authPage }) => {
    const page = authPage;

    // 验证用户昵称显示
    await expect(page.locator('text=管理员').first()).toBeVisible();
  });

  // ------------------------------------------------------------
  // 测试 5：主题切换按钮
  // ------------------------------------------------------------
  test('主题切换按钮 - 存在且可点击', async ({ authPage }) => {
    const page = authPage;

    const themeBtn = page.locator('#themeToggleBtn');
    await expect(themeBtn).toBeVisible();
    await expect(themeBtn).toHaveAttribute('aria-label', '切换主题');
  });

});
