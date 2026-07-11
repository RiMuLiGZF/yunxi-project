/**
 * 云汐系统 (Yunxi System) - 三层启动屏控制器
 * 控制 Splash → Greeting → Mode Selector 的层切换与所有交互逻辑
 */

/* ============================================================
   数据定义
   ============================================================ */

// Splash 层状态消息 - 启动检测序列
const SPLASH_MESSAGES = [
  { main: '正在启动云汐系统', sub: '正在初始化系统组件…' },
  { main: '正在启动云汐系统', sub: '正在检查 M1 感知中枢…' },
  { main: '正在启动云汐系统', sub: '正在检查 M2 情绪引擎…' },
  { main: '正在启动云汐系统', sub: '正在检查 M3 行为决策…' },
  { main: '正在启动云汐系统', sub: '正在检查 M4 呼吸节律…' },
  { main: '正在启动云汐系统', sub: '正在检查 M5 潮汐记忆…' },
  { main: '正在启动云汐系统', sub: '正在检查 M6 成长进化…' },
  { main: '正在启动云汐系统', sub: '正在检查 M7 隐私守护…' },
  { main: '正在启动云汐系统', sub: '正在检查 M8 控制塔…' },
  { main: '正在启动云汐系统', sub: '正在检测大模型服务…' },
  { main: '正在启动云汐系统', sub: '正在加载个人偏好…' },
  { main: '正在启动云汐系统', sub: '准备就绪，即将进入…' },
];

// 场景卡片数据
const SCENE_CARDS = [
  { id: 'scene-a', name: '工作开发', desc: '代码、文档、评审，全流程技术助手', color: '#165DFF', icon: 'code-symbol', lastUsed: '2 小时前' },
  { id: 'scene-b', name: '学业规划', desc: '拆解目标，推演路径，步步为营', color: '#00B42A', icon: 'milestone', lastUsed: '昨天' },
  { id: 'scene-c', name: '复盘总结', desc: '情绪梳理 + 客观评审，深度成长', color: '#722ED1', icon: 'review-arrows', lastUsed: '3 天前' },
  { id: 'scene-d', name: '人际关系', desc: '理解关系，改善沟通，化解纠结', color: '#FF7D97', icon: 'people-connect', lastUsed: '上周' },
  { id: 'scene-e', name: '情绪陪伴', desc: '倾听、理解、陪伴，你不是一个人', color: '#E8A0BF', icon: 'heart-glow', lastUsed: null },
  { id: 'scene-f', name: '生活综合管理', desc: '日程、设备、作息，一手掌控', color: '#52C41A', icon: 'dashboard', lastUsed: '今天' },
    { id: 'scene-g', name: '形象工坊', desc: '定制云汐的视觉形象与粒子特效', color: '#4ECDC4', icon: 'palette', lastUsed: null }
  ];

// 设备状态数据
const DEVICES = [
  { name: '桌面端', icon: 'monitor', online: true, detail: 'Windows 11 · 电量 87%' },
  { name: '笔记本', icon: 'laptop', online: true, detail: 'macOS · 电量 62%' },
  { name: '手机', icon: 'smartphone', online: true, detail: 'iOS · 电量 45%' },
  { name: '智能手表', icon: 'watch', online: true, detail: '已连接 · 同步中' },
  { name: '智能戒指', icon: 'ring', online: false, detail: '离线 · 充电中' },
  { name: 'AR 眼镜', icon: 'glasses', online: false, detail: '离线 · 未检测到' },
];

// 今日概览数据
const TODAY_OVERVIEW = [
  { label: '日程', value: '3 项' },
  { label: '待办', value: '7 项' },
  { label: '学习进度', value: '68%' },
];

// 情绪状态数据
const EMOTION_DATA = [
  { label: '平静', value: 65, color: '#7B8CDE' },
  { label: '愉悦', value: 45, color: '#52C41A' },
  { label: '专注', value: 55, color: '#165DFF' },
];

// 设备状态卡数据
const DEVICE_STATUS_DATA = [
  { name: '在线设备', value: '4/6', status: 'normal' },
  { name: '电量告警', value: '1', status: 'warning' },
  { name: '同步中', value: '2', status: 'syncing' },
];

