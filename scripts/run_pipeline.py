"""
Pipeline CLI 入口

用法:
  python -m scripts.run_pipeline --up-mid 12345 --city 北京 --limit 10
  python -m scripts.run_pipeline --up-mid 12345 --city 上海 --skip-store
"""

from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import click
from loguru import logger

from config.settings import settings


def setup_logging() -> None:
    """配置日志"""
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan> | "
            "<level>{message}</level>"
        ),
    )
    log_file = settings.data_dir / "pipeline.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger.add(str(log_file), rotation="10 MB", level="DEBUG")


@click.command()
@click.option("--up-mid", required=True, type=int, help="UP主的B站MID")
@click.option("--city", default="", help="目标城市（用于数据标注）")
@click.option("--limit", default=20, type=int, help="最大处理视频数")
@click.option("--skip-store", is_flag=True, help="跳过数据库存储（调试模式）")
def main(up_mid: int, city: str, limit: int, skip_store: bool) -> None:
    """B站探店视频数据 Pipeline"""
    setup_logging()

    logger.info("=" * 60)
    logger.info(f"B站探店视频 Pipeline")
    logger.info(f"  UP主MID: {up_mid}")
    logger.info(f"  目标城市: {city or '自动识别'}")
    logger.info(f"  最大视频数: {limit}")
    logger.info(f"  跳过存储: {skip_store}")
    logger.info("=" * 60)

    asyncio.run(_run(up_mid, city, limit, skip_store))


async def _run(up_mid: int, city: str, limit: int, skip_store: bool) -> None:
    """异步运行 Pipeline"""
    from src.pipeline.runner import PipelineRunner

    runner = PipelineRunner()

    try:
        if not skip_store:
            await runner.init_stores()

        tasks = await runner.run(
            up_mid=up_mid,
            city=city,
            limit=limit,
            skip_store=skip_store,
        )

        # 打印汇总
        click.echo("\n" + "=" * 60)
        click.echo("[Pipeline Summary]")
        click.echo("=" * 60)

        for task in tasks:
            icon = "[OK]" if task.status == "done" else "[FAIL]"
            rest_count = len(task.extraction.restaurants) if task.extraction else 0
            dish_count = (
                sum(len(r.dishes) for r in task.extraction.restaurants)
                if task.extraction
                else 0
            )
            click.echo(
                f"  {icon} [{task.video.bvid}] {task.video.title[:40]}"
                f"  -> {rest_count} restaurants, {dish_count} dishes"
            )

        click.echo("=" * 60)

    finally:
        if not skip_store:
            await runner.close_stores()


if __name__ == "__main__":
    main()
