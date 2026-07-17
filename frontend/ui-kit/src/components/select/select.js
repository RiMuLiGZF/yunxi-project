/**
 * YunXi UI Kit - Select Component
 * 云汐组件库 - 下拉选择组件
 */

(function (global) {
  'use strict';

  const CHEVRON_DOWN = '<polyline points="6 9 12 15 18 9"></polyline>';
  const X_ICON = '<line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line>';
  const SEARCH_ICON = '<circle cx="11" cy="11" r="8"></circle><path d="m21 21-4.3-4.3"></path>';

  const Select = {
    /**
     * Create a select component
     * @param {Object} options
     * @param {Array} options.options - [{value, label, disabled}]
     * @param {string|Array} [options.value] - Selected value(s)
     * @param {string} [options.placeholder='请选择']
     * @param {string} [options.size='md'] - sm | md | lg
     * @param {boolean} [options.multiple=false]
     * @param {boolean} [options.searchable=false]
     * @param {boolean} [options.disabled=false]
     * @param {string} [options.status=''] - '' | error | success
     * @param {Function} [options.onChange]
     * @returns {HTMLElement}
     */
    create(options) {
      options = options || {};
      const opts = options.options || [];
      const multiple = !!options.multiple;

      const container = document.createElement('div');
      let classes = ['yx-select'];
      if (options.size && options.size !== 'md') classes.push('yx-select--' + options.size);
      if (multiple) classes.push('yx-select--multiple');
      if (options.disabled) classes.push('yx-select--disabled');
      if (options.status) classes.push('yx-select--' + options.status);

      container.className = classes.join(' ');
      container.tabIndex = options.disabled ? -1 : 0;
      container.setAttribute('role', 'listbox');
      container.setAttribute('aria-haspopup', 'listbox');

      // Trigger
      const trigger = document.createElement('div');
      trigger.className = 'yx-select__trigger';

      const valueEl = document.createElement('div');
      valueEl.className = 'yx-select__value';
      trigger.appendChild(valueEl);

      const arrow = document.createElement('span');
      arrow.className = 'yx-select__arrow';
      arrow.innerHTML = '<svg viewBox="0 0 24 24">' + CHEVRON_DOWN + '</svg>';
      trigger.appendChild(arrow);

      container.appendChild(trigger);

      // Dropdown
      const dropdown = document.createElement('div');
      dropdown.className = 'yx-select__dropdown';
      dropdown.setAttribute('role', 'listbox');

      // Search
      if (options.searchable) {
        const searchWrap = document.createElement('div');
        searchWrap.className = 'yx-select__search';
        searchWrap.innerHTML = '<span style="position:absolute;left:10px;top:50%;transform:translateY(-50%);color:var(--yx-color-text-tertiary);width:14px;height:14px;">' +
          '<svg viewBox="0 0 24 24" style="width:100%;height:100%;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;">' + SEARCH_ICON + '</svg></span>';
        const searchInput = document.createElement('input');
        searchInput.type = 'text';
        searchInput.placeholder = '搜索...';
        searchWrap.appendChild(searchInput);
        dropdown.appendChild(searchWrap);

        searchInput.addEventListener('input', function (e) {
          const keyword = e.target.value.toLowerCase();
          const optionEls = optionsEl.querySelectorAll('.yx-select__option');
          optionEls.forEach(function (opt) {
            const text = opt.textContent.toLowerCase();
            opt.style.display = text.indexOf(keyword) > -1 ? '' : 'none';
          });
        });
      }

      // Options
      const optionsEl = document.createElement('div');
      optionsEl.className = 'yx-select__options';

      if (opts.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'yx-select__empty';
        empty.textContent = '暂无数据';
        optionsEl.appendChild(empty);
      } else {
        opts.forEach(function (opt) {
          const optionEl = document.createElement('div');
          optionEl.className = 'yx-select__option' + (opt.disabled ? ' yx-select__option--disabled' : '');
          optionEl.setAttribute('role', 'option');
          optionEl.setAttribute('data-value', opt.value);
          optionEl.textContent = opt.label;
          optionsEl.appendChild(optionEl);
        });
      }

      dropdown.appendChild(optionsEl);
      container.appendChild(dropdown);

      // State
      let selectedValue = multiple
        ? (Array.isArray(options.value) ? options.value.slice() : [])
        : (options.value !== undefined ? options.value : null);

      // Update display
      function updateDisplay() {
        if (multiple) {
          valueEl.innerHTML = '';
          if (selectedValue.length === 0) {
            valueEl.className = 'yx-select__value yx-select__placeholder';
            valueEl.textContent = options.placeholder || '请选择';
          } else {
            valueEl.className = 'yx-select__value';
            selectedValue.forEach(function (val) {
              const opt = opts.find(function (o) { return o.value === val; });
              if (opt) {
                const tag = document.createElement('span');
                tag.className = 'yx-select__tag';
                tag.innerHTML = opt.label + '<span class="yx-select__tag-close" data-value="' + val + '">' +
                  '<svg viewBox="0 0 24 24">' + X_ICON + '</svg></span>';
                valueEl.appendChild(tag);
              }
            });
          }
        } else {
          if (selectedValue === null || selectedValue === undefined) {
            valueEl.className = 'yx-select__value yx-select__placeholder';
            valueEl.textContent = options.placeholder || '请选择';
          } else {
            const opt = opts.find(function (o) { return o.value === selectedValue; });
            valueEl.className = 'yx-select__value';
            valueEl.textContent = opt ? opt.label : String(selectedValue);
          }
        }

        // Update selected class
        const optionEls = optionsEl.querySelectorAll('.yx-select__option');
        optionEls.forEach(function (optEl) {
          const val = optEl.getAttribute('data-value');
          const isSelected = multiple
            ? selectedValue.indexOf(val) > -1
            : val == selectedValue;
          optEl.classList.toggle('yx-select__option--selected', isSelected);
        });
      }

      // Toggle dropdown
      function openDropdown() {
        if (options.disabled) return;
        container.classList.add('yx-select--open');
        document.addEventListener('click', onOutsideClick);
      }

      function closeDropdown() {
        container.classList.remove('yx-select--open');
        document.removeEventListener('click', onOutsideClick);
      }

      function onOutsideClick(e) {
        if (!container.contains(e.target)) {
          closeDropdown();
        }
      }

      trigger.addEventListener('click', function (e) {
        e.stopPropagation();
        if (options.disabled) return;
        if (container.classList.contains('yx-select--open')) {
          closeDropdown();
        } else {
          openDropdown();
        }
      });

      // Option click
      optionsEl.addEventListener('click', function (e) {
        const optEl = e.target.closest('.yx-select__option');
        if (!optEl || optEl.classList.contains('yx-select__option--disabled')) return;

        const val = optEl.getAttribute('data-value');

        if (multiple) {
          const idx = selectedValue.indexOf(val);
          if (idx > -1) {
            selectedValue.splice(idx, 1);
          } else {
            selectedValue.push(val);
          }
          updateDisplay();
          if (typeof options.onChange === 'function') {
            options.onChange(selectedValue.slice());
          }
        } else {
          selectedValue = val;
          updateDisplay();
          closeDropdown();
          if (typeof options.onChange === 'function') {
            options.onChange(val);
          }
        }
      });

      // Tag close (for multiple)
      valueEl.addEventListener('click', function (e) {
        if (!multiple) return;
        const closeBtn = e.target.closest('.yx-select__tag-close');
        if (closeBtn) {
          e.stopPropagation();
          const val = closeBtn.getAttribute('data-value');
          const idx = selectedValue.indexOf(val);
          if (idx > -1) {
            selectedValue.splice(idx, 1);
            updateDisplay();
            if (typeof options.onChange === 'function') {
              options.onChange(selectedValue.slice());
            }
          }
        }
      });

      // Keyboard support
      container.addEventListener('keydown', function (e) {
        if (options.disabled) return;
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          if (container.classList.contains('yx-select--open')) {
            closeDropdown();
          } else {
            openDropdown();
          }
        } else if (e.key === 'Escape') {
          closeDropdown();
        }
      });

      updateDisplay();

      // API
      container._select = {
        getValue: function () { return multiple ? selectedValue.slice() : selectedValue; },
        setValue: function (val) {
          selectedValue = multiple ? (Array.isArray(val) ? val.slice() : []) : val;
          updateDisplay();
        },
        setOptions: function (newOpts) {
          opts.length = 0;
          Array.prototype.push.apply(opts, newOpts);
          optionsEl.innerHTML = '';
          newOpts.forEach(function (opt) {
            const optionEl = document.createElement('div');
            optionEl.className = 'yx-select__option' + (opt.disabled ? ' yx-select__option--disabled' : '');
            optionEl.setAttribute('data-value', opt.value);
            optionEl.textContent = opt.label;
            optionsEl.appendChild(optionEl);
          });
          updateDisplay();
        },
        setDisabled: function (disabled) {
          options.disabled = disabled;
          container.classList.toggle('yx-select--disabled', disabled);
          container.tabIndex = disabled ? -1 : 0;
        }
      };

      return container;
    },

    getValue(el) {
      return el && el._select ? el._select.getValue() : null;
    },

    setValue(el, value) {
      if (el && el._select) el._select.setValue(value);
    },

    setOptions(el, options) {
      if (el && el._select) el._select.setOptions(options);
    },

    setDisabled(el, disabled) {
      if (el && el._select) el._select.setDisabled(disabled);
    }
  };

  global.YunXiUI = global.YunXiUI || {};
  global.YunXiUI.Select = Select;

})(typeof window !== 'undefined' ? window : this);
