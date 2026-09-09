"""
LLM 评测框架单元测试
"""

import pytest

from src.eval.evaluator import ExtractionEvaluator
from src.models.entities import (
    ExtractedDish,
    ExtractedRestaurant,
    ExtractionResult,
)


class TestExtractionEvaluator:
    """评测指标计算与抗幻觉能力测试"""

    def test_perfect_prediction(self):
        """完全匹配时所有 F1 和保真度均应为 1.0"""
        ground_truth = {
            "restaurants": [
                {
                    "name": "萃华楼",
                    "dishes": [
                        {"name": "九转大肠", "verdict": "推荐", "original_quote": "外焦里嫩太好吃了"},
                        {"name": "糟熘三白", "verdict": "踩雷", "original_quote": "完全没有味道差评"},
                    ],
                }
            ]
        }

        predicted = ExtractionResult(
            restaurants=[
                ExtractedRestaurant(
                    name="萃华楼",
                    dishes=[
                        ExtractedDish(name="九转大肠", verdict="推荐", original_quote="外焦里嫩太好吃了"),
                        ExtractedDish(name="糟熘三白", verdict="踩雷", original_quote="完全没有味道差评"),
                    ],
                )
            ],
            confidence=1.0,
        )

        transcript = "今天来到萃华楼，九转大肠外焦里嫩太好吃了，糟熘三白完全没有味道差评"

        result = ExtractionEvaluator.evaluate_sample(
            sample_id="test_01",
            predicted=predicted,
            ground_truth=ground_truth,
            transcript_text=transcript,
        )

        assert result.restaurant_ner.f1 == 1.0
        assert result.dish_ner.f1 == 1.0
        assert result.sentiment_metrics.accuracy == 1.0
        assert result.sentiment_metrics.macro_f1 == 1.0
        assert result.sentiment_metrics.false_recommendation_count == 0
        assert result.faithfulness.faithfulness_rate == 1.0
        assert result.faithfulness.hallucination_rate == 0.0

    def test_entity_miss_and_spurious(self):
        """测试漏采与多采情况下的 Precision / Recall 降级"""
        ground_truth = {
            "restaurants": [
                {
                    "name": "海金滋",
                    "dishes": [
                        {"name": "红烧肉", "verdict": "推荐"},
                        {"name": "葱油拌面", "verdict": "推荐"},
                    ],
                }
            ]
        }

        # 模型只预测出了红烧肉，并且多预测了一道虚构的“炸猪排”
        predicted = ExtractionResult(
            restaurants=[
                ExtractedRestaurant(
                    name="海金滋",
                    dishes=[
                        ExtractedDish(name="红烧肉", verdict="推荐"),
                        ExtractedDish(name="炸猪排", verdict="一般"),
                    ],
                )
            ],
            confidence=0.8,
        )

        result = ExtractionEvaluator.evaluate_sample(
            sample_id="test_02",
            predicted=predicted,
            ground_truth=ground_truth,
            transcript_text="我们在海金滋吃了红烧肉和葱油拌面",
        )

        # 菜品预测了 2 个，匹配了 1 个，真实有 2 个
        assert result.dish_ner.precision == 0.5
        assert result.dish_ner.recall == 0.5
        assert result.dish_ner.f1 == 0.5

    def test_false_recommendation_detection(self):
        """踩雷菜品被误报为推荐时，应准确捕获高危事故指标"""
        ground_truth = {
            "restaurants": [
                {
                    "name": "朱光玉火锅",
                    "dishes": [
                        {"name": "麻辣红锅", "verdict": "踩雷"},
                    ],
                }
            ]
        }

        # 大模型错误将踩雷判定为推荐
        predicted = ExtractionResult(
            restaurants=[
                ExtractedRestaurant(
                    name="朱光玉火锅",
                    dishes=[
                        ExtractedDish(name="麻辣红锅", verdict="推荐"),
                    ],
                )
            ],
            confidence=0.9,
        )

        result = ExtractionEvaluator.evaluate_sample(
            sample_id="test_03",
            predicted=predicted,
            ground_truth=ground_truth,
            transcript_text="锅底太难吃了，大雷",
        )

        assert result.sentiment_metrics.accuracy == 0.0
        assert result.sentiment_metrics.false_recommendation_count == 1
        assert result.sentiment_metrics.false_recommendation_rate == 1.0

    def test_hallucination_detection(self):
        """原话中捏造不存在的言论时，应判定为幻觉 (Hallucination)"""
        ground_truth = {
            "restaurants": [
                {
                    "name": "全聚德",
                    "dishes": [
                        {"name": "烤鸭", "verdict": "推荐", "original_quote": "皮脆肉嫩"},
                    ],
                }
            ]
        }

        # 原文字幕中只有"皮脆肉嫩"，但模型脑补了"这是全中国最好吃的烤鸭没有之一"
        predicted = ExtractionResult(
            restaurants=[
                ExtractedRestaurant(
                    name="全聚德",
                    dishes=[
                        ExtractedDish(
                            name="烤鸭",
                            verdict="推荐",
                            original_quote="这是全中国最好吃的烤鸭没有之一",
                        ),
                    ],
                )
            ],
            confidence=0.85,
        )

        result = ExtractionEvaluator.evaluate_sample(
            sample_id="test_04",
            predicted=predicted,
            ground_truth=ground_truth,
            transcript_text="全聚德烤鸭端上来了，皮脆肉嫩，口感不错",
        )

        assert result.faithfulness.hallucinated_quotes == 1
        assert result.faithfulness.faithfulness_rate == 0.0
        assert result.faithfulness.hallucination_rate == 1.0

    def test_batch_evaluation_and_markdown(self):
        """批量聚合与 Markdown 格式导出验证"""
        samples = [
            {
                "id": "s1",
                "transcript_text": "在老店吃了烤肉，很香很好吃",
                "ground_truth": {
                    "restaurants": [
                        {"name": "老店", "dishes": [{"name": "烤肉", "verdict": "推荐"}]}
                    ]
                },
            }
        ]

        predictions = [
            ExtractionResult(
                restaurants=[
                    ExtractedRestaurant(
                        name="老店",
                        dishes=[ExtractedDish(name="烤肉", verdict="推荐", original_quote="很香很好吃")],
                    )
                ],
                confidence=0.95,
            )
        ]

        report = ExtractionEvaluator.evaluate_batch(
            model_name="mock-model",
            samples=samples,
            predictions=predictions,
        )

        assert report.total_samples == 1
        assert report.restaurant_f1 == 1.0
        assert report.dish_f1 == 1.0
        assert report.sentiment_accuracy == 1.0

        md = report.to_markdown()
        assert "# 📊 FoodMCP LLM 抽取基准评测报告" in md
        assert "mock-model" in md
        assert "混淆矩阵" in md
