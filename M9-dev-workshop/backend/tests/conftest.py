"""M9 开发者工坊 - 测试配置与共享 fixtures"""
import sys
import os
from pathlib import Path

# 确保可以导入 backend 模块
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def backend_dir():
    return BACKEND_DIR


@pytest.fixture(scope="session")
def test_token():
    return "m9-dev-token-placeholder"


@pytest.fixture(scope="session")
def admin_headers(test_token):
    return {"X-M9-Token": test_token}


@pytest.fixture(scope="session")
def m8_headers(test_token):
    return {"x-m8-token": test_token}


@pytest.fixture(scope="session")
def client():
    """创建 FastAPI 测试客户端"""
    from main import app
    return TestClient(app)
