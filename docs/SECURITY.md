# 云汐系统安全文档

## 1. 安全架构概述

云汐系统采用纵深防御（Defense in Depth）的安全架构设计，在多个层级实施安全防护措施，确保系统的机密性、完整性和可用性。

### 1.1 安全分层架构

```
┌─────────────────────────────────────────────────┐
│              应用层安全 (Application)           │
│  输入验证 / 输出编码 / 业务权限 / 数据脱敏       │
├─────────────────────────────────────────────────┤
│              中间件层安全 (Middleware)          │
│  WAF / 限流 / 安全头 / CORS / 认证中间件        │
├─────────────────────────────────────────────────┤
│              网关层安全 (API Gateway)           │
│  统一认证 / 速率限制 / 请求审计 / IP 封禁        │
├─────────────────────────────────────────────────┤
│              数据层安全 (Data)                  │
│  密码哈希 / 敏感数据加密 / SQL 注入防护          │
├─────────────────────────────────────────────────┤
│              基础设施安全 (Infrastructure)      │
│  HTTPS / 网络隔离 / 容器安全 / 日志审计          │
└─────────────────────────────────────────────────┘
```

### 1.2 核心安全组件

| 组件 | 位置 | 职责 |
|------|------|------|
| WAF 中间件 | `shared/core/waf_middleware.py` | SQL注入、XSS、命令注入、路径遍历检测与拦截 |
| 安全头中间件 | `shared/core/middleware/security_headers.py` | HTTP 安全响应头设置 |
| 认证中间件 | `shared/core/auth/middleware.py` | JWT Token 验证、用户身份识别 |
| 速率限制器 | `API-Gateway/src/services/rate_limiter.py` | 多级限流、登录失败锁定、IP 封禁 |
| 密码工具 | `shared/core/auth/password.py` | bcrypt 密码哈希、密码验证 |
| JWT 工具 | `shared/core/auth/jwt.py` | Token 签发、验证、刷新 |
| 输入验证工具 | `shared/core/security.py` | 输入净化、XSS过滤、路径安全、文件上传验证 |
| CORS 工具 | `shared/core/utils/cors_utils.py` | 跨域请求安全配置 |

---

## 2. 已实施的安全措施

### 2.1 认证与授权

#### 2.1.1 身份认证
- **JWT Token 机制**：使用 HS256 算法签名，支持访问令牌和刷新令牌
- **Token 过期策略**：访问令牌 2 小时过期，刷新令牌 7 天过期
- **Token 黑名单**：支持主动注销 Token（Redis 存储）
- **密码哈希**：使用 bcrypt 算法，工作因子 12，自动加盐

#### 2.1.2 登录安全
- **登录失败锁定**：连续 5 次失败后锁定账号 5 分钟，渐进式延长
- **IP 级锁定**：同一 IP 20 次登录失败后锁定整个 IP
- **登录限流**：登录接口每分钟 10 次请求限制
- **恒定时间比较**：使用 `hmac.compare_digest` 防止时序攻击

#### 2.1.3 权限控制
- **角色权限体系**：基于角色的访问控制（RBAC）
- **中间件鉴权**：统一认证中间件，支持可选/强制认证
- **API Key 认证**：支持服务间 API Key 认证，独立限流

### 2.2 输入验证与注入防护

#### 2.2.1 XSS 防护
- **输出编码**：`escape_html()` 自动转义 HTML 特殊字符
- **HTML 净化**：`sanitize_html()` 基于白名单的 HTML 标签过滤
- **多模式过滤**：`xss_filter()` 支持 strict/basic/rich 三种模式
- **安全头辅助**：`X-XSS-Protection` 和 `Content-Security-Policy`

#### 2.2.2 SQL 注入防护
- **ORM 优先**：优先使用 SQLAlchemy ORM，避免手写 SQL
- **参数化查询**：所有原生查询使用参数化语句
- **WAF 检测**：WAF 中间件实时检测 SQL 注入攻击模式

#### 2.2.3 路径遍历防护
- **安全路径拼接**：`safe_join_path()` 确保路径在基础目录内
- **文件名净化**：`safe_filename()` 移除危险字符和路径组件
- **路径组件验证**：`validate_path_component()` 单组件安全检查
- **规范化处理**：`normalize_path()` 移除路径遍历字符

#### 2.2.4 命令注入防护
- **输入检测**：`is_command_injection()` 检测命令注入模式
- **Shell 执行保护**：禁止使用 shell=True，参数列表方式调用

