"""
证据层测试：原话核验、时间点定位、多 UP 主证据汇总
"""

from src.evidence.consensus import classify_dish, summarize_dishes
from src.evidence.quotes import (
    format_timestamp,
    locate_quote,
    match_quote,
    published_date,
    video_url,
)
from src.models.entities import SubtitleSegment, TranscriptResult


def _transcript() -> TranscriptResult:
    segments = [
        SubtitleSegment(start=0.0, end=4.0, text="今天来到这家河鲜馆"),
        SubtitleSegment(start=61.2, end=64.0, text="这鱼肉真的好嫩，进嘴之后不用嚼"),
        SubtitleSegment(start=64.0, end=68.5, text="吃到最后还是有一点点土腥味"),
        SubtitleSegment(start=68.5, end=71.0, text="我能尝出来，你们不一定"),
    ]
    return TranscriptResult(
        video_bvid="BV1example",
        source="ai",
        segments=segments,
        full_text=" ".join(s.text for s in segments),
    )


class TestQuoteMatching:
    """原话核验：与评测的保真度共用同一套规则"""

    def test_exact_quote_is_verified(self):
        match = match_quote("鱼肉真的好嫩", "这鱼肉真的好嫩，进嘴之后不用嚼")
        assert match.checked and match.verified
        assert match.score == 100.0

    def test_minor_asr_difference_is_tolerated(self):
        match = match_quote("大肠处理的极为干净毫无异味", "九转大肠，大肠处理得极为干净，毫无异味")
        assert match.verified
        assert 80.0 <= match.score < 100.0

    def test_fabricated_quote_is_rejected(self):
        match = match_quote("这是全中国最好吃的鱼没有之一", "这鱼肉真的好嫩，进嘴之后不用嚼")
        assert match.checked and not match.verified

    def test_too_short_quote_is_not_checked(self):
        match = match_quote("好", "好吃好吃")
        assert not match.checked and not match.verified

    def test_locate_quote_returns_segment_start(self):
        """原话跨越两个字幕片段时，时间点取原话开头所在片段的起点"""
        match = locate_quote("吃到最后还是有一点点土腥味，我能尝出来", _transcript())
        assert match.verified
        assert match.start_seconds == 64.0

    def test_locate_quote_without_segments_falls_back_to_text(self):
        transcript = TranscriptResult(video_bvid="BV1", full_text="这鱼肉真的好嫩")
        match = locate_quote("鱼肉真的好嫩", transcript)
        assert match.verified
        assert match.start_seconds is None

    def test_locate_quote_without_transcript(self):
        match = locate_quote("鱼肉真的好嫩", None)
        assert not match.checked and not match.verified


class TestEvidenceFormatting:
    """出处格式：时间点、跳转链接、发布日期"""

    def test_format_timestamp(self):
        assert format_timestamp(64.0) == "01:04"
        assert format_timestamp(3725.0) == "1:02:05"
        assert format_timestamp(None) == ""

    def test_video_url_jumps_to_quote(self):
        assert video_url("BV1example", 64.9) == "https://www.bilibili.com/video/BV1example?t=64"
        assert video_url("BV1example") == "https://www.bilibili.com/video/BV1example"
        assert video_url("") == ""

    def test_published_date_uses_beijing_time(self):
        # 1700000000 = 2023-11-14 22:13:20 UTC = 2023-11-15 06:13:20 北京时间
        assert published_date("1700000000") == "2023-11-15"
        assert published_date(1700000000) == "2023-11-15"
        assert published_date("2024-05-01 12:00:00") == "2024-05-01"
        assert published_date("") == ""


def _row(dish, up, verdict, *, verified=True, created="2025-01-01", published="2024-12-01", rid=None):
    return {
        "id": rid or f"{up}-{dish}-{created}",
        "dish_id": f"d-{dish}",
        "dish_name": dish,
        "up_master_id": f"u-{up}",
        "up_name": up,
        "sentiment": verdict,
        "raw_text": f"{up}说{dish}{verdict}",
        "video_bvid": "BV1example",
        "timestamp_seconds": 30.0,
        "quote_verified": verified,
        "video_published_at": published,
        "created_at": created,
    }


class TestConsensus:
    """按 UP 主计票，而不是求平均"""

    def test_disagreement_is_not_averaged_away(self):
        """一推荐一踩雷的均值与两个"一般"相同；按分布汇总时二者可以区分"""
        disputed = summarize_dishes([_row("宝塔肉", "甲", "推荐"), _row("宝塔肉", "乙", "踩雷")])[0]
        mediocre = summarize_dishes([_row("番茄", "甲", "一般"), _row("番茄", "乙", "一般")])[0]

        assert disputed["evidence_level"] == "争议"
        assert classify_dish(disputed) == "disputed"
        assert mediocre["evidence_level"] == "共识"
        assert classify_dish(mediocre) == "neutral"

    def test_one_vote_per_up_master(self):
        """同一位 UP 主的重复评价只算一票，取最近的一次"""
        rows = [
            _row("鱼片", "甲", "一般", created="2025-01-01", published="2023-01-01"),
            _row("鱼片", "甲", "推荐", created="2025-01-02", published="2024-06-01"),
            _row("鱼片", "甲", "推荐", created="2025-01-03", published="2024-06-01"),
        ]
        summary = summarize_dishes(rows)[0]
        assert summary["up_count"] == 1
        assert summary["evidence_level"] == "孤证"
        assert summary["verdict_counts"] == {"推荐": 1, "一般": 0, "踩雷": 0}

    def test_avoid_requires_verified_quote(self):
        """负面结论的举证要求更高：踩雷原话未核验时不进黑榜"""
        verified = summarize_dishes([_row("鸭掌", "甲", "踩雷", verified=True)])[0]
        unverified = summarize_dishes([_row("鸭掌", "甲", "踩雷", verified=False)])[0]
        assert classify_dish(verified) == "avoid"
        assert classify_dish(unverified) == "avoid_unverified"

    def test_recommendation_does_not_require_verification(self):
        summary = summarize_dishes([_row("烤鸭", "甲", "推荐", verified=False)])[0]
        assert classify_dish(summary) == "recommended"

    def test_evidence_carries_source(self):
        summary = summarize_dishes([_row("烤鸭", "甲", "推荐")])[0]
        evidence = summary["evidence"][0]
        assert evidence["up"] == "甲"
        assert evidence["video_url"] == "https://www.bilibili.com/video/BV1example?t=30"
        assert evidence["timestamp"] == "00:30"
        assert evidence["published"] == "2024-12-01"
