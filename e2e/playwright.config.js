// @ts-check
const { defineConfig, devices } = require('@playwright/test');
const path = require('path');

/**
 * 云汐项目 Playwright E2E 测试配置
 * 读取环境变量：
 *   BASE_URL     - 测试目标地址，默认 http://localhost:3000
 *   CI           - CI 环境标记
 *   HEADLESS     - 是否无头模式，默认 true
 */
const baseURL = process.env.BASE_URL || 'http://localhost:3000';

module.exports = defineConfig({
  // 测试目录
  testDir: path.join(__dirname, 'tests'),

  // 测试输出目录（截图、视频、trace 等）
  outputDir: path.join(__dirname, 'test-results'),

  // 全局超时 30 秒
  timeout: 30 * 1000,

  // 单个断言超时 5 秒
  expect: {
    timeout: 5000,
  },

  // 失败时重试 1 次（CI 环境）
  retries: process.env.CI ? 1 : 0,

  // 并行 worker 数
  workers: process.env.CI ? 2 : undefined,

  // 测试报告
  reporter: [
    ['list'],
    ['html', { open: 'never', outputFolder: path.join(__dirname, 'playwright-report') }],
    ['json', { outputFile: path.join(__dirname, 'test-results', 'results.json') }],
  ],

  // 共享配置
  use: {
    // 基础 URL，测试中可使用 page.goto('/m8/login.html')
    baseURL,

    // 默认超时
    actionTimeout: 10000,
    navigationTimeout: 15000,

    // 失败时自动截图（仅失败用例，全页）
    screenshot: 'only-on-failure',

    // 失败时保留视频（retain-on-failure 可减少存储）
    video: 'retain-on-failure',

    // 失败时保留 trace（便于调试）
    trace: 'retain-on-failure',

    // 视口大小
    viewport: { width: 1440, height: 900 },

    // 忽略 HTTPS 错误（本地开发常见）
    ignoreHTTPSErrors: true,
  },

  // 项目配置 — 仅启用 Chromium 以减少体积
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        // Chromium 启动参数
        launchOptions: {
          args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
          ],
        },
      },
    },
  ],

  // 本地开发服务器配置（可选，用于静态文件服务）
  // 如果测试目标是本地静态文件，可启用 webServer 自动启动
  // webServer: {
  //   command: 'npx http-server ../frontend -p 3000 -c-1',
  //   port: 3000,
  //   reuseExistingServer: !process.env.CI,
  //   timeout: 10000,
  // },
});
