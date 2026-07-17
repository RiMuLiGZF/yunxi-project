/**
 * YunXi UI Kit - Timeline Component
 * 云汐组件库 - 时间线组件
 */

(function (global) {
  'use strict';

  const CHECK_ICON = '<polyline points="20 6 9 17 4 12"></polyline>';
  const CLOCK_ICON = '<circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline>';
  const X_ICON = '<line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line>';

  const Timeline = {
    /**
     * Create a timeline component
     * @param {Object} options
     * @param {Array} options.items - [{title, description, time, color, icon, dot, pending}]
     * @param {string} [options.mode='left'] - left | right | alternate
     * @param {string} [options.size='md'] - sm | md | lg
     * @param {boolean} [options.pending=false] - Last item is pending
     * @returns {HTMLElement}
     */
    create(options) {
      options = options || {};
      const items = options.items || [];

      const timeline = document.createElement('ul');
      let classes = ['yx-timeline'];
      if (options.mode === 'right') classes.push('yx-timeline--right');
      if (options.mode === 'alternate') classes.push('yx-timeline--alternate');
      if (options.size && options.size !== 'md') classes.push('yx-timeline--' + options.size);
      timeline.className = classes.join(' ');

      items.forEach(function (item, index) {
        const li = document.createElement('li');
        let itemClasses = ['yx-timeline__item'];
        if (item.pending || (options.pending && index === items.length - 1)) {
          itemClasses.push('yx-timeline__item--pending');
        }
        li.className = itemClasses.join(' ');

        // Dot
        const dot = document.createElement('div');
        let dotClasses = ['yx-timeline__dot'];
        if (item.color) dotClasses.push('yx-timeline__dot--' + item.color);
        if (item.icon) dotClasses.push('yx-timeline__dot--custom');
        dot.className = dotClasses.join(' ');

        let iconContent = '';
        if (item.icon) {
          iconContent = item.icon;
        } else if (item.color === 'success') {
          iconContent = CHECK_ICON;
        } else if (item.color === 'error') {
          iconContent = X_ICON;
        }

        if (iconContent) {
          dot.innerHTML = '<svg viewBox="0 0 24 24">' + iconContent + '</svg>';
        }

        li.appendChild(dot);

        // Content
        const content = document.createElement('div');
        content.className = 'yx-timeline__content';

        if (item.title) {
          const title = document.createElement('div');
          title.className = 'yx-timeline__title';
          title.textContent = item.title;
          content.appendChild(title);
        }

        if (item.description) {
          const desc = document.createElement('div');
          desc.className = 'yx-timeline__description';
          if (typeof item.description === 'string') {
            desc.textContent = item.description;
          } else if (item.description instanceof HTMLElement) {
            desc.appendChild(item.description);
          }
          content.appendChild(desc);
        }

        if (item.time) {
          const time = document.createElement('div');
          time.className = 'yx-timeline__time';
          time.textContent = item.time;
          content.appendChild(time);
        }

        li.appendChild(content);
        timeline.appendChild(li);
      });

      return timeline;
    }
  };

  global.YunXiUI = global.YunXiUI || {};
  global.YunXiUI.Timeline = Timeline;

})(typeof window !== 'undefined' ? window : this);
