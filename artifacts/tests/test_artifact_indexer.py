"""
artifact_indexer 单元测试
"""

import json
import os
import sys
import tempfile
import shutil
from pathlib import Path
from unittest import TestCase

# 将 tools 目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from artifact_indexer import (
    detect_type,
    detect_module,
    detect_dialog,
    extract_tags,
    compute_file_hash,
    generate_artifact_id,
    build_index,
    add_artifact,
    load_index,
    save_index,
    MODULE_MAP,
    TYPE_MAP,
)


class TestDetectType(TestCase):
    """测试文件类型检测"""

    def test_md_file(self):
        self.assertEqual(detect_type(Path("test.md")), "doc")

    def test_py_file(self):
        self.assertEqual(detect_type(Path("test.py")), "code")

    def test_yaml_file(self):
        self.assertEqual(detect_type(Path("config.yaml")), "config")

    def test_sh_file(self):
        self.assertEqual(detect_type(Path("deploy.sh")), "script")

    def test_report_keyword_in_filename(self):
        """文件名包含报告关键词时类型升级为 report"""
        self.assertEqual(detect_type(Path("test-report.md")), "report")
        self.assertEqual(detect_type(Path("测试报告.md")), "report")
        self.assertEqual(detect_type(Path("验收报告.md")), "report")

    def test_proto_keyword_in_filename(self):
        self.assertEqual(detect_type(Path("demo-proto.html")), "proto")
        self.assertEqual(detect_type(Path("原型演示.md")), "proto")

    def test_unknown_extension(self):
        self.assertEqual(detect_type(Path("file.unknown")), "doc")


class TestDetectModule(TestCase):
    """测试模块检测"""

    def test_by_module_directory_m1(self):
        path = Path("by-module/M1-agent-cluster/doc.md")
        self.assertEqual(detect_module(path), "M1")

    def test_by_module_directory_m10(self):
        """M10 不应被误识别为 M1"""
        path = Path("by-module/M10-system-guard/doc.md")
        self.assertEqual(detect_module(path), "M10")

    def test_by_module_directory_m5(self):
        path = Path("by-module/M5-tide-memory/api.md")
        self.assertEqual(detect_module(path), "M5")

    def test_filename_m_prefix(self):
        """文件名包含 Mx 标识"""
        self.assertEqual(detect_module(Path("m10-design.md")), "M10")
        self.assertEqual(detect_module(Path("M3-arch.md")), "M3")

    def test_filename_no_module(self):
        self.assertIsNone(detect_module(Path("readme.md")))

    def test_path_keyword(self):
        path = Path("some/path/tide-memory/doc.md")
        self.assertEqual(detect_module(path), "M5")


class TestDetectDialog(TestCase):
    """测试对话检测"""

    def test_by_dialog_directory(self):
        path = Path("by-dialog/dialog-001-m1-dev/doc.md")
        dialog_id, dialog_name = detect_dialog(path)
        self.assertEqual(dialog_id, "dialog-001")
        self.assertEqual(dialog_name, "m1-dev")

    def test_no_dialog(self):
        path = Path("by-module/M1/doc.md")
        dialog_id, dialog_name = detect_dialog(path)
        self.assertIsNone(dialog_id)
        self.assertIsNone(dialog_name)


class TestExtractTags(TestCase):
    """测试标签提取"""

    def test_basic_tags(self):
        tags = extract_tags(Path("m1-architecture-design.md"), "M1", "doc")
        self.assertIn("M1", tags)
        self.assertIn("doc", tags)
        self.assertIn("architecture", tags)
        self.assertIn("design", tags)

    def test_no_module(self):
        tags = extract_tags(Path("test.md"), None, "doc")
        self.assertIn("doc", tags)
        # 没有模块标签
        self.assertNotIn("M1", tags)

    def test_report_keywords(self):
        tags = extract_tags(Path("m10-test-report.md"), "M10", "report")
        self.assertIn("test", tags)
        self.assertIn("report", tags)


