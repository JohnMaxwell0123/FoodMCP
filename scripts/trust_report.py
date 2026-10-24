"""
可信度报告

把 PORTFOLIO 第六章里的指标算出来：
  - 可核对率：原话能在字幕中找到的评价占比（领先指标，形态内即可观测）
  - 北极星：照推荐去吃之后没有踩雷的比例（需要 Agent 代收的餐后反馈）
  - 每位 UP 主的说法与食客反馈的一致率，按菜系拆分

用法:
  python -m scripts.trust_report
"""

from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import click

from src.evidence.feedback import north_star, summarize_up_feedback


async def build_report(pg) -> dict:
    """从已连接的 PostgresStore 计算可信度报告"""
    stats = await pg.get_verification_stats()
    total, verified = stats["total"], stats["verified"]
    rows = await pg.get_feedback_rows()
    return {
        "verifiable": {
            "reviews": total,
            "verified": verified,
            "rate": f"{verified / total * 100:.1f}%" if total else "N/A",
        },
        "north_star": north_star(rows),
        "up_feedback": summarize_up_feedback(rows),
    }


def render_report(report: dict) -> str:
    """把报告渲染成终端文本"""
    v = report["verifiable"]
    ns = report["north_star"]
    lines = [
        "=" * 60,
        "FoodMCP 可信度报告",
        "=" * 60,
        f"可核对率（领先指标）: {v['rate']}  "
        f"({v['verified']}/{v['reviews']} 条评价的原话能在字幕中找到)",
        "",
        f"北极星（照推荐去吃没有踩雷）: {ns['no_regret_rate']}",
        f"  餐后反馈 {ns['feedback_reports']} 次，"
        f"其中照推荐去吃 {ns['followed_recommendations']} 次，踩雷 {ns['regretted']} 次",
    ]
    if not ns["feedback_reports"]:
        lines.append("  还没有餐后反馈：Agent 可以通过 report_dining_outcome 回写")

    lines += ["", "UP 主说法与食客反馈的一致率:"]
    if not report["up_feedback"]:
        lines.append("  暂无")
    for up in report["up_feedback"]:
        note = f"（{up['note']}）" if up.get("note") else ""
        lines.append(f"  {up['up']}: {up['agreement_rate']}，反馈 {up['reports']} 条{note}")
        for c in up["by_cuisine"]:
            lines.append(f"    - {c['cuisine']}: {c['agreement_rate']}（{c['reports']} 条）")
    lines.append("=" * 60)
    return "\n".join(lines)


async def _run() -> None:
    from src.storage.pg_store import PostgresStore

    pg = PostgresStore()
    await pg.connect()
    try:
        await pg.init_tables()  # 确保证据字段与反馈表已迁移
        report = await build_report(pg)
    finally:
        await pg.close()
    click.echo(render_report(report))


@click.command()
def main() -> None:
    """输出可核对率、北极星与 UP 主一致率"""
    asyncio.run(_run())


if __name__ == "__main__":
    main()
