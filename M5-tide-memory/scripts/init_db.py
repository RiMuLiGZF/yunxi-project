"""
数据库初始化脚本

⚠️ 本脚本仅创建空数据库结构，不包含任何用户数据
运行: python scripts/init_db.py
"""

import os
import sys
import sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def init_sqlite_db(db_path: str) -> bool:
    """初始化SQLite数据库（空结构）"""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    
    # 记忆主表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            memory_id TEXT PRIMARY KEY,
            content_hash TEXT,
            layer TEXT NOT NULL DEFAULT 'l1_shallow',
            domain TEXT NOT NULL DEFAULT 'private',
            owner_agent TEXT NOT NULL DEFAULT 'system',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_accessed_at TEXT,
            access_count INTEGER DEFAULT 0,
            quality_score REAL DEFAULT 50,
            quality_level TEXT DEFAULT 'normal',
            retention_days INTEGER DEFAULT -1,
            tags TEXT DEFAULT '[]',
            metadata TEXT DEFAULT '{}',
            sync_version INTEGER DEFAULT 0,
            is_dirty INTEGER DEFAULT 0,
            emotion_valence REAL DEFAULT 0,
            emotion_arousal REAL DEFAULT 0,
            emotion_ei REAL DEFAULT 0,
            emotion_label TEXT DEFAULT 'neutral',
            classification TEXT DEFAULT 'TOP_SECRET'
        )
    """)
    
    # 索引
    conn.execute("CREATE INDEX IF NOT EXISTS idx_layer ON memories(layer)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_domain ON memories(domain)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_owner ON memories(owner_agent)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_created ON memories(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_quality ON memories(quality_score)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_classification ON memories(classification)")
    
    # 审计日志表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            operation TEXT NOT NULL,
            memory_id TEXT,
            agent_id TEXT NOT NULL,
            domain TEXT NOT NULL,
            success INTEGER NOT NULL DEFAULT 1,
            failure_reason TEXT DEFAULT '',
            client_ip TEXT DEFAULT '',
            request_id TEXT DEFAULT ''
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(timestamp)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_agent ON audit_logs(agent_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_operation ON audit_logs(operation)")
    
    # 版本表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
    """)
    
    from datetime import datetime
    conn.execute(
        "INSERT OR REPLACE INTO schema_version VALUES (?, ?)",
        ("2.4.0", datetime.now().isoformat())
    )
    
    conn.commit()
    conn.close()
    return True


def init_vector_index(path: str) -> bool:
    """初始化向量索引目录（空结构）"""
    os.makedirs(path, exist_ok=True)
    # ChromaDB等会自动创建，这里只确保目录存在
    return True


def main():
    base_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    
    print("=" * 50)
    print("M5 潮汐记忆系统 - 数据库初始化")
    print("=" * 50)
    print()
    
    # 1. L1 浅水层
    l1_path = os.path.join(base_dir, "memory", "l1_shallow.db")
    print(f"[1/4] 初始化 L1 浅水层数据库...")
    init_sqlite_db(l1_path)
    print(f"      ✓ {l1_path}")
    
    # 2. L2 深水层
    l2_path = os.path.join(base_dir, "memory", "l2_deep.db")
    print(f"[2/4] 初始化 L2 深水层数据库...")
    init_sqlite_db(l2_path)
    print(f"      ✓ {l2_path}")
    
    # 3. L3 深海层
    l3_path = os.path.join(base_dir, "memory", "l3_abyss")
    print(f"[3/4] 初始化 L3 深海层目录...")
    os.makedirs(l3_path, exist_ok=True)
    print(f"      ✓ {l3_path}")
    
    # 4. 向量索引
    vector_path = os.path.join(base_dir, "vector")
    print(f"[4/4] 初始化向量索引目录...")
    init_vector_index(vector_path)
    print(f"      ✓ {vector_path}")
    
    print()
    print("=" * 50)
    print("数据库初始化完成！")
    print("⚠️  所有数据库均为空结构，不含任何用户数据")
    print("=" * 50)


if __name__ == "__main__":
    main()
