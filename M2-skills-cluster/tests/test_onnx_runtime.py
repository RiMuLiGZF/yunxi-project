"""
M2 ONNX Runtime GPU 加速测试（直接导入，绕过 __init__.py 语法问题）
"""
import sys
import os
import tempfile
import pytest

# 直接添加 skill_cluster 到 path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skill_cluster"))


class TestONNXRuntimeEngine:
    """ONNX Runtime 引擎测试"""

    def test_engine_import(self):
        """引擎模块可导入"""
        from onnx_runtime.engine import ONNXRuntimeEngine
        assert ONNXRuntimeEngine is not None

    def test_singleton(self):
        """单例模式"""
        from onnx_runtime.engine import ONNXRuntimeEngine, get_engine
        e1 = get_engine()
        e2 = ONNXRuntimeEngine.get_instance()
        assert e1 is e2

    def test_initialize_default(self):
        """默认初始化状态"""
        from onnx_runtime.engine import ONNXRuntimeEngine
        engine = ONNXRuntimeEngine()
        stats = engine.get_stats()
        assert "initialized" in stats
        assert stats["initialized"] is False

    def test_initialize_cpu(self):
        """CPU 模式初始化"""
        from onnx_runtime.engine import ONNXRuntimeEngine
        engine = ONNXRuntimeEngine()
        result = engine.initialize({
            "models_dir": tempfile.mkdtemp(),
            "preferred_backend": "cpu",
        })
        assert result is True
        assert engine.get_preferred_backend() == "cpu"

    def test_detect_backends(self):
        """后端检测"""
        from onnx_runtime.engine import ONNXRuntimeEngine
        engine = ONNXRuntimeEngine()
        engine.initialize({
            "models_dir": tempfile.mkdtemp(),
            "preferred_backend": "auto",
        })
        backends = engine.get_available_backends()
        assert isinstance(backends, list)

    def test_is_gpu_available(self):
        """GPU 可用性检测"""
        from onnx_runtime.engine import ONNXRuntimeEngine
        engine = ONNXRuntimeEngine()
        engine.initialize({
            "models_dir": tempfile.mkdtemp(),
        })
        result = engine.is_gpu_available()
        assert isinstance(result, bool)

    def test_list_models_empty(self):
        """空模型列表"""
        from onnx_runtime.engine import ONNXRuntimeEngine
        engine = ONNXRuntimeEngine()
        engine.initialize({
            "models_dir": tempfile.mkdtemp(),
        })
        models = engine.list_models()
        assert isinstance(models, list)
        assert len(models) == 0

    def test_get_stats(self):
        """获取统计信息"""
        from onnx_runtime.engine import ONNXRuntimeEngine
        engine = ONNXRuntimeEngine()
        engine.initialize({
            "models_dir": tempfile.mkdtemp(),
            "preferred_backend": "cpu",
        })
        stats = engine.get_stats()
        assert "initialized" in stats
        assert "preferred_backend" in stats
        assert "available_backends" in stats
        assert "gpu_available" in stats
        assert "loaded_models" in stats
        assert "total_inferences" in stats
        assert "models" in stats

    def test_inference_result_model(self):
        """InferenceResult 数据类"""
        from onnx_runtime.engine import InferenceResult
        result = InferenceResult(
            outputs={"output": [1, 2, 3]},
            latency_ms=12.5,
            model_name="test",
            backend="cpu",
            success=True,
        )
        assert result.success is True
        assert result.model_name == "test"
        assert result.latency_ms == 12.5
        assert "output" in result.outputs

    def test_model_info_model(self):
        """ModelInfo 数据类"""
        from onnx_runtime.engine import ModelInfo
        info = ModelInfo(
            name="test-model",
            path="/tmp/test.onnx",
            task_type="translation",
            backend="cpu",
            input_names=["input_ids"],
            output_names=["logits"],
            loaded=True,
            load_time=0.5,
        )
        assert info.name == "test-model"
        assert info.task_type == "translation"
        assert len(info.input_names) == 1

    def test_model_not_found(self):
        """加载不存在的模型抛出异常"""
        from onnx_runtime.engine import ONNXRuntimeEngine
        engine = ONNXRuntimeEngine()
        engine.initialize({
            "models_dir": tempfile.mkdtemp(),
            "preferred_backend": "cpu",
        })
        with pytest.raises((FileNotFoundError, RuntimeError)):
            engine.load_model("nonexistent_model")


class TestModelManager:
    """模型管理器测试"""

    def test_manager_import(self):
        """管理器模块可导入"""
        from onnx_runtime.model_manager import ModelManager
        assert ModelManager is not None

    def test_singleton(self):
        """单例模式"""
        from onnx_runtime.model_manager import ModelManager, get_model_manager
        m1 = get_model_manager()
        m2 = ModelManager.get_instance()
        assert m1 is m2

    def test_initialize(self):
        """初始化"""
        from onnx_runtime.model_manager import ModelManager
        mgr = ModelManager()
        tmpdir = tempfile.mkdtemp()
        result = mgr.initialize({
            "models_dir": tmpdir,
            "auto_load": False,
        })
        assert result is True

    def test_list_models_empty(self):
        """空模型列表"""
        from onnx_runtime.model_manager import ModelManager
        mgr = ModelManager()
        tmpdir = tempfile.mkdtemp()
        mgr.initialize({
            "models_dir": tmpdir,
            "auto_load": False,
        })
        models = mgr.list_models()
        assert isinstance(models, list)
        assert len(models) == 0

    def test_register_invalid_model(self):
        """注册不存在的模型文件"""
        from onnx_runtime.model_manager import ModelManager
        mgr = ModelManager()
        tmpdir = tempfile.mkdtemp()
        mgr.initialize({
            "models_dir": tmpdir,
            "auto_load": False,
        })
        result = mgr.register_model(
            name="test",
            file_path="/nonexistent/path/model.onnx",
            task_type="translation",
        )
        assert result is False

    def test_unregister_nonexistent(self):
        """注销不存在的模型"""
        from onnx_runtime.model_manager import ModelManager
        mgr = ModelManager()
        tmpdir = tempfile.mkdtemp()
        mgr.initialize({
            "models_dir": tmpdir,
            "auto_load": False,
        })
        result = mgr.unregister_model("nonexistent")
        assert result is False

    def test_get_stats(self):
        """获取统计信息"""
        from onnx_runtime.model_manager import ModelManager
        mgr = ModelManager()
        tmpdir = tempfile.mkdtemp()
        mgr.initialize({
            "models_dir": tmpdir,
            "auto_load": False,
        })
        stats = mgr.get_stats()
        assert "registered_count" in stats
        assert "loaded_count" in stats
        assert "total_size_mb" in stats
        assert stats["registered_count"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
