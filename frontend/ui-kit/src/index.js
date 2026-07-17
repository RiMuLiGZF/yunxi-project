/**
 * YunXi UI Kit - Main Entry Point
 * 云汐组件库 - 主入口文件
 * 
 * 完整引入方式：
 *   <link rel="stylesheet" href="ui-kit/index.css">
 *   <script src="ui-kit/index.js"></script>
 *
 * 按需引入方式：
 *   <link rel="stylesheet" href="ui-kit/src/components/button/button.css">
 *   <script src="ui-kit/src/components/button/button.js"></script>
 * 
 * 使用方式：
 *   const btn = YunXiUI.Button.create({ text: '点击', type: 'primary' });
 *   document.body.appendChild(btn);
 * 
 * 或者直接使用 CSS class：
 *   <button class="yx-btn yx-btn--primary">点击</button>
 */

(function (global) {
  'use strict';

  // Initialize theme early (prevents flash)
  if (global.YunXiUI && global.YunXiUI.Utils && global.YunXiUI.Utils.Theme) {
    global.YunXiUI.Utils.Theme.init();
  }

  // Version
  const VERSION = '1.0.0';

  // Ensure namespace exists
  const YunXiUI = global.YunXiUI || {};
  YunXiUI.VERSION = VERSION;

  /**
   * Initialize the UI Kit
   * Auto-discovers and enhances elements with data-yx-* attributes
   */
  YunXiUI.init = function (options) {
    options = options || {};

    // Initialize theme if not already done
    if (options.theme) {
      if (YunXiUI.Utils && YunXiUI.Utils.Theme) {
        YunXiUI.Utils.Theme.set(options.theme);
      }
    }

    return YunXiUI;
  };

  /**
   * Get all available component names
   */
  YunXiUI.getComponents = function () {
    const components = [];
    for (const key in YunXiUI) {
      if (
        YunXiUI.hasOwnProperty(key) &&
        typeof YunXiUI[key] === 'object' &&
        YunXiUI[key] !== null &&
        key !== 'Utils' &&
        key !== 'VERSION' &&
        typeof YunXiUI[key].create === 'function'
      ) {
        components.push(key);
      }
    }
    return components.sort();
  };

  // Re-export for convenience
  global.YunXiUI = YunXiUI;

  // Auto-init on DOM ready if not in a module environment
  if (global.document && global.document.readyState !== 'loading') {
    // Don't auto-init, let users call init() explicitly
  }

})(typeof window !== 'undefined' ? window : this);
