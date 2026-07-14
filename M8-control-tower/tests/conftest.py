# -*- coding: utf-8 -*-
"""
M8 控制塔 - pytest 共享 fixtures

提供测试客户端和内存数据库会话，确保测试不依赖任何外部服务
（Redis、Ollama 等），可在 Windows 上独立运行。
"""

import os
import sys
from pathlib import Path

# ============================================================
# 路径设置（必须在导入 backend 之前完成）
# ============================================================

# M8-control-tower 根目录
M8_ROOT = Path(__file__).resolve().parent.parent
# yunxi-project 根目录（包含 shared 模块）
PROJECT_ROOT = M8_ROOT.parent

# 将项目根目录和 M8 根目录加入 sys.path
for _p in (str(PROJECT_ROOT), str(M8_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ============================================================
# 环境变量覆盖（必须在导入 backend 之前设置）
# ============================================================

# 使用内存 SQLite，避免写入磁盘文件
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("YUNXI_ENV", "test")

# ============================================================
# 导入 backend 模块（此时环境变量已就绪）
# ============================================================

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# 导入 Base（确保所有模型已注册到 metadata）
import backend.models  # noqa: F401  -- 触发所有模型的导入
from backend.models.base import Base, get_db
from backend.main import create_app


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def db_session():
    """创建内存 SQLite 数据库会话。

    使用 StaticPool 保证同一连接被复用，确保 :memory: 数据库中
    创建的表在同一个事务内可见。
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # 在测试引擎上创建所有表
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def client(db_session):
    """创建 FastAPI 测试客户端。

    - 使用 create_app() 构建应用实例
    - 覆盖 get_db 依赖，使其指向内存数据库会话
    - 通过 TestClient 上下文管理器触发 lifespan（含 init_db）
    """
    app = create_app()

    # 覆盖数据库依赖，使所有路由使用测试会话
    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db

    # TestClient 作为上下文管理器会触发 app lifespan
    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
