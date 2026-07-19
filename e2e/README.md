# 云汐项目 E2E 测试（Playwright）

基于 [Playwright](https://playwright.dev/) 的端到端测试套件，用于验证云汐项目前端页面的核心用户路径。

## 目录

- [快速开始](#快速开始)
- [目录结构](#目录结构)
- [运行测试](#运行测试)
- [编写新测试](#编写新测试)
- [Mock 方案](#mock-方案)
- [最佳实践](#最佳实践)
- [CI/CD 集成](#cicd-集成)
- [常见问题](#常见问题)

---

## 快速开始

### 1. 安装依赖

```bash
cd e2e
npm install
```

### 2. 安装浏览器

仅安装 Chromium（推荐，减少体积）：

```bash
npm run install:browsers
```

### 3. 启动前端服务

测试需要访问前端页面。你可以用任意方式启动静态文件服务：

```bash
# 方式一：Python 内置服务器（推荐，无需额外安装）
cd ../frontend
python -m http.server 3000

# 方式二：http-server
npx http-server ../frontend -p 3000 -c-1

# 方式三：项目自带的后端服务
# 启动 M8 或 API-Gateway，服务端口按需配置
```

### 4. 运行测试

```bash
# 运行所有测试
npm test

# 仅运行烟雾测试（带 @smoke 标签）
npm run test:smoke
```

---

## 目录结构

```
e2e/
├── fixtures/              # 测试 Fixtures（扩展 Playwright 能力）
│   └── index.js           # 自定义 test 对象，提供登录态、导航等 fixture
├── mocks/                 # Mock 数据与 API Mock
│   ├── mockData.js        # Mock 数据工厂（用户、模块、仪表盘等）
│   └── mockApis.js        # API Mock 路由注册器（Playwright page.route）
├── tests/                 # 测试用例目录
│   ├── home.spec.js       # 首页/入口测试
│   ├── login.spec.js      # 登录流程测试
│   ├── dashboard.spec.js  # 仪表盘/主页面测试
│   ├── modules.spec.js    # 模块管理测试
│   └── settings.spec.js   # 设置页面测试
├── utils/                 # 工具函数
│   └── helpers.js         # 通用辅助函数（等待网络空闲、截图命名等）
├── test-results/          # 测试结果输出（截图、视频、trace）
├── playwright-report/     # HTML 测试报告
├── playwright.config.js   # Playwright 配置文件
├── package.json           # 独立的 npm 项目配置
├── .env.example           # 环境变量示例
├── .gitignore             # Git 忽略规则
└── README.md              # 本文档
```

---

## 运行测试

### 常用命令

```bash
# 运行所有测试
npm test

# 仅运行烟雾测试（核心路径）
npm run test:smoke

# 按模块运行
npm run test:login       # 仅登录相关
npm run test:dashboard   # 仅仪表盘
npm run test:modules     # 仅模块管理
npm run test:settings    # 仅设置页面

# 有头模式（可见浏览器窗口）
npm run test:headed

# Playwright UI 模式（图形化测试运行器）
npm run test:ui

# 查看 HTML 报告
npm run report
```

### 环境变量

复制 `.env.example` 为 `.env` 并按需修改：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `BASE_URL` | `http://localhost:3000` | 测试目标地址 |
| `CI` | - | 设置为 `true` 时启用 CI 模式（失败重试 1 次） |

### 测试标签

测试用例使用 `@tag` 标注在 describe 名称中，可通过 `--grep` 筛选：

| 标签 | 说明 |
|------|------|
| `@smoke` | 烟雾测试（核心路径，快速验证） |
| `@login` | 登录流程相关 |
| `@dashboard` | 仪表盘相关 |
| `@modules` | 模块管理相关 |
| `@settings` | 设置页面相关 |

---

## 编写新测试

### 基本模板

```javascript
const { test, expect } = require('../fixtures');

test.describe('功能模块名 @smoke @模块标签', () => {

  test.beforeEach(async ({ navigate }) => {
    await navigate.toModules(); // 跳转到被测页面
  });

  test('测试用例描述', async ({ authPage }) => {
    const page = authPage; // 已登录状态的 page

    // 你的测试逻辑
    await expect(page.locator('#some-element')).toBeVisible();
  });

});
```

### 可用 Fixtures

| Fixture 名 | 类型 | 说明 |
|-----------|------|------|
| `page` | Page | 普通 Playwright Page 对象 |
| `authPage` | Page | 已注入登录态的 Page（localStorage 中有 token 和 user） |
| `navigate` | Object | 页面导航助手，快速跳转到各页面 |
| `testUser` | Object | 测试用户信息（用户名、密码等） |
| `sidebar` | Object | 侧边栏操作助手 |
| `mockApis` | - | 自动启用（auto: true），Mock 所有 API 请求 |

### navigate 方法

```javascript
await navigate.toHome();        // 首页
await navigate.toLogin();       // 登录页
await navigate.toDashboard();   // 仪表盘
await navigate.toModules();     // 模块管理
await navigate.toSettings();    // 系统设置
await navigate.toTasks();       // 任务中心
await navigate.toDeploy();      // 部署管理
await navigate.toMonitor();     // 系统监控
await navigate.toAgents();      // Agent 中心
await navigate.toCompute();     // 算力调度
await navigate.toPortal();      // 统一门户
```

### 测试用户

```javascript
// 正确凭证
testUser.username  // 'admin'
testUser.password  // 'admin123'

// 错误凭证
testUser.wrongPassword  // 'wrongpass123'
```

### 选择器最佳实践

优先使用以下选择器（按优先级排序）：

1. **data-dom-id 属性**（项目中已大量使用）：
   ```javascript
   page.locator('[data-dom-id="cta-login"]')
   ```

2. **id 属性**：
   ```javascript
   page.locator('#username')
   ```

3. **Role + 文本**（更贴近用户视角）：
   ```javascript
   page.getByRole('button', { name: '登 录' })
   ```

4. **class 选择器**（用于列表项等）：
   ```javascript
   page.locator('.module-card').first()
   ```

---

## Mock 方案

### 设计思路

E2E 测试采用 **Mock 优先** 策略，确保测试可以在没有真实后端的情况下独立运行。

使用 Playwright 的 `page.route()` 拦截所有 `/api/**` 请求，根据 URL 路径返回预设的 Mock 数据。

### Mock 数据

Mock 数据定义在 `mocks/mockData.js` 中，包含：

- **testUser** - 测试用户信息
- **testToken** - 测试 Token
- **modulesList** - 模块列表（8 个模块）
- **dashboardStats** - 仪表盘统计数据
- **systemSettings** - 系统设置数据
- **healthStatus** - 健康检查状态

### Mock API 列表

已 Mock 的 API 接口：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/login` | 登录（支持正确/错误凭证） |
| POST | `/api/auth/logout` | 登出 |
| GET | `/api/auth/me` | 当前用户信息 |
| GET | `/api/modules` | 模块列表 |
| GET | `/api/modules/:key` | 模块详情 |
| POST | `/api/modules/:key/start` | 启动模块 |
| POST | `/api/modules/:key/stop` | 停止模块 |
| POST | `/api/modules/:key/restart` | 重启模块 |
| GET | `/api/dashboard/stats` | 仪表盘统计 |
| GET/PUT | `/api/settings` | 系统设置 |
| GET | `/api/health` | 健康检查 |
| * | `/api/**` | 兜底（返回成功 + 空数据） |

### 扩展 Mock

在 `mocks/mockApis.js` 的统一路由处理器中添加新的 `if` 分支即可：

```javascript
// 新增 API Mock
if (path === '/api/new-endpoint' && method === 'GET') {
  return route.fulfill(jsonResponse(
    mockData.success({ your: 'data' })
  ));
}
```

在 `mocks/mockData.js` 中添加对应的数据工厂函数。

### 覆盖 Mock 数据

测试中可以通过 overrides 选项覆盖特定数据（需要修改 fixture 实现）：

```javascript
// 目前通过直接在测试中 page.route 覆盖
test.beforeEach(async ({ page }) => {
  await page.route('**/api/modules', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ code: 0, data: { list: customList, total: 0 } }),
    });
  });
});
```

---

## 最佳实践

### 1. 测试独立性

每个测试用例应该是独立的，不依赖其他测试的执行结果。Playwright 默认每个测试用例使用独立的浏览器上下文，状态天然隔离。

### 2. 使用 Fixture 复用逻辑

- 通用的登录态、导航等能力放在 `fixtures/` 中
- 避免在每个测试文件中重复编写登录逻辑

### 3. 优先使用 Mock

- 烟雾测试全部使用 Mock，确保快速、稳定
- 集成测试（后续扩展）可以连接真实后端
- Mock 数据尽量贴近真实后端响应格式

### 4. 断言粒度

- 每个测试聚焦一个核心验证点
- 不要过度断言，避免因 UI 微调导致测试失效
- 优先断言用户可见的内容，而非内部实现

### 5. 选择器稳定性

- 优先使用 `data-dom-id`、`id` 等稳定选择器
- 避免使用 CSS 层级选择器（如 `div > span:nth-child(2)`）
- 避免使用仅靠文本定位的选择器（文本可能变化）

### 6. 测试命名

- describe 名称：功能模块名 + @标签
- test 名称：场景 - 预期结果
- 示例：`正常登录成功 - 使用正确凭证并跳转到仪表盘`

### 7. 失败调试

测试失败时自动保存：
- **截图** - 失败时的页面状态
- **视频** - 失败用例的执行过程
- **Trace** - 完整的执行轨迹（可在 Playwright Trace Viewer 中查看）

查看 Trace：
```bash
npx playwright show-trace test-results/[测试名]/trace.zip
```

---

## CI/CD 集成

### GitHub Actions 示例

在 `.github/workflows/e2e.yml` 中添加：

```yaml
name: E2E Tests

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'

      - name: Install dependencies
        working-directory: e2e
        run: npm ci

      - name: Install Playwright browsers
        working-directory: e2e
        run: npx playwright install chromium --with-deps

      - name: Start frontend server
        run: |
          cd frontend
          python -m http.server 3000 &
          npx wait-on http://localhost:3000

      - name: Run E2E tests
        working-directory: e2e
        env:
          CI: true
          BASE_URL: http://localhost:3000
        run: npm run test:smoke

      - name: Upload test results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: playwright-report
          path: |
            e2e/playwright-report/
            e2e/test-results/
```

### 在 Docker 中运行

```dockerfile
FROM mcr.microsoft.com/playwright:v1.45.0-jammy

WORKDIR /app/e2e
COPY e2e/package*.json ./
RUN npm ci

COPY . .

CMD ["npm", "test"]
```

---

## 常见问题

### Q: 测试运行报 "page.goto: Timeout" 错误？

A: 确认前端服务已经启动，且 `BASE_URL` 配置正确。可以用浏览器手动访问测试一下。

### Q: 为什么所有测试都用 Mock？

A: 烟雾测试的目标是验证前端页面能正常加载、基本交互能工作，不依赖后端状态。Mock 确保了测试的稳定性和速度。后续可以增加连接真实后端的集成测试。

### Q: 如何添加新的页面测试？

1. 在 `tests/` 下新建 `xxx.spec.js`
2. 引入 `const { test, expect } = require('../fixtures')`
3. 在 `fixtures/index.js` 的 `navigate` 中添加跳转方法
4. 如需 Mock 新 API，在 `mocks/mockApis.js` 中添加路由

### Q: 测试失败了怎么调试？

1. 查看控制台输出的错误信息
2. 查看 `test-results/` 下的截图和视频
3. 使用 Trace Viewer 查看完整执行轨迹：
   ```bash
   npx playwright show-trace test-results/[路径]/trace.zip
   ```
4. 使用有头模式运行：`npm run test:headed`
5. 使用 UI 模式：`npm run test:ui`

### Q: 可以连接真实后端测试吗？

A: 可以。在测试文件中通过 `test.use()` 禁用 mock fixture，或者直接使用 `@playwright/test` 的 base test：

```javascript
const { test, expect } = require('@playwright/test');

test('真实后端测试', async ({ page }) => {
  await page.goto('/m8/login.html');
  // ...
});
```

---

## 后续扩展方向

1. **更多页面覆盖** - 任务中心、部署管理、系统监控、Agent 中心等
2. **可视化回归测试** - 使用截图对比（`toHaveScreenshot`）
3. **真实后端集成测试** - 启动完整后端 + 数据库进行端到端验证
4. **性能测试** - 利用 Playwright 的网络节流和性能指标
5. **无障碍测试** - 集成 axe-core 进行可访问性检测
6. **多浏览器测试** - 按需启用 Firefox 和 WebKit
7. **移动端测试** - 使用 Playwright 的设备模拟能力
