"""
MCP Server 入口

提供三个核心 Tool:
  1. search_dish_by_semantic_review — 语义搜索菜品
  2. get_restaurant_detailed_review — 餐厅详细评价
  3. generate_food_tour_itinerary — 美食行程规划
"""

from __future__ import annotations

import asyncio
import json

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
            description="获取指定餐厅的所有UP主评价汇总，含菜品级别的好评/差评统计",
            inputSchema={
                "type": "object",
                "properties": {
                    "restaurant_name": {"type": "string", "description": "餐厅名称"},
                    "city": {"type": "string", "description": "所在城市（用于消歧义）"},
                },
                "required": ["restaurant_name"],
            },
        ),
        Tool(
            name="generate_food_tour_itinerary",
            description="结合UP主评价和地理位置，生成结构化美食行程",
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


async def _generate_itinerary(args: dict) -> dict:
    """生成美食行程"""
    city = args["city"]
    days = args.get("days", 1)
    preferences = args.get("preferences", "")
    budget = args.get("budget", "moderate")

    # 获取城市餐厅数据
    restaurants = await pg.list_restaurants(city=city, limit=30)

    if not restaurants:
        return {"error": f"暂无 {city} 的餐厅数据"}

    # 构建餐厅数据摘要
    rest_summaries = []
    for r in restaurants[:20]:
        reviews = await pg.get_reviews_for_restaurant(r["id"])
        summary = f"【{r['name']}】{r['cuisine_type']}，{r['price_range']}"
        if reviews:
            summary += f"，{len(reviews)}条评价"
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
    try:
        await pg.connect()
        await neo4j_store.connect()
        vector.connect()
        vector.init_collection()
        logger.info("MCP Server 存储后端初始化完成")
    except Exception as e:
        logger.warning(f"部分存储后端初始化失败 (可降级运行): {e}")


async def main() -> None:
    """MCP Server 主函数"""
    logger.info("启动 Bilibili Food MCP Server...")
    await startup()

    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
