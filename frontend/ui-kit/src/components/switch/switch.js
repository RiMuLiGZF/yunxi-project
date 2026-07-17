/**
 * YunXi UI Kit - Switch Component
 * 云汐组件库 - 开关组件
 */

(function (global) {
  'use strict';

  const Switch = {
    /**
     * Create a switch
     * @param {Object} options
     * @param {string} [options.label]
     * @param {boolean} [options.checked=false]
     * @param {boolean} [options.disabled=false]
     * @param {boolean} [options.loading=false]
     * @param {string} [options.size='md'] - sm | md | lg
     * @param {Function} [options.onChange]
     * @param {Function} [options.beforeChange] - Return false to prevent change
     * @returns {HTMLLabelElement}
     */
    create(options) {
      options = options || {};

      const label = document.createElement('label');
      let classes = ['yx-switch'];
      if (options.size && options.size !== 'md') classes.push('yx-switch--' + options.size);
      if (options.checked) classes.push('yx-switch--checked');
      if (options.disabled) classes.push('yx-switch--disabled');
      if (options.loading) classes.push('yx-switch--loading');

      label.className = classes.join(' ');

      const input = document.createElement('input');
      input.type = 'checkbox';
      input.className = 'yx-switch__input';
      input.checked = !!options.checked;
      input.disabled = !!options.disabled;
      label.appendChild(input);

      const track = document.createElement('span');
      track.className = 'yx-switch__track';
      track.innerHTML = '<span class="yx-switch__thumb"></span>';
      label.appendChild(track);

      if (options.label) {
        const text = document.createElement('span');
        text.className = 'yx-switch__label';
        text.textContent = options.label;
        label.appendChild(text);
      }

      function toggle() {
        if (options.disabled || options.loading) return;

        if (typeof options.beforeChange === 'function') {
          const result = options.beforeChange(!input.checked);
          if (result === false) return;
          if (result && typeof result.then === 'function') {
            label.classList.add('yx-switch--loading');
            result.then(function (allow) {
              label.classList.remove('yx-switch--loading');
              if (allow !== false) doToggle();
            }).catch(function () {
              label.classList.remove('yx-switch--loading');
            });
            return;
          }
        }

        doToggle();
      }

      function doToggle() {
        input.checked = !input.checked;
        label.classList.toggle('yx-switch--checked', input.checked);
        if (typeof options.onChange === 'function') {
          options.onChange(input.checked);
        }
      }

      input.addEventListener('change', function (e) {
        e.preventDefault();
        toggle();
      });

      label.addEventListener('click', function (e) {
        e.preventDefault();
        toggle();
      });

      label._switch = {
        isChecked: function () { return input.checked; },
        setChecked: function (checked) {
          input.checked = !!checked;
          label.classList.toggle('yx-switch--checked', checked);
        },
        setDisabled: function (disabled) {
          options.disabled = disabled;
          input.disabled = disabled;
          label.classList.toggle('yx-switch--disabled', disabled);
        },
        setLoading: function (loading) {
          options.loading = loading;
          label.classList.toggle('yx-switch--loading', loading);
        },
        toggle: toggle
      };

      return label;
    },

    isChecked(el) {
      return el && el._switch ? el._switch.isChecked() : false;
    },

    setChecked(el, checked) {
      if (el && el._switch) el._switch.setChecked(checked);
    },

    setDisabled(el, disabled) {
      if (el && el._switch) el._switch.setDisabled(disabled);
    },

    setLoading(el, loading) {
      if (el && el._switch) el._switch.setLoading(loading);
    }
  };

  global.YunXiUI = global.YunXiUI || {};
  global.YunXiUI.Switch = Switch;

})(typeof window !== 'undefined' ? window : this);