// 记忆回溯数据
const MEMORY_ITEMS = [
  { scene: '工作开发', tag: 'Scene-A', summary: '完成了用户认证模块的代码评审', time: '2 小时前' },
  { scene: '学业规划', tag: 'Scene-B', summary: '更新了 Q3 学习目标与里程碑路径', time: '昨天' },
  { scene: '复盘总结', tag: 'Scene-C', summary: '上周情绪波动分析报告已生成', time: '3 天前', sensitive: true },
];

// SVG 图标模板
const ICONS = {
  sun: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>`,
  moon: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`,
  gear: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`,
  chevronDown: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>`,
  chevronUp: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="18 15 12 9 6 15"/></svg>`,
  expand: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>`,
};

// 设备图标 SVG
const DEVICE_ICONS = {
  monitor: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>`,
  laptop: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><path d="M2 17h20"/><path d="M6 21h12"/><path d="M10 17v4"/><path d="M14 17v4"/></svg>`,
  smartphone: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="2" width="14" height="20" rx="2" ry="2"/><line x1="12" y1="18" x2="12" y2="18.01"/></svg>`,
  watch: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="7"/><polyline points="12 9 12 12 13.5 13.5"/><path d="M16.51 4.95l1.49 1.49"/><path d="M6.01 4.95L4.51 6.44"/><path d="M6.01 19.05l-1.5 1.49"/><path d="M16.51 19.05l1.5 1.49"/></svg>`,
  ring: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>`,
  glasses: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12h3l3-7 3 7"/><path d="M22 12h-3l-3-7-3 7"/><circle cx="7" cy="15" r="3"/><circle cx="17" cy="15" r="3"/><line x1="10" y1="15" x2="14" y2="15"/></svg>`,
};

// 场景图标 SVG
const SCENE_ICONS = {
  'code-symbol': `<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>`,
  'milestone': `<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`,
  'review-arrows': `<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="1 4 1 10 7 10"/><polyline points="23 20 23 14 17 14"/><path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15"/></svg>`,
  'people-connect': `<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>`,
  'heart-glow': `<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/><circle cx="12" cy="12" r="10" stroke-dasharray="3 3" opacity="0.3"/></svg>`,
  'dashboard': `<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>`,
};

/* ============================================================
   工具函数
   ============================================================ */

/**
 * 获取时段问候语
 */
function getTimeGreeting(hour) {
  if (hour >= 6 && hour < 11) return '早上好';
  if (hour >= 11 && hour < 14) return '中午好';
  if (hour >= 14 && hour < 18) return '下午好';
  if (hour >= 18 && hour < 22) return '晚上好';
  return '深夜好';
}

/**
 * 格式化日期为 "YYYY年M月D日 星期X"
 */
function formatDate(date) {
  const dayNames = ['日', '一', '二', '三', '四', '五', '六'];
  const y = date.getFullYear();
  const m = date.getMonth() + 1;
  const d = date.getDate();
  const w = dayNames[date.getDay()];
  return `${y}年${m}月${d}日 星期${w}`;
}

/* ============================================================
   Toast 通知系统
   ============================================================ */

