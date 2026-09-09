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


if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


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
@click.option("--resume/--no-resume", default=True, help="是否启用断点续传跳过已完成视频（默认启用）")
@click.option("--max-retries", default=3, type=int, help="单视频最大重试次数")
@click.option("--status", is_flag=True, help="仅查询该 UP主的历史任务处理状态统计")
def main(
    up_mid: int,
    city: str,
    limit: int,
    skip_store: bool,
    resume: bool,
    max_retries: int,
    status: bool,
) -> None:
    """B站探店视频数据 Pipeline"""
    setup_logging()

    if status:
        asyncio.run(_show_status(up_mid, limit))
        return

    logger.info("=" * 60)
    logger.info("B站探店视频 Pipeline")
    logger.info(f"  UP主MID: {up_mid}")
    logger.info(f"  目标城市: {city or '自动识别'}")
    logger.info(f"  最大视频数: {limit}")
    logger.info(f"  跳过存储: {skip_store}")
    logger.info(f"  断点续传: {resume}")
    logger.info(f"  最大重试: {max_retries}")
    logger.info("=" * 60)

    asyncio.run(_run(up_mid, city, limit, skip_store, resume, max_retries))


async def _show_status(up_mid: int, limit: int) -> None:
    """查询并展示指定 UP 主的历史任务状态"""
    from src.storage.pg_store import PostgresStore

    pg = PostgresStore()
    try:
        await pg.connect()
        tasks = await pg.list_pipeline_tasks(up_mid=up_mid, limit=limit)

        click.echo("\n" + "=" * 80)
        click.echo(f"[UP主任务状态监控] MID: {up_mid} (共查询到 {len(tasks)} 条任务)")
        click.echo("=" * 80)

        if not tasks:
            click.echo("  暂无历史任务记录")
        else:
            for t in tasks:
                st = t["status"]
                icon = "[STORED]" if st in ("STORED", "done") else f"[{st}]"
                err_info = f" (错误: {t['error_message']})" if t.get("error_message") else ""
                click.echo(
                    f"  {icon:<10} [{t['bvid']}] {t['title'][:32]:<32} "
                    f"| 阶段: {t['stage']:<10} | 重试: {t['retry_count']} | "
                    f"餐厅: {t['restaurant_count']} | 菜品: {t['dish_count']}{err_info}"
                )

        click.echo("=" * 80)
    finally:
        await pg.close()


async def _run(
    up_mid: int,
    city: str,
    limit: int,
    skip_store: bool,
    resume: bool,
    max_retries: int,
) -> None:
    """异步运行 Pipeline"""
    from src.models.entities import TaskStatus
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
            resume=resume,
            max_retries=max_retries,
        )

        # 打印汇总
        click.echo("\n" + "=" * 70)
        click.echo("[Pipeline Summary]")
        click.echo("=" * 70)

        for task in tasks:
            if task.status == TaskStatus.STORED:
                icon = "[STORED]"
            elif task.status == TaskStatus.SKIPPED:
                icon = "[SKIPPED]"
            elif task.status == TaskStatus.FAILED:
                icon = "[FAILED]"
            else:
                icon = f"[{task.status.value}]"

            rest_count = len(task.extraction.restaurants) if task.extraction else task.restaurant_count
            dish_count = (
                sum(len(r.dishes) for r in task.extraction.restaurants)
                if task.extraction
                else task.dish_count
            )
            extra = f" (错误: {task.error_message})" if task.error_message else ""
            click.echo(
                f"  {icon:<10} [{task.bvid}] {task.title[:30]:<30}"
                f" -> {rest_count} restaurants, {dish_count} dishes{extra}"
            )

        click.echo("=" * 70)

    finally:
        if not skip_store:
            await runner.close_stores()


if __name__ == "__main__":
    main()
