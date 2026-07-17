/**
 * YunXi UI Kit - Card Component
 * 云汐组件库 - 卡片组件
 */

(function (global) {
  'use strict';

  const Card = {
    /**
     * Create a card element
     * @param {Object} options
     * @param {string} [options.title] - Card title
     * @param {string} [options.subtitle] - Card subtitle
     * @param {string|HTMLElement} [options.content] - Card body content
     * @param {string} [options.cover] - Cover image URL
     * @param {Array|HTMLElement} [options.actions] - Footer action buttons or HTML
     * @param {Array|HTMLElement} [options.extra] - Header extra content
     * @param {boolean} [options.hoverable=false] - Hover lift effect
     * @param {boolean} [options.borderless=false]
     * @param {boolean} [options.glass=false]
     * @param {boolean} [options.loading=false]
     * @param {string} [options.size='md'] - sm | md | lg
     * @param {string} [options.className]
     * @returns {HTMLDivElement}
     */
    create(options) {
      options = options || {};

      const card = document.createElement('div');
      let classes = ['yx-card'];

      if (options.size && options.size !== 'md') classes.push('yx-card--' + options.size);
      if (options.hoverable) classes.push('yx-card--hoverable');
      if (options.borderless) classes.push('yx-card--borderless');
      if (options.glass) classes.push('yx-card--glass');
      if (options.loading) classes.push('yx-card--loading');
      if (options.className) classes.push(options.className);

      card.className = classes.join(' ');

      // Cover image
      if (options.cover) {
        const cover = document.createElement('img');
        cover.className = 'yx-card__cover';
        cover.src = options.cover;
        cover.alt = options.title || '';
        card.appendChild(cover);
      }

      // Header
      if (options.title || options.extra) {
        const header = document.createElement('div');
        header.className = 'yx-card__header';

        const titleWrap = document.createElement('div');
        titleWrap.style.flex = '1';
        titleWrap.style.minWidth = '0';

        if (options.title) {
          const title = document.createElement('h3');
          title.className = 'yx-card__title';
          title.textContent = options.title;
          titleWrap.appendChild(title);
        }

        if (options.subtitle) {
          const subtitle = document.createElement('p');
          subtitle.className = 'yx-card__subtitle';
          subtitle.textContent = options.subtitle;
          titleWrap.appendChild(subtitle);
        }

        header.appendChild(titleWrap);

        if (options.extra) {
          const extra = document.createElement('div');
          extra.className = 'yx-card__extra';
          if (typeof options.extra === 'string') {
            extra.innerHTML = options.extra;
          } else if (Array.isArray(options.extra)) {
            options.extra.forEach(function (el) {
              extra.appendChild(el);
            });
          } else if (options.extra instanceof HTMLElement) {
            extra.appendChild(options.extra);
          }
          header.appendChild(extra);
        }

        card.appendChild(header);
      }

      // Body
      if (options.content !== undefined) {
        const body = document.createElement('div');
        body.className = 'yx-card__body';
        if (typeof options.content === 'string') {
          body.innerHTML = options.content;
        } else if (options.content instanceof HTMLElement) {
          body.appendChild(options.content);
        }
        card.appendChild(body);
      }

      // Footer actions
      if (options.actions) {
        const footer = document.createElement('div');
        footer.className = 'yx-card__footer';
        if (typeof options.actions === 'string') {
          footer.innerHTML = options.actions;
        } else if (Array.isArray(options.actions)) {
          options.actions.forEach(function (el) {
            footer.appendChild(el);
          });
        } else if (options.actions instanceof HTMLElement) {
          footer.appendChild(options.actions);
        }
        card.appendChild(footer);
      }

      // API
      card._card = {
        setTitle: function (title) {
          const titleEl = card.querySelector('.yx-card__title');
          if (titleEl) titleEl.textContent = title;
        },
        setContent: function (content) {
          let body = card.querySelector('.yx-card__body');
          if (!body) {
            body = document.createElement('div');
            body.className = 'yx-card__body';
            card.appendChild(body);
          }
          if (typeof content === 'string') {
            body.innerHTML = content;
          } else if (content instanceof HTMLElement) {
            body.innerHTML = '';
            body.appendChild(content);
          }
        },
        setLoading: function (loading) {
          card.classList.toggle('yx-card--loading', loading);
        }
      };

      return card;
    },

    /**
     * Create a card grid container
     * @param {Array} cards - Array of card elements or card options
     * @returns {HTMLDivElement}
     */
    createGrid(cards) {
      const grid = document.createElement('div');
      grid.className = 'yx-card-grid';

      cards.forEach(function (card) {
        if (card instanceof HTMLElement) {
          grid.appendChild(card);
        } else {
          grid.appendChild(this.create(card));
        }
      }, this);

      return grid;
    },

    setTitle(el, title) {
      if (el && el._card) el._card.setTitle(title);
    },

    setContent(el, content) {
      if (el && el._card) el._card.setContent(content);
    },

    setLoading(el, loading) {
      if (el && el._card) el._card.setLoading(loading);
    }
  };

  global.YunXiUI = global.YunXiUI || {};
  global.YunXiUI.Card = Card;

})(typeof window !== 'undefined' ? window : this);