function showToast(message, color = null, duration = 2000) {
  const toast = document.createElement('div');
  toast.className = 'toast-notification';
  toast.textContent = message;
  if (color) {
    toast.style.borderLeft = `3px solid ${color}`;
  }
  document.body.appendChild(toast);

  // 触发动画：先添加 visible 类
  requestAnimationFrame(() => {
    toast.classList.add('toast-notification--visible');
  });

  // 自动移除
  setTimeout(() => {
    toast.classList.remove('toast-notification--visible');
    toast.classList.add('toast-notification--exit');
    setTimeout(() => {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 300);
  }, duration);
}

/* ============================================================
   层切换函数
   ============================================================ */

let isTransitioning = false;

function transitionLayer(fromId, toId) {
  if (isTransitioning) return;
  isTransitioning = true;

  const fromLayer = document.getElementById(fromId);
  const toLayer = document.getElementById(toId);

  fromLayer.classList.remove('layer--active');
  fromLayer.classList.add('layer--exit');

  setTimeout(() => {
    fromLayer.classList.remove('layer--exit');
    fromLayer.classList.add('layer--hidden');
    toLayer.classList.remove('layer--hidden');
    toLayer.classList.add('layer--enter');
    requestAnimationFrame(() => {
      toLayer.classList.add('layer--active');
      toLayer.classList.remove('layer--enter');
      isTransitioning = false;
    });
  }, 400);
}

/* ============================================================
   Layer 1: Splash 逻辑
   ============================================================ */

function startSplash() {
  const statusMainEl = document.getElementById('splash-status-main');
  const statusSubEl = document.getElementById('splash-status-sub');

  // 状态消息轮换 - 每条消息显示约 1.5 秒
  let msgIndex = 0;
  const totalMessages = SPLASH_MESSAGES.length;
  
  // 初始化第一条消息
  if (statusMainEl && SPLASH_MESSAGES[0]) {
    statusMainEl.textContent = SPLASH_MESSAGES[0].main;
  }
  if (statusSubEl && SPLASH_MESSAGES[0]) {
    statusSubEl.textContent = SPLASH_MESSAGES[0].sub;
  }

  // 消息切换间隔
  const msgInterval = setInterval(() => {
    msgIndex++;
    if (msgIndex >= totalMessages) {
      msgIndex = totalMessages - 1; // 停在最后一条
      clearInterval(msgInterval);
      return;
    }

    // 淡出效果：先淡出旧文字，再淡入新文字
    if (statusSubEl) {
      statusSubEl.style.opacity = '0';
      setTimeout(() => {
        if (SPLASH_MESSAGES[msgIndex]) {
          if (statusMainEl) {
            statusMainEl.textContent = SPLASH_MESSAGES[msgIndex].main;
          }
          statusSubEl.textContent = SPLASH_MESSAGES[msgIndex].sub;
        }
        statusSubEl.style.opacity = '0.85';
      }, 200);
    }
  }, 1200);

  // 总启动时间：根据消息数量计算，每条约 1.2 秒，最后再加 1 秒缓冲
  const totalDuration = totalMessages * 1200 + 800;

  setTimeout(() => {
    clearInterval(msgInterval);
    // 检查登录状态
    if (typeof YunxiAPI !== 'undefined' && YunxiAPI.isLoggedIn()) {
      // 已登录：进入模式选择层
      transitionLayer('splash-layer', 'mode-selector-layer');
    } else {
      // 未登录：跳转到登录页
      if (typeof YunxiAPI !== 'undefined') {
        YunxiAPI.redirectToLogin();
      } else {
        window.location.href = '../m8/login.html';
      }
    }
  }, totalDuration);
}

/* ============================================================
   Layer 2: Greeting 逻辑
   ============================================================ */

function renderGreetingContent() {
  // Update greeting text
  const greetingText = document.getElementById('greeting-text');
  const greetingDate = document.getElementById('greeting-date');
  if (greetingText) {
    const hour = new Date().getHours();
    const timeGreeting = getTimeGreeting(hour);
    greetingText.textContent = `${timeGreeting}，汐舟主理`;
  }
  if (greetingDate) {
    greetingDate.textContent = formatDate(new Date());
  }

  // Fill status card bodies
  const overviewBody = document.getElementById('card-overview-body');
  if (overviewBody) {
    overviewBody.innerHTML = TODAY_OVERVIEW.map(item => `
      <div class="status-card__item">
        <span class="status-card__label">${item.label}</span>
        <span class="status-card__value">${item.value}</span>
      </div>
    `).join('');
  }

  const emotionBody = document.getElementById('card-emotion-body');
  if (emotionBody) {
    emotionBody.innerHTML = `<p class="emotion-card-subtitle">最近 7 天情绪基调</p>
      <div class="emotion-bars">
        ${EMOTION_DATA.map(em => `
          <div class="emotion-bar__row">
            <span class="emotion-bar__label">${em.label}</span>
            <div class="emotion-bar__track">
              <div class="emotion-bar__fill" style="width: ${em.value}%; background-color: ${em.color};"></div>
            </div>
            <span class="emotion-bar__value">${em.value}%</span>
          </div>
        `).join('')}
      </div>`;
  }

  const devicesBody = document.getElementById('card-devices-body');
  if (devicesBody) {
    devicesBody.innerHTML = DEVICE_STATUS_DATA.map(item => `
      <div class="status-card__item status-card__item--${item.status}">
        <span class="status-card__label">${item.name}</span>
        <span class="status-card__value status-card__value--${item.status}">${item.value}</span>
      </div>
    `).join('');
  }

  // Fill memory list
  const memoryList = document.getElementById('memory-list');
  if (memoryList) {
    const isPrivacy = document.documentElement.getAttribute('data-privacy') === 'active';
    memoryList.innerHTML = MEMORY_ITEMS.map(item => {
      const summary = (isPrivacy && item.sensitive) ? '🔒 脱敏内容' : item.summary;
      return `
        <div class="memory-item ${item.sensitive ? 'memory-item--sensitive' : ''}" tabindex="0">
          <div class="memory-item__header">
            <span class="memory-item__scene">${item.scene}</span>
            <span class="memory-item__tag">${item.tag}</span>
          </div>
          <p class="memory-item__summary" ${item.sensitive ? `data-original="${item.summary}"` : ''}>${summary}</p>
          <span class="memory-item__time">${item.time}</span>
        </div>
      `;
    }).join('');
  }

  // Fill quick scenes chips
  const quickScenes = document.getElementById('quick-scenes');
  if (quickScenes) {
    quickScenes.innerHTML = SCENE_CARDS.map(scene => `
      <button class="quick-scene-chip" data-scene="${scene.id}" data-color="${scene.color}">${scene.name}</button>
    `).join('');
  }
}

/**
 * 绑定 Greeting 层事件
 */
function bindGreetingEvents() {
  // 今日概览卡点击 → 切换到 mode-selector
  const overviewCard = document.querySelector('[data-card="overview"]');
  if (overviewCard) {
    const handler = () => {
      transitionLayer('greeting-layer', 'mode-selector-layer');
    };
    overviewCard.addEventListener('click', handler);
    overviewCard.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handler(); }
    });
  }

  // 情绪状态卡点击 → 切换到 mode-selector 并高亮 emotion-comfort
  const emotionCard = document.querySelector('[data-card="emotion"]');
  if (emotionCard) {
    const handler = () => {
      transitionLayer('greeting-layer', 'mode-selector-layer');
      setTimeout(() => highlightSceneCard('emotion-comfort'), 450);
    };
    emotionCard.addEventListener('click', handler);
    emotionCard.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handler(); }
    });
  }

  // 设备状态卡点击 → 切换到 mode-selector 并高亮 life-management
  const devicesCard = document.querySelector('[data-card="devices"]');
  if (devicesCard) {
    const handler = () => {
      transitionLayer('greeting-layer', 'mode-selector-layer');
      setTimeout(() => highlightSceneCard('life-management'), 450);
    };
    devicesCard.addEventListener('click', handler);
    devicesCard.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handler(); }
    });
  }

  // "开始对话"按钮
  const chatBtn = document.getElementById('btn-start-chat');
  if (chatBtn) {
    chatBtn.addEventListener('click', () => {
      showToast('正在进入对话模式…', '#5DD3D3', 1200);
      setTimeout(() => {
        window.location.href = '../modes/main-chat.html';
      }, 800);
    });
    chatBtn.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        showToast('正在进入对话模式…', '#5DD3D3', 1200);
        setTimeout(() => {
          window.location.href = '../modes/main-chat.html';
        }, 800);
      }
    });
  }

  // Quick scene chip clicks → 直接跳转到对应功能页面
  const QUICK_SCENE_MAP = {
    'scene-a': '../modes/work-dev.html',
    'scene-b': '../modes/study-plan.html',
    'scene-c': '../modes/review-summary.html',
    'scene-d': '../modes/social-relation.html',
    'scene-e': '../modes/emotion-comfort.html',
    'scene-f': '../modes/life-management.html',
    'scene-g': '../modes/appearance-workshop.html',
  };

  document.querySelectorAll('.quick-scene-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const sceneId = chip.getAttribute('data-scene');
      const name = chip.textContent;
      const color = chip.getAttribute('data-color');
      showToast(`正在进入「${name}」模式…`, color, 1200);
      const targetUrl = QUICK_SCENE_MAP[sceneId];
      if (targetUrl) {
        setTimeout(() => { window.location.href = targetUrl; }, 800);
      }
    });
  });

  // 下滑切换到 mode-selector 层（通过 scroll 检测）
  const greetingLayer = document.getElementById('greeting-layer');
  let touchStartY = 0;
  let scrollAccumulator = 0;

  greetingLayer?.addEventListener('wheel', (e) => {
    if (e.deltaY > 0) {
      // Only trigger layer transition when content is scrolled to bottom
      const container = greetingLayer.querySelector('.greeting-container');
      if (container) {
        const atBottom = container.scrollHeight - container.scrollTop - container.clientHeight <= 5;
        if (atBottom) {
          scrollAccumulator += e.deltaY;
          if (scrollAccumulator > 60) {
            transitionLayer('greeting-layer', 'mode-selector-layer');
            scrollAccumulator = 0;
          }
        } else {
          scrollAccumulator = 0;
        }
      }
    } else {
      scrollAccumulator = 0;
    }
  }, { passive: true });

  greetingLayer?.addEventListener('touchstart', (e) => {
    touchStartY = e.touches[0].clientY;
  }, { passive: true });

  greetingLayer?.addEventListener('touchend', (e) => {
    const touchEndY = e.changedTouches[0].clientY;
    const diff = touchStartY - touchEndY;
    if (diff > 60) {
      // Only trigger if scrolled to bottom of content
      const container = greetingLayer.querySelector('.greeting-container');
      if (container) {
        const atBottom = container.scrollHeight - container.scrollTop - container.clientHeight <= 30;
        if (atBottom) {
          transitionLayer('greeting-layer', 'mode-selector-layer');
        }
      }
    }
  }, { passive: true });
}

