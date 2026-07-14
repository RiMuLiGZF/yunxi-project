"""
验证脚本：工作开发模式 + 复盘总结模式 持久化迁移测试
测试内容：
1. work_dev：项目列表、创建项目、任务看板、提交记录
2. review：复盘列表、创建复盘、日记列表、情绪统计

运行方式：
    python test_modes_p1.py
"""
import sys
import os
import json

# 添加 M8-control-tower 目录到路径（backend 作为包导入）
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

# 在导入 models 之前，先设置环境变量使用测试数据库
TEST_DB_PATH = os.path.join(PROJECT_DIR, "data", "test_m8.db")
# 确保测试目录存在
os.makedirs(os.path.join(PROJECT_DIR, "data"), exist_ok=True)

# 如果测试数据库已存在，先删除（确保干净测试）
if os.path.exists(TEST_DB_PATH):
    os.remove(TEST_DB_PATH)

# 修改 models 模块的数据库路径
import backend.models as models_module
models_module.SQLALCHEMY_DATABASE_URL = f"sqlite:///{TEST_DB_PATH}"
from sqlalchemy import create_engine
models_module.engine = create_engine(
    f"sqlite:///{TEST_DB_PATH}",
    connect_args={"check_same_thread": False},
)
from sqlalchemy.orm import sessionmaker
models_module.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=models_module.engine)

from fastapi.testclient import TestClient
from backend.main import app
from backend.models import init_db, SessionLocal, WorkProject, WorkTask, WorkCommit
from backend.models import ReviewReview, ReviewDiary, ReviewEmotion

client = TestClient(app)

# 测试计数器
passed = 0
failed = 0


