/**
 * YunXi UI Kit - Radio Component
 * 云汐组件库 - 单选框组件
 */

(function (global) {
  'use strict';

  const Radio = {
    /**
     * Create a radio button
     * @param {Object} options
     * @param {string} [options.label]
     * @param {boolean} [options.checked=false]
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
      let classes = ['yx-radio'];
      if (options.size && options.size !== 'md') classes.push('yx-radio--' + options.size);
      if (options.checked) classes.push('yx-radio--checked');
      if (options.disabled) classes.push('yx-radio--disabled');

      label.className = classes.join(' ');

      const input = document.createElement('input');
      input.type = 'radio';
      input.className = 'yx-radio__input';
      input.checked = !!options.checked;
      input.disabled = !!options.disabled;
      if (options.value !== undefined) input.value = options.value;
      if (options.name) input.name = options.name;
      label.appendChild(input);

      const circle = document.createElement('span');
      circle.className = 'yx-radio__circle';
      circle.innerHTML = '<span class="yx-radio__dot"></span>';
      label.appendChild(circle);

      if (options.label) {
        const text = document.createElement('span');
        text.className = 'yx-radio__label';
        text.textContent = options.label;
        label.appendChild(text);
      }

      input.addEventListener('change', function () {
        if (input.checked) {
          label.classList.add('yx-radio--checked');
          // Uncheck siblings with same name
          if (options.name) {
            const siblings = document.querySelectorAll('input[type="radio"][name="' + options.name + '"]');
            siblings.forEach(function (sib) {
              if (sib !== input) {
                const sibLabel = sib.closest('.yx-radio');
                if (sibLabel) sibLabel.classList.remove('yx-radio--checked');
              }
            });
          }
          if (typeof options.onChange === 'function') {
            options.onChange(input.value);
          }
        }
      });

      label._radio = {
        isChecked: function () { return input.checked; },
        setChecked: function (checked) {
          input.checked = !!checked;
          label.classList.toggle('yx-radio--checked', checked);
        },
        setDisabled: function (disabled) {
          input.disabled = disabled;
          label.classList.toggle('yx-radio--disabled', disabled);
        }
      };

      return label;
    },

    /**
     * Create a radio group
     * @param {Object} options
     * @param {Array} options.options - [{label, value, disabled}]
     * @param {string} [options.value] - Selected value
     * @param {string} [options.name]
     * @param {boolean} [options.horizontal=false]
     * @param {boolean} [options.buttonStyle=false]
     * @param {string} [options.size='md']
     * @param {Function} [options.onChange]
     * @returns {HTMLDivElement}
     */
    createGroup(options) {
      options = options || {};
      const opts = options.options || [];
      const groupName = options.name || ('yx-radio-' + Math.random().toString(36).slice(2, 9));

      const group = document.createElement('div');
      let groupClasses = ['yx-radio-group'];
      if (options.horizontal || options.buttonStyle) groupClasses.push('yx-radio-group--horizontal');
      if (options.buttonStyle) groupClasses.push('yx-radio-group--buttons');
      group.className = groupClasses.join(' ');

      const radios = [];
      let selectedValue = options.value !== undefined ? options.value : null;

      opts.forEach(function (opt) {
        const radio = this.create({
          label: opt.label,
          value: opt.value,
          name: groupName,
          checked: opt.value === selectedValue,
          disabled: opt.disabled,
          size: options.size || 'md',
          onChange: function (val) {
            selectedValue = val;
            if (typeof options.onChange === 'function') {
              options.onChange(val);
            }
          }
        });
        radios.push(radio);
        group.appendChild(radio);
      }, this);

      group._radioGroup = {
        getValue: function () { return selectedValue; },
        setValue: function (val) {
          selectedValue = val;
          radios.forEach(function (r) {
            const input = r.querySelector('input');
            const checked = input.value === val;
            input.checked = checked;
            r.classList.toggle('yx-radio--checked', checked);
          });
        },
        setDisabled: function (disabled) {
          radios.forEach(function (r) {
            r._radio.setDisabled(disabled);
          });
        }
      };

      return group;
    },

    isChecked(el) {
      return el && el._radio ? el._radio.isChecked() : false;
    },

    setChecked(el, checked) {
      if (el && el._radio) el._radio.setChecked(checked);
    },

    getGroupValue(el) {
      return el && el._radioGroup ? el._radioGroup.getValue() : null;
    },

    setGroupValue(el, value) {
      if (el && el._radioGroup) el._radioGroup.setValue(value);
    }
  };

  global.YunXiUI = global.YunXiUI || {};
  global.YunXiUI.Radio = Radio;

})(typeof window !== 'undefined' ? window : this);
