# 云汐系统 - 全局产物管理目录

## 概述

本目录是云汐系统的**全局开发产物统一管理中心**，用于收纳所有对话窗口产生的开发交付物，解决多窗口并行开发导致的文件散乱、难以查找和复用的问题。

任何对话窗口产生的代码、文档、脚本、报告等产物，都应在此处登记归档，确保跨会话可查询、可追溯、可复用。

## 目录结构

```
artifacts/
├── README.md                    # 本文件 - 产物管理说明文档
├── index.json                   # 产物索引总表（所有产物的元数据）
├── by-module/                   # 按模块分类存放（主存储）
│   ├── M1-agent-cluster/        # M1 多Agent集群调度
│   ├── M2-skills-cluster/       # M2 技能集群
│   ├── M3-edge-cloud/           # M3 端云协同
│   ├── M4-scene-engine/         # M4 场景引擎
│   ├── M5-tide-memory/          # M5 潮汐记忆
│   ├── M6-hardware-peripheral/  # M6 硬件外设
│   ├── M7-workflow-builder/     # M7 工作流构建器
│   ├── M8-control-tower/        # M8 控制塔
│   ├── M9-programming-dev/      # M9 编程开发
│   └── M10-system-guard/        # M10 系统卫士
├── by-type/                     # 按类型分类（索引视图）
│   ├── docs/                    # 文档类
│   ├── scripts/                 # 脚本类
│   ├── reports/                 # 报告类
│   └── prototypes/              # 原型类
├── by-dialog/                   # 按对话窗口分类
│   ├── dialog-001-xxx/
│   │   └── manifest.json        # 该对话的产物清单
│   └── dialog-002-xxx/
│       └── manifest.json
├── templates/                   # 产物模板
│   ├── module-readme.md         # 模块README模板
│   ├── api-doc-template.md      # API文档模板
│   ├── test-report-template.md  # 测试报告模板
│   ├── release-note-template.md # 发布说明模板
│   └── dev-log-template.md      # 开发日志模板
├── tools/                       # 管理工具脚本
│   ├── __init__.py
│   ├── artifact_indexer.py      # 产物索引生成器
│   ├── artifact_search.py       # 产物搜索工具
│   └── manifest_generator.py    # 对话产物清单生成器
└── tests/                       # 单元测试
    ├── __init__.py
    ├── test_artifact_indexer.py
    ├── test_artifact_search.py
    └── test_manifest_generator.py
```

## 如何查找产物

### 方式一：使用搜索工具（推荐）

```bash
# 按名称搜索
python tools/artifact_search.py --name "M10"

# 按模块和类型筛选
python tools/artifact_search.py --module M1 --type doc

# 按标签搜索
python tools/artifact_search.py --tag "开发方案"

# 显示详细信息
python tools/artifact_search.py -n "测试报告" -v

# 查看统计
python tools/artifact_search.py --stats

# 列出所有产物
python tools/artifact_search.py --list
```

### 方式二：按模块查找

直接进入 `by-module/Mx-xxx/` 目录浏览对应模块的所有产物。

### 方式三：按对话查找

进入 `by-dialog/dialog-xxx/` 目录查看该对话的 `manifest.json` 清单。

```bash
# 列出所有对话
python tools/manifest_generator.py --list

# 查看对话详情
python tools/manifest_generator.py --show dialog-001
```

### 方式四：查看索引文件

直接打开 `index.json` 查看所有产物的元数据总表。

## 如何登记新产物

### 方式一：自动扫描（推荐）

将产物文件放入 `by-module/Mx-xxx/` 对应模块目录下，然后运行索引器：

```bash
# 增量更新（保留已有记录的元数据）
python tools/artifact_indexer.py

# 全量重建
python tools/artifact_indexer.py --full

# 显示统计信息
python tools/artifact_indexer.py --stats
```

索引器会自动识别：
- 文件类型（根据扩展名和文件名关键词）
- 所属模块（根据路径和文件名中的 Mx 标识）
- 文件大小和内容哈希（用于检测变更）

### 方式二：手动登记

```bash
python tools/artifact_indexer.py --add "产物名称" doc M1 "by-module/M1-agent-cluster/file.md" "产物描述"
```

### 方式三：对话清单登记

```bash
# 创建对话
python tools/manifest_generator.py --create dialog-005 "M10开发对话"

# 向对话添加产物
python tools/manifest_generator.py --add dialog-005 \
  --artifact artifact-001 \
  --name "M10系统卫士开发方案" \
  --type doc \
  --module M10 \
  --path "by-module/M10-system-guard/m10-dev-spec.md" \
  --desc "M10系统卫士模块完整开发方案"
```

