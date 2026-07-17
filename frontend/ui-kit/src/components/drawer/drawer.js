/**
 * YunXi UI Kit - Drawer Component
 * 云汐组件库 - 抽屉组件
 */

(function (global) {
  'use strict';

  const CLOSE_ICON = '<line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line>';

  const drawerStack = [];

  const Drawer = {
    /**
     * Create a drawer instance
     * @param {Object} options
     * @param {string} [options.title]
     * @param {string|HTMLElement} [options.content]
     * @param {string} [options.placement='right'] - left | right | top | bottom
     * @param {string} [options.size='md'] - sm | md | lg | xl
     * @param {boolean} [options.closable=true]
     * @param {boolean} [options.maskClosable=true]
     * @param {boolean} [options.showFooter=false]
     * @param {Array|HTMLElement} [options.footer]
     * @param {Function} [options.onClose]
     * @param {string} [options.className]
     * @returns {Object} drawer instance
     */
    create(options) {
      options = options || {};
      const placement = options.placement || 'right';

      const overlay = document.createElement('div');
      overlay.className = 'yx-drawer-overlay';

      const drawer = document.createElement('div');
      let classes = ['yx-drawer', 'yx-drawer--' + placement];
      if (options.size && options.size !== 'md') classes.push('yx-drawer--' + options.size);
      if (options.className) classes.push(options.className);
      drawer.className = classes.join(' ');

      // Header
      if (options.title || options.closable !== false) {
        const header = document.createElement('div');
        header.className = 'yx-drawer__header';

        const title = document.createElement('h3');
        title.className = 'yx-drawer__title';
        title.textContent = options.title || '';
        header.appendChild(title);

        if (options.closable !== false) {
          const closeBtn = document.createElement('button');
          closeBtn.className = 'yx-drawer__close';
          closeBtn.setAttribute('aria-label', '关闭');
          closeBtn.innerHTML = '<svg viewBox="0 0 24 24">' + CLOSE_ICON + '</svg>';
          closeBtn.addEventListener('click', function () {
            instance.close();
          });
          header.appendChild(closeBtn);
        }

        drawer.appendChild(header);
      }

      // Body
      const body = document.createElement('div');
      body.className = 'yx-drawer__body';
      if (typeof options.content === 'string') {
        body.innerHTML = options.content;
      } else if (options.content instanceof HTMLElement) {
        body.appendChild(options.content);
      }
      drawer.appendChild(body);

      // Footer
      if (options.showFooter || options.footer) {
        const footer = document.createElement('div');
        footer.className = 'yx-drawer__footer';

        if (options.footer) {
          if (typeof options.footer === 'string') {
            footer.innerHTML = options.footer;
          } else if (Array.isArray(options.footer)) {
            options.footer.forEach(function (el) {
              footer.appendChild(el);
            });
          } else if (options.footer instanceof HTMLElement) {
            footer.appendChild(options.footer);
          }
        }

        drawer.appendChild(footer);
      }

      overlay.appendChild(drawer);

      // Mask click
      if (options.maskClosable !== false) {
        overlay.addEventListener('click', function (e) {
          if (e.target === overlay) {
            instance.close();
          }
        });
      }

      // ESC key
      function onKeyDown(e) {
        if (e.key === 'Escape' && drawerStack[drawerStack.length - 1] === instance) {
          instance.close();
        }
      }

      const instance = {
        element: overlay,
        drawer: drawer,
        body: body,
        isOpen: false,

        open: function () {
          if (this.isOpen) return;
          document.body.appendChild(overlay);
          document.body.classList.add('yx-drawer-open');
          drawerStack.push(this);
          requestAnimationFrame(function () {
            overlay.classList.add('yx-drawer-overlay--open');
          });
          this.isOpen = true;
          document.addEventListener('keydown', onKeyDown);
        },

        close: function () {
          if (!this.isOpen) return;
          overlay.classList.remove('yx-drawer-overlay--open');
          this.isOpen = false;
          document.removeEventListener('keydown', onKeyDown);

          if (typeof options.onClose === 'function') {
            options.onClose();
          }

          var self = this;
          setTimeout(function () {
            if (overlay.parentNode) {
              overlay.parentNode.removeChild(overlay);
            }
            var idx = drawerStack.indexOf(self);
            if (idx > -1) drawerStack.splice(idx, 1);
            if (drawerStack.length === 0) {
              document.body.classList.remove('yx-drawer-open');
            }
          }, 400);
        },

        setTitle: function (text) {
          const titleEl = drawer.querySelector('.yx-drawer__title');
          if (titleEl) titleEl.textContent = text;
        },

        setContent: function (content) {
          if (typeof content === 'string') {
            body.innerHTML = content;
          } else if (content instanceof HTMLElement) {
            body.innerHTML = '';
            body.appendChild(content);
          }
        },

        destroy: function () {
          this.close();
          setTimeout(function () {
            if (overlay.parentNode) {
              overlay.parentNode.removeChild(overlay);
            }
          }, 450);
        }
      };

      return instance;
    }
  };

  global.YunXiUI = global.YunXiUI || {};
  global.YunXiUI.Drawer = Drawer;

})(typeof window !== 'undefined' ? window : this);
