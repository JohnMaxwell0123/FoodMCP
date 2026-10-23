"""
多 UP 主证据汇总

FoodMCP 不输出平均分：一个推荐加一个踩雷的均值是 0，和两个"一般"无法区分，
而"有人说好、有人说差"恰恰是用户最需要知道的。

这里按 UP 主计票：每位 UP 主对一道菜只算一票（取其最近一次评价，
管线重跑产生的重复评价因此也只算一次），并给出证据等级：
  - 孤证：只有一位 UP 主评价过
  - 共识：多位 UP 主结论一致
  - 争议：多位 UP 主结论不一致
"""

from __future__ import annotations

from typing import Any

from src.evidence.quotes import format_timestamp, video_url

VERDICTS: tuple[str, ...] = ("推荐", "一般", "踩雷")


def _recency(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("video_published_at") or ""), str(row.get("created_at") or ""))


def _evidence_item(row: dict[str, Any], verdict: str) -> dict[str, Any]:
    seconds = row.get("timestamp_seconds")
    return {
        "up": row.get("up_name", ""),
        "verdict": verdict,
        "quote": row.get("raw_text", ""),
        "quote_verified": bool(row.get("quote_verified")),
        "timestamp": format_timestamp(seconds),
        "video_url": video_url(row.get("video_bvid", ""), seconds),
        "published": row.get("video_published_at") or "",
        "review_id": row.get("id", ""),
    }


def summarize_dishes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    把评价行汇总为菜品级证据分布

    每行需要 dish_id/dish_name、up_master_id/up_name、sentiment、raw_text，
    可选 video_bvid、timestamp_seconds、quote_verified、video_published_at、created_at、id。
    """
    latest: dict[str, dict[str, dict[str, Any]]] = {}
    dish_names: dict[str, str] = {}
    for row in rows:
        dish_key = str(row.get("dish_id") or row.get("dish_name") or "")
        up_key = str(row.get("up_master_id") or row.get("up_name") or "")
        if not dish_key or not up_key:
            continue
        dish_names.setdefault(dish_key, row.get("dish_name") or "")
        by_up = latest.setdefault(dish_key, {})
        current = by_up.get(up_key)
        if current is None or _recency(row) > _recency(current):
            by_up[up_key] = row

    summaries: list[dict[str, Any]] = []
    for dish_key, by_up in latest.items():
        counts = {v: 0 for v in VERDICTS}
        evidence = []
        for row in by_up.values():
            verdict = row.get("sentiment") if row.get("sentiment") in VERDICTS else "一般"
            counts[verdict] += 1
            evidence.append(_evidence_item(row, verdict))

        up_count = len(by_up)
        if up_count == 1:
            level = "孤证"
        elif max(counts.values()) == up_count:
            level = "共识"
        else:
            level = "争议"

        evidence.sort(key=lambda e: (VERDICTS.index(e["verdict"]), e["up"]))
        summaries.append({
            "dish": dish_names[dish_key],
            "up_count": up_count,
            "verdict_counts": counts,
            "evidence_level": level,
            "evidence": evidence,
        })

    summaries.sort(key=lambda s: (-s["up_count"], s["dish"]))
    return summaries


def classify_dish(summary: dict[str, Any]) -> str:
    """
    把一道菜的证据分布归入红黑榜

      recommended       有人推荐、无人踩雷，且推荐不少于一般
      avoid             有人说踩雷、无人推荐，且踩雷不少于一般；至少一条踩雷原话已在字幕中核验
      avoid_unverified  同上，但踩雷原话都未能核验——只转述原话，不下"避雷"结论
      disputed          同时有人推荐、有人说踩雷
      neutral           其他

    推荐与踩雷的规则不对称：负面结论会让一家店背锅，所以要求更高的证据。
    """
    counts = summary["verdict_counts"]
    rec, avg, bad = counts["推荐"], counts["一般"], counts["踩雷"]
    if rec and bad:
        return "disputed"
    if bad and bad >= avg:
        verified = any(
            e["verdict"] == "踩雷" and e["quote_verified"] for e in summary["evidence"]
        )
        return "avoid" if verified else "avoid_unverified"
    if rec and rec >= avg:
        return "recommended"
    return "neutral"
