"""
MCP Server 入口

提供五个核心 Tool:
  1. search_dish_by_semantic_review — 语义搜索菜品
  2. get_restaurant_detailed_review — 餐厅详细评价
  3. compare_restaurants — 餐厅横向多维对比
  4. get_up_taste_profile — UP主探店与口味画像
  5. generate_food_tour_itinerary — 地理感知的行程规划
"""

from __future__ import annotations

import asyncio
import json
import os

from loguru import logger
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from config.settings import settings
from src.extractor.llm_client import LLMClient
from src.extractor.prompts import PromptBuilder
from src.storage.pg_store import PostgresStore
from src.storage.neo4j_store import Neo4jStore
from src.storage.vector_store import VectorStore

# 初始化 MCP Server
app = Server("bilibili-food-mcp")

# 全局服务实例（在 startup 中初始化）
pg = PostgresStore()
neo4j_store = Neo4jStore()
vector = VectorStore()
llm = LLMClient()


# ============================================================
# Tool 注册
# ============================================================


@app.list_tools()
async def list_tools() -> list[Tool]:
    """列出所有可用 Tool"""
    return [
        Tool(
            name="search_dish_by_semantic_review",
            description="根据自然语言描述搜索符合条件的菜品及其UP主评价。例如：'红烧肉要肥而不腻'、'锅气足的炒菜'",
            inputSchema={
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "目标城市"},
                    "query": {"type": "string", "description": "自然语言描述"},
                    "sentiment_filter": {
                        "type": "string",
                        "enum": ["all", "recommended", "average", "avoid"],
                        "description": "评价倾向筛选",
                        "default": "all",
                    },
                    "top_k": {"type": "integer", "default": 10, "description": "返回数量"},
                },
                "required": ["city", "query"],
            },
        ),
        Tool(
            name="get_restaurant_detailed_review",
            description="获取指定餐厅的所有UP主评价汇总，含菜品级别的好评/差评统计与知识图谱节点",
            inputSchema={
                "type": "object",
                "properties": {
                    "restaurant_name": {"type": "string", "description": "餐厅名称"},
                    "city": {"type": "string", "description": "所在城市（用于消歧义）", "default": ""},
                },
                "required": ["restaurant_name"],
            },
        ),
        Tool(
            name="compare_restaurants",
            description="横向对比两家餐厅的多UP主探店评价、好评率与踩雷率、招牌必吃菜及核心特色差异",
            inputSchema={
                "type": "object",
                "properties": {
                    "restaurant_a": {"type": "string", "description": "第一家餐厅名称"},
                    "restaurant_b": {"type": "string", "description": "第二家餐厅名称"},
                    "city": {"type": "string", "description": "所在城市（用于消歧义）", "default": ""},
                },
                "required": ["restaurant_a", "restaurant_b"],
            },
        ),
        Tool(
            name="get_up_taste_profile",
            description="获取指定美食UP主的探店与口味画像（探店城市偏好、常探菜系、踩雷排雷严苛度、最推崇招牌菜与踩雷名录）",
            inputSchema={
                "type": "object",
                "properties": {
                    "up_name": {"type": "string", "description": "B站美食UP主名称（如：特厨隋卞、盗月社食遇记）"},
                },
                "required": ["up_name"],
            },
        ),
        Tool(
            name="generate_food_tour_itinerary",
            description="结合UP主评价与高德真实POI经纬度坐标，生成路线紧凑、避免绕路的美食行程规划",
            inputSchema={
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "目标城市"},
                    "days": {"type": "integer", "default": 1, "description": "行程天数"},
                    "preferences": {"type": "string", "description": "偏好描述"},
                    "budget": {
                        "type": "string",
                        "enum": ["budget", "moderate", "premium"],
                        "default": "moderate",
                    },
                },
                "required": ["city"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Tool 调用分发"""
    try:
        if name == "search_dish_by_semantic_review":
            result = await _search_dish(arguments)
        elif name == "get_restaurant_detailed_review":
            result = await _get_restaurant_review(arguments)
        elif name == "compare_restaurants":
            result = await _compare_restaurants(arguments)
        elif name == "get_up_taste_profile":
            result = await _get_up_taste_profile(arguments)
        elif name == "generate_food_tour_itinerary":
            result = await _generate_itinerary(arguments)
        else:
            result = {"error": f"未知工具: {name}"}
    except Exception as e:
        logger.error(f"Tool '{name}' 执行失败: {e}")
        result = {"error": str(e)}

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]


# ============================================================
# Tool 实现
# ============================================================


async def _search_dish(args: dict) -> dict:
    """语义搜索菜品"""
    city = args["city"]
    query = args["query"]
    sentiment_filter = args.get("sentiment_filter", "all")
    top_k = args.get("top_k", 10)

    # 获取查询向量
    embedding = await llm.get_embedding(query)

    # 向量检索
    hits = vector.search(
        query_embedding=embedding,
        city=city,
        sentiment_filter=sentiment_filter,
        top_k=top_k,
    )

    results = []
    for hit in hits:
        results.append({
            "dish_name": hit["dish_name"],
            "restaurant_name": hit["restaurant_name"],
            "city": hit["city"],
            "sentiment": hit["sentiment"],
            "review_text": hit["text"],
            "relevance_score": round(hit["score"], 4),
        })

    return {
        "query": query,
        "city": city,
        "result_count": len(results),
        "results": results,
    }


async def _get_restaurant_review(args: dict) -> dict:
    """获取餐厅详细评价"""
    name = args["restaurant_name"]
    city = args.get("city", "")

    # 从PG查找餐厅
    rest = await pg.find_restaurant_by_name(name, city)
    if not rest:
        return {"error": f"未找到餐厅: {name}", "suggestion": "请检查餐厅名称或尝试模糊搜索"}

    # 从Neo4j获取评价图谱
    graph = await neo4j_store.get_restaurant_graph(rest["id"])

    # 从PG获取详细评价
    reviews = await pg.get_reviews_for_restaurant(rest["id"])

    # 统计
    up_names = list(set(r["up_name"] for r in reviews))

    return {
        "restaurant": rest["name"],
        "city": rest["city"],
        "cuisine": rest["cuisine_type"],
        "review_count": len(reviews),
        "up_masters_visited": up_names,
        "dish_reviews": graph.get("dishes", []),
    }


async def _compare_restaurants(args: dict) -> dict:
    """横向对比两家餐厅"""
    name_a = args["restaurant_a"].strip()
    name_b = args["restaurant_b"].strip()
    city = args.get("city", "").strip()

    rest_a = await pg.find_restaurant_by_name(name_a, city)
    rest_b = await pg.find_restaurant_by_name(name_b, city)

    if not rest_a and not rest_b:
        return {"error": f"两家餐厅均未在知识库中找到: '{name_a}', '{name_b}'"}
    if not rest_a:
        return {"error": f"未在知识库中找到餐厅A数据: '{name_a}'"}
    if not rest_b:
        return {"error": f"未在知识库中找到餐厅B数据: '{name_b}'"}

    stats_a = await _analyze_restaurant(rest_a)
    stats_b = await _analyze_restaurant(rest_b)

    better_rec = (
        name_a if stats_a["recommend_rate"] > stats_b["recommend_rate"]
        else (name_b if stats_b["recommend_rate"] > stats_a["recommend_rate"] else "持平")
    )
    lower_avoid = (
        name_a if stats_a["avoid_rate"] < stats_b["avoid_rate"]
        else (name_b if stats_b["avoid_rate"] < stats_a["avoid_rate"] else "持平")
    )

    return {
        "comparison_summary": {
            "restaurant_a": name_a,
            "restaurant_b": name_b,
            "city": city or rest_a["city"],
            "higher_recommendation": better_rec,
            "safer_choice_lower_avoid": lower_avoid,
        },
        "restaurant_a": stats_a,
        "restaurant_b": stats_b,
    }


async def _analyze_restaurant(rest: dict) -> dict:
    """辅助方法：分析单家餐厅的综合数据画像"""
    rid = rest["id"]
    reviews = await pg.get_reviews_for_restaurant(rid)
    dishes = await pg.find_dishes_by_restaurant(rid)
    up_names = list({r["up_name"] for r in reviews if r.get("up_name")})

    rec_count = sum(1 for r in reviews if r["sentiment"] == "推荐")
    avg_count = sum(1 for r in reviews if r["sentiment"] == "一般")
    avoid_count = sum(1 for r in reviews if r["sentiment"] == "踩雷")
    total = len(reviews)

    rec_rate = round(rec_count / total * 100, 1) if total > 0 else 0.0
    avoid_rate = round(avoid_count / total * 100, 1) if total > 0 else 0.0

    recommended_dishes = [
        {"name": d["name"], "price": d.get("price"), "avg_sentiment": d.get("avg_sentiment", 0.0)}
        for d in dishes if (d.get("avg_sentiment") or 0.0) >= 0.2
    ]
    avoid_dishes = [
        {"name": d["name"], "price": d.get("price"), "avg_sentiment": d.get("avg_sentiment", 0.0)}
        for d in dishes if (d.get("avg_sentiment") or 0.0) < -0.2
    ]

    return {
        "id": rid,
        "name": rest["name"],
        "city": rest["city"],
        "district": rest.get("district", ""),
        "address": rest.get("address", ""),
        "cuisine_type": rest.get("cuisine_type", "其他"),
        "price_range": rest.get("price_range", ""),
        "geo_verified": rest.get("geo_verified", False),
        "total_reviews": total,
        "up_masters_visited": up_names,
        "sentiment_stats": {
            "recommended": rec_count,
            "average": avg_count,
            "avoid": avoid_count,
        },
        "recommend_rate": rec_rate,
        "avoid_rate": avoid_rate,
        "recommended_dishes": recommended_dishes,
        "avoid_dishes": avoid_dishes,
    }


async def _get_up_taste_profile(args: dict) -> dict:
    """获取 UP主口味画像"""
    up_name = args["up_name"].strip()
    up = await pg.find_up_master_by_name(up_name)
    if not up:
        return {"error": f"未找到 UP 主: '{up_name}'", "suggestion": "请确认UP主名称是否准确"}

    reviews = await pg.get_reviews_by_up_master(up["id"])
    if not reviews:
        return {
            "up_name": up["name"],
            "bilibili_uid": up["bilibili_uid"],
            "follower_count": up.get("follower_count", 0),
            "credibility_score": up.get("credibility_score", 0.5),
            "message": "该UP主暂无已入库的探店评价数据",
        }

    visited_restaurants = {r["restaurant_name"] for r in reviews if r.get("restaurant_name")}
    visited_cities = {r["restaurant_city"] for r in reviews if r.get("restaurant_city")}

    cuisine_counts: dict[str, int] = {}
    for r in reviews:
        c = r.get("restaurant_cuisine") or "其他"
        cuisine_counts[c] = cuisine_counts.get(c, 0) + 1
    total_rev = len(reviews)
    cuisine_pref = [
        {"cuisine": c, "count": cnt, "percentage": f"{cnt / total_rev * 100:.1f}%"}
        for c, cnt in sorted(cuisine_counts.items(), key=lambda x: x[1], reverse=True)
    ]

    rec_count = sum(1 for r in reviews if r["sentiment"] == "推荐")
    avg_count = sum(1 for r in reviews if r["sentiment"] == "一般")
    avoid_count = sum(1 for r in reviews if r["sentiment"] == "踩雷")
    avoid_rate = round(avoid_count / total_rev * 100, 1)

    if avoid_rate >= 30.0:
        harshness = "极高（毒舌/真实/排雷专家）"
    elif avoid_rate >= 15.0:
        harshness = "中等偏高（客观中肯，敢于踩雷）"
    elif avoid_rate >= 5.0:
        harshness = "温和（以鼓励为主，偶尔踩雷）"
    else:
        harshness = "极度温和/以推荐为主（罕见踩雷）"

    top_recommended = [
        {
            "dish": r["dish_name"],
            "restaurant": r["restaurant_name"],
            "city": r["restaurant_city"],
            "quote": r["raw_text"],
        }
        for r in reviews if r["sentiment"] == "推荐"
    ][:8]

    avoided_dishes = [
        {
            "dish": r["dish_name"],
            "restaurant": r["restaurant_name"],
            "city": r["restaurant_city"],
            "quote": r["raw_text"],
        }
        for r in reviews if r["sentiment"] == "踩雷"
    ][:8]

    graph_extra = {}
    try:
        graph_data = await neo4j_store.get_up_master_graph(up["id"])
        graph_extra["graph_evaluations_count"] = len(graph_data.get("evaluations", []))
    except Exception:
        pass

    return {
        "up_master": {
            "name": up["name"],
            "bilibili_uid": up["bilibili_uid"],
            "credibility_score": up.get("credibility_score", 0.5),
            "style_tags": up.get("style_tags", []),
        },
        "overview": {
            "total_reviews": total_rev,
            "total_restaurants_visited": len(visited_restaurants),
            "visited_cities": list(visited_cities),
        },
        "taste_profile": {
            "cuisine_preferences": cuisine_pref,
            "harshness_level": harshness,
            "sentiment_distribution": {
                "recommended": rec_count,
                "average": avg_count,
                "avoid": avoid_count,
                "avoid_rate": f"{avoid_rate}%",
            },
        },
        "hall_of_fame": {
            "top_recommended_dishes": top_recommended,
            "avoided_dishes": avoided_dishes,
        },
        **graph_extra,
    }


async def _generate_itinerary(args: dict) -> dict:
    """生成美食行程（融合高德真实经纬度与地理就近原则）"""
    city = args["city"]
    days = args.get("days", 1)
    preferences = args.get("preferences", "")
    budget = args.get("budget", "moderate")

    # 获取城市餐厅数据
    restaurants = await pg.list_restaurants(city=city, limit=30)

    if not restaurants:
        return {"error": f"暂无 {city} 的餐厅数据"}

    # 构建带精确地理位置与推荐菜的餐厅数据摘要
    rest_summaries = []
    for r in restaurants[:25]:
        reviews = await pg.get_reviews_for_restaurant(r["id"])
        dishes = await pg.find_dishes_by_restaurant(r["id"])

        geo_info = ""
        if r.get("district"):
            geo_info += f"[{r['district']}]"
        if r.get("latitude") and r.get("longitude"):
            geo_info += f"(坐标:{r['latitude']:.4f},{r['longitude']:.4f})"
        if r.get("geo_verified"):
            geo_info += "[高德已核验]"

        rec_dishes = [d["name"] for d in dishes if (d.get("avg_sentiment") or 0.0) >= 0.2][:4]
        rec_dishes_str = f"，推荐菜: {', '.join(rec_dishes)}" if rec_dishes else ""

        summary = f"【{r['name']}】{geo_info} 菜系: {r['cuisine_type']}，人均: {r['price_range'] or '未知'}"
        if reviews:
            rec_cnt = sum(1 for rev in reviews if rev["sentiment"] == "推荐")
            summary += f"，UP主好评率: {rec_cnt}/{len(reviews)}"
        summary += rec_dishes_str
        rest_summaries.append(summary)

    restaurant_data = "\n".join(rest_summaries)

    # 使用LLM生成行程
    sys_prompt, user_prompt = PromptBuilder.build_itinerary_prompt(
        city=city,
        restaurant_data=restaurant_data,
        preferences=preferences,
        days=days,
        budget=budget,
    )

    response = await llm.chat(
        system_prompt=sys_prompt,
        user_prompt=user_prompt,
        temperature=0.7,
        response_format={"type": "json_object"},
    )

    try:
        return json.loads(response)
    except json.JSONDecodeError:
        return {"itinerary_text": response}


# ============================================================
# 启动入口
# ============================================================


async def startup() -> None:
    """初始化存储连接"""
    strict = os.getenv("MCP_STRICT_STORAGE", "false").lower() in ("true", "1", "yes")
    try:
        await pg.connect()
        await neo4j_store.connect()
        vector.connect()
        vector.init_collection()
        logger.info("MCP Server 存储后端初始化完成")
    except Exception as e:
        if strict:
            logger.error(f"MCP Server 存储后端初始化失败 (STRICT 模式终止): {e}")
            raise RuntimeError(f"存储后端连接失败: {e}") from e
        logger.warning(f"部分存储后端初始化失败 (可降级运行): {e}")


async def main() -> None:
    """MCP Server 主函数"""
    logger.info("启动 Bilibili Food MCP Server...")
    await startup()

    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
