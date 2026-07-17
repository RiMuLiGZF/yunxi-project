/**
 * YunXi UI Kit - Tabs Component
 * 云汐组件库 - 标签页组件
 */

(function (global) {
  'use strict';

  const Tabs = {
    /**
     * Create a tabs component
     * @param {Object} options
     * @param {Array} options.items - [{key, label, content, disabled, icon}]
     * @param {string} [options.activeKey] - Initially active tab key
     * @param {string} [options.type='line'] - line | card | segment
     * @param {string} [options.placement='top'] - top | left (vertical)
     * @param {string} [options.size='md'] - sm | md | lg
     * @param {Function} [options.onChange] - (key) => void
     * @returns {HTMLElement}
     */
    create(options) {
      options = options || {};
      const items = options.items || [];
      let activeKey = options.activeKey || (items.length > 0 ? items[0].key : null);

      const container = document.createElement('div');
      let classes = ['yx-tabs'];
      if (options.type && options.type !== 'line') classes.push('yx-tabs--' + options.type);
      if (options.placement === 'left') classes.push('yx-tabs--vertical');
      if (options.size && options.size !== 'md') classes.push('yx-tabs--' + options.size);
      container.className = classes.join(' ');

      // Nav
      const nav = document.createElement('div');
      nav.className = 'yx-tabs__nav';

      const navList = document.createElement('div');
      navList.className = 'yx-tabs__nav-list';

      const indicator = document.createElement('div');
      indicator.className = 'yx-tabs__indicator';
      navList.appendChild(indicator);

      const tabElements = [];

      items.forEach(function (item, index) {
        const tab = document.createElement('button');
        tab.className = 'yx-tabs__tab';
        tab.setAttribute('data-key', item.key);
        tab.type = 'button';

        if (item.disabled) tab.classList.add('yx-tabs__tab--disabled');
        if (item.key === activeKey) tab.classList.add('yx-tabs__tab--active');

        if (item.icon) {
          const icon = document.createElement('span');
          icon.className = 'yx-tabs__tab-icon';
          icon.innerHTML = item.icon;
          tab.appendChild(icon);
        }

        const label = document.createElement('span');
        label.textContent = item.label;
        tab.appendChild(label);

        if (!item.disabled) {
          tab.addEventListener('click', function () {
            if (activeKey === item.key) return;
            setActive(item.key);
          });
        }

        tabElements.push(tab);
        navList.appendChild(tab);
      });

      nav.appendChild(navList);
      container.appendChild(nav);

      // Content
      const content = document.createElement('div');
      content.className = 'yx-tabs__content';

      const paneElements = [];
      items.forEach(function (item) {
        const pane = document.createElement('div');
        pane.className = 'yx-tab-pane';
        pane.setAttribute('data-key', item.key);
        if (item.key === activeKey) pane.classList.add('yx-tab-pane--active');

        if (typeof item.content === 'string') {
          pane.innerHTML = item.content;
        } else if (item.content instanceof HTMLElement) {
          pane.appendChild(item.content);
        }

        paneElements.push(pane);
        content.appendChild(pane);
      });

      container.appendChild(content);

      // Update indicator position
      function updateIndicator() {
        const activeTab = navList.querySelector('.yx-tabs__tab--active');
        if (!activeTab) return;

        const isVertical = container.classList.contains('yx-tabs--vertical');
        const rect = activeTab.getBoundingClientRect();
        const navRect = navList.getBoundingClientRect();

        if (isVertical) {
          indicator.style.top = (rect.top - navRect.top) + 'px';
          indicator.style.height = rect.height + 'px';
          indicator.style.left = 'auto';
          indicator.style.width = '2px';
        } else {
          indicator.style.left = (activeTab.offsetLeft) + 'px';
          indicator.style.width = rect.width + 'px';
          indicator.style.top = 'auto';
          indicator.style.height = '2px';
        }
      }

      function setActive(key) {
        activeKey = key;

        tabElements.forEach(function (tab) {
          tab.classList.toggle('yx-tabs__tab--active', tab.getAttribute('data-key') === key);
        });

        paneElements.forEach(function (pane) {
          pane.classList.toggle('yx-tab-pane--active', pane.getAttribute('data-key') === key);
        });

        updateIndicator();

        if (typeof options.onChange === 'function') {
          options.onChange(key);
        }
      }

      // Initialize indicator after mount
      requestAnimationFrame(updateIndicator);
      window.addEventListener('resize', updateIndicator);

      // API
      container._tabs = {
        getActiveKey: function () { return activeKey; },
        setActiveKey: setActive,
        update: updateIndicator,
        addTab: function (item) {
          // Implementation for dynamic add
        },
        removeTab: function (key) {
          // Implementation for dynamic remove
        }
      };

      return container;
    },

    getActiveKey(el) {
      return el && el._tabs ? el._tabs.getActiveKey() : null;
    },

    setActiveKey(el, key) {
      if (el && el._tabs) el._tabs.setActiveKey(key);
    }
  };

  global.YunXiUI = global.YunXiUI || {};
  global.YunXiUI.Tabs = Tabs;

})(typeof window !== 'undefined' ? window : this);