/* ============================================================
   Layer 3: Mode Selector 逻辑
   ============================================================ */

function renderModeSelectorContent() {
  // Mode selector content is already in HTML, no need to regenerate
}

/**
 * 高亮指定的场景卡片
 */
function highlightSceneCard(sceneValue) {
  const card = document.querySelector(`.scene-card[data-scene="${sceneValue}"]`);
  if (!card) return;

  card.classList.add('scene-card--highlighted');
  card.scrollIntoView({ behavior: 'smooth', block: 'center' });

  // 3 秒后移除高亮
  setTimeout(() => {
    card.classList.remove('scene-card--highlighted');
  }, 3000);
}

/**
 * 绑定 Mode Selector 层事件
 */
function bindModeSelectorEvents() {
  // Mode buttons click → navigate to corresponding page
  const SCENE_PAGE_MAP = {
    'work-dev': '../modes/work-dev.html',
    'study-plan': '../modes/study-plan.html',
    'review-summary': '../modes/review-summary.html',
    'social-relation': '../modes/social-relation.html',
    'emotion-comfort': '../modes/emotion-comfort.html',
    'life-management': '../modes/life-management.html',
    'appearance-workshop': '../modes/appearance-workshop.html',
  };

  document.querySelectorAll('.mode-btn[data-scene]').forEach(btn => {
    const handler = () => {
      const sceneId = btn.getAttribute('data-scene');
      const nameEl = btn.querySelector('.mode-btn__name');
      const name = nameEl ? nameEl.textContent : sceneId;
      const color = getComputedStyle(btn).getPropertyValue('--btn-color').trim();
      showToast(`正在进入「${name}」模式…`, color || null, 1200);
      const targetUrl = SCENE_PAGE_MAP[sceneId];
      if (targetUrl) {
        setTimeout(() => { window.location.href = targetUrl; }, 800);
      }
    };
    btn.addEventListener('click', handler);
  });

  // "开启对话" button
  const startConvBtn = document.getElementById('btn-start-conversation');
  if (startConvBtn) {
    startConvBtn.addEventListener('click', () => {
      const href = startConvBtn.getAttribute('data-href');
      if (href) {
        showToast('正在进入对话模式…', '#5DD3D3', 1200);
        setTimeout(() => { window.location.href = href; }, 800);
      }
    });
  }
}

