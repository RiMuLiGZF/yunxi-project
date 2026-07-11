"""
数据迁移脚本

支持从 v2.0 / v2.1 / v2.2 / v2.3 迁移到 v2.4
⚠️ 迁移前请务必备份数据

运行: python scripts/migrate.py --from 2.3.0 --to 2.4.0
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from typing import Dict, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class MemoryMigrator:
    """记忆数据迁移器"""

    SUPPORTED_VERSIONS = ["2.0.0", "2.1.0", "2.2.0", "2.3.0", "2.4.0"]

    def __init__(self, data_dir: str):
        self._data_dir = data_dir
        self._backup_dir = None

    def backup(self) -> str:
        """创建数据备份"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = f"{self._data_dir}_backup_{timestamp}"
        
        if os.path.exists(self._data_dir):
            shutil.copytree(self._data_dir, backup_dir)
        
        self._backup_dir = backup_dir
        return backup_dir

    def get_current_version(self) -> Optional[str]:
        """获取当前数据版本"""
        version_file = os.path.join(self._data_dir, "VERSION")
        if os.path.exists(version_file):
            with open(version_file, "r") as f:
                return f.read().strip()
        return None

    def migrate(self, from_version: str, to_version: str) -> Dict:
        """
        执行数据迁移
        
        Args:
            from_version: 源版本
            to_version: 目标版本
        
        Returns:
            迁移结果
        """
        if from_version not in self.SUPPORTED_VERSIONS:
            return {"success": False, "error": f"不支持的源版本: {from_version}"}
        
        if to_version not in self.SUPPORTED_VERSIONS:
            return {"success": False, "error": f"不支持的目标版本: {to_version}"}

        # 按版本顺序逐步迁移
        start_idx = self.SUPPORTED_VERSIONS.index(from_version)
        end_idx = self.SUPPORTED_VERSIONS.index(to_version)
        
        if start_idx >= end_idx:
            return {"success": True, "message": "已是最新版本，无需迁移"}

        migrated_count = 0
        for i in range(start_idx, end_idx):
            v_from = self.SUPPORTED_VERSIONS[i]
            v_to = self.SUPPORTED_VERSIONS[i + 1]
            result = self._migrate_step(v_from, v_to)
            if not result["success"]:
                return result
            migrated_count += result.get("migrated", 0)

        # 更新版本文件
        self._write_version(to_version)

        return {
            "success": True,
            "from_version": from_version,
            "to_version": to_version,
            "migrated_count": migrated_count,
        }

    def _migrate_step(self, from_ver: str, to_ver: str) -> Dict:
        """单步迁移"""
        # 简化实现：各版本迁移逻辑
        migrations = {
            ("2.0.0", "2.1.0"): self._migrate_20_21,
            ("2.1.0", "2.2.0"): self._migrate_21_22,
            ("2.2.0", "2.3.0"): self._migrate_22_23,
            ("2.3.0", "2.4.0"): self._migrate_23_24,
        }
        
        key = (from_ver, to_ver)
        if key in migrations:
            return migrations[key]()
        
        return {"success": True, "migrated": 0}

    def _migrate_20_21(self) -> Dict:
        """v2.0 → v2.1：增加情绪字段"""
        db_path = os.path.join(self._data_dir, "l1_shallow.db")
        if not os.path.exists(db_path):
            return {"success": True, "migrated": 0}
        
        conn = sqlite3.connect(db_path)
        try:
            # 检查字段是否存在
            cursor = conn.execute("PRAGMA table_info(memories)")
            columns = [row[1] for row in cursor.fetchall()]
            
            if "emotion_valence" not in columns:
                conn.execute("ALTER TABLE memories ADD COLUMN emotion_valence REAL DEFAULT 0")
                conn.execute("ALTER TABLE memories ADD COLUMN emotion_arousal REAL DEFAULT 0")
                conn.execute("ALTER TABLE memories ADD COLUMN emotion_ei REAL DEFAULT 0")
                conn.execute("ALTER TABLE memories ADD COLUMN emotion_label TEXT DEFAULT 'neutral'")
            
            conn.commit()
            return {"success": True, "migrated": 0}
        finally:
            conn.close()

    def _migrate_21_22(self) -> Dict:
        """v2.1 → v2.2：增加密级字段"""
        db_path = os.path.join(self._data_dir, "l1_shallow.db")
        if not os.path.exists(db_path):
            return {"success": True, "migrated": 0}
        
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute("PRAGMA table_info(memories)")
            columns = [row[1] for row in cursor.fetchall()]
            
            if "classification" not in columns:
                conn.execute("ALTER TABLE memories ADD COLUMN classification TEXT DEFAULT 'TOP_SECRET'")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_classification ON memories(classification)")
            
            conn.commit()
            return {"success": True, "migrated": 0}
        finally:
            conn.close()

    def _migrate_22_23(self) -> Dict:
        """v2.2 → v2.3：增加质量评估字段"""
        db_path = os.path.join(self._data_dir, "l1_shallow.db")
        if not os.path.exists(db_path):
            return {"success": True, "migrated": 0}
        
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute("PRAGMA table_info(memories)")
            columns = [row[1] for row in cursor.fetchall()]
            
            if "quality_score" not in columns:
                conn.execute("ALTER TABLE memories ADD COLUMN quality_score REAL DEFAULT 50")
                conn.execute("ALTER TABLE memories ADD COLUMN quality_level TEXT DEFAULT 'normal'")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_quality ON memories(quality_score)")
            
            conn.commit()
            return {"success": True, "migrated": 0}
        finally:
            conn.close()

    def _migrate_23_24(self) -> Dict:
        """v2.3 → v2.4：增加同步字段"""
        db_path = os.path.join(self._data_dir, "l1_shallow.db")
        if not os.path.exists(db_path):
            return {"success": True, "migrated": 0}
        
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute("PRAGMA table_info(memories)")
            columns = [row[1] for row in cursor.fetchall()]
            
            if "sync_version" not in columns:
                conn.execute("ALTER TABLE memories ADD COLUMN sync_version INTEGER DEFAULT 0")
                conn.execute("ALTER TABLE memories ADD COLUMN is_dirty INTEGER DEFAULT 0")
                conn.execute("ALTER TABLE memories ADD COLUMN content_hash TEXT DEFAULT ''")
            
            conn.commit()
            return {"success": True, "migrated": 0}
        finally:
            conn.close()

    def _write_version(self, version: str) -> None:
        """写入版本文件"""
        os.makedirs(self._data_dir, exist_ok=True)
        version_file = os.path.join(self._data_dir, "VERSION")
        with open(version_file, "w") as f:
            f.write(version)

    def rollback(self, backup_dir: str) -> bool:
        """从备份回滚"""
        if not os.path.exists(backup_dir):
            return False
        
        if os.path.exists(self._data_dir):
            shutil.rmtree(self._data_dir)
        
        shutil.copytree(backup_dir, self._data_dir)
        return True


