"""
manifest_generator 单元测试
"""

import json
import os
import sys
import tempfile
import shutil
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from manifest_generator import (
    create_dialog,
    add_artifact_to_dialog,
    remove_artifact_from_dialog,
    load_manifest,
    save_manifest,
    list_dialogs,
    get_dialog_summary,
    get_dialog_dir,
    get_manifest_path,
)


class TestCreateDialog(TestCase):
    """测试创建对话"""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.artifacts_dir = Path(self.test_dir) / "artifacts"
        (self.artifacts_dir / "by-dialog").mkdir(parents=True)

        import manifest_generator
        self._original_root = manifest_generator.get_artifacts_root

        def mock_root():
            return self.artifacts_dir

        manifest_generator.get_artifacts_root = mock_root

    def tearDown(self):
        import manifest_generator
        manifest_generator.get_artifacts_root = self._original_root
        shutil.rmtree(self.test_dir)

    def test_create_dialog(self):
        manifest = create_dialog("dialog-001", "测试对话", "这是一个测试对话")
        self.assertEqual(manifest["dialog_id"], "dialog-001")
        self.assertEqual(manifest["dialog_name"], "测试对话")
        self.assertEqual(manifest["artifact_count"], 0)
        self.assertTrue("created_at" in manifest)

        # 检查目录和文件是否创建
        manifest_path = self.artifacts_dir / "by-dialog" / "dialog-001" / "manifest.json"
        self.assertTrue(manifest_path.exists())

    def test_create_duplicate_dialog_raises(self):
        create_dialog("dialog-001", "测试对话")
        with self.assertRaises(ValueError):
            create_dialog("dialog-001", "重复对话")


class TestAddArtifact(TestCase):
    """测试添加产物到对话"""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.artifacts_dir = Path(self.test_dir) / "artifacts"
        (self.artifacts_dir / "by-dialog").mkdir(parents=True)

        import manifest_generator
        self._original_root = manifest_generator.get_artifacts_root

        def mock_root():
            return self.artifacts_dir

        manifest_generator.get_artifacts_root = mock_root

        create_dialog("dialog-001", "测试对话")

    def tearDown(self):
        import manifest_generator
        manifest_generator.get_artifacts_root = self._original_root
        shutil.rmtree(self.test_dir)

    def test_add_single_artifact(self):
        manifest = add_artifact_to_dialog(
            dialog_id="dialog-001",
            artifact_id="artifact-001",
            name="测试文档",
            artifact_type="doc",
            module="M1",
            path="by-module/M1/test.md",
            description="测试描述",
            tags=["M1", "doc"],
        )
        self.assertEqual(manifest["artifact_count"], 1)
        self.assertEqual(len(manifest["artifacts"]), 1)
        self.assertIn("M1", manifest["modules"])

    def test_add_multiple_artifacts(self):
        add_artifact_to_dialog("dialog-001", "artifact-001", "文档1", "doc", "M1", "path1.md")
        manifest = add_artifact_to_dialog("dialog-001", "artifact-002", "文档2", "report", "M2", "path2.md")
        self.assertEqual(manifest["artifact_count"], 2)
        self.assertIn("M1", manifest["modules"])
        self.assertIn("M2", manifest["modules"])

    def test_add_existing_artifact_updates(self):
        add_artifact_to_dialog("dialog-001", "artifact-001", "旧名称", "doc", "M1", "path.md")
        manifest = add_artifact_to_dialog("dialog-001", "artifact-001", "新名称", "doc", "M1", "path.md")
        self.assertEqual(manifest["artifact_count"], 1)
        self.assertEqual(manifest["artifacts"][0]["name"], "新名称")

    def test_add_to_nonexistent_dialog_creates_it(self):
        manifest = add_artifact_to_dialog(
            dialog_id="dialog-099",
            artifact_id="artifact-001",
            name="测试",
            artifact_type="doc",
            module="M3",
            path="test.md",
            dialog_name="新对话",
        )
        self.assertEqual(manifest["dialog_name"], "新对话")
        self.assertEqual(manifest["artifact_count"], 1)


class TestRemoveArtifact(TestCase):
    """测试移除产物"""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.artifacts_dir = Path(self.test_dir) / "artifacts"
        (self.artifacts_dir / "by-dialog").mkdir(parents=True)

        import manifest_generator
        self._original_root = manifest_generator.get_artifacts_root

        def mock_root():
            return self.artifacts_dir

        manifest_generator.get_artifacts_root = mock_root

        create_dialog("dialog-001", "测试对话")
        add_artifact_to_dialog("dialog-001", "artifact-001", "文档1", "doc", "M1", "path1.md")
        add_artifact_to_dialog("dialog-001", "artifact-002", "文档2", "doc", "M1", "path2.md")

    def tearDown(self):
        import manifest_generator
        manifest_generator.get_artifacts_root = self._original_root
        shutil.rmtree(self.test_dir)

    def test_remove_existing_artifact(self):
        result = remove_artifact_from_dialog("dialog-001", "artifact-001")
        self.assertTrue(result)
        manifest = load_manifest("dialog-001")
        self.assertEqual(manifest["artifact_count"], 1)

    def test_remove_nonexistent_artifact(self):
        result = remove_artifact_from_dialog("dialog-001", "artifact-999")
        self.assertFalse(result)


