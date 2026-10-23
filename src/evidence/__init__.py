"""证据层：原话核验、时间戳定位、多 UP 主证据汇总"""

from src.evidence.consensus import classify_dish, summarize_dishes
from src.evidence.quotes import (
    QuoteMatch,
    format_timestamp,
    locate_quote,
    match_quote,
    published_date,
    video_url,
)

__all__ = [
    "QuoteMatch",
    "classify_dish",
    "format_timestamp",
    "locate_quote",
    "match_quote",
    "published_date",
    "summarize_dishes",
    "video_url",
]
