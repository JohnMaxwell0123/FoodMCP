"""
端到端 Pipeline 编排

完整流程:
  1. 获取UP主视频列表
  2. 筛选探店类视频
  3. 提取/转写字幕
  4. LLM信息抽取
  5. 数据存储（PG + Neo4j + Milvus）
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

from loguru import logger

from config.settings import settings
from src.collector.bilibili_client import BilibiliClient
from src.collector.subtitle_extractor import SubtitleExtractor
from src.collector.video_filter import VideoFilter
from src.extractor.llm_client import LLMClient
from src.models.entities import (
    Dish, ExtractionResult, PipelineTask, Restaurant,
    Review, Sentiment, UPMaster, VideoInfo, AspectReview,
)
from src.storage.pg_store import PostgresStore
from src.storage.neo4j_store import Neo4jStore
from src.storage.vector_store import VectorStore
from src.geocode.amap_client import AmapClient


class PipelineRunner:
    """数据处理 Pipeline"""

    def __init__(self) -> None:
        self.bilibili = BilibiliClient()
        self.subtitle_extractor = SubtitleExtractor()
        self.video_filter = VideoFilter()
        self.llm = LLMClient()
        self.pg = PostgresStore()
        self.neo4j = Neo4jStore()
        self.vector = VectorStore()
        self.amap = AmapClient()

    async def init_stores(self) -> None:
        """初始化所有存储后端"""
        await self.pg.connect()
        await self.pg.init_tables()
        await self.neo4j.connect()
        await self.neo4j.init_constraints()
        self.vector.connect()
        self.vector.init_collection()
        logger.info("所有存储后端初始化完成")

    async def close_stores(self) -> None:
        """关闭所有存储后端"""
        await self.pg.close()
        await self.neo4j.close()
        self.vector.close()

    async def run(
        self,
        up_mid: int,
        city: str = "",
        limit: int = 20,
        skip_store: bool = False,
    ) -> list[PipelineTask]:
        """
        运行完整 Pipeline

        Args:
            up_mid: UP主MID
            city: 目标城市（用于数据标注）
            limit: 最大处理视频数
            skip_store: 是否跳过数据库存储（调试用）

        Returns:
            处理任务列表
        """
        settings.ensure_data_dirs()

        logger.info(f"=== Pipeline 启动: UP主={up_mid}, 城市={city}, 限制={limit} ===")

        # Step 1: 获取视频列表
        logger.info("Step 1: 获取视频列表...")
        all_videos = await self.bilibili.get_up_videos(mid=up_mid, max_pages=2)
        logger.info(f"获取到 {len(all_videos)} 个视频")

        # Step 2: 筛选探店视频
        logger.info("Step 2: 筛选探店视频...")
        food_videos = self.video_filter.filter_videos(all_videos)
        food_videos = food_videos[:limit]
        logger.info(f"筛选出 {len(food_videos)} 个探店视频")

        if not food_videos:
            logger.warning("未找到探店视频，Pipeline 结束")
            return []

        # Step 3 & 4: 逐个处理视频
        tasks: list[PipelineTask] = []
        for i, video in enumerate(food_videos):
            logger.info(f"--- 处理视频 [{i+1}/{len(food_videos)}]: {video.title} ---")
            task = PipelineTask(video=video)

            try:
                # Step 3: 提取字幕
                task.status = "processing"
                transcript = await self.subtitle_extractor.extract(video.bvid)
                task.transcript = transcript

                if not transcript.full_text and not transcript.segments:
                    logger.warning(f"视频 {video.bvid} 无可用字幕，跳过")
                    task.status = "error"
                    task.error_message = "无可用字幕"
                    tasks.append(task)
                    continue

                # Step 4: LLM 信息抽取
                text = transcript.to_full_text()
                extraction = await self.llm.extract_from_transcript(
                    up_name=video.up_name,
                    video_title=video.title,
                    transcript_text=text,
                )
                task.extraction = extraction

                # Step 5: 存储
                if not skip_store and extraction.restaurants:
                    await self._store_extraction(
                        video=video, extraction=extraction, city=city,
                    )

                task.status = "done"

            except Exception as e:
                logger.error(f"处理视频 {video.bvid} 失败: {e}")
                task.status = "error"
                task.error_message = str(e)

            tasks.append(task)
            # 礼貌性延迟
            await asyncio.sleep(2.0)

        # 汇总统计
        done = sum(1 for t in tasks if t.status == "done")
        errors = sum(1 for t in tasks if t.status == "error")
        total_restaurants = sum(
            len(t.extraction.restaurants) for t in tasks
            if t.extraction and t.extraction.restaurants
        )
        total_dishes = sum(
            sum(len(r.dishes) for r in t.extraction.restaurants)
            for t in tasks if t.extraction and t.extraction.restaurants
        )

        logger.info(
            f"=== Pipeline 完成 ===\n"
            f"  处理: {done}/{len(tasks)} 成功, {errors} 失败\n"
            f"  提取: {total_restaurants} 个餐厅, {total_dishes} 道菜品"
        )

        # 保存报告
        self._save_report(tasks)

        return tasks

    async def _store_extraction(
        self, video: VideoInfo, extraction: ExtractionResult, city: str,
    ) -> None:
        """将提取结果存储到三个数据库"""

        # 确保UP主存在
        up = UPMaster(bilibili_uid=video.up_mid, name=video.up_name)
        existing = await self.pg.find_up_master_by_uid(video.up_mid)
        if existing:
            up.id = existing["id"]
        await self.pg.upsert_up_master(up)
        await self.neo4j.merge_up_master(up)

        for ext_rest in extraction.restaurants:
            # 存储餐厅
            restaurant = Restaurant(
                name=ext_rest.name,
                city=city or "未知",
                address=ext_rest.location,
                cuisine_type=ext_rest.cuisine_type,
            )
            existing_rest = await self.pg.find_restaurant_by_name(ext_rest.name, city)
            if existing_rest:
                restaurant.id = existing_rest["id"]
            await self.pg.upsert_restaurant(restaurant)

            # 通过高德 API 补全精确地址
            geo = await self.amap.resolve_address(
                name=ext_rest.name,
                location_hint=ext_rest.location,
                city=city or self._guess_city_from_location(ext_rest.location),
            )
            if geo:
                await self.pg.update_restaurant_geo(
                    restaurant_id=restaurant.id,
                    address=geo.address,
                    city=geo.city,
                    district=geo.district,
                    latitude=geo.latitude,
                    longitude=geo.longitude,
                )
                restaurant.address = geo.address
                restaurant.city = geo.city
                restaurant.latitude = geo.latitude
                restaurant.longitude = geo.longitude

            await self.neo4j.merge_restaurant(restaurant)

            for ext_dish in ext_rest.dishes:
                # 存储菜品
                sentiment_map = {"推荐": 0.8, "一般": 0.0, "踩雷": -0.8}
                dish = Dish(
                    name=ext_dish.name,
                    restaurant_id=restaurant.id,
                    price=float(ext_dish.price) if ext_dish.price.replace(".", "").isdigit() else None,
                    avg_sentiment=sentiment_map.get(ext_dish.verdict, 0.0),
                )
                await self.pg.upsert_dish(dish)
                await self.neo4j.merge_dish(dish, restaurant.id)

                # 存储评价
                sentiment_enum = {
                    "推荐": Sentiment.RECOMMENDED,
                    "一般": Sentiment.AVERAGE,
                    "踩雷": Sentiment.AVOID,
                }.get(ext_dish.verdict, Sentiment.AVERAGE)

                aspects = AspectReview(**{
                    k: v for k, v in ext_dish.aspects.items()
                    if k in ("taste", "texture", "portion", "presentation", "value")
                })

                review = Review(
                    up_master_id=up.id,
                    dish_id=dish.id,
                    restaurant_id=restaurant.id,
                    video_bvid=video.bvid,
                    timestamp=ext_dish.timestamp,
                    raw_text=ext_dish.original_quote,
                    sentiment=sentiment_enum,
                    sentiment_score=sentiment_map.get(ext_dish.verdict, 0.0),
                    aspects=aspects,
                )
                await self.pg.insert_review(review)
                await self.neo4j.create_review_relations(review, video.bvid)

                # 存储向量
                try:
                    embedding_text = f"{ext_dish.name}: {ext_dish.original_quote}"
                    embedding = await self.llm.get_embedding(embedding_text)
                    self.vector.insert([{
                        "id": str(uuid.uuid4()),
                        "review_id": review.id,
                        "dish_name": ext_dish.name,
                        "restaurant_name": ext_rest.name,
                        "city": city,
                        "sentiment": ext_dish.verdict,
                        "text": embedding_text[:2000],
                        "embedding": embedding,
                    }])
                except Exception as e:
                    logger.warning(f"向量存储失败: {e}")

    @staticmethod
    def _guess_city_from_location(location: str) -> str:
        """从位置文本中提取城市名"""
        known = [
            "北京", "上海", "广州", "深圳", "杭州", "成都", "重庆",
            "南京", "武汉", "西安", "长沙", "天津", "苏州", "厦门",
            "青岛", "大连", "昆明", "贵阳", "南宁", "哈尔滨", "沈阳",
            "郑州", "济南", "福州", "合肥", "南昌", "太原", "石家庄",
            "长春", "兰州", "银川", "西宁", "海口", "乌鲁木齐",
            "钦州", "柳州", "桂林", "北海", "澳门",
        ]
        for c in known:
            if c in location:
                return c
        return ""

    def _save_report(self, tasks: list[PipelineTask]) -> None:
        """保存 Pipeline 运行报告"""
        report_dir = settings.data_dir / "extractions"
        report_dir.mkdir(parents=True, exist_ok=True)

        report = []
        for task in tasks:
            entry = {
                "bvid": task.video.bvid,
                "title": task.video.title,
                "status": task.status,
                "error": task.error_message,
            }
            if task.extraction:
                entry["restaurants"] = [
                    r.model_dump() for r in task.extraction.restaurants
                ]
                entry["confidence"] = task.extraction.confidence
            report.append(entry)

        report_file = report_dir / "pipeline_report.json"
        report_file.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"Pipeline 报告已保存: {report_file}")
