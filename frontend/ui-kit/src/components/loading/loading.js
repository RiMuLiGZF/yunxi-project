/**
 * YunXi UI Kit - Loading Component
 * 云汐组件库 - 加载组件
 */

(function (global) {
  'use strict';

  const Loading = {
    /**
     * Create a spinner loading element
     * @param {Object} [options]
     * @param {string} [options.size='md'] - sm | md | lg
     * @param {string} [options.type='spinner'] - spinner | dots | pulse
     * @param {string} [options.text] - Loading text
     * @returns {HTMLElement}
     */
    create(options) {
      options = options || {};
      const type = options.type || 'spinner';
      const size = options.size || 'md';

      const wrapper = document.createElement('div');
      wrapper.className = 'yx-loading yx-loading--' + type +
        (size !== 'md' ? ' yx-loading--' + size : '');

      if (type === 'spinner') {
        const spinner = document.createElement('span');
        spinner.className = 'yx-loading__spinner';
        wrapper.appendChild(spinner);
      } else if (type === 'dots') {
        for (let i = 0; i < 3; i++) {
          const dot = document.createElement('span');
          dot.className = 'yx-loading__dot';
          wrapper.appendChild(dot);
        }
      } else if (type === 'pulse') {
        const pulse = document.createElement('span');
        pulse.className = 'yx-loading__pulse';
        wrapper.appendChild(pulse);
      }

      if (options.text) {
        const text = document.createElement('div');
        text.style.marginTop = '8px';
        text.style.fontSize = 'var(--yx-font-size-sm)';
        text.style.color = 'var(--yx-color-text-secondary)';
        text.textContent = options.text;
        wrapper.style.flexDirection = 'column';
        wrapper.style.gap = '8px';
        wrapper.appendChild(text);
      }

      return wrapper;
    },

    /**
     * Show fullscreen loading
     * @param {string} [text] - Loading text
     * @returns {Object} instance with close method
     */
    fullscreen(text) {
      const overlay = document.createElement('div');
      overlay.className = 'yx-loading-overlay';

      const spinner = this.create({ type: 'spinner', size: 'lg' });
      overlay.appendChild(spinner);

      if (text) {
        const textEl = document.createElement('div');
        textEl.className = 'yx-loading-overlay__text';
        textEl.textContent = text;
        overlay.appendChild(textEl);
      }

      document.body.appendChild(overlay);

      return {
        element: overlay,
        close: function () {
          if (overlay.parentNode) {
            overlay.style.opacity = '0';
            overlay.style.transition = 'opacity 0.2s ease';
            setTimeout(function () {
              if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
            }, 200);
          }
        }
      };
    },

    /**
     * Wrap a container with loading state
     * @param {HTMLElement} content - Content element
     * @param {Object} [options]
     * @param {boolean} [options.loading=false]
     * @param {string} [options.text]
     * @returns {HTMLElement}
     */
    container(content, options) {
      options = options || {};

      const container = document.createElement('div');
      container.className = 'yx-loading-container' + (options.loading ? ' yx-loading-container--loading' : '');

      const contentWrap = document.createElement('div');
      contentWrap.className = 'yx-loading-container__content';
      if (content instanceof HTMLElement) {
        contentWrap.appendChild(content);
      } else if (typeof content === 'string') {
        contentWrap.innerHTML = content;
      }
      container.appendChild(contentWrap);

      const spinnerWrap = document.createElement('div');
      spinnerWrap.className = 'yx-loading-container__spinner';
      spinnerWrap.style.display = options.loading ? 'flex' : 'none';
      spinnerWrap.appendChild(this.create({ type: 'spinner' }));

      if (options.text) {
        const text = document.createElement('span');
        text.className = 'yx-loading-container__text';
        text.textContent = options.text;
        spinnerWrap.appendChild(text);
      }

      container.appendChild(spinnerWrap);

      container._loading = {
        setLoading: function (loading, text) {
          container.classList.toggle('yx-loading-container--loading', loading);
          spinnerWrap.style.display = loading ? 'flex' : 'none';
          if (text !== undefined) {
            const textEl = spinnerWrap.querySelector('.yx-loading-container__text');
            if (textEl) textEl.textContent = text;
          }
        }
      };

      return container;
    },

    /**
     * Create skeleton elements
     * @param {Object} options
     * @param {string} [options.variant='text'] - text | circle | rect | paragraph
     * @param {string} [options.width]
     * @param {string} [options.height]
     * @param {number} [options.rows=3] - For paragraph
     * @returns {HTMLElement}
     */
    skeleton(options) {
      options = options || {};
      const variant = options.variant || 'text';

      if (variant === 'paragraph') {
        const wrap = document.createElement('div');
        wrap.className = 'yx-skeleton-paragraph';
        const rows = options.rows || 3;
        for (let i = 0; i < rows; i++) {
          const line = document.createElement('span');
          line.className = 'yx-skeleton yx-skeleton--text';
          wrap.appendChild(line);
        }
        return wrap;
      }

      const el = document.createElement('span');
      el.className = 'yx-skeleton yx-skeleton--' + variant;
      if (options.width) el.style.width = options.width;
      if (options.height) el.style.height = options.height;
      return el;
    }
  };

  global.YunXiUI = global.YunXiUI || {};
  global.YunXiUI.Loading = Loading;

})(typeof window !== 'undefined' ? window : this);
