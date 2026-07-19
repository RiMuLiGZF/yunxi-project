/**
 * Mock 数据工厂
 * 为 E2E 测试提供各 API 的 mock 响应数据
 * 保持与真实后端响应格式一致：{ code: 0, data: {...}, message: 'ok' }
 */

// 统一成功响应包装
function success(data, message = 'ok') {
  return { code: 0, data, message };
}

// 统一错误响应包装
function error(code, message) {
  return { code, data: null, message };
}

// ============================================================
// 测试用户数据
// ============================================================
const testUser = {
  id: 1,
  username: 'admin',
  nickname: '管理员',
  email: 'admin@yunxi.local',
  role: 'admin',
  avatar: null,
  created_at: '2024-01-01T00:00:00Z',
};

const testToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test-token-mock';

// ============================================================
// 模块管理数据
// ============================================================
const modulesList = [
  { key: 'm1', name: '调度引擎', version: 'v2.1.0', status: 'running', port: 8001, description: '负责任务调度、Agent 管理与工作流编排的核心模块。', latency_ms: 12 },
  { key: 'm2', name: '技能中心', version: 'v1.8.3', status: 'running', port: 8002, description: '提供各类 AI 技能与工具调用的统一管理平台。', latency_ms: 18 },
  { key: 'm3', name: '对话系统', version: 'v3.0.1', status: 'running', port: 8003, description: '多轮对话、上下文管理与自然语言理解模块。', latency_ms: 45 },
  { key: 'm4', name: '场景工坊', version: 'v1.2.7', status: 'stopped', port: 8004, description: '可视化场景配置与自定义交互流程搭建工具。', latency_ms: 0 },
  { key: 'm5', name: '记忆存储', version: 'v2.4.0', status: 'running', port: 8005, description: '向量数据库与长期记忆管理，支持语义检索。', latency_ms: 8 },
  { key: 'm6', name: '感知分析', version: 'v1.5.2', status: 'running', port: 8006, description: '多模态感知、情绪识别与用户画像分析模块。', latency_ms: 27 },
  { key: 'm7', name: '积木平台', version: 'v1.0.5', status: 'running', port: 8007, description: '低代码积木式编程平台，支持可视化工作流设计。', latency_ms: 15 },
  { key: 'm8', name: '云汐核心', version: 'v4.2.0', status: 'running', port: 8008, description: '云汐系统核心服务，负责全局协调与系统管理。', latency_ms: 5 },
];

// ============================================================
// 仪表盘统计数据
// ============================================================
const dashboardStats = {
  total_modules: 8,
  running_modules: 7,
  stopped_modules: 1,
  total_agents: 24,
  active_tasks: 12,
  completed_today: 156,
  system_uptime: '15天 8小时 32分',
  avg_latency_ms: 18,
};

// ============================================================
// 系统设置数据
// ============================================================
const systemSettings = {
  system_name: '云汐管理台',
  system_version: 'v1.2.0',
  max_concurrent_tasks: 100,
  default_language: 'zh-CN',
  theme_mode: 'light',
  enable_notifications: true,
  log_level: 'info',
  data_retention_days: 90,
};

// ============================================================
// 健康检查
// ============================================================
const healthStatus = {
  status: 'healthy',
  timestamp: new Date().toISOString(),
  version: 'v1.2.0',
  uptime_seconds: 1324800,
};

// ============================================================
// 导出 Mock 数据
// ============================================================
module.exports = {
  success,
  error,
  testUser,
  testToken,
  modulesList,
  dashboardStats,
  systemSettings,
  healthStatus,
};
