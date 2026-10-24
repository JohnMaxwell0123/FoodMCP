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
        # 冲突时不再两两平均（结果依赖写入顺序），由 refresh_dish_sentiment 统一重算
        assert "avg_sentiment =" not in executed_sql

    @pytest.mark.asyncio
    async def test_refresh_dish_sentiment_uses_mean_of_all_reviews(self):
        """测试菜品情感分按全部评价求平均，返回最新值"""
        store = PostgresStore()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=[0.27])

        mock_conn = MagicMock()
        mock_cursor_ctx = MagicMock()
        mock_cursor_ctx.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor = MagicMock(return_value=mock_cursor_ctx)

        store._conn = mock_conn

        score = await store.refresh_dish_sentiment("dish-uuid-001")
        assert score == 0.27

        executed_sql, params = mock_cursor.execute.call_args[0]
        assert "AVG(sentiment_score)" in executed_sql
        assert "FROM reviews WHERE dish_id = %s" in executed_sql
        assert params == ("dish-uuid-001", "dish-uuid-001")

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

    @pytest.mark.asyncio
    async def test_upsert_up_master_keeps_offline_fields(self):
        """管线用默认值构造 UPMaster，冲突时只更新名称，不覆盖可信度等离线字段"""
        from src.models.entities import UPMaster

        store = PostgresStore()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=["up-001"])
        mock_conn = MagicMock()
        mock_cursor_ctx = MagicMock()
        mock_cursor_ctx.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor = MagicMock(return_value=mock_cursor_ctx)
        store._conn = mock_conn

        await store.upsert_up_master(UPMaster(bilibili_uid="10001", name="示例UP主"))

        executed_sql, params = mock_cursor.execute.call_args[0]
        assert "name = EXCLUDED.name" in executed_sql
        assert "credibility_score = EXCLUDED" not in executed_sql
        assert "follower_count = EXCLUDED" not in executed_sql
        assert params[-1] is None  # 可信度未计算时写入 NULL，而不是 0.5

    @pytest.mark.asyncio
    async def test_list_restaurants_accepts_city_with_or_without_suffix(self):
        """高德写入的"北京市"与用户输入的"北京"视为同一城市"""
        store = PostgresStore()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        mock_conn = MagicMock()
        mock_cursor_ctx = MagicMock()
        mock_cursor_ctx.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor = MagicMock(return_value=mock_cursor_ctx)
        store._conn = mock_conn

        await store.list_restaurants(city="北京市", limit=30)

        executed_sql, params = mock_cursor.execute.call_args[0]
        assert "city IN (%s, %s)" in executed_sql
        assert params == ("北京", "北京市", 30)

    @pytest.mark.asyncio
    async def test_insert_dining_outcomes_keeps_latest_per_reporter(self):
        """同一匿名反馈者对同一条评价只保留最新一次；匿名为空时照常插入"""
        from src.models.entities import DiningOutcome, Sentiment

        store = PostgresStore()
        mock_cursor = AsyncMock()
        mock_conn = MagicMock()
        mock_cursor_ctx = MagicMock()
        mock_cursor_ctx.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor = MagicMock(return_value=mock_cursor_ctx)
        store._conn = mock_conn

        outcomes = [
            DiningOutcome(report_id="meal-1", review_id="rv-1", diner_verdict=Sentiment.AVOID,
                          reporter_id="anon-1"),
            DiningOutcome(report_id="meal-1", review_id="rv-2", diner_verdict=Sentiment.AVOID),
        ]
        await store.insert_dining_outcomes(outcomes)

        executed_sql, params = mock_cursor.executemany.call_args[0]
        assert "ON CONFLICT (review_id, reporter_id) WHERE reporter_id <> ''" in executed_sql
        assert [p[2] for p in params] == ["rv-1", "rv-2"]
        assert [p[3] for p in params] == ["踩雷", "踩雷"]
        assert [p[5] for p in params] == ["anon-1", ""]
