"""
ONNX Runtime 推理引擎

支持 CPU 和 GPU（CUDA）两种执行模式，自动检测并选择最优后端。
提供模型加载、推理、Session 池化等能力。
"""

from __future__ import annotations

import os
import time
import threading
from typing import Any, Dict, List, Optional, Tuple, Union
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class InferenceResult:
    """推理结果"""
    outputs: Dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    model_name: str = ""
    backend: str = "cpu"  # cpu / cuda / tensorrt
    success: bool = True
    error_message: str = ""


@dataclass
class ModelInfo:
    """模型信息"""
    name: str = ""
    path: str = ""
    task_type: str = ""  # translation / classification / embedding / qa / summarization
    backend: str = "cpu"
    input_names: List[str] = field(default_factory=list)
    output_names: List[str] = field(default_factory=list)
    loaded: bool = False
    load_time: float = 0.0
    inference_count: int = 0
    total_latency_ms: float = 0.0


class ONNXRuntimeEngine:
    """ONNX Runtime 推理引擎

    单例模式，管理所有 ONNX 模型的加载和推理。
    自动检测 GPU 可用性，优先使用 GPU 加速。
    """

    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "ONNXRuntimeEngine":
        """获取单例"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._sessions: Dict[str, Any] = {}  # model_name -> InferenceSession
        self._model_info: Dict[str, ModelInfo] = {}
        self._session_lock = threading.Lock()
        self._available_backends: List[str] = []
        self._preferred_backend: str = "cpu"
        self._gpu_available: bool = False
        self._gpu_device_id: int = 0
        self._gpu_memory_limit_gb: float = 4.0
        self._initialized: bool = False
        self._models_dir: str = ""

    # ============================================================
    # 初始化与后端检测
    # ============================================================

    def initialize(self, config: Optional[Dict[str, Any]] = None) -> bool:
        """初始化引擎，检测可用后端

        Args:
            config: 配置字典
                - models_dir: 模型目录
                - preferred_backend: 首选后端 (cpu/cuda/auto)
                - gpu_device_id: GPU 设备 ID
                - gpu_memory_limit_gb: GPU 显存限制(GB)

        Returns:
            是否初始化成功
        """
        if self._initialized:
            return True

        config = config or {}
        self._models_dir = config.get("models_dir", os.path.expanduser("~/.yunxi/models/onnx"))
        self._preferred_backend = config.get("preferred_backend", "auto")
        self._gpu_device_id = config.get("gpu_device_id", 0)
        self._gpu_memory_limit_gb = config.get("gpu_memory_limit_gb", 4.0)

        # 检测可用后端
        self._detect_backends()

        # 确定实际使用的后端
        if self._preferred_backend == "auto":
            if "cuda" in self._available_backends:
                self._preferred_backend = "cuda"
                self._gpu_available = True
            else:
                self._preferred_backend = "cpu"
        elif self._preferred_backend == "cuda":
            if "cuda" not in self._available_backends:
                logger.warning("CUDA 后端不可用，降级到 CPU")
                self._preferred_backend = "cpu"
            else:
                self._gpu_available = True

        os.makedirs(self._models_dir, exist_ok=True)
        self._initialized = True

        logger.info(
            f"ONNX Runtime 引擎初始化完成: "
            f"backend={self._preferred_backend}, "
            f"available={self._available_backends}, "
            f"models_dir={self._models_dir}"
        )
        return True

    def _detect_backends(self):
        """检测可用的 ONNX Runtime 后端"""
        self._available_backends = ["cpu"]  # CPU 总是可用（如果 onnxruntime 安装了）

        try:
            import onnxruntime as ort

            # 获取所有可用的执行提供程序
            providers = ort.get_available_providers()

            if "CUDAExecutionProvider" in providers:
                self._available_backends.append("cuda")

            if "TensorrtExecutionProvider" in providers:
                self._available_backends.append("tensorrt")

            logger.debug(f"ONNX Runtime 可用后端: {providers}")

        except ImportError:
            logger.warning("onnxruntime 未安装，ONNX 推理功能不可用")
            self._available_backends = []

    # ============================================================
    # 模型加载
    # ============================================================

    def load_model(
        self,
        model_name: str,
        model_path: Optional[str] = None,
        task_type: str = "",
        backend: Optional[str] = None,
    ) -> ModelInfo:
        """加载 ONNX 模型

        Args:
            model_name: 模型名称
            model_path: ONNX 模型文件路径，默认从 models_dir 查找
            task_type: 任务类型
            backend: 指定后端，默认使用 preferred_backend

        Returns:
            模型信息
        """
        if not self._initialized:
            self.initialize()

        # 如果已加载，直接返回
        if model_name in self._sessions:
            return self._model_info[model_name]

        with self._session_lock:
            # 双重检查
            if model_name in self._sessions:
                return self._model_info[model_name]

            # 确定模型路径
            if not model_path:
                model_path = os.path.join(self._models_dir, f"{model_name}.onnx")

            if not os.path.exists(model_path):
                raise FileNotFoundError(f"ONNX 模型文件不存在: {model_path}")

            # 确定后端
            use_backend = backend or self._preferred_backend
            if use_backend not in self._available_backends and self._available_backends:
                use_backend = self._available_backends[0]

            try:
                import onnxruntime as ort

                # 配置 Session 选项
                sess_options = ort.SessionOptions()
                sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                sess_options.intra_op_num_threads = os.cpu_count() or 4

                # 选择执行提供程序
                providers = []
                if use_backend == "cuda":
                    providers.append(("CUDAExecutionProvider", {
                        "device_id": self._gpu_device_id,
                        "gpu_mem_limit": int(self._gpu_memory_limit_gb * 1024 * 1024 * 1024),
                    }))
                elif use_backend == "tensorrt":
                    providers.append(("TensorrtExecutionProvider", {
                        "device_id": self._gpu_device_id,
                    }))
                    providers.append("CUDAExecutionProvider")

                providers.append("CPUExecutionProvider")  # CPU 作为 fallback

                start = time.time()
                session = ort.InferenceSession(
                    model_path,
                    sess_options=sess_options,
                    providers=providers,
                )
                load_time = time.time() - start

                # 获取输入输出信息
                input_names = [inp.name for inp in session.get_inputs()]
                output_names = [out.name for out in session.get_outputs()]

                # 实际使用的后端
                actual_backend = use_backend
                if session.get_providers():
                    first_provider = session.get_providers()[0]
                    if "CUDA" in first_provider:
                        actual_backend = "cuda"
                    elif "Tensorrt" in first_provider:
                        actual_backend = "tensorrt"
                    else:
                        actual_backend = "cpu"

                info = ModelInfo(
                    name=model_name,
                    path=model_path,
                    task_type=task_type,
                    backend=actual_backend,
                    input_names=input_names,
                    output_names=output_names,
                    loaded=True,
                    load_time=load_time,
                )

                self._sessions[model_name] = session
                self._model_info[model_name] = info

                logger.info(
                    f"ONNX 模型加载成功: {model_name} "
                    f"(backend={actual_backend}, load_time={load_time:.2f}s, "
                    f"inputs={input_names}, outputs={output_names})"
                )

                return info

            except ImportError:
                raise RuntimeError("onnxruntime 未安装，无法加载模型")
            except Exception as e:
                logger.error(f"ONNX 模型加载失败: {model_name}, error: {e}")
                raise

    def unload_model(self, model_name: str) -> bool:
        """卸载模型

        Args:
            model_name: 模型名称

        Returns:
            是否成功卸载
        """
        with self._session_lock:
            if model_name in self._sessions:
                del self._sessions[model_name]
                del self._model_info[model_name]
                logger.info(f"ONNX 模型已卸载: {model_name}")
                return True
            return False

    def is_model_loaded(self, model_name: str) -> bool:
        """检查模型是否已加载"""
        return model_name in self._sessions

    # ============================================================
    # 推理
    # ============================================================

    def run(
        self,
        model_name: str,
        inputs: Dict[str, Any],
        output_names: Optional[List[str]] = None,
    ) -> InferenceResult:
        """执行推理

        Args:
            model_name: 模型名称
            inputs: 输入字典 {input_name: numpy_array}
            output_names: 指定输出名称，默认全部输出

        Returns:
            推理结果
        """
        start = time.time()

        try:
            session = self._sessions.get(model_name)
            if session is None:
                # 尝试自动加载
                self.load_model(model_name)
                session = self._sessions.get(model_name)
                if session is None:
                    raise RuntimeError(f"模型未加载: {model_name}")

            info = self._model_info[model_name]

            # 执行推理
            outputs = session.run(output_names, inputs)

            # 整理输出
            result_outputs = {}
            if output_names:
                for name, output in zip(output_names, outputs):
                    result_outputs[name] = output
            else:
                for out_info, output in zip(session.get_outputs(), outputs):
                    result_outputs[out_info.name] = output

            latency = (time.time() - start) * 1000

            # 更新统计
            info.inference_count += 1
            info.total_latency_ms += latency

            return InferenceResult(
                outputs=result_outputs,
                latency_ms=round(latency, 2),
                model_name=model_name,
                backend=info.backend,
                success=True,
            )

        except Exception as e:
            latency = (time.time() - start) * 1000
            logger.error(f"ONNX 推理失败: {model_name}, error: {e}")
            return InferenceResult(
                latency_ms=round(latency, 2),
                model_name=model_name,
                backend=self._preferred_backend,
                success=False,
                error_message=str(e),
            )

    async def run_async(
        self,
        model_name: str,
        inputs: Dict[str, Any],
        output_names: Optional[List[str]] = None,
    ) -> InferenceResult:
        """异步推理（在线程池中执行）"""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self.run(model_name, inputs, output_names)
        )

    # ============================================================
    # 状态与统计
    # ============================================================

    def get_available_backends(self) -> List[str]:
        """获取可用后端列表"""
        if not self._initialized:
            self.initialize()
        return self._available_backends.copy()

    def get_preferred_backend(self) -> str:
        """获取当前首选后端"""
        return self._preferred_backend

    def is_gpu_available(self) -> bool:
        """GPU 是否可用"""
        return self._gpu_available

    def list_models(self) -> List[ModelInfo]:
        """列出所有已加载模型"""
        return list(self._model_info.values())

    def get_model_info(self, model_name: str) -> Optional[ModelInfo]:
        """获取模型信息"""
        return self._model_info.get(model_name)

    def get_stats(self) -> Dict[str, Any]:
        """获取引擎统计信息"""
        models = self.list_models()
        total_inferences = sum(m.inference_count for m in models)
        avg_latency = 0.0
        if total_inferences > 0:
            total_latency = sum(m.total_latency_ms for m in models)
            avg_latency = total_latency / total_inferences

        return {
            "initialized": self._initialized,
            "preferred_backend": self._preferred_backend,
            "available_backends": self._available_backends,
            "gpu_available": self._gpu_available,
            "gpu_device_id": self._gpu_device_id if self._gpu_available else None,
            "models_dir": self._models_dir,
            "loaded_models": len(models),
            "total_inferences": total_inferences,
            "avg_latency_ms": round(avg_latency, 2),
            "models": [
                {
                    "name": m.name,
                    "task_type": m.task_type,
                    "backend": m.backend,
                    "inference_count": m.inference_count,
                    "avg_latency_ms": round(
                        m.total_latency_ms / m.inference_count, 2
                    ) if m.inference_count > 0 else 0,
                    "load_time": m.load_time,
                }
                for m in models
            ],
        }


def get_engine() -> ONNXRuntimeEngine:
    """获取 ONNX Runtime 引擎单例"""
    return ONNXRuntimeEngine.get_instance()
