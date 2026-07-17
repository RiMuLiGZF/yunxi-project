"""M9 开发者工坊 - 项目模板系统.

提供项目模板的管理功能：
- 内置项目模板（Python脚本、FastAPI项目、数据分析等）
- 从模板创建项目
- 自定义模板管理
- 模板版本管理
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from .core.path_safety import safe_join, assert_path_safe, PathSecurityError
except ImportError:
    from core.path_safety import safe_join, assert_path_safe, PathSecurityError

try:
    from .config import get_settings
except ImportError:
    from config import get_settings


class ProjectTemplateManager:
    """项目模板管理器."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._templates_dir = Path(self.settings.workspace_root) / ".templates"
        self._templates_dir.mkdir(parents=True, exist_ok=True)
        self._custom_templates_file = self._templates_dir / "custom_templates.json"

    # ------------------------------------------------------------------
    # 内置模板定义
    # ------------------------------------------------------------------

    BUILTIN_TEMPLATES: List[Dict[str, Any]] = [
        {
            "id": "tpl_python_script",
            "name": "Python 脚本",
            "description": "简单的 Python 脚本项目，适合快速原型开发和工具脚本",
            "category": "Python",
            "icon": "🐍",
            "tags": ["python", "script", "基础"],
            "version": "1.0.0",
            "language": "python",
            "files": {
                "main.py": '''#!/usr/bin/env python3
"""主入口脚本."""


def main():
    """主函数."""
    print("Hello, 云汐开发者工坊!")
    return 0


if __name__ == "__main__":
    exit(main())
''',
                "requirements.txt": """# 项目依赖
# requests>=2.28.0
""",
                "README.md": """# Python 脚本项目

## 简介
使用云汐 M9 开发者工坊创建的 Python 脚本项目。

## 运行
```bash
python main.py
```
""",
                ".gitignore": """__pycache__/
*.py[cod]
*$py.class
*.so
.Python
.env
.venv/
venv/
""",
            },
        },
        {
            "id": "tpl_fastapi",
            "name": "FastAPI 项目",
            "description": "基于 FastAPI 的 Web API 项目，包含完整的项目结构",
            "category": "Python",
            "icon": "⚡",
            "tags": ["python", "fastapi", "web", "api"],
            "version": "1.0.0",
            "language": "python",
            "files": {
                "main.py": '''#!/usr/bin/env python3
"""FastAPI 应用主入口."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="云汐 M9 FastAPI 项目",
    description="基于 FastAPI 的 Web API 项目",
    version="1.0.0",
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """根路径."""
    return {"message": "Hello from M9 Dev Workshop!", "status": "ok"}


@app.get("/health")
async def health():
    """健康检查."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
''',
                "requirements.txt": """fastapi>=0.100.0
uvicorn>=0.23.0
pydantic>=2.0.0
""",
                "README.md": """# FastAPI 项目

## 简介
基于 FastAPI 的 Web API 项目模板。

## 安装依赖
```bash
pip install -r requirements.txt
```

## 运行
```bash
python main.py
```

## API 文档
启动后访问: http://localhost:8000/docs
""",
                ".gitignore": """__pycache__/
*.py[cod]
.env
.venv/
""",
            },
        },
        {
            "id": "tpl_data_analysis",
            "name": "数据分析项目",
            "description": "数据分析和可视化项目，包含 pandas、numpy、matplotlib 等常用库",
            "category": "数据科学",
            "icon": "📊",
            "tags": ["python", "data", "analysis", "pandas"],
            "version": "1.0.0",
            "language": "python",
            "files": {
                "analysis.py": '''#!/usr/bin/env python3
"""数据分析脚本."""

import pandas as pd
import numpy as np


def load_data(file_path: str) -> pd.DataFrame:
    """加载数据."""
    return pd.read_csv(file_path)


def analyze_data(df: pd.DataFrame) -> dict:
    """分析数据."""
    return {
        "shape": df.shape,
        "columns": list(df.columns),
        "describe": df.describe().to_dict(),
        "dtypes": df.dtypes.astype(str).to_dict(),
    }


def main():
    """主函数."""
    print("数据分析项目模板")
    print("使用 pandas 进行数据处理和分析")


if __name__ == "__main__":
    main()
''',
                "requirements.txt": """pandas>=2.0.0
numpy>=1.24.0
matplotlib>=3.7.0
seaborn>=0.12.0
""",
                "README.md": """# 数据分析项目

## 简介
数据分析和可视化项目模板。

## 安装依赖
```bash
pip install -r requirements.txt
```

## 使用
```python
from analysis import load_data, analyze_data

df = load_data("data.csv")
result = analyze_data(df)
print(result)
```
""",
                ".gitignore": """__pycache__/
*.py[cod]
*.csv
*.xlsx
data/
.venv/
""",
                "data/.gitkeep": "",
            },
        },
        {
            "id": "tpl_nodejs_express",
            "name": "Node.js Express 项目",
            "description": "基于 Express.js 的 Node.js Web 服务项目",
            "category": "Node.js",
            "icon": "🟢",
            "tags": ["nodejs", "express", "web", "javascript"],
            "version": "1.0.0",
            "language": "javascript",
            "files": {
                "src/index.js": '''// Express 应用入口
const express = require("express");
const cors = require("cors");

const app = express();
const PORT = process.env.PORT || 3000;

// 中间件
app.use(cors());
app.use(express.json());

// 路由
app.get("/", (req, res) => {
  res.json({ message: "Hello from M9 Dev Workshop!", status: "ok" });
});

app.get("/health", (req, res) => {
  res.json({ status: "healthy" });
});

// 启动服务
app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});

module.exports = app;
''',
                "package.json": """{
  "name": "m9-express-project",
  "version": "1.0.0",
  "description": "Express.js project from M9 Dev Workshop",
  "main": "src/index.js",
  "scripts": {
    "start": "node src/index.js",
    "dev": "nodemon src/index.js"
  },
  "dependencies": {
    "express": "^4.18.0",
    "cors": "^2.8.5"
  },
  "devDependencies": {
    "nodemon": "^3.0.0"
  }
}
""",
                "README.md": """# Node.js Express 项目

## 简介
基于 Express.js 的 Node.js Web 服务项目模板。

## 安装依赖
```bash
npm install
```

## 运行
```bash
npm start
```

## 开发模式
```bash
npm run dev
```
""",
                ".gitignore": """node_modules/
.env
.DS_Store
*.log
""",
            },
        },
        {
            "id": "tpl_react_app",
            "name": "React 前端应用",
            "description": "基于 React 的前端应用项目模板",
            "category": "前端",
            "icon": "⚛️",
            "tags": ["react", "frontend", "javascript"],
            "version": "1.0.0",
            "language": "javascript",
            "files": {
                "src/App.jsx": '''import { useState } from "react";
import "./App.css";

function App() {
  const [count, setCount] = useState(0);

  return (
    <div className="app">
      <h1>云汐 M9 开发者工坊</h1>
      <p>React 项目模板</p>
      <button onClick={() => setCount(count + 1)}>
        点击了 {count} 次
      </button>
    </div>
  );
}

export default App;
''',
                "src/App.css": """.app {
  text-align: center;
  padding: 2rem;
  font-family: system-ui, -apple-system, sans-serif;
}

.app button {
  padding: 0.5rem 1rem;
  font-size: 1rem;
  cursor: pointer;
  border: none;
  border-radius: 4px;
  background: #3b82f6;
  color: white;
}

.app button:hover {
  background: #2563eb;
}
""",
                "src/main.jsx": '''import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
''',
                "index.html": '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>M9 React App</title>
</head>
<body>
  <div id="root"></div>
  <script type="module" src="/src/main.jsx"></script>
</body>
</html>
''',
                "package.json": """{
  "name": "m9-react-app",
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.0.0",
    "vite": "^5.0.0"
  }
}
""",
                "vite.config.js": '''import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
});
''',
                "README.md": """# React 前端应用

## 简介
基于 React + Vite 的前端应用项目模板。

## 安装依赖
```bash
npm install
```

## 开发模式
```bash
npm run dev
```

## 构建生产版本
```bash
npm run build
```
""",
                ".gitignore": """node_modules/
dist/
.env
.DS_Store
*.log
""",
            },
        },
        {
            "id": "tpl_cli_tool",
            "name": "命令行工具",
            "description": "Python 命令行工具项目，使用 argparse 或 click",
            "category": "Python",
            "icon": "💻",
            "tags": ["python", "cli", "工具"],
            "version": "1.0.0",
            "language": "python",
            "files": {
                "cli.py": '''#!/usr/bin/env python3
"""命令行工具."""

import argparse
import sys


def main():
    """主函数."""
    parser = argparse.ArgumentParser(
        description="云汐 M9 命令行工具",
    )
    parser.add_argument(
        "command",
        choices=["hello", "version", "info"],
        help="要执行的命令",
    )
    parser.add_argument(
        "--name",
        default="世界",
        help="名称参数",
    )

    args = parser.parse_args()

    if args.command == "hello":
        print(f"你好, {args.name}!")
    elif args.command == "version":
        print("版本: 1.0.0")
    elif args.command == "info":
        print("云汐 M9 开发者工坊 - 命令行工具模板")

    return 0


if __name__ == "__main__":
    sys.exit(main())
''',
                "requirements.txt": """# 可选依赖
# click>=8.0.0
""",
                "README.md": """# 命令行工具项目

## 简介
Python 命令行工具项目模板。

## 使用
```bash
python cli.py hello --name 云汐
python cli.py version
python cli.py info
```
""",
                ".gitignore": """__pycache__/
*.py[cod]
.venv/
""",
            },
        },
        {
            "id": "tpl_flask_api",
            "name": "Flask API 项目",
            "description": "基于 Flask 的轻量级 Web API 项目",
            "category": "Python",
            "icon": "🌶️",
            "tags": ["python", "flask", "web", "api"],
            "version": "1.0.0",
            "language": "python",
            "files": {
                "app.py": '''#!/usr/bin/env python3
"""Flask 应用."""

from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)


