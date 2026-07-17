/**
 * YunXi UI Kit - Textarea Component
 * 云汐组件库 - 多行文本输入组件
 */

(function (global) {
  'use strict';

  const Textarea = {
    /**
     * Create a textarea element
     * @param {Object} options
     * @param {string} [options.placeholder]
     * @param {string} [options.value]
     * @param {string} [options.size='md'] - sm | md | lg
     * @param {string} [options.status=''] - '' | success | warning | error
     * @param {boolean} [options.disabled=false]
     * @param {boolean} [options.readonly=false]
     * @param {number} [options.rows=3]
     * @param {number} [options.maxLength]
     * @param {boolean} [options.showCount=false]
     * @param {boolean} [options.autoResize=false]
     * @param {string} [options.label]
     * @param {boolean} [options.required=false]
     * @param {string} [options.helpText]
     * @param {string} [options.errorText]
     * @param {string} [options.name]
     * @param {Function} [options.onChange]
     * @param {Function} [options.onInput]
     * @param {Function} [options.onFocus]
     * @param {Function} [options.onBlur]
     * @param {string} [options.className]
     * @returns {HTMLElement}
     */
    create(options) {
      options = options || {};

      if (options.label || options.helpText || options.errorText) {
        return this._createWithLabel(options);
      }

      return this._createTextarea(options);
    },

    _createTextarea(options) {
      const wrapper = document.createElement('div');
      let wrapperClasses = ['yx-textarea-wrapper'];
      if (options.showCount) wrapperClasses.push('yx-textarea-wrapper--count');
      wrapper.className = wrapperClasses.join(' ');

      const textarea = document.createElement('textarea');
      let classes = ['yx-textarea'];

      const size = options.size || 'md';
      if (size !== 'md') classes.push('yx-textarea--' + size);
      if (options.status) classes.push('yx-textarea--' + options.status);
      if (options.autoResize) classes.push('yx-textarea--auto-resize');
      if (options.className) classes.push(options.className);

      textarea.className = classes.join(' ');
      textarea.placeholder = options.placeholder || '';
      if (options.value) textarea.value = options.value;
      if (options.disabled) textarea.disabled = true;
      if (options.readonly) textarea.readOnly = true;
      if (options.name) textarea.name = options.name;
      if (options.rows) textarea.rows = options.rows;
      if (options.maxLength) textarea.maxLength = options.maxLength;

      wrapper.appendChild(textarea);

      // Character count
      if (options.showCount) {
        const countEl = document.createElement('span');
        countEl.className = 'yx-textarea__count';
        const current = (options.value || '').length;
        const max = options.maxLength || '';
        countEl.textContent = current + (max ? ' / ' + max : '');
        wrapper.appendChild(countEl);

        textarea.addEventListener('input', function () {
          countEl.textContent = textarea.value.length + (max ? ' / ' + max : '');
        });
      }

      // Auto resize
      if (options.autoResize) {
        const resize = function () {
          textarea.style.height = 'auto';
          textarea.style.height = textarea.scrollHeight + 'px';
        };
        textarea.addEventListener('input', resize);
        // Initial resize
        requestAnimationFrame(resize);
      }

      // Events
      if (typeof options.onChange === 'function') {
        textarea.addEventListener('change', options.onChange);
      }
      if (typeof options.onInput === 'function') {
        textarea.addEventListener('input', options.onInput);
      }
      if (typeof options.onFocus === 'function') {
        textarea.addEventListener('focus', options.onFocus);
      }
      if (typeof options.onBlur === 'function') {
        textarea.addEventListener('blur', options.onBlur);
      }

      wrapper._textarea = textarea;
      return wrapper;
    },

    _createWithLabel(options) {
      const group = document.createElement('div');
      group.className = 'yx-input-group';

      if (options.label) {
        const label = document.createElement('label');
        label.className = 'yx-input-group__label' + (options.required ? ' yx-input-group__label--required' : '');
        label.textContent = options.label;
        group.appendChild(label);
      }

      const wrapper = this._createTextarea(options);
      group.appendChild(wrapper);

      if (options.errorText) {
        const error = document.createElement('div');
        error.className = 'yx-input-group__error';
        error.textContent = options.errorText;
        group.appendChild(error);
      } else if (options.helpText) {
        const help = document.createElement('div');
        help.className = 'yx-input-group__help';
        help.textContent = options.helpText;
        group.appendChild(help);
      }

      group._textarea = wrapper._textarea;
      return group;
    },

    getTextarea(wrapper) {
      return wrapper && wrapper._textarea ? wrapper._textarea : null;
    },

    getValue(wrapper) {
      const ta = this.getTextarea(wrapper);
      return ta ? ta.value : '';
    },

    setValue(wrapper, value) {
      const ta = this.getTextarea(wrapper);
      if (ta) {
        ta.value = value;
        ta.dispatchEvent(new Event('input', { bubbles: true }));
      }
    },

    setStatus(wrapper, status, message) {
      if (!wrapper) return;
      const ta = this.getTextarea(wrapper);
      if (!ta) return;

      ta.classList.remove('yx-textarea--success', 'yx-textarea--warning', 'yx-textarea--error');
      if (status) ta.classList.add('yx-textarea--' + status);

      const group = wrapper.closest('.yx-input-group');
      if (group) {
        let msgEl = group.querySelector('.yx-input-group__error');
        if (status === 'error' && message) {
          if (!msgEl) {
            msgEl = document.createElement('div');
            msgEl.className = 'yx-input-group__error';
            group.appendChild(msgEl);
          }
          msgEl.textContent = message;
        } else if (msgEl) {
          msgEl.remove();
        }
      }
    },

    focus(wrapper) {
      const ta = this.getTextarea(wrapper);
      if (ta) ta.focus();
    },

    blur(wrapper) {
      const ta = this.getTextarea(wrapper);
      if (ta) ta.blur();
    }
  };

  global.YunXiUI = global.YunXiUI || {};
  global.YunXiUI.Textarea = Textarea;

})(typeof window !== 'undefined' ? window : this);