def test_case(name):
    """测试用例装饰器"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            global passed, failed
            print(f"\n{'='*60}")
            print(f"▶ 测试: {name}")
            print(f"{'='*60}")
            try:
                result = func(*args, **kwargs)
                print(f"✅ 通过: {name}")
                passed += 1
                return result
            except AssertionError as e:
                print(f"❌ 失败: {name} - {e}")
                failed += 1
                return None
            except Exception as e:
                print(f"❌ 异常: {name} - {type(e).__name__}: {e}")
                failed += 1
                return None
        return wrapper
    return decorator


# ============================================================
# 一、工作开发模式测试
# ============================================================

@test_case("work_dev - 项目列表接口")
def test_work_dev_projects_list():
    """测试项目列表接口"""
    resp = client.get("/api/work-dev/projects")
    assert resp.status_code == 200, f"状态码错误: {resp.status_code}"
    data = resp.json()
    assert data["code"] == 0, f"返回码错误: {data['code']}"
    assert isinstance(data["data"], list), "data 应为列表"
    assert len(data["data"]) >= 3, f"项目数量不足: {len(data['data'])}"

    # 验证字段完整性
    project = data["data"][0]
    required_fields = ["id", "name", "description", "status", "language",
                       "created_at", "updated_at", "task_count", "done_count"]
    for field in required_fields:
        assert field in project, f"缺少字段: {field}"

    print(f"  项目数量: {len(data['data'])}")
    print(f"  首个项目: {project['name']} (id={project['id']})")
    return data["data"]


@test_case("work_dev - 创建项目")
def test_work_dev_create_project():
    """测试创建项目接口"""
    payload = {
        "name": "测试项目-AI助手",
        "description": "这是一个测试项目",
        "language": "python",
    }
    resp = client.post("/api/work-dev/projects", json=payload)
    assert resp.status_code == 200, f"状态码错误: {resp.status_code}"
    data = resp.json()
    assert data["code"] == 0, f"返回码错误: {data['code']}"
    assert data["data"]["name"] == "测试项目-AI助手", "项目名称不匹配"
    assert data["data"]["status"] == "planning", "新项目状态应为 planning"
    assert data["data"]["language"] == "python", "语言不匹配"
    assert "id" in data["data"], "缺少 id 字段"

    print(f"  创建的项目ID: {data['data']['id']}")
    print(f"  创建时间: {data['data']['created_at']}")

    # 验证数据库中确实存在
    db = SessionLocal()
    try:
        count = db.query(WorkProject).filter_by(
            project_id=data["data"]["id"], user_id=1
        ).count()
        assert count == 1, "数据库中未找到创建的项目"
        print(f"  数据库验证: 存在")
    finally:
        db.close()

    return data["data"]


@test_case("work_dev - 任务看板")
def test_work_dev_task_board():
    """测试任务看板接口"""
    resp = client.get("/api/work-dev/tasks/board")
    assert resp.status_code == 200, f"状态码错误: {resp.status_code}"
    data = resp.json()
    assert data["code"] == 0, f"返回码错误: {data['code']}"

    board = data["data"]
    assert "todo" in board, "缺少 todo 列"
    assert "in_progress" in board, "缺少 in_progress 列"
    assert "done" in board, "缺少 done 列"

    total = len(board["todo"]) + len(board["in_progress"]) + len(board["done"])
    assert total > 0, "任务看板为空"

    # 验证任务字段
    if board["todo"]:
        task = board["todo"][0]
        required_fields = ["id", "title", "status", "priority", "project_id", "assignee"]
        for field in required_fields:
            assert field in task, f"任务缺少字段: {field}"

    print(f"  Todo: {len(board['todo'])} 个")
    print(f"  In Progress: {len(board['in_progress'])} 个")
    print(f"  Done: {len(board['done'])} 个")
    print(f"  总计: {total} 个任务")

    # 按项目筛选
    resp2 = client.get("/api/work-dev/tasks/board?project_id=1")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["code"] == 0
    print(f"  项目1任务数: {len(data2['data']['todo']) + len(data2['data']['in_progress']) + len(data2['data']['done'])}")

    return board


@test_case("work_dev - 提交记录")
def test_work_dev_commits():
    """测试提交记录接口"""
    resp = client.get("/api/work-dev/commits")
    assert resp.status_code == 200, f"状态码错误: {resp.status_code}"
    data = resp.json()
    assert data["code"] == 0, f"返回码错误: {data['code']}"
    assert isinstance(data["data"], list), "data 应为列表"
    assert len(data["data"]) > 0, "提交记录为空"

    # 验证字段
    commit = data["data"][0]
    required_fields = ["id", "hash", "message", "author", "project_id",
                       "branch", "created_at", "insertions", "deletions"]
    for field in required_fields:
        assert field in commit, f"缺少字段: {field}"

    print(f"  提交总数: {len(data['data'])}")
    print(f"  最新提交: {commit['message'][:40]}...")

    # 提交统计接口
    resp2 = client.get("/api/work-dev/commits/stats")
    assert resp2.status_code == 200
    stats = resp2.json()
    assert stats["code"] == 0
    assert "total_commits" in stats["data"]
    assert "daily_commits" in stats["data"]
    print(f"  统计 - 总提交: {stats['data']['total_commits']}, 近7天: {stats['data']['daily_commits']}")

    # 新建提交
    resp3 = client.post("/api/work-dev/commits", json={
        "message": "test: 测试提交",
        "project_id": 1,
    })
    assert resp3.status_code == 200
    create_data = resp3.json()
    assert create_data["code"] == 0
    assert create_data["data"]["message"] == "test: 测试提交"
    print(f"  新建提交ID: {create_data['data']['id']}")

    # 验证数据库
    db = SessionLocal()
    try:
        db_commit = db.query(WorkCommit).filter_by(
            commit_id=create_data["data"]["id"], user_id=1
        ).first()
        assert db_commit is not None, "数据库中未找到提交记录"
        assert db_commit.message == "test: 测试提交"
        print(f"  数据库验证: 存在")
    finally:
        db.close()

    return data["data"]


@test_case("work_dev - 概览统计")
def test_work_dev_overview():
    """测试工作开发概览接口"""
    resp = client.get("/api/work-dev/overview")
    assert resp.status_code == 200, f"状态码错误: {resp.status_code}"
    data = resp.json()
    assert data["code"] == 0, f"返回码错误: {data['code']}"

    stats = data["data"]["stats"]
    required_stats = ["total_projects", "active_projects", "total_tasks",
                      "done_tasks", "in_progress_tasks", "todo_tasks",
                      "total_commits", "week_commits", "total_lines"]
    for field in required_stats:
        assert field in stats, f"统计缺少字段: {field}"

    assert "recent_tasks" in data["data"], "缺少 recent_tasks"
    assert "recent_commits" in data["data"], "缺少 recent_commits"

    print(f"  项目数: {stats['total_projects']} (活跃: {stats['active_projects']})")
    print(f"  任务数: {stats['total_tasks']} (done:{stats['done_tasks']} doing:{stats['in_progress_tasks']} todo:{stats['todo_tasks']})")
    print(f"  提交数: {stats['total_commits']} (本周: {stats['week_commits']})")
    print(f"  代码行数: {stats['total_lines']}")

    return data["data"]


# ============================================================
# 二、复盘总结模式测试
# ============================================================

@test_case("review - 复盘列表")
def test_review_list():
    """测试复盘记录列表接口"""
    resp = client.get("/api/review/reviews")
    assert resp.status_code == 200, f"状态码错误: {resp.status_code}"
    data = resp.json()
    assert data["code"] == 0, f"返回码错误: {data['code']}"
    assert isinstance(data["data"], list), "data 应为列表"
    assert len(data["data"]) >= 5, f"复盘记录数量不足: {len(data['data'])}"

    # 验证字段
    review = data["data"][0]
    required_fields = ["id", "type", "title", "content", "date",
                       "quality", "word_count", "created_at", "updated_at"]
    for field in required_fields:
        assert field in review, f"缺少字段: {field}"

    print(f"  复盘总数: {len(data['data'])}")
    print(f"  最新复盘: {review['title']}")

    # 按类型筛选
    resp2 = client.get("/api/review/reviews?review_type=daily")
    assert resp2.status_code == 200
    daily_data = resp2.json()
    assert daily_data["code"] == 0
    daily_count = len(daily_data["data"])
    assert all(r["type"] == "daily" for r in daily_data["data"]), "筛选结果不正确"
    print(f"  日报数量: {daily_count}")

    return data["data"]


@test_case("review - 创建复盘")
def test_review_create():
    """测试创建复盘（AI生成）接口"""
    payload = {
        "type": "daily",
        "content": "今天完成了数据库迁移工作",
    }
    resp = client.post("/api/review/generate", json=payload)
    assert resp.status_code == 200, f"状态码错误: {resp.status_code}"
    data = resp.json()
    assert data["code"] == 0, f"返回码错误: {data['code']}"
    assert data["data"]["type"] == "daily", "类型不匹配"
    assert "日报" in data["data"]["title"], "标题应包含'日报'"
    assert data["data"]["content"], "内容不应为空"
    assert data["data"]["quality"] == "high", "质量应为 high"

    print(f"  创建的复盘ID: {data['data']['id']}")
    print(f"  标题: {data['data']['title']}")
    print(f"  字数: {data['data']['word_count']}")

    # 验证数据库
    db = SessionLocal()
    try:
        db_review = db.query(ReviewReview).filter_by(
            review_id=data["data"]["id"], user_id=1
        ).first()
        assert db_review is not None, "数据库中未找到复盘记录"
        assert db_review.type == "daily"
        print(f"  数据库验证: 存在")
    finally:
        db.close()

    # 测试周报生成
    resp2 = client.post("/api/review/generate", json={"type": "weekly"})
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["code"] == 0
    assert "周报" in data2["data"]["title"]
    print(f"  周报生成: {data2['data']['title']}")

    return data["data"]


@test_case("review - 日记列表")
def test_review_diaries():
    """测试日记列表接口"""
    resp = client.get("/api/review/diaries")
    assert resp.status_code == 200, f"状态码错误: {resp.status_code}"
    data = resp.json()
    assert data["code"] == 0, f"返回码错误: {data['code']}"
    assert isinstance(data["data"], list), "data 应为列表"
    assert len(data["data"]) >= 5, f"日记数量不足: {len(data['data'])}"

    # 验证字段
    diary = data["data"][0]
    required_fields = ["id", "title", "content", "mood", "tags",
                       "word_count", "created_at", "encrypted"]
    for field in required_fields:
        assert field in diary, f"缺少字段: {field}"

    assert isinstance(diary["tags"], list), "tags 应为列表"
    assert diary["encrypted"] is True, "默认应加密"

    print(f"  日记总数: {len(data['data'])}")
    print(f"  最新日记: {diary['title']}")
    print(f"  心情: {diary['mood']}, 字数: {diary['word_count']}")

    # 创建新日记
    resp2 = client.post("/api/review/diaries", json={
        "title": "测试日记",
        "content": "今天的天气真好，心情也很好。",
        "mood": "happy",
        "tags": ["测试", "日常"],
    })
    assert resp2.status_code == 200
    create_data = resp2.json()
    assert create_data["code"] == 0
    assert create_data["data"]["title"] == "测试日记"
    assert create_data["data"]["mood"] == "happy"
    print(f"  新建日记ID: {create_data['data']['id']}")

    # 验证数据库
    db = SessionLocal()
    try:
        db_diary = db.query(ReviewDiary).filter_by(
            diary_id=create_data["data"]["id"], user_id=1
        ).first()
        assert db_diary is not None, "数据库中未找到日记"
        assert db_diary.title == "测试日记"
        print(f"  数据库验证: 存在")
    finally:
        db.close()

    return data["data"]


@test_case("review - 情绪统计")
def test_review_emotion_stats():
    """测试情绪统计接口"""
    resp = client.get("/api/review/emotions/stats")
    assert resp.status_code == 200, f"状态码错误: {resp.status_code}"
    data = resp.json()
    assert data["code"] == 0, f"返回码错误: {data['code']}"

    stats = data["data"]
    assert "total_records" in stats, "缺少 total_records"
    assert "emotion_distribution" in stats, "缺少 emotion_distribution"
    assert "dominant_emotion" in stats, "缺少 dominant_emotion"
    assert "daily_trend" in stats, "缺少 daily_trend"
    assert "avg_level" in stats, "缺少 avg_level"

    assert isinstance(stats["emotion_distribution"], dict), "emotion_distribution 应为字典"
    assert isinstance(stats["daily_trend"], list), "daily_trend 应为列表"
    assert len(stats["daily_trend"]) == 30, "daily_trend 应有30天数据"

    print(f"  总记录数: {stats['total_records']}")
    print(f"  主导情绪: {stats['dominant_emotion']}")
    print(f"  平均强度: {stats['avg_level']}")
    print(f"  情绪分布: {json.dumps(stats['emotion_distribution'], ensure_ascii=False)}")

    # 情绪记录列表
    resp2 = client.get("/api/review/emotions?days=10")
    assert resp2.status_code == 200
    list_data = resp2.json()
    assert list_data["code"] == 0
    assert len(list_data["data"]) <= 10, "不应超过请求的天数"
    print(f"  最近10天情绪记录: {len(list_data['data'])} 条")

    # 验证数据库
    db = SessionLocal()
    try:
        count = db.query(ReviewEmotion).filter_by(user_id=1).count()
        assert count >= 30, f"数据库中情绪记录不足: {count}"
        print(f"  数据库验证: {count} 条记录")
    finally:
        db.close()

    return stats


@test_case("review - 概览统计")
def test_review_overview():
    """测试复盘模式概览接口"""
    resp = client.get("/api/review/overview")
    assert resp.status_code == 200, f"状态码错误: {resp.status_code}"
    data = resp.json()
    assert data["code"] == 0, f"返回码错误: {data['code']}"

    stats = data["data"]["stats"]
    required_stats = ["total_reviews", "total_diaries", "total_decisions",
                      "total_emotions", "week_reviews", "streak_days"]
    for field in required_stats:
        assert field in stats, f"统计缺少字段: {field}"

    assert "emotion_distribution" in data["data"]
    assert "recent_reviews" in data["data"]
    assert "recent_diaries" in data["data"]

    print(f"  复盘数: {stats['total_reviews']}")
    print(f"  日记数: {stats['total_diaries']}")
    print(f"  决策数: {stats['total_decisions']}")
    print(f"  情绪记录: {stats['total_emotions']}")
    print(f"  连续打卡: {stats['streak_days']} 天")

    return data["data"]


# ============================================================
# 主函数
# ============================================================

def main():
    """运行所有测试"""
    global passed, failed
    print("\n" + "="*60)
    print("  M8 模式页持久化迁移验证脚本")
    print("  测试范围: work_dev + review")
    print("="*60)

    # 初始化数据库（创建表 + 种子数据）
    print("\n▶ 初始化数据库...")
    init_db()
    print("  数据库初始化完成")

    # ---- work_dev 测试 ----
    print("\n\n" + "="*60)
    print("  第一部分：工作开发模式 (work_dev)")
    print("="*60)

    test_work_dev_overview()
    test_work_dev_projects_list()
    test_work_dev_create_project()
    test_work_dev_task_board()
    test_work_dev_commits()

    # ---- review 测试 ----
    print("\n\n" + "="*60)
    print("  第二部分：复盘总结模式 (review)")
    print("="*60)

    test_review_overview()
    test_review_list()
    test_review_create()
    test_review_diaries()
    test_review_emotion_stats()

    # ---- 结果汇总 ----
    total = passed + failed
    print("\n\n" + "="*60)
    print(f"  测试结果汇总")
    print("="*60)
    print(f"  总计: {total} 个测试用例")
    print(f"  ✅ 通过: {passed}")
    print(f"  ❌ 失败: {failed}")
    print(f"  通过率: {passed/total*100:.1f}%" if total > 0 else "  无测试")
    print("="*60)

    if failed == 0:
        print("\n🎉 所有测试通过！持久化迁移验证成功。")
    else:
        print(f"\n⚠️  有 {failed} 个测试失败，请检查。")

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
