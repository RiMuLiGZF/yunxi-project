"""M9 Programming Dev - VSCode管理器"""

import subprocess
import os
import uuid
import time
import logging
from typing import Optional, List, Dict
from .config import settings
from .models import VSCodeInstance, VSCodeStatus

logger = logging.getLogger("m9.vscode")


class VSCodeManager:
    """VSCode实例管理器"""
    
    def __init__(self):
        self._instances: Dict[str, VSCodeInstance] = {}
    
    def list_instances(self) -> List[VSCodeInstance]:
        """列出所有VSCode实例"""
        return list(self._instances.values())
    
    def get_instance(self, instance_id: str) -> Optional[VSCodeInstance]:
        """获取指定实例"""
        return self._instances.get(instance_id)
    
    def start_instance(self, name: str, workspace: Optional[str] = None) -> VSCodeInstance:
        """启动VSCode实例"""
        instance_id = str(uuid.uuid4())[:8]
        ws = workspace or settings.vscode_default_workspace
        
        instance = VSCodeInstance(
            id=instance_id,
            name=name,
            status=VSCodeStatus.STARTING,
            workspace=ws,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S")
        )
        
        try:
            # 启动 VSCode
            cmd = [settings.vscode_code_command, ws]
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            instance.pid = process.pid
            instance.status = VSCodeStatus.RUNNING
        except Exception as e:
            instance.status = VSCodeStatus.ERROR
            logger.error("启动VSCode实例 %s 失败: %s", instance_id, e)
        
        self._instances[instance_id] = instance
        return instance
    
    def stop_instance(self, instance_id: str) -> bool:
        """停止VSCode实例"""
        instance = self._instances.get(instance_id)
        if not instance:
            return False

        if instance.pid:
            try:
                import psutil
                process = psutil.Process(instance.pid)
                process.terminate()
                try:
                    process.wait(timeout=2)
                except psutil.TimeoutExpired:
                    logger.warning("VSCode实例 %s 未响应terminate，执行kill", instance_id)
                    process.kill()
            except Exception as e:
                logger.warning("停止VSCode实例 %s 异常: %s", instance_id, e)

        instance.status = VSCodeStatus.STOPPED
        return True
    
    def open_file(self, instance_id: str, file_path: str) -> bool:
        """在VSCode中打开文件"""
        instance = self._instances.get(instance_id)
        if not instance or instance.status != VSCodeStatus.RUNNING:
            return False
        
        try:
            subprocess.run(
                [settings.vscode_code_command, "--goto", file_path],
                capture_output=True
            )
            return True
        except Exception:
            return False


# 全局单例
vscode_manager = VSCodeManager()
