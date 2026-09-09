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
from src.models.entities import Dish, Restaurant, Review, UPMaster

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
    created_at TIMESTAMP DEFAULT NOW()
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

-- 索引
CREATE INDEX IF NOT EXISTS idx_restaurants_city ON restaurants(city);
CREATE INDEX IF NOT EXISTS idx_restaurants_name ON restaurants(name);
CREATE INDEX IF NOT EXISTS idx_dishes_restaurant ON dishes(restaurant_id);
CREATE INDEX IF NOT EXISTS idx_reviews_restaurant ON reviews(restaurant_id);
CREATE INDEX IF NOT EXISTS idx_reviews_dish ON reviews(dish_id);
CREATE INDEX IF NOT EXISTS idx_reviews_up_master ON reviews(up_master_id);
CREATE INDEX IF NOT EXISTS idx_reviews_sentiment ON reviews(sentiment);
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
        logger.info("PostgreSQL 数据表初始化完成")

    # =========================================================
    # 餐厅 CRUD
    # =========================================================

    async def upsert_restaurant(self, restaurant: Restaurant) -> str:
        """插入或更新餐厅"""
        sql = """
            INSERT INTO restaurants (id, name, city, district, address, cuisine_type,
                                     price_range, tags, latitude, longitude)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                city = EXCLUDED.city,
                district = EXCLUDED.district,
                address = EXCLUDED.address,
                cuisine_type = EXCLUDED.cuisine_type,
                price_range = EXCLUDED.price_range,
                tags = EXCLUDED.tags,
                latitude = EXCLUDED.latitude,
                longitude = EXCLUDED.longitude,
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
    ) -> None:
        """更新餐厅的地理信息"""
        sql = """
            UPDATE restaurants
            SET address = %s, city = %s, district = %s,
                latitude = %s, longitude = %s, updated_at = NOW()
            WHERE id = %s
        """
        async with self._conn.cursor() as cur:
                await cur.execute(
                    sql, (address, city, district, latitude, longitude, restaurant_id),
                )

    async def find_restaurant_by_name(self, name: str, city: str = "") -> dict | None:
        """按名称查找餐厅"""
        async with self._conn.cursor(row_factory=dict_row) as cur:
                if city:
                    await cur.execute(
                        "SELECT * FROM restaurants WHERE name ILIKE %s AND city = %s LIMIT 1",
                        (f"%{name}%", city),
                    )
                else:
                    await cur.execute(
                        "SELECT * FROM restaurants WHERE name ILIKE %s LIMIT 1",
                        (f"%{name}%",),
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
        """插入或更新菜品"""
        sql = """
            INSERT INTO dishes (id, name, category, price, restaurant_id, avg_sentiment)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                category = EXCLUDED.category,
                price = EXCLUDED.price,
                avg_sentiment = EXCLUDED.avg_sentiment
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