/* ============================================================
   设置与主题
   ============================================================ */

function initThemeToggle() {
  // 读取本地存储的主题偏好
  const savedTheme = localStorage.getItem('yunxi-theme');
  if (savedTheme === 'light') {
    document.documentElement.setAttribute('data-mode', 'light');
    updateThemeIcon(true);
  } else {
    document.documentElement.setAttribute('data-mode', 'dark');
    updateThemeIcon(false);
  }

  // 绑定所有主题切换按钮
  const themeToggles = document.querySelectorAll('#theme-toggle, #theme-toggle-mode');
  themeToggles.forEach(btn => {
    btn.addEventListener('click', () => {
      const isCurrentlyLight = document.documentElement.getAttribute('data-mode') === 'light';
      if (isCurrentlyLight) {
        document.documentElement.setAttribute('data-mode', 'dark');
        localStorage.setItem('yunxi-theme', 'dark');
        updateThemeIcon(false);
      } else {
        document.documentElement.removeAttribute('data-mode');
        document.documentElement.setAttribute('data-mode', 'light');
        localStorage.setItem('yunxi-theme', 'light');
        updateThemeIcon(true);
      }
    });
  });
}

/**
 * 更新所有主题切换按钮的图标
 */
function updateThemeIcon(isLight) {
  const themeToggles = document.querySelectorAll('#theme-toggle, #theme-toggle-mode');
  themeToggles.forEach(btn => {
    btn.innerHTML = isLight ? ICONS.moon : ICONS.sun;
  });
}

