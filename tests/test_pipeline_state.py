"""
Pipeline 任务状态机与断点续传单元测试
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.entities import (
    ExtractedDish, ExtractedRestaurant, ExtractionResult, PipelineTask, TaskStatus,
    TranscriptResult, VideoInfo,
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
        assert params_arg[10] == 0  # verified_quote_count

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


class TestStoreExtractionSentiment:
    """测试多UP主评价写入时菜品情感分的聚合顺序"""

    @pytest.mark.asyncio
    async def test_dish_sentiment_refreshed_after_review_and_synced_to_graph(self) -> None:
        """评价落库后按真实均值重算菜品情感分，并以该值写入 Neo4j 菜品节点"""
        runner = PipelineRunner()
        calls: list[str] = []

        runner.pg = MagicMock()
        runner.pg.find_up_master_by_uid = AsyncMock(return_value=None)
        runner.pg.upsert_up_master = AsyncMock()
        runner.pg.find_restaurant_by_name = AsyncMock(return_value={"id": "rest-001"})
        runner.pg.upsert_restaurant = AsyncMock()
        runner.pg.upsert_dish = AsyncMock(return_value="dish-001")
        runner.pg.insert_review = AsyncMock(side_effect=lambda r: calls.append("insert_review"))

        async def _refresh(dish_id: str) -> float:
            calls.append("refresh")
            return 0.27

        runner.pg.refresh_dish_sentiment = _refresh

        runner.neo4j = MagicMock()
        runner.neo4j.merge_up_master = AsyncMock()
        runner.neo4j.merge_restaurant = AsyncMock()
        runner.neo4j.merge_dish = AsyncMock(side_effect=lambda d, rid: calls.append("merge_dish"))
        runner.neo4j.create_review_relations = AsyncMock()

        runner.amap.resolve_address = AsyncMock(return_value=None)
        runner.llm.get_embedding = AsyncMock(return_value=[0.0])
        runner.vector = MagicMock()

        extraction = ExtractionResult(restaurants=[
            ExtractedRestaurant(name="测试餐厅", dishes=[
                ExtractedDish(name="红烧肉", verdict="踩雷", original_quote="太咸了"),
            ]),
        ])
        video = VideoInfo(bvid="BV_MULTI", title="探店", up_mid="300", up_name="老饕")

        await runner._store_extraction(video=video, extraction=extraction, city="北京")

        assert calls == ["insert_review", "refresh", "merge_dish"]
        synced_dish = runner.neo4j.merge_dish.call_args[0][0]
        assert synced_dish.avg_sentiment == 0.27


class TestEvidenceAndFailureHandling:
    """抽取失败不得被当作"已落盘"；入库时核验原话并记录出处"""

    @pytest.mark.asyncio
    async def test_llm_failure_marks_task_failed_not_stored(self) -> None:
        """LLM 调用失败时标记 FAILED，下次运行会重新处理，而不是被断点续传永久跳过"""
        runner = PipelineRunner()

        video = VideoInfo(bvid="BV_LLM_DOWN", title="探店", up_mid="300", up_name="老饕")
        runner.bilibili.get_up_videos = AsyncMock(return_value=[video])
        runner.video_filter.filter_videos = MagicMock(return_value=[video])
        runner.pg.get_completed_bvids = AsyncMock(return_value=set())
        runner.pg.upsert_pipeline_task = AsyncMock()
        runner.subtitle_extractor.extract = AsyncMock(return_value=TranscriptResult(
            video_bvid="BV_LLM_DOWN", source="ai", full_text="今天吃了红烧肉，太咸了别点"
        ))
        runner.llm.extract_from_transcript = AsyncMock(
            return_value=ExtractionResult(error="429 rate limited")
        )
        runner._store_extraction = AsyncMock()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            tasks = await runner.run(up_mid=300, skip_store=False, resume=True)

        task = tasks[0]
        assert task.status == TaskStatus.FAILED
        assert task.stage == "llm"
        assert task.error_message == "429 rate limited"
        assert not runner._store_extraction.called
        persisted = runner.pg.upsert_pipeline_task.call_args[0][0]
        assert persisted.status == TaskStatus.FAILED

    @pytest.mark.asyncio
    async def test_store_extraction_verifies_quotes_and_records_source(self) -> None:
        """原话对回字幕：对上的记时间点，对不上的标未核验；向量库与 PG 使用同一个城市"""
        from src.geocode.amap_client import GeoResult
        from src.models.entities import SubtitleSegment

        runner = PipelineRunner()

        runner.pg = MagicMock()
        runner.pg.find_up_master_by_uid = AsyncMock(return_value=None)
        runner.pg.upsert_up_master = AsyncMock()
        runner.pg.find_restaurant_by_name = AsyncMock(return_value=None)
        runner.pg.upsert_restaurant = AsyncMock()
        runner.pg.update_restaurant_geo = AsyncMock()
        runner.pg.upsert_dish = AsyncMock(side_effect=["dish-1", "dish-2"])
        runner.pg.insert_review = AsyncMock()
        runner.pg.refresh_dish_sentiment = AsyncMock(return_value=0.8)

        runner.neo4j = MagicMock()
        runner.neo4j.merge_up_master = AsyncMock()
        runner.neo4j.merge_restaurant = AsyncMock()
        runner.neo4j.merge_dish = AsyncMock()
        runner.neo4j.create_review_relations = AsyncMock()

        runner.amap.resolve_address = AsyncMock(return_value=GeoResult(
            name="示例河鲜馆", address="示例路1号", city="北京市", district="朝阳区",
            latitude=39.9, longitude=116.4, source="poi", confidence=0.8, is_verified=True,
        ))
        runner.llm.get_embedding = AsyncMock(return_value=[0.0])
        runner.vector = MagicMock()

        transcript = TranscriptResult(
            video_bvid="BV_EVIDENCE",
            source="ai",
            segments=[
                SubtitleSegment(start=10.0, end=14.0, text="今天来到这家河鲜馆"),
                SubtitleSegment(start=95.5, end=99.0, text="这鱼肉真的好嫩，进嘴之后不用嚼"),
            ],
        )
        extraction = ExtractionResult(restaurants=[
            ExtractedRestaurant(name="示例河鲜馆", location="北京朝阳", dishes=[
                ExtractedDish(name="清蒸鱼", verdict="推荐", original_quote="这鱼肉真的好嫩"),
                ExtractedDish(name="炒时蔬", verdict="一般", original_quote="字幕里根本没有这句话"),
            ]),
        ])
        video = VideoInfo(
            bvid="BV_EVIDENCE", title="探店", up_mid="300", up_name="老饕", publish_date="1700000000",
        )

        verified = await runner._store_extraction(
            video=video, extraction=extraction, city="", transcript=transcript,
        )

        assert verified == 1
        reviews = [c.args[0] for c in runner.pg.insert_review.call_args_list]
        assert reviews[0].quote_verified is True
        assert reviews[0].timestamp_seconds == 95.5
        assert reviews[0].timestamp == "01:35"
        assert reviews[0].video_published_at == "2023-11-15"
        assert reviews[1].quote_verified is False
        assert reviews[1].timestamp_seconds is None

        # 高德返回"北京市"，统一为"北京"；命令行没给城市时向量库也用这个城市
        assert runner.pg.update_restaurant_geo.call_args.kwargs["city"] == "北京"
        vector_rows = [c.args[0][0] for c in runner.vector.insert.call_args_list]
        assert {row["city"] for row in vector_rows} == {"北京"}
