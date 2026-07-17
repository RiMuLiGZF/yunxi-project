/**
 * YunXi UI Kit - Utility Functions
 * 云汐组件库 - 工具函数库
 *
 * 包含：DOM操作、事件处理、表单验证、日期格式化、
 *       数字格式化、防抖节流、深拷贝、类型判断
 */

(function (global) {
  'use strict';

  // ============================================================
  // Type Check / 类型判断
  // ============================================================
  const Type = {
    isString: function (v) { return typeof v === 'string'; },
    isNumber: function (v) { return typeof v === 'number' && !isNaN(v); },
    isBoolean: function (v) { return typeof v === 'boolean'; },
    isArray: function (v) { return Array.isArray(v); },
    isObject: function (v) { return v !== null && typeof v === 'object' && !Array.isArray(v); },
    isFunction: function (v) { return typeof v === 'function'; },
    isUndefined: function (v) { return typeof v === 'undefined'; },
    isNull: function (v) { return v === null; },
    isNil: function (v) { return v === null || v === undefined; },
    isEmpty: function (v) {
      if (v === null || v === undefined) return true;
      if (typeof v === 'string') return v.length === 0;
      if (Array.isArray(v)) return v.length === 0;
      if (typeof v === 'object') return Object.keys(v).length === 0;
      return false;
    },
    isDate: function (v) { return v instanceof Date && !isNaN(v.getTime()); },
    isRegExp: function (v) { return v instanceof RegExp; },
    isPromise: function (v) { return v && typeof v.then === 'function'; },
    isElement: function (v) { return v instanceof HTMLElement; },
    typeOf: function (v) {
      return Object.prototype.toString.call(v).slice(8, -1).toLowerCase();
    }
  };

  // ============================================================
  // DOM Utilities / DOM 操作工具
  // ============================================================
  const Dom = {
    /**
     * Query selector
     */
    $: function (selector, context) {
      return (context || document).querySelector(selector);
    },

    /**
     * Query selector all
     */
    $$: function (selector, context) {
      return Array.prototype.slice.call((context || document).querySelectorAll(selector));
    },

    /**
     * Create element with attributes
     * @param {string} tag
     * @param {Object} [attrs]
     * @param {string|HTMLElement|Array} [children]
     * @returns {HTMLElement}
     */
    create: function (tag, attrs, children) {
      const el = document.createElement(tag);

      if (attrs && Type.isObject(attrs)) {
        for (const key in attrs) {
          if (key === 'class' || key === 'className') {
            el.className = attrs[key];
          } else if (key === 'style' && Type.isObject(attrs[key])) {
            Object.assign(el.style, attrs[key]);
          } else if (key.startsWith('on') && Type.isFunction(attrs[key])) {
            el.addEventListener(key.slice(2).toLowerCase(), attrs[key]);
          } else if (key === 'html') {
            el.innerHTML = attrs[key];
          } else if (attrs[key] !== undefined && attrs[key] !== null) {
            el.setAttribute(key, attrs[key]);
          }
        }
      }

      if (children !== undefined) {
        if (Type.isString(children)) {
          el.textContent = children;
        } else if (children instanceof HTMLElement) {
          el.appendChild(children);
        } else if (Type.isArray(children)) {
          children.forEach(function (child) {
            if (child instanceof HTMLElement) {
              el.appendChild(child);
            } else if (Type.isString(child)) {
              el.appendChild(document.createTextNode(child));
            }
          });
        }
      }

      return el;
    },

    /**
     * Add class(es)
     */
    addClass: function (el, classes) {
      if (!el) return;
      const classList = Array.isArray(classes) ? classes : classes.split(/\s+/);
      classList.forEach(function (cls) {
        if (cls) el.classList.add(cls);
      });
    },

    /**
     * Remove class(es)
     */
    removeClass: function (el, classes) {
      if (!el) return;
      const classList = Array.isArray(classes) ? classes : classes.split(/\s+/);
      classList.forEach(function (cls) {
        if (cls) el.classList.remove(cls);
      });
    },

    /**
     * Toggle class
     */
    toggleClass: function (el, cls, force) {
      if (!el) return;
      if (force === undefined) {
        el.classList.toggle(cls);
      } else {
        el.classList.toggle(cls, force);
      }
    },

    /**
     * Check if element has class
     */
    hasClass: function (el, cls) {
      return el && el.classList.contains(cls);
    },

    /**
     * Get / Set CSS styles
     */
    css: function (el, prop, value) {
      if (!el) return;
      if (Type.isObject(prop)) {
        Object.assign(el.style, prop);
      } else if (value !== undefined) {
        el.style[prop] = value;
      } else {
        return getComputedStyle(el)[prop];
      }
    },

    /**
     * Get element offset relative to document
     */
    offset: function (el) {
      if (!el) return { top: 0, left: 0 };
      const rect = el.getBoundingClientRect();
      return {
        top: rect.top + window.pageYOffset,
        left: rect.left + window.pageXOffset
      };
    },

    /**
     * Check if element is visible in viewport
     */
    isInViewport: function (el, offset) {
      if (!el) return false;
      const rect = el.getBoundingClientRect();
      offset = offset || 0;
      return (
        rect.top + offset >= 0 &&
        rect.left + offset >= 0 &&
        rect.bottom - offset <= (window.innerHeight || document.documentElement.clientHeight) &&
        rect.right - offset <= (window.innerWidth || document.documentElement.clientWidth)
      );
    }
  };

  // ============================================================
  // Event Utilities / 事件处理工具
  // ============================================================
  const Event = {
    /**
     * Debounce - 防抖
     * @param {Function} fn
     * @param {number} delay - ms
     * @param {boolean} [immediate=false]
     * @returns {Function}
     */
    debounce: function (fn, delay, immediate) {
      let timer = null;
      const debounced = function () {
        const context = this;
        const args = arguments;
        if (timer) clearTimeout(timer);
        if (immediate) {
          const callNow = !timer;
          timer = setTimeout(function () { timer = null; }, delay);
          if (callNow) fn.apply(context, args);
        } else {
          timer = setTimeout(function () {
            fn.apply(context, args);
          }, delay);
        }
      };
      debounced.cancel = function () {
        if (timer) clearTimeout(timer);
        timer = null;
      };
      return debounced;
    },

    /**
     * Throttle - 节流
     * @param {Function} fn
     * @param {number} delay - ms
     * @returns {Function}
     */
    throttle: function (fn, delay) {
      let last = 0;
      let timer = null;
      const throttled = function () {
        const context = this;
        const args = arguments;
        const now = Date.now();
        const remaining = delay - (now - last);

        if (remaining <= 0) {
          if (timer) {
            clearTimeout(timer);
            timer = null;
          }
          last = now;
          fn.apply(context, args);
        } else if (!timer) {
          timer = setTimeout(function () {
            last = Date.now();
            timer = null;
            fn.apply(context, args);
          }, remaining);
        }
      };
      throttled.cancel = function () {
        if (timer) clearTimeout(timer);
        timer = null;
        last = 0;
      };
      return throttled;
    },

    /**
     * Create a custom event
     */
    emit: function (el, eventName, detail) {
      if (!el) return;
      const event = new CustomEvent(eventName, { detail: detail, bubbles: true });
      el.dispatchEvent(event);
    },

    /**
     * Add event listener with delegation support
     */
    on: function (el, event, selector, handler) {
      if (!el) return;
      if (Type.isFunction(selector)) {
        handler = selector;
        selector = null;
      }

      const listener = function (e) {
        if (!selector) {
          handler.call(el, e);
          return;
        }
        const target = e.target.closest(selector);
        if (target && el.contains(target)) {
          handler.call(target, e, target);
        }
      };

      el.addEventListener(event, listener);
      return function off() {
        el.removeEventListener(event, listener);
      };
    },

    /**
     * Remove event listener (returns from on())
     */
    off: function (el, event, handler) {
      if (!el) return;
      el.removeEventListener(event, handler);
    },

    /**
     * Run function when DOM is ready
     */
    ready: function (fn) {
      if (document.readyState !== 'loading') {
        fn();
      } else {
        document.addEventListener('DOMContentLoaded', fn);
      }
    }
  };

  // ============================================================
  // Form Validation / 表单验证工具
  // ============================================================
  const Validate = {
    /**
     * Validate email
     */
    isEmail: function (str) {
      const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
      return re.test(str);
    },

    /**
     * Validate phone number (China)
     */
    isPhone: function (str) {
      const re = /^1[3-9]\d{9}$/;
      return re.test(str);
    },

    /**
     * Validate URL
     */
    isUrl: function (str) {
      try {
        new URL(str);
        return true;
      } catch (_) {
        return false;
      }
    },

    /**
     * Validate ID card (China)
     */
    isIdCard: function (str) {
      const re = /(^\d{15}$)|(^\d{18}$)|(^\d{17}(\d|X|x)$)/;
      return re.test(str);
    },

    /**
     * Validate required
     */
    isRequired: function (val) {
      return !Type.isEmpty(val);
    },

    /**
     * Validate min length
     */
    minLength: function (str, min) {
      return str && str.length >= min;
    },

    /**
     * Validate max length
     */
    maxLength: function (str, max) {
      return str && str.length <= max;
    },

    /**
     * Validate min value
     */
    min: function (num, minVal) {
      return Type.isNumber(num) && num >= minVal;
    },

    /**
     * Validate max value
     */
    max: function (num, maxVal) {
      return Type.isNumber(num) && num <= maxVal;
    },

    /**
     * Validate number
     */
    isNumber: function (str) {
      return !isNaN(parseFloat(str)) && isFinite(str);
    },

    /**
     * Validate integer
     */
    isInteger: function (str) {
      return /^-?\d+$/.test(str);
    },

    /**
     * Validate pattern
     */
    pattern: function (str, regex) {
      return new RegExp(regex).test(str);
    },

    /**
     * Validate a form field with rules
     * @param {*} value
     * @param {Array} rules - [{required, message}, {type: 'email', message}, ...]
     * @returns {{valid: boolean, errors: string[]}}
     */
    validate: function (value, rules) {
      const errors = [];
      rules = rules || [];

      for (let i = 0; i < rules.length; i++) {
        const rule = rules[i];
        let valid = true;
        let msg = rule.message || '验证失败';

        if (rule.required) {
          valid = this.isRequired(value);
          if (!valid) msg = rule.message || '此项为必填';
        } else if (rule.type === 'email') {
          if (value) valid = this.isEmail(value);
        } else if (rule.type === 'phone') {
          if (value) valid = this.isPhone(value);
        } else if (rule.type === 'url') {
          if (value) valid = this.isUrl(value);
        } else if (rule.type === 'number') {
          if (value) valid = this.isNumber(value);
        } else if (rule.type === 'integer') {
          if (value) valid = this.isInteger(value);
        } else if (rule.min !== undefined) {
          if (value) valid = this.min(Number(value), rule.min);
        } else if (rule.max !== undefined) {
          if (value) valid = this.max(Number(value), rule.max);
        } else if (rule.minLength !== undefined) {
          if (value) valid = this.minLength(value, rule.minLength);
        } else if (rule.maxLength !== undefined) {
          if (value) valid = this.maxLength(value, rule.maxLength);
        } else if (rule.pattern) {
          if (value) valid = this.pattern(value, rule.pattern);
        } else if (typeof rule.validator === 'function') {
          valid = rule.validator(value);
        }

        if (!valid) {
          errors.push(msg);
          if (rule.first !== false) break;
        }
      }

      return {
        valid: errors.length === 0,
        errors: errors
      };
    }
  };

  // ============================================================
  // Date Format / 日期格式化
  // ============================================================
  const DateUtil = {
    /**
     * Format date
     * @param {Date|string|number} date
     * @param {string} [format='YYYY-MM-DD HH:mm:ss']
     *  YYYY - 4-digit year
     *  MM - 2-digit month
     *  DD - 2-digit day
     *  HH - 24-hour
     *  hh - 12-hour
     *  mm - minutes
     *  ss - seconds
     *  A - AM/PM
     *  a - am/pm
     * @returns {string}
     */
    format: function (date, format) {
      const d = date instanceof Date ? date : new Date(date);
      if (isNaN(d.getTime())) return '';

      format = format || 'YYYY-MM-DD HH:mm:ss';

      const pad = function (n) { return n < 10 ? '0' + n : String(n); };

      const year = d.getFullYear();
      const month = d.getMonth() + 1;
      const day = d.getDate();
      const hours = d.getHours();
      const hours12 = hours % 12 || 12;
      const minutes = d.getMinutes();
      const seconds = d.getSeconds();
      const ampm = hours < 12 ? 'AM' : 'PM';

      return format
        .replace('YYYY', year)
        .replace('MM', pad(month))
        .replace('DD', pad(day))
        .replace('HH', pad(hours))
        .replace('hh', pad(hours12))
        .replace('mm', pad(minutes))
        .replace('ss', pad(seconds))
        .replace('A', ampm)
        .replace('a', ampm.toLowerCase());
    },

    /**
     * Get relative time string
     */
    relativeTime: function (date) {
      const d = date instanceof Date ? date : new Date(date);
      const diff = Date.now() - d.getTime();
      const sec = Math.floor(diff / 1000);
      const min = Math.floor(sec / 60);
      const hour = Math.floor(min / 60);
      const day = Math.floor(hour / 24);
      const month = Math.floor(day / 30);
      const year = Math.floor(day / 365);

      if (sec < 60) return '刚刚';
      if (min < 60) return min + ' 分钟前';
      if (hour < 24) return hour + ' 小时前';
      if (day < 30) return day + ' 天前';
      if (month < 12) return month + ' 个月前';
      return year + ' 年前';
    },

    /**
     * Get start of day
     */
    startOfDay: function (date) {
      const d = new Date(date);
      d.setHours(0, 0, 0, 0);
      return d;
    },

    /**
     * Get end of day
     */
    endOfDay: function (date) {
      const d = new Date(date);
      d.setHours(23, 59, 59, 999);
      return d;
    },

    /**
     * Check if two dates are same day
     */
    isSameDay: function (date1, date2) {
      const d1 = new Date(date1);
      const d2 = new Date(date2);
      return (
        d1.getFullYear() === d2.getFullYear() &&
        d1.getMonth() === d2.getMonth() &&
        d1.getDate() === d2.getDate()
      );
    },

    /**
     * Add days to date
     */
    addDays: function (date, days) {
      const d = new Date(date);
      d.setDate(d.getDate() + days);
      return d;
    }
  };

  // ============================================================
  // Number Format / 数字格式化
  // ============================================================
  const NumberUtil = {
    /**
     * Format number with thousands separator
     * @param {number} num
     * @param {number} [decimals=0]
     * @returns {string}
     */
    format: function (num, decimals) {
      if (isNaN(num)) return '';
      decimals = decimals !== undefined ? decimals : 0;
      const n = Number(num).toFixed(decimals);
      const parts = n.split('.');
      parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
      return parts.join('.');
    },

    /**
     * Format as currency
     * @param {number} num
     * @param {string} [symbol='¥']
     * @param {number} [decimals=2]
     * @returns {string}
     */
    currency: function (num, symbol, decimals) {
      symbol = symbol || '¥';
      decimals = decimals !== undefined ? decimals : 2;
      return symbol + this.format(num, decimals);
    },

    /**
     * Format as percentage
     * @param {number} num
     * @param {number} [decimals=0]
     * @returns {string}
     */
    percent: function (num, decimals) {
      decimals = decimals !== undefined ? decimals : 0;
      return (num * 100).toFixed(decimals) + '%';
    },

    /**
     * Format bytes to human readable
     * @param {number} bytes
     * @param {number} [decimals=2]
     * @returns {string}
     */
    formatBytes: function (bytes, decimals) {
      if (bytes === 0) return '0 B';
      decimals = decimals !== undefined ? decimals : 2;
      const k = 1024;
      const sizes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
      const i = Math.floor(Math.log(bytes) / Math.log(k));
      return parseFloat((bytes / Math.pow(k, i)).toFixed(decimals)) + ' ' + sizes[i];
    },

    /**
     * Clamp number between min and max
     */
    clamp: function (num, min, max) {
      return Math.min(Math.max(num, min), max);
    },

    /**
     * Pad number with leading zeros
     */
    pad: function (num, length) {
      return String(num).padStart(length || 2, '0');
    }
  };

  // ============================================================
  // Object Utilities / 对象工具
  // ============================================================
  const Obj = {
    /**
     * Deep clone
     * @param {*} obj
     * @returns {*}
     */
    deepClone: function (obj) {
      if (obj === null || typeof obj !== 'object') return obj;
      if (obj instanceof Date) return new Date(obj.getTime());
      if (obj instanceof RegExp) return new RegExp(obj.source, obj.flags);
      if (Array.isArray(obj)) return obj.map(function (item) { return deepClone(item); });

      const result = {};
      for (const key in obj) {
        if (obj.hasOwnProperty(key)) {
          result[key] = deepClone(obj[key]);
        }
      }
      return result;
    },

    /**
     * Deep merge (target <- source)
     */
    deepMerge: function (target, source) {
      if (!Type.isObject(target)) target = {};
      if (!Type.isObject(source)) return target;

      for (const key in source) {
        if (source.hasOwnProperty(key)) {
          if (Type.isObject(source[key]) && Type.isObject(target[key])) {
            target[key] = this.deepMerge(target[key], source[key]);
          } else if (Type.isArray(source[key])) {
            target[key] = source[key].slice();
          } else {
            target[key] = source[key];
          }
        }
      }
      return target;
    },

    /**
     * Get nested value by path
     * @param {Object} obj
     * @param {string} path - e.g. 'a.b.c' or 'a[0].b'
     * @param {*} [defaultValue]
     * @returns {*}
     */
    get: function (obj, path, defaultValue) {
      if (!obj || !path) return defaultValue;
      const keys = path.replace(/\[(\d+)\]/g, '.$1').split('.');
      let result = obj;
      for (let i = 0; i < keys.length; i++) {
        if (result == null) return defaultValue;
        result = result[keys[i]];
      }
      return result === undefined ? defaultValue : result;
    },

    /**
     * Set nested value by path
     */
    set: function (obj, path, value) {
      if (!obj || !path) return obj;
      const keys = path.replace(/\[(\d+)\]/g, '.$1').split('.');
      let current = obj;
      for (let i = 0; i < keys.length - 1; i++) {
        const key = keys[i];
        const nextKey = keys[i + 1];
        if (current[key] == null) {
          current[key] = /^\d+$/.test(nextKey) ? [] : {};
        }
        current = current[key];
      }
      current[keys[keys.length - 1]] = value;
      return obj;
    },

    /**
     * Pick keys from object
     */
    pick: function (obj, keys) {
      const result = {};
      keys.forEach(function (key) {
        if (obj && obj.hasOwnProperty(key)) {
          result[key] = obj[key];
        }
      });
      return result;
    },

    /**
     * Omit keys from object
     */
    omit: function (obj, keys) {
      const result = {};
      for (const key in obj) {
        if (obj.hasOwnProperty(key) && keys.indexOf(key) === -1) {
          result[key] = obj[key];
        }
      }
      return result;
    }
  };

  // ============================================================
  // String Utilities / 字符串工具
  // ============================================================
  const Str = {
    /**
     * Capitalize first letter
     */
    capitalize: function (str) {
      if (!str) return '';
      return str.charAt(0).toUpperCase() + str.slice(1);
    },

    /**
     * Camel case to kebab case
     */
    kebabCase: function (str) {
      return str.replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase();
    },

    /**
     * Kebab case to camel case
     */
    camelCase: function (str) {
      return str.replace(/-([a-z])/g, function (_, c) { return c.toUpperCase(); });
    },

    /**
     * Truncate string
     */
    truncate: function (str, length, suffix) {
      if (!str) return '';
      length = length || 30;
      suffix = suffix || '...';
      if (str.length <= length) return str;
      return str.slice(0, length) + suffix;
    },

    /**
     * Escape HTML
     */
    escapeHtml: function (str) {
      const div = document.createElement('div');
      div.textContent = str;
      return div.innerHTML;
    },

    /**
     * Generate unique ID
     */
    uid: function (prefix) {
      return (prefix || 'yx-') + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
    }
  };

  // ============================================================
  // Storage Utilities / 存储工具
  // ============================================================
  const Storage = {
    /**
     * Get from localStorage
     */
    get: function (key) {
      try {
        const val = localStorage.getItem(key);
        if (val === null) return null;
        try {
          return JSON.parse(val);
        } catch (_) {
          return val;
        }
      } catch (_) {
        return null;
      }
    },

    /**
     * Set to localStorage
     */
    set: function (key, value) {
      try {
        localStorage.setItem(key, typeof value === 'string' ? value : JSON.stringify(value));
        return true;
      } catch (_) {
        return false;
      }
    },

    /**
     * Remove from localStorage
     */
    remove: function (key) {
      try {
        localStorage.removeItem(key);
        return true;
      } catch (_) {
        return false;
      }
    },

    /**
     * Clear all localStorage
     */
    clear: function () {
      try {
        localStorage.clear();
        return true;
      } catch (_) {
        return false;
      }
    }
  };

  // Helper for deepClone (referenced inside)
  function deepClone(obj) {
    return Obj.deepClone(obj);
  }

  // ============================================================
  // Theme Utilities / 主题工具
  // ============================================================
  const Theme = {
    STORAGE_KEY: 'yx-ui-theme',

    /**
     * Get current theme
     * @returns {'light'|'dark'}
     */
    get: function () {
      const saved = Storage.get(this.STORAGE_KEY);
      if (saved === 'light' || saved === 'dark') return saved;
      if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
        return 'dark';
      }
      return 'light';
    },

    /**
     * Set theme
     * @param {'light'|'dark'} theme
     */
    set: function (theme) {
      const html = document.documentElement;
      if (theme === 'dark') {
        html.classList.add('yx-dark');
      } else {
        html.classList.remove('yx-dark');
      }
      Storage.set(this.STORAGE_KEY, theme);

      // Dispatch event
      Event.emit(window, 'yxthemechange', { theme: theme });
    },

    /**
     * Toggle theme
     */
    toggle: function () {
      const current = this.get();
      const next = current === 'dark' ? 'light' : 'dark';
      this.set(next);
      return next;
    },

    /**
     * Initialize theme (call early to prevent flash)
     */
    init: function () {
      const theme = this.get();
      if (theme === 'dark') {
        document.documentElement.classList.add('yx-dark');
      }
    }
  };

  // ============================================================
  // Export
  // ============================================================
  const Utils = {
    Type: Type,
    Dom: Dom,
    Event: Event,
    Validate: Validate,
    Date: DateUtil,
    Number: NumberUtil,
    Obj: Obj,
    Str: Str,
    Storage: Storage,
    Theme: Theme,

    // Shortcuts
    debounce: Event.debounce,
    throttle: Event.throttle,
    deepClone: Obj.deepClone,
    deepMerge: Obj.deepMerge,
    formatDate: DateUtil.format,
    formatNumber: NumberUtil.format
  };

  global.YunXiUI = global.YunXiUI || {};
  global.YunXiUI.Utils = Utils;

})(typeof window !== 'undefined' ? window : this);
