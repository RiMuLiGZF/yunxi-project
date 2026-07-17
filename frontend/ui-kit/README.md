# YunXi UI Kit / 云汐前端统一组件库

> 云汐系统前端统一组件库基础版 - 轻量级、零依赖、主题化、框架无关

## 特性

- **零依赖** - 纯原生 HTML/CSS/JS，无需任何框架
- **主题系统** - CSS 变量驱动，支持深浅主题切换
- **按需引入** - 支持完整引入和按需引入两种方式
- **海洋风格** - 与云汐系统现有设计语言一致
- **响应式** - 适配不同屏幕尺寸
- **可访问性** - 基本的 a11y 支持（焦点、ARIA、键盘导航）
- **框架无关** - 可在原生 HTML、Vue、React 等任何环境中使用

## 技术选型

| 技术 | 选择 | 原因 |
|------|------|------|
| 语言 | 原生 JavaScript (ES6+) | 零依赖、兼容所有框架 |
| 样式 | CSS 变量 + 原生 CSS | 主题切换简单、性能好 |
| 组件模式 | 函数式创建 + CSS Class 双模式 | 灵活适配不同使用场景 |
| 主题 | CSS 变量 + localStorage | 与现有云汐主题系统兼容 |

## 目录结构

```
ui-kit/
├── README.md                # 组件库文档
├── package.json             # 包配置
├── src/
│   ├── index.js             # 入口文件（完整引入）
│   ├── index.css            # 样式入口（完整引入）
│   ├── styles/
│   │   ├── variables.css    # CSS 变量（设计令牌）
│   │   ├── reset.css        # 样式重置
│   │   └── base.css         # 基础样式 & 工具类
│   ├── components/          # 组件目录
│   │   ├── button/          # 按钮
│   │   ├── input/           # 输入框
│   │   ├── textarea/        # 多行文本
│   │   ├── select/          # 下拉选择
│   │   ├── checkbox/        # 复选框
│   │   ├── radio/           # 单选框
│   │   ├── switch/          # 开关
│   │   ├── card/            # 卡片
│   │   ├── modal/           # 弹窗
│   │   ├── drawer/          # 抽屉
│   │   ├── tabs/            # 标签页
│   │   ├── table/           # 表格
│   │   ├── pagination/      # 分页
│   │   ├── toast/           # 消息提示
│   │   ├── loading/         # 加载中
│   │   ├── dropdown/        # 下拉菜单
│   │   ├── timeline/        # 时间线（业务组件）
│   │   ├── steps/           # 步骤条（业务组件）
│   │   └── chart/           # 图表（业务组件）
│   └── utils/
│       └── index.js         # 工具函数库
├── docs/
│   └── index.html           # 组件文档 & 示例
└── tests/                   # 测试（待完善）
```

## 组件清单

### 基础组件（16 个）

| 组件 | 说明 | 特性 |
|------|------|------|
| **Button** | 按钮 | primary/secondary/outline/ghost/danger/success/warning/link，支持 disabled/loading/icon/size/block/round |
| **Input** | 输入框 | text/password/number/search/email，支持验证状态/前缀后缀/可清除/密码可见性 |
| **Textarea** | 多行文本 | 支持自适应高度/字数统计/验证状态 |
| **Select** | 下拉选择 | 单选/多选/搜索/禁用项 |
| **Checkbox** | 复选框 | 单个/组/半选状态 |
| **Radio** | 单选框 | 单个/组/按钮样式 |
| **Switch** | 开关 | 支持 loading/异步切换 |
| **Card** | 卡片 | 基础/带图/悬停效果/玻璃拟态/加载态 |
| **Modal** | 弹窗 | 基础/确认框/信息框/成功/警告/错误 |
| **Drawer** | 抽屉 | 四个方向/尺寸/底部操作栏 |
| **Tabs** | 标签页 | line/card/segment 样式/垂直/动态 |
| **Table** | 表格 | 斑马纹/排序/行选择/加载态/空状态 |
| **Pagination** | 分页 | 页码/跳页/每页数量/简洁模式 |
| **Toast** | 消息提示 | success/error/warning/info/loading/自动关闭 |
| **Loading** | 加载中 | spinner/dots/pulse/全屏/容器包裹/骨架屏 |
| **Dropdown** | 下拉菜单 | 点击/悬停触发/多方向/分组/分割线 |

### 业务组件（3 个）

| 组件 | 说明 |
|------|------|
| **Timeline** | 时间线 | 左侧/右侧/交替布局/多种状态颜色 |
| **Steps** | 步骤条 | 水平/垂直/点状/多种状态 |
| **Chart** | 图表 | 柱状图/折线图/饼图（Canvas 实现，零依赖） |

## 快速开始

### 方式一：完整引入

```html
<link rel="stylesheet" href="/ui-kit/src/index.css">
<script src="/ui-kit/src/index.js"></script>
<script src="/ui-kit/src/utils/index.js"></script>
```

### 方式二：按需引入

```html
<!-- 基础样式（必须） -->
<link rel="stylesheet" href="/ui-kit/src/styles/variables.css">
<link rel="stylesheet" href="/ui-kit/src/styles/reset.css">
<link rel="stylesheet" href="/ui-kit/src/styles/base.css">

<!-- 按需引入组件 -->
<link rel="stylesheet" href="/ui-kit/src/components/button/button.css">
<script src="/ui-kit/src/components/button/button.js"></script>
```

### 方式三：仅使用 CSS 类

