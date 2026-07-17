/**
 * YunXi UI Kit - Modal Component
 * 云汐组件库 - 弹窗组件
 */

(function (global) {
  'use strict';

  const CLOSE_ICON = '<line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line>';
  const INFO_ICON = '<circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line>';
  const SUCCESS_ICON = '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline>';
  const WARNING_ICON = '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line>';
  const ERROR_ICON = '<circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line>';

  const modalStack = [];

  const Modal = {
    /**
     * Create a modal instance
     * @param {Object} options
     * @param {string} [options.title]
     * @param {string|HTMLElement} [options.content]
     * @param {Array|HTMLElement} [options.footer] - Footer buttons
     * @param {string} [options.size='md'] - sm | md | lg | xl | full
     * @param {boolean} [options.closable=true]
     * @param {boolean} [options.maskClosable=true]
     * @param {boolean} [options.showFooter=true]
     * @param {Function} [options.onOk]
     * @param {Function} [options.onCancel]
     * @param {string} [options.okText='确定']
     * @param {string} [options.cancelText='取消']
     * @param {string} [options.className]
     * @returns {Object} modal instance with open/close/destroy methods
     */
    create(options) {
      options = options || {};

      const overlay = document.createElement('div');
      let overlayClasses = ['yx-modal-overlay'];
      if (options.placement === 'top') overlayClasses.push('yx-modal-overlay--top');
      overlay.className = overlayClasses.join(' ');
      overlay.setAttribute('role', 'dialog');
      overlay.setAttribute('aria-modal', 'true');

      const modal = document.createElement('div');
      let modalClasses = ['yx-modal'];
      if (options.size && options.size !== 'md') modalClasses.push('yx-modal--' + options.size);
      if (options.className) modalClasses.push(options.className);
      modal.className = modalClasses.join(' ');

      // Header
      const header = document.createElement('div');
      header.className = 'yx-modal__header';

      const title = document.createElement('h3');
      title.className = 'yx-modal__title';
      title.textContent = options.title || '';
      header.appendChild(title);

      if (options.closable !== false) {
        const closeBtn = document.createElement('button');
        closeBtn.className = 'yx-modal__close';
        closeBtn.setAttribute('aria-label', '关闭');
        closeBtn.innerHTML = '<svg viewBox="0 0 24 24">' + CLOSE_ICON + '</svg>';
        closeBtn.addEventListener('click', function () {
          instance.close();
        });
        header.appendChild(closeBtn);
      }

      modal.appendChild(header);

      // Body
      const body = document.createElement('div');
      body.className = 'yx-modal__body';
      if (typeof options.content === 'string') {
        body.innerHTML = options.content;
      } else if (options.content instanceof HTMLElement) {
        body.appendChild(options.content);
      }
      modal.appendChild(body);

      // Footer
      if (options.showFooter !== false) {
        const footer = document.createElement('div');
        footer.className = 'yx-modal__footer';

        if (options.footer) {
          if (typeof options.footer === 'string') {
            footer.innerHTML = options.footer;
          } else if (Array.isArray(options.footer)) {
            options.footer.forEach(function (btn) {
              footer.appendChild(btn);
            });
          } else if (options.footer instanceof HTMLElement) {
            footer.appendChild(options.footer);
          }
        } else {
          // Default buttons
          const cancelBtn = document.createElement('button');
          cancelBtn.className = 'yx-btn yx-btn--secondary';
          cancelBtn.textContent = options.cancelText || '取消';
          cancelBtn.addEventListener('click', function () {
            if (typeof options.onCancel === 'function') {
              const result = options.onCancel();
              if (result !== false) instance.close();
            } else {
              instance.close();
            }
          });
          footer.appendChild(cancelBtn);

          const okBtn = document.createElement('button');
          okBtn.className = 'yx-btn yx-btn--primary';
          okBtn.textContent = options.okText || '确定';
          okBtn.addEventListener('click', function () {
            if (typeof options.onOk === 'function') {
              const result = options.onOk();
              if (result && typeof result.then === 'function') {
                okBtn.disabled = true;
                okBtn.classList.add('yx-btn--loading');
                const spinner = document.createElement('span');
                spinner.className = 'yx-btn__spinner';
                okBtn.appendChild(spinner);
                result.then(function (res) {
                  if (res !== false) instance.close();
                }).catch(function () {
                  okBtn.disabled = false;
                  okBtn.classList.remove('yx-btn--loading');
                  const s = okBtn.querySelector('.yx-btn__spinner');
                  if (s) s.remove();
                });
              } else if (result !== false) {
                instance.close();
              }
            } else {
              instance.close();
            }
          });
          footer.appendChild(okBtn);
        }

        modal.appendChild(footer);
      }

      overlay.appendChild(modal);

      // Mask click to close
      if (options.maskClosable !== false) {
        overlay.addEventListener('click', function (e) {
          if (e.target === overlay) {
            instance.close();
          }
        });
      }

      // ESC key to close
      function onKeyDown(e) {
        if (e.key === 'Escape' && modalStack[modalStack.length - 1] === instance) {
          instance.close();
        }
      }

      const instance = {
        element: overlay,
        modal: modal,
        body: body,
        header: header,
        isOpen: false,

        open: function () {
          if (this.isOpen) return;
          document.body.appendChild(overlay);
          document.body.classList.add('yx-modal-open');
          modalStack.push(this);
          requestAnimationFrame(function () {
            overlay.classList.add('yx-modal-overlay--open');
          });
          this.isOpen = true;
          document.addEventListener('keydown', onKeyDown);
        },

        close: function () {
          if (!this.isOpen) return;
          overlay.classList.remove('yx-modal-overlay--open');
          this.isOpen = false;
          document.removeEventListener('keydown', onKeyDown);

          var self = this;
          setTimeout(function () {
            if (overlay.parentNode) {
              overlay.parentNode.removeChild(overlay);
            }
            var idx = modalStack.indexOf(self);
            if (idx > -1) modalStack.splice(idx, 1);
            if (modalStack.length === 0) {
              document.body.classList.remove('yx-modal-open');
            }
          }, 250);
        },

        setTitle: function (text) {
          title.textContent = text;
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
          }, 300);
        }
      };

      return instance;
    },

    /**
     * Show a confirm dialog
     * @param {Object} options
     * @param {string} options.title
     * @param {string} [options.content]
     * @param {string} [options.type='info'] - info | success | warning | error
     * @param {Function} [options.onOk]
     * @param {Function} [options.onCancel]
     * @returns {Object} modal instance
     */
    confirm(options) {
      options = options || {};
      const iconMap = {
        info: INFO_ICON,
        success: SUCCESS_ICON,
        warning: WARNING_ICON,
        error: ERROR_ICON
      };

      const content = document.createElement('div');
      content.className = 'yx-modal__confirm-content';

      const iconWrap = document.createElement('div');
      iconWrap.className = 'yx-modal__icon yx-modal__icon--' + (options.type || 'info');
      iconWrap.innerHTML = '<svg viewBox="0 0 24 24">' + (iconMap[options.type] || INFO_ICON) + '</svg>';
      content.appendChild(iconWrap);

      const textWrap = document.createElement('div');
      textWrap.style.flex = '1';

      const titleEl = document.createElement('div');
      titleEl.className = 'yx-modal__confirm-title';
      titleEl.textContent = options.title || '';
      textWrap.appendChild(titleEl);

      if (options.content) {
        const textEl = document.createElement('div');
        textEl.className = 'yx-modal__confirm-text';
        textEl.textContent = options.content;
        textWrap.appendChild(textEl);
      }

      content.appendChild(textWrap);

      const modal = this.create({
        content: content,
        showFooter: true,
        closable: true,
        onOk: options.onOk,
        onCancel: options.onCancel,
        okText: options.okText,
        cancelText: options.cancelText,
        className: 'yx-modal--confirm'
      });

      // Remove default header title for confirm dialog
      const header = modal.element.querySelector('.yx-modal__header');
      if (header) header.style.display = 'none';

      modal.open();
      return modal;
    },

    /**
     * Show an info dialog
     */
    info(options) {
      options = options || {};
      options.type = 'info';
      return this.confirm(options);
    },

    /**
     * Show a success dialog
     */
    success(options) {
      options = options || {};
      options.type = 'success';
      return this.confirm(options);
    },

    /**
     * Show a warning dialog
     */
    warning(options) {
      options = options || {};
      options.type = 'warning';
      return this.confirm(options);
    },

    /**
     * Show an error dialog
     */
    error(options) {
      options = options || {};
      options.type = 'error';
      return this.confirm(options);
    }
  };

  global.YunXiUI = global.YunXiUI || {};
  global.YunXiUI.Modal = Modal;

})(typeof window !== 'undefined' ? window : this);
