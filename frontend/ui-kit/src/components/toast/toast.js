/**
 * YunXi UI Kit - Toast Component
 * 云汐组件库 - 消息提示组件
 */

(function (global) {
  'use strict';

  const ICONS = {
    success: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline>',
    error: '<circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line>',
    warning: '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line>',
    info: '<circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line>',
    loading: '<path d="M21 12a9 9 0 1 1-6.219-8.56"></path>',
    close: '<line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line>'
  };

  const containers = {};

  function getContainer(position) {
    position = position || 'top';
    if (containers[position]) return containers[position];

    const container = document.createElement('div');
    container.className = 'yx-toast-container' + (position === 'bottom' ? ' yx-toast-container--bottom' : '');
    document.body.appendChild(container);
    containers[position] = container;
    return container;
  }

  const Toast = {
    /**
     * Show a toast
     * @param {Object|string} options - Options object or message string
     * @param {string} options.message - Toast message
     * @param {string} [options.type='info'] - success | error | warning | info | loading
     * @param {number} [options.duration=3000] - Duration in ms, 0 for persistent
     * @param {string} [options.position='top'] - top | bottom
     * @param {boolean} [options.closable=false]
     * @param {Function} [options.onClose]
     * @returns {Object} toast instance with close method
     */
    show(options) {
      if (typeof options === 'string') {
        options = { message: options };
      }
      options = options || {};

      const type = options.type || 'info';
      const duration = options.duration !== undefined ? options.duration : 3000;
      const position = options.position || 'top';
      const container = getContainer(position);

      const toast = document.createElement('div');
      toast.className = 'yx-toast yx-toast--' + type;

      // Icon
      const icon = document.createElement('span');
      icon.className = 'yx-toast__icon';
      icon.innerHTML = '<svg viewBox="0 0 24 24">' + (ICONS[type] || ICONS.info) + '</svg>';
      toast.appendChild(icon);

      // Content
      const content = document.createElement('span');
      content.className = 'yx-toast__content';
      content.textContent = options.message || '';
      toast.appendChild(content);

      // Close button
      if (options.closable || duration === 0) {
        const closeBtn = document.createElement('button');
        closeBtn.className = 'yx-toast__close';
        closeBtn.setAttribute('aria-label', '关闭');
        closeBtn.innerHTML = '<svg viewBox="0 0 24 24">' + ICONS.close + '</svg>';
        closeBtn.addEventListener('click', function () {
          instance.close();
        });
        toast.appendChild(closeBtn);
      }

      container.appendChild(toast);

      const instance = {
        element: toast,
        isClosed: false,

        close: function () {
          if (this.isClosed) return;
          this.isClosed = true;
          toast.classList.add('yx-toast--leaving');

          var self = this;
          setTimeout(function () {
            if (toast.parentNode) {
              toast.parentNode.removeChild(toast);
            }
            if (typeof options.onClose === 'function') {
              options.onClose();
            }
            // Clean up container if empty
            if (container.children.length === 0 && container.parentNode) {
              container.parentNode.removeChild(container);
              delete containers[position];
            }
          }, 300);
        },

        update: function (message) {
          content.textContent = message;
        }
      };

      // Auto close
      if (duration > 0 && type !== 'loading') {
        setTimeout(function () {
          instance.close();
        }, duration);
      }

      return instance;
    },

    /**
     * Show success toast
     */
    success(message, duration) {
      return this.show({ message: message, type: 'success', duration: duration });
    },

    /**
     * Show error toast
     */
    error(message, duration) {
      return this.show({ message: message, type: 'error', duration: duration });
    },

    /**
     * Show warning toast
     */
    warning(message, duration) {
      return this.show({ message: message, type: 'warning', duration: duration });
    },

    /**
     * Show info toast
     */
    info(message, duration) {
      return this.show({ message: message, type: 'info', duration: duration });
    },

    /**
     * Show loading toast
     */
    loading(message) {
      return this.show({ message: message || '加载中...', type: 'loading', duration: 0 });
    }
  };

  global.YunXiUI = global.YunXiUI || {};
  global.YunXiUI.Toast = Toast;

})(typeof window !== 'undefined' ? window : this);
