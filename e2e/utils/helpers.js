/**
 * 通用工具函数
 * 供测试用例和 fixtures 复用
 */

/**
 * 等待网络空闲（简单版本：等待指定时间内无新请求）
 * @param {import('@playwright/test').Page} page
 * @param {Object} options
 * @param {number} options.idleTime - 空闲时间（ms），默认 500ms
 * @param {number} options.timeout - 总超时（ms），默认 10000ms
 */
async function waitForNetworkIdle(page, options = {}) {
  const { idleTime = 500, timeout = 10000 } = options;
  try {
    await page.waitForLoadState('networkidle', { timeout });
  } catch (e) {
    // networkidle 不一定总能满足，退化为等待 load 状态 + 固定延迟
    await page.waitForLoadState('load', { timeout }).catch(() => {});
    await page.waitForTimeout(idleTime);
  }
}

/**
 * 生成带时间戳的截图文件名
 * @param {string} prefix - 前缀，通常是测试名
 * @param {string} suffix - 后缀描述
 * @returns {string}
 */
function screenshotName(prefix, suffix = '') {
  const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const cleanSuffix = suffix ? `-${suffix}` : '';
  return `${prefix}${cleanSuffix}-${ts}.png`;
}

/**
 * 断言元素包含文本（忽略前后空白）
 * @param {import('@playwright/test').Page} page
 * @param {string} selector - 选择器
 * @param {string} text - 期望文本
 */
async function assertElementHasText(page, selector, text) {
  const locator = page.locator(selector).first();
  await expect(locator).toContainText(text);
}

/**
 * 断言元素可见
 * @param {import('@playwright/test').Locator} locator
 */
async function assertVisible(locator) {
  await expect(locator).toBeVisible();
}

/**
 * 填写表单字段
 * @param {import('@playwright/test').Page} page
 * @param {Object} fields - { fieldId: value }
 */
async function fillForm(page, fields) {
  for (const [id, value] of Object.entries(fields)) {
    const selector = `#${id}`;
    await page.fill(selector, value);
  }
}

/**
 * 等待元素出现并返回 locator
 * @param {import('@playwright/test').Page} page
 * @param {string} selector
 * @param {Object} options
 * @returns {Promise<import('@playwright/test').Locator>}
 */
async function waitForSelector(page, selector, options = {}) {
  const locator = page.locator(selector).first();
  await locator.waitFor(options);
  return locator;
}

/**
 * 检查元素是否存在（不抛错）
 * @param {import('@playwright/test').Page} page
 * @param {string} selector
 * @returns {Promise<boolean>}
 */
async function elementExists(page, selector) {
  const count = await page.locator(selector).count();
  return count > 0;
}

/**
 * 获取元素文本内容（第一个匹配）
 * @param {import('@playwright/test').Page} page
 * @param {string} selector
 * @returns {Promise<string>}
 */
async function getText(page, selector) {
  const locator = page.locator(selector).first();
  return await locator.textContent() || '';
}

/**
 * 模拟慢速网络（用于测试加载状态）
 * @param {import('@playwright/test').Page} page
 * @param {number} latencyMs - 延迟毫秒数
 */
async function simulateSlowNetwork(page, latencyMs = 2000) {
  await page.route('**/*', async (route) => {
    await page.waitForTimeout(latencyMs);
    route.continue();
  });
}

module.exports = {
  waitForNetworkIdle,
  screenshotName,
  assertElementHasText,
  assertVisible,
  fillForm,
  waitForSelector,
  elementExists,
  getText,
  simulateSlowNetwork,
};
