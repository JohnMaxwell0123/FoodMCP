"""
证据回填脚本测试
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from scripts.backfill_evidence import backfill
from src.models.entities import SubtitleSegment, TranscriptResult


@pytest.mark.asyncio
async def test_backfill_verifies_quotes_from_cached_subtitles(tmp_path):
    """用缓存字幕为已入库评价回填核验结果与时间点；没有字幕缓存时只补发布日期"""
    transcript = TranscriptResult(
        video_bvid="BV_CACHED",
        source="ai",
        segments=[
            SubtitleSegment(start=5.0, end=9.0, text="今天来到这家馆子"),
            SubtitleSegment(start=42.0, end=46.0, text="宝塔肉蒸软蒸透了，皮很有胶质感"),
        ],
    )
    (tmp_path / "BV_CACHED.json").write_text(transcript.model_dump_json(), encoding="utf-8")

    pg = MagicMock()
    pg.list_reviews_for_backfill = AsyncMock(return_value=[
        {"id": "rv-1", "video_bvid": "BV_CACHED", "raw_text": "宝塔肉蒸软蒸透了",
         "timestamp": "", "timestamp_seconds": None, "quote_verified": False, "video_published_at": ""},
        {"id": "rv-2", "video_bvid": "BV_CACHED", "raw_text": "字幕里没有的一句话",
         "timestamp": "", "timestamp_seconds": None, "quote_verified": False, "video_published_at": ""},
        {"id": "rv-3", "video_bvid": "BV_NO_CACHE", "raw_text": "随便一句",
         "timestamp": "", "timestamp_seconds": None, "quote_verified": False, "video_published_at": ""},
    ])
    pg.update_review_evidence = AsyncMock()
    fetch_date = AsyncMock(side_effect=lambda bvid: "2024-05-01")

    stats = await backfill(pg, tmp_path, fetch_date)

    assert stats == {"total": 3, "verified": 1, "no_subtitle": 1}
    calls = {c.args[0]: c.args for c in pg.update_review_evidence.call_args_list}
    assert calls["rv-1"] == ("rv-1", "00:42", 42.0, True, "2024-05-01")
    assert calls["rv-2"] == ("rv-2", "", None, False, "2024-05-01")
    # 没有字幕缓存：保留原有核验结果，只补日期
    assert calls["rv-3"] == ("rv-3", "", None, False, "2024-05-01")
    assert fetch_date.call_count == 2  # 每个视频只查一次