def main():
    parser = argparse.ArgumentParser(description="M5 潮汐记忆系统数据迁移工具")
    parser.add_argument("--data-dir", default="./data/memory", help="数据目录")
    parser.add_argument("--from", dest="from_ver", help="源版本")
    parser.add_argument("--to", dest="to_ver", default="2.4.0", help="目标版本")
    parser.add_argument("--backup", action="store_true", help="迁移前备份")
    parser.add_argument("--rollback", help="从指定备份目录回滚")
    parser.add_argument("--check", action="store_true", help="检查当前版本")
    
    args = parser.parse_args()
    
    migrator = MemoryMigrator(args.data_dir)
    
    if args.check:
        version = migrator.get_current_version()
        print(f"当前数据版本: {version or '未检测到'}")
        return
    
    if args.rollback:
        print(f"正在从备份回滚: {args.rollback}")
        if migrator.rollback(args.rollback):
            print("✓ 回滚成功")
        else:
            print("✗ 回滚失败")
        return
    
    # 迁移
    from_ver = args.from_ver or migrator.get_current_version() or "2.0.0"
    
    if args.backup:
        print("创建数据备份...")
        backup = migrator.backup()
        print(f"✓ 备份已创建: {backup}")
    
    print(f"迁移: {from_ver} → {args.to_ver}")
    result = migrator.migrate(from_ver, args.to_ver)
    
    if result["success"]:
        print("✓ 迁移成功")
        if "migrated_count" in result:
            print(f"  迁移步数: {result['migrated_count']}")
    else:
        print(f"✗ 迁移失败: {result.get('error')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
