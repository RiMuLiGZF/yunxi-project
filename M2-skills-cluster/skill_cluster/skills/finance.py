from __future__ import annotations

"""记账本技能."""

import os
import sqlite3
import uuid
from datetime import datetime
from typing import Any

import structlog

from skill_cluster.interfaces import (
    ISkill,
    SkillInvokeRequest,
    SkillInvokeResult,
    SkillManifest,
)

logger = structlog.get_logger()


class FinanceSkill(ISkill):
    """记账本技能，支持收支记录、分类统计、月度汇总、预算管理."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            skill_id="skill.finance",
            name="记账本",
            version="1.0.0",
            description="简单记账工具，支持收支记录、分类统计、月度汇总、预算管理",
            author="yunxi",
            tags=["finance", "money", "budget"],
            capabilities=["add_record", "list", "stats", "categories", "monthly_summary", "budget"],
            permissions=["read_file", "write"],
            entrypoint="FinanceSkill",
        )
        super().__init__(manifest)
        self._config: dict[str, Any] = {}
        self._db_path = os.path.expanduser("~/.yunxi/data/finance.db")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """初始化数据库表结构."""
        with sqlite3.connect(self._db_path) as conn:
            # 交易记录表
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS transactions (
                    txn_id TEXT PRIMARY KEY,
                    type TEXT,
                    amount REAL,
                    category TEXT,
                    description TEXT,
                    date TEXT,
                    created_at TEXT
                )
                """
            )
            # 预算表
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS budgets (
                    budget_id TEXT PRIMARY KEY,
                    category TEXT,
                    amount REAL,
                    period TEXT,
                    month TEXT,
                    created_at TEXT
                )
                """
            )
            conn.commit()

    async def invoke(self, request: SkillInvokeRequest) -> SkillInvokeResult:
        """技能调用分发入口."""
        action = request.action
        params = request.params
        start = __import__("time").perf_counter()

        try:
            if action == "add_record":
                data = self._add_record(params)
            elif action == "list":
                data = self._list(params)
            elif action == "stats":
                data = self._stats(params)
            elif action == "categories":
                data = self._categories(params)
            elif action == "monthly_summary":
                data = self._monthly_summary(params)
            elif action == "budget":
                data = self._budget(params)
            else:
                return self._error(request, f"Unknown action: {action}", start)

            latency = (__import__("time").perf_counter() - start) * 1000
            return SkillInvokeResult(
                skill_id=self.manifest.skill_id,
                action=action,
                status="success",
                data=data,
                latency_ms=latency,
                trace_id=request.trace_id,
            )
        except Exception as e:
            return self._error(request, str(e), start)

    # ------------------------------ 动作：记一笔 ------------------------------

    def _add_record(self, params: dict[str, Any]) -> dict[str, Any]:
        """添加一笔收支记录.

        Args:
            params:
                - type: 类型（income/expense）
                - amount: 金额
                - category: 分类（如餐饮、交通、工资等）
                - description: 描述（可选）
                - date: 日期 ISO 格式（可选，默认今天）

        Returns:
            创建结果及记录信息
        """
        txn_id = str(uuid.uuid4())
        txn_type = params.get("type", "expense")
        if txn_type not in ("income", "expense"):
            raise ValueError("type must be 'income' or 'expense'")

        amount = float(params.get("amount", 0))
        if amount <= 0:
            raise ValueError("amount must be positive")

        category = params.get("category", "其他")
        description = params.get("description", "")
        date_str = params.get("date") or datetime.now().strftime("%Y-%m-%d")
        now = datetime.now().isoformat()

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO transactions (txn_id, type, amount, category, description, date, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (txn_id, txn_type, amount, category, description, date_str, now),
            )
            conn.commit()

        return {
            "txn_id": txn_id,
            "created": True,
            "type": txn_type,
            "amount": amount,
            "category": category,
        }

    # ------------------------------ 动作：记录列表 ------------------------------

    def _list(self, params: dict[str, Any]) -> dict[str, Any]:
        """获取交易记录列表，支持日期范围、分类、类型筛选.

        Args:
            params:
                - start_date: 开始日期（可选，YYYY-MM-DD）
                - end_date: 结束日期（可选，YYYY-MM-DD）
                - category: 分类筛选（可选）
                - type: 类型筛选（income/expense，可选）
                - limit: 返回数量限制（可选，默认 50）
                - offset: 偏移量（可选，默认 0）
                - sort_by: 排序字段（可选，默认 date）
                - sort_order: 排序方向 asc/desc（可选，默认 desc）

        Returns:
            记录列表及总数
        """
        start_date = params.get("start_date")
        end_date = params.get("end_date")
        category = params.get("category")
        txn_type = params.get("type")
        limit = int(params.get("limit", 50))
        offset = int(params.get("offset", 0))
        sort_by = params.get("sort_by", "date")
        sort_order = params.get("sort_order", "desc")

        # 允许的排序字段白名单
        allowed_sort = {"date", "amount", "created_at", "category"}
        if sort_by not in allowed_sort:
            sort_by = "date"
        if sort_order not in ("asc", "desc"):
            sort_order = "desc"

        query = """
            SELECT txn_id, type, amount, category, description, date, created_at
            FROM transactions
            WHERE 1=1
        """
        count_query = "SELECT COUNT(*) FROM transactions WHERE 1=1"
        args: list[Any] = []
        count_args: list[Any] = []

        if start_date:
            query += " AND date >= ?"
            count_query += " AND date >= ?"
            args.append(start_date)
            count_args.append(start_date)

        if end_date:
            query += " AND date <= ?"
            count_query += " AND date <= ?"
            args.append(end_date)
            count_args.append(end_date)

        if category:
            query += " AND category = ?"
            count_query += " AND category = ?"
            args.append(category)
            count_args.append(category)

        if txn_type:
            query += " AND type = ?"
            count_query += " AND type = ?"
            args.append(txn_type)
            count_args.append(txn_type)

        query += f" ORDER BY {sort_by} {sort_order} LIMIT ? OFFSET ?"
        args.extend([limit, offset])

        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(query, args).fetchall()
            total = conn.execute(count_query, count_args).fetchone()[0]

        transactions = [
            {
                "txn_id": r[0],
                "type": r[1],
                "amount": r[2],
                "category": r[3],
                "description": r[4] or "",
                "date": r[5],
                "created_at": r[6],
            }
            for r in rows
        ]

        return {
            "transactions": transactions,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    # ------------------------------ 动作：统计 ------------------------------

    def _stats(self, params: dict[str, Any]) -> dict[str, Any]:
        """获取收支统计数据.

        Args:
            params:
                - start_date: 开始日期（可选）
                - end_date: 结束日期（可选）

        Returns:
            结构化统计数据（总支出、总收入、结余、分类占比）
        """
        start_date = params.get("start_date")
        end_date = params.get("end_date")

        base_where = "WHERE 1=1"
        args: list[Any] = []

        if start_date:
            base_where += " AND date >= ?"
            args.append(start_date)

        if end_date:
            base_where += " AND date <= ?"
            args.append(end_date)

        with sqlite3.connect(self._db_path) as conn:
            # 总收入
            income_row = conn.execute(
                f"SELECT COALESCE(SUM(amount), 0), COUNT(*) FROM transactions {base_where} AND type = 'income'",
                args,
            ).fetchone()
            total_income = income_row[0]
            income_count = income_row[1]

            # 总支出
            expense_row = conn.execute(
                f"SELECT COALESCE(SUM(amount), 0), COUNT(*) FROM transactions {base_where} AND type = 'expense'",
                args,
            ).fetchone()
            total_expense = expense_row[0]
            expense_count = expense_row[1]

            # 支出分类占比
            category_rows = conn.execute(
                f"""
                SELECT category, COALESCE(SUM(amount), 0) as total
                FROM transactions
                {base_where} AND type = 'expense'
                GROUP BY category
                ORDER BY total DESC
                """,
                args,
            ).fetchall()

            # 收入分类占比
            income_category_rows = conn.execute(
                f"""
                SELECT category, COALESCE(SUM(amount), 0) as total
                FROM transactions
                {base_where} AND type = 'income'
                GROUP BY category
                ORDER BY total DESC
                """,
                args,
            ).fetchall()

        balance = total_income - total_expense

        # 计算支出分类占比
        expense_by_category = []
        for r in category_rows:
            percentage = round(r[1] / total_expense * 100, 2) if total_expense > 0 else 0.0
            expense_by_category.append({
                "category": r[0],
                "amount": r[1],
                "percentage": percentage,
            })

        # 计算收入分类占比
        income_by_category = []
        for r in income_category_rows:
            percentage = round(r[1] / total_income * 100, 2) if total_income > 0 else 0.0
            income_by_category.append({
                "category": r[0],
                "amount": r[1],
                "percentage": percentage,
            })

        return {
            "total_income": round(total_income, 2),
            "total_expense": round(total_expense, 2),
            "balance": round(balance, 2),
            "income_count": income_count,
            "expense_count": expense_count,
            "expense_by_category": expense_by_category,
            "income_by_category": income_by_category,
            "start_date": start_date,
            "end_date": end_date,
        }

    # ------------------------------ 动作：常用分类 ------------------------------

    def _categories(self, params: dict[str, Any]) -> dict[str, Any]:
        """获取常用分类列表及使用次数.

        Args:
            params:
                - type: 类型筛选（income/expense，可选，默认统计全部）

        Returns:
            分类列表及使用次数
        """
        txn_type = params.get("type")

        query = """
            SELECT category, COUNT(*) as cnt, COALESCE(SUM(amount), 0) as total_amount
            FROM transactions
            WHERE 1=1
        """
        args: list[Any] = []

        if txn_type:
            query += " AND type = ?"
            args.append(txn_type)

        query += " GROUP BY category ORDER BY cnt DESC"

        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(query, args).fetchall()

        categories = [
            {
                "category": r[0],
                "count": r[1],
                "total_amount": round(r[2], 2),
            }
            for r in rows
        ]

        # 预设常用分类（当没有数据时返回）
        if not categories:
            if txn_type == "income":
                default_categories = ["工资", "奖金", "投资收益", "兼职", "其他收入"]
            elif txn_type == "expense":
                default_categories = ["餐饮", "交通", "购物", "娱乐", "住房", "医疗", "教育", "其他"]
            else:
                default_categories = []
            categories = [{"category": c, "count": 0, "total_amount": 0.0} for c in default_categories]

        return {"categories": categories, "total_categories": len(categories)}

    # ------------------------------ 动作：月度汇总 ------------------------------

    def _monthly_summary(self, params: dict[str, Any]) -> dict[str, Any]:
        """获取月度汇总（某月的收支详情）.

        Args:
            params:
                - month: 月份（格式：YYYY-MM，可选，默认本月）

        Returns:
            月度汇总数据
        """
        month = params.get("month") or datetime.now().strftime("%Y-%m")
        start_date = f"{month}-01"

        # 计算该月的最后一天
        year, month_num = int(month[:4]), int(month[5:7])
        if month_num == 12:
            next_month_year = year + 1
            next_month_num = 1
        else:
            next_month_year = year
            next_month_num = month_num + 1
        from datetime import timedelta as td
        end_date = (datetime(next_month_year, next_month_num, 1) - td(days=1)).strftime("%Y-%m-%d")

        # 复用 stats 逻辑
        stats_params = {"start_date": start_date, "end_date": end_date}
        stats_data = self._stats(stats_params)

        # 每日收支明细
        with sqlite3.connect(self._db_path) as conn:
            daily_rows = conn.execute(
                """
                SELECT date, type, COALESCE(SUM(amount), 0) as total
                FROM transactions
                WHERE date >= ? AND date <= ?
                GROUP BY date, type
                ORDER BY date ASC
                """,
                (start_date, end_date),
            ).fetchall()

        # 整理每日数据
        daily_data: dict[str, dict[str, float]] = {}
        for r in daily_rows:
            date = r[0]
            txn_type = r[1]
            amount = r[2]
            if date not in daily_data:
                daily_data[date] = {"income": 0.0, "expense": 0.0}
            daily_data[date][txn_type] = amount

        daily_list = []
        for date in sorted(daily_data.keys()):
            d = daily_data[date]
            daily_list.append({
                "date": date,
                "income": round(d["income"], 2),
                "expense": round(d["expense"], 2),
                "balance": round(d["income"] - d["expense"], 2),
            })

        return {
            "month": month,
            "start_date": start_date,
            "end_date": end_date,
            "total_income": stats_data["total_income"],
            "total_expense": stats_data["total_expense"],
            "balance": stats_data["balance"],
            "income_count": stats_data["income_count"],
            "expense_count": stats_data["expense_count"],
            "expense_by_category": stats_data["expense_by_category"],
            "income_by_category": stats_data["income_by_category"],
            "daily_summary": daily_list,
        }

    # ------------------------------ 动作：预算管理 ------------------------------

    def _budget(self, params: dict[str, Any]) -> dict[str, Any]:
        """预算管理：设置/查看/超额提醒.

        Args:
            params:
                - action: "list" / "set" / "delete" / "check"
                - category: 分类（set/delete 必填）
                - amount: 预算金额（set 必填）
                - month: 月份（可选，默认本月，格式 YYYY-MM）
                - budget_id: 预算 ID（delete 可选）

        Returns:
            预算列表或操作结果
        """
        sub_action = params.get("action", "list")

        if sub_action == "set":
            return self._set_budget(params)
        elif sub_action == "delete":
            return self._delete_budget(params)
        elif sub_action == "check":
            return self._check_budget(params)

        # list 模式
        month = params.get("month") or datetime.now().strftime("%Y-%m")

        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT budget_id, category, amount, period, month, created_at
                FROM budgets
                WHERE month = ?
                ORDER BY category ASC
                """,
                (month,),
            ).fetchall()

        budgets = [
            {
                "budget_id": r[0],
                "category": r[1],
                "amount": r[2],
                "period": r[3],
                "month": r[4],
                "created_at": r[5],
            }
            for r in rows
        ]

        return {"budgets": budgets, "month": month, "total": len(budgets)}

    def _set_budget(self, params: dict[str, Any]) -> dict[str, Any]:
        """设置预算（已存在则更新）."""
        category = params.get("category", "")
        amount = float(params.get("amount", 0))
        month = params.get("month") or datetime.now().strftime("%Y-%m")
        period = params.get("period", "monthly")

        if not category:
            raise ValueError("category is required")
        if amount < 0:
            raise ValueError("amount must be non-negative")

        now = datetime.now().isoformat()

        with sqlite3.connect(self._db_path) as conn:
            # 检查是否已存在该月该分类的预算
            row = conn.execute(
                "SELECT budget_id FROM budgets WHERE category = ? AND month = ?",
                (category, month),
            ).fetchone()

            if row:
                budget_id = row[0]
                conn.execute(
                    "UPDATE budgets SET amount = ? WHERE budget_id = ?",
                    (amount, budget_id),
                )
                created = False
            else:
                budget_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO budgets (budget_id, category, amount, period, month, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (budget_id, category, amount, period, month, now),
                )
                created = True

            conn.commit()

        return {
            "budget_id": budget_id,
            "category": category,
            "amount": amount,
            "month": month,
            "created": created,
        }

    def _delete_budget(self, params: dict[str, Any]) -> dict[str, Any]:
        """删除预算."""
        budget_id = params.get("budget_id", "")
        category = params.get("category", "")
        month = params.get("month") or datetime.now().strftime("%Y-%m")

        with sqlite3.connect(self._db_path) as conn:
            if budget_id:
                conn.execute("DELETE FROM budgets WHERE budget_id = ?", (budget_id,))
            elif category:
                conn.execute(
                    "DELETE FROM budgets WHERE category = ? AND month = ?",
                    (category, month),
                )
            else:
                raise ValueError("budget_id or category is required")
            conn.commit()

        return {"deleted": True, "budget_id": budget_id, "category": category}

    def _check_budget(self, params: dict[str, Any]) -> dict[str, Any]:
        """检查预算使用情况，返回超额提醒."""
        month = params.get("month") or datetime.now().strftime("%Y-%m")
        start_date = f"{month}-01"

        with sqlite3.connect(self._db_path) as conn:
            # 获取当月所有预算
            budget_rows = conn.execute(
                "SELECT budget_id, category, amount FROM budgets WHERE month = ?",
                (month,),
            ).fetchall()

            # 获取当月支出按分类汇总
            expense_rows = conn.execute(
                """
                SELECT category, COALESCE(SUM(amount), 0) as spent
                FROM transactions
                WHERE date >= ? AND type = 'expense'
                GROUP BY category
                """,
                (start_date,),
            ).fetchall()

        # 构造支出字典
        spent_by_category: dict[str, float] = {r[0]: r[1] for r in expense_rows}

        budget_status = []
        over_budget = []
        warning = []

        for r in budget_rows:
            budget_id, category, budget_amount = r
            spent = spent_by_category.get(category, 0.0)
            remaining = budget_amount - spent
            usage_percent = round(spent / budget_amount * 100, 2) if budget_amount > 0 else 0.0

            status_info = {
                "budget_id": budget_id,
                "category": category,
                "budget": budget_amount,
                "spent": round(spent, 2),
                "remaining": round(remaining, 2),
                "usage_percent": usage_percent,
            }

            if spent >= budget_amount:
                status_info["status"] = "over"
                over_budget.append(status_info)
            elif usage_percent >= 80:
                status_info["status"] = "warning"
                warning.append(status_info)
            else:
                status_info["status"] = "normal"

            budget_status.append(status_info)

        # 按使用比例降序排列
        budget_status.sort(key=lambda x: x["usage_percent"], reverse=True)

        return {
            "month": month,
            "budget_status": budget_status,
            "over_budget_count": len(over_budget),
            "warning_count": len(warning),
            "over_budget": over_budget,
            "warning": warning,
        }

    # ------------------------------ 工具方法 ------------------------------

    def _error(self, request: SkillInvokeRequest, error: str, start: float) -> SkillInvokeResult:
        """构造错误返回结果."""
        latency = (__import__("time").perf_counter() - start) * 1000
        logger.error("finance_error", action=request.action, error=error, trace_id=request.trace_id)
        return SkillInvokeResult(
            skill_id=self.manifest.skill_id,
            action=request.action,
            status="failure",
            error=error,
            latency_ms=latency,
            trace_id=request.trace_id,
        )

    async def health(self) -> dict[str, Any]:
        """健康检查."""
        return {"healthy": True, "skill_id": self.manifest.skill_id}

    async def configure(self, config: dict[str, Any]) -> None:
        """配置技能."""
        self._config.update(config)
