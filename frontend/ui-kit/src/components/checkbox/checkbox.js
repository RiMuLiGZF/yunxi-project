/**
 * YunXi UI Kit - Checkbox Component
 * 云汐组件库 - 复选框组件
 */

(function (global) {
  'use strict';

  const CHECK_ICON = '<polyline points="20 6 9 17 4 12"></polyline>';

  const Checkbox = {
    /**
     * Create a checkbox
     * @param {Object} options
     * @param {string} [options.label]
     * @param {boolean} [options.checked=false]
     * @param {boolean} [options.indeterminate=false]
     * @param {boolean} [options.disabled=false]
     * @param {string} [options.size='md'] - sm | md | lg
     * @param {string} [options.value]
     * @param {string} [options.name]
     * @param {Function} [options.onChange]
     * @returns {HTMLLabelElement}
     */
    create(options) {
      options = options || {};

      const label = document.createElement('label');
      let classes = ['yx-checkbox'];
      if (options.size && options.size !== 'md') classes.push('yx-checkbox--' + options.size);
      if (options.checked) classes.push('yx-checkbox--checked');
      if (options.indeterminate) classes.push('yx-checkbox--indeterminate');
      if (options.disabled) classes.push('yx-checkbox--disabled');

      label.className = classes.join(' ');

      // Hidden input
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.className = 'yx-checkbox__input';
      input.checked = !!options.checked;
      input.disabled = !!options.disabled;
      if (options.value !== undefined) input.value = options.value;
      if (options.name) input.name = options.name;
      label.appendChild(input);

      // Box
      const box = document.createElement('span');
      box.className = 'yx-checkbox__box';
      box.innerHTML = '<svg viewBox="0 0 24 24">' + CHECK_ICON + '</svg>' +
        '<span class="yx-checkbox__indeterminate-icon"></span>';
      label.appendChild(box);

      // Label text
      if (options.label) {
        const text = document.createElement('span');
        text.className = 'yx-checkbox__label';
        text.textContent = options.label;
        label.appendChild(text);
      }

      // Change handler
      input.addEventListener('change', function () {
        label.classList.toggle('yx-checkbox--checked', input.checked);
        if (input.checked) label.classList.remove('yx-checkbox--indeterminate');
        if (typeof options.onChange === 'function') {
          options.onChange(input.checked, input.value);
        }
      });

      // API
      label._checkbox = {
        isChecked: function () { return input.checked; },
        setChecked: function (checked) {
          input.checked = !!checked;
          label.classList.toggle('yx-checkbox--checked', input.checked);
          if (checked) label.classList.remove('yx-checkbox--indeterminate');
        },
        setIndeterminate: function (indeterminate) {
          input.indeterminate = indeterminate;
          label.classList.toggle('yx-checkbox--indeterminate', indeterminate);
          if (indeterminate) label.classList.remove('yx-checkbox--checked');
        },
        setDisabled: function (disabled) {
          input.disabled = disabled;
          label.classList.toggle('yx-checkbox--disabled', disabled);
        }
      };

      return label;
    },

    /**
     * Create a checkbox group
     * @param {Object} options
     * @param {Array} options.options - [{label, value, disabled, checked}]
     * @param {Array} [options.value] - Selected values
     * @param {boolean} [options.horizontal=false]
     * @param {string} [options.size='md']
     * @param {Function} [options.onChange]
     * @returns {HTMLDivElement}
     */
    createGroup(options) {
      options = options || {};
      const opts = options.options || [];

      const group = document.createElement('div');
      group.className = 'yx-checkbox-group' + (options.horizontal ? ' yx-checkbox-group--horizontal' : '');

      const checkboxes = [];
      let selectedValues = Array.isArray(options.value) ? options.value.slice() : [];

      opts.forEach(function (opt) {
        const checkbox = this.create({
          label: opt.label,
          value: opt.value,
          checked: selectedValues.indexOf(opt.value) > -1,
          disabled: opt.disabled,
          size: options.size || 'md',
          onChange: function (checked) {
            const idx = selectedValues.indexOf(opt.value);
            if (checked && idx === -1) {
              selectedValues.push(opt.value);
            } else if (!checked && idx > -1) {
              selectedValues.splice(idx, 1);
            }
            if (typeof options.onChange === 'function') {
              options.onChange(selectedValues.slice());
            }
          }
        });
        checkboxes.push(checkbox);
        group.appendChild(checkbox);
      }, this);

      group._checkboxGroup = {
        getValue: function () { return selectedValues.slice(); },
        setValue: function (values) {
          selectedValues = Array.isArray(values) ? values.slice() : [];
          checkboxes.forEach(function (cb) {
            const val = cb.querySelector('input').value;
            cb._checkbox.setChecked(selectedValues.indexOf(val) > -1);
          });
        },
        setDisabled: function (disabled) {
          checkboxes.forEach(function (cb) {
            cb._checkbox.setDisabled(disabled);
          });
        }
      };

      return group;
    },

    isChecked(el) {
      return el && el._checkbox ? el._checkbox.isChecked() : false;
    },

    setChecked(el, checked) {
      if (el && el._checkbox) el._checkbox.setChecked(checked);
    },

    setIndeterminate(el, indeterminate) {
      if (el && el._checkbox) el._checkbox.setIndeterminate(indeterminate);
    },

    getGroupValue(el) {
      return el && el._checkboxGroup ? el._checkboxGroup.getValue() : [];
    },

    setGroupValue(el, values) {
      if (el && el._checkboxGroup) el._checkboxGroup.setValue(values);
    }
  };

  global.YunXiUI = global.YunXiUI || {};
  global.YunXiUI.Checkbox = Checkbox;

})(typeof window !== 'undefined' ? window : this);
