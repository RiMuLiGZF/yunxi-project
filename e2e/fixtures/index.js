/**
 * 测试 Fixtures
 * 扩展 Playwright 的 base test，提供登录状态、页面导航等预置能力
 *
 * 使用方式：
 *   const { test, expect } = require('../fixtures');
 *   test('已登录用户访问仪表盘', async ({ authPage, navigate }) => {
 *     await navigate.toDashboard();
 *   });
 */

const base = require('@playwright/test');
const { setupMockApis } = require('../mocks/mockApis');
const mockData = require('../mocks/mockData');
const path = require('path');

/**
 * 自定义 test，扩展 fixtures
 */
const test = base.test.extend({
  // ============================================================
  // 全局级 fixture：为每个测试自动启用 mock API
  // ============================================================
  mockApis: [
    async ({ page }, use) => {
      await setupMockApis(page, { delay: 50 });
      await use();
    },
    { scope: 'test', auto: true },
  ],

  // ============================================================
  // 已登录状态的 page（通过注入 localStorage token 模拟登录）
  // 避免每个测试都走一遍登录 UI 流程
  // ============================================================
  authPage: async ({ page, baseURL }, use) => {
    // 在页面加载前注入登录态
    await page.addInitScript(({ token, user, tokenKey, userKey }) => {
      window.localStorage.setItem(tokenKey, token);
      window.localStorage.setItem(userKey, JSON.stringify(user));
    }, {
      token: mockData.testToken,
      user: mockData.testUser,
      tokenKey: 'yunxi_token',
      userKey: 'yunxi_user',
    });

    await use(page);
  },

  // ============================================================
  // 页面导航 fixture：快速跳转到各页面
  // ============================================================
  navigate: async ({ page, baseURL }, use) => {
    const base = baseURL || '';

    const navigate = {
      /** 跳转到首页 */
      async toHome() {
        await page.goto(`${base}/index.html`);
      },
      /** 跳转到登录页 */
      async toLogin() {
        await page.goto(`${base}/m8/login.html`);
      },
      /** 跳转到仪表盘 */
      async toDashboard() {
        await page.goto(`${base}/m8/dashboard.html`);
      },
      /** 跳转到模块列表 */
      async toModules() {
        await page.goto(`${base}/m8/modules.html`);
      },
      /** 跳转到系统设置 */
      async toSettings() {
        await page.goto(`${base}/m8/settings.html`);
      },
      /** 跳转到任务中心 */
      async toTasks() {
        await page.goto(`${base}/m8/tasks.html`);
      },
      /** 跳转到部署管理 */
      async toDeploy() {
        await page.goto(`${base}/m8/deploy.html`);
      },
      /** 跳转到系统监控 */
      async toMonitor() {
        await page.goto(`${base}/m8/monitor.html`);
      },
      /** 跳转到 Agent 中心 */
      async toAgents() {
        await page.goto(`${base}/m8/agents.html`);
      },
      /** 跳转到算力调度 */
      async toCompute() {
        await page.goto(`${base}/m8/compute.html`);
      },
      /** 跳转到门户首页 */
      async toPortal() {
        await page.goto(`${base}/portal/index.html`);
      },
    };

    await use(navigate);
  },

  // ============================================================
  // 测试用户 fixture：创建临时测试用户信息
  // ============================================================
  testUser: async ({}, use) => {
    const user = {
      username: 'admin',
      password: 'admin123',
      nickname: '管理员',
      wrongPassword: 'wrongpass123',
      emptyUsername: '',
      emptyPassword: '',
    };
    await use(user);
  },

  // ============================================================
  // 侧边栏导航 fixture：提供侧边栏操作方法
  // ============================================================
  sidebar: async ({ page }, use) => {
    const sidebar = {
      /** 点击侧边栏菜单项 */
      async clickMenu(dataDomId) {
        await page.click(`[data-dom-id="${dataDomId}"]`);
      },
      /** 获取当前激活的菜单项 */
      async getActiveMenu() {
        return page.locator('nav a[data-active="true"]').first();
      },
      /** 断言菜单存在 */
      async assertMenuExists(dataDomId) {
        await base.expect(page.locator(`[data-dom-id="${dataDomId}"]`)).toBeVisible();
      },
    };
    await use(sidebar);
  },
});

const expect = base.expect;

module.exports = { test, expect };
