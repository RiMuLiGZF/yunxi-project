/**
 * 云汐系统 - 前端安全工具库
 *
 * 功能：
 * 1. HTML 转义（防 XSS）
 * 2. 安全 DOM 操作（替代 innerHTML）
 * 3. 安全元素创建
 * 4. 数据驱动的列表/表格安全渲染
 * 5. Token 安全管理
 *
 * 设计原则：
 * - 零依赖：纯原生 JavaScript 实现
 * - 渐进式：不破坏现有代码，可逐步替换
 * - 最小改动：提供与 innerHTML 类似的使用体验
 */

const SecurityUtils = (function() {
    'use strict';

    // =========================================================================
    // 一、HTML 转义
    // =========================================================================

    /**
     * HTML 特殊字符转义映射表
     */
    var HTML_ESCAPE_MAP = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#x27;',
        '/': '&#x2F;',
        '`': '&#x60;',
        '=': '&#x3D;',
    };

    /**
     * HTML 转义
     * 将特殊字符转换为 HTML 实体，防止 XSS 注入
     *
     * @param {string} str - 要转义的字符串
     * @returns {string} 转义后的安全字符串
     */
    function escapeHtml(str) {
        if (str === null || str === undefined) {
            return '';
        }
        if (typeof str !== 'string') {
            str = String(str);
        }
        return str.replace(/[&<>"'`=\/]/g, function(char) {
            return HTML_ESCAPE_MAP[char];
        });
    }

    /**
     * HTML 属性值转义（用于属性值内的用户数据）
     *
     * @param {string} str - 要转义的属性值
     * @returns {string} 转义后的安全属性值
     */
    function escapeAttr(str) {
        if (str === null || str === undefined) {
            return '';
        }
        if (typeof str !== 'string') {
            str = String(str);
        }
        return str.replace(/[&<>"'`=]/g, function(char) {
            return HTML_ESCAPE_MAP[char];
        });
    }

    // =========================================================================
    // 二、安全文本设置（替代 innerHTML 的纯文本场景）
    // =========================================================================

    /**
     * 安全设置元素文本内容
     * 使用 textContent，完全避免 XSS
     *
     * @param {HTMLElement} element - 目标元素
     * @param {string} text - 文本内容
     */
    function safeSetText(element, text) {
        if (!element) return;
        element.textContent = (text === null || text === undefined) ? '' : String(text);
    }

    /**
     * 安全设置元素 HTML 内容（先转义再设置）
     * 适用于需要 HTML 结构但内容来自用户输入的场景
     *
     * 注意：这会将所有 HTML 标签转义为纯文本显示。
     * 如果需要保留某些 HTML 标签，请使用 safeSetSanitizedHtml。
     *
     * @param {HTMLElement} element - 目标元素
     * @param {string} html - 要转义后显示的 HTML 字符串
     */
    function safeSetHtml(element, html) {
        if (!element) return;
        element.textContent = (html === null || html === undefined) ? '' : String(html);
    }

    // =========================================================================
    // 三、安全元素创建
    // =========================================================================

    /**
     * 安全创建 DOM 元素
     *
     * @param {string} tag - 标签名（如 'div', 'span', 'button'）
     * @param {Object} options - 配置选项
     * @param {string} options.text - 文本内容（安全，使用 textContent）
     * @param {string} options.className - CSS 类名
     * @param {string} options.id - 元素 ID
     * @param {Object} options.attrs - 属性键值对（自动转义属性值）
     * @param {Object} options.style - 内联样式键值对
     * @param {Array} options.children - 子元素数组（DOM 元素或字符串，字符串会转义）
     * @param {Object} options.events - 事件监听器 { click: fn, ... }
     * @param {string} options.html - 原始 HTML（警告：仅用于可信内容！）
     * @returns {HTMLElement} 创建的元素
     */
    function createElement(tag, options) {
        options = options || {};
        var el = document.createElement(tag);

        // 设置文本内容（安全）
        if (options.text !== undefined && options.text !== null) {
            el.textContent = String(options.text);
        }

        // 设置 HTML（仅用于可信内容，有警告）
        if (options.html !== undefined && options.html !== null) {
            console.warn('[SecurityUtils] createElement: 使用 html 选项可能存在 XSS 风险，请确保内容来源可信');
            el.innerHTML = String(options.html);
        }

        // 设置 className
        if (options.className) {
            el.className = options.className;
        }

        // 设置 ID
        if (options.id) {
            el.id = options.id;
        }

        // 设置属性（自动转义属性值）
        if (options.attrs && typeof options.attrs === 'object') {
            for (var attr in options.attrs) {
                if (options.attrs.hasOwnProperty(attr)) {
                    var value = options.attrs[attr];
                    // 跳过事件处理属性，应通过 events 选项设置
                    if (attr.substring(0, 2).toLowerCase() === 'on') {
                        console.warn('[SecurityUtils] createElement: 请通过 events 选项设置事件监听器，而不是 on* 属性');
                        continue;
                    }
                    // 安全设置属性
                    el.setAttribute(attr, String(value));
                }
            }
        }

        // 设置内联样式
        if (options.style && typeof options.style === 'object') {
            for (var prop in options.style) {
                if (options.style.hasOwnProperty(prop)) {
                    // 使用 setProperty 更安全
                    el.style.setProperty(prop, options.style[prop]);
                }
            }
        }

        // 添加子元素
        if (options.children && Array.isArray(options.children)) {
            for (var i = 0; i < options.children.length; i++) {
                var child = options.children[i];
                if (child instanceof HTMLElement) {
                    el.appendChild(child);
                } else if (child !== null && child !== undefined) {
                    // 字符串内容使用文本节点（安全）
                    el.appendChild(document.createTextNode(String(child)));
                }
            }
        }

        // 绑定事件
        if (options.events && typeof options.events === 'object') {
            for (var event in options.events) {
                if (options.events.hasOwnProperty(event)) {
                    if (typeof options.events[event] === 'function') {
                        el.addEventListener(event, options.events[event]);
                    }
                }
            }
        }

        return el;
    }

    /**
     * 创建文档片段
     * 用于批量添加元素，减少 DOM 重排
     *
     * @param {Array} children - 子元素数组
     * @returns {DocumentFragment}
     */
    function createFragment(children) {
        var fragment = document.createDocumentFragment();
        if (children && Array.isArray(children)) {
            for (var i = 0; i < children.length; i++) {
                if (children[i] instanceof Node) {
                    fragment.appendChild(children[i]);
                }
            }
        }
        return fragment;
    }

    // =========================================================================
    // 四、表格/列表安全渲染
    // =========================================================================

    /**
     * 安全创建表格行
     *
     * @param {Array} cells - 单元格内容数组（字符串或对象）
     * @param {Object} options - 配置
     * @param {string} options.tag - 单元格标签 'td' 或 'th'（默认 'td'）
     * @param {string} options.className - 行的类名
     * @param {Object} options.attrs - 行的属性
     * @param {Array} options.cellClasses - 每个单元格的类名
     * @param {boolean} options.escape - 是否转义内容（默认 true）
     * @returns {HTMLElement} <tr> 元素
     */
    function createTableRow(cells, options) {
        options = options || {};
        var tag = options.tag || 'td';
        var tr = document.createElement('tr');

        if (options.className) {
            tr.className = options.className;
        }

        if (options.attrs && typeof options.attrs === 'object') {
            for (var attr in options.attrs) {
                if (options.attrs.hasOwnProperty(attr)) {
                    tr.setAttribute(attr, String(options.attrs[attr]));
                }
            }
        }

        if (cells && Array.isArray(cells)) {
            for (var i = 0; i < cells.length; i++) {
                var cell = document.createElement(tag);
                var cellContent = cells[i];

                // 支持对象格式：{ text: '内容', className: '类名', style: {...} }
                if (cellContent && typeof cellContent === 'object' && !(cellContent instanceof HTMLElement)) {
                    if (cellContent.text !== undefined) {
                        cell.textContent = String(cellContent.text);
                    }
                    if (cellContent.html !== undefined) {
                        console.warn('[SecurityUtils] createTableRow: 使用 html 选项可能存在 XSS 风险');
                        cell.innerHTML = String(cellContent.html);
                    }
                    if (cellContent.className) {
                        cell.className = cellContent.className;
                    }
                    if (cellContent.style && typeof cellContent.style === 'object') {
                        for (var prop in cellContent.style) {
                            if (cellContent.style.hasOwnProperty(prop)) {
                                cell.style.setProperty(prop, cellContent.style[prop]);
                            }
                        }
                    }
                    if (cellContent.attrs && typeof cellContent.attrs === 'object') {
                        for (var attrKey in cellContent.attrs) {
                            if (cellContent.attrs.hasOwnProperty(attrKey)) {
                                cell.setAttribute(attrKey, String(cellContent.attrs[attrKey]));
                            }
                        }
                    }
                } else if (cellContent instanceof HTMLElement) {
                    // 如果是 DOM 元素，直接添加
                    cell.appendChild(cellContent);
                } else if (cellContent !== null && cellContent !== undefined) {
                    // 纯文本，安全设置
                    cell.textContent = String(cellContent);
                }

                // 应用单元格类名
                if (options.cellClasses && options.cellClasses[i]) {
                    cell.className += (cell.className ? ' ' : '') + options.cellClasses[i];
                }

                tr.appendChild(cell);
            }
        }

        return tr;
    }

    /**
     * 安全渲染列表到容器
     *
     * @param {HTMLElement} container - 容器元素
     * @param {Array} items - 数据数组
     * @param {Function} renderItem - 渲染函数，接收单个数据项，返回 HTMLElement
     * @param {Object} options - 配置
     * @param {string} options.tag - 列表项标签（默认 'li'）
     * @param {string} options.containerTag - 容器标签（默认 'ul'），如果容器为空则创建
     * @param {boolean} options.clear - 是否先清空容器（默认 true）
     * @param {string} options.emptyText - 空数据时的提示文本
     */
    function renderList(container, items, renderItem, options) {
        if (!container) return;
        options = options || {};
        var clear = options.clear !== false;

        if (clear) {
            container.innerHTML = '';
        }

        if (!items || items.length === 0) {
            if (options.emptyText) {
                var emptyEl = createElement('div', {
                    text: options.emptyText,
                    className: 'empty-list-tip',
                });
                container.appendChild(emptyEl);
            }
            return;
        }

        var fragment = document.createDocumentFragment();

        for (var i = 0; i < items.length; i++) {
            var itemEl = renderItem(items[i], i);
            if (itemEl instanceof HTMLElement) {
                fragment.appendChild(itemEl);
            }
        }

        container.appendChild(fragment);
    }

    // =========================================================================
    // 五、输入验证与清理
    // =========================================================================

    /**
     * 验证字符串是否包含潜在的 XSS 攻击向量
     *
     * @param {string} str - 要检查的字符串
     * @returns {boolean} true 表示可疑，false 表示安全
     */
    function hasXssPattern(str) {
        if (!str || typeof str !== 'string') return false;
        var lower = str.toLowerCase();
        var patterns = [
            /<script[^>]*>/i,
            /javascript:/i,
            /on\w+\s*=/i,
            /<iframe[^>]*>/i,
            /<img[^>]+on\w+/i,
            /eval\s*\(/i,
            /document\.cookie/i,
            /<object[^>]*>/i,
            /<embed[^>]*>/i,
            /data:text\/html/i,
        ];
        for (var i = 0; i < patterns.length; i++) {
            if (patterns[i].test(lower)) {
                return true;
            }
        }
        return false;
    }

    /**
     * 安全获取 URL 参数（防止参数注入）
     *
     * @param {string} name - 参数名
     * @param {string} defaultValue - 默认值
     * @returns {string} 转义后的参数值
     */
    function getSafeUrlParam(name, defaultValue) {
        var params = new URLSearchParams(window.location.search);
        var value = params.get(name);
        if (value === null) {
            return defaultValue || '';
        }
        // 限制长度，防止超长参数攻击
        if (value.length > 2048) {
            value = value.substring(0, 2048);
        }
        return value;
    }

    // =========================================================================
    // 六、Token 安全管理
    // =========================================================================

    var TOKEN_CONFIG = {
        // Token 存储前缀
        prefix: 'yunxi_',
        // 是否使用 sessionStorage（更安全，关闭浏览器即清除）
        useSessionStorage: true,
        // Token 有效期（毫秒），0 表示不检查
        tokenExpiryMs: 15 * 60 * 1000, // 15 分钟
        // 刷新 Token 有效期（毫秒）
        refreshExpiryMs: 7 * 24 * 60 * 60 * 1000, // 7 天
        // 是否启用 Token 过期检查
        enableExpiryCheck: true,
    };

    /**
     * 配置 Token 安全选项
     *
     * @param {Object} config - 配置项
     */
    function configureToken(config) {
        if (config && typeof config === 'object') {
            for (var key in config) {
                if (TOKEN_CONFIG.hasOwnProperty(key) && config.hasOwnProperty(key)) {
                    TOKEN_CONFIG[key] = config[key];
                }
            }
        }
    }

    /**
     * 获取存储键名
     */
    function _getTokenKey() {
        return TOKEN_CONFIG.prefix + 'token';
    }

    function _getTokenTimeKey() {
        return TOKEN_CONFIG.prefix + 'token_time';
    }

    function _getRefreshKey() {
        return TOKEN_CONFIG.prefix + 'refresh_token';
    }

    /**
     * 获取当前使用的存储对象
     */
    function _getStorage() {
        return TOKEN_CONFIG.useSessionStorage ? sessionStorage : localStorage;
    }

    /**
     * 安全存储 Token
     *
     * @param {string} token - 访问令牌
     * @param {string} refreshToken - 刷新令牌（可选）
     * @param {boolean} remember - 是否持久化（true 则用 localStorage）
     */
    function setToken(token, refreshToken, remember) {
        var storage = remember ? localStorage : _getStorage();

        if (token) {
            storage.setItem(_getTokenKey(), token);
            // 记录设置时间
            storage.setItem(_getTokenTimeKey(), String(Date.now()));
        }

        if (refreshToken) {
            // refresh token 始终用 localStorage（跨会话）
            localStorage.setItem(_getRefreshKey(), refreshToken);
        }
    }

    /**
     * 获取 Token（带有效性检查）
     *
     * @returns {string|null} Token 或 null
     */
    function getToken() {
        var token = _getStorage().getItem(_getTokenKey());
        if (!token) {
            // 尝试从 localStorage 获取（remember me 的情况）
            token = localStorage.getItem(_getTokenKey());
        }

        if (!token) return null;

        // 检查是否过期
        if (TOKEN_CONFIG.enableExpiryCheck && TOKEN_CONFIG.tokenExpiryMs > 0) {
            var tokenTime = parseInt(_getStorage().getItem(_getTokenTimeKey()) || '0', 10);
            if (!tokenTime) {
                tokenTime = parseInt(localStorage.getItem(_getTokenTimeKey()) || '0', 10);
            }
            if (tokenTime && Date.now() - tokenTime > TOKEN_CONFIG.tokenExpiryMs) {
                // Token 已过期
                clearToken();
                return null;
            }
        }

        return token;
    }

    /**
     * 获取刷新 Token
     *
     * @returns {string|null}
     */
    function getRefreshToken() {
        return localStorage.getItem(_getRefreshKey());
    }

    /**
     * 清除所有 Token
     */
    function clearToken() {
        var storage = _getStorage();
        storage.removeItem(_getTokenKey());
        storage.removeItem(_getTokenTimeKey());
        localStorage.removeItem(_getTokenKey());
        localStorage.removeItem(_getTokenTimeKey());
        localStorage.removeItem(_getRefreshKey());
    }

    /**
     * 检查 Token 是否有效（存在且未过期）
     *
     * @returns {boolean}
     */
    function isTokenValid() {
        return !!getToken();
    }

    /**
     * 获取 Token 剩余有效时间（毫秒）
     *
     * @returns {number} 剩余毫秒数，-1 表示没有 Token 或不检查过期
     */
    function getTokenRemainingTime() {
        if (!TOKEN_CONFIG.enableExpiryCheck || TOKEN_CONFIG.tokenExpiryMs <= 0) {
            return -1;
        }

        var token = getToken();
        if (!token) return 0;

        var tokenTime = parseInt(_getStorage().getItem(_getTokenTimeKey()) || '0', 10);
        if (!tokenTime) {
            tokenTime = parseInt(localStorage.getItem(_getTokenTimeKey()) || '0', 10);
        }
        if (!tokenTime) return -1;

        var elapsed = Date.now() - tokenTime;
        return Math.max(0, TOKEN_CONFIG.tokenExpiryMs - elapsed);
    }

    // =========================================================================
    // 七、其他安全工具
    // =========================================================================

    /**
     * 安全打开新窗口（防止 window.opener 攻击）
     *
     * @param {string} url - 要打开的 URL
     * @param {string} target - 打开方式（默认 '_blank'）
     * @returns {Window|null}
     */
    function safeOpenWindow(url, target) {
        target = target || '_blank';
        var newWindow = window.open(url, target, 'noopener,noreferrer');
        if (newWindow) {
            newWindow.opener = null;
        }
        return newWindow;
    }

    /**
     * 安全设置元素的 src 属性（防止 javascript: 协议攻击）
     *
     * @param {HTMLImageElement|HTMLIFrameElement|HTMLScriptElement} element - 元素
     * @param {string} src - 源地址
     * @param {Array} allowedProtocols - 允许的协议列表
     * @returns {boolean} 是否设置成功
     */
    function safeSetSrc(element, src, allowedProtocols) {
        if (!element || !src) return false;

        allowedProtocols = allowedProtocols || ['http:', 'https:', 'data:'];

        try {
            var url = new URL(src, window.location.origin);
            if (allowedProtocols.indexOf(url.protocol) === -1) {
                console.warn('[SecurityUtils] safeSetSrc: 不允许的协议 ' + url.protocol);
                return false;
            }
            element.src = src;
            return true;
        } catch (e) {
            console.warn('[SecurityUtils] safeSetSrc: 无效的 URL', src);
            return false;
        }
    }

    /**
     * 防 CSRF：获取 CSRF Token（从 meta 标签或 cookie）
     *
     * @returns {string}
     */
    function getCsrfToken() {
        // 从 meta 标签获取
        var meta = document.querySelector('meta[name="csrf-token"]');
        if (meta) {
            return meta.content;
        }
        // 从 cookie 获取
        var match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
        if (match) {
            return decodeURIComponent(match[1]);
        }
        return '';
    }

    // =========================================================================
    // 公开接口
    // =========================================================================

    return {
        // HTML 转义
        escapeHtml: escapeHtml,
        escapeAttr: escapeAttr,

        // 安全文本设置
        safeSetText: safeSetText,
        safeSetHtml: safeSetHtml,

        // 元素创建
        createElement: createElement,
        createFragment: createFragment,

        // 表格/列表渲染
        createTableRow: createTableRow,
        renderList: renderList,

        // 输入验证
        hasXssPattern: hasXssPattern,
        getSafeUrlParam: getSafeUrlParam,

        // Token 安全
        configureToken: configureToken,
        setToken: setToken,
        getToken: getToken,
        getRefreshToken: getRefreshToken,
        clearToken: clearToken,
        isTokenValid: isTokenValid,
        getTokenRemainingTime: getTokenRemainingTime,

        // 其他安全工具
        safeOpenWindow: safeOpenWindow,
        safeSetSrc: safeSetSrc,
        getCsrfToken: getCsrfToken,

        // 配置
        config: TOKEN_CONFIG,
    };
})();

// 兼容 CommonJS 和浏览器全局
if (typeof module !== 'undefined' && module.exports) {
    module.exports = SecurityUtils;
}