#### 2.2.5 文件上传安全
- **MIME 类型验证**：白名单验证 Content-Type
- **扩展名验证**：白名单验证文件扩展名
- **魔数检测**：通过文件头魔数验证真实文件类型
- **大小限制**：默认最大 10MB，可配置
- **危险扩展名拦截**：.exe、.php、.js 等危险扩展名直接拒绝
- **随机文件名**：存储时使用随机文件名，防止路径猜测
- **扩展名与 MIME 匹配**：确保文件扩展名与声明的 MIME 类型一致

### 2.3 敏感数据保护

#### 2.3.1 日志脱敏
- **自动脱敏**：`mask_sensitive_data()` 自动检测并脱敏敏感信息
- **脱敏字段**：密码、Token、API Key、手机号、邮箱、身份证、银行卡、IP 地址
- **日志过滤器**：日志系统内置脱敏过滤器

#### 2.3.2 错误响应安全
- **生产环境脱敏**：生产环境不返回异常详情和堆栈信息
- **通用错误消息**：仅返回 "服务器内部错误，请稍后重试"
- **服务端日志**：详细错误信息仅记录在服务端日志中

#### 2.3.3 数据传输安全
- **HTTPS 强制**：生产环境强制 HTTPS
- **HSTS**：Strict-Transport-Security 头，max-age=31536000

### 2.4 安全响应头

所有 HTTP 响应自动添加以下安全头：

| 安全头 | 值 | 作用 |
|--------|-----|------|
| X-Content-Type-Options | nosniff | 防止 MIME 类型嗅探 |
| X-Frame-Options | DENY | 防止点击劫持 |
| X-XSS-Protection | 1; mode=block | 启用浏览器 XSS 防护 |
| Content-Security-Policy | default-src 'self' | 防止 XSS 和数据注入 |
| Strict-Transport-Security | max-age=31536000 | 强制 HTTPS |
| Referrer-Policy | strict-origin-when-cross-origin | 控制 Referer 信息泄露 |
| Cache-Control | no-store | 敏感页面不缓存 |
| Permissions-Policy | 禁用高风险权限 | 限制浏览器功能 |

### 2.5 速率限制与防滥用

#### 2.5.1 多级限流
- **全局限速**：令牌桶算法，默认 600 请求/分钟
- **IP 级限流**：令牌桶算法，默认 100 请求/分钟
- **分级限流**：不同接口不同级别（public/sensitive/strict/admin/mcp）
- **用户级限流**：登录用户按用户 ID 限流（预留）
- **API Key 限流**：按 API Key 独立限流

#### 2.5.2 限流级别定义

| 级别 | 每分钟请求 | 每小时请求 | 适用场景 |
|------|-----------|-----------|----------|
| public | 100 | 2000 | 公开接口（默认） |
| sensitive | 10 | 100 | 登录、注册、验证码 |
| strict | 5 | 20 | 密码重置、API Key 管理 |
| admin | 30 | 500 | 管理后台接口 |
| mcp | 60 | 1000 | MCP 工具调用 |

#### 2.5.3 渐进式封禁
- 第 1-3 次超限：仅警告，不封禁
- 第 4-6 次：封禁 5 分钟
- 第 7-10 次：封禁 30 分钟
- 第 11+ 次：封禁 24 小时

### 2.6 CORS 安全

- **生产环境强制白名单**：禁止使用通配符 `*`
- **开发环境默认本地**：自动配置 localhost 常用端口
- **凭证控制**：`allow_credentials=True` 配合具体来源

### 2.7 Web 应用防火墙（WAF）

- **检测引擎**：内置 WAF 检测引擎，零外部依赖
- **工作模式**：monitor（只检测）/ block（拦截）
- **检测类型**：SQL 注入、XSS、命令注入、路径遍历、CSRF
- **降级策略**：引擎异常时自动降级放行，不阻塞正常请求
- **统计监控**：实时统计请求数、拦截数、攻击类型分布

---

## 3. 安全最佳实践

### 3.1 开发安全规范

#### 3.1.1 输入验证
- **所有用户输入必须验证**：不信任任何来自客户端的数据
- **使用白名单验证**：优先使用白名单而非黑名单
- **类型约束**：使用 Pydantic 模型定义请求/响应数据结构
- **边界检查**：数值范围、字符串长度、数组大小

#### 3.1.2 输出编码
- **HTML 上下文**：使用 `escape_html()` 转义
- **JavaScript 上下文**：使用 JSON 序列化
- **URL 上下文**：使用 URL 编码
- **数据库上下文**：使用参数化查询

