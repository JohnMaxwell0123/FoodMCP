"""
Pipeline 任务状态机与断点续传单元测试
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.entities import (
    ExtractionResult, PipelineTask, TaskStatus, TranscriptResult, VideoInfo,
)
from src.pipeline.runner import PipelineRunner
from src.storage.pg_store import PostgresStore


class TestPipelineTaskModel:
    """测试 PipelineTask 数据模型及状态转换"""

    def test_model_auto_properties(self) -> None:
        """测试由 VideoInfo 自动推导 bvid, up_mid, title 及默认状态"""
        video = VideoInfo(
            bvid="BV123456789",
            title="探店北京胡同涮肉",
            up_mid="987654",
            up_name="探店老饕",
        )
        task = PipelineTask(video=video)

        assert task.bvid == "BV123456789"
        assert task.up_mid == 987654
        assert task.title == "探店北京胡同涮肉"
        assert task.status == TaskStatus.PENDING
        assert task.stage == "init"
        assert task.retry_count == 0
        assert task.updated_at is not None

    def test_status_normalization(self) -> None:
        """测试历史遗留字符串状态值自动规范化为 TaskStatus 枚举"""
        video = VideoInfo(bvid="BV1", title="test", up_mid="1")

        t1 = PipelineTask(video=video, status="done")
        assert t1.status == TaskStatus.STORED

        t2 = PipelineTask(video=video, status="error")
        assert t2.status == TaskStatus.FAILED

        t3 = PipelineTask(video=video, status="processing")
        assert t3.status == TaskStatus.PROCESSING

        t4 = PipelineTask(video=video, status="skipped")
        assert t4.status == TaskStatus.SKIPPED

        t5 = PipelineTask(video=video, status="SUBTITLE_EXTRACTED")
        assert t5.status == TaskStatus.SUBTITLE_EXTRACTED


class TestPostgresPipelineState:
    """测试 PostgresStore 对任务状态机与断点续传的 SQL 交互"""

    @pytest.mark.asyncio
    async def test_upsert_pipeline_task(self) -> None:
        """测试 upsert_pipeline_task 的 SQL 构造与参数传递"""
        store = PostgresStore()
        mock_conn = MagicMock()
        mock_cursor = AsyncMock()
        mock_conn.cursor.return_value.__aenter__.return_value = mock_cursor
        store._conn = mock_conn

        video = VideoInfo(bvid="BV100", title="成都串串香", up_mid="555")
        task = PipelineTask(
            video=video,
            status=TaskStatus.STORED,
            stage="completed",
            retry_count=1,
            restaurant_count=1,
            dish_count=5,
            transcript_source="ai",
        )

        await store.upsert_pipeline_task(task)

        assert mock_cursor.execute.called
        sql_arg, params_arg = mock_cursor.execute.call_args[0]
        assert "INSERT INTO pipeline_tasks" in sql_arg
        assert "ON CONFLICT (bvid) DO UPDATE" in sql_arg
        assert params_arg[0] == "BV100"
        assert params_arg[1] == 555
        assert params_arg[3] == "STORED"
        assert params_arg[4] == "completed"
        assert params_arg[5] == 1
        assert params_arg[7] == "ai"
        assert params_arg[8] == 1
        assert params_arg[9] == 5

    @pytest.mark.asyncio
    async def test_get_completed_bvids(self) -> None:
        """测试获取已落盘视频 BVID 集合用于断点续传"""
        store = PostgresStore()
        mock_conn = MagicMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall.return_value = [("BV111",), ("BV222",)]
        mock_conn.cursor.return_value.__aenter__.return_value = mock_cursor
        store._conn = mock_conn

        completed = await store.get_completed_bvids(up_mid=555)

        assert completed == {"BV111", "BV222"}
        sql_arg, params_arg = mock_cursor.execute.call_args[0]
        assert "status IN ('STORED', 'done')" in sql_arg
        assert "AND up_mid = %s" in sql_arg
        assert params_arg == (555,)


class TestPipelineRunnerResumption:
    """测试 PipelineRunner 断点续传调度与重试机制"""

    @pytest.mark.asyncio
    async def test_resume_skips_completed_videos(self) -> None:
        """测试开启 resume 时秒级跳过已落盘视频，不执行字幕与大模型抽取"""
        runner = PipelineRunner()

        video_done = VideoInfo(bvid="BV_DONE", title="已完成探店", up_mid="100", up_name="老饕")
        video_new = VideoInfo(bvid="BV_NEW", title="新探店", up_mid="100", up_name="老饕")

        # Mock B 站采集与筛选
        runner.bilibili.get_up_videos = AsyncMock(return_value=[video_done, video_new])
        runner.video_filter.filter_videos = MagicMock(return_value=[video_done, video_new])

        # Mock PG 存储已存在 BV_DONE
        runner.pg.get_completed_bvids = AsyncMock(return_value={"BV_DONE"})
        runner.pg.upsert_pipeline_task = AsyncMock()

        # Mock 字幕提取与大模型
        mock_transcript = TranscriptResult(
            video_bvid="BV_NEW", source="ai", full_text="这家菜不错"
        )
        runner.subtitle_extractor.extract = AsyncMock(return_value=mock_transcript)

        mock_extraction = ExtractionResult(restaurants=[], confidence=0.9)
        runner.llm.extract_from_transcript = AsyncMock(return_value=mock_extraction)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            tasks = await runner.run(up_mid=100, skip_store=False, resume=True)

        assert len(tasks) == 2

        # 验证 BV_DONE 被跳过
        task_done = next(t for t in tasks if t.bvid == "BV_DONE")
        assert task_done.status == TaskStatus.SKIPPED
        assert task_done.stage == "resumed"

        # 验证 BV_NEW 正常执行完成
        task_new = next(t for t in tasks if t.bvid == "BV_NEW")
        assert task_new.status == TaskStatus.STORED

        # 验证字幕提取与 LLM 仅对新视频调用过 1 次
        assert runner.subtitle_extractor.extract.call_count == 1
        runner.subtitle_extractor.extract.assert_called_once_with("BV_NEW")
        assert runner.llm.extract_from_transcript.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_subtitle_failure_records_error(self) -> None:
        """测试无可用字幕时标记 FAILED 并持久化状态"""
        runner = PipelineRunner()

        video = VideoInfo(bvid="BV_NO_SUB", title="无字幕视频", up_mid="200", up_name="老饕")
        runner.bilibili.get_up_videos = AsyncMock(return_value=[video])
        runner.video_filter.filter_videos = MagicMock(return_value=[video])
        runner.pg.get_completed_bvids = AsyncMock(return_value=set())
        runner.pg.upsert_pipeline_task = AsyncMock()

        # 返回空字幕
        empty_transcript = TranscriptResult(video_bvid="BV_NO_SUB", source="", full_text="")
        runner.subtitle_extractor.extract = AsyncMock(return_value=empty_transcript)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            tasks = await runner.run(up_mid=200, skip_store=False, resume=True)

        assert len(tasks) == 1
        task = tasks[0]
        assert task.status == TaskStatus.FAILED
        assert task.error_message == "无可用字幕"
        assert runner.pg.upsert_pipeline_task.called
