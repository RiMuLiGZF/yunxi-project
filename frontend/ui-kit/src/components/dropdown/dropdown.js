/**
 * YunXi UI Kit - Dropdown Component
 * 云汐组件库 - 下拉菜单组件
 */

(function (global) {
  'use strict';

  const CHEVRON_DOWN = '<polyline points="6 9 12 15 18 9"></polyline>';

  const Dropdown = {
    /**
     * Create a dropdown component
     * @param {Object} options
     * @param {string|HTMLElement} options.trigger - Trigger element or text
     * @param {Array} options.items - Menu items [{key, label, icon, disabled, danger, divider, onClick}]
     * @param {string} [options.placement='bottom-left'] - bottom-left | bottom-right | top-left | top-right
     * @param {string} [options.triggerType='click'] - click | hover
     * @param {Function} [options.onSelect] - (key, item) => void
     * @param {string} [options.className]
     * @returns {HTMLElement}
     */
    create(options) {
      options = options || {};
      const items = options.items || [];

      const container = document.createElement('div');
      let classes = ['yx-dropdown'];

      const placement = options.placement || 'bottom-left';
      if (placement === 'bottom-right') classes.push('yx-dropdown--right');
      if (placement === 'top-left') classes.push('yx-dropdown--top');
      if (placement === 'top-right') classes.push('yx-dropdown--top-right');

      if (options.className) classes.push(options.className);
      container.className = classes.join(' ');

      // Trigger
      const trigger = document.createElement('div');
      trigger.className = 'yx-dropdown__trigger';

      if (typeof options.trigger === 'string') {
        const btn = document.createElement('button');
        btn.className = 'yx-btn yx-btn--secondary';
        btn.innerHTML = options.trigger +
          '<span class="yx-dropdown__trigger-arrow"><svg viewBox="0 0 24 24">' + CHEVRON_DOWN + '</svg></span>';
        trigger.appendChild(btn);
      } else if (options.trigger instanceof HTMLElement) {
        trigger.appendChild(options.trigger);
      }

      container.appendChild(trigger);

      // Menu
      const menu = document.createElement('div');
      menu.className = 'yx-dropdown__menu';
      menu.setAttribute('role', 'menu');

      items.forEach(function (item) {
        if (item.divider) {
          const divider = document.createElement('div');
          divider.className = 'yx-dropdown__divider';
          menu.appendChild(divider);
          return;
        }

        if (item.group) {
          const groupTitle = document.createElement('div');
          groupTitle.className = 'yx-dropdown__group-title';
          groupTitle.textContent = item.group;
          menu.appendChild(groupTitle);
          return;
        }

        const menuItem = document.createElement('div');
        let itemClasses = ['yx-dropdown__item'];
        if (item.disabled) itemClasses.push('yx-dropdown__item--disabled');
        if (item.danger) itemClasses.push('yx-dropdown__item--danger');
        if (item.active) itemClasses.push('yx-dropdown__item--active');
        menuItem.className = itemClasses.join(' ');
        menuItem.setAttribute('role', 'menuitem');
        menuItem.setAttribute('data-key', item.key || '');

        if (item.icon) {
          const icon = document.createElement('span');
          icon.className = 'yx-dropdown__item-icon';
          icon.innerHTML = item.icon;
          menuItem.appendChild(icon);
        }

        const label = document.createElement('span');
        label.style.flex = '1';
        label.textContent = item.label || '';
        menuItem.appendChild(label);

        if (!item.disabled && !item.divider) {
          menuItem.addEventListener('click', function (e) {
            e.stopPropagation();
            if (typeof item.onClick === 'function') {
              item.onClick(item);
            }
            if (typeof options.onSelect === 'function') {
              options.onSelect(item.key, item);
            }
            close();
          });
        }

        menu.appendChild(menuItem);
      });

      container.appendChild(menu);

      function open() {
        container.classList.add('yx-dropdown--open');
        document.addEventListener('click', onOutsideClick);
      }

      function close() {
        container.classList.remove('yx-dropdown--open');
        document.removeEventListener('click', onOutsideClick);
      }

      function toggle() {
        if (container.classList.contains('yx-dropdown--open')) {
          close();
        } else {
          open();
        }
      }

      function onOutsideClick(e) {
        if (!container.contains(e.target)) {
          close();
        }
      }

      // Trigger event
      const triggerType = options.triggerType || 'click';
      if (triggerType === 'hover') {
        container.addEventListener('mouseenter', open);
        container.addEventListener('mouseleave', close);
      } else {
        trigger.addEventListener('click', function (e) {
          e.stopPropagation();
          toggle();
        });
      }

      // API
      container._dropdown = {
        open: open,
        close: close,
        toggle: toggle,
        setItems: function (newItems) {
          // Re-render menu items
        }
      };

      return container;
    },

    open(el) {
      if (el && el._dropdown) el._dropdown.open();
    },

    close(el) {
      if (el && el._dropdown) el._dropdown.close();
    },

    toggle(el) {
      if (el && el._dropdown) el._dropdown.toggle();
    }
  };

  global.YunXiUI = global.YunXiUI || {};
  global.YunXiUI.Dropdown = Dropdown;

})(typeof window !== 'undefined' ? window : this);
