"""
自进化引擎 MVP - 核心流程验证脚本
使用 httpx 直接调用本地 API（需先启动后端服务）

测试流程：
1. 触发健康扫描 → 生成扫描记录
2. 创建进化计划 → 生成候选方案 → 选择方案
3. 启动安全审计 → 生成审计报告
4. 审批 → 部署 → 生成版本记录
5. 回滚测试
"""

import sys
import json
import time
import httpx

BASE_URL = "http://127.0.0.1:8081"

# 全局变量
token = None
plan_id = None
candidate_id = None
audit_report_id = None
approval_id = None
version_id = None


def print_step(step_num: int, title: str):
    """打印步骤标题"""
    print(f"\n{'='*60}")
    print(f"  步骤 {step_num}: {title}")
    print(f"{'='*60}")


def print_result(label: str, data: dict = None, success: bool = True):
    """打印结果"""
    status = "✓ 成功" if success else "✗ 失败"
    print(f"\n{status} - {label}")
    if data:
        data_str = json.dumps(data, ensure_ascii=False, indent=2)
        if len(data_str) > 600:
            data_str = data_str[:600] + "..."
        print(f"  数据: {data_str}")


def login():
    """登录获取 token"""
    print_step(0, "登录获取 Token")
    try:
        response = httpx.post(
            f"{BASE_URL}/api/auth/login",
            json={"username": "admin", "password": "admin123456"}
        )
        result = response.json()
        if result.get("code") == 0:
            global token
            token = result["data"]["access_token"]
            print_result("登录成功", {"token_preview": token[:20] + "..."})
            return True
        else:
            print_result("登录失败", result, success=False)
            return False
    except Exception as e:
        print(f"\n✗ 连接失败: {e}")
        print(f"  请确保后端服务已启动: uvicorn main:app --port 8080")
        return False


def auth_headers():
    """获取带认证的请求头"""
    return {"Authorization": f"Bearer {token}"}


# ============================================================
# 步骤 1：健康扫描
# ============================================================

def step_1_health_scan():
    """触发健康扫描"""
    print_step(1, "触发健康扫描")

    try:
        # 1.1 触发扫描
        response = httpx.post(
            f"{BASE_URL}/api/evo/planner/scan",
            headers=auth_headers(),
            timeout=30,
        )
        result = response.json()

        if result.get("code") == 0:
            scan_data = result["data"]
            print_result("健康扫描完成", {
                "scan_id": scan_data["id"],
                "overall_score": scan_data["overall_score"],
                "module_count": len(scan_data.get("module_scores", {})),
                "anomaly_count": len(scan_data.get("anomalies", [])),
                "recommendation_count": len(scan_data.get("recommendations", [])),
            })

            # 1.2 获取扫描列表
            response2 = httpx.get(
                f"{BASE_URL}/api/evo/planner/scans",
                headers=auth_headers(),
            )
            result2 = response2.json()
            if result2.get("code") == 0:
                print_result("扫描历史列表", {"total": result2["data"]["total"]})

            # 1.3 获取扫描详情
            scan_id = scan_data["id"]
            response3 = httpx.get(
                f"{BASE_URL}/api/evo/planner/scans/{scan_id}",
                headers=auth_headers(),
            )
            result3 = response3.json()
            if result3.get("code") == 0:
                print_result(f"扫描详情 (id={scan_id})", {
                    "status": result3["data"]["status"],
                    "score": result3["data"]["overall_score"],
                })

            return True
        else:
            print_result("健康扫描失败", result, success=False)
            return False
    except Exception as e:
        print_result(f"健康扫描异常: {e}", success=False)
        return False


# ============================================================
# 步骤 2：进化计划
# ============================================================

