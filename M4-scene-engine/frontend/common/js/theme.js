/* ============================================================
   M8 云汐管理台 — 主题切换工具
   Theme Manager: Light/Dark mode with localStorage persistence
   ============================================================ */

(function() {
  'use strict';

  var STORAGE_KEY = 'yunxi-m8-theme';
  var THEME_LIGHT = 'light';
  var THEME_DARK = 'dark';

  /**
   * 获取当前主题
   * @returns {string} 'light' | 'dark'
   */
  function getTheme() {
    var saved = null;
    try {
      saved = localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      // localStorage 不可用时降级
    }

    if (saved === THEME_LIGHT || saved === THEME_DARK) {
      return saved;
    }

    // 自动检测系统偏好
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
      return THEME_DARK;
    }

    return THEME_LIGHT;
  }

  /**
   * 设置主题
   * @param {string} theme - 'light' | 'dark'
   */
  function setTheme(theme) {
    var html = document.documentElement;

    // 临时禁用过渡以实现即时切换感
    html.classList.add('theme-switching');

    if (theme === THEME_DARK) {
      html.classList.add('dark');
      html.classList.remove('light');
    } else {
      html.classList.remove('dark');
      html.classList.add('light');
    }

    // 保存偏好
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch (e) {
      // 忽略存储错误
    }

    // 触发自定义事件
    var event = new CustomEvent('themechange', { detail: { theme: theme } });
    window.dispatchEvent(event);

    // 恢复过渡
    // 强制 reflow 以确保过渡被正确重置
    void html.offsetWidth;
    requestAnimationFrame(function() {
      html.classList.remove('theme-switching');
    });
  }

  /**
   * 切换主题
   * @returns {string} 新的主题值
   */
  function toggleTheme() {
    var current = getTheme();
    var next = current === THEME_DARK ? THEME_LIGHT : THEME_DARK;
    setTheme(next);
    return next;
  }

  /**
   * 初始化主题 - 在页面加载早期应用，避免闪烁
   */
  function initTheme() {
    var theme = getTheme();
    var html = document.documentElement;

    if (theme === THEME_DARK) {
      if (!html.classList.contains('dark')) {
        html.classList.add('dark');
      }
    } else {
      html.classList.remove('dark');
    }

    html.setAttribute('data-theme', theme);
  }

  /**
   * 创建主题切换按钮
   * @param {Object} options - 配置选项
   * @returns {HTMLElement} 按钮元素
   */
  function createToggleButton(options) {
    options = options || {};
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'theme-toggle-btn';
    btn.setAttribute('aria-label', '切换主题');
    btn.setAttribute('title', '切换亮色/暗色模式');

    // 太阳图标 (SVG)
    var sunIcon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    sunIcon.setAttribute('class', 'theme-icon icon-sun');
    sunIcon.setAttribute('viewBox', '0 0 24 24');
    sunIcon.setAttribute('fill', 'none');
    sunIcon.setAttribute('stroke', 'currentColor');
    sunIcon.setAttribute('stroke-width', '2');
    sunIcon.setAttribute('stroke-linecap', 'round');
    sunIcon.setAttribute('stroke-linejoin', 'round');
    sunIcon.innerHTML =
      '<circle cx="12" cy="12" r="4"></circle>' +
      '<path d="M12 2v2"></path>' +
      '<path d="M12 20v2"></path>' +
      '<path d="m4.93 4.93 1.41 1.41"></path>' +
      '<path d="m17.66 17.66 1.41 1.41"></path>' +
      '<path d="M2 12h2"></path>' +
      '<path d="M20 12h2"></path>' +
      '<path d="m6.34 17.66-1.41 1.41"></path>' +
      '<path d="m19.07 4.93-1.41 1.41"></path>';

    // 月亮图标 (SVG)
    var moonIcon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    moonIcon.setAttribute('class', 'theme-icon icon-moon');
    moonIcon.setAttribute('viewBox', '0 0 24 24');
    moonIcon.setAttribute('fill', 'none');
    moonIcon.setAttribute('stroke', 'currentColor');
    moonIcon.setAttribute('stroke-width', '2');
    moonIcon.setAttribute('stroke-linecap', 'round');
    moonIcon.setAttribute('stroke-linejoin', 'round');
    moonIcon.innerHTML =
      '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"></path>';

    btn.appendChild(sunIcon);
    btn.appendChild(moonIcon);

    btn.addEventListener('click', function() {
      toggleTheme();
    });

    return btn;
  }

  /**
   * 自动初始化页面上的主题切换按钮
   * 查找所有 [data-theme-toggle] 元素并替换为按钮
   */
  function initToggleButtons() {
    var placeholders = document.querySelectorAll('[data-theme-toggle]');
    placeholders.forEach(function(placeholder) {
      var btn = createToggleButton();
      // 复制所有自定义属性
      if (placeholder.className) {
        btn.className = 'theme-toggle-btn ' + placeholder.className;
      }
      placeholder.parentNode.replaceChild(btn, placeholder);
    });
  }

  // 监听系统主题变化（仅当用户未手动设置时）
  function listenSystemThemeChange() {
    if (!window.matchMedia) return;

    var mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');

    var handler = function(e) {
      var saved = null;
      try {
        saved = localStorage.getItem(STORAGE_KEY);
      } catch (err) {}

      // 只有用户没有手动设置时才跟随系统
      if (saved !== THEME_LIGHT && saved !== THEME_DARK) {
        setTheme(e.matches ? THEME_DARK : THEME_LIGHT);
      }
    };

    if (mediaQuery.addEventListener) {
      mediaQuery.addEventListener('change', handler);
    } else if (mediaQuery.addListener) {
      mediaQuery.addListener(handler);
    }
  }

  // 立即初始化主题（防止闪烁）
  initTheme();

  // DOM 就绪后初始化切换按钮
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
      initToggleButtons();
      listenSystemThemeChange();
    });
  } else {
    initToggleButtons();
    listenSystemThemeChange();
  }

  // 暴露全局 API
  window.YunxiTheme = {
    getTheme: getTheme,
    setTheme: setTheme,
    toggleTheme: toggleTheme,
    createToggleButton: createToggleButton,
    THEME_LIGHT: THEME_LIGHT,
    THEME_DARK: THEME_DARK
  };
})();
