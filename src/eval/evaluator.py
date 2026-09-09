"""
LLM 抽取 Eval 评测核心引擎

提供实体识别 (NER)、情感三分类 (Classification)、原文保真度 (Faithfulness)
以及结构完备度 (Schema) 的工业级评测计算能力。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from loguru import logger
from rapidfuzz import fuzz

from src.models.entities import ExtractionResult

# 规范化情感类别
SENTIMENT_LABELS = ["推荐", "一般", "踩雷"]


@dataclass
class NERScore:
    """实体识别评测得分 (餐厅或菜品)"""

    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    matched_count: int = 0
    pred_count: int = 0
    target_count: int = 0


@dataclass
class SentimentMetrics:
    """情感分类评估指标"""

    accuracy: float = 0.0
    macro_f1: float = 0.0
    class_f1: dict[str, float] = field(default_factory=dict)
    confusion_matrix: dict[str, dict[str, int]] = field(default_factory=dict)
    # 高危缺陷监控：将真实踩雷误判为推荐的数量及比率
    false_recommendation_count: int = 0
    total_avoid_dishes: int = 0
    false_recommendation_rate: float = 0.0


@dataclass
class FaithfulnessMetrics:
    """原文引用保真度与抗幻觉评估"""

    faithfulness_rate: float = 1.0  # 原文引用保真率 (真实出现于字幕的比率)
    hallucination_rate: float = 0.0  # 幻觉率 (1 - faithfulness_rate)
    faithful_quotes: int = 0
    hallucinated_quotes: int = 0
    total_quotes: int = 0


@dataclass
class SampleEvalResult:
    """单条样本评测明细"""

    sample_id: str
    restaurant_ner: NERScore
    dish_ner: NERScore
    sentiment_metrics: SentimentMetrics
    faithfulness: FaithfulnessMetrics
    schema_valid: bool
    confidence: float
    matched_restaurants: list[tuple[str, str]] = field(default_factory=list)
    matched_dishes: list[tuple[str, str, str, str]] = field(default_factory=list)  # (pred_name, gt_name, pred_v, gt_v)


@dataclass
class EvalReport:
    """全局评测汇总报告"""

    model_name: str
    total_samples: int
    schema_valid_rate: float
    avg_confidence: float
    # 宏观 NER
    restaurant_precision: float
    restaurant_recall: float
    restaurant_f1: float
    dish_precision: float
    dish_recall: float
    dish_f1: float
    # 情感分类
    sentiment_accuracy: float
    sentiment_macro_f1: float
    sentiment_confusion_matrix: dict[str, dict[str, int]]
    false_recommendation_rate: float
    # 保真度
    faithfulness_rate: float
    hallucination_rate: float
    # 明细
    sample_results: list[SampleEvalResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_markdown(self) -> str:
        """生成 Markdown 格式的评测基准报告"""
        lines = [
            f"# 📊 FoodMCP LLM 抽取基准评测报告 ({self.model_name})",
            "",
            f"- **评测样本总数**: {self.total_samples}",
            f"- **Schema 合规解析率**: {self.schema_valid_rate * 100:.1f}%",
            f"- **大模型置信度均值**: {self.avg_confidence:.2f}",
            "",
            "## 1. 实体识别与抽取指标 (NER)",
            "",
            "| 实体类型 | 精确率 (Precision) | 召回率 (Recall) | F1-Score |",
            "| :--- | :--- | :--- | :--- |",
            f"| **餐厅实体 (Restaurant)** | {self.restaurant_precision * 100:.2f}% | {self.restaurant_recall * 100:.2f}% | **{self.restaurant_f1 * 100:.2f}%** |",
            f"| **菜品实体 (Dish)** | {self.dish_precision * 100:.2f}% | {self.dish_recall * 100:.2f}% | **{self.dish_f1 * 100:.2f}%** |",
            "",
            "## 2. 情感倾向三分类指标 (Sentiment Classification)",
            "",
            f"- **分类总体准确率 (Accuracy)**: {self.sentiment_accuracy * 100:.2f}%",
            f"- **Macro-F1 得分**: {self.sentiment_macro_f1 * 100:.2f}%",
            f"- **高危踩雷误报为推荐率 (False Recommendation)**: {self.false_recommendation_rate * 100:.2f}%",
            "",
            "### 混淆矩阵 (Confusion Matrix: 行=真实值, 列=预测值)",
            "",
            "| 真实类别 \\ 预测类别 | 推荐 | 一般 | 踩雷 |",
            "| :--- | :--- | :--- | :--- |",
        ]

        for label in SENTIMENT_LABELS:
            row_data = self.sentiment_confusion_matrix.get(label, {})
            r_c = row_data.get("推荐", 0)
            a_c = row_data.get("一般", 0)
            av_c = row_data.get("踩雷", 0)
            lines.append(f"| **{label}** | {r_c} | {a_c} | {av_c} |")

        lines.extend([
            "",
            "## 3. 保真度与抗幻觉能力 (Faithfulness)",
            "",
            f"- **原文引用保真率 (Faithful Quotes)**: **{self.faithfulness_rate * 100:.2f}%**",
            f"- **大模型虚构原话幻觉率 (Hallucination Rate)**: {self.hallucination_rate * 100:.2f}%",
            "",
            "---",
            "*(注：由 FoodMCP ExtractionEvaluator 自动化评测框架生成)*",
        ])
        return "\n".join(lines)


class ExtractionEvaluator:
    """评测器实现类"""

    RESTAURANT_MATCH_THRESHOLD: float = 75.0
    DISH_MATCH_THRESHOLD: float = 70.0
    QUOTE_MATCH_THRESHOLD: float = 80.0

    @classmethod
    def evaluate_sample(
        cls,
        sample_id: str,
        predicted: ExtractionResult,
        ground_truth: dict[str, Any],
        transcript_text: str,
    ) -> SampleEvalResult:
        """评估单条样本"""
        schema_valid = not bool(predicted.error)
        confidence = predicted.confidence

        gt_restaurants = ground_truth.get("restaurants", [])
        pred_restaurants = predicted.restaurants if schema_valid else []

        # --- 1. 餐厅实体对齐与评测 ---
        matched_rest_pairs: list[tuple[Any, Any]] = []
        unmatched_gt_rest = list(gt_restaurants)

        for p_r in pred_restaurants:
            best_gt = None
            best_sim = 0.0
            for g_r in unmatched_gt_rest:
                sim = fuzz.token_set_ratio(p_r.name.strip(), g_r["name"].strip())
                if sim > best_sim:
                    best_sim = sim
                    best_gt = g_r

            if best_gt and best_sim >= cls.RESTAURANT_MATCH_THRESHOLD:
                matched_rest_pairs.append((p_r, best_gt))
                unmatched_gt_rest.remove(best_gt)

        r_match_cnt = len(matched_rest_pairs)
        r_pred_cnt = len(pred_restaurants)
        r_target_cnt = len(gt_restaurants)

        r_p = r_match_cnt / r_pred_cnt if r_pred_cnt > 0 else (1.0 if r_target_cnt == 0 else 0.0)
        r_r = r_match_cnt / r_target_cnt if r_target_cnt > 0 else (1.0 if r_pred_cnt == 0 else 0.0)
        r_f1 = (2 * r_p * r_r / (r_p + r_r)) if (r_p + r_r) > 0 else 0.0

        rest_ner = NERScore(
            precision=round(r_p, 4),
            recall=round(r_r, 4),
            f1=round(r_f1, 4),
            matched_count=r_match_cnt,
            pred_count=r_pred_cnt,
            target_count=r_target_cnt,
        )

        # --- 2. 菜品实体对齐与评测 ---
        matched_dish_tuples: list[tuple[str, str, str, str]] = []
        d_match_cnt = 0
        all_pred_dishes_cnt = sum(len(r.dishes) for r in pred_restaurants)
        all_gt_dishes_cnt = sum(len(r.get("dishes", [])) for r in gt_restaurants)

        # 在匹配成功的餐厅对之间进行菜品对齐
        for p_r, g_r in matched_rest_pairs:
            unmatched_gt_dishes = list(g_r.get("dishes", []))
            for p_d in p_r.dishes:
                best_gt_dish = None
                best_sim = 0.0
                p_name_clean = p_d.name.strip()

                for g_d in unmatched_gt_dishes:
                    g_name_clean = g_d["name"].strip()
                    sim = fuzz.token_set_ratio(p_name_clean, g_name_clean)
                    # 包含匹配加分
                    if p_name_clean in g_name_clean or g_name_clean in p_name_clean:
                        sim = max(sim, 85.0)

                    if sim > best_sim:
                        best_sim = sim
                        best_gt_dish = g_d

                if best_gt_dish and best_sim >= cls.DISH_MATCH_THRESHOLD:
                    d_match_cnt += 1
                    unmatched_gt_dishes.remove(best_gt_dish)
                    matched_dish_tuples.append(
                        (p_d.name, best_gt_dish["name"], p_d.verdict, best_gt_dish.get("verdict", "一般"))
                    )

        d_p = d_match_cnt / all_pred_dishes_cnt if all_pred_dishes_cnt > 0 else (1.0 if all_gt_dishes_cnt == 0 else 0.0)
        d_r = d_match_cnt / all_gt_dishes_cnt if all_gt_dishes_cnt > 0 else (1.0 if all_pred_dishes_cnt == 0 else 0.0)
        d_f1 = (2 * d_p * d_r / (d_p + d_r)) if (d_p + d_r) > 0 else 0.0

        dish_ner = NERScore(
            precision=round(d_p, 4),
            recall=round(d_r, 4),
            f1=round(d_f1, 4),
            matched_count=d_match_cnt,
            pred_count=all_pred_dishes_cnt,
            target_count=all_gt_dishes_cnt,
        )

        # --- 3. 情感三分类计算 ---
        conf_matrix: dict[str, dict[str, int]] = {
            gt_lbl: {pred_lbl: 0 for pred_lbl in SENTIMENT_LABELS}
            for gt_lbl in SENTIMENT_LABELS
        }

        correct_verdict_cnt = 0
        false_rec_cnt = 0
        total_avoid_cnt = 0

        for _, _, p_v, g_v in matched_dish_tuples:
            norm_pv = p_v if p_v in SENTIMENT_LABELS else "一般"
            norm_gv = g_v if g_v in SENTIMENT_LABELS else "一般"

            conf_matrix[norm_gv][norm_pv] += 1
            if norm_pv == norm_gv:
                correct_verdict_cnt += 1

            if norm_gv == "踩雷":
                total_avoid_cnt += 1
                if norm_pv == "推荐":
                    false_rec_cnt += 1

        acc = correct_verdict_cnt / len(matched_dish_tuples) if matched_dish_tuples else 1.0

        # 计算每个类别的 F1
        class_f1_dict = {}
        active_f1s = []
        for lbl in SENTIMENT_LABELS:
            tp = conf_matrix[lbl][lbl]
            fp = sum(conf_matrix[other][lbl] for other in SENTIMENT_LABELS if other != lbl)
            fn = sum(conf_matrix[lbl][other] for other in SENTIMENT_LABELS if other != lbl)
            if tp + fp + fn == 0:
                continue
            c_p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            c_r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            c_f1 = (2 * c_p * c_r / (c_p + c_r)) if (c_p + c_r) > 0 else 0.0
            class_f1_dict[lbl] = round(c_f1, 4)
            active_f1s.append(c_f1)

        macro_f1 = sum(active_f1s) / len(active_f1s) if active_f1s else 1.0
        false_rec_rate = false_rec_cnt / total_avoid_cnt if total_avoid_cnt > 0 else 0.0

        sentiment_metrics = SentimentMetrics(
            accuracy=round(acc, 4),
            macro_f1=round(macro_f1, 4),
            class_f1=class_f1_dict,
            confusion_matrix=conf_matrix,
            false_recommendation_count=false_rec_cnt,
            total_avoid_dishes=total_avoid_cnt,
            false_recommendation_rate=round(false_rec_rate, 4),
        )

        # --- 4. 保真度与抗幻觉计算 ---
        faithful_cnt = 0
        hallucinated_cnt = 0
        clean_transcript = re.sub(r"[^\w\u4e00-\u9fa5]", "", transcript_text)

        for p_r in pred_restaurants:
            for p_d in p_r.dishes:
                quote = p_d.original_quote.strip()
                if not quote or len(quote) < 3:
                    continue

                clean_quote = re.sub(r"[^\w\u4e00-\u9fa5]", "", quote)
                if not clean_quote:
                    continue

                # 检查是否包含在字幕文本中
                if clean_quote in clean_transcript:
                    faithful_cnt += 1
                else:
                    # 使用 partial_ratio 容忍微小 ASR 切词差异
                    partial_sim = fuzz.partial_ratio(clean_quote, clean_transcript)
                    if partial_sim >= cls.QUOTE_MATCH_THRESHOLD:
                        faithful_cnt += 1
                    else:
                        hallucinated_cnt += 1

        total_quotes = faithful_cnt + hallucinated_cnt
        faithfulness_rate = faithful_cnt / total_quotes if total_quotes > 0 else 1.0

        faithfulness = FaithfulnessMetrics(
            faithfulness_rate=round(faithfulness_rate, 4),
            hallucination_rate=round(1.0 - faithfulness_rate, 4),
            faithful_quotes=faithful_cnt,
            hallucinated_quotes=hallucinated_cnt,
            total_quotes=total_quotes,
        )

        matched_rest_names = [(pr.name, gr["name"]) for pr, gr in matched_rest_pairs]

        return SampleEvalResult(
            sample_id=sample_id,
            restaurant_ner=rest_ner,
            dish_ner=dish_ner,
            sentiment_metrics=sentiment_metrics,
            faithfulness=faithfulness,
            schema_valid=schema_valid,
            confidence=confidence,
            matched_restaurants=matched_rest_names,
            matched_dishes=matched_dish_tuples,
        )

    @classmethod
    def evaluate_batch(
        cls,
        model_name: str,
        samples: list[dict[str, Any]],
        predictions: list[ExtractionResult],
    ) -> EvalReport:
        """批量聚合评估报告"""
        assert len(samples) == len(predictions), "样本数与预测结果数必须相等"

        sample_results: list[SampleEvalResult] = []
        total_samples = len(samples)

        for sample, pred in zip(samples, predictions):
            res = cls.evaluate_sample(
                sample_id=sample.get("id", ""),
                predicted=pred,
                ground_truth=sample.get("ground_truth", {}),
                transcript_text=sample.get("transcript_text", ""),
            )
            sample_results.append(res)

        # 汇总统计
        valid_schema_cnt = sum(1 for s in sample_results if s.schema_valid)
        avg_conf = sum(s.confidence for s in sample_results) / total_samples if total_samples else 0.0

        # 宏观 NER
        r_pred_total = sum(s.restaurant_ner.pred_count for s in sample_results)
        r_tgt_total = sum(s.restaurant_ner.target_count for s in sample_results)
        r_match_total = sum(s.restaurant_ner.matched_count for s in sample_results)

        r_p = r_match_total / r_pred_total if r_pred_total else (1.0 if r_tgt_total == 0 else 0.0)
        r_r = r_match_total / r_tgt_total if r_tgt_total else (1.0 if r_pred_total == 0 else 0.0)
        r_f1 = (2 * r_p * r_r / (r_p + r_r)) if (r_p + r_r) > 0 else 0.0

        d_pred_total = sum(s.dish_ner.pred_count for s in sample_results)
        d_tgt_total = sum(s.dish_ner.target_count for s in sample_results)
        d_match_total = sum(s.dish_ner.matched_count for s in sample_results)

        d_p = d_match_total / d_pred_total if d_pred_total else (1.0 if d_tgt_total == 0 else 0.0)
        d_r = d_match_total / d_tgt_total if d_tgt_total else (1.0 if d_pred_total == 0 else 0.0)
        d_f1 = (2 * d_p * d_r / (d_p + d_r)) if (d_p + d_r) > 0 else 0.0

        # 全局混淆矩阵汇总
        agg_matrix: dict[str, dict[str, int]] = {
            gt_lbl: {pred_lbl: 0 for pred_lbl in SENTIMENT_LABELS}
            for gt_lbl in SENTIMENT_LABELS
        }

        total_matched_dishes = 0
        total_correct_verdicts = 0
        total_avoid = 0
        total_false_rec = 0

        for s in sample_results:
            for gt_lbl in SENTIMENT_LABELS:
                for pred_lbl in SENTIMENT_LABELS:
                    agg_matrix[gt_lbl][pred_lbl] += s.sentiment_metrics.confusion_matrix.get(gt_lbl, {}).get(pred_lbl, 0)

            total_matched_dishes += s.dish_ner.matched_count
            total_avoid += s.sentiment_metrics.total_avoid_dishes
            total_false_rec += s.sentiment_metrics.false_recommendation_count

        total_correct_verdicts = sum(agg_matrix[lbl][lbl] for lbl in SENTIMENT_LABELS)
        overall_acc = total_correct_verdicts / total_matched_dishes if total_matched_dishes else 1.0

        # 全局 Macro-F1
        agg_class_f1 = {}
        active_agg_f1s = []
        for lbl in SENTIMENT_LABELS:
            tp = agg_matrix[lbl][lbl]
            fp = sum(agg_matrix[other][lbl] for other in SENTIMENT_LABELS if other != lbl)
            fn = sum(agg_matrix[lbl][other] for other in SENTIMENT_LABELS if other != lbl)
            if tp + fp + fn == 0:
                continue
            c_p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            c_r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            c_f1 = (2 * c_p * c_r / (c_p + c_r)) if (c_p + c_r) > 0 else 0.0
            agg_class_f1[lbl] = round(c_f1, 4)
            active_agg_f1s.append(c_f1)

        agg_macro_f1 = sum(active_agg_f1s) / len(active_agg_f1s) if active_agg_f1s else 1.0
        agg_false_rec_rate = total_false_rec / total_avoid if total_avoid else 0.0

        # 保真度汇总
        total_quotes = sum(s.faithfulness.total_quotes for s in sample_results)
        total_faithful = sum(s.faithfulness.faithful_quotes for s in sample_results)
        overall_faithfulness = total_faithful / total_quotes if total_quotes else 1.0

        return EvalReport(
            model_name=model_name,
            total_samples=total_samples,
            schema_valid_rate=round(valid_schema_cnt / total_samples, 4) if total_samples else 0.0,
            avg_confidence=round(avg_conf, 4),
            restaurant_precision=round(r_p, 4),
            restaurant_recall=round(r_r, 4),
            restaurant_f1=round(r_f1, 4),
            dish_precision=round(d_p, 4),
            dish_recall=round(d_r, 4),
            dish_f1=round(d_f1, 4),
            sentiment_accuracy=round(overall_acc, 4),
            sentiment_macro_f1=round(agg_macro_f1, 4),
            sentiment_confusion_matrix=agg_matrix,
            false_recommendation_rate=round(agg_false_rec_rate, 4),
            faithfulness_rate=round(overall_faithfulness, 4),
            hallucination_rate=round(1.0 - overall_faithfulness, 4),
            sample_results=sample_results,
        )