def step_2_evolution_plan():
    """创建进化计划并生成候选方案"""
    global plan_id, candidate_id
    print_step(2, "创建进化计划 → 生成候选方案 → 选择方案")

    try:
        # 2.1 创建进化计划（文档完善型）
        plan_data = {
            "title": "M5 潮汐记忆系统文档完善",
            "description": "完善 M5 模块的 API 文档和使用指南，提升开发者体验",
            "type": "doc_improvement",
            "module_key": "m5",
            "priority": "medium",
            "risk_level": "low",
            "expected_effect": "文档覆盖率提升至 95%，新成员上手成本降低 40%",
        }
        response = httpx.post(
            f"{BASE_URL}/api/evo/planner/plans",
            json=plan_data,
            headers=auth_headers(),
        )
        result = response.json()

        if result.get("code") == 0:
            plan = result["data"]
            plan_id = plan["plan_id"]
            print_result("进化计划创建成功", {
                "plan_id": plan_id,
                "title": plan["title"],
                "type": plan["type"],
                "status": plan["status"],
            })
        else:
            print_result("进化计划创建失败", result, success=False)
            return False

        # 2.2 获取计划列表
        response_list = httpx.get(
            f"{BASE_URL}/api/evo/planner/plans",
            headers=auth_headers(),
        )
        result_list = response_list.json()
        if result_list.get("code") == 0:
            print_result("进化计划列表", {"total": result_list["data"]["total"]})

        # 2.3 生成候选方案
        response2 = httpx.post(
            f"{BASE_URL}/api/evo/planner/plans/{plan_id}/generate",
            headers=auth_headers(),
        )
        result2 = response2.json()

        if result2.get("code") == 0:
            candidates = result2["data"]["candidates"]
            print_result(f"生成候选方案", {
                "count": result2["data"]["count"],
                "candidates": [c["name"] for c in candidates],
            })

            # 2.4 获取候选方案列表
            response3 = httpx.get(
                f"{BASE_URL}/api/evo/planner/plans/{plan_id}/candidates",
                headers=auth_headers(),
            )
            result3 = response3.json()
            if result3.get("code") == 0:
                items = result3["data"]["items"]
                print_result(f"候选方案列表", {"total": result3["data"]["total"]})

                # 选择第一个方案
                if items:
                    candidate_id = items[0]["candidate_id"]

                    # 2.5 选择方案
                    response4 = httpx.post(
                        f"{BASE_URL}/api/evo/planner/plans/{plan_id}/select",
                        json={"candidate_id": candidate_id},
                        headers=auth_headers(),
                    )
                    result4 = response4.json()
                    if result4.get("code") == 0:
                        print_result(f"方案已选定", {
                            "selected_candidate": result4["data"]["selected_candidate"]["name"],
                            "plan_status": result4["data"]["plan"]["status"],
                        })
                        return True
                    else:
                        print_result("方案选择失败", result4, success=False)
        else:
            print_result("候选方案生成失败", result2, success=False)

    except Exception as e:
        print_result(f"进化计划异常: {e}", success=False)

    return False


# ============================================================
# 步骤 3：安全审计
# ============================================================

def step_3_security_audit():
    """启动安全审计"""
    global audit_report_id
    print_step(3, "启动安全审计 → 生成审计报告")

    try:
        # 3.1 启动安全审计
        response = httpx.post(
            f"{BASE_URL}/api/evo/auditor/audit/{plan_id}",
            headers=auth_headers(),
            timeout=30,
        )
        result = response.json()

        if result.get("code") == 0:
            report = result["data"]["report"]
            audit_report_id = report["id"]
            print_result("安全审计完成", {
                "report_id": audit_report_id,
                "risk_level": report["risk_level"],
                "recommendation": report["recommendation"],
                "issues_count": len(report.get("issues", [])),
                "code_security": report["code_security_result"].get("status", "unknown"),
                "dependency_security": report["dependency_security_result"].get("status", "unknown"),
                "permission_check": report["permission_check_result"],
                "data_security": report["data_security_result"],
            })

            # 3.2 获取审计报告列表
            response2 = httpx.get(
                f"{BASE_URL}/api/evo/auditor/reports",
                headers=auth_headers(),
            )
            result2 = response2.json()
            if result2.get("code") == 0:
                print_result("审计报告列表", {"total": result2["data"]["total"]})

            # 3.3 获取审计报告详情
            response3 = httpx.get(
                f"{BASE_URL}/api/evo/auditor/reports/{audit_report_id}",
                headers=auth_headers(),
            )
            result3 = response3.json()
            if result3.get("code") == 0:
                print_result(f"审计报告详情", {
                    "risk_level": result3["data"]["risk_level"],
                    "recommendation": result3["data"]["recommendation"],
                    "plan_title": result3["data"].get("plan", {}).get("title", ""),
                })

            return True
        else:
            print_result("安全审计失败", result, success=False)
            return False
    except Exception as e:
        print_result(f"安全审计异常: {e}", success=False)
        return False


# ============================================================
# 步骤 4：审批 → 部署 → 生成版本记录
# ============================================================

