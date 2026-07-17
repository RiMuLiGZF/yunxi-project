/**
 * YunXi UI Kit - Steps Component
 * 云汐组件库 - 步骤条组件
 */

(function (global) {
  'use strict';

  const CHECK_ICON = '<polyline points="20 6 9 17 4 12"></polyline>';
  const ERROR_ICON = '<line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line>';

  const Steps = {
    /**
     * Create a steps component
     * @param {Object} options
     * @param {Array} options.steps - [{title, description, icon, status}]
     * @param {number} [options.current=0] - Current step index
     * @param {string} [options.direction='horizontal'] - horizontal | vertical
     * @param {string} [options.size='md'] - sm | md | lg
     * @param {string} [options.status='process'] - Current step status: process | error
     * @param {boolean} [options.dots=false] - Dot style
     * @returns {HTMLElement}
     */
    create(options) {
      options = options || {};
      const steps = options.steps || [];
      const current = options.current !== undefined ? options.current : 0;

      const container = document.createElement('div');
      let classes = ['yx-steps'];
      if (options.direction === 'vertical') classes.push('yx-steps--vertical');
      else classes.push('yx-steps--horizontal');
      if (options.size && options.size !== 'md') classes.push('yx-steps--' + options.size);
      if (options.dots) classes.push('yx-steps--dots');
      container.className = classes.join(' ');

      steps.forEach(function (step, index) {
        const item = document.createElement('div');
        let status = step.status;
        if (!status) {
          if (index < current) status = 'finish';
          else if (index === current) status = options.status || 'process';
          else status = 'wait';
        }
        item.className = 'yx-steps__item yx-steps__item--' + status;

        const content = document.createElement('div');
        content.className = 'yx-steps__item-content';

        // Icon
        const icon = document.createElement('div');
        icon.className = 'yx-steps__icon';

        if (status === 'finish') {
          icon.innerHTML = '<svg viewBox="0 0 24 24">' + (step.icon || CHECK_ICON) + '</svg>';
        } else if (status === 'error') {
          icon.innerHTML = '<svg viewBox="0 0 24 24">' + (step.icon || ERROR_ICON) + '</svg>';
        } else if (step.icon && status !== 'wait') {
          icon.innerHTML = '<svg viewBox="0 0 24 24">' + step.icon + '</svg>';
        } else {
          icon.textContent = String(index + 1);
        }

        content.appendChild(icon);

        // Text wrapper for vertical mode
        const textWrap = document.createElement('div');
        textWrap.className = 'yx-steps__item-text';

        if (step.title) {
          const title = document.createElement('div');
          title.className = 'yx-steps__title';
          title.textContent = step.title;
          textWrap.appendChild(title);
        }

        if (step.description) {
          const desc = document.createElement('div');
          desc.className = 'yx-steps__description';
          desc.textContent = step.description;
          textWrap.appendChild(desc);
        }

        content.appendChild(textWrap);

        // Line
        const line = document.createElement('div');
        line.className = 'yx-steps__line';
        item.appendChild(line);

        item.appendChild(content);
        container.appendChild(item);
      });

      container._steps = {
        setCurrent: function (index, status) {
          const items = container.querySelectorAll('.yx-steps__item');
          items.forEach(function (item, i) {
            item.classList.remove('yx-steps__item--wait', 'yx-steps__item--process', 'yx-steps__item--finish', 'yx-steps__item--error');
            let s;
            if (i < index) s = 'finish';
            else if (i === index) s = status || 'process';
            else s = 'wait';
            item.classList.add('yx-steps__item--' + s);
          });
        }
      };

      return container;
    },

    setCurrent(el, index, status) {
      if (el && el._steps) el._steps.setCurrent(index, status);
    }
  };

  global.YunXiUI = global.YunXiUI || {};
  global.YunXiUI.Steps = Steps;

})(typeof window !== 'undefined' ? window : this);