/**
 * 设置下拉菜单
 */
function initSettingsDropdown() {
  const settingsBtn = document.getElementById('settings-btn');
  const settingsWrapper = document.getElementById('settings-wrapper');
  const settingsDropdown = document.getElementById('settings-dropdown');

  if (!settingsBtn || !settingsDropdown) return;

  settingsBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    const isOpen = settingsDropdown.classList.contains('settings-dropdown--open');
    if (isOpen) {
      closeSettingsDropdown();
    } else {
      settingsDropdown.classList.add('settings-dropdown--open');
      // 聚焦第一个选项
      const firstItem = settingsDropdown.querySelector('.settings-dropdown__item');
      if (firstItem) firstItem.focus();
    }
  });

  // 下拉菜单项点击
  settingsDropdown.querySelectorAll('.settings-dropdown__item').forEach(item => {
    item.addEventListener('click', (e) => {
      e.stopPropagation();
      const action = item.getAttribute('data-action');
      closeSettingsDropdown();
      switch (action) {
        case 'display-settings':
          showToast('打开显示设置…');
          break;
        case 'privacy-security':
          showToast('打开隐私与安全设置…');
          break;
        case 'about':
          showToast('云汐 v0.1.0 · Edge-Cloud AI Companion');
          break;
      }
    });
  });
}

function closeSettingsDropdown() {
  const dropdown = document.getElementById('settings-dropdown');
  if (dropdown) {
    dropdown.classList.remove('settings-dropdown--open');
    dropdown.querySelectorAll('.settings-dropdown__item').forEach(item => {
      item.setAttribute('tabindex', '-1');
    });
  }
}

/* ============================================================
   隐私模式
   ============================================================ */

function initPrivacyMode() {
  const privacyBadge = document.getElementById('privacy-badge');
  const isPrivacy = document.documentElement.getAttribute('data-privacy') === 'active';

  if (privacyBadge) {
    privacyBadge.style.display = isPrivacy ? 'flex' : 'none';
  }

  // 监听 privacy 属性变化（通过 MutationObserver）
  const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      if (mutation.type === 'attributes' && mutation.attributeName === 'data-privacy') {
        const active = document.documentElement.getAttribute('data-privacy') === 'active';
        if (privacyBadge) {
          privacyBadge.style.display = active ? 'flex' : 'none';
        }
        // 更新记忆回溯中的敏感内容
        updatePrivacyContent(active);
      }
    });
  });

  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-privacy'],
  });
}

/**
 * 更新隐私模式下的内容显示
 */
