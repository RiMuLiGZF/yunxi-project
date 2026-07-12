"""
M2 ONNX Runtime 推理引擎

提供本地模型的 ONNX Runtime 推理支持，支持 CPU/GPU 加速。
适用于翻译、文本分类、嵌入、摘要等 NLP 技能的本地推理。
"""

from .engine import ONNXRuntimeEngine, get_engine
from .model_manager import ModelManager, get_model_manager

__all__ = [
    "ONNXRuntimeEngine",
    "get_engine",
    "ModelManager",
    "get_model_manager",
]
