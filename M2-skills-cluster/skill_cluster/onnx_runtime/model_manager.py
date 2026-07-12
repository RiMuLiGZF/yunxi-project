"""
ONNX 模型管理器

负责模型的下载、校验、版本管理和热更新。
支持从本地目录或远程地址加载模型。
"""

from __future__ import annotations

import os
import json
import hashlib
import shutil
import time
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

import structlog

from .engine import ONNXRuntimeEngine, ModelInfo, get_engine

logger = structlog.get_logger(__name__)


@dataclass
class ModelRegistryEntry:
    """模型注册条目"""
    name: str = ""
    version: str = "1.0.0"
    task_type: str = ""  # translation / classification / embedding / qa
    description: str = ""
    file_name: str = ""
    file_size: int = 0
    md5_hash: str = ""
    source: str = ""  # local / remote
    url: str = ""
    config: Dict[str, Any] = field(default_factory=dict)
    loaded: bool = False


class ModelManager:
    """ONNX 模型管理器

    管理本地 ONNX 模型的注册、加载、版本控制。
    """

    _instance = None
    _lock = None  # 延迟初始化

    @classmethod
    def get_instance(cls) -> "ModelManager":
        """获取单例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._registry: Dict[str, ModelRegistryEntry] = {}
        self._models_dir: str = ""
        self._registry_path: str = ""
        self._engine: Optional[ONNXRuntimeEngine] = None
        self._initialized: bool = False

    def initialize(self, config: Optional[Dict[str, Any]] = None) -> bool:
        """初始化模型管理器

        Args:
            config: 配置字典
                - models_dir: 模型存储目录
                - registry_file: 注册表文件路径
                - auto_load: 是否自动加载注册的模型
        """
        if self._initialized:
            return True

        config = config or {}
        self._models_dir = config.get(
            "models_dir", os.path.expanduser("~/.yunxi/models/onnx")
        )
        self._registry_path = config.get(
            "registry_file", os.path.join(self._models_dir, "registry.json")
        )

        os.makedirs(self._models_dir, exist_ok=True)

        # 初始化引擎
        self._engine = get_engine()
        self._engine.initialize(config)

        # 加载注册表
        self._load_registry()

        # 自动加载
        if config.get("auto_load", False):
            self._auto_load_models()

        self._initialized = True
        logger.info(f"ONNX 模型管理器初始化完成: models_dir={self._models_dir}")
        return True

    # ============================================================
    # 注册表管理
    # ============================================================

    def _load_registry(self):
        """加载模型注册表"""
        if not os.path.exists(self._registry_path):
            self._registry = {}
            return

        try:
            with open(self._registry_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._registry = {}
            for name, entry_data in data.items():
                entry = ModelRegistryEntry(**entry_data)
                self._registry[name] = entry

            logger.info(f"已加载 {len(self._registry)} 个模型注册条目")
        except Exception as e:
            logger.error(f"加载模型注册表失败: {e}")
            self._registry = {}

    def _save_registry(self):
        """保存模型注册表"""
        try:
            data = {}
            for name, entry in self._registry.items():
                data[name] = {
                    "name": entry.name,
                    "version": entry.version,
                    "task_type": entry.task_type,
                    "description": entry.description,
                    "file_name": entry.file_name,
                    "file_size": entry.file_size,
                    "md5_hash": entry.md5_hash,
                    "source": entry.source,
                    "url": entry.url,
                    "config": entry.config,
                    "loaded": entry.loaded,
                }

            with open(self._registry_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存模型注册表失败: {e}")

    def register_model(
        self,
        name: str,
        file_path: str,
        task_type: str = "",
        version: str = "1.0.0",
        description: str = "",
        config: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """注册模型

        Args:
            name: 模型名称
            file_path: ONNX 文件路径
            task_type: 任务类型
            version: 版本号
            description: 描述
            config: 扩展配置

        Returns:
            是否注册成功
        """
        if not os.path.exists(file_path):
            logger.error(f"模型文件不存在: {file_path}")
            return False

        # 计算文件大小和 MD5
        file_size = os.path.getsize(file_path)
        md5_hash = self._compute_md5(file_path)

        # 复制到模型目录
        file_name = f"{name}.onnx"
        dest_path = os.path.join(self._models_dir, file_name)

        try:
            shutil.copy2(file_path, dest_path)
        except Exception as e:
            logger.error(f"复制模型文件失败: {e}")
            return False

        entry = ModelRegistryEntry(
            name=name,
            version=version,
            task_type=task_type,
            description=description,
            file_name=file_name,
            file_size=file_size,
            md5_hash=md5_hash,
            source="local",
            config=config or {},
        )

        self._registry[name] = entry
        self._save_registry()

        logger.info(f"模型注册成功: {name} v{version} ({file_size/1024/1024:.2f} MB)")
        return True

    def unregister_model(self, name: str) -> bool:
        """注销模型

        Args:
            name: 模型名称

        Returns:
            是否成功
        """
        if name not in self._registry:
            return False

        # 先卸载
        if self._engine and self._engine.is_model_loaded(name):
            self._engine.unload_model(name)

        # 删除文件
        entry = self._registry[name]
        file_path = os.path.join(self._models_dir, entry.file_name)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                logger.warning(f"删除模型文件失败: {e}")

        del self._registry[name]
        self._save_registry()

        logger.info(f"模型已注销: {name}")
        return True

    def list_models(self) -> List[Dict[str, Any]]:
        """列出所有注册模型"""
        result = []
        for name, entry in self._registry.items():
            loaded = self._engine.is_model_loaded(name) if self._engine else False
            result.append({
                "name": entry.name,
                "version": entry.version,
                "task_type": entry.task_type,
                "description": entry.description,
                "file_size_mb": round(entry.file_size / 1024 / 1024, 2),
                "source": entry.source,
                "loaded": loaded,
            })
        return result

    # ============================================================
    # 模型加载/卸载
    # ============================================================

    def load_model(self, name: str) -> Optional[ModelInfo]:
        """加载注册的模型

        Args:
            name: 模型名称

        Returns:
            模型信息，失败返回 None
        """
        if name not in self._registry:
            logger.error(f"模型未注册: {name}")
            return None

        entry = self._registry[name]
        model_path = os.path.join(self._models_dir, entry.file_name)

        if not os.path.exists(model_path):
            logger.error(f"模型文件不存在: {model_path}")
            return None

        try:
            info = self._engine.load_model(
                name, model_path, task_type=entry.task_type
            )
            entry.loaded = True
            return info
        except Exception as e:
            logger.error(f"加载模型失败: {name}, error: {e}")
            return None

    def unload_model(self, name: str) -> bool:
        """卸载模型"""
        if self._engine:
            result = self._engine.unload_model(name)
            if name in self._registry:
                self._registry[name].loaded = False
            return result
        return False

    def _auto_load_models(self):
        """自动加载所有注册的模型"""
        for name in self._registry:
            try:
                self.load_model(name)
            except Exception:
                pass

    # ============================================================
    # 工具方法
    # ============================================================

    @staticmethod
    def _compute_md5(file_path: str, chunk_size: int = 8192) -> str:
        """计算文件 MD5"""
        md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                md5.update(chunk)
        return md5.hexdigest()

    def get_stats(self) -> Dict[str, Any]:
        """获取管理器统计信息"""
        registered = len(self._registry)
        loaded = sum(
            1 for e in self._registry.values()
            if self._engine and self._engine.is_model_loaded(e.name)
        )
        total_size = sum(e.file_size for e in self._registry.values())

        return {
            "models_dir": self._models_dir,
            "registered_count": registered,
            "loaded_count": loaded,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
            "models": self.list_models(),
        }


def get_model_manager() -> ModelManager:
    """获取模型管理器单例"""
    return ModelManager.get_instance()
