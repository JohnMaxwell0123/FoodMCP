"""
餐后反馈的汇总：UP 主说得准不准、照推荐去吃有没有踩雷

反馈由 Agent 代收（MCP 工具 report_dining_outcome），挂在具体的那条 UP 主说法上。
这里把它汇总成三类数字：
  - 每位 UP 主（及其在各菜系上）的说法与食客感受的一致率——第③层反向校准第②层的原始材料
  - 北极星：照推荐去吃之后没有踩雷的比例（按一顿饭计，而不是按说法计）
  - 每条说法收到的食客反馈分布——随证据一起返回给 Agent
"""

from __future__ import annotations

from typing import Any

# 工具入参 → 与 UP 主判定同一套标签
OUTCOME_TO_VERDICT: dict[str, str] = {"liked": "推荐", "neutral": "一般", "disliked": "踩雷"}
VERDICT_TO_OUTCOME: dict[str, str] = {v: k for k, v in OUTCOME_TO_VERDICT.items()}

# 少于这么多条反馈时只给出"仅供参考"的提示
MIN_REPORTS: int = 5


def _rate(numerator: int, denominator: int) -> str:
    return f"{numerator / denominator * 100:.1f}%" if denominator else "N/A"


def summarize_up_feedback(
    rows: list[dict[str, Any]], min_reports: int = MIN_REPORTS,
) -> list[dict[str, Any]]:
    """
    按 UP 主（及菜系）汇总食客反馈与 UP 主说法的一致率

    每行需要 up_master_id、up_name、cuisine、up_verdict、diner_verdict。
    """
    by_up: dict[str, dict[str, Any]] = {}
    for row in rows:
        up = by_up.setdefault(
            str(row["up_master_id"]),
            {"up": row.get("up_name", ""), "reports": 0, "agreed": 0, "by_cuisine": {}},
        )
        agreed = row["up_verdict"] == row["diner_verdict"]
        up["reports"] += 1
        up["agreed"] += agreed
        cuisine = up["by_cuisine"].setdefault(
            row.get("cuisine") or "其他", {"reports": 0, "agreed": 0}
        )
        cuisine["reports"] += 1
        cuisine["agreed"] += agreed

    summaries = []
    for up in by_up.values():
        summary: dict[str, Any] = {
            "up": up["up"],
            "reports": up["reports"],
            "agreement_rate": _rate(up["agreed"], up["reports"]),
            "by_cuisine": [
                {
                    "cuisine": name,
                    "reports": c["reports"],
                    "agreement_rate": _rate(c["agreed"], c["reports"]),
                }
                for name, c in sorted(up["by_cuisine"].items(), key=lambda x: -x[1]["reports"])
            ],
        }
        if up["reports"] < min_reports:
            summary["note"] = f"反馈少于 {min_reports} 条，仅供参考"
        summaries.append(summary)

    summaries.sort(key=lambda s: -s["reports"])
    return summaries


def north_star(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """
    北极星：照推荐去吃之后没有踩雷的比例

    一顿饭可能同时验证多位 UP 主的说法（多行共享一个 report_id），这里按 report_id 计一次。
    只要这顿饭对应的说法里有"推荐"，就算"照推荐去吃"；食客反馈为踩雷即算踩雷。
    每行需要 report_id、up_verdict、diner_verdict。
    """
    reports: dict[str, dict[str, bool]] = {}
    for row in rows:
        report = reports.setdefault(str(row["report_id"]), {"followed": False, "regret": False})
        if row["up_verdict"] == "推荐":
            report["followed"] = True
        if row["diner_verdict"] == "踩雷":
            report["regret"] = True

    followed = [r for r in reports.values() if r["followed"]]
    regretted = sum(1 for r in followed if r["regret"])
    return {
        "feedback_reports": len(reports),
        "followed_recommendations": len(followed),
        "regretted": regretted,
        "no_regret_rate": _rate(len(followed) - regretted, len(followed)),
    }


def diner_feedback_counts(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """每条 UP 主说法收到的食客反馈分布：{review_id: {liked, neutral, disliked}}"""
    counts: dict[str, dict[str, int]] = {}
    for row in rows:
        outcome = VERDICT_TO_OUTCOME.get(row["diner_verdict"])
        if outcome is None:
            continue
        bucket = counts.setdefault(
            str(row["review_id"]), {"liked": 0, "neutral": 0, "disliked": 0}
        )
        bucket[outcome] += 1
    return counts
