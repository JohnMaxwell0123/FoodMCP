"""
MCP Server 与高级工具单元测试

测试中的餐厅与 UP 主均为虚构。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.mcp_server.server import (
    _compare_restaurants,
    _generate_itinerary,
    _get_restaurant_review,
    _get_up_taste_profile,
    _search_dish,
    call_tool,
    list_tools,
)


def _review(
    dish: str,
    up: str,
    verdict: str,
    quote: str = "",
    *,
    rid: str | None = None,
    bvid: str = "BV1example",
    seconds: float | None = 12.0,
    verified: bool = True,
    created: str = "2025-05-02 10:00:00",
) -> dict:
    """构造一行 reviews 联表结果（get_reviews_for_restaurant 的返回格式）"""
    return {
        "id": rid or f"rv-{up}-{dish}",
        "dish_id": f"d-{dish}",
        "dish_name": dish,
        "up_master_id": f"u-{up}",
        "up_name": up,
        "sentiment": verdict,
        "raw_text": quote or f"{dish}{verdict}",
        "video_bvid": bvid,
        "timestamp_seconds": seconds,
        "quote_verified": verified,
        "video_published_at": "2025-05-01",
        "created_at": created,
    }


@pytest.mark.asyncio
async def test_list_tools_contains_all_five_tools() -> None:
    """测试 list_tools 正确注册 5 个核心工具，并在描述里写明引用规范"""
    tools = await list_tools()
    tool_names = [t.name for t in tools]

    assert "search_dish_by_semantic_review" in tool_names
    assert "get_restaurant_detailed_review" in tool_names
    assert "compare_restaurants" in tool_names
    assert "get_up_taste_profile" in tool_names
    assert "generate_food_tour_itinerary" in tool_names
    assert len(tools) == 5

    search_tool = next(t for t in tools if t.name == "search_dish_by_semantic_review")
    assert "quote_verified" in search_tool.description


@pytest.mark.asyncio
async def test_search_attaches_source_and_drops_duplicate_quotes() -> None:
    """检索结果按 review_id 回查出处；重跑留下的重复向量只保留一条"""
    hits = [
        {"id": "v1", "score": 0.91, "review_id": "rv-1", "dish_name": "红烧肉",
         "restaurant_name": "示例本帮菜馆", "city": "上海", "sentiment": "推荐", "text": "红烧肉: 肥而不腻"},
        {"id": "v2", "score": 0.90, "review_id": "rv-1-dup", "dish_name": "红烧肉",
         "restaurant_name": "示例本帮菜馆", "city": "上海", "sentiment": "推荐", "text": "红烧肉: 肥而不腻"},
        {"id": "v3", "score": 0.70, "review_id": "rv-missing", "dish_name": "腌笃鲜",
         "restaurant_name": "示例本帮菜馆", "city": "上海", "sentiment": "踩雷", "text": "腌笃鲜: 笋子太老"},
    ]
    source = {
        "raw_text": "肥而不腻", "video_bvid": "BV1example", "timestamp_seconds": 125.4,
        "quote_verified": True, "video_published_at": "2025-05-01", "up_name": "老饕甲",
    }
    rows = [{"id": "rv-1", **source}, {"id": "rv-1-dup", **source}]

    with patch("src.mcp_server.server.llm.get_embedding", new_callable=AsyncMock, return_value=[0.0]), \
         patch("src.mcp_server.server.vector.search", MagicMock(return_value=hits)) as mock_search, \
         patch("src.mcp_server.server.pg.get_reviews_by_ids", new_callable=AsyncMock, return_value=rows):
        result = await _search_dish({"city": "上海市", "query": "肥而不腻的红烧肉", "top_k": 5})

    # 城市写法统一；多取一倍用于去重
    assert mock_search.call_args.kwargs["city"] == "上海"
    assert mock_search.call_args.kwargs["top_k"] == 10

    assert result["result_count"] == 2
    first = result["results"][0]
    assert first["up_name"] == "老饕甲"
    assert first["video_url"] == "https://www.bilibili.com/video/BV1example?t=125"
    assert first["timestamp"] == "02:05"
    assert first["quote_verified"] is True
    assert result["results"][1]["source"] == "出处回查失败"


@pytest.mark.asyncio
async def test_restaurant_review_reports_distribution_not_average() -> None:
    """餐厅详情按 UP 主计票：分歧标为争议，重复评价只算一票，不输出平均分"""
    rest = {"id": "r1", "name": "示例私房菜", "city": "北京", "cuisine_type": "京菜"}
    reviews = [
        _review("宝塔肉", "老饕甲", "推荐"),
        _review("宝塔肉", "老饕乙", "踩雷"),
        _review("锅贴鱼片", "老饕甲", "推荐"),
        _review("锅贴鱼片", "老饕甲", "推荐", rid="rv-retry-duplicate"),
        _review("梅子番茄", "老饕甲", "一般"),
        _review("梅子番茄", "老饕乙", "一般"),
    ]

    with patch("src.mcp_server.server.pg.find_restaurant_by_name", new_callable=AsyncMock, return_value=rest), \
         patch("src.mcp_server.server.pg.get_reviews_for_restaurant", new_callable=AsyncMock, return_value=reviews):
        result = await _get_restaurant_review({"restaurant_name": "示例私房菜"})

    dishes = {d["dish"]: d for d in result["dishes"]}
    assert dishes["宝塔肉"]["evidence_level"] == "争议"
    assert dishes["宝塔肉"]["verdict_counts"] == {"推荐": 1, "一般": 0, "踩雷": 1}
    assert dishes["锅贴鱼片"]["evidence_level"] == "孤证"
    assert dishes["锅贴鱼片"]["verdict_counts"]["推荐"] == 1
    assert dishes["梅子番茄"]["evidence_level"] == "共识"
    assert result["evidence_levels"] == {"孤证": 1, "共识": 1, "争议": 1}
    assert result["up_masters_visited"] == ["老饕乙", "老饕甲"]
    assert "avg_sentiment" not in json.dumps(result, ensure_ascii=False)
    assert dishes["宝塔肉"]["evidence"][0]["video_url"] == "https://www.bilibili.com/video/BV1example?t=12"


@pytest.mark.asyncio
async def test_compare_restaurants_prefers_shared_reviewers() -> None:
    """两家都被同一位 UP 主评价过时，只用这位 UP 主的判定做比较"""
    rest_a = {"id": "rest-a", "name": "示例涮肉馆(东店)", "city": "北京", "district": "西城区",
              "cuisine_type": "清真涮肉", "price_range": "", "geo_verified": True}
    rest_b = {"id": "rest-b", "name": "示例铜锅涮肉(西店)", "city": "北京", "district": "东城区",
              "cuisine_type": "铜锅涮肉", "price_range": "", "geo_verified": True}

    reviews_a = [
        _review("手切羊肉", "老饕甲", "推荐"),
        _review("芝麻烧饼", "老饕甲", "推荐"),
        _review("糖蒜", "老饕甲", "一般"),
        _review("炸酱面", "老饕乙", "踩雷", verified=True),
        _review("卤煮", "老饕乙", "踩雷", verified=False),
    ]
    reviews_b = [
        _review("鲜羊上脑", "老饕甲", "推荐"),
        _review("麻酱小料", "老饕甲", "一般"),
        _review("冻豆腐", "老饕甲", "一般"),
        _review("羊尾油", "探店小王", "推荐"),
        _review("毛肚", "探店小王", "推荐"),
        _review("白菜", "探店小王", "推荐"),
    ]

    with patch("src.mcp_server.server.pg.find_restaurant_by_name", new_callable=AsyncMock,
               side_effect=[rest_a, rest_b]), \
         patch("src.mcp_server.server.pg.get_reviews_for_restaurant", new_callable=AsyncMock,
               side_effect=[reviews_a, reviews_b]):
        result = await _compare_restaurants({
            "restaurant_a": "示例涮肉馆(东店)",
            "restaurant_b": "示例铜锅涮肉(西店)",
            "city": "北京",
        })

    summary = result["comparison_summary"]
    assert "共同评价者：老饕甲" in summary["basis"]
    # 只看老饕甲：A 推荐率 66.7% 高于 B 的 33.3%（若混合全部 UP 主，结论会反过来）
    assert summary["higher_recommendation"] == "示例涮肉馆(东店)"
    assert summary["safer_choice_lower_avoid"] == "持平"

    stat_a = result["restaurant_a"]
    assert stat_a["dish_verdicts"] == 5
    assert [d["dish"] for d in stat_a["avoid_dishes"]] == ["炸酱面"]
    # 踩雷原话未核验：不进黑榜，只作为原话提及
    assert [m["dish"] for m in stat_a["unverified_negative_mentions"]] == ["卤煮"]


@pytest.mark.asyncio
async def test_compare_restaurants_withholds_verdict_on_small_samples() -> None:
    """1 条好评不能赢过 9/10 的好评率：样本不足时不给结论"""
    rest_a = {"id": "rest-a", "name": "示例小馆", "city": "北京"}
    rest_b = {"id": "rest-b", "name": "示例老店", "city": "北京"}
    reviews_a = [_review("招牌面", "老饕甲", "推荐")]
    reviews_b = [_review(f"菜{i}", f"UP{i}", "推荐") for i in range(9)] + [_review("菜9", "UP9", "一般")]

    with patch("src.mcp_server.server.pg.find_restaurant_by_name", new_callable=AsyncMock,
               side_effect=[rest_a, rest_b]), \
         patch("src.mcp_server.server.pg.get_reviews_for_restaurant", new_callable=AsyncMock,
               side_effect=[reviews_a, reviews_b]):
        result = await _compare_restaurants({"restaurant_a": "示例小馆", "restaurant_b": "示例老店"})

    summary = result["comparison_summary"]
    assert summary["higher_recommendation"] is None
    assert summary["safer_choice_lower_avoid"] is None
    assert "样本不足" in summary["note"]
    assert "没有共同评价者" in summary["basis"]


@pytest.mark.asyncio
async def test_compare_restaurants_not_found() -> None:
    """测试餐厅未在知识库时的友好提示"""
    with patch("src.mcp_server.server.pg.find_restaurant_by_name", new_callable=AsyncMock, return_value=None):
        result = await _compare_restaurants({
            "restaurant_a": "不存在的店A",
            "restaurant_b": "不存在的店B",
        })
        assert "error" in result
        assert "不存在的店A" in result["error"]


@pytest.mark.asyncio
async def test_get_up_taste_profile() -> None:
    """UP 主画像：去重、中性的选择性标签、不暴露未计算的可信度"""
    mock_up = {
        "id": "up-001",
        "name": "示例UP主",
        "bilibili_uid": "10001",
        "follower_count": 1000,
        "credibility_score": 0.5,
        "style_tags": [],
    }

    base = {"restaurant_name": "示例淮扬菜馆", "restaurant_city": "淮安", "restaurant_cuisine": "淮扬菜"}
    mock_reviews = [
        {**base, "dish_id": "d1", "dish_name": "软兜长鱼", "sentiment": "推荐", "raw_text": "长鱼极滑嫩",
         "video_bvid": "BV1a", "created_at": "2025-01-01", "quote_verified": True, "timestamp_seconds": 30.0},
        # 管线重跑留下的重复评价
        {**base, "dish_id": "d1", "dish_name": "软兜长鱼", "sentiment": "推荐", "raw_text": "长鱼极滑嫩",
         "video_bvid": "BV1a", "created_at": "2025-01-02", "quote_verified": True, "timestamp_seconds": 30.0},
        {**base, "dish_id": "d2", "dish_name": "平桥豆腐", "sentiment": "推荐", "raw_text": "刀工细腻",
         "video_bvid": "BV1a", "created_at": "2025-01-01", "quote_verified": False, "timestamp_seconds": None},
        {"dish_id": "d3", "dish_name": "麻辣牛蛙", "restaurant_name": "示例川菜馆", "restaurant_city": "北京",
         "restaurant_cuisine": "川菜", "sentiment": "踩雷", "raw_text": "调料包味道明显",
         "video_bvid": "BV1b", "created_at": "2025-02-01", "quote_verified": True, "timestamp_seconds": 75.0},
    ]

    with patch("src.mcp_server.server.pg.find_up_master_by_name", new_callable=AsyncMock, return_value=mock_up), \
         patch("src.mcp_server.server.pg.get_reviews_by_up_master", new_callable=AsyncMock,
               return_value=mock_reviews), \
         patch("src.mcp_server.server.neo4j_store.get_up_master_graph", new_callable=AsyncMock) as mock_graph:

        mock_graph.return_value = {"evaluations": mock_reviews}

        result = await _get_up_taste_profile({"up_name": "示例UP主"})

    assert result["up_master"]["name"] == "示例UP主"
    assert result["up_master"]["credibility"] == "未计算（第②层来源可信仍在设计中）"
    assert "credibility_score" not in result["up_master"]
    assert result["overview"]["total_reviews"] == 3
    assert result["overview"]["visited_cities"] == ["北京", "淮安"]

    cuisines = result["taste_profile"]["cuisine_preferences"]
    assert cuisines[0]["cuisine"] == "淮扬菜"
    assert cuisines[0]["count"] == 2

    # 1/3 踩雷：只描述表达风格，不再出现"真实"之类的价值判断
    assert result["taste_profile"]["selectivity"] == "高（经常给出踩雷）"
    assert "真实" not in json.dumps(result["taste_profile"], ensure_ascii=False)
    assert result["taste_profile"]["sentiment_distribution"]["recommend_rate"] == "66.7%"

    top = result["hall_of_fame"]["top_recommended_dishes"]
    assert [d["dish"] for d in top] == ["软兜长鱼", "平桥豆腐"]  # 已核验的原话排在前面
    avoided = result["hall_of_fame"]["avoided_dishes"]
    assert avoided[0]["dish"] == "麻辣牛蛙"
    assert avoided[0]["video_url"] == "https://www.bilibili.com/video/BV1b?t=75"


@pytest.mark.asyncio
async def test_generate_itinerary_only_uses_evidence() -> None:
    """行程只编排有推荐证据的餐厅，并删掉 LLM 新增的餐厅、菜品与原话"""
    restaurants = [
        {"id": "r1", "name": "示例烤鸭店", "city": "北京", "district": "东城区", "cuisine_type": "京菜",
         "price_range": "", "latitude": 39.9165, "longitude": 116.4025, "geo_verified": True},
        {"id": "r2", "name": "示例快餐店", "city": "北京", "district": "", "cuisine_type": "其他",
         "price_range": "", "latitude": None, "longitude": None, "geo_verified": False},
    ]
    reviews_by_rest = {
        "r1": [
            _review("酥皮烤鸭", "老饕甲", "推荐", "鸭皮酥脆入口即化", seconds=61.0),
            _review("芥末鸭掌", "老饕甲", "踩雷", "芥末味太冲", seconds=95.0),
        ],
        "r2": [_review("炸鸡", "老饕乙", "一般")],
    }

    async def fake_reviews(restaurant_id: str) -> list[dict]:
        return reviews_by_rest[restaurant_id]

    mock_llm_reply = json.dumps({
        "city": "北京",
        "days": 1,
        "total_budget_estimate": "未知",
        "itinerary": [{"day": 1, "stops": [
            {"order": 1, "meal_type": "午餐", "restaurant": "示例烤鸭店",
             "recommended_dishes": ["酥皮烤鸭", "宫保鸡丁"], "avoid_dishes": ["芥末鸭掌"],
             "budget_per_person": "未知", "up_master_quote": "「鸭皮酥脆入口即化」——老饕甲", "tips": ""},
            {"order": 2, "meal_type": "晚餐", "restaurant": "凭空出现的餐厅",
             "recommended_dishes": ["招牌菜"], "avoid_dishes": [], "up_master_quote": "", "tips": ""},
            {"order": 3, "meal_type": "宵夜", "restaurant": "示例烤鸭店",
             "recommended_dishes": [], "avoid_dishes": [],
             "up_master_quote": "这是全北京最好吃的烤鸭", "tips": ""},
        ]}],
    }, ensure_ascii=False)

    with patch("src.mcp_server.server.pg.list_restaurants", new_callable=AsyncMock, return_value=restaurants), \
         patch("src.mcp_server.server.pg.get_reviews_for_restaurant", new_callable=AsyncMock,
               side_effect=fake_reviews), \
         patch("src.mcp_server.server.llm.chat", new_callable=AsyncMock) as mock_chat:

        mock_chat.return_value = mock_llm_reply

        result = await _generate_itinerary({
            "city": "北京",
            "days": 1,
            "preferences": "想吃地道北京烤鸭",
        })

    call_kwargs = mock_chat.call_args[1]
    user_prompt = call_kwargs["user_prompt"]
    assert "高德已核验" in user_prompt
    assert "东城区" in user_prompt
    assert "39.9165" in user_prompt
    assert "避雷菜: 芥末鸭掌" in user_prompt
    assert "「鸭皮酥脆入口即化」——老饕甲" in user_prompt
    assert "示例快餐店" not in user_prompt  # 没有推荐证据的餐厅不进入行程
    assert call_kwargs["temperature"] == 0.2

    stops = result["itinerary"][0]["stops"]
    assert [s["restaurant"] for s in stops] == ["示例烤鸭店", "示例烤鸭店"]
    assert stops[0]["recommended_dishes"] == ["酥皮烤鸭"]
    assert stops[0]["avoid_dishes"] == ["芥末鸭掌"]
    assert stops[0]["up_master_quote"] == "「鸭皮酥脆入口即化」——老饕甲"
    assert stops[1]["up_master_quote"] == ""
    assert result["grounding_note"] == "已删除 3 处不在证据数据中的内容"
    assert result["evidence"]["示例烤鸭店"]["avoid"][0]["video_urls"] == [
        "https://www.bilibili.com/video/BV1example?t=95"
    ]


@pytest.mark.asyncio
async def test_generate_itinerary_without_recommendation_evidence() -> None:
    """没有任何餐厅具备推荐证据时直接说明，而不是让 LLM 凑一份行程"""
    restaurants = [{"id": "r2", "name": "示例快餐店", "city": "北京", "cuisine_type": "其他"}]
    with patch("src.mcp_server.server.pg.list_restaurants", new_callable=AsyncMock, return_value=restaurants), \
         patch("src.mcp_server.server.pg.get_reviews_for_restaurant", new_callable=AsyncMock,
               return_value=[_review("炸鸡", "老饕乙", "一般")]), \
         patch("src.mcp_server.server.llm.chat", new_callable=AsyncMock) as mock_chat:
        result = await _generate_itinerary({"city": "北京"})

    assert "暂无有UP主推荐证据的餐厅" in result["error"]
    assert not mock_chat.called


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
        res = await call_tool("get_up_taste_profile", {"up_name": "示例UP主"})
        data = json.loads(res[0].text)
        assert data["status"] == "ok_profile"
