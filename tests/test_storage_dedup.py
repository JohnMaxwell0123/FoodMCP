"""
存储去重与实体一致性测试
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.models.entities import Dish, Restaurant
from src.storage.pg_store import PostgresStore


class TestEntityAndDeduplication:
    """实体模型与去重逻辑测试"""

    def test_restaurant_geo_verified_default(self):
        """Restaurant 默认 geo_verified 字段应为 False"""
        rest = Restaurant(name="测试餐厅", city="北京")
        assert rest.geo_verified is False

        rest_verified = Restaurant(name="测试餐厅", city="北京", geo_verified=True)
        assert rest_verified.geo_verified is True

    @pytest.mark.asyncio
    async def test_upsert_dish_returns_id_and_updates_sentiment(self):
        """测试 upsert_dish 能够正确执行并返回 ID"""
        store = PostgresStore()
        mock_cursor = AsyncMock()
        # 模拟 RETURNING id 返回数据库原本的 dish_id
        mock_cursor.fetchone = AsyncMock(return_value=["existing-dish-uuid-123"])

        mock_conn = MagicMock()
        mock_cursor_ctx = MagicMock()
        mock_cursor_ctx.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor = MagicMock(return_value=mock_cursor_ctx)

        store._conn = mock_conn

        dish = Dish(
            name="招牌红烧肉",
            restaurant_id="rest-uuid-001",
            price=68.0,
            avg_sentiment=0.8,
        )

        persisted_id = await store.upsert_dish(dish)
        assert persisted_id == "existing-dish-uuid-123"

        # 检查 SQL 中是否包含 ON CONFLICT (restaurant_id, name)
        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "ON CONFLICT (restaurant_id, name)" in executed_sql
        assert "ROUND(((dishes.avg_sentiment + EXCLUDED.avg_sentiment) / 2.0)::numeric, 2)" in executed_sql

    @pytest.mark.asyncio
    async def test_find_restaurant_precision_priority(self):
        """测试餐厅查找优先精确匹配"""
        store = PostgresStore()
        mock_cursor = AsyncMock()
        # 模拟同城精确匹配命中
        mock_cursor.fetchone = AsyncMock(return_value={"id": "rest-001", "name": "全聚德", "city": "北京"})

        mock_conn = MagicMock()
        mock_cursor_ctx = MagicMock()
        mock_cursor_ctx.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor = MagicMock(return_value=mock_cursor_ctx)

        store._conn = mock_conn

        res = await store.find_restaurant_by_name("全聚德", "北京")
        assert res is not None
        assert res["id"] == "rest-001"

        # 校验第一次查询使用了精确相等的 SQL 语句
        first_sql = mock_cursor.execute.call_args_list[0][0][0]
        assert "WHERE name = %s AND city = %s" in first_sql
