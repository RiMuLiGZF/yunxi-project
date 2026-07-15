from __future__ import annotations

"""技能市场 - 技能包存储管理.

负责技能包文件的打包（zip）、解压、持久化存储。
打包格式：ZIP，包含 manifest.json + 所有 .py 源文件 + requirements.txt（可选）。
"""

import hashlib
import json
import os
import shutil
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Optional, Tuple

import structlog

logger = structlog.get_logger()


class SkillPackageStore:
    """技能包文件存储管理器.

    管理两个目录：
    - base_dir: 已发布技能包的 zip 文件存储（~/.yunxi/market/skills/）
    - installed_dir: 已安装技能的解压目录（~/.yunxi/skills/installed/）
    """

    def __init__(self, base_dir: Optional[str] = None) -> None:
        # 默认存储路径: ~/.yunxi/market/skills/
        if base_dir is None:
            base_dir = os.path.join(
                os.path.expanduser("~"), ".yunxi", "market", "skills"
            )
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.installed_dir = Path(
            os.path.join(
                os.path.expanduser("~"), ".yunxi", "skills", "installed"
            )
        )
        self.installed_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 打包 / 解压
    # ------------------------------------------------------------------

    def pack_skill(
        self, skill_dir: str, skill_id: str
    ) -> Tuple[bytes, str, int]:
        """将技能目录打包为 zip bytes，返回 (data, checksum, size).

        打包内容：
        - 所有 .py 源文件（递归，跳过 __pycache__）
        - requirements.txt（若存在）
        - manifest.json（若存在）

        Args:
            skill_dir: 技能源文件目录.
            skill_id: 技能 ID（用于日志）.

        Returns:
            (zip_bytes, sha256_hex, size).

        Raises:
            FileNotFoundError: 目录不存在.
        """
        src = Path(skill_dir)
        if not src.exists() or not src.is_dir():
            raise FileNotFoundError(f"技能目录不存在: {skill_dir}")

        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(src):
                # 跳过缓存目录
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for fname in files:
                    # 只打包 .py、requirements.txt、manifest.json
                    if not (
                        fname.endswith(".py")
                        or fname == "requirements.txt"
                        or fname == "manifest.json"
                    ):
                        continue
                    fpath = Path(root) / fname
                    arcname = str(fpath.relative_to(src))
                    zf.write(str(fpath), arcname)

        data = buf.getvalue()
        checksum = hashlib.sha256(data).hexdigest()
        size = len(data)
        logger.info(
            "skill_packed",
            skill_id=skill_id,
            size=size,
            checksum=checksum[:12],
        )
        return data, checksum, size

    def unpack_skill(self, package_data: bytes, target_dir: str) -> str:
        """解压技能包到目标目录，返回目标路径.

        Args:
            package_data: zip 文件字节流.
            target_dir: 解压目标目录.

        Returns:
            目标目录绝对路径.

        Raises:
            zipfile.BadZipFile: 数据不是合法 zip.
        """
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(BytesIO(package_data)) as zf:
            # 安全检查：防止路径遍历
            for member in zf.namelist():
                member_path = Path(member)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise ValueError(f"不安全的压缩包路径: {member}")
            zf.extractall(str(target))

        logger.info("skill_unpacked", target_dir=str(target))
        return str(target)

    # ------------------------------------------------------------------
    # 包文件持久化
    # ------------------------------------------------------------------

    def save_package(self, package_id: str, data: bytes) -> str:
        """保存技能包文件，返回文件路径."""
        path = self.base_dir / f"{package_id}.zip"
        path.write_bytes(data)
        return str(path)

    def get_package_path(self, package_id: str) -> Optional[str]:
        """获取技能包文件路径，不存在返回 None."""
        path = self.base_dir / f"{package_id}.zip"
        return str(path) if path.exists() else None

    def read_package(self, package_id: str) -> Optional[bytes]:
        """读取技能包文件字节流，不存在返回 None."""
        path = self.get_package_path(package_id)
        if path is None:
            return None
        return Path(path).read_bytes()

    def delete_package(self, package_id: str) -> bool:
        """删除技能包文件，返回是否删除成功."""
        path = self.base_dir / f"{package_id}.zip"
        if path.exists():
            path.unlink()
            return True
        return False

    # ------------------------------------------------------------------
    # 已安装技能目录管理
    # ------------------------------------------------------------------

    def get_installed_dir(self, package_id: str) -> Path:
        """获取已安装技能的目录."""
        return self.installed_dir / package_id

    def remove_installed(self, package_id: str) -> bool:
        """删除已安装技能目录，返回是否删除成功."""
        inst = self.get_installed_dir(package_id)
        if inst.exists():
            shutil.rmtree(str(inst), ignore_errors=True)
            return True
        return False

    def is_installed(self, package_id: str) -> bool:
        """判断技能包是否已安装."""
        return self.get_installed_dir(package_id).exists()
