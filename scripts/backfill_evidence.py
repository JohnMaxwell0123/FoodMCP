"""
为已入库的评价回填证据字段

早期入库的评价没有原话核验结果和视频内时间点。本脚本用本地缓存的字幕（data/subtitles/{bvid}.json）
把每条原话对回字幕，回写 quote_verified / timestamp / timestamp_seconds；
加 --with-dates 时额外调用 B 站接口补全视频发布日期。
不重新调用 LLM，也不会产生重复评价。

用法:
  python -m scripts.backfill_evidence
  python -m scripts.backfill_evidence --with-dates
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import click
from loguru import logger

from config.settings import settings
from src.evidence.quotes import format_timestamp, locate_quote, published_date
from src.models.entities import TranscriptResult


def load_cached_transcript(cache_dir: Path, bvid: str) -> TranscriptResult | None:
    """读取 SubtitleExtractor 缓存的字幕"""
    path = cache_dir / f"{bvid}.json"
    if not path.exists():
        return None
    try:
        return TranscriptResult(**json.loads(path.read_text(encoding="utf-8")))
    except Exception as e:
        logger.warning(f"字幕缓存无法读取 [{bvid}]: {e}")
        return None


async def backfill(
    pg,
    cache_dir: Path,
    fetch_date: Callable[[str], Awaitable[str]] | None = None,
) -> dict[str, int]:
    """
    回填全部评价的证据字段

    Args:
        pg: 已连接的 PostgresStore
        cache_dir: 字幕缓存目录
        fetch_date: 可选，bvid → 发布日期 (YYYY-MM-DD)

    Returns:
        统计：total / verified / no_subtitle
    """
    rows = await pg.list_reviews_for_backfill()
    stats = {"total": 0, "verified": 0, "no_subtitle": 0}
    transcripts: dict[str, TranscriptResult | None] = {}
    dates: dict[str, str] = {}

    for row in rows:
        bvid = row["video_bvid"]
        if bvid not in transcripts:
            transcripts[bvid] = load_cached_transcript(cache_dir, bvid)
            if fetch_date and not row.get("video_published_at"):
                try:
                    dates[bvid] = await fetch_date(bvid)
                except Exception as e:
                    logger.warning(f"获取发布日期失败 [{bvid}]: {e}")

        stats["total"] += 1
        transcript = transcripts[bvid]
        if transcript is None:
            stats["no_subtitle"] += 1
            if dates.get(bvid):
                # 没有字幕缓存时只补日期，保留原有核验结果
                await pg.update_review_evidence(
                    row["id"],
                    row.get("timestamp") or "",
                    row.get("timestamp_seconds"),
                    bool(row.get("quote_verified")),
                    dates[bvid],
                )
            continue

        match = locate_quote(row["raw_text"], transcript)
        if match.verified:
            stats["verified"] += 1
        await pg.update_review_evidence(
            row["id"],
            format_timestamp(match.start_seconds),
            match.start_seconds,
            match.verified,
            dates.get(bvid, ""),
        )

    return stats


async def _run(with_dates: bool) -> None:
    from src.storage.pg_store import PostgresStore

    pg = PostgresStore()
    await pg.connect()
    await pg.init_tables()  # 确保证据字段已迁移

    fetch_date = None
    if with_dates:
        from src.collector.bilibili_client import BilibiliClient

        client = BilibiliClient()

        async def fetch_date(bvid: str) -> str:
            info = await client.get_video_info(bvid)
            await asyncio.sleep(BilibiliClient.REQUEST_DELAY)
            return published_date(info.get("pubdate"))

    try:
        stats = await backfill(pg, settings.data_dir / "subtitles", fetch_date)
    finally:
        await pg.close()

    total = stats["total"]
    rate = f"{stats['verified'] / total * 100:.1f}%" if total else "N/A"
    click.echo(
        f"回填完成：共 {total} 条评价，原话可核对 {stats['verified']} 条（可核对率 {rate}），"
        f"缺少字幕缓存 {stats['no_subtitle']} 条"
    )


@click.command()
@click.option("--with-dates", is_flag=True, help="调用 B 站接口补全视频发布日期")
def main(with_dates: bool) -> None:
    """为已入库评价回填原话核验结果、视频时间点与发布日期"""
    asyncio.run(_run(with_dates))


if __name__ == "__main__":
    main()
