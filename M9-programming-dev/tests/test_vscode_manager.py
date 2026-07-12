"""M9 VSCode管理器单元测试"""

import pytest
from m9_programming_dev.vscode_manager import VSCodeManager
from m9_programming_dev.models import VSCodeStatus


class TestVSCodeManager:
    """VSCode管理器测试"""
    
    def setup_method(self):
        self.manager = VSCodeManager()
    
    def test_list_instances_empty(self):
        """测试空实例列表"""
        instances = self.manager.list_instances()
        assert isinstance(instances, list)
        assert len(instances) == 0
    
    def test_get_nonexistent_instance(self):
        """测试获取不存在的实例"""
        instance = self.manager.get_instance("nonexistent")
        assert instance is None
    
    def test_stop_nonexistent_instance(self):
        """测试停止不存在的实例"""
        result = self.manager.stop_instance("nonexistent")
        assert result is False
    
    def test_open_file_nonexistent_instance(self):
        """测试在不存在的实例中打开文件"""
        result = self.manager.open_file("nonexistent", "/path/to/file")
        assert result is False