#### 3.1.3 密码安全
- **强制密码强度**：至少 12 位，包含大小写字母、数字、特殊字符
- **禁止弱密码**：常见弱密码字典检测
- **密码哈希**：使用 bcrypt，禁止明文存储
- **密码重置**：使用一次性 Token，有过期时间

#### 3.1.4 API 设计安全
- **幂等性**：重要操作支持幂等键
- **请求签名**：高敏感接口支持请求签名
- **版本控制**：API 版本化，平滑升级
- **错误消息**：不泄露内部实现细节

### 3.2 部署安全配置

#### 3.2.1 环境变量
敏感配置必须通过环境变量注入，禁止硬编码：

```bash
# 数据库密码
YUNXI_DB_PASSWORD=your_secure_password

# JWT 密钥（生产环境必须修改）
YUNXI_JWT_SECRET=your_jwt_secret_key_at_least_32_chars

# 加密密钥
YUNXI_ENCRYPTION_KEY=your_encryption_key

# 环境标识
YUNXI_ENV=production
```

#### 3.2.2 生产环境检查清单

- [ ] DEBUG 模式已关闭
- [ ] JWT 密钥已更换为强随机值
- [ ] 数据库密码已修改
- [ ] CORS 已配置具体来源（非通配符）
- [ ] HTTPS 已启用
- [ ] HSTS 已启用
- [ ] 日志脱敏已启用
- [ ] 错误堆栈已关闭
- [ ] 速率限制已配置
- [ ] WAF 已启用 block 模式
- [ ] 文件上传大小限制已配置
- [ ] 备份加密已配置

### 3.3 依赖安全

- **版本锁定**：`requirements.txt` 锁定精确版本
- **定期更新**：每月检查依赖更新和安全公告
- **最小依赖**：只引入必要的依赖包
- **可信来源**：只从官方 PyPI 安装包

---

## 4. 漏洞响应流程

### 4.1 漏洞等级定义

| 等级 | 定义 | 响应时间 | 示例 |
|------|------|---------|------|
| P0 紧急 | 可直接获取系统权限、数据大规模泄露 | 24 小时内 | SQL 注入获取所有数据、远程代码执行 |
| P1 高危 | 可越权访问敏感数据、绕过认证 | 3 天内 | 垂直越权、水平越权访问他人数据 |
| P2 中危 | 有限制的信息泄露、普通用户体验影响 | 7 天内 | 反射型 XSS、路径遍历读取非敏感文件 |
| P3 低危 | 理论性漏洞、可忽略的信息泄露 | 30 天内 | 版本号泄露、最佳实践建议 |

### 4.2 漏洞报告

安全漏洞请通过以下方式报告：

1. **内部渠道**：安全团队工单系统
2. **邮件**：security@yunxi-system.com
3. **紧急联系**：安全值班电话

请提供以下信息：
- 漏洞类型和等级
- 复现步骤和环境
- 影响范围评估
- 建议修复方案（如有）

### 4.3 处理流程

```
漏洞报告 → 初步确认 (24h) → 等级评定 → 修复开发 → 验证测试 → 发布上线 → 复盘总结
```

### 4.4 漏洞披露政策

- 内部漏洞：修复后内部通报
- 外部报告：征得报告者同意后披露
- 客户通知：影响客户数据的漏洞需主动通知
- 公开披露：修复验证完成后 90 天内可公开

---

## 5. 安全配置指南

### 5.1 安全头配置

通过环境变量配置安全头中间件：

```bash
# 启用/禁用安全头（默认 true）
SEC_HEADERS_ENABLED=true

# HSTS（生产环境自动启用）
SEC_HEADERS_HSTS=true

# 自定义 CSP 策略
SEC_HEADERS_CSP="default-src 'self'; script-src 'self' 'unsafe-inline'"

# X-Frame-Options（默认 DENY）
SEC_HEADERS_FRAME_OPTIONS=DENY
```

代码方式配置：

```python
from shared.core.middleware.security_headers import SecurityHeadersMiddleware, CSPBuilder

# 自定义 CSP
csp = (
    CSPBuilder()
    .default_src("'self'")
    .script_src("'self'", "https://cdn.example.com")
    .img_src("'self'", "data:", "https://*.example.com")
    .style_src("'self'", "'unsafe-inline'")
    .build()
)

app.add_middleware(
    SecurityHeadersMiddleware,
    env="production",
    csp_policy=csp,
    frame_options_value="SAMEORIGIN",
)
```

### 5.2 速率限制配置