def step_4_deploy():
    """审批并部署"""
    global approval_id, version_id
    print_step(4, "审批 → 部署 → 生成版本记录")

    try:
        # 直接执行部署（MVP 会自动创建审批记录）
        response = httpx.post(
            f"{BASE_URL}/api/evo/deployer/deploy/{plan_id}",
            headers=auth_headers(),
            timeout=30,
        )
        result = response.json()

        if result.get("code") == 0:
            deploy_data = result["data"]
            version_id = deploy_data["version"]["version_id"]
            print_result("部署完成", {
                "plan_status": deploy_data["plan"]["status"],
                "version_id": version_id,
                "version_name": deploy_data["version"]["version_name"],
                "evo_sequence": deploy_data["version"]["evo_sequence"],
                "module_key": deploy_data["deploy_info"]["module_key"],
            })

            # 4.2 获取审批列表
            response2 = httpx.get(
                f"{BASE_URL}/api/evo/deployer/approvals?plan_id={plan_id}",
                headers=auth_headers(),
            )
            result2 = response2.json()
            if result2.get("code") == 0:
                items = result2["data"]["items"]
                if items:
                    approval_id = items[0]["id"]
                    print_result(f"审批列表", {
                        "total": result2["data"]["total"],
                        "latest_status": items[0]["status"],
                    })

            # 4.3 获取版本列表
            response3 = httpx.get(
                f"{BASE_URL}/api/evo/deployer/versions/m5",
                headers=auth_headers(),
            )
            result3 = response3.json()
            if result3.get("code") == 0:
                print_result(f"M5 版本列表", {
                    "total": result3["data"]["total"],
                    "versions": [v["version_name"] for v in result3["data"]["items"]],
                })

            # 4.4 获取版本详情
            response4 = httpx.get(
                f"{BASE_URL}/api/evo/deployer/versions/id/{version_id}",
                headers=auth_headers(),
            )
            result4 = response4.json()
            if result4.get("code") == 0:
                print_result(f"版本详情", {
                    "version_name": result4["data"]["version_name"],
                    "status": result4["data"]["status"],
                    "plan_title": result4["data"].get("plan", {}).get("title", ""),
                })

            return True
        else:
            print_result("部署失败", result, success=False)
            return False
    except Exception as e:
        print_result(f"部署异常: {e}", success=False)
        return False


# ============================================================
# 步骤 5：回滚测试
# ============================================================

def step_5_rollback():
    """一键回滚测试"""
    print_step(5, "一键回滚测试")

    try:
        # 创建第二个进化计划并部署，以便有版本可回滚
        plan_data2 = {
            "title": "M5 模块测试增强计划",
            "description": "为 M5 模块补充单元测试，提升代码质量和稳定性",
            "type": "test_enhancement",
            "module_key": "m5",
            "priority": "medium",
            "risk_level": "low",
            "expected_effect": "测试覆盖率提升至 80%",
        }
        response = httpx.post(
            f"{BASE_URL}/api/evo/planner/plans",
            json=plan_data2,
            headers=auth_headers(),
        )
        result = response.json()
        if result.get("code") != 0:
            print_result("创建第二个计划失败", result, success=False)
            return False

        plan2_id = result["data"]["plan_id"]

        # 生成候选方案
        httpx.post(
            f"{BASE_URL}/api/evo/planner/plans/{plan2_id}/generate",
            headers=auth_headers(),
        )

        # 获取候选并选择
        cand_resp = httpx.get(
            f"{BASE_URL}/api/evo/planner/plans/{plan2_id}/candidates",
            headers=auth_headers(),
        )
        cand_result = cand_resp.json()
        if cand_result.get("code") == 0 and cand_result["data"]["items"]:
            cand_id = cand_result["data"]["items"][0]["candidate_id"]
            httpx.post(
                f"{BASE_URL}/api/evo/planner/plans/{plan2_id}/select",
                json={"candidate_id": cand_id},
                headers=auth_headers(),
            )

        # 部署第二个版本
        deploy_resp = httpx.post(
            f"{BASE_URL}/api/evo/deployer/deploy/{plan2_id}",
            headers=auth_headers(),
        )
        deploy_result = deploy_resp.json()
        if deploy_result.get("code") != 0:
            print_result("部署第二个版本失败", deploy_result, success=False)
            return False

        version2_id = deploy_result["data"]["version"]["version_id"]
        print_result("第二个版本部署成功", {
            "version_id": version2_id,
            "version_name": deploy_result["data"]["version"]["version_name"],
            "evo_sequence": deploy_result["data"]["version"]["evo_sequence"],
        })

        # 5.1 执行回滚
        rollback_resp = httpx.post(
            f"{BASE_URL}/api/evo/deployer/rollback/m5",
            json={"reason": "验证回滚功能 - 测试"},
            headers=auth_headers(),
        )
        rollback_result = rollback_resp.json()

        if rollback_result.get("code") == 0:
            rollback_data = rollback_result["data"]
            print_result("回滚成功", {
                "from_version": rollback_data["from_version"]["version_name"],
                "to_version": rollback_data["to_version"]["version_name"],
                "reason": rollback_data["rollback"]["reason"],
                "verification_result": rollback_data["rollback"]["verification_result"],
            })

            # 5.2 验证版本状态
            versions_resp = httpx.get(
                f"{BASE_URL}/api/evo/deployer/versions/m5",
                headers=auth_headers(),
            )
            versions_result = versions_resp.json()
            if versions_result.get("code") == 0:
                stable_versions = [
                    v for v in versions_result["data"]["items"]
                    if v["status"] == "stable"
                ]
                rolled_back = [
                    v for v in versions_result["data"]["items"]
                    if v["status"] == "rolled_back"
                ]
                print_result("版本状态验证", {
                    "stable_count": len(stable_versions),
                    "rolled_back_count": len(rolled_back),
                    "latest_stable": stable_versions[0]["version_name"] if stable_versions else "none",
                })

            # 5.3 查看回滚历史
            history_resp = httpx.get(
                f"{BASE_URL}/api/evo/deployer/rollbacks/m5",
                headers=auth_headers(),
            )
            history_result = history_resp.json()
            if history_result.get("code") == 0:
                print_result("回滚历史", {"total": history_result["data"]["total"]})

            return True
        else:
            print_result("回滚失败", rollback_result, success=False)
            return False

    except Exception as e:
        print_result(f"回滚测试异常: {e}", success=False)
        return False


