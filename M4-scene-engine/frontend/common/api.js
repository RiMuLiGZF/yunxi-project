/**
 * 云汐系统 - 前端公共 API 工具
 * 处理认证、API 调用、Token 管理、系统校验、状态同步
 */

const YunxiAPI = (function() {
    // API 基础地址（M4 场景引擎，使用 v1 版本前缀）
    const API_BASE = '/api/v1';

    // Token 存储 key
    const TOKEN_KEY = 'yunxi_token';
    const USER_KEY = 'yunxi_user';
    const SYSTEM_STATUS_KEY = 'yunxi_system_status';

    // 系统状态缓存
    let systemStatusCache = null;
    let systemStatusLastFetch = 0;
    const STATUS_CACHE_TTL = 30000; // 30秒缓存

    // 全局加载状态
    let loadingCount = 0;
    let loadingOverlay = null;

    /**
     * 获取存储的 Token
     */
    function getToken() {
        return localStorage.getItem(TOKEN_KEY) || sessionStorage.getItem(TOKEN_KEY);
    }

    /**
     * 存储 Token
     */
    function setToken(token, remember = false) {
        if (remember) {
            localStorage.setItem(TOKEN_KEY, token);
        } else {
            sessionStorage.setItem(TOKEN_KEY, token);
        }
    }

    /**
     * 清除 Token
     */
    function clearToken() {
        localStorage.removeItem(TOKEN_KEY);
        sessionStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(USER_KEY);
    }

    /**
     * 获取当前用户信息
     */
    function getCurrentUser() {
        const userStr = localStorage.getItem(USER_KEY);
        return userStr ? JSON.parse(userStr) : null;
    }

    /**
     * 存储用户信息
     */
    function setUser(user) {
        localStorage.setItem(USER_KEY, JSON.stringify(user));
    }

    /**
     * 检查是否已登录
     */
    function isLoggedIn() {
        // M4 独立部署时自动启用访客模式，无需登录
        if (!getToken()) {
            setGuestToken();
        }
        return true;
    }

    /**
     * 设置访客模式 Token（本地演示用）
     */
    function setGuestToken() {
        const guestToken = 'guest_' + Date.now();
        setToken(guestToken, true);
        setUser({
            username: 'guest',
            nickname: '汐舟',
            role: 'user'
        });
    }

    /**
     * 统一 API 请求方法
     */
    async function request(method, path, options = {}) {
        // 处理路径：如果 path 已经以 /api 开头则直接用，否则自动拼接
        let url;
        if (path.startsWith('/api/')) {
            url = path;
        } else if (path.startsWith('/')) {
            url = API_BASE + path;
        } else {
            url = API_BASE + '/' + path;
        }
        const headers = {
            'Content-Type': 'application/json',
            ...options.headers,
        };

        const token = getToken();
        if (token) {
            headers['Authorization'] = 'Bearer ' + token;
        }

        const config = {
            method: method,
            headers: headers,
        };

        if (options.body) {
            config.body = JSON.stringify(options.body);
        }

        if (options.signal) {
            config.signal = options.signal;
        }

        try {
            const response = await fetch(url, config);
            const data = await response.json();

            if (response.status === 401) {
                clearToken();
                if (!location.pathname.includes('login')) {
                    redirectToLogin();
                }
                throw new Error('登录已过期，请重新登录');
            }

            if (data.code !== 0) {
                throw new Error(data.message || '请求失败');
            }

            return data.data;
        } catch (error) {
            // 静默失败，不在控制台打印错误，避免干扰
            // AbortError 是正常取消，直接抛出
            if (error.name === 'AbortError') {
                throw error;
            }
            throw error;
        }
    }

    /**
     * 跳转到登录页
     */
    function redirectToLogin() {
        // M4 独立部署时使用访客模式，不跳转登录
        if (!getToken()) {
            setGuestToken();
        }
        // 刷新当前页以应用访客状态
        location.reload();
    }

    /**
     * 登录
     */
    async function login(username, password, remember = false) {
        const data = await request('POST', '/auth/login', {
            body: { username, password },
        });
        setToken(data.access_token, remember);
        if (data.user) {
            setUser(data.user);
        }
        return data;
    }

    /**
     * 登出
     */
    async function logout() {
        try {
            await request('POST', '/auth/logout');
        } catch (e) {
            // 忽略登出错误
        }
        clearToken();
    }

    /**
     * 获取当前用户信息
     */
    async function fetchCurrentUser() {
        const data = await request('GET', '/auth/me');
        setUser(data);
        return data;
    }

    // ===== 任务相关 API =====

    async function submitTask(taskData) {
        return request('POST', '/tasks/submit', { body: taskData });
    }

    async function getTask(taskId) {
        return request('GET', '/tasks/' + taskId);
    }

    async function listTasks(params = {}) {
        const query = new URLSearchParams(params).toString();
        return request('GET', '/tasks/' + (query ? '?' + query : ''));
    }

    async function cancelTask(taskId) {
        return request('POST', '/tasks/' + taskId + '/cancel');
    }

    // ===== 模块相关 API =====

    async function listModules() {
        return request('GET', '/system/modules');
    }

    async function getModuleHealth(moduleId) {
        return request('GET', '/modules/' + moduleId + '/health');
    }

    async function startModule(moduleId) {
        return request('POST', '/system/modules/' + moduleId + '/start');
    }

    async function stopModule(moduleId) {
        return request('POST', '/system/modules/' + moduleId + '/stop');
    }

    async function restartModule(moduleId) {
        return request('POST', '/system/modules/' + moduleId + '/restart');
    }

    async function getModuleDetail(moduleId) {
        return request('GET', '/system/modules/' + moduleId);
    }

    // ===== 部署相关 API =====

    async function pullModel(modelName) {
        return request('POST', '/deploy/ollama/pull', { body: { model: modelName } });
    }

    async function commitChanges(message) {
        return request('POST', '/deploy/git/commit', { body: { message: message } });
    }

    async function packageModule(moduleId) {
        return request('POST', '/deploy/modules/package', { body: { module_id: moduleId } });
    }

    async function pairDevice(deviceId) {
        return request('POST', '/deploy/bluetooth/pair', { body: { device_id: deviceId } });
    }

    async function deployAll() {
        return request('POST', '/deploy/all');
    }

    async function rollbackVersion(version) {
        return request('POST', '/deploy/rollback', { body: { version: version } });
    }

    // ===== 监控相关 API =====

    async function getMonitorOverview() {
        return request('GET', '/monitor/overview');
    }

    async function getMonitorMetrics(type = 'cpu', range = '1h') {
        return request('GET', '/monitor/metrics?type=' + type + '&range=' + range);
    }

    async function getRealtimeMetrics() {
        return request('GET', '/monitor/metrics/realtime');
    }

    async function getMonitorLogs(params = {}) {
        const query = new URLSearchParams(params).toString();
        return request('GET', '/monitor/logs' + (query ? '?' + query : ''));
    }

    async function getAlertList(params = {}) {
        const query = new URLSearchParams(params).toString();
        return request('GET', '/monitor/alerts' + (query ? '?' + query : ''));
    }

    async function createAlert(alertData) {
        return request('POST', '/monitor/alerts', { body: alertData });
    }

    async function acknowledgeAlert(alertId) {
        return request('POST', '/monitor/alerts/' + alertId + '/acknowledge');
    }

    async function getModuleHealthDetail(moduleKey) {
        return request('GET', '/monitor/modules/' + moduleKey + '/health');
    }

    // ===== 设置相关 API =====

    async function getSettings() {
        return request('GET', '/system/settings');
    }

    async function saveSettings(settings) {
        return request('PUT', '/system/settings', { body: settings });
    }

    async function listUsers() {
        return request('GET', '/system/users');
    }

    async function createUser(userData) {
        return request('POST', '/system/users', { body: userData });
    }

    async function updateUser(userId, data) {
        return request('PUT', '/system/users/' + userId, { body: data });
    }

    async function deleteUser(userId) {
        return request('DELETE', '/system/users/' + userId);
    }

    async function changePassword(oldPassword, newPassword, confirmPassword) {
        return request('POST', '/auth/change-password', {
            body: { old_password: oldPassword, new_password: newPassword, confirm_password: confirmPassword }
        });
    }

    // ===== 公告相关 API =====

    async function getAnnouncements() {
        return request('GET', '/system/announcements');
    }

    // ===== 系统相关 API =====

    async function getSystemHealth() {
        const response = await fetch('/health');
        const data = await response.json();
        return data.data;
    }

    async function getSystemStats() {
        return request('GET', '/system/stats');
    }

    /**
     * 获取全局系统状态检测（带缓存）
     */
    async function getSystemStatus(force = false) {
        const now = Date.now();
        if (!force && systemStatusCache && (now - systemStatusLastFetch < STATUS_CACHE_TTL)) {
            return systemStatusCache;
        }

        try {
            const response = await fetch('/api/system/check', { cache: 'no-cache' });
            if (!response.ok) return null;
            const ct = response.headers.get('content-type') || '';
            if (!ct.includes('application/json')) return null;
            const data = await response.json();
            if (data.code === 0 && data.data) {
                systemStatusCache = data.data;
                systemStatusLastFetch = now;
                return data.data;
            }
        } catch (e) {
            // 静默失败
        }
        return null;
    }

    /**
     * 系统校验 - 执行功能前检查依赖状态
     * @param {Object} requirements - 需要检查的项 { ollama: true, git: true, bluetooth: false, modules: ['m1','m2'] }
     * @returns {Object} { pass: boolean, failed: [], message: string }
     */
    async function validateSystem(requirements = {}) {
        const status = await getSystemStatus();
        if (!status) {
            // 无法获取状态时默认通过（避免阻塞用户）
            return { pass: true, failed: [], message: '状态检测不可用，跳过校验' };
        }

        const failed = [];
        const checks = status.checks || {};

        // 检查 Ollama
        if (requirements.ollama && checks.ollama) {
            if (checks.ollama.status !== 'running') {
                failed.push({ key: 'ollama', message: checks.ollama.message || 'Ollama服务未启动' });
            }
        }

        // 检查 Git
        if (requirements.git && checks.git) {
            if (!['ready', 'available'].includes(checks.git.status)) {
                failed.push({ key: 'git', message: checks.git.message || 'Git不可用' });
            }
        }

        // 检查蓝牙
        if (requirements.bluetooth && checks.bluetooth) {
            if (checks.bluetooth.status !== 'ready') {
                failed.push({ key: 'bluetooth', message: checks.bluetooth.message || '蓝牙未连接' });
            }
        }

        // 检查模块
        if (requirements.modules && Array.isArray(requirements.modules)) {
            // 模块状态需要额外检查
            // 简单处理：检查整体模块状态
            if (checks.modules && checks.modules.status === 'stopped') {
                failed.push({ key: 'modules', message: '模块服务未启动' });
            }
        }

        return {
            pass: failed.length === 0,
            failed: failed,
            message: failed.length > 0 ? failed.map(f => f.message).join('；') : '校验通过',
        };
    }

    /**
     * 带系统校验的操作封装
     * @param {Object} requirements - 校验要求
     * @param {Function} action - 要执行的操作
     * @param {Object} options - { showError: true, loadingText: '' }
     */
    async function withValidation(requirements, action, options = {}) {
        const { showError = true, loadingText = '' } = options;

        if (loadingText) {
            showLoading(loadingText);
        }

        try {
            const validation = await validateSystem(requirements);
            if (!validation.pass) {
                if (showError) {
                    showToast('无法执行：' + validation.message, 'warning');
                }
                return { success: false, error: validation.message };
            }

            const result = await action();
            return { success: true, data: result };
        } catch (error) {
            if (showError && error.name !== 'AbortError') {
                showToast('操作失败：' + error.message, 'error');
            }
            return { success: false, error: error.message };
        } finally {
            if (loadingText) {
                hideLoading();
            }
        }
    }

    // ===== 加载动画 =====

    function showLoading(text = '加载中...') {
        loadingCount++;
        if (!loadingOverlay) {
            loadingOverlay = document.createElement('div');
            loadingOverlay.id = 'yunxi-loading-overlay';
            loadingOverlay.style.cssText = `
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(255, 255, 255, 0.7);
                backdrop-filter: blur(4px);
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 99999;
                transition: opacity 0.2s;
            `;
            loadingOverlay.innerHTML = `
                <div style="
                    background: white;
                    padding: 24px 32px;
                    border-radius: 12px;
                    box-shadow: 0 8px 32px rgba(0,0,0,0.1);
                    display: flex;
                    align-items: center;
                    gap: 16px;
                ">
                    <div style="
                        width: 32px;
                        height: 32px;
                        border: 3px solid #e5e7eb;
                        border-top-color: #5B8DEF;
                        border-radius: 50%;
                        animation: yunxiSpin 0.8s linear infinite;
                    "></div>
                    <span id="yunxi-loading-text" style="
                        font-size: 14px;
                        color: #1A2B4A;
                        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
                    ">${text}</span>
                </div>
            `;
            document.body.appendChild(loadingOverlay);

            // 添加动画样式
            if (!document.getElementById('yunxi-loading-style')) {
                const style = document.createElement('style');
                style.id = 'yunxi-loading-style';
                style.textContent = `
                    @keyframes yunxiSpin {
                        to { transform: rotate(360deg); }
                    }
                `;
                document.head.appendChild(style);
            }
        } else {
            const textEl = document.getElementById('yunxi-loading-text');
            if (textEl) textEl.textContent = text;
            loadingOverlay.style.display = 'flex';
            loadingOverlay.style.opacity = '1';
        }
    }

    function hideLoading() {
        loadingCount = Math.max(0, loadingCount - 1);
        if (loadingCount === 0 && loadingOverlay) {
            loadingOverlay.style.opacity = '0';
            setTimeout(() => {
                if (loadingOverlay && loadingCount === 0) {
                    loadingOverlay.style.display = 'none';
                }
            }, 200);
        }
    }

    // ===== 按钮状态管理 =====

    /**
     * 设置按钮禁用/启用状态
     */
    function setButtonDisabled(btn, disabled, reason = '') {
        if (!btn) return;
        btn.disabled = disabled;
        if (disabled) {
            btn.style.opacity = '0.5';
            btn.style.cursor = 'not-allowed';
            if (reason) {
                btn.title = reason;
            }
        } else {
            btn.style.opacity = '';
            btn.style.cursor = '';
            btn.title = '';
        }
    }

    /**
     * 批量更新按钮状态（根据系统状态）
     */
    async function updateButtonsBySystemStatus() {
        const status = await getSystemStatus();
        if (!status) return;

        const checks = status.checks || {};

        // 更新所有需要模型的按钮
        const ollamaRunning = checks.ollama?.status === 'running';
        document.querySelectorAll('[data-require-ollama]').forEach(btn => {
            setButtonDisabled(btn, !ollamaRunning, ollamaRunning ? '' : 'Ollama服务未启动');
        });

        // 更新所有需要Git的按钮
        const gitReady = ['ready', 'available'].includes(checks.git?.status);
        document.querySelectorAll('[data-require-git]').forEach(btn => {
            setButtonDisabled(btn, !gitReady, gitReady ? '' : 'Git不可用');
        });

        // 更新所有需要蓝牙的按钮
        const bluetoothReady = checks.bluetooth?.status === 'ready';
        document.querySelectorAll('[data-require-bluetooth]').forEach(btn => {
            setButtonDisabled(btn, !bluetoothReady, bluetoothReady ? '' : '蓝牙未连接');
        });

        // 更新所有需要模块服务的按钮
        const modulesReady = checks.modules?.status !== 'stopped';
        document.querySelectorAll('[data-require-modules]').forEach(btn => {
            setButtonDisabled(btn, !modulesReady, modulesReady ? '' : '模块服务未启动');
        });
    }

    // ===== 静默检测（Image方案，零控制台错误） =====

    /**
     * 使用 Image 对象静默检测服务状态
     * （不会产生控制台错误）
     */
    function silentCheck(url, timeout = 3000) {
        return new Promise((resolve) => {
            const img = new Image();
            const timer = setTimeout(() => {
                img.src = '';
                resolve({ online: false, reason: 'timeout' });
            }, timeout);

            img.onload = () => {
                clearTimeout(timer);
                resolve({ online: true });
            };
            img.onerror = () => {
                clearTimeout(timer);
                // onerror 也可能是端口通了但返回非图片，视为在线
                resolve({ online: true });
            };

            // 添加随机参数避免缓存
            img.src = url + (url.includes('?') ? '&' : '?') + '_t=' + Date.now();
        });
    }

    // ===== 工具函数 =====

    /**
     * 显示 Toast 消息
     */
    function showToast(message, type = 'info', duration = 3000) {
        // 检查是否已有 toast 容器
        let container = document.getElementById('yunxi-toast-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'yunxi-toast-container';
            container.style.cssText = `
                position: fixed;
                top: 20px;
                right: 20px;
                z-index: 9999;
                display: flex;
                flex-direction: column;
                gap: 10px;
            `;
            document.body.appendChild(container);
        }

        const toast = document.createElement('div');
        const colors = {
            success: 'background: rgba(16, 185, 129, 0.95); border-color: rgba(16, 185, 129, 0.5);',
            error: 'background: rgba(239, 68, 68, 0.95); border-color: rgba(239, 68, 68, 0.5);',
            warning: 'background: rgba(245, 158, 11, 0.95); border-color: rgba(245, 158, 11, 0.5);',
            info: 'background: rgba(59, 130, 246, 0.95); border-color: rgba(59, 130, 246, 0.5);',
        };

        toast.style.cssText = `
            padding: 12px 20px;
            border-radius: 8px;
            color: white;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
            font-size: 14px;
            ${colors[type] || colors.info}
            border: 1px solid;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            animation: slideIn 0.3s ease;
            backdrop-filter: blur(10px);
            max-width: 320px;
            word-break: break-word;
        `;
        toast.textContent = message;

        container.appendChild(toast);

        setTimeout(() => {
            toast.style.animation = 'slideOut 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }

    /**
     * 显示确认对话框
     */
    function showConfirm(message, title = '确认操作') {
        return new Promise((resolve) => {
            const overlay = document.createElement('div');
            overlay.style.cssText = `
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(0, 0, 0, 0.4);
                backdrop-filter: blur(2px);
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 10000;
            `;

            const modal = document.createElement('div');
            modal.style.cssText = `
                background: white;
                border-radius: 12px;
                padding: 24px;
                min-width: 320px;
                max-width: 440px;
                box-shadow: 0 16px 48px rgba(0,0,0,0.2);
                animation: modalIn 0.2s ease;
            `;

            modal.innerHTML = `
                <h3 style="font-size: 16px; font-weight: 600; color: #1A2B4A; margin-bottom: 12px;">${title}</h3>
                <p style="font-size: 14px; color: #4A5F80; line-height: 1.6; margin-bottom: 20px;">${message}</p>
                <div style="display: flex; gap: 12px; justify-content: flex-end;">
                    <button class="cancel-btn" style="
                        padding: 8px 20px;
                        border-radius: 6px;
                        border: 1px solid #d1d5db;
                        background: white;
                        color: #4A5F80;
                        font-size: 14px;
                        cursor: pointer;
                        transition: all 0.2s;
                    ">取消</button>
                    <button class="confirm-btn" style="
                        padding: 8px 20px;
                        border-radius: 6px;
                        border: none;
                        background: #5B8DEF;
                        color: white;
                        font-size: 14px;
                        cursor: pointer;
                        transition: all 0.2s;
                    ">确认</button>
                </div>
            `;

            overlay.appendChild(modal);
            document.body.appendChild(overlay);

            // 添加动画样式
            if (!document.getElementById('yunxi-modal-style')) {
                const style = document.createElement('style');
                style.id = 'yunxi-modal-style';
                style.textContent = `
                    @keyframes modalIn {
                        from { opacity: 0; transform: scale(0.95); }
                        to { opacity: 1; transform: scale(1); }
                    }
                `;
                document.head.appendChild(style);
            }

            modal.querySelector('.cancel-btn').addEventListener('click', () => {
                overlay.remove();
                resolve(false);
            });

            modal.querySelector('.confirm-btn').addEventListener('click', () => {
                overlay.remove();
                resolve(true);
            });

            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) {
                    overlay.remove();
                    resolve(false);
                }
            });
        });
    }

    // 添加动画样式
    const style = document.createElement('style');
    style.textContent = `
        @keyframes slideIn {
            from { transform: translateX(100%); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }
        @keyframes slideOut {
            from { transform: translateX(0); opacity: 1; }
            to { transform: translateX(100%); opacity: 0; }
        }
    `;
    document.head.appendChild(style);

    // 自动启动状态同步（页面加载后）
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            // 延迟启动，避免影响首屏
            setTimeout(updateButtonsBySystemStatus, 1000);
        });
    } else {
        setTimeout(updateButtonsBySystemStatus, 1000);
    }

    // 公开接口
    return {
        getToken,
        setToken,
        clearToken,
        isLoggedIn,
        getCurrentUser,
        login,
        logout,
        fetchCurrentUser,
        request,
        // 任务
        submitTask,
        getTask,
        listTasks,
        cancelTask,
        // 模块
        listModules,
        getModuleHealth,
        startModule,
        stopModule,
        restartModule,
        getModuleDetail,
        // 部署
        pullModel,
        commitChanges,
        packageModule,
        pairDevice,
        deployAll,
        rollbackVersion,
        // 监控
        getMonitorOverview,
        getMonitorMetrics,
        getRealtimeMetrics,
        getMonitorLogs,
        getAlertList,
        createAlert,
        acknowledgeAlert,
        getModuleHealthDetail,
        // 设置
        getSettings,
        saveSettings,
        listUsers,
        createUser,
        updateUser,
        deleteUser,
        changePassword,
        // 公告
        getAnnouncements,
        // 系统
        getSystemHealth,
        getSystemStats,
        getSystemStatus,
        validateSystem,
        withValidation,
        // UI
        showToast,
        showLoading,
        hideLoading,
        setButtonDisabled,
        updateButtonsBySystemStatus,
        silentCheck,
        showConfirm,
        redirectToLogin,
    };
})();
