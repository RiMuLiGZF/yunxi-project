/**
 * YunXi UI Kit - Input Component
 * 云汐组件库 - 输入框组件
 */

(function (global) {
  'use strict';

  const EYE_ICON = '<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>';
  const EYE_OFF_ICON = '<path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"/><path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"/><path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"/><line x1="2" x2="22" y1="2" y2="22"/>';
  const SEARCH_ICON = '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>';

  const Input = {
    /**
     * Create an input element
     * @param {Object} options
     * @param {string} [options.type='text'] - text | password | number | search | email | tel | url
     * @param {string} [options.placeholder]
     * @param {string} [options.value]
     * @param {string} [options.size='md'] - sm | md | lg
     * @param {string} [options.status=''] - '' | success | warning | error
     * @param {boolean} [options.disabled=false]
     * @param {boolean} [options.readonly=false]
     * @param {string} [options.prefixIcon] - SVG string
     * @param {string} [options.suffixIcon] - SVG string
     * @param {boolean} [options.clearable=false]
     * @param {string} [options.label]
     * @param {boolean} [options.required=false]
     * @param {string} [options.helpText]
     * @param {string} [options.errorText]
     * @param {string} [options.name]
     * @param {number} [options.maxLength]
     * @param {Function} [options.onChange]
     * @param {Function} [options.onInput]
     * @param {Function} [options.onFocus]
     * @param {Function} [options.onBlur]
     * @param {string} [options.className]
     * @returns {HTMLElement} wrapper element
     */
    create(options) {
      options = options || {};
      const type = options.type || 'text';

      // Create input group if label or help/error text
      if (options.label || options.helpText || options.errorText) {
        return this._createWithLabel(type, options);
      }

      return this._createInput(type, options);
    },

    _createInput(type, options) {
      const wrapper = document.createElement('div');
      let wrapperClasses = ['yx-input-wrapper'];

      if (options.prefixIcon || type === 'search') {
        wrapperClasses.push('yx-input-wrapper--prefix');
      }
      if (options.suffixIcon || type === 'password' || options.clearable) {
        wrapperClasses.push('yx-input-wrapper--suffix');
      }

      wrapper.className = wrapperClasses.join(' ');

      // Input element
      const input = document.createElement('input');
      input.type = type === 'search' ? 'text' : type;
      input.className = this._getInputClasses(type, options);
      input.placeholder = options.placeholder || '';
      if (options.value) input.value = options.value;
      if (options.disabled) input.disabled = true;
      if (options.readonly) input.readOnly = true;
      if (options.name) input.name = options.name;
      if (options.maxLength) input.maxLength = options.maxLength;

      // Prefix icon
      if (options.prefixIcon || type === 'search') {
        const prefix = document.createElement('span');
        prefix.className = 'yx-input__prefix';
        prefix.innerHTML = options.prefixIcon || SEARCH_ICON;
        wrapper.appendChild(prefix);
      }

      wrapper.appendChild(input);

      // Password toggle
      if (type === 'password') {
        const toggleBtn = document.createElement('button');
        toggleBtn.type = 'button';
        toggleBtn.className = 'yx-input__toggle-password';
        toggleBtn.setAttribute('aria-label', '切换密码可见性');
        toggleBtn.innerHTML = EYE_ICON;
        toggleBtn.addEventListener('click', function () {
          if (input.type === 'password') {
            input.type = 'text';
            toggleBtn.innerHTML = EYE_OFF_ICON;
          } else {
            input.type = 'password';
            toggleBtn.innerHTML = EYE_ICON;
          }
        });
        wrapper.appendChild(toggleBtn);
      }

      // Suffix icon
      if (options.suffixIcon && type !== 'password') {
        const suffix = document.createElement('span');
        suffix.className = 'yx-input__suffix' + (options.suffixClickable ? ' yx-input__suffix--clickable' : '');
        suffix.innerHTML = options.suffixIcon;
        wrapper.appendChild(suffix);
      }

      // Clear button
      if (options.clearable) {
        const clearBtn = document.createElement('span');
        clearBtn.className = 'yx-input__suffix yx-input__suffix--clickable yx-input__clear';
        clearBtn.style.display = 'none';
        clearBtn.innerHTML = '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="15" x2="9" y1="9" y2="15"/><line x1="9" x2="15" y1="9" y2="15"/></svg>';
        clearBtn.addEventListener('click', function () {
          input.value = '';
          input.dispatchEvent(new Event('input', { bubbles: true }));
          input.dispatchEvent(new Event('change', { bubbles: true }));
          input.focus();
          clearBtn.style.display = 'none';
        });
        wrapper.appendChild(clearBtn);

        input.addEventListener('input', function () {
          clearBtn.style.display = input.value ? 'flex' : 'none';
        });
      }

      // Event handlers
      if (typeof options.onChange === 'function') {
        input.addEventListener('change', options.onChange);
      }
      if (typeof options.onInput === 'function') {
        input.addEventListener('input', options.onInput);
      }
      if (typeof options.onFocus === 'function') {
        input.addEventListener('focus', options.onFocus);
      }
      if (typeof options.onBlur === 'function') {
        input.addEventListener('blur', options.onBlur);
      }

      // Store input reference
      wrapper._input = input;

      return wrapper;
    },

    _createWithLabel(type, options) {
      const group = document.createElement('div');
      group.className = 'yx-input-group';

      if (options.label) {
        const label = document.createElement('label');
        label.className = 'yx-input-group__label' + (options.required ? ' yx-input-group__label--required' : '');
        label.textContent = options.label;
        group.appendChild(label);
      }

      const inputWrapper = this._createInput(type, options);
      group.appendChild(inputWrapper);

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

      group._input = inputWrapper._input;
      return group;
    },

    _getInputClasses(type, options) {
      let classes = ['yx-input'];

      const size = options.size || 'md';
      if (size !== 'md') classes.push('yx-input--' + size);

      if (options.status) classes.push('yx-input--' + options.status);
      if (type === 'search') classes.push('yx-input--search');
      if (type === 'password') classes.push('yx-input--password');
      if (options.className) classes.push(options.className);

      return classes.join(' ');
    },

    /**
     * Get the input element from wrapper
     * @param {HTMLElement} wrapper
     * @returns {HTMLInputElement}
     */
    getInput(wrapper) {
      return wrapper && wrapper._input ? wrapper._input : null;
    },

    /**
     * Get input value
     */
    getValue(wrapper) {
      const input = this.getInput(wrapper);
      return input ? input.value : '';
    },

    /**
     * Set input value
     */
    setValue(wrapper, value) {
      const input = this.getInput(wrapper);
      if (input) {
        input.value = value;
        input.dispatchEvent(new Event('input', { bubbles: true }));
      }
    },

    /**
     * Set validation status
     * @param {HTMLElement} wrapper
     * @param {string} status - '' | success | warning | error
     * @param {string} [message]
     */
    setStatus(wrapper, status, message) {
      if (!wrapper) return;
      const input = this.getInput(wrapper);
      if (!input) return;

      input.classList.remove('yx-input--success', 'yx-input--warning', 'yx-input--error');
      if (status) input.classList.add('yx-input--' + status);

      // Update or create error/help message
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

    /**
     * Focus the input
     */
    focus(wrapper) {
      const input = this.getInput(wrapper);
      if (input) input.focus();
    },

    /**
     * Blur the input
     */
    blur(wrapper) {
      const input = this.getInput(wrapper);
      if (input) input.blur();
    }
  };

  global.YunXiUI = global.YunXiUI || {};
  global.YunXiUI.Input = Input;

})(typeof window !== 'undefined' ? window : this);
