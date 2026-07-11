# -*- coding: utf-8 -*-
"""M8 测试共享配置"""
import os
import sys
import pytest

# 将 backend 目录加入 path，方便导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 设置测试环境
os.environ["M8_ENV"] = "test"
os.environ["M8_DB_PATH"] = os.path.join(os.path.dirname(__file__), "data", "test_m8.db")
