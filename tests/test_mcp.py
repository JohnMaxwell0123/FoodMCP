"""
MCP Server 与高级工具单元测试
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.mcp_server.server import (
    _analyze_restaurant,
    _compare_restaurants,
    _generate_itinerary,
    _get_up_taste_profile,
    call_tool,
    list_tools,
)


@pytest.mark.asyncio
async def test_list_tools_contains_all_five_tools() -> None:
    """测试 list_tools 正确注册 5 个核心工具"""
    tools = await list_tools()
    tool_names = [t.name for t in tools]

    assert "search_dish_by_semantic_review" in tool_names
    assert "get_restaurant_detailed_review" in tool_names
    assert "compare_restaurants" in tool_names
    assert "get_up_taste_profile" in tool_names
    assert "generate_food_tour_itinerary" in tool_names
    assert len(tools) == 5


@pytest.mark.asyncio
async def test_compare_restaurants() -> None:
    """测试 compare_restaurants 餐厅横向多维对比"""
    rest_a = {
        "id": "rest-a-id",
        "name": "聚宝源(牛街店)",
        "city": "北京",
        "district": "西城区",
        "cuisine_type": "清真涮肉",
        "price_range": "100-150元",
        "geo_verified": True,
    }
    rest_b = {
        "id": "rest-b-id",
        "name": "南门涮肉(天坛店)",
        "city": "北京",
        "district": "东城区",
        "cuisine_type": "铜锅涮肉",
        "price_range": "120-180元",
        "geo_verified": True,
    }

    reviews_a = [
        {"sentiment": "推荐", "up_name": "老饕", "raw_text": "手切羊肉极好"},
        {"sentiment": "推荐", "up_name": "大厨", "raw_text": "烧饼一绝"},
        {"sentiment": "一般", "up_name": "探店小王", "raw_text": "排队太长"},
    ]
    reviews_b = [
        {"sentiment": "推荐", "up_name": "老饕", "raw_text": "鲜羊上脑嫩"},
        {"sentiment": "踩雷", "up_name": "探店小王", "raw_text": "麻酱调料偏甜"},
    ]

    dishes_a = [
        {"name": "手切鲜羊肉", "price": 58.0, "avg_sentiment": 0.8},
        {"name": "芝麻烧饼", "price": 3.0, "avg_sentiment": 0.9},
    ]
    dishes_b = [
        {"name": "鲜羊上脑", "price": 62.0, "avg_sentiment": 0.5},
        {"name": "秘制麻酱", "price": 8.0, "avg_sentiment": -0.6},
    ]

    with patch("src.mcp_server.server.pg.find_restaurant_by_name", side_effect=[rest_a, rest_b]), \
         patch("src.mcp_server.server.pg.get_reviews_for_restaurant", side_effect=[reviews_a, reviews_b]), \
         patch("src.mcp_server.server.pg.find_dishes_by_restaurant", side_effect=[dishes_a, dishes_b]):

        result = await _compare_restaurants({
            "restaurant_a": "聚宝源(牛街店)",
            "restaurant_b": "南门涮肉(天坛店)",
            "city": "北京",
        })

        assert "comparison_summary" in result
        summary = result["comparison_summary"]
        assert summary["higher_recommendation"] == "聚宝源(牛街店)"
        assert summary["safer_choice_lower_avoid"] == "聚宝源(牛街店)"

        stat_a = result["restaurant_a"]
        assert stat_a["recommend_rate"] == 66.7
        assert stat_a["avoid_rate"] == 0.0
        assert len(stat_a["recommended_dishes"]) == 2

        stat_b = result["restaurant_b"]
        assert stat_b["recommend_rate"] == 50.0
        assert stat_b["avoid_rate"] == 50.0
        assert len(stat_b["avoid_dishes"]) == 1


@pytest.mark.asyncio
async def test_compare_restaurants_not_found() -> None:
    """测试餐厅未在知识库时的友好提示"""
    with patch("src.mcp_server.server.pg.find_restaurant_by_name", return_value=None):
        result = await _compare_restaurants({
            "restaurant_a": "不存在的店A",
            "restaurant_b": "不存在的店B",
        })
        assert "error" in result
        assert "不存在的店A" in result["error"]


@pytest.mark.asyncio
async def test_get_up_taste_profile() -> None:
    """测试 UP 主口味画像生成"""
    mock_up = {
        "id": "up-001",
        "name": "特厨隋卞",
        "bilibili_uid": "1462401621",
        "follower_count": 2500000,
        "credibility_score": 0.95,
        "style_tags": ["国宴大厨", "专业客观"],
    }

    mock_reviews = [
        {
            "dish_name": "软兜长鱼",
            "restaurant_name": "淮安宾馆",
            "restaurant_city": "淮安",
            "restaurant_cuisine": "淮扬菜",
            "sentiment": "推荐",
            "raw_text": "长鱼极滑嫩，蒜香与胡椒恰到好处",
        },
        {
            "dish_name": "平桥豆腐",
            "restaurant_name": "淮安宾馆",
            "restaurant_city": "淮安",
            "restaurant_cuisine": "淮扬菜",
            "sentiment": "推荐",
            "raw_text": "刀工细腻，鲜而不腻",
        },
        {
            "dish_name": "麻辣牛蛙",
            "restaurant_name": "某网红餐厅",
            "restaurant_city": "北京",
            "restaurant_cuisine": "川菜",
            "sentiment": "踩雷",
            "raw_text": "预制调料包味道明显，毫无锅气",
        },
    ]

    with patch("src.mcp_server.server.pg.find_up_master_by_name", return_value=mock_up), \
         patch("src.mcp_server.server.pg.get_reviews_by_up_master", return_value=mock_reviews), \
         patch("src.mcp_server.server.neo4j_store.get_up_master_graph", new_callable=AsyncMock) as mock_graph:

        mock_graph.return_value = {"evaluations": mock_reviews}

        result = await _get_up_taste_profile({"up_name": "特厨隋卞"})

        assert result["up_master"]["name"] == "特厨隋卞"
        assert result["overview"]["total_reviews"] == 3
        assert "淮安" in result["overview"]["visited_cities"]
        assert "北京" in result["overview"]["visited_cities"]

        # 验证菜系偏好：淮扬菜应排第 1 (2次, 66.7%)
        cuisines = result["taste_profile"]["cuisine_preferences"]
        assert cuisines[0]["cuisine"] == "淮扬菜"
        assert cuisines[0]["count"] == 2

        # 验证严苛度
        assert "避雷专家" in result["taste_profile"]["harshness_level"] or "毒舌" in result["taste_profile"]["harshness_level"]
        assert result["taste_profile"]["sentiment_distribution"]["avoid"] == 1

        # 验证红黑榜
        assert len(result["hall_of_fame"]["top_recommended_dishes"]) == 2
        assert len(result["hall_of_fame"]["avoided_dishes"]) == 1
        assert result["hall_of_fame"]["avoided_dishes"][0]["dish"] == "麻辣牛蛙"


@pytest.mark.asyncio
async def test_generate_itinerary_with_geo_coordinates() -> None:
    """测试行程规划融合高德 POI 经纬度与推荐菜"""
    restaurants = [
        {
            "id": "r1",
            "name": "四季民福烤鸭店",
            "city": "北京",
            "district": "东城区",
            "cuisine_type": "京菜",
            "price_range": "150元",
            "latitude": 39.9165,
            "longitude": 116.4025,
            "geo_verified": True,
        }
    ]

    reviews = [{"sentiment": "推荐", "raw_text": "烤鸭酥脆"}]
    dishes = [{"name": "酥皮烤鸭", "avg_sentiment": 0.9}]

    mock_llm_reply = json.dumps({
        "city": "北京",
        "itinerary": [
            {
                "day": 1,
                "meal_type": "午餐",
                "restaurant": "四季民福烤鸭店",
                "recommended_dishes": ["酥皮烤鸭"],
            }
        ]
    })

    with patch("src.mcp_server.server.pg.list_restaurants", return_value=restaurants), \
         patch("src.mcp_server.server.pg.get_reviews_for_restaurant", return_value=reviews), \
         patch("src.mcp_server.server.pg.find_dishes_by_restaurant", return_value=dishes), \
         patch("src.mcp_server.server.llm.chat", new_callable=AsyncMock) as mock_chat:

        mock_chat.return_value = mock_llm_reply

        result = await _generate_itinerary({
            "city": "北京",
            "days": 1,
            "preferences": "想吃地道北京烤鸭",
        })

        assert result["city"] == "北京"
        assert len(result["itinerary"]) == 1
        assert mock_chat.called
        # 验证地理坐标与已核验标识被传入了 Prompt
        call_kwargs = mock_chat.call_args[1]
        user_prompt = call_kwargs["user_prompt"]
        assert "高德已核验" in user_prompt
        assert "东城区" in user_prompt
        assert "39.9165" in user_prompt


@pytest.mark.asyncio
async def test_call_tool_dispatch() -> None:
    """测试 call_tool 能够正确分发各个工具"""
    with patch("src.mcp_server.server._compare_restaurants", new_callable=AsyncMock) as mock_comp:
        mock_comp.return_value = {"status": "ok_compare"}
        res = await call_tool("compare_restaurants", {"restaurant_a": "A", "restaurant_b": "B"})
        data = json.loads(res[0].text)
        assert data["status"] == "ok_compare"

    with patch("src.mcp_server.server._get_up_taste_profile", new_callable=AsyncMock) as mock_prof:
        mock_prof.return_value = {"status": "ok_profile"}
        res = await call_tool("get_up_taste_profile", {"up_name": "隋卞"})
        data = json.loads(res[0].text)
        assert data["status"] == "ok_profile"
