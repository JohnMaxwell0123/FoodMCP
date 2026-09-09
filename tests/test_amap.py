"""
高德地图 POI 置信度与地理消歧模块测试
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.geocode.amap_client import AmapClient, GeoResult


class TestAmapConfidence:
    """高德 POI 匹配置信度算法测试"""

    def test_high_confidence_match(self):
        """完全匹配或分店匹配应判定为高置信度"""
        score = AmapClient.calculate_confidence(
            query_name="四季民福烤鸭店",
            poi_name="四季民福烤鸭店(故宫店)",
            target_city="北京",
            poi_city="北京市",
            poi_type="餐饮服务;中餐厅;北京菜",
        )
        assert score >= 0.85

    def test_cross_city_misalignment_penalty(self):
        """跨城误匹配应受到严厉惩罚 (如山居满陇在杭州，误搜到北京农家院)"""
        score = AmapClient.calculate_confidence(
            query_name="山居满陇",
            poi_name="北京绿岗山居农家院",
            target_city="杭州",
            poi_city="北京市",
            poi_type="餐饮服务;农家院",
        )
        # 相似度低且跨城惩罚，得分必定低于拒绝阈值 0.45
        assert score < 0.35

    def test_weak_name_similarity_rejected(self):
        """字面重合极低的误匹配应低于门禁阈值"""
        score = AmapClient.calculate_confidence(
            query_name="大祥哥海鲜排档",
            poi_name="祥哥烧烤小吃",
            target_city="上海",
            poi_city="上海市",
            poi_type="餐饮服务",
        )
        assert score < 0.70

    def test_city_bonus_and_penalty(self):
        """同城加成与跨城扣分机制生效"""
        score_same_city = AmapClient.calculate_confidence(
            query_name="陈光记烧鹅",
            poi_name="陈光记烧鹅饭店",
            target_city="广州",
            poi_city="广州市",
        )
        score_diff_city = AmapClient.calculate_confidence(
            query_name="陈光记烧鹅",
            poi_name="陈光记烧鹅饭店",
            target_city="广州",
            poi_city="沈阳市",
        )
        assert score_same_city > score_diff_city + 0.4


class TestAmapSearchFlow:
    """测试带有 Mock 的高德多候选与降级流程"""

    @pytest.mark.asyncio
    async def test_search_poi_filters_low_confidence(self):
        """低置信度候选应被拒绝，返回 None"""
        client = AmapClient(api_key="mock_key")

        mock_resp = {
            "status": "1",
            "pois": [
                {
                    "name": "北京绿岗山居农家院",
                    "cityname": "北京市",
                    "type": "餐饮服务",
                    "address": "黄松峪乡",
                    "location": "117.123,40.123",
                }
            ],
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json = MagicMock(return_value=mock_resp)
            mock_get.return_value = mock_response

            # 目标城市是杭州，但返回北京农家院
            res = await client.search_poi(keyword="山居满陇", city="杭州")
            assert res is None

    @pytest.mark.asyncio
    async def test_search_poi_accepts_high_confidence(self):
        """高置信度候选应被采纳并标记 verified"""
        client = AmapClient(api_key="mock_key")

        mock_resp = {
            "status": "1",
            "pois": [
                {
                    "name": "四季民福烤鸭店(故宫店)",
                    "cityname": "北京市",
                    "adname": "东城区",
                    "type": "餐饮服务;北京菜",
                    "address": "南池子大街11号",
                    "location": "116.403,39.915",
                }
            ],
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json = MagicMock(return_value=mock_resp)
            mock_get.return_value = mock_response

            res = await client.search_poi(keyword="四季民福烤鸭店", city="北京")
            assert res is not None
            assert res.name == "四季民福烤鸭店(故宫店)"
            assert res.is_verified is True
            assert res.confidence >= 0.70
