/**
 * YunXi UI Kit - Button Component
 * 云汐组件库 - 按钮组件
 *
 * Usage:
 *   const btn = YunXiUI.Button.create({ text: 'Click me', type: 'primary' });
 *   document.body.appendChild(btn);
 *
 *   // Or with HTML:
 *   <button class="yx-btn yx-btn--primary">Click me</button>
 */

(function (global) {
  'use strict';

  const Button = {
    /**
     * Create a button element
     * @param {Object} options
     * @param {string} [options.text] - Button text
     * @param {string} [options.type='primary'] - primary | secondary | outline | ghost | danger | success | warning | link
     * @param {string} [options.size='md'] - sm | md | lg
     * @param {boolean} [options.disabled=false]
     * @param {boolean} [options.loading=false]
     * @param {boolean} [options.block=false]
     * @param {boolean} [options.round=false]
     * @param {boolean} [options.icon=false]
     * @param {string} [options.iconSvg] - SVG string for icon
     * @param {string} [options.iconPosition='left'] - left | right
     * @param {string} [options.htmlType='button'] - button | submit | reset
     * @param {Function} [options.onClick]
     * @param {string} [options.className] - Additional class names
     * @returns {HTMLButtonElement}
     */
    create(options) {
      options = options || {};
      const btn = document.createElement('button');
      btn.type = options.htmlType || 'button';

      // Base class
      let classes = ['yx-btn'];

      // Type
      const type = options.type || 'primary';
      classes.push('yx-btn--' + type);

      // Size
      const size = options.size || 'md';
      if (size !== 'md') classes.push('yx-btn--' + size);

      // Block
      if (options.block) classes.push('yx-btn--block');

      // Round
      if (options.round) classes.push('yx-btn--round');

      // Icon button
      if (options.icon) classes.push('yx-btn--icon');

      // Loading
      if (options.loading) classes.push('yx-btn--loading');

      // Disabled
      if (options.disabled) btn.disabled = true;

      // Additional classes
      if (options.className) classes.push(options.className);

      btn.className = classes.join(' ');

      // Icon
      if (options.iconSvg) {
        const iconEl = document.createElement('span');
        iconEl.className = 'yx-btn__icon';
        iconEl.innerHTML = options.iconSvg;
        if (options.iconPosition === 'right') {
          btn.appendChild(document.createElement('span')).className = 'yx-btn__text';
          btn.lastChild.textContent = options.text || '';
          btn.appendChild(iconEl);
        } else {
          btn.appendChild(iconEl);
          const textEl = document.createElement('span');
          textEl.className = 'yx-btn__text';
          textEl.textContent = options.text || '';
          btn.appendChild(textEl);
        }
      } else if (options.text) {
        const textEl = document.createElement('span');
        textEl.className = 'yx-btn__text';
        textEl.textContent = options.text;
        btn.appendChild(textEl);
      }

      // Loading spinner
      const spinner = document.createElement('span');
      spinner.className = 'yx-btn__spinner';
      btn.appendChild(spinner);

      // Click handler
      if (typeof options.onClick === 'function') {
        btn.addEventListener('click', options.onClick);
      }

      return btn;
    },

    /**
     * Set button loading state
     * @param {HTMLButtonElement} btn
     * @param {boolean} loading
     */
    setLoading(btn, loading) {
      if (!btn) return;
      if (loading) {
        btn.classList.add('yx-btn--loading');
        btn.disabled = true;
      } else {
        btn.classList.remove('yx-btn--loading');
        btn.disabled = false;
      }
    },

    /**
     * Set button disabled state
     * @param {HTMLButtonElement} btn
     * @param {boolean} disabled
     */
    setDisabled(btn, disabled) {
      if (!btn) return;
      btn.disabled = disabled;
      if (disabled) {
        btn.classList.add('yx-btn--disabled');
      } else {
        btn.classList.remove('yx-btn--disabled');
      }
    },

    /**
     * Set button text
     * @param {HTMLButtonElement} btn
     * @param {string} text
     */
    setText(btn, text) {
      if (!btn) return;
      const textEl = btn.querySelector('.yx-btn__text');
      if (textEl) {
        textEl.textContent = text;
      }
    }
  };

  // Export
  global.YunXiUI = global.YunXiUI || {};
  global.YunXiUI.Button = Button;

})(typeof window !== 'undefined' ? window : this);
