/**
 * 登录流程 E2E 测试
 * @smoke @login
 *
 * 覆盖场景：
 * 1. 登录页正常加载
 * 2. 正常登录成功（正确凭证）
 * 3. 错误密码提示
 * 4. 空表单验证（用户名和密码都为空）
 * 5. 记住我功能
 */

const { test, expect } = require('../fixtures');

test.describe('登录流程 @smoke @login', () => {

  test.beforeEach(async ({ navigate }) => {
    await navigate.toLogin();
  });

  // ------------------------------------------------------------
  // 测试 1：登录页正常加载
  // ------------------------------------------------------------
  test('登录页正常加载 - 页面标题和表单元素显示', async ({ page }) => {
    // 验证页面标题
    await expect(page).toHaveTitle(/登录/);

    // 验证品牌标识
    await expect(page.locator('text=云汐').first()).toBeVisible();

    // 验证用户名输入框存在
    const usernameInput = page.locator('#username');
    await expect(usernameInput).toBeVisible();
    await expect(usernameInput).toHaveAttribute('placeholder', '请输入用户名');

    // 验证密码输入框存在
    const passwordInput = page.locator('#password');
    await expect(passwordInput).toBeVisible();
    await expect(passwordInput).toHaveAttribute('placeholder', '请输入密码');

    // 验证登录按钮存在
    const loginBtn = page.locator('[data-dom-id="cta-login"]');
    await expect(loginBtn).toBeVisible();
    await expect(loginBtn).toContainText('登 录');

    // 验证版本号显示
    await expect(page.locator('text=v1.0.0')).toBeVisible();
  });

  // ------------------------------------------------------------
  // 测试 2：正常登录成功（勾选记住我）
  // ------------------------------------------------------------
  test('正常登录成功 - 使用正确凭证并跳转到仪表盘', async ({ page, testUser }) => {
    // 勾选"记住我"，确保 token 存入 localStorage
    await page.click('#remember-toggle');
    await expect(page.locator('#remember-me')).toBeChecked();

    // 填写用户名和密码
    await page.fill('#username', testUser.username);
    await page.fill('#password', testUser.password);

    // 点击登录按钮
    await page.click('[data-dom-id="cta-login"]');

    // 等待页面跳转（跳转到仪表盘）
    await page.waitForURL(/dashboard\.html/, { timeout: 10000 });

    // 验证跳转到了仪表盘页面
    await expect(page).toHaveURL(/dashboard\.html/);
    await expect(page).toHaveTitle(/总览/);

    // 验证 token 已存入 localStorage（因为勾选了记住我）
    const token = await page.evaluate(() => localStorage.getItem('yunxi_token'));
    expect(token).toBeTruthy();

    // 验证用户信息已存入
    const userStr = await page.evaluate(() => localStorage.getItem('yunxi_user'));
    expect(userStr).toBeTruthy();
    const user = JSON.parse(userStr);
    expect(user.username).toBe('admin');
  });

  // ------------------------------------------------------------
  // 测试 3：错误密码 - 不跳转，留在登录页
  // ------------------------------------------------------------
  test('错误密码 - 留在登录页且不设置 token', async ({ page, testUser }) => {
    // 填写正确用户名和错误密码
    await page.fill('#username', testUser.username);
    await page.fill('#password', testUser.wrongPassword);

    // 点击登录按钮
    await page.click('[data-dom-id="cta-login"]');

    // 等待请求完成
    await page.waitForTimeout(1000);

    // 验证仍在登录页（URL 不变）
    await expect(page).toHaveURL(/login\.html/);

    // 验证登录按钮仍然可见（页面没有跳转）
    await expect(page.locator('[data-dom-id="cta-login"]')).toBeVisible();

    // 验证 token 没有被设置
    const sessionToken = await page.evaluate(() => sessionStorage.getItem('yunxi_token'));
    const localToken = await page.evaluate(() => localStorage.getItem('yunxi_token'));
    expect(sessionToken).toBeFalsy();
    expect(localToken).toBeFalsy();
  });

  // ------------------------------------------------------------
  // 测试 4：空表单提交 - 前端验证阻止提交
  // ------------------------------------------------------------
  test('空表单提交 - 前端验证阻止提交', async ({ page }) => {
    // 直接点击登录按钮（不填写任何内容）
    await page.click('[data-dom-id="cta-login"]');

    // 短暂等待
    await page.waitForTimeout(500);

    // 验证仍在登录页
    await expect(page.locator('[data-dom-id="cta-login"]')).toBeVisible();
    await expect(page).toHaveURL(/login\.html/);

    // 验证 token 没有被设置
    const token = await page.evaluate(() => sessionStorage.getItem('yunxi_token'));
    expect(token).toBeFalsy();
  });

  // ------------------------------------------------------------
  // 测试 5：记住我勾选状态切换
  // ------------------------------------------------------------
  test('记住我勾选状态 - 切换正常', async ({ page }) => {
    const checkbox = page.locator('#remember-me');
    const toggle = page.locator('#remember-toggle');

    // 默认未选中
    await expect(checkbox).not.toBeChecked();

    // 点击切换为选中
    await toggle.click();
    await expect(checkbox).toBeChecked();

    // 再次点击取消选中
    await toggle.click();
    await expect(checkbox).not.toBeChecked();
  });

});
