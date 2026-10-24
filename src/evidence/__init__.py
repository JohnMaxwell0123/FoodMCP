"""证据层：原话核验、时间戳定位、多 UP 主证据汇总、餐后反馈汇总"""

from src.evidence.consensus import classify_dish, summarize_dishes
from src.evidence.feedback import (
    OUTCOME_TO_VERDICT,
    diner_feedback_counts,
    north_star,
    summarize_up_feedback,
)
from src.evidence.quotes import (
    QuoteMatch,
    format_timestamp,
    locate_quote,
    match_quote,
    published_date,
    video_url,
)

__all__ = [
    "OUTCOME_TO_VERDICT",
    "QuoteMatch",
    "classify_dish",
    "diner_feedback_counts",
    "format_timestamp",
    "locate_quote",
    "match_quote",
    "north_star",
    "published_date",
    "summarize_dishes",
    "summarize_up_feedback",
    "video_url",
]
