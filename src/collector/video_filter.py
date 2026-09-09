"""
探店视频智能筛选

功能：
  - 基于标题、标签、描述等信息判断是否为探店类视频
  - 支持自定义关键词和规则
"""

from __future__ import annotations

import re

from loguru import logger

from src.models.entities import VideoInfo

# 探店相关关键词（正向）
FOOD_KEYWORDS: set[str] = {
    # 核心动作
    "探店", "测评", "试吃", "打卡", "觅食", "逛吃",
    # 推荐/评价
    "美食", "必吃", "种草", "安利", "推荐", "踩雷", "好吃", "难吃",
    # 场所
    "餐厅", "饭店", "馆子", "食堂", "小吃", "夜市", "网红", "网红店", "菜馆",
    # 菜系/品类
    "火锅", "烧烤", "烤肉", "串串", "奶茶", "甜品", "烤鱼", "大盘鸡",
    "饺子", "面馆", "胡辣汤", "鸡煲", "海鲜", "河鲜",
    # 餐次
    "早餐", "午餐", "晚餐", "宵夜", "下午茶",
    # 价格/体验
    "人均", "性价比", "排队", "实惠",
    # 榜单
    "米其林", "黑珍珠", "必比登",
    # 常见食材关键词（提高探店视频召回）
    "吃",
}

# 排除关键词（假阳性过滤）
EXCLUDE_KEYWORDS: set[str] = {
    "教程", "食谱", "做法", "烹饪教学", "家常菜做法",
    "mukbang", "吃播挑战",
}

# 城市关键词（辅助判断）
CITY_KEYWORDS: set[str] = {
    "北京", "上海", "广州", "深圳", "成都", "重庆",
    "杭州", "南京", "武汉", "西安", "长沙", "厦门",
    "青岛", "大连", "苏州", "天津", "昆明", "贵阳",
    "哈尔滨", "沈阳", "福州", "郑州", "济南", "合肥",
    # 新增城市（覆盖新疆、东北等探店热门区域）
    "新疆", "伊宁", "阿勒泰", "乌鲁木齐", "温州", "洛阳",
    "东北", "潮汕", "顺德", "佛山", "汕头", "拉萨",
}


class VideoFilter:
    """视频筛选器"""

    def __init__(
        self,
        food_keywords: set[str] | None = None,
        exclude_keywords: set[str] | None = None,
        min_duration: int = 60,
        max_duration: int = 3600,
        score_threshold: float = 0.3,
    ) -> None:
        """
        Args:
            food_keywords: 自定义探店关键词集合
            exclude_keywords: 自定义排除关键词集合
            min_duration: 最短时长（秒）
            max_duration: 最长时长（秒）
            score_threshold: 判定为探店视频的最低得分阈值
        """
        self.food_keywords = food_keywords or FOOD_KEYWORDS
        self.exclude_keywords = exclude_keywords or EXCLUDE_KEYWORDS
        self.min_duration = min_duration
        self.max_duration = max_duration
        self.score_threshold = score_threshold

    def is_food_exploration(self, video: VideoInfo) -> bool:
        """
        判断视频是否为探店类视频

        Args:
            video: 视频信息

        Returns:
            是否为探店视频
        """
        score = self._compute_score(video)
        result = score >= self.score_threshold
        video.is_food_exploration = result

        if result:
            logger.debug(f"✅ 探店视频: [{video.bvid}] {video.title} (score={score:.2f})")
        else:
            logger.debug(f"❌ 非探店视频: [{video.bvid}] {video.title} (score={score:.2f})")

        return result

    def filter_videos(self, videos: list[VideoInfo]) -> list[VideoInfo]:
        """
        批量筛选探店视频

        Args:
            videos: 视频列表

        Returns:
            筛选后的探店视频列表
        """
        food_videos = [v for v in videos if self.is_food_exploration(v)]
        logger.info(
            f"视频筛选完成: {len(food_videos)}/{len(videos)} 为探店视频"
        )
        return food_videos

    def _compute_score(self, video: VideoInfo) -> float:
        """
        计算视频的探店相关性得分

        评分策略：
          - 标题匹配权重最高 (0.5)
          - 标签匹配 (0.3)
          - 描述匹配 (0.2)
          - 排除关键词减分
          - 时长异常减分

        Returns:
            0.0 ~ 1.0 的得分
        """
        score = 0.0
        combined_text = f"{video.title} {video.description}"
        tag_text = " ".join(video.tags)

        # 检查排除关键词
        for kw in self.exclude_keywords:
            if kw in combined_text:
                return 0.0

        # 标题关键词匹配（权重 0.5）
        title_hits = sum(1 for kw in self.food_keywords if kw in video.title)
        if title_hits > 0:
            score += min(0.5, title_hits * 0.15)

        # 标签匹配（权重 0.3）
        tag_hits = sum(1 for kw in self.food_keywords if kw in tag_text)
        if tag_hits > 0:
            score += min(0.3, tag_hits * 0.1)

        # 描述匹配（权重 0.2）
        desc_hits = sum(1 for kw in self.food_keywords if kw in video.description)
        if desc_hits > 0:
            score += min(0.2, desc_hits * 0.05)

        # 城市关键词 bonus
        for city in CITY_KEYWORDS:
            if city in video.title:
                score += 0.1
                break

        # 时长惩罚
        if video.duration > 0:
            if video.duration < self.min_duration or video.duration > self.max_duration:
                score *= 0.5

        return min(1.0, score)