function updatePrivacyContent(isPrivacy) {
  document.querySelectorAll('.memory-item--sensitive .memory-item__summary').forEach(el => {
    el.textContent = isPrivacy ? '🔒 脱敏内容' : el.getAttribute('data-original');
  });

  // 保存原始文本
  if (isPrivacy) {
    document.querySelectorAll('.memory-item--sensitive .memory-item__summary').forEach(el => {
      if (!el.getAttribute('data-original')) {
        el.setAttribute('data-original', el.textContent);
      }
      el.textContent = '🔒 脱敏内容';
    });
  } else {
    document.querySelectorAll('.memory-item--sensitive .memory-item__summary').forEach(el => {
      const original = el.getAttribute('data-original');
      if (original) el.textContent = original;
    });
  }
}

/* ============================================================
   键盘导航
   ============================================================ */

function initKeyboardNavigation() {
  document.addEventListener('keydown', (e) => {
    // Escape: 关闭弹窗/下拉
    if (e.key === 'Escape') {
      closeSettingsDropdown();
      // 关闭设备 popover
      const activePopover = document.querySelector('.device-popover--visible');
      if (activePopover) {
        activePopover.classList.remove('device-popover--visible');
        setTimeout(() => activePopover.remove(), 200);
      }
    }

    // Arrow keys: 在场景卡片间导航
    const sceneGrid = document.getElementById('scene-grid');
    if (sceneGrid && sceneGrid.contains(document.activeElement)) {
      const cards = Array.from(sceneGrid.querySelectorAll('.scene-card'));
      const currentIndex = cards.indexOf(document.activeElement);
      const cols = 2; // 假设两列布局

      if (e.key === 'ArrowRight' || e.key === 'ArrowDown' || e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
        e.preventDefault();
        let nextIndex = currentIndex;

        switch (e.key) {
          case 'ArrowRight':
            nextIndex = currentIndex + 1;
            break;
          case 'ArrowLeft':
            nextIndex = currentIndex - 1;
            break;
          case 'ArrowDown':
            nextIndex = currentIndex + cols;
            break;
          case 'ArrowUp':
            nextIndex = currentIndex - cols;
            break;
        }

        if (nextIndex >= 0 && nextIndex < cards.length) {
          cards[nextIndex].focus();
        }
      }
    }
  });
}

/* ============================================================
   初始化
   ============================================================ */

document.addEventListener('DOMContentLoaded', () => {
  // 1. 检查并应用主题偏好
  initThemeToggle();

  // 2. 生成问候页内容
  renderGreetingContent();

  // 3. 生成模式选择器内容
  renderModeSelectorContent();

  // 4. 设置下拉菜单
  initSettingsDropdown();

  // 5. 设置隐私模式
  initPrivacyMode();

  // 6. 绑定事件
  bindGreetingEvents();
  bindModeSelectorEvents();

  // 7. 初始化键盘导航
  initKeyboardNavigation();

  // 8. 启动 Splash 加载序列
  startSplash();
});

