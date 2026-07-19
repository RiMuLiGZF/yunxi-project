/**
 * API Mock 路由注册器
 * 使用 Playwright 的 page.route() 拦截 API 请求并返回 mock 数据
 * 确保测试可以在没有真实后端的情况下独立运行
 *
 * 实现方式：使用单个统一路由处理器，根据 URL 路径分发 mock 响应
 * 这样可以完全控制匹配逻辑，避免 Playwright glob 模式优先级问题
 */

const mockData = require('./mockData');

/**
 * 为指定 page 注册所有 mock API 路由
 * @param {import('@playwright/test').Page} page - Playwright Page 对象
 * @param {Object} options - 配置选项
 * @param {number} options.delay - 模拟网络延迟（ms），默认 50ms
 * @param {Object} options.overrides - 覆盖特定 API 的返回数据
 */
async function setupMockApis(page, options = {}) {
  const { delay = 50, overrides = {} } = options;

  // 模拟网络延迟
  const simulateDelay = async () => {
    if (delay > 0) {
      await page.waitForTimeout(delay);
    }
  };

  // 统一响应生成器
  const jsonResponse = (data, status = 200) => ({
    status,
    contentType: 'application/json',
    body: JSON.stringify(data),
  });

  /**
   * 解析请求 body
   */
  const parseBody = async (request) => {
    try {
      return request.postDataJSON ? await request.postDataJSON() : {};
    } catch (e) {
      return {};
    }
  };

  // ============================================================
  // 注册单个统一路由，拦截所有 /api/ 请求
  // ============================================================
  await page.route('**/api/**', async (route, request) => {
    const url = request.url();
    const method = request.method();

    // 解析 URL 路径（去掉 query string 和 domain）
    const urlObj = new URL(url);
    const path = urlObj.pathname;

    await simulateDelay();

    // ============================================================
    // 认证相关 API
    // ============================================================

    // 登录 POST /api/auth/login
    if (path === '/api/auth/login' && method === 'POST') {
      const body = await parseBody(request);
      const { username, password } = body || {};

      if (username === 'admin' && password === 'admin123') {
        return route.fulfill(jsonResponse(
          mockData.success({
            access_token: mockData.testToken,
            token_type: 'bearer',
            expires_in: 86400,
            user: mockData.testUser,
          })
        ));
      }

      // 错误密码
      return route.fulfill(jsonResponse(
        { code: 1001, data: null, message: '用户名或密码错误' },
        401
      ));
    }

    // 登出 POST /api/auth/logout
    if (path === '/api/auth/logout' && method === 'POST') {
      return route.fulfill(jsonResponse(
        mockData.success({ logged_out: true })
      ));
    }

    // 当前用户 GET /api/auth/me
    if (path === '/api/auth/me' && method === 'GET') {
      return route.fulfill(jsonResponse(
        mockData.success(mockData.testUser)
      ));
    }

    // ============================================================
    // 模块管理 API
    // ============================================================

    // 模块列表 GET /api/modules
    if (path === '/api/modules' && method === 'GET') {
      const customModules = overrides.modulesList || mockData.modulesList;
      return route.fulfill(jsonResponse(
        mockData.success({
          list: customModules,
          total: customModules.length,
        })
      ));
    }

    // 模块详情 GET /api/modules/:key
    const moduleDetailMatch = path.match(/^\/api\/modules\/([a-zA-Z0-9_-]+)$/);
    if (moduleDetailMatch && method === 'GET') {
      const key = moduleDetailMatch[1];
      const mod = mockData.modulesList.find(m => m.key === key) || mockData.modulesList[0];
      return route.fulfill(jsonResponse(mockData.success(mod)));
    }

    // 启动模块 POST /api/modules/:key/start
    if (/^\/api\/modules\/[^/]+\/start$/.test(path) && method === 'POST') {
      return route.fulfill(jsonResponse(
        mockData.success({ status: 'running', message: '模块启动成功' })
      ));
    }

    // 停止模块 POST /api/modules/:key/stop
    if (/^\/api\/modules\/[^/]+\/stop$/.test(path) && method === 'POST') {
      return route.fulfill(jsonResponse(
        mockData.success({ status: 'stopped', message: '模块停止成功' })
      ));
    }

    // 重启模块 POST /api/modules/:key/restart
    if (/^\/api\/modules\/[^/]+\/restart$/.test(path) && method === 'POST') {
      return route.fulfill(jsonResponse(
        mockData.success({ status: 'running', message: '模块重启成功' })
      ));
    }

    // ============================================================
    // 仪表盘 API
    // ============================================================

    if (path === '/api/dashboard/stats' && method === 'GET') {
      return route.fulfill(jsonResponse(
        mockData.success(mockData.dashboardStats)
      ));
    }

    // ============================================================
    // 系统设置 API
    // ============================================================

    if (path === '/api/settings') {
      if (method === 'GET') {
        return route.fulfill(jsonResponse(
          mockData.success(mockData.systemSettings)
        ));
      }
      if (method === 'PUT' || method === 'POST' || method === 'PATCH') {
        const body = await parseBody(request);
        return route.fulfill(jsonResponse(
          mockData.success({
            ...mockData.systemSettings,
            ...body,
          })
        ));
      }
    }

    // ============================================================
    // 健康检查
    // ============================================================

    if (path === '/api/health' && method === 'GET') {
      return route.fulfill(jsonResponse(
        mockData.success(mockData.healthStatus)
      ));
    }

    // ============================================================
    // 兜底：未匹配的 API 请求返回 200 + 空数据
    // 避免页面因 API 报错而无法渲染
    // ============================================================

    if (method === 'GET') {
      return route.fulfill(jsonResponse(mockData.success(null)));
    }

    // POST/PUT/DELETE 也返回成功
    return route.fulfill(jsonResponse(mockData.success({ ok: true })));
  });
}

module.exports = {
  setupMockApis,
};
