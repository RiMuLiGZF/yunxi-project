/**
 * YunXi UI Kit - Pagination Component
 * 云汐组件库 - 分页组件
 */

(function (global) {
  'use strict';

  const CHEVRON_LEFT = '<polyline points="15 18 9 12 15 6"></polyline>';
  const CHEVRON_RIGHT = '<polyline points="9 18 15 12 9 6"></polyline>';

  const Pagination = {
    /**
     * Create a pagination component
     * @param {Object} options
     * @param {number} options.total - Total items
     * @param {number} [options.current=1] - Current page
     * @param {number} [options.pageSize=10] - Items per page
     * @param {Array} [options.pageSizeOptions] - [10, 20, 50, 100]
     * @param {boolean} [options.showTotal=true]
     * @param {boolean} [options.showJumper=false]
     * @param {boolean} [options.showSizeChanger=false]
     * @param {string} [options.size='md'] - sm | md | lg
     * @param {boolean} [options.simple=false]
     * @param {Function} [options.onChange] - (page, pageSize) => void
     * @param {Function} [options.onShowSizeChange] - (current, size) => void
     * @returns {HTMLElement}
     */
    create(options) {
      options = options || {};
      let current = options.current || 1;
      let pageSize = options.pageSize || 10;
      const total = options.total || 0;
      const totalPages = Math.max(1, Math.ceil(total / pageSize));

      const container = document.createElement('div');
      let classes = ['yx-pagination'];
      if (options.size && options.size !== 'md') classes.push('yx-pagination--' + options.size);
      if (options.simple) classes.push('yx-pagination--simple');
      container.className = classes.join(' ');

      function render() {
        container.innerHTML = '';

        // Total
        if (options.showTotal !== false) {
          const totalEl = document.createElement('span');
          totalEl.className = 'yx-pagination__total';
          totalEl.textContent = '共 ' + total + ' 条';
          container.appendChild(totalEl);
        }

        // Page size selector
        if (options.showSizeChanger && options.pageSizeOptions) {
          const sizer = document.createElement('span');
          sizer.className = 'yx-pagination__sizer';
          const select = document.createElement('select');
          options.pageSizeOptions.forEach(function (size) {
            const opt = document.createElement('option');
            opt.value = size;
            opt.textContent = size + ' 条/页';
            if (size === pageSize) opt.selected = true;
            select.appendChild(opt);
          });
          select.addEventListener('change', function (e) {
            pageSize = parseInt(e.target.value, 10);
            current = 1;
            render();
            if (typeof options.onShowSizeChange === 'function') {
              options.onShowSizeChange(current, pageSize);
            }
            if (typeof options.onChange === 'function') {
              options.onChange(current, pageSize);
            }
          });
          sizer.appendChild(select);
          container.appendChild(sizer);
        }

        // Prev button
        const prev = createItem('prev', current <= 1, function () {
          if (current > 1) goTo(current - 1);
        });
        container.appendChild(prev);

        if (options.simple) {
          const simpleText = document.createElement('span');
          simpleText.className = 'yx-pagination__simple-text';
          simpleText.textContent = current + ' / ' + totalPages;
          container.appendChild(simpleText);
        } else {
          // Page numbers
          const pages = getPageList(current, totalPages);
          pages.forEach(function (p) {
            if (p === '...') {
              const dots = document.createElement('span');
              dots.className = 'yx-pagination__item yx-pagination__item--dots';
              dots.textContent = '...';
              container.appendChild(dots);
            } else {
              const page = createItem(p, false, function () {
                goTo(p);
              }, p === current);
              container.appendChild(page);
            }
          });
        }

        // Next button
        const next = createItem('next', current >= totalPages, function () {
          if (current < totalPages) goTo(current + 1);
        });
        container.appendChild(next);

        // Jumper
        if (options.showJumper) {
          const jumper = document.createElement('span');
          jumper.className = 'yx-pagination__jumper';
          jumper.innerHTML = '跳至';
          const input = document.createElement('input');
          input.type = 'number';
          input.min = 1;
          input.max = totalPages;
          input.value = current;
          input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
              let val = parseInt(input.value, 10);
              if (val >= 1 && val <= totalPages) {
                goTo(val);
              }
            }
          });
          input.addEventListener('blur', function () {
            let val = parseInt(input.value, 10);
            if (val >= 1 && val <= totalPages && val !== current) {
              goTo(val);
            } else {
              input.value = current;
            }
          });
          jumper.appendChild(input);
          jumper.appendChild(document.createTextNode('页'));
          container.appendChild(jumper);
        }
      }

      function createItem(content, disabled, onClick, active) {
        const btn = document.createElement('button');
        let classes = ['yx-pagination__item'];

        if (content === 'prev') {
          classes.push('yx-pagination__prev');
          btn.innerHTML = '<svg viewBox="0 0 24 24">' + CHEVRON_LEFT + '</svg>';
          btn.setAttribute('aria-label', '上一页');
        } else if (content === 'next') {
          classes.push('yx-pagination__next');
          btn.innerHTML = '<svg viewBox="0 0 24 24">' + CHEVRON_RIGHT + '</svg>';
          btn.setAttribute('aria-label', '下一页');
        } else {
          btn.textContent = content;
        }

        if (active) classes.push('yx-pagination__item--active');
        if (disabled) classes.push('yx-pagination__item--disabled');

        btn.className = classes.join(' ');
        btn.disabled = disabled;

        if (onClick && !disabled) {
          btn.addEventListener('click', onClick);
        }

        return btn;
      }

      function getPageList(current, total) {
        const pages = [];
        const delta = 2; // Number of pages to show on each side of current

        if (total <= 7 + delta * 2) {
          for (let i = 1; i <= total; i++) pages.push(i);
          return pages;
        }

        // Always show first page
        pages.push(1);

        // Left dots or pages
        const leftStart = Math.max(2, current - delta);
        const leftEnd = current - 1;

        if (leftStart > 2) {
          pages.push('...');
        }

        for (let i = leftStart; i <= leftEnd; i++) {
          if (i > 1) pages.push(i);
        }

        // Current page
        if (current > 1 && current < total) {
          pages.push(current);
        }

        // Right pages or dots
        const rightStart = current + 1;
        const rightEnd = Math.min(total - 1, current + delta);

        for (let i = rightStart; i <= rightEnd; i++) {
          if (i < total) pages.push(i);
        }

        if (rightEnd < total - 1) {
          pages.push('...');
        }

        // Always show last page
        if (total > 1) pages.push(total);

        return pages;
      }

      function goTo(page) {
        if (page < 1 || page > totalPages || page === current) return;
        current = page;
        render();
        if (typeof options.onChange === 'function') {
          options.onChange(current, pageSize);
        }
      }

      render();

      // API
      container._pagination = {
        getCurrent: function () { return current; },
        getPageSize: function () { return pageSize; },
        setCurrent: function (page) { goTo(page); },
        setTotal: function (newTotal) {
          // Not implemented fully - would need re-render
        }
      };

      return container;
    },

    getCurrent(el) {
      return el && el._pagination ? el._pagination.getCurrent() : 1;
    },

    setCurrent(el, page) {
      if (el && el._pagination) el._pagination.setCurrent(page);
    }
  };

  global.YunXiUI = global.YunXiUI || {};
  global.YunXiUI.Pagination = Pagination;

})(typeof window !== 'undefined' ? window : this);
