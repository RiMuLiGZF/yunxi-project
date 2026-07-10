# CryptoUtils 加密工具模块

## 一、组件职责

CryptoUtils 是联邦调度系统的"加密基础设施"，为整个联邦模块提供统一的加密解密、密钥管理和安全工具服务。核心职责包括：主密钥的加载与管理（从环境变量读取或自动生成）、基于 Fernet 的对称加密/解密、主密钥轮换、受信任调用者鉴权、API Key 脱敏展示、以及内容哈希计算。采用单例模式全局共享一个 `CryptoManager` 实例，确保密钥管理的一致性和安全性。

## 二、核心数据结构

| 结构 | 关键字段 | 说明 |
|------|---------|------|
| `CryptoManager` | `_fernet`, `_master_key`, `_logger` | 加密管理器主类，封装所有加密操作 |
| `TRUSTED_INTERNAL_CALLERS: set` | `federation.adapter.*`, `federation.registry` 等 6 个组件 ID | 受信任内部组件白名单，可读取明文 Key |
| `MASTER_KEY_ENV: str` | `FEDERATION_MASTER_KEY` | 主密钥环境变量名 |
| `_crypto_manager: CryptoManager \| None` | 模块级单例 | 全局共享的加密管理器实例 |
| `_CRYPTO_AVAILABLE: bool` | 运行时检测 | cryptography 库是否可用，不可用时降级到 base64 |

## 三、关键方法

- **`encrypt(plaintext) -> str`** — 加密明文：使用 Fernet（AES-128-CBC + HMAC-SHA256）加密，返回 base64 编码的密文字符串。cryptography 库不可用时降级为 base64 编码（仅开发模式）。
- **`decrypt(ciphertext, caller_id) -> str`** — 解密密文：验证密文有效性后解密，记录调用者 ID 用于审计，解密失败抛出 `ValueError`。
- **`rotate_master_key(new_key) -> dict`** — 主密钥轮换：支持传入新密钥或自动生成，返回轮换结果和预览，调用方需负责使用新密钥重新加密现有数据。
- **`is_trusted_caller(caller_id) -> bool`** — 调用者鉴权：检查 caller_id 是否在受信任白名单中，用于 API Key 读取权限控制。
- **`mask_api_key(api_key, keep_prefix, keep_suffix) -> str`** — API Key 脱敏：只保留前后各 4 位，中间用 `****` 替换，用于日志和预览展示。
- **`content_hash(content) -> str`** — 内容哈希：计算 SHA-256 十六进制哈希，用于内容完整性校验和审计去标识化。
- **`get_crypto_manager() -> CryptoManager`** — 获取单例：模块级函数，懒加载全局加密管理器实例。

## 四、依赖关系

| 依赖方 | 依赖类型 | 说明 |
|--------|---------|------|
| `cryptography.Fernet` | 可选强依赖 | Fernet 对称加密（AES-128-CBC + HMAC-SHA256），不可用时降级 base64 |
| `os` / `base64` / `hashlib` | 标准库 | 环境变量读取、base64 编解码、SHA-256 哈希 |
| `structlog` | 工具依赖 | 结构化日志记录密钥加载、解密操作、轮换事件 |
| `ExternalAgentRegistry` | 被依赖方 | Registry 使用 CryptoUtils 进行 API Key 加解密和鉴权 |

调用方向：`ExternalAgentRegistry` -> `get_crypto_manager()` -> `encrypt()/decrypt()`；各 Adapter -> `mask_api_key()`（日志脱敏）。所有需要加密能力的联邦子模块均通过此模块获取服务。

## 五、V11.1 改进点

1. **Fernet 对称加密**：V11.1 新增独立加密工具模块，采用 `cryptography.Fernet`（AES-128-CBC + HMAC-SHA256）实现工业级对称加密，替代之前的明文存储方案。
2. **主密钥管理**：支持从环境变量 `FEDERATION_MASTER_KEY` 加载主密钥；未配置时自动生成并给出持久化警告；主密钥与加密数据分离存储，便于密钥轮换和权限管控。
3. **API Key 脱敏工具**：提供 `mask_api_key()` 统一脱敏函数，默认保留前后各 4 位，供所有组件在日志输出、界面展示时调用，从源头防止密钥泄露。
4. **受信任调用者列表**：定义 `TRUSTED_INTERNAL_CALLERS` 白名单（6 个内部组件 ID），配合 `is_trusted_caller()` 方法实现细粒度的 API Key 读取权限控制，未授权组件只能获取脱敏预览。
5. **优雅降级与密钥轮换**：cryptography 库缺失时自动降级为 base64 编码（开发模式）；提供 `rotate_master_key()` 支持主密钥应急轮换，保障系统在不同环境下的可用性和安全性。
