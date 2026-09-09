"""
核心实体模型

定义 Restaurant / Dish / UPMaster / Review 等核心业务实体，
以及 LLM 提取结果的中间模型和 Pipeline 数据结构。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ============================================================
# 枚举
# ============================================================


class Sentiment(str, Enum):
    """评价情感倾向"""

    RECOMMENDED = "推荐"
    AVERAGE = "一般"
    AVOID = "踩雷"


class CuisineType(str, Enum):
    """主要菜系分类"""

    SICHUAN = "川菜"
    CANTONESE = "粤菜"
    SHANDONG = "鲁菜"
    JIANGSU = "苏菜"
    HUNAN = "湘菜"
    BEIJING = "京菜"
    HOTPOT = "火锅"
    BBQ = "烧烤"
    SEAFOOD = "海鲜"
    JAPANESE = "日料"
    KOREAN = "韩餐"
    WESTERN = "西餐"
    DESSERT = "甜品"
    NOODLES = "面食"
    SNACK = "小吃"
    OTHER = "其他"


# ============================================================
# 核心业务实体
# ============================================================


class Restaurant(BaseModel):
    """餐厅实体"""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(..., description="餐厅名称")
    city: str = Field(..., description="所在城市")
    district: str = Field(default="", description="所在区域")
    address: str = Field(default="", description="详细地址")
    cuisine_type: str = Field(default="其他", description="菜系分类")
    price_range: str = Field(default="", description="人均价格区间")
    tags: list[str] = Field(default_factory=list, description="标签")
    latitude: float | None = Field(default=None, description="纬度")
    longitude: float | None = Field(default=None, description="经度")
    geo_verified: bool = Field(default=False, description="地理编码是否经过高置信度核验")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class Dish(BaseModel):
    """菜品实体"""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(..., description="菜品名称")
    category: str = Field(default="", description="分类(凉菜/热菜/主食/甜品等)")
    price: float | None = Field(default=None, description="价格")
    restaurant_id: str = Field(..., description="所属餐厅ID")
    avg_sentiment: float = Field(default=0.0, description="综合情绪分 (-1.0~1.0)")
    created_at: datetime = Field(default_factory=datetime.now)


class UPMaster(BaseModel):
    """B站UP主实体"""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    bilibili_uid: str = Field(..., description="B站UID")
    name: str = Field(..., description="UP主名称")
    follower_count: int = Field(default=0, description="粉丝数")
    style_tags: list[str] = Field(default_factory=list, description="风格标签")
    credibility_score: float = Field(default=0.5, description="可信度评分 (0~1)")
    created_at: datetime = Field(default_factory=datetime.now)


class AspectReview(BaseModel):
    """细分维度评价"""

    taste: str = Field(default="", description="口味描述")
    texture: str = Field(default="", description="口感描述")
    portion: str = Field(default="", description="分量描述")
    presentation: str = Field(default="", description="卖相描述")
    value: str = Field(default="", description="性价比描述")


class Review(BaseModel):
    """评价实体 — 核心数据单元"""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    up_master_id: str = Field(..., description="评价者UP主ID")
    dish_id: str = Field(..., description="评价菜品ID")
    restaurant_id: str = Field(..., description="评价餐厅ID")
    video_bvid: str = Field(..., description="来源视频BV号")
    timestamp: str = Field(default="", description="视频中的时间戳")
    raw_text: str = Field(..., description="UP主原话")
    sentiment: Sentiment = Field(..., description="评价倾向")
    sentiment_score: float = Field(default=0.0, description="情绪分值 (-1.0~1.0)")
    aspects: AspectReview = Field(default_factory=AspectReview, description="细分维度评价")
    created_at: datetime = Field(default_factory=datetime.now)


# ============================================================
# LLM 提取中间模型 — 对应 Prompt 输出格式
# ============================================================


class ExtractedDish(BaseModel):
    """LLM从视频中提取的单道菜品信息"""

    name: str = Field(..., description="菜品名称")
    price: str = Field(default="", description="价格（原始文本）")
    verdict: str = Field(..., description="推荐/一般/踩雷")
    aspects: dict[str, str] = Field(default_factory=dict, description="细分维度评价")
    original_quote: str = Field(default="", description="UP主原话")
    timestamp: str = Field(default="", description="大致时间段")


class ExtractedRestaurant(BaseModel):
    """LLM从视频中提取的单个餐厅信息"""

    name: str = Field(..., description="餐厅名")
    location: str = Field(default="", description="地址/区域")
    cuisine_type: str = Field(default="", description="菜系")
    dishes: list[ExtractedDish] = Field(default_factory=list, description="菜品列表")
    overall_impression: str = Field(default="", description="整体评价")


class ExtractionResult(BaseModel):
    """LLM 提取的完整结果"""

    restaurants: list[ExtractedRestaurant] = Field(
        default_factory=list, description="提取到的餐厅列表"
    )
    confidence: float = Field(default=0.0, description="整体置信度")
    error: str = Field(default="", description="提取错误信息")


# ============================================================
# Pipeline 数据结构
# ============================================================


class VideoInfo(BaseModel):
    """B站视频基本信息"""

    bvid: str = Field(..., description="视频BV号")
    title: str = Field(..., description="视频标题")
    description: str = Field(default="", description="视频简介")
    duration: int = Field(default=0, description="视频时长(秒)")
    publish_date: str = Field(default="", description="发布日期")
    up_mid: str = Field(..., description="UP主MID")
    up_name: str = Field(default="", description="UP主名称")
    tags: list[str] = Field(default_factory=list, description="标签")
    view_count: int = Field(default=0, description="播放量")
    is_food_exploration: bool = Field(default=False, description="是否为探店视频")


class SubtitleSegment(BaseModel):
    """字幕片段"""

    start: float = Field(..., description="开始时间(秒)")
    end: float = Field(..., description="结束时间(秒)")
    text: str = Field(..., description="字幕文本")


class TranscriptResult(BaseModel):
    """转写结果"""

    video_bvid: str = Field(..., description="视频BV号")
    source: str = Field(default="", description="来源(cc/ai/whisper)")
    language: str = Field(default="zh", description="语言")
    segments: list[SubtitleSegment] = Field(default_factory=list, description="字幕片段")
    full_text: str = Field(default="", description="完整文本")

    def to_full_text(self) -> str:
        """将所有字幕片段合并为完整文本"""
        if self.full_text:
            return self.full_text
        return " ".join(seg.text for seg in self.segments)


class TaskStatus(str, Enum):
    """Pipeline 任务状态机"""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUBTITLE_EXTRACTED = "SUBTITLE_EXTRACTED"
    EXTRACTED = "EXTRACTED"
    STORED = "STORED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class PipelineTask(BaseModel):
    """Pipeline 处理任务状态模型"""

    video: VideoInfo
    bvid: str = Field(default="", description="视频BV号")
    up_mid: int = Field(default=0, description="UP主MID")
    title: str = Field(default="", description="视频标题")
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="任务状态")
    stage: str = Field(default="init", description="生命周期阶段(init/subtitle/llm/storage)")
    retry_count: int = Field(default=0, description="重试次数")
    error_message: str = Field(default="", description="错误信息")
    transcript_source: str = Field(default="", description="字幕来源(cc/ai/whisper)")
    restaurant_count: int = Field(default=0, description="识别餐厅数")
    dish_count: int = Field(default=0, description="识别菜品数")
    updated_at: datetime | None = Field(default=None, description="更新时间")
    transcript: TranscriptResult | None = None
    extraction: ExtractionResult | None = None

    def model_post_init(self, __context: Any) -> None:
        if not self.bvid and self.video:
            self.bvid = self.video.bvid
        if not self.up_mid and self.video:
            try:
                self.up_mid = int(self.video.up_mid)
            except (ValueError, TypeError):
                self.up_mid = 0
        if not self.title and self.video:
            self.title = self.video.title
        if self.updated_at is None:
            self.updated_at = datetime.now()

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, v: Any) -> TaskStatus:
        if isinstance(v, TaskStatus):
            return v
        if isinstance(v, str):
            mapping = {
                "pending": TaskStatus.PENDING,
                "processing": TaskStatus.PROCESSING,
                "done": TaskStatus.STORED,
                "stored": TaskStatus.STORED,
                "error": TaskStatus.FAILED,
                "failed": TaskStatus.FAILED,
                "skipped": TaskStatus.SKIPPED,
                "extracted": TaskStatus.EXTRACTED,
                "subtitle_extracted": TaskStatus.SUBTITLE_EXTRACTED,
            }
            v_lower = v.lower()
            if v_lower in mapping:
                return mapping[v_lower]
            try:
                return TaskStatus(v.upper())
            except ValueError:
                return TaskStatus.PENDING
        return TaskStatus.PENDING
