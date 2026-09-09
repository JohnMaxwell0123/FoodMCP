"""
PostgreSQL 存储

负责存储结构化元数据：餐厅、菜品、UP主、评价等核心实体。
提供基础 CRUD 操作和查询接口。
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

from loguru import logger
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from config.settings import settings
from src.models.entities import (
    Dish, PipelineTask, Restaurant, Review, TaskStatus, UPMaster,
)

# 数据库初始化 DDL
INIT_SQL = """
-- 餐厅表
CREATE TABLE IF NOT EXISTS restaurants (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    city VARCHAR(100) NOT NULL,
    district VARCHAR(100) DEFAULT '',
    address TEXT DEFAULT '',
    cuisine_type VARCHAR(100) DEFAULT '其他',
    price_range VARCHAR(50) DEFAULT '',
    tags JSONB DEFAULT '[]',
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    geo_verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 菜品表
CREATE TABLE IF NOT EXISTS dishes (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    category VARCHAR(100) DEFAULT '',
    price DOUBLE PRECISION,
    restaurant_id VARCHAR(36) REFERENCES restaurants(id),
    avg_sentiment DOUBLE PRECISION DEFAULT 0.0,
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_dishes_restaurant_name UNIQUE (restaurant_id, name)
);

-- UP主表
CREATE TABLE IF NOT EXISTS up_masters (
    id VARCHAR(36) PRIMARY KEY,
    bilibili_uid VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    follower_count INTEGER DEFAULT 0,
    style_tags JSONB DEFAULT '[]',
    credibility_score DOUBLE PRECISION DEFAULT 0.5,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 评价表
CREATE TABLE IF NOT EXISTS reviews (
    id VARCHAR(36) PRIMARY KEY,
    up_master_id VARCHAR(36) REFERENCES up_masters(id),
    dish_id VARCHAR(36) REFERENCES dishes(id),
    restaurant_id VARCHAR(36) REFERENCES restaurants(id),
    video_bvid VARCHAR(50) NOT NULL,
    timestamp VARCHAR(50) DEFAULT '',
    raw_text TEXT NOT NULL,
    sentiment VARCHAR(20) NOT NULL,
    sentiment_score DOUBLE PRECISION DEFAULT 0.0,
    aspects JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

-- Pipeline 任务状态追踪表
CREATE TABLE IF NOT EXISTS pipeline_tasks (
    bvid VARCHAR(50) PRIMARY KEY,
    up_mid BIGINT NOT NULL,
    title TEXT NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    stage VARCHAR(30) DEFAULT '',
    retry_count INTEGER DEFAULT 0,
    error_message TEXT DEFAULT '',
    transcript_source VARCHAR(20) DEFAULT '',
    restaurant_count INTEGER DEFAULT 0,
    dish_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_restaurants_city ON restaurants(city);
CREATE INDEX IF NOT EXISTS idx_restaurants_name ON restaurants(name);
CREATE INDEX IF NOT EXISTS idx_dishes_restaurant ON dishes(restaurant_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_dishes_restaurant_name ON dishes(restaurant_id, name);
CREATE INDEX IF NOT EXISTS idx_reviews_restaurant ON reviews(restaurant_id);
CREATE INDEX IF NOT EXISTS idx_reviews_dish ON reviews(dish_id);
CREATE INDEX IF NOT EXISTS idx_reviews_up_master ON reviews(up_master_id);
CREATE INDEX IF NOT EXISTS idx_reviews_sentiment ON reviews(sentiment);
CREATE INDEX IF NOT EXISTS idx_pipeline_tasks_up_mid ON pipeline_tasks(up_mid);
CREATE INDEX IF NOT EXISTS idx_pipeline_tasks_status ON pipeline_tasks(status);
"""


class PostgresStore:
    """PostgreSQL 存储管理"""

    def __init__(self) -> None:
        self._conn: AsyncConnection | None = None

    @property
    def _dsn(self) -> str:
        return (
            f"host={settings.postgres.host} "
            f"port={settings.postgres.port} "
            f"dbname={settings.postgres.db} "
            f"user={settings.postgres.user} "
            f"password={settings.postgres.password}"
        )

    async def connect(self) -> None:
        """建立数据库连接"""
        try:
            self._conn = await AsyncConnection.connect(self._dsn)
            await self._conn.set_autocommit(True)
            logger.info("PostgreSQL 连接已建立")
        except Exception as e:
            logger.error(f"PostgreSQL 连接失败: {e}")
            raise

    async def close(self) -> None:
        """关闭连接"""
        if self._conn:
            try:
                await self._conn.close()
            except Exception:
                pass
            logger.info("PostgreSQL 连接已关闭")

    async def init_tables(self) -> None:
        """初始化数据表"""
        async with self._conn.cursor() as cur:
            await cur.execute(INIT_SQL)
            # 兼容已有库的增量 DDL 迁移
            await cur.execute(
                "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS geo_verified BOOLEAN DEFAULT FALSE;"
            )
            await cur.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_dishes_restaurant_name ON dishes(restaurant_id, name);"
            )
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS pipeline_tasks (
                    bvid VARCHAR(50) PRIMARY KEY,
                    up_mid BIGINT NOT NULL,
                    title TEXT NOT NULL,
                    status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
                    stage VARCHAR(30) DEFAULT '',
                    retry_count INTEGER DEFAULT 0,
                    error_message TEXT DEFAULT '',
                    transcript_source VARCHAR(20) DEFAULT '',
                    restaurant_count INTEGER DEFAULT 0,
                    dish_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_pipeline_tasks_up_mid ON pipeline_tasks(up_mid);
                CREATE INDEX IF NOT EXISTS idx_pipeline_tasks_status ON pipeline_tasks(status);
                """
            )
        logger.info("PostgreSQL 数据表初始化完成")

    # =========================================================
    # 餐厅 CRUD
    # =========================================================

    async def upsert_restaurant(self, restaurant: Restaurant) -> str:
        """插入或更新餐厅"""
        sql = """
            INSERT INTO restaurants (id, name, city, district, address, cuisine_type,
                                     price_range, tags, latitude, longitude, geo_verified)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                city = EXCLUDED.city,
                district = EXCLUDED.district,
                address = EXCLUDED.address,
                cuisine_type = EXCLUDED.cuisine_type,
                price_range = EXCLUDED.price_range,
                tags = EXCLUDED.tags,
                latitude = COALESCE(EXCLUDED.latitude, restaurants.latitude),
                longitude = COALESCE(EXCLUDED.longitude, restaurants.longitude),
                geo_verified = EXCLUDED.geo_verified OR restaurants.geo_verified,
                updated_at = NOW()
            RETURNING id
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                sql,
                (
                    restaurant.id, restaurant.name, restaurant.city,
                    restaurant.district, restaurant.address, restaurant.cuisine_type,
                    restaurant.price_range,
                    json.dumps(restaurant.tags, ensure_ascii=False),
                    restaurant.latitude, restaurant.longitude,
                    restaurant.geo_verified,
                ),
            )
            row = await cur.fetchone()
        return row[0]

    async def update_restaurant_geo(
        self,
        restaurant_id: str,
        address: str,
        city: str,
        district: str = "",
        latitude: float = 0,
        longitude: float = 0,
        geo_verified: bool = False,
    ) -> None:
        """更新餐厅的地理信息"""
        sql = """
            UPDATE restaurants
            SET address = %s, city = %s, district = %s,
                latitude = %s, longitude = %s, geo_verified = %s, updated_at = NOW()
            WHERE id = %s
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                sql, (address, city, district, latitude, longitude, geo_verified, restaurant_id),
            )

    async def find_restaurant_by_name(self, name: str, city: str = "") -> dict | None:
        """按名称查找餐厅（优先精确匹配消歧，后降级模糊匹配）"""
        clean_name = name.strip()
        async with self._conn.cursor(row_factory=dict_row) as cur:
            # 1. 尝试同城精确匹配
            if city and city != "未知":
                await cur.execute(
                    "SELECT * FROM restaurants WHERE name = %s AND city = %s LIMIT 1",
                    (clean_name, city),
                )
                row = await cur.fetchone()
                if row:
                    return row

            # 2. 尝试全局精确匹配
            await cur.execute(
                "SELECT * FROM restaurants WHERE name = %s LIMIT 1",
                (clean_name,),
            )
            row = await cur.fetchone()
            if row:
                return row

            # 3. 降级为同城模糊匹配
            if city and city != "未知":
                await cur.execute(
                    "SELECT * FROM restaurants WHERE name ILIKE %s AND city = %s LIMIT 1",
                    (f"%{clean_name}%", city),
                )
                row = await cur.fetchone()
                if row:
                    return row

            # 4. 全局模糊匹配
            await cur.execute(
                "SELECT * FROM restaurants WHERE name ILIKE %s LIMIT 1",
                (f"%{clean_name}%",),
            )
            return await cur.fetchone()

    async def list_restaurants(self, city: str = "", limit: int = 50) -> list[dict]:
        """列出餐厅"""
        async with self._conn.cursor(row_factory=dict_row) as cur:
            if city:
                await cur.execute(
                    "SELECT * FROM restaurants WHERE city = %s ORDER BY updated_at DESC LIMIT %s",
                    (city, limit),
                )
            else:
                await cur.execute(
                    "SELECT * FROM restaurants ORDER BY updated_at DESC LIMIT %s",
                    (limit,),
                )
            return await cur.fetchall()

    # =========================================================
    # 菜品 CRUD
    # =========================================================

    async def upsert_dish(self, dish: Dish) -> str:
        """插入或更新菜品（按餐厅ID + 菜名联合唯一去重并聚合情感分）"""
        sql = """
            INSERT INTO dishes (id, name, category, price, restaurant_id, avg_sentiment)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (restaurant_id, name) DO UPDATE SET
                category = CASE WHEN EXCLUDED.category != '' THEN EXCLUDED.category ELSE dishes.category END,
                price = COALESCE(EXCLUDED.price, dishes.price),
                avg_sentiment = ROUND(((dishes.avg_sentiment + EXCLUDED.avg_sentiment) / 2.0)::numeric, 2)
            RETURNING id
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                sql,
                (dish.id, dish.name, dish.category, dish.price,
                 dish.restaurant_id, dish.avg_sentiment),
            )
            row = await cur.fetchone()
        return row[0]

    async def find_dish_by_name(self, restaurant_id: str, name: str) -> dict | None:
        """查找指定餐厅下的菜品"""
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT * FROM dishes WHERE restaurant_id = %s AND name = %s LIMIT 1",
                (restaurant_id, name.strip()),
            )
            return await cur.fetchone()

    async def find_dishes_by_restaurant(self, restaurant_id: str) -> list[dict]:
        """查找餐厅的所有菜品"""
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT * FROM dishes WHERE restaurant_id = %s ORDER BY name",
                (restaurant_id,),
            )
            return await cur.fetchall()

    # =========================================================
    # UP主 CRUD
    # =========================================================

    async def upsert_up_master(self, up: UPMaster) -> str:
        """插入或更新UP主"""
        sql = """
            INSERT INTO up_masters (id, bilibili_uid, name, follower_count,
                                    style_tags, credibility_score)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s)
            ON CONFLICT (bilibili_uid) DO UPDATE SET
                name = EXCLUDED.name,
                follower_count = EXCLUDED.follower_count,
                style_tags = EXCLUDED.style_tags,
                credibility_score = EXCLUDED.credibility_score
            RETURNING id
        """
        async with self._conn.cursor() as cur:
                await cur.execute(
                    sql,
                    (
                        up.id, up.bilibili_uid, up.name, up.follower_count,
                        json.dumps(up.style_tags, ensure_ascii=False),
                        up.credibility_score,
                    ),
                )
                row = await cur.fetchone()
        return row[0]

    async def find_up_master_by_uid(self, bilibili_uid: str) -> dict | None:
        """按B站UID查找UP主"""
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT * FROM up_masters WHERE bilibili_uid = %s",
                (bilibili_uid,),
            )
            return await cur.fetchone()

    async def find_up_master_by_name(self, name: str) -> dict | None:
        """按 UP主姓名模糊查找"""
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT * FROM up_masters WHERE name ILIKE %s LIMIT 1",
                (f"%{name.strip()}%",),
            )
            return await cur.fetchone()

    # =========================================================
    # 评价 CRUD
    # =========================================================

    async def insert_review(self, review: Review) -> str:
        """插入评价"""
        sql = """
            INSERT INTO reviews (id, up_master_id, dish_id, restaurant_id,
                                 video_bvid, timestamp, raw_text, sentiment,
                                 sentiment_score, aspects)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING id
        """
        async with self._conn.cursor() as cur:
                await cur.execute(
                    sql,
                    (
                        review.id, review.up_master_id, review.dish_id,
                        review.restaurant_id, review.video_bvid, review.timestamp,
                        review.raw_text, review.sentiment.value, review.sentiment_score,
                        review.aspects.model_dump_json(),
                    ),
                )
                row = await cur.fetchone()
        return row[0]

    async def get_reviews_for_restaurant(self, restaurant_id: str) -> list[dict]:
        """获取餐厅的所有评价"""
        sql = """
            SELECT r.*, d.name as dish_name, u.name as up_name
            FROM reviews r
            JOIN dishes d ON r.dish_id = d.id
            JOIN up_masters u ON r.up_master_id = u.id
            WHERE r.restaurant_id = %s
            ORDER BY r.created_at DESC
        """
        async with self._conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(sql, (restaurant_id,))
                return await cur.fetchall()

    async def get_reviews_for_dish(self, dish_id: str) -> list[dict]:
        """获取菜品的所有评价"""
        sql = """
            SELECT r.*, u.name as up_name
            FROM reviews r
            JOIN up_masters u ON r.up_master_id = u.id
            WHERE r.dish_id = %s
            ORDER BY r.created_at DESC
        """
        async with self._conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(sql, (dish_id,))
                return await cur.fetchall()

    async def get_reviews_by_up_master(self, up_master_id: str) -> list[dict]:
        """获取指定 UP 主的所有评价详情（联表查询餐厅与菜品信息）"""
        sql = """
            SELECT r.*, d.name as dish_name, d.category as dish_category,
                   rest.name as restaurant_name, rest.city as restaurant_city,
                   rest.cuisine_type as restaurant_cuisine
            FROM reviews r
            JOIN dishes d ON r.dish_id = d.id
            JOIN restaurants rest ON r.restaurant_id = rest.id
            WHERE r.up_master_id = %s
            ORDER BY r.created_at DESC
        """
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, (up_master_id,))
            return await cur.fetchall()

    # =========================================================
    # Pipeline 任务状态机 CRUD
    # =========================================================

    async def upsert_pipeline_task(self, task: PipelineTask) -> None:
        """插入或更新 Pipeline 任务状态"""
        sql = """
            INSERT INTO pipeline_tasks (
                bvid, up_mid, title, status, stage, retry_count,
                error_message, transcript_source, restaurant_count, dish_count, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (bvid) DO UPDATE SET
                status = EXCLUDED.status,
                stage = EXCLUDED.stage,
                retry_count = EXCLUDED.retry_count,
                error_message = EXCLUDED.error_message,
                transcript_source = CASE 
                    WHEN EXCLUDED.transcript_source != '' THEN EXCLUDED.transcript_source 
                    ELSE pipeline_tasks.transcript_source 
                END,
                restaurant_count = EXCLUDED.restaurant_count,
                dish_count = EXCLUDED.dish_count,
                updated_at = NOW()
        """
        status_val = task.status.value if isinstance(task.status, TaskStatus) else str(task.status)
        async with self._conn.cursor() as cur:
            await cur.execute(
                sql,
                (
                    task.bvid,
                    task.up_mid,
                    task.title,
                    status_val,
                    task.stage,
                    task.retry_count,
                    task.error_message,
                    task.transcript_source,
                    task.restaurant_count,
                    task.dish_count,
                ),
            )

    async def get_pipeline_task(self, bvid: str) -> dict | None:
        """按 BVID 查询任务记录"""
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT * FROM pipeline_tasks WHERE bvid = %s",
                (bvid,),
            )
            return await cur.fetchone()

    async def get_completed_bvids(self, up_mid: int | None = None) -> set[str]:
        """获取已成功完成（STORED）的视频 BVID 集合，供断点续传快速筛选"""
        sql = "SELECT bvid FROM pipeline_tasks WHERE status IN ('STORED', 'done')"
        params: list[Any] = []
        if up_mid is not None and up_mid > 0:
            sql += " AND up_mid = %s"
            params.append(up_mid)
        async with self._conn.cursor() as cur:
            await cur.execute(sql, tuple(params))
            rows = await cur.fetchall()
            return {r[0] for r in rows}

    async def list_pipeline_tasks(
        self, up_mid: int | None = None, status: str | None = None, limit: int = 100
    ) -> list[dict]:
        """查询任务列表，支持按 UP主 MID 或状态筛选"""
        sql = "SELECT * FROM pipeline_tasks WHERE 1=1"
        params: list[Any] = []
        if up_mid is not None and up_mid > 0:
            sql += " AND up_mid = %s"
            params.append(up_mid)
        if status:
            status_val = status.value if isinstance(status, TaskStatus) else str(status)
            sql += " AND status = %s"
            params.append(status_val)
        sql += " ORDER BY updated_at DESC LIMIT %s"
        params.append(limit)

        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, tuple(params))
            return await cur.fetchall()