## 命名规范

### 文件命名

- **统一使用小写字母 + 连字符**：`module-name-description.md`
- **包含模块标识**：文件名开头或包含 `Mx` 标识，如 `m10-dev-spec.md`
- **使用有意义的名称**：避免 `新建文本文档.md`、`123.md` 等无意义命名
- **版本号放在末尾**：`m1-architecture-v2.0.md`

### 对话命名

- 格式：`dialog-{序号}-{简称}`
- 示例：`dialog-001-m1-architecture`、`dialog-015-m10-dev`

### 产物 ID

- 格式：`artifact-{三位序号}`
- 示例：`artifact-001`、`artifact-042`
- 由索引器自动分配，无需手动指定

## 标签规范

标签用于分类和搜索，每个产物应包含以下几类标签：

### 必选标签
- **模块标签**：如 `M1`、`M10`
- **类型标签**：如 `doc`、`code`、`report`

### 可选标签
- **功能领域**：`架构`、`接口`、`测试`、`部署`、`配置`
- **文档类型**：`开发方案`、`设计文档`、`测试报告`、`用户手册`
- **状态标签**：`草稿`、`评审中`、`已发布`、`已废弃`
- **关联模块**：`M2`、`M5`（涉及多个模块时）

### 命名约定
- 使用中文或英文均可，但同一语义保持一致
- 避免过于宽泛的标签（如 `文档`、`代码`）
- 标签数量控制在 3-8 个为宜

## 产物类型定义

| 类型 | 说明 | 常见扩展名 |
|------|------|------------|
| doc | 文档类 | .md, .txt, .rst, .docx, .pptx |
| code | 代码类 | .py, .js, .ts, .go, .rs, .java |
| script | 脚本类 | .sh, .bat, .ps1, 工具类.py |
| report | 报告类 | 测试报告、验收报告、评审报告等 |
| proto | 原型类 | HTML原型、图片原型、Demo等 |
| config | 配置类 | .yaml, .json, .ini, .cfg |

## 状态定义

| 状态 | 说明 |
|------|------|
| active | 活跃 - 当前有效的产物 |
| deprecated | 已废弃 - 不再使用但保留参考 |
| replaced | 已替代 - 已有更新版本替代 |

## 索引结构说明

`index.json` 是所有产物的元数据总表，结构如下：

```json
{
  "version": "1.0",
  "generated_at": "2026-07-08T10:30:00",
  "artifact_count": 42,
  "artifacts": {
    "artifact-001": {
      "id": "artifact-001",
      "name": "产物名称",
      "type": "doc",
      "module": "M10",
      "dialog_id": "dialog-005",
      "dialog_name": "M10开发对话",
      "description": "产物描述",
      "path": "by-module/M10-system-guard/file.md",
      "tags": ["M10", "开发方案"],
      "created_at": "2026-07-08T10:30:00",
      "updated_at": "2026-07-08T10:30:00",
      "version": "1.0",
      "status": "active",
      "related_artifacts": ["artifact-002"],
      "size_bytes": 15360,
      "content_hash": "md5哈希值"
    }
  }
}
```

## 工具脚本说明

### artifact_indexer.py - 产物索引器

功能：
- 扫描 artifacts/ 目录下所有文件
- 自动识别文件类型和所属模块
- 生成/更新 index.json
- 支持增量更新和全量重建
- 支持手动登记新产物

### artifact_search.py - 产物搜索工具

功能：
- 按名称模糊搜索
- 按模块/类型/状态/对话筛选
- 按标签模糊搜索
- 支持详细模式和统计视图
- 命令行接口

### manifest_generator.py - 对话清单生成器

功能：
- 创建/管理对话目录
- 生成单个对话的 manifest.json
- 支持追加、移除产物
- 支持从全局索引同步生成

## 工作流建议

1. **开发过程中**：将产出的文档、脚本等放入对应模块目录
2. **会话结束前**：运行 `artifact_indexer.py` 更新索引
3. **登记对话产物**：使用 `manifest_generator.py` 生成对话清单
4. **查找参考资料**：使用 `artifact_search.py` 搜索已有产物
5. **定期整理**：检查废弃产物，更新状态标签

## 注意事项

- 所有文件使用 **UTF-8 编码**，确保中文正常显示
- 大文件（>10MB）建议使用链接引用而非直接放入
- 敏感信息（密钥、密码等）不得放入产物目录
- 模板文件和工具脚本不计入产物索引
- 修改产物文件后请重新运行索引器更新元数据