class TestListDialogs(TestCase):
    """测试列出所有对话"""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.artifacts_dir = Path(self.test_dir) / "artifacts"
        (self.artifacts_dir / "by-dialog").mkdir(parents=True)

        import manifest_generator
        self._original_root = manifest_generator.get_artifacts_root

        def mock_root():
            return self.artifacts_dir

        manifest_generator.get_artifacts_root = mock_root

    def tearDown(self):
        import manifest_generator
        manifest_generator.get_artifacts_root = self._original_root
        shutil.rmtree(self.test_dir)

    def test_empty_dialogs(self):
        dialogs = list_dialogs()
        self.assertEqual(len(dialogs), 0)

    def test_multiple_dialogs(self):
        create_dialog("dialog-001", "对话1")
        create_dialog("dialog-002", "对话2")
        create_dialog("dialog-010", "对话10")

        dialogs = list_dialogs()
        self.assertEqual(len(dialogs), 3)
        self.assertIn("dialog-001", dialogs)
        self.assertIn("dialog-002", dialogs)
        self.assertIn("dialog-010", dialogs)
        # 验证排序
        self.assertEqual(dialogs, sorted(dialogs))


class TestDialogSummary(TestCase):
    """测试对话摘要"""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.artifacts_dir = Path(self.test_dir) / "artifacts"
        (self.artifacts_dir / "by-dialog").mkdir(parents=True)

        import manifest_generator
        self._original_root = manifest_generator.get_artifacts_root

        def mock_root():
            return self.artifacts_dir

        manifest_generator.get_artifacts_root = mock_root

        create_dialog("dialog-001", "测试对话")
        add_artifact_to_dialog("dialog-001", "artifact-001", "文档", "doc", "M1", "p1.md")
        add_artifact_to_dialog("dialog-001", "artifact-002", "报告", "report", "M2", "p2.md")

    def tearDown(self):
        import manifest_generator
        manifest_generator.get_artifacts_root = self._original_root
        shutil.rmtree(self.test_dir)

    def test_summary_fields(self):
        summary = get_dialog_summary("dialog-001")
        self.assertEqual(summary["dialog_id"], "dialog-001")
        self.assertEqual(summary["dialog_name"], "测试对话")
        self.assertEqual(summary["artifact_count"], 2)
        self.assertEqual(summary["by_type"]["doc"], 1)
        self.assertEqual(summary["by_type"]["report"], 1)
        self.assertEqual(summary["by_module"]["M1"], 1)
        self.assertEqual(summary["by_module"]["M2"], 1)


class TestManifestLoadSave(TestCase):
    """测试 manifest 加载和保存"""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.artifacts_dir = Path(self.test_dir) / "artifacts"
        (self.artifacts_dir / "by-dialog").mkdir(parents=True)

        import manifest_generator
        self._original_root = manifest_generator.get_artifacts_root

        def mock_root():
            return self.artifacts_dir

        manifest_generator.get_artifacts_root = mock_root

    def tearDown(self):
        import manifest_generator
        manifest_generator.get_artifacts_root = self._original_root
        shutil.rmtree(self.test_dir)

    def test_load_nonexistent_returns_default(self):
        manifest = load_manifest("nonexistent")
        self.assertEqual(manifest["dialog_id"], "nonexistent")
        self.assertEqual(manifest["artifact_count"], 0)
        self.assertEqual(len(manifest["artifacts"]), 0)

    def test_save_and_load(self):
        test_data = {
            "dialog_id": "dialog-test",
            "dialog_name": "测试",
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
            "artifact_count": 1,
            "modules": ["M1"],
            "artifacts": [
                {
                    "artifact_id": "artifact-001",
                    "name": "测试",
                    "type": "doc",
                    "module": "M1",
                    "path": "test.md",
                }
            ]
        }
        save_manifest("dialog-test", test_data)
        loaded = load_manifest("dialog-test")
        self.assertEqual(loaded["dialog_id"], "dialog-test")
        self.assertEqual(loaded["artifact_count"], 1)
        self.assertEqual(len(loaded["artifacts"]), 1)

    def test_utf8_encoding(self):
        """测试中文正常保存和读取"""
        add_artifact_to_dialog(
            "dialog-zh",
            "artifact-001",
            "中文名称测试",
            "doc",
            "M1",
            "test.md",
            description="中文描述测试",
            dialog_name="中文对话",
        )
        manifest = load_manifest("dialog-zh")
        self.assertEqual(manifest["dialog_name"], "中文对话")
        self.assertEqual(manifest["artifacts"][0]["name"], "中文名称测试")
        self.assertEqual(manifest["artifacts"][0]["description"], "中文描述测试")


if __name__ == "__main__":
    import unittest
    unittest.main()
