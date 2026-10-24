"""
餐后反馈汇总与可信度报告测试
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from scripts.trust_report import build_report, render_report
from src.evidence.feedback import diner_feedback_counts, north_star, summarize_up_feedback


def _row(report_id, up, up_verdict, diner_verdict, cuisine="川菜"):
    return {
        "report_id": report_id,
        "up_master_id": f"u-{up}",
        "up_name": up,
        "cuisine": cuisine,
        "up_verdict": up_verdict,
        "diner_verdict": diner_verdict,
    }


class TestUpFeedback:
    """UP 主说法与食客反馈的一致率"""

    def test_agreement_by_up_and_cuisine(self):
        rows = [
            _row("m1", "甲", "推荐", "推荐", "川菜"),
            _row("m2", "甲", "推荐", "踩雷", "川菜"),
            _row("m3", "甲", "推荐", "推荐", "粤菜"),
            _row("m4", "乙", "一般", "一般"),
        ]
        summary = {s["up"]: s for s in summarize_up_feedback(rows, min_reports=2)}

        assert summary["甲"]["reports"] == 3
        assert summary["甲"]["agreement_rate"] == "66.7%"
        assert summary["甲"]["by_cuisine"][0] == {
            "cuisine": "川菜", "reports": 2, "agreement_rate": "50.0%",
        }
        assert "note" not in summary["甲"]
        # 反馈少于门槛时提示仅供参考
        assert "仅供参考" in summary["乙"]["note"]

    def test_empty_feedback(self):
        assert summarize_up_feedback([]) == []


class TestNorthStar:
    """北极星：照推荐去吃之后没有踩雷的比例，按一顿饭计"""

    def test_one_meal_counts_once_even_with_several_claims(self):
        rows = [
            # 一顿饭同时验证了两位 UP 主的推荐，结果踩雷：只算一次
            _row("meal-1", "甲", "推荐", "踩雷"),
            _row("meal-1", "乙", "推荐", "踩雷"),
            _row("meal-2", "甲", "推荐", "推荐"),
            # 没有照推荐去吃（UP 主说的是"一般"），不进入北极星分母
            _row("meal-3", "乙", "一般", "踩雷"),
        ]
        result = north_star(rows)
        assert result == {
            "feedback_reports": 3,
            "followed_recommendations": 2,
            "regretted": 1,
            "no_regret_rate": "50.0%",
        }

    def test_no_feedback_yet(self):
        assert north_star([])["no_regret_rate"] == "N/A"


def test_diner_feedback_counts_per_claim():
    rows = [
        {"review_id": "rv-1", "diner_verdict": "推荐"},
        {"review_id": "rv-1", "diner_verdict": "一般"},
        {"review_id": "rv-2", "diner_verdict": "踩雷"},
    ]
    assert diner_feedback_counts(rows) == {
        "rv-1": {"liked": 1, "neutral": 1, "disliked": 0},
        "rv-2": {"liked": 0, "neutral": 0, "disliked": 1},
    }


@pytest.mark.asyncio
async def test_trust_report_combines_verifiability_and_feedback():
    pg = MagicMock()
    pg.get_verification_stats = AsyncMock(return_value={"total": 11, "verified": 9})
    pg.get_feedback_rows = AsyncMock(return_value=[
        _row("meal-1", "甲", "推荐", "推荐"),
        _row("meal-2", "甲", "推荐", "踩雷"),
    ])

    report = await build_report(pg)

    assert report["verifiable"] == {"reviews": 11, "verified": 9, "rate": "81.8%"}
    assert report["north_star"]["no_regret_rate"] == "50.0%"
    text = render_report(report)
    assert "可核对率（领先指标）: 81.8%" in text
    assert "北极星（照推荐去吃没有踩雷）: 50.0%" in text
    assert "甲: 50.0%" in text
