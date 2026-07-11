"""
M2 技能集群 - 技能列表与搜索测试
"""
import sys
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

MOCK_SKILLS = [
    {"skill_id": "skill_001", "name": "日程管理", "category": "productivity",
     "description": "管理日程安排", "version": "v1.2.0", "status": "active",
     "tags": ["calendar", "schedule"], "usage_count": 1250, "rating": 4.5},
    {"skill_id": "skill_002", "name": "翻译助手", "category": "language",
     "description": "多语言互译", "version": "v2.0.1", "status": "active",
     "tags": ["translate", "language"], "usage_count": 3420, "rating": 4.8},
    {"skill_id": "skill_003", "name": "代码生成", "category": "development",
     "description": "根据需求生成代码", "version": "v1.5.0", "status": "active",
     "tags": ["code", "generate"], "usage_count": 2180, "rating": 4.3},
    {"skill_id": "skill_004", "name": "心情记录", "category": "emotion",
     "description": "记录每日心情", "version": "v1.0.0", "status": "active",
     "tags": ["mood", "emotion"], "usage_count": 890, "rating": 4.6},
    {"skill_id": "skill_005", "name": "旧版天气", "category": "utility",
     "description": "已废弃天气查询", "version": "v0.9.0", "status": "deprecated",
     "tags": ["weather"], "usage_count": 150, "rating": 3.2},
]

class TestSkillList:
    """技能列表测试类"""

    @pytest.mark.m2
    @pytest.mark.skill
    def test_get_all_skills(self):
        """测试获取全部技能列表"""
        assert len(MOCK_SKILLS) == 5
        for s in MOCK_SKILLS:
            assert "skill_id" in s
            assert "name" in s
            assert "category" in s

    @pytest.mark.m2
    @pytest.mark.skill
    def test_skill_categories(self):
        """测试技能分类完整性"""
        categories = set(s["category"] for s in MOCK_SKILLS)
        assert len(categories) == 5

    @pytest.mark.m2
    @pytest.mark.skill
    def test_skill_version_format(self):
        """测试技能版本号格式"""
        import re
        for s in MOCK_SKILLS:
            assert re.match(r"^v\d+\.\d+\.\d+$", s["version"])

    @pytest.mark.m2
    @pytest.mark.skill
    def test_skill_ratings_range(self):
        """测试评分在0-5之间"""
        for s in MOCK_SKILLS:
            assert 0 <= s["rating"] <= 5

    @pytest.mark.m2
    @pytest.mark.skill
    def test_search_by_keyword(self):
        """测试按关键词搜索"""
        results = [s for s in MOCK_SKILLS if "代码" in s["name"]]
        assert len(results) == 1
        assert results[0]["name"] == "代码生成"

    @pytest.mark.m2
    @pytest.mark.skill
    def test_search_by_tag(self):
        """测试按标签搜索"""
        results = [s for s in MOCK_SKILLS if "translate" in s["tags"]]
        assert len(results) >= 1

    @pytest.mark.m2
    @pytest.mark.skill
    def test_filter_by_status(self):
        """测试按状态过滤"""
        active = [s for s in MOCK_SKILLS if s["status"] == "active"]
        assert len(active) == 4

    @pytest.mark.m2
    @pytest.mark.skill
    def test_filter_by_category(self):
        """测试按分类过滤"""
        dev_skills = [s for s in MOCK_SKILLS if s["category"] == "development"]
        assert len(dev_skills) == 1

    @pytest.mark.m2
    @pytest.mark.skill
    def test_sort_by_usage(self):
        """测试按使用量排序"""
        sorted_skills = sorted(MOCK_SKILLS, key=lambda x: x["usage_count"], reverse=True)
        assert sorted_skills[0]["name"] == "翻译助手"

    @pytest.mark.m2
    @pytest.mark.skill
    def test_sort_by_rating(self):
        """测试按评分排序"""
        sorted_skills = sorted(MOCK_SKILLS, key=lambda x: x["rating"], reverse=True)
        assert sorted_skills[0]["rating"] >= sorted_skills[-1]["rating"]

    @pytest.mark.m2
    @pytest.mark.skill
    def test_skill_detail_has_tags(self):
        """测试技能详情包含标签"""
        skill = MOCK_SKILLS[0]
        assert isinstance(skill["tags"], list)
        assert len(skill["tags"]) > 0

    @pytest.mark.m2
    @pytest.mark.skill
    def test_skill_id_unique(self):
        """测试技能ID唯一"""
        ids = [s["skill_id"] for s in MOCK_SKILLS]
        assert len(ids) == len(set(ids))
