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
            if verdict not in VALID_VERDICTS:
                # 尝试模糊匹配
                if "推" in verdict or "好" in verdict or "赞" in verdict:
                    verdict = "推荐"
                elif "雷" in verdict or "差" in verdict or "不" in verdict:
                    verdict = "踩雷"
                else:
                    verdict = "一般"

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
                aspects=aspects,
                original_quote=str(raw.get("original_quote", "")),
                timestamp=str(raw.get("timestamp", "")),
            )
            dishes.append(dish)

        return dishes

    def _compute_confidence(self, restaurants: list[ExtractedRestaurant]) -> float:
        """
        计算提取结果的置信度

        评分维度：
          - 是否有餐厅记录
          - 餐厅信息完整度（名称、地址、菜系）
          - 菜品信息完整度（名称、verdict、原话）
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
                    if dish.verdict in VALID_VERDICTS:
                        d_score += 0.2
                    if dish.original_quote:
                        d_score += 0.2
                    if any(dish.aspects.values()):
                        d_score += 0.2
                    dish_scores.append(d_score)
                rest_score += 0.2 * (sum(dish_scores) / len(dish_scores))

            scores.append(min(1.0, rest_score))

        return sum(scores) / len(scores)