```html
<button class="yx-btn yx-btn--primary">主按钮</button>
<button class="yx-btn yx-btn--secondary">次按钮</button>
<input class="yx-input" placeholder="请输入内容">
```

## 使用示例

### Button 按钮

```javascript
// JS 方式创建
const btn = YunXiUI.Button.create({
  text: '提交',
  type: 'primary',
  size: 'md',
  onClick: function() {
    console.log('clicked');
  }
});
document.body.appendChild(btn);

// 设置加载状态
YunXiUI.Button.setLoading(btn, true);
```

### Modal 弹窗

```javascript
// 确认框
YunXiUI.Modal.confirm({
  title: '确认删除？',
  content: '删除后无法恢复，确定要继续吗？',
  type: 'warning',
  onOk: function() {
    // 执行删除
    YunXiUI.Toast.success('删除成功');
  }
});

// 自定义弹窗
const modal = YunXiUI.Modal.create({
  title: '用户信息',
  content: '<p>这里是弹窗内容...</p>',
  onOk: function() {
    console.log('确认');
  }
});
modal.open();
```

### Table 表格

```javascript
const table = YunXiUI.Table.create({
  columns: [
    { key: 'name', title: '名称', sortable: true },
    { key: 'status', title: '状态', render: function(val) {
      return '<span class="yx-badge">' + val + '</span>';
    }},
    { key: 'action', title: '操作', align: 'right' }
  ],
  data: [
    { key: 1, name: '项目A', status: '运行中' },
    { key: 2, name: '项目B', status: '已停止' }
  ],
  striped: true,
  onSort: function(key, order) {
    console.log(key, order);
  }
});
document.getElementById('table-container').appendChild(table);
```

### Toast 消息提示

```javascript
YunXiUI.Toast.success('操作成功');
YunXiUI.Toast.error('操作失败，请重试');
YunXiUI.Toast.warning('请注意');
YunXiUI.Toast.info('提示信息');

// Loading toast
const loading = YunXiUI.Toast.loading('加载中...');
setTimeout(() => loading.close(), 2000);
```

## 主题系统

### 切换主题

```javascript
// 获取当前主题
YunXiUI.Utils.Theme.get(); // 'light' | 'dark'

// 设置主题
YunXiUI.Utils.Theme.set('dark');

// 切换主题
YunXiUI.Utils.Theme.toggle();
```

### 自定义主题

只需覆盖 CSS 变量即可：

```css
:root {
  --yx-color-primary: #your-color;
  --yx-color-primary-hover: #your-hover-color;
  --yx-radius-lg: 12px;
  /* ... 更多变量 */
}
```

### 完整变量列表

- 颜色系统：主色、辅助色、成功/警告/错误/信息、中性色、背景色、边框色、文字色
- 字体系统：字号、字重、行高、字间距
- 间距系统：4px 基准
- 圆角系统：sm/md/lg/xl/2xl/full
- 阴影系统：xs/sm/md/lg/xl/2xl + 发光效果
- 动效系统：过渡时间、缓动函数
- 层级系统：dropdown/sticky/modal/toast/tooltip
- 布局常量：header高度、sidebar宽度

## 工具函数

```javascript
// 类型判断
YunXiUI.Utils.Type.isString('hello');   // true
YunXiUI.Utils.Type.isArray([1, 2]);      // true

// DOM 操作
YunXiUI.Utils.Dom.$('.selector');        // querySelector
YunXiUI.Utils.Dom.$$('.selector');       // querySelectorAll
YunXiUI.Utils.Dom.create('div', { class: 'box' }, 'content');

// 防抖节流
const debouncedFn = YunXiUI.Utils.debounce(fn, 300);
const throttledFn = YunXiUI.Utils.throttle(fn, 300);

// 深拷贝
const copy = YunXiUI.Utils.deepClone(obj);

// 日期格式化
YunXiUI.Utils.Date.format(new Date(), 'YYYY-MM-DD HH:mm:ss');
YunXiUI.Utils.Date.relativeTime(date); // "5 分钟前"

// 数字格式化
YunXiUI.Utils.Number.format(1234567);    // "1,234,567"
YunXiUI.Utils.Number.currency(99.9);     // "¥99.90"
YunXiUI.Utils.Number.formatBytes(1024);  // "1 KB"

// 表单验证
YunXiUI.Utils.Validate.isEmail('a@b.com');
YunXiUI.Utils.Validate.validate(value, [
  { required: true, message: '必填' },
  { type: 'email', message: '邮箱格式不正确' }
]);

// 存储
YunXiUI.Utils.Storage.set('key', { foo: 'bar' });
YunXiUI.Utils.Storage.get('key');
```

## 与现有云汐系统集成

本组件库与云汐现有主题系统（`common/css/theme.css` + `common/js/theme.js`）完全兼容：

1. CSS 变量命名风格一致（`--yx-*` vs `--color-*`）
2. 都支持浅色/深色双主题
3. 都使用 localStorage 持久化主题偏好
4. 海洋蓝渐变设计语言统一

在已有页面中引入组件库不会与现有样式冲突。

## 浏览器支持

- Chrome / Edge (最新版)
- Firefox (最新版)
- Safari (最新版)
- 不支持 IE

## 版本历史

### v1.0.0 (2026-07-17)
- 初始版本
- 16 个基础组件
- 3 个业务组件
- 主题系统（浅/深双主题）
- 工具函数库
- 文档与示例页面