// ═══════════════════════════════════════════════════════════
// v2.3 — Hub Avatar Canvas Renderer (Tide Particle Sphere)
// ═══════════════════════════════════════════════════════════
(function() {
  var canvas = document.getElementById('hubAvatarCanvas');
  if (!canvas) return;
  var ctx = canvas.getContext('2d');
  var W = canvas.width;  // 240
  var H = canvas.height; // 240
  var cx = W / 2;
  var cy = H / 2;

  // Generate particles in 3 rings
  var particles = [];
  var ringConfig = [
    { count: 12, radiusMin: 35, radiusMax: 50, sizeMin: 3, sizeMax: 5, color: [139, 124, 240], alpha: 0.7, speed: 0.8 },   // Inner - purple
    { count: 16, radiusMin: 55, radiusMax: 75, sizeMin: 3, sizeMax: 6, color: [91, 200, 220], alpha: 0.65, speed: 0.6 },    // Mid - teal
    { count: 20, radiusMin: 80, radiusMax: 105, sizeMin: 2, sizeMax: 4, color: [100, 160, 240], alpha: 0.4, speed: 0.4 }     // Outer - blue
  ];

  for (var r = 0; r < ringConfig.length; r++) {
    var rc = ringConfig[r];
    for (var i = 0; i < rc.count; i++) {
      particles.push({
        angle: Math.random() * Math.PI * 2,
        radius: rc.radiusMin + Math.random() * (rc.radiusMax - rc.radiusMin),
        size: rc.sizeMin + Math.random() * (rc.sizeMax - rc.sizeMin),
        color: rc.color,
        baseAlpha: rc.alpha * (0.6 + Math.random() * 0.4),
        speed: rc.speed * (0.7 + Math.random() * 0.6),
        phase: Math.random() * Math.PI * 2,
        ring: r,
        ellipseY: r === 2 ? 0.75 : (r === 1 ? 0.85 : 0.9) // vertical squash per ring
      });
    }
  }

  function render(t) {
    t *= 0.001; // seconds
    ctx.clearRect(0, 0, W, H);

    // Core glow - outer
    var coreR = 28 + 3 * Math.sin(t * 0.8);
    var grd3 = ctx.createRadialGradient(cx, cy, 0, cx, cy, coreR * 2.5);
    grd3.addColorStop(0, 'rgba(91,140,239,0.15)');
    grd3.addColorStop(0.5, 'rgba(139,124,240,0.08)');
    grd3.addColorStop(1, 'rgba(139,124,240,0)');
    ctx.beginPath();
    ctx.arc(cx, cy, coreR * 2.5, 0, Math.PI * 2);
    ctx.fillStyle = grd3;
    ctx.fill();

    // Core glow - mid
    var grd2 = ctx.createRadialGradient(cx, cy, 0, cx, cy, coreR * 1.5);
    grd2.addColorStop(0, 'rgba(139,124,240,0.5)');
    grd2.addColorStop(0.4, 'rgba(91,140,239,0.25)');
    grd2.addColorStop(1, 'rgba(91,140,239,0)');
    ctx.beginPath();
    ctx.arc(cx, cy, coreR * 1.5, 0, Math.PI * 2);
    ctx.fillStyle = grd2;
    ctx.fill();

    // Core highlight
    var grd1 = ctx.createRadialGradient(cx - 5, cy - 5, 0, cx, cy, coreR * 0.6);
    grd1.addColorStop(0, 'rgba(200,210,255,0.6)');
    grd1.addColorStop(0.5, 'rgba(139,124,240,0.35)');
    grd1.addColorStop(1, 'rgba(91,140,239,0.1)');
    ctx.beginPath();
    ctx.arc(cx, cy, coreR * 0.6, 0, Math.PI * 2);
    ctx.fillStyle = grd1;
    ctx.fill();

    // Core text "汐"
    ctx.save();
    ctx.font = '600 32px Inter, PingFang SC, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = 'rgba(255,255,255,' + (0.7 + 0.15 * Math.sin(t * 1.2)) + ')';
    ctx.shadowColor = 'rgba(91,140,239,0.5)';
    ctx.shadowBlur = 8;
    ctx.fillText('汐', cx, cy);
    ctx.restore();

    // Draw particles
    for (var i = 0; i < particles.length; i++) {
      var p = particles[i];
      var angle = p.angle + t * p.speed;
      var r = p.radius + 5 * Math.sin(t * 0.5 + p.phase);
      var x = cx + Math.cos(angle) * r;
      var y = cy + Math.sin(angle) * r * p.ellipseY;
      var alpha = p.baseAlpha * (0.7 + 0.3 * Math.sin(t * 1.5 + p.phase));
      var sz = p.size * (0.8 + 0.2 * Math.sin(t + p.phase));

      // Particle glow
      var pg = ctx.createRadialGradient(x, y, 0, x, y, sz * 2.5);
      pg.addColorStop(0, 'rgba(' + p.color[0] + ',' + p.color[1] + ',' + p.color[2] + ',' + (alpha * 0.4) + ')');
      pg.addColorStop(1, 'rgba(' + p.color[0] + ',' + p.color[1] + ',' + p.color[2] + ',0)');
      ctx.beginPath();
      ctx.arc(x, y, sz * 2.5, 0, Math.PI * 2);
      ctx.fillStyle = pg;
      ctx.fill();

      // Particle core
      ctx.beginPath();
      ctx.arc(x, y, sz, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(' + p.color[0] + ',' + p.color[1] + ',' + p.color[2] + ',' + alpha + ')';
      ctx.fill();
    }

    requestAnimationFrame(render);
  }

  requestAnimationFrame(render);
})();