class TestComputeFileHash(TestCase):
    """测试文件哈希计算"""

    def test_hash_consistency(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt", encoding="utf-8") as f:
            f.write("test content")
            fpath = f.name
        try:
            h1 = compute_file_hash(Path(fpath))
            h2 = compute_file_hash(Path(fpath))
            self.assertEqual(h1, h2)
            self.assertTrue(len(h1) > 0)
        finally:
            os.unlink(fpath)

    def test_different_content_different_hash(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt", encoding="utf-8") as f:
            f.write("content A")
            fpath1 = f.name
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt", encoding="utf-8") as f:
            f.write("content B")
            fpath2 = f.name
        try:
            h1 = compute_file_hash(Path(fpath1))
            h2 = compute_file_hash(Path(fpath2))
            self.assertNotEqual(h1, h2)
        finally:
            os.unlink(fpath1)
            os.unlink(fpath2)


class TestGenerateArtifactId(TestCase):
    """测试产物ID生成"""

    def test_id_format(self):
        self.assertEqual(generate_artifact_id(1), "artifact-001")
        self.assertEqual(generate_artifact_id(10), "artifact-010")
        self.assertEqual(generate_artifact_id(100), "artifact-100")


class TestBuildIndex(TestCase):
    """测试索引构建"""

    def setUp(self):
        """创建临时测试目录"""
        self.test_dir = tempfile.mkdtemp()
        self.artifacts_dir = Path(self.test_dir) / "artifacts"
        self.tools_dir = self.artifacts_dir / "tools"
        self.tools_dir.mkdir(parents=True)

        # 创建测试文件
        (self.artifacts_dir / "by-module" / "M1-agent-cluster").mkdir(parents=True)
        (self.artifacts_dir / "by-module" / "M10-system-guard").mkdir(parents=True)
        (self.artifacts_dir / "templates").mkdir(parents=True)

        # 写入测试文件
        test_md = self.artifacts_dir / "by-module" / "M1-agent-cluster" / "test-doc.md"
        test_md.write_text("# Test\ncontent", encoding="utf-8")

        test_md2 = self.artifacts_dir / "by-module" / "M10-system-guard" / "test-report.md"
        test_md2.write_text("# Report\ncontent", encoding="utf-8")

        # 模板文件（应被排除）
        tpl = self.artifacts_dir / "templates" / "template.md"
        tpl.write_text("template", encoding="utf-8")

        # 工具文件（应被排除）
        tool = self.tools_dir / "tool.py"
        tool.write_text("print('tool')", encoding="utf-8")

        # README（应被排除）
        readme = self.artifacts_dir / "README.md"
        readme.write_text("# README", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_build_index_counts(self):
        """测试索引构建的产物数量"""
        # 我们需要模拟 get_artifacts_root 返回测试目录
        import artifact_indexer
        original_root = artifact_indexer.get_artifacts_root

        def mock_root():
            return self.artifacts_dir

        artifact_indexer.get_artifacts_root = mock_root
        try:
            index = build_index(incremental=False)
            # 应该只有 2 个产物（排除模板、工具、README）
            self.assertEqual(index["artifact_count"], 2)
        finally:
            artifact_indexer.get_artifacts_root = original_root

    def test_index_json_valid(self):
        """测试生成的 index.json 是有效的JSON"""
        import artifact_indexer
        original_root = artifact_indexer.get_artifacts_root

        def mock_root():
            return self.artifacts_dir

        artifact_indexer.get_artifacts_root = mock_root
        try:
            build_index(incremental=False)
            index_path = self.artifacts_dir / "index.json"
            self.assertTrue(index_path.exists())

            with open(index_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.assertIn("version", data)
            self.assertIn("artifacts", data)
            self.assertIn("generated_at", data)
            self.assertIsInstance(data["artifacts"], dict)
        finally:
            artifact_indexer.get_artifacts_root = original_root

    def test_artifact_record_fields(self):
        """测试产物记录包含所有必要字段"""
        import artifact_indexer
        original_root = artifact_indexer.get_artifacts_root

        def mock_root():
            return self.artifacts_dir

        artifact_indexer.get_artifacts_root = mock_root
        try:
            index = build_index(incremental=False)
            for aid, record in index["artifacts"].items():
                self.assertIn("id", record)
                self.assertIn("name", record)
                self.assertIn("type", record)
                self.assertIn("module", record)
                self.assertIn("path", record)
                self.assertIn("tags", record)
                self.assertIn("created_at", record)
                self.assertIn("updated_at", record)
                self.assertIn("status", record)
                self.assertIn("size_bytes", record)
        finally:
            artifact_indexer.get_artifacts_root = original_root

    def test_m10_not_mistaken_for_m1(self):
        """M10 模块不应被误识别为 M1"""
        import artifact_indexer
        original_root = artifact_indexer.get_artifacts_root

        def mock_root():
            return self.artifacts_dir

        artifact_indexer.get_artifacts_root = mock_root
        try:
            index = build_index(incremental=False)
            modules = [r["module"] for r in index["artifacts"].values()]
            self.assertIn("M10", modules)
            self.assertIn("M1", modules)
            # M1 只有 1 个（test-doc.md），M10 有 1 个（test-report.md）
            m1_count = sum(1 for m in modules if m == "M1")
            m10_count = sum(1 for m in modules if m == "M10")
            self.assertEqual(m1_count, 1)
            self.assertEqual(m10_count, 1)
        finally:
            artifact_indexer.get_artifacts_root = original_root


class TestAddArtifact(TestCase):
    """测试手动添加产物"""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.artifacts_dir = Path(self.test_dir) / "artifacts"
        self.artifacts_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_add_artifact(self):
        import artifact_indexer
        original_root = artifact_indexer.get_artifacts_root

        def mock_root():
            return self.artifacts_dir

        artifact_indexer.get_artifacts_root = mock_root
        try:
            aid = add_artifact(
                name="测试文档",
                artifact_type="doc",
                module="M5",
                filepath="by-module/M5-tide-memory/test.md",
                description="测试描述",
            )
            self.assertTrue(aid.startswith("artifact-"))

            index = load_index(self.artifacts_dir / "index.json")
            self.assertEqual(index["artifact_count"], 1)
            self.assertIn(aid, index["artifacts"])

            record = index["artifacts"][aid]
            self.assertEqual(record["name"], "测试文档")
            self.assertEqual(record["module"], "M5")
            self.assertEqual(record["type"], "doc")
        finally:
            artifact_indexer.get_artifacts_root = original_root


if __name__ == "__main__":
    import unittest
    unittest.main()
