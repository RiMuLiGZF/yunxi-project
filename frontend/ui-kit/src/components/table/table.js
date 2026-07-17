/**
 * YunXi UI Kit - Table Component
 * 云汐组件库 - 表格组件
 */

(function (global) {
  'use strict';

  const Table = {
    /**
     * Create a table component
     * @param {Object} options
     * @param {Array} options.columns - [{key, title, width, align, sortable, render}]
     * @param {Array} [options.data] - Table data rows
     * @param {boolean} [options.striped=false] - Zebra stripe rows
     * @param {boolean} [options.bordered=false]
     * @param {boolean} [options.hoverable=true]
     * @param {boolean} [options.loading=false]
     * @param {string} [options.size='md'] - sm | md | lg
     * @param {string} [options.emptyText='暂无数据']
     * @param {boolean} [options.rowSelection=false]
     * @param {Function} [options.onRowClick]
     * @param {Function} [options.onSort]
     * @param {Function} [options.onSelectionChange]
     * @returns {HTMLElement}
     */
    create(options) {
      options = options || {};
      const columns = options.columns || [];
      let data = (options.data || []).slice();
      let selectedKeys = [];
      let sortKey = null;
      let sortOrder = null; // 'asc' | 'desc'

      const container = document.createElement('div');
      let classes = ['yx-table'];
      if (options.striped) classes.push('yx-table--striped');
      if (options.bordered) classes.push('yx-table--bordered');
      if (options.size && options.size !== 'md') classes.push('yx-table--' + options.size);
      if (options.loading) classes.push('yx-table--loading');
      container.className = classes.join(' ');

      const wrapper = document.createElement('div');
      wrapper.className = 'yx-table-wrapper';
      container.appendChild(wrapper);

      const table = document.createElement('table');
      table.className = '';
      wrapper.appendChild(table);

      // Header
      const thead = document.createElement('thead');
      const headerRow = document.createElement('tr');

      if (options.rowSelection) {
        const th = document.createElement('th');
        th.className = 'yx-table__checkbox-cell';
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.className = 'yx-table__select-all';
        th.appendChild(checkbox);
        headerRow.appendChild(th);

        checkbox.addEventListener('change', function () {
          if (checkbox.checked) {
            selectedKeys = data.map(function (row) { return row.key !== undefined ? row.key : data.indexOf(row); });
          } else {
            selectedKeys = [];
          }
          updateRowSelection();
          if (typeof options.onSelectionChange === 'function') {
            options.onSelectionChange(selectedKeys.slice(), data.filter(function (row, i) {
              return selectedKeys.indexOf(row.key !== undefined ? row.key : i) > -1;
            }));
          }
        });
      }

      columns.forEach(function (col) {
        const th = document.createElement('th');
        th.setAttribute('data-key', col.key);
        if (col.sortable) th.classList.add('yx-table__sortable');
        if (col.align) th.style.textAlign = col.align;
        if (col.width) th.style.width = col.width;

        const label = document.createElement('span');
        label.textContent = col.title;
        th.appendChild(label);

        if (col.sortable) {
          const sortIcon = document.createElement('span');
          sortIcon.className = 'yx-table__sort-icon';
          sortIcon.innerHTML = '<span class="yx-table__sort-up">▲</span><span class="yx-table__sort-down">▼</span>';
          th.appendChild(sortIcon);

          th.addEventListener('click', function () {
            if (sortKey === col.key) {
              sortOrder = sortOrder === 'asc' ? 'desc' : (sortOrder === 'desc' ? null : 'asc');
              if (!sortOrder) sortKey = null;
            } else {
              sortKey = col.key;
              sortOrder = 'asc';
            }
            updateSortIcons();
            if (sortKey && sortOrder) {
              data.sort(function (a, b) {
                const va = a[sortKey];
                const vb = b[sortKey];
                if (va < vb) return sortOrder === 'asc' ? -1 : 1;
                if (va > vb) return sortOrder === 'asc' ? 1 : -1;
                return 0;
              });
            }
            renderBody();
            if (typeof options.onSort === 'function') {
              options.onSort(sortKey, sortOrder);
            }
          });
        }

        headerRow.appendChild(th);
      });

      thead.appendChild(headerRow);
      table.appendChild(thead);

      // Body
      const tbody = document.createElement('tbody');
      table.appendChild(tbody);

      function updateSortIcons() {
        const ths = thead.querySelectorAll('th');
        ths.forEach(function (th) {
          const icon = th.querySelector('.yx-table__sort-icon');
          if (!icon) return;
          icon.classList.remove('yx-table__sort-icon--asc', 'yx-table__sort-icon--desc');
          const key = th.getAttribute('data-key');
          if (key === sortKey && sortOrder) {
            icon.classList.add('yx-table__sort-icon--' + sortOrder);
          }
        });
      }

      function renderBody() {
        tbody.innerHTML = '';

        if (data.length === 0) {
          const tr = document.createElement('tr');
          const td = document.createElement('td');
          td.colSpan = columns.length + (options.rowSelection ? 1 : 0);
          td.className = 'yx-table__empty';
          td.innerHTML = '<div class="yx-table__empty-icon">📋</div>' + (options.emptyText || '暂无数据');
          tr.appendChild(td);
          tbody.appendChild(tr);
          return;
        }

        data.forEach(function (row, rowIndex) {
          const tr = document.createElement('tr');
          const rowKey = row.key !== undefined ? row.key : rowIndex;
          tr.setAttribute('data-key', rowKey);

          if (selectedKeys.indexOf(rowKey) > -1) {
            tr.classList.add('yx-table__row--selected');
          }

          if (options.rowSelection) {
            const td = document.createElement('td');
            td.className = 'yx-table__checkbox-cell';
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.checked = selectedKeys.indexOf(rowKey) > -1;
            checkbox.addEventListener('click', function (e) {
              e.stopPropagation();
            });
            checkbox.addEventListener('change', function () {
              const idx = selectedKeys.indexOf(rowKey);
              if (checkbox.checked) {
                if (idx === -1) selectedKeys.push(rowKey);
              } else {
                if (idx > -1) selectedKeys.splice(idx, 1);
              }
              tr.classList.toggle('yx-table__row--selected', checkbox.checked);
              updateSelectAllState();
              if (typeof options.onSelectionChange === 'function') {
                options.onSelectionChange(selectedKeys.slice(), data.filter(function (r, i) {
                  return selectedKeys.indexOf(r.key !== undefined ? r.key : i) > -1;
                }));
              }
            });
            td.appendChild(checkbox);
            tr.appendChild(td);
          }

          columns.forEach(function (col) {
            const td = document.createElement('td');
            if (col.align) td.style.textAlign = col.align;

            let cellContent = row[col.key];
            if (col.render && typeof col.render === 'function') {
              const result = col.render(row[col.key], row, rowIndex);
              if (typeof result === 'string') {
                td.innerHTML = result;
              } else if (result instanceof HTMLElement) {
                td.appendChild(result);
              } else {
                td.textContent = result !== undefined ? result : '';
              }
            } else {
              td.textContent = cellContent !== undefined && cellContent !== null ? String(cellContent) : '';
            }

            tr.appendChild(td);
          });

          if (typeof options.onRowClick === 'function') {
            tr.style.cursor = 'pointer';
            tr.addEventListener('click', function () {
              options.onRowClick(row, rowIndex);
            });
          }

          tbody.appendChild(tr);
        });
      }

      function updateRowSelection() {
        const rows = tbody.querySelectorAll('tbody tr');
        rows.forEach(function (tr) {
          const key = tr.getAttribute('data-key');
          const isSelected = selectedKeys.indexOf(key) > -1;
          tr.classList.toggle('yx-table__row--selected', isSelected);
          const cb = tr.querySelector('input[type="checkbox"]');
          if (cb) cb.checked = isSelected;
        });
        updateSelectAllState();
      }

      function updateSelectAllState() {
        const selectAll = container.querySelector('.yx-table__select-all');
        if (!selectAll) return;
        const total = data.length;
        const selected = selectedKeys.length;
        selectAll.checked = selected === total && total > 0;
        selectAll.indeterminate = selected > 0 && selected < total;
      }

      // Loading overlay
      if (options.loading) {
        const loadingOverlay = document.createElement('div');
        loadingOverlay.className = 'yx-table__loading-overlay';
        loadingOverlay.innerHTML = '<div class="yx-loading yx-loading--spinner"><span class="yx-loading__spinner"></span></div>';
        container.appendChild(loadingOverlay);
      }

      renderBody();

      // API
      container._table = {
        setData: function (newData) {
          data = (newData || []).slice();
          renderBody();
        },
        getData: function () { return data.slice(); },
        getSelected: function () { return selectedKeys.slice(); },
        setLoading: function (loading) {
          container.classList.toggle('yx-table--loading', loading);
          let overlay = container.querySelector('.yx-table__loading-overlay');
          if (loading && !overlay) {
            overlay = document.createElement('div');
            overlay.className = 'yx-table__loading-overlay';
            overlay.innerHTML = '<div class="yx-loading yx-loading--spinner"><span class="yx-loading__spinner"></span></div>';
            container.appendChild(overlay);
          } else if (!loading && overlay) {
            overlay.remove();
          }
        },
        clearSelection: function () {
          selectedKeys = [];
          updateRowSelection();
        }
      };

      return container;
    },

    setData(el, data) {
      if (el && el._table) el._table.setData(data);
    },

    getSelected(el) {
      return el && el._table ? el._table.getSelected() : [];
    },

    setLoading(el, loading) {
      if (el && el._table) el._table.setLoading(loading);
    }
  };

  global.YunXiUI = global.YunXiUI || {};
  global.YunXiUI.Table = Table;

})(typeof window !== 'undefined' ? window : this);
