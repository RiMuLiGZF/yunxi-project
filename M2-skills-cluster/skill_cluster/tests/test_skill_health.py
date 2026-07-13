"""Tests for Skill Cluster Health checker."""

import pytest

from skill_cluster.infrastructure.health.skill_health import (
    CacheHealthChecker,
    CircuitBreakerHealthChecker,
    ClusterHealthReport,
    ComponentHealth,
    HealthStatus,
    RegistryHealthChecker,
    SkillClusterHealthChecker,
)


def test_component_health_defaults():
    ch = ComponentHealth(
        component_name="test",
        status=HealthStatus.HEALTHY,
    )
    assert ch.score == 1.0
    assert ch.issues == []
    assert ch.checked_at != ""


def test_cluster_health_report_summary():
    report = ClusterHealthReport(
        overall_status=HealthStatus.HEALTHY,
        overall_score=0.95,
        components=[
            ComponentHealth("a", HealthStatus.HEALTHY, 1.0),
            ComponentHealth("b", HealthStatus.DEGRADED, 0.7, issues=["slow"]),
        ],
    )
    summary = report.to_summary()
    assert summary["overall_status"] == "healthy"
    assert summary["overall_score"] == 0.95
    assert len(summary["components"]) == 2
    assert summary["components"][1]["issues"] == ["slow"]


def test_health_checker_no_checkers():
    checker = SkillClusterHealthChecker()
    report = checker.check()
    assert report.overall_status == HealthStatus.UNHEALTHY
    assert report.overall_score == 0.0


def test_health_checker_manual_scores():
    checker = SkillClusterHealthChecker()
    checker.set_manual_score("module_a", 0.9)
    checker.set_manual_score("module_b", 0.4, issues=["timeout"])
    report = checker.check()
    assert len(report.components) == 2
    # Average = (0.9 + 0.4) / 2 = 0.65 → DEGRADED
    assert report.overall_status == HealthStatus.DEGRADED
    assert report.overall_score == 0.65


def test_health_checker_auto_checker():
    class FakeChecker:
        def check(self):
            return ComponentHealth(
                "fake", HealthStatus.HEALTHY, 0.85
            )
    checker = SkillClusterHealthChecker()
    checker.register_checker("fake", FakeChecker())
    report = checker.check()
    assert report.overall_score == 0.85
    assert report.overall_status == HealthStatus.HEALTHY


def test_health_checker_failed_checker():
    class BrokenChecker:
        def check(self):
            raise RuntimeError("boom")
    checker = SkillClusterHealthChecker()
    checker.register_checker("broken", BrokenChecker())
    report = checker.check()
    assert len(report.components) == 1
    assert report.components[0].status == HealthStatus.UNKNOWN


def test_health_status_enum():
    assert HealthStatus.HEALTHY.value == "healthy"
    assert HealthStatus.DEGRADED.value == "degraded"
    assert HealthStatus.UNHEALTHY.value == "unhealthy"


# --- Registry health ---

def test_registry_health_empty():
    class FakeRegistry:
        def list_skills(self):
            return []
    checker = RegistryHealthChecker(FakeRegistry())
    health = checker.check()
    assert health.status == HealthStatus.DEGRADED
    assert health.score == 0.3


def test_registry_health_with_skills():
    class FakeRegistry:
        def list_skills(self):
            return ["s1", "s2"]
        def get_manifest(self, sid):
            # Return manifest with actions
            class M:
                actions = ["act1"]
            return M()
    checker = RegistryHealthChecker(FakeRegistry())
    health = checker.check()
    assert health.status == HealthStatus.HEALTHY
    assert health.score == 1.0


# --- Cache health ---

def test_cache_health_with_stats():
    class FakeCache:
        def get_stats(self):
            return {"hit_rate": 0.85, "total_entries": 100}
    checker = CacheHealthChecker(FakeCache())
    health = checker.check()
    assert health.status == HealthStatus.HEALTHY
    assert health.score == 0.85


def test_cache_health_empty():
    class FakeCache:
        def get_stats(self):
            return {"hit_rate": 0.0, "total_entries": 0}
    checker = CacheHealthChecker(FakeCache())
    health = checker.check()
    assert "empty" in health.issues[0].lower()


def test_cache_health_broken():
    class FakeCache:
        def get_stats(self):
            raise RuntimeError("no stats")
    checker = CacheHealthChecker(FakeCache())
    health = checker.check()
    assert health.status == HealthStatus.UNKNOWN


# --- Circuit breaker health ---

def test_cb_health_closed():
    class FakeCB:
        def get_stats(self):
            return {"state": "closed"}
    checker = CircuitBreakerHealthChecker(FakeCB())
    health = checker.check()
    assert health.status == HealthStatus.HEALTHY
    assert health.score == 1.0


def test_cb_health_open():
    class FakeCB:
        def get_stats(self):
            return {"state": "open"}
    checker = CircuitBreakerHealthChecker(FakeCB())
    health = checker.check()
    assert health.status == HealthStatus.UNHEALTHY
    assert health.score == 0.2


def test_cb_health_half_open():
    class FakeCB:
        def get_stats(self):
            return {"state": "half_open"}
    checker = CircuitBreakerHealthChecker(FakeCB())
    health = checker.check()
    assert health.status == HealthStatus.DEGRADED
    assert health.score == 0.6