```python
from API-Gateway.src.services.rate_limiter import RateLimiter, RATE_LIMIT_TIERS

# 自定义限速级别
rate_limiter = RateLimiter(
    total_limit=1000,    # 全局限速：1000 请求/分钟
    per_ip_limit=200,    # 单 IP 限速：200 请求/分钟
)

# 设置 API Key 限速
rate_limiter.set_api_key_limit(
    api_key="your-api-key",
    requests_per_minute=500,
)
```

### 5.3 WAF 配置

```python
from shared.core.waf_middleware import WafMiddleware, WafConfig

config = WafConfig(
    mode="block",              # block / monitor
    sql_injection_enabled=True,
    xss_enabled=True,
    command_injection_enabled=True,
    path_traversal_enabled=True,
    csrf_enabled=False,         # API 服务通常不需要 CSRF
)

app.add_middleware(WafMiddleware, config=config)
```

### 5.4 文件上传安全配置

```python
from shared.core.security import validate_file_upload, ALLOWED_IMAGE_TYPES

# 仅允许图片上传
is_safe, reason = validate_file_upload(
    filename=upload.filename,
    content_type=upload.content_type,
    file_content=await upload.read(),
    max_size_bytes=5 * 1024 * 1024,  # 5MB
    allowed_types=ALLOWED_IMAGE_TYPES,
)
```

---

## 6. 安全审计记录

### 6.1 第四阶段生产就绪安全审计

**审计日期**：2026-07-17
**审计范围**：全系统 P1/P2 级安全问题
**审计结果**：

| 编号 | 问题 | 等级 | 状态 | 修复位置 |
|------|------|------|------|---------|
| SEC-001 | 缺少安全响应头（X-Frame-Options、CSP、HSTS 等） | P1 | 已修复 | `shared/core/middleware/security_headers.py` |
| SEC-002 | 生产环境错误响应泄露堆栈信息 | P1 | 已修复 | `M0-principal-console/src/errors.py` |
| SEC-003 | 缺少文件上传安全验证机制 | P1 | 已修复 | `shared/core/security.py` (validate_file_upload) |
| SEC-004 | 登录接口缺少账号锁定机制 | P2 | 已修复 | `API-Gateway/src/services/rate_limiter.py` |
| SEC-005 | 缺少统一的路径安全工具函数 | P2 | 已修复 | `shared/core/security.py` (路径安全工具集) |
| SEC-006 | XSS 过滤功能不完善 | P2 | 已修复 | `shared/core/security.py` (xss_filter 多模式) |
| SEC-007 | 缺少 API Key 级独立限流 | P2 | 已修复 | `API-Gateway/src/services/rate_limiter.py` |
| SEC-008 | 缺少密码强度校验 | P2 | 已修复 | `shared/core/security.py` (check_password_strength) |

---

## 7. 附录

### 7.1 安全工具速查表

| 工具函数 | 位置 | 用途 |
|---------|------|------|
| `escape_html()` | shared/core/security.py | HTML 转义 |
| `sanitize_html()` | shared/core/security.py | HTML 净化（白名单） |
| `xss_filter()` | shared/core/security.py | XSS 过滤（多模式） |
| `validate_input()` | shared/core/security.py | 通用输入验证 |
| `safe_join_path()` | shared/core/security.py | 安全路径拼接 |
| `safe_filename()` | shared/core/security.py | 安全文件名 |
| `is_path_safe()` | shared/core/security.py | 路径安全检查 |
| `normalize_path()` | shared/core/security.py | 路径规范化 |
| `validate_file_upload()` | shared/core/security.py | 文件上传安全验证 |
| `detect_file_type_by_magic()` | shared/core/security.py | 文件魔数检测 |
| `generate_safe_filename()` | shared/core/security.py | 生成安全存储文件名 |
| `mask_sensitive_data()` | shared/core/security.py | 日志脱敏 |
| `check_password_strength()` | shared/core/security.py | 密码强度检查 |
| `constant_time_equals()` | shared/core/security.py | 恒定时间比较 |
| `secure_random_string()` | shared/core/security.py | 安全随机字符串 |
| `prevent_js_protocol()` | shared/core/security.py | 防止 javascript: 协议注入 |
| `validate_url_safety()` | shared/core/security.py | URL 安全验证 |

### 7.2 参考标准

- OWASP Top 10
- OWASP ASVS (Application Security Verification Standard)
- NIST SP 800-53
- GDPR 数据保护要求
- 网络安全等级保护 2.0

---

**文档版本**：v1.0 (第四阶段生产就绪)
**最后更新**：2026-07-17
**维护者**：云汐安全团队
