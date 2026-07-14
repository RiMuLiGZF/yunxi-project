"""M8 管理工作台后端 - 包入口.

支持以包模式启动: python -m backend
"""
from .main import app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)