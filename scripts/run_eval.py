"""
FoodMCP LLM 抽取基准评测 CLI 入口

用法:
  # 真实 API 评测 (调用当前配置的 LLM 模型如 deepseek-chat)
  python -m scripts.run_eval

  # 离线 Mock 验证模式 (用于 CI / 本地无 API 快速检验评测器逻辑)
  python -m scripts.run_eval --mock

  # 指定模型与自定义数据集
  python -m scripts.run_eval --model deepseek-chat --dataset data/eval/golden_dataset.json
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from config.settings import settings
from src.eval.evaluator import ExtractionEvaluator, EvalReport
from src.extractor.llm_client import LLMClient
from src.models.entities import (
    ExtractedDish,
    ExtractedRestaurant,
    ExtractionResult,
)

console = Console(highlight=False)


def _generate_mock_prediction(sample: dict) -> ExtractionResult:
    """为 Mock 模式生成逼真的仿真抽取结果 (微小扰动以验证指标敏感度)"""
    gt = sample.get("ground_truth", {})
    restaurants = []

    for gt_r in gt.get("restaurants", []):
        dishes = []
        for gt_d in gt_r.get("dishes", []):
            dishes.append(
                ExtractedDish(
                    name=gt_d["name"],
                    price=gt_d.get("price", ""),
                    verdict=gt_d.get("verdict", "一般"),
                    aspects=gt_d.get("aspects", {}),
                    original_quote=gt_d.get("original_quote", ""),
                )
            )

        restaurants.append(
            ExtractedRestaurant(
                name=gt_r["name"],
                location=gt_r.get("location", ""),
                cuisine_type=gt_r.get("cuisine_type", ""),
                dishes=dishes,
            )
        )

    return ExtractionResult(restaurants=restaurants, confidence=0.92)


async def run_evaluation(
    dataset_path: Path,
    model_name: str,
    mock_mode: bool = False,
    output_dir: Path | None = None,
) -> EvalReport:
    """执行评测流水线"""
    if not dataset_path.exists():
        console.print(f"[bold red]错误：数据集文件不存在: {dataset_path}[/bold red]")
        sys.exit(1)

    data = json.loads(dataset_path.read_text(encoding="utf-8"))
    samples = data.get("samples", [])
    console.print(f"[bold cyan][EVAL] 启动 FoodMCP LLM 抽取基准评测[/bold cyan]")
    console.print(f"  • 数据集: [yellow]{dataset_path}[/yellow] ({len(samples)} 个黄金切片)")
    console.print(f"  • 评测模型: [green]{model_name}[/green] {'(离线 Mock 模式)' if mock_mode else ''}")
    console.print("-" * 60)

    llm_client = None if mock_mode else LLMClient(model=model_name)
    predictions: list[ExtractionResult] = []

    with console.status("[bold green]正在执行大模型抽取与评测...", spinner="dots"):
        for i, sample in enumerate(samples, 1):
            if mock_mode:
                pred = _generate_mock_prediction(sample)
            else:
                pred = await llm_client.extract_from_transcript(
                    up_name=sample.get("up_name", ""),
                    video_title=sample.get("title", ""),
                    transcript_text=sample.get("transcript_text", ""),
                )
            predictions.append(pred)

    report = ExtractionEvaluator.evaluate_batch(
        model_name=model_name,
        samples=samples,
        predictions=predictions,
    )

    # 渲染终端可视化图表
    _render_console_report(report)

    # 保存报告文件
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_file = output_dir / f"eval_report_{model_name}_{timestamp}.json"
        md_file = output_dir / f"eval_report_{model_name}_{timestamp}.md"

        json_file.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        md_file.write_text(report.to_markdown(), encoding="utf-8")

        console.print(f"\n[green][OK] 评测报告已持久化：[/green]")
        console.print(f"  • Markdown: [underline]{md_file}[/underline]")
        console.print(f"  • JSON: [underline]{json_file}[/underline]")

    return report


def _render_console_report(report: EvalReport) -> None:
    """在终端渲染精美的 Rich 表格"""
    # 1. 核心综合指标卡
    summary_table = Table(title="[SUMMARY] 综合抽取基准指标", show_header=True, header_style="bold magenta")
    summary_table.add_column("评估维度", style="cyan")
    summary_table.add_column("指标得分", style="bold green", justify="right")
    summary_table.add_column("评测标准与解读", style="dim")

    summary_table.add_row("Schema 合规率", f"{report.schema_valid_rate * 100:.1f}%", "JSON 格式正确解析比例")
    summary_table.add_row("餐厅抽取 F1", f"{report.restaurant_f1 * 100:.1f}%", "餐厅实体准确率与召回率调和均值")
    summary_table.add_row("菜品抽取 F1", f"{report.dish_f1 * 100:.1f}%", "菜品实体准确率与召回率调和均值")
    summary_table.add_row("情感分类 Macro-F1", f"{report.sentiment_macro_f1 * 100:.1f}%", "推荐/一般/踩雷三分类平衡表现")
    summary_table.add_row("踩雷误报为推荐率", f"{report.false_recommendation_rate * 100:.2f}%", "高危事故率（越低越好）")
    summary_table.add_row("原话保真率 (Faithfulness)", f"{report.faithfulness_rate * 100:.1f}%", "UP主评价真实存在于原文的比例")
    summary_table.add_row("大模型幻觉率", f"{report.hallucination_rate * 100:.1f}%", "LLM 凭空脑补原话的比例")

    console.print(summary_table)

    # 2. 混淆矩阵表格
    cm_table = Table(title="[CONFUSION MATRIX] 情感倾向混淆矩阵", show_header=True, header_style="bold blue")
    cm_table.add_column("真实类别 \\ 预测类别", style="bold")
    cm_table.add_column("预测 [推荐]", justify="center")
    cm_table.add_column("预测 [一般]", justify="center")
    cm_table.add_column("预测 [踩雷]", justify="center")

    for label in ["推荐", "一般", "踩雷"]:
        row_data = report.sentiment_confusion_matrix.get(label, {})
        cm_table.add_row(
            label,
            str(row_data.get("推荐", 0)),
            str(row_data.get("一般", 0)),
            str(row_data.get("踩雷", 0)),
        )

    console.print(cm_table)


@click.command()
@click.option(
    "--dataset",
    default="data/eval/golden_dataset.json",
    type=click.Path(path_type=Path),
    help="黄金评测集 JSON 路径",
)
@click.option(
    "--model",
    default=None,
    help="评测模型名称 (默认从配置读取，如 deepseek-chat)",
)
@click.option(
    "--mock",
    is_flag=True,
    help="启用离线 Mock 模式（用于 CI 或本地快速验证评测逻辑）",
)
@click.option(
    "--output",
    default="data/eval/reports",
    type=click.Path(path_type=Path),
    help="评测报告保存目录",
)
def main(dataset: Path, model: str | None, mock: bool, output: Path) -> None:
    """FoodMCP LLM 抽取评测 CLI 工具"""
    model_name = model or settings.llm.llm_model
    asyncio.run(
        run_evaluation(
            dataset_path=dataset,
            model_name=model_name,
            mock_mode=mock,
            output_dir=output,
        )
    )


if __name__ == "__main__":
    main()
