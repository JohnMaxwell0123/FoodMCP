"""
JSON Schema 校验器

对 LLM 输出的 JSON 进行结构校验和数据清洗，
确保提取结果符合预期格式。
"""

from __future__ import annotations

import json
import re

from loguru import logger

from src.models.entities import (
    ExtractionResult,
    ExtractedDish,
    ExtractedRestaurant,
)

# 合法的评价值
VALID_VERDICTS = {"推荐", "一般", "踩雷"}

# 非标准判定只按白名单整词映射，不做子串猜测：
# 子串规则会把"不推荐""不好吃"判成推荐、把"不错"判成踩雷。
# 白名单之外的值一律记为"一般"并保留原值待复核——宁可漏判，也不把差评说成推荐。
VERDICT_SYNONYMS: dict[str, str] = {
    "强烈推荐": "推荐", "好吃推荐": "推荐", "值得推荐": "推荐", "必点": "推荐", "必吃": "推荐",
    "不推荐": "踩雷", "别点": "踩雷", "避雷": "踩雷", "雷": "踩雷", "差评": "踩雷",
    "难吃": "踩雷", "不好吃": "踩雷", "太差了": "踩雷",
    "还可以": "一般", "还行": "一般", "中规中矩": "一般", "一般般": "一般", "普通": "一般",
}


class SchemaValidator:
    """LLM 输出校验器"""

    def validate_extraction(self, raw_text: str) -> ExtractionResult:
        """
        验证并解析 LLM 的提取结果

        Args:
            raw_text: LLM 原始输出文本

        Returns:
            验证后的 ExtractionResult
        """
        # Step 1: 提取 JSON
        json_str = self._extract_json(raw_text)
        if not json_str:
            logger.warning("无法从LLM输出中提取有效JSON")
            return ExtractionResult(error="无法提取有效JSON", confidence=0.0)

        # Step 2: 解析 JSON
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON解析失败: {e}")
            return ExtractionResult(error=f"JSON解析失败: {e}", confidence=0.0)

        # Step 3: 结构校验 & 数据清洗
        restaurants = self._validate_restaurants(data.get("restaurants", []))

        # Step 4: 计算置信度
        confidence = self._compute_confidence(restaurants)

        return ExtractionResult(
            restaurants=restaurants,
            confidence=confidence,
        )

    def _extract_json(self, text: str) -> str | None:
        """
        从 LLM 输出中提取 JSON 字符串

        处理常见情况：
          - 纯 JSON
          - 被 ```json ... ``` 包裹的 JSON
          - 包含前后解释文字的 JSON
        """
        text = text.strip()

        # 尝试直接解析
        if text.startswith("{"):
            return text

        # 尝试提取 ```json ... ``` 中的内容
        json_block_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if json_block_match:
            return json_block_match.group(1).strip()

        # 尝试找到第一个 { 和最后一个 }
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            return text[first_brace : last_brace + 1]

        return None

    def _validate_restaurants(
        self, raw_restaurants: list[dict],
    ) -> list[ExtractedRestaurant]:
        """验证并清洗餐厅数据"""
        restaurants = []

        for raw in raw_restaurants:
            if not isinstance(raw, dict):
                continue

            name = str(raw.get("name", "")).strip()
            if not name:
                logger.debug("跳过无名称的餐厅记录")
                continue

            # 处理菜品
            dishes = self._validate_dishes(raw.get("dishes", []))

            restaurant = ExtractedRestaurant(
                name=name,
                location=str(raw.get("location", "")),
                cuisine_type=str(raw.get("cuisine_type", "")),
                dishes=dishes,
                overall_impression=str(raw.get("overall_impression", "")),
            )
            restaurants.append(restaurant)

        return restaurants

    def _validate_dishes(self, raw_dishes: list[dict]) -> list[ExtractedDish]:
        """验证并清洗菜品数据"""
        dishes = []

        for raw in raw_dishes:
            if not isinstance(raw, dict):
                continue

            name = str(raw.get("name", "")).strip()
            if not name:
                continue

            # 规范化 verdict
            verdict = str(raw.get("verdict", "一般")).strip()
            verdict_raw = ""
            if verdict not in VALID_VERDICTS:
                verdict_raw = verdict
                verdict = VERDICT_SYNONYMS.get(verdict, "一般")
                logger.warning(f"非标准判定 '{verdict_raw}' 已记为 '{verdict}'，待复核: {name}")

            # 处理 aspects
            raw_aspects = raw.get("aspects", {})
            aspects = {}
            if isinstance(raw_aspects, dict):
                for key in ("taste", "texture", "portion", "presentation", "value"):
                    aspects[key] = str(raw_aspects.get(key, ""))

            dish = ExtractedDish(
                name=name,
                price=str(raw.get("price", "")),
                verdict=verdict,
                verdict_raw=verdict_raw,
                aspects=aspects,
                original_quote=str(raw.get("original_quote", "")),
                timestamp=str(raw.get("timestamp", "")),
            )
            dishes.append(dish)

        return dishes

    def _compute_confidence(self, restaurants: list[ExtractedRestaurant]) -> float:
        """
        计算提取结果的字段完整度（沿用 confidence 字段名）

        它只衡量"字段齐不齐"，不衡量"内容对不对"：ASR 听错的菜名同样能拿满分。
        内容是否可靠由入库时的原话核验（src/evidence/quotes.py）负责。

        评分维度：
          - 是否有餐厅记录
          - 餐厅信息完整度（名称、地址、菜系）
          - 菜品信息完整度（名称、标准 verdict、原话）
          - 细分维度覆盖率
        """
        if not restaurants:
            return 0.0

        scores: list[float] = []

        for rest in restaurants:
            rest_score = 0.5  # 基础分（有名称即得）

            # 位置信息
            if rest.location:
                rest_score += 0.1
            # 菜系
            if rest.cuisine_type:
                rest_score += 0.1
            # 整体评价
            if rest.overall_impression:
                rest_score += 0.1

            # 菜品完整度
            if rest.dishes:
                dish_scores = []
                for dish in rest.dishes:
                    d_score = 0.4  # 有菜名即得
                    if not dish.verdict_raw:  # LLM 直接给出了标准判定
                        d_score += 0.2
                    if dish.original_quote:
                        d_score += 0.2
                    if any(dish.aspects.values()):
                        d_score += 0.2
                    dish_scores.append(d_score)
                rest_score += 0.2 * (sum(dish_scores) / len(dish_scores))

            scores.append(min(1.0, rest_score))

        return sum(scores) / len(scores)