# ============================================================
# 主函数
# ============================================================

def main():
    """运行完整验证流程"""
    print("\n" + "█" * 60)
    print("█" + " " * 58 + "█")
    print("█       自进化引擎 MVP - 核心流程验证脚本              █")
    print("█" + " " * 58 + "█")
    print("█" * 60)
    print(f"\n  目标地址: {BASE_URL}")
    print(f"  测试账号: admin / admin123456")

    results = {}

    # 检查服务是否可用
    print("\n  检查服务连接...", end=" ")
    try:
        httpx.get(f"{BASE_URL}/health", timeout=5)
        print("✓ 服务运行中")
    except Exception:
        print("✗ 服务不可用")
        print(f"\n  请先启动后端服务:")
        print(f"    cd backend")
        print(f"    uvicorn main:app --host 0.0.0.0 --port 8080 --reload")
        print()
        return

    # 登录
    if not login():
        print("\n✗ 登录失败，无法继续测试")
        return

    # 步骤 1：健康扫描
    results["step1_health_scan"] = step_1_health_scan()

    # 步骤 2：进化计划
    results["step2_evolution_plan"] = step_2_evolution_plan()

    # 步骤 3：安全审计
    results["step3_security_audit"] = step_3_security_audit()

    # 步骤 4：部署
    results["step4_deploy"] = step_4_deploy()

    # 步骤 5：回滚
    results["step5_rollback"] = step_5_rollback()

    # 汇总
    print("\n" + "=" * 60)
    print("  测试结果汇总")
    print("=" * 60)

    passed = 0
    failed = 0
    step_names = {
        "step1_health_scan": "健康扫描",
        "step2_evolution_plan": "进化计划（创建→候选→选择）",
        "step3_security_audit": "安全审计",
        "step4_deploy": "部署治理（审批→部署→版本）",
        "step5_rollback": "回滚测试",
    }

    for key, name in step_names.items():
        status = "✓ 通过" if results.get(key) else "✗ 失败"
        print(f"  {status}  {name}")
        if results.get(key):
            passed += 1
        else:
            failed += 1

    print(f"\n  总计: {passed}/{len(step_names)} 通过, {failed} 失败")

    if failed == 0:
        print("\n  所有测试通过！自进化引擎 MVP 核心流程运行正常。")
    else:
        print(f"\n  有 {failed} 项测试失败，请检查相关功能。")

    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
