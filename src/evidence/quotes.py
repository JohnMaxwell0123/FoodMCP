"""
原话核验与时间戳定位

LLM 抽取的 UP 主原话必须能在字幕里找到，才算可核对的证据；
对上的字幕片段起点就是这句话在视频里的时间点。

评测（src/eval/evaluator.py 的保真度）与入库（src/pipeline/runner.py）共用这里的匹配规则，
所以离线评测的保真率和线上每条评价的 quote_verified 是同一个口径。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from rapidfuzz import fuzz

from src.models.entities import TranscriptResult

# partial_ratio 阈值：容忍 ASR 切词差异与个别错字，但不接受改写
QUOTE_MATCH_THRESHOLD: float = 80.0
# 短于此长度的原话无法有意义地核验
MIN_QUOTE_CHARS: int = 3

_NON_WORD = re.compile(r"[^\w一-龥]")
_CHINA_TZ = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class QuoteMatch:
    """原话与字幕的匹配结果"""

    checked: bool  # 原话足够长、参与了核验
    verified: bool  # 能在字幕中找到（精确或模糊）
    score: float = 0.0  # 0 ~ 100
    start_seconds: float | None = None  # 对上的字幕片段起点（秒），只有带时间轴的字幕才有


def normalize(text: str) -> str:
    """只保留文字，去掉标点与空白"""
    return _NON_WORD.sub("", text)


def _search(clean_quote: str, clean_text: str) -> tuple[float, int]:
    """返回 (匹配得分, 在 clean_text 中的起点)"""
    if not clean_quote or not clean_text:
        return 0.0, -1
    pos = clean_text.find(clean_quote)
    if pos >= 0:
        return 100.0, pos
    alignment = fuzz.partial_ratio_alignment(clean_quote, clean_text)
    return alignment.score, alignment.dest_start


def match_quote(quote: str, text: str) -> QuoteMatch:
    """核验原话是否出现在一段纯文本字幕中（不定位时间）"""
    quote = quote.strip()
    clean_quote = normalize(quote)
    if len(quote) < MIN_QUOTE_CHARS or not clean_quote:
        return QuoteMatch(checked=False, verified=False)

    score, _ = _search(clean_quote, normalize(text))
    return QuoteMatch(checked=True, verified=score >= QUOTE_MATCH_THRESHOLD, score=score)


def locate_quote(quote: str, transcript: TranscriptResult | None) -> QuoteMatch:
    """
    在字幕中定位原话

    有时间轴时返回对上的字幕片段起点；只有纯文本时退化为 match_quote。
    """
    if transcript is None:
        return QuoteMatch(checked=False, verified=False)
    if not transcript.segments:
        return match_quote(quote, transcript.to_full_text())

    quote = quote.strip()
    clean_quote = normalize(quote)
    if len(quote) < MIN_QUOTE_CHARS or not clean_quote:
        return QuoteMatch(checked=False, verified=False)

    # 拼接去标点后的字幕，并记录每个片段在拼接文本中的起点
    parts: list[str] = []
    offsets: list[tuple[int, float]] = []
    cursor = 0
    for seg in transcript.segments:
        clean = normalize(seg.text)
        if not clean:
            continue
        offsets.append((cursor, seg.start))
        parts.append(clean)
        cursor += len(clean)

    score, pos = _search(clean_quote, "".join(parts))
    if score < QUOTE_MATCH_THRESHOLD:
        return QuoteMatch(checked=True, verified=False, score=score)

    start_seconds = None
    for offset, seg_start in offsets:
        if offset > pos:
            break
        start_seconds = seg_start
    return QuoteMatch(checked=True, verified=True, score=score, start_seconds=start_seconds)


def format_timestamp(seconds: float | None) -> str:
    """秒数 → mm:ss（超过一小时为 h:mm:ss）"""
    if seconds is None:
        return ""
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def video_url(bvid: str, seconds: float | None = None) -> str:
    """B 站视频链接；带秒数时可直接跳到原话所在的时间点"""
    if not bvid:
        return ""
    url = f"https://www.bilibili.com/video/{bvid}"
    if seconds is not None:
        url += f"?t={int(seconds)}"
    return url


def published_date(raw: str | int | None) -> str:
    """B 站发布时间（Unix 秒，或已格式化的日期）→ YYYY-MM-DD（北京时间）"""
    if raw is None:
        return ""
    text = str(raw).strip()
    if not text:
        return ""
    if text.isdigit():
        return datetime.fromtimestamp(int(text), tz=_CHINA_TZ).strftime("%Y-%m-%d")
    return text[:10]