@app.route("/")
def index():
    """根路径."""
    return jsonify({
        "message": "Hello from M9 Dev Workshop!",
        "status": "ok",
    })


@app.route("/health")
def health():
    """健康检查."""
    return jsonify({"status": "healthy"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
''',
                "requirements.txt": """flask>=2.3.0
flask-cors>=4.0.0
""",
                "README.md": """# Flask API 项目

## 简介
基于 Flask 的轻量级 Web API 项目模板。

## 安装依赖
```bash
pip install -r requirements.txt
```

## 运行
```bash
python app.py
```

访问: http://localhost:5000
""",
                ".gitignore": """__pycache__/
*.py[cod]
.env
instance/
.venv/
""",
            },
        },
        {
            "id": "tpl_test_project",
            "name": "测试项目模板",
            "description": "包含 pytest 测试框架的 Python 项目模板",
            "category": "Python",
            "icon": "🧪",
            "tags": ["python", "test", "pytest"],
            "version": "1.0.0",
            "language": "python",
            "files": {
                "src/__init__.py": "",
                "src/calculator.py": '''"""示例计算器模块."""


def add(a: float, b: float) -> float:
    """加法."""
    return a + b


def subtract(a: float, b: float) -> float:
    """减法."""
    return a - b


def multiply(a: float, b: float) -> float:
    """乘法."""
    return a * b


def divide(a: float, b: float) -> float:
    """除法."""
    if b == 0:
        raise ValueError("除数不能为零")
    return a / b
''',
                "tests/__init__.py": "",
                "tests/test_calculator.py": '''"""计算器模块测试."""

import pytest
from src.calculator import add, subtract, multiply, divide


class TestCalculator:
    """计算器测试类."""

    def test_add(self):
        """测试加法."""
        assert add(2, 3) == 5
        assert add(-1, 1) == 0
        assert add(0, 0) == 0

    def test_subtract(self):
        """测试减法."""
        assert subtract(5, 3) == 2
        assert subtract(0, 5) == -5

    def test_multiply(self):
        """测试乘法."""
        assert multiply(3, 4) == 12
        assert multiply(-2, 3) == -6
        assert multiply(0, 5) == 0

    def test_divide(self):
        """测试除法."""
        assert divide(10, 2) == 5
        assert divide(9, 3) == 3

    def test_divide_by_zero(self):
        """测试除以零."""
        with pytest.raises(ValueError, match="除数不能为零"):
            divide(10, 0)
''',
                "requirements.txt": """pytest>=7.0.0
pytest-cov>=4.0.0
""",
                "README.md": """# 测试项目模板

## 简介
包含 pytest 测试框架的 Python 项目模板。

## 安装依赖
```bash
pip install -r requirements.txt
```

## 运行测试
```bash
pytest
```

## 运行测试并生成覆盖率报告
```bash
pytest --cov=src --cov-report=html
```
""",
                ".gitignore": """__pycache__/
*.py[cod]
.pytest_cache/
htmlcov/
.coverage
.venv/
""",
            },
        },
    ]

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def list_templates(
        self,
        category: Optional[str] = None,
        search: Optional[str] = None,
        language: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取模板列表.

        Args:
            category: 分类筛选
            search: 搜索关键词
            language: 语言筛选

        Returns:
            模板列表
        """
        all_templates = self._get_all_templates()
        result = []

        for tpl in all_templates:
            # 分类筛选
            if category and tpl.get("category") != category:
                continue

            # 语言筛选
            if language and tpl.get("language") != language:
                continue

            # 搜索
            if search:
                keyword = search.lower()
                search_text = (
                    tpl.get("name", "") + " " +
                    tpl.get("description", "") + " " +
                    " ".join(tpl.get("tags", []))
                ).lower()
                if keyword not in search_text:
                    continue

            # 不返回 files 字段（节省带宽）
            tpl_info = {k: v for k, v in tpl.items() if k != "files"}
            result.append(tpl_info)

        return result

    def get_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        """获取模板详情.

        Args:
            template_id: 模板 ID

        Returns:
            模板详情（含 files 字段），不存在返回 None
        """
        all_templates = self._get_all_templates()
        for tpl in all_templates:
            if tpl["id"] == template_id:
                return tpl
        return None

    def create_project_from_template(
        self,
        template_id: str,
        project_name: str,
        project_path: Optional[str] = None,
        description: str = "",
    ) -> Dict[str, Any]:
        """从模板创建项目.

        Args:
            template_id: 模板 ID
            project_name: 项目名称
            project_path: 项目路径（默认在 workspace_root 下）
            description: 项目描述

        Returns:
            创建结果
        """
        template = self.get_template(template_id)
        if not template:
            return {
                "success": False,
                "error": f"模板不存在: {template_id}",
            }

        # 确定项目路径
        if not project_path:
            project_path = os.path.join(str(self.settings.workspace_root), project_name)

        # 路径安全校验
        try:
            assert_path_safe(str(self.settings.workspace_root), project_path, "create_from_template")
        except PathSecurityError as e:
            return {
                "success": False,
                "error": f"路径不安全: {str(e)}",
            }

        # 检查路径是否已存在
        if os.path.exists(project_path):
            return {
                "success": False,
                "error": f"项目路径已存在: {project_path}",
            }

        try:
            # 创建项目目录
            os.makedirs(project_path, exist_ok=True)

            # 写入模板文件
            files = template.get("files", {})
            created_files = []
            for file_path, content in files.items():
                full_path = os.path.join(project_path, file_path)
                # 确保子目录存在
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                # 写入文件内容
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(content)
                created_files.append(file_path)

            return {
                "success": True,
                "project_name": project_name,
                "project_path": project_path,
                "template_id": template_id,
                "template_name": template.get("name", ""),
                "created_files": created_files,
                "file_count": len(created_files),
            }

        except Exception as e:
            # 出错时清理
            if os.path.exists(project_path):
                try:
                    shutil.rmtree(project_path)
                except Exception:
                    pass
            return {
                "success": False,
                "error": f"创建项目失败: {str(e)}",
            }

    def get_categories(self) -> List[Dict[str, Any]]:
        """获取模板分类列表.

        Returns:
            分类列表（含数量统计）
        """
        all_templates = self._get_all_templates()
        categories: Dict[str, int] = {}

        for tpl in all_templates:
            cat = tpl.get("category", "未分类")
            categories[cat] = categories.get(cat, 0) + 1

        return [
            {"name": cat, "count": count}
            for cat, count in sorted(categories.items())
        ]

    def save_custom_template(
        self,
        source_path: str,
        name: str,
        description: str = "",
        category: str = "自定义",
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """从现有项目保存为自定义模板.

        Args:
            source_path: 源项目路径
            name: 模板名称
            description: 描述
            category: 分类
            tags: 标签列表

        Returns:
            保存结果
        """
        try:
            assert_path_safe(str(self.settings.workspace_root), source_path, "save_template")
        except PathSecurityError as e:
            return {
                "success": False,
                "error": f"路径不安全: {str(e)}",
            }

        if not os.path.isdir(source_path):
            return {
                "success": False,
                "error": f"源路径不存在或不是目录: {source_path}",
            }

        # 收集文件内容
        files: Dict[str, str] = {}
        ignore_dirs = {"__pycache__", "node_modules", ".git", ".venv", "venv", "dist", "build"}
        ignore_files = {".DS_Store", "*.pyc"}

        for root, dirs, filenames in os.walk(source_path):
            # 过滤掉忽略的目录
            dirs[:] = [d for d in dirs if d not in ignore_dirs]

            for filename in filenames:
                if filename.startswith(".") and filename != ".gitignore":
                    continue
                rel_path = os.path.relpath(os.path.join(root, filename), source_path)
                try:
                    with open(os.path.join(root, filename), "r", encoding="utf-8") as f:
                        files[rel_path] = f.read()
                except (UnicodeDecodeError, OSError):
                    # 跳过二进制文件或无法读取的文件
                    continue

        template_id = f"custom_{uuid.uuid4().hex[:8]}"
        template = {
            "id": template_id,
            "name": name,
            "description": description,
            "category": category,
            "icon": "📦",
            "tags": tags or [],
            "version": "1.0.0",
            "language": "python",
            "is_custom": True,
            "files": files,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "source_path": source_path,
        }

        # 保存自定义模板
        custom_templates = self._load_custom_templates()
        custom_templates.append(template)
        self._save_custom_templates(custom_templates)

        return {
            "success": True,
            "template_id": template_id,
            "name": name,
            "file_count": len(files),
        }

    def delete_custom_template(self, template_id: str) -> bool:
        """删除自定义模板.

        Args:
            template_id: 模板 ID

        Returns:
            是否成功删除
        """
        custom_templates = self._load_custom_templates()
        original_len = len(custom_templates)
        custom_templates = [t for t in custom_templates if t["id"] != template_id]
        if len(custom_templates) == original_len:
            return False
        self._save_custom_templates(custom_templates)
        return True

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _get_all_templates(self) -> List[Dict[str, Any]]:
        """获取所有模板（内置 + 自定义）."""
        all_templates = list(self.BUILTIN_TEMPLATES)
        custom_templates = self._load_custom_templates()
        all_templates.extend(custom_templates)
        return all_templates

    def _load_custom_templates(self) -> List[Dict[str, Any]]:
        """加载自定义模板."""
        if not self._custom_templates_file.exists():
            return []
        try:
            with open(self._custom_templates_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

    def _save_custom_templates(self, templates: List[Dict[str, Any]]) -> None:
        """保存自定义模板."""
        self._custom_templates_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._custom_templates_file, "w", encoding="utf-8") as f:
            json.dump(templates, f, ensure_ascii=False, indent=2)


# 全局单例
_template_manager: Optional[ProjectTemplateManager] = None


def get_template_manager() -> ProjectTemplateManager:
    """获取模板管理器单例."""
    global _template_manager
    if _template_manager is None:
        _template_manager = ProjectTemplateManager()
    return _template_manager
