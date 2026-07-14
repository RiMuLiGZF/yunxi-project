"""M11 MCP Bus - 包入口.

支持以包模式启动: python -m src
"""
from .main import app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8011)