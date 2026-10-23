"""
MCP Server 入口

提供五个核心 Tool:
  1. search_dish_by_semantic_review — 按口味描述检索菜品，附 UP 主原话证据
  2. get_restaurant_detailed_review — 餐厅的菜品级证据分布（按 UP 主计票）
  3. compare_restaurants — 餐厅横向对比（优先比较共同评价者）
  4. get_up_taste_profile — UP 主的城市足迹、菜系与判定分布
  5. generate_food_tour_itinerary — 只使用证据数据的行程规划

所有返回值都带出处：哪位 UP 主、哪个视频（链接带时间点）、原话是否已在字幕中核验。
FoodMCP 不输出平均分，只输出证据的分布。
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from loguru import logger
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from src.evidence.consensus import VERDICTS, classify_dish, summarize_dishes
from src.evidence.quotes import format_timestamp, normalize, video_url
from src.extractor.llm_client import LLMClient
from src.extractor.prompts import PromptBuilder
from src.geocode.amap_client import normalize_city
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

# 两家餐厅各自至少有这么多条菜品判定，对比工具才给出孰优孰劣的结论
MIN_VERDICTS_FOR_COMPARISON = 3

CREDIBILITY_NOT_COMPUTED = "未计算（第②层来源可信仍在设计中）"

# 写进 Tool 描述的引用规范：在 Agent 形态里，Tool 描述和返回结构就是产品界面
CITATION_RULE = (
    "结果来自B站UP主的探店视频。向用户转述时请注明是哪位UP主、哪个视频"
    "（video_url 带时间点，可直接跳到原话）；quote_verified 为 false 表示原话未能在字幕中找到，"
    "只转述原话，不要据此下结论。"
)


# ============================================================
# Tool 注册
# ============================================================


@app.list_tools()
async def list_tools() -> list[Tool]:
    """列出所有可用 Tool"""
    return [
        Tool(
            name="search_dish_by_semantic_review",
            description=(
                "根据口味、口感等自然语言描述搜索菜品，返回UP主原话作为证据。"
                "例如：'红烧肉要肥而不腻'、'锅气足的炒菜'。"
                "sentiment_filter=avoid 可以只查UP主说别点的菜。" + CITATION_RULE
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "目标城市"},
                    "query": {"type": "string", "description": "自然语言描述"},
                    "sentiment_filter": {
                        "type": "string",
                        "enum": ["all", "recommended", "average", "avoid"],
                        "description": "评价倾向筛选（avoid = 只看UP主说踩雷的菜）",
                        "default": "all",
                    },
                    "top_k": {"type": "integer", "default": 10, "description": "返回数量"},
                },
                "required": ["city", "query"],
            },
        ),
        Tool(
            name="get_restaurant_detailed_review",
            description=(
                "获取一家餐厅被哪些UP主评价过，以及每道菜的证据分布：按UP主计票（每位UP主一票），"
                "并标注证据等级——孤证（只有一位UP主评价过）、共识（多位一致）、争议（多位不一致）。"
                "不提供平均分。" + CITATION_RULE
            ),
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
            description=(
                "横向对比两家餐厅的UP主评价：推荐率与踩雷率、推荐菜、避雷菜、争议菜。"
                "两家都去过的UP主（共同评价者）的判断优先，因为同一个人的标准更可比；"
                f"任何一家用于比较的菜品判定少于 {MIN_VERDICTS_FOR_COMPARISON} 条时"
                "不给出孰优孰劣的结论。"
            ),
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
            description=(
                "获取一位美食UP主的探店画像：城市足迹、常探菜系、判定分布与代表性原话。"
                "selectivity 只描述这位UP主给出踩雷的频率（表达风格），不代表可信度；"
                "可信度尚未计算。"
            ),
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
            description=(
                "结合UP主证据与高德坐标生成美食行程。只编排有UP主推荐证据的餐厅；"
                "推荐菜、避雷菜和UP主原话只取自证据数据，人均等缺失信息写'未知'而不估算。"
            ),
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
# 证据辅助
# ============================================================


def _source_fields(row: dict[str, Any]) -> dict[str, Any]:
    """一条评价的出处：视频链接（带时间点）、发布日期、原话是否已核验"""
    seconds = row.get("timestamp_seconds")
    return {
        "video_url": video_url(row.get("video_bvid", ""), seconds),
        "timestamp": format_timestamp(seconds),
        "published": row.get("video_published_at") or "",
        "quote_verified": bool(row.get("quote_verified")),
    }


def _dish_lists(summaries: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """按 classify_dish 把菜品分到红榜、黑榜、争议与未核验的负面提及"""
    lists: dict[str, list[dict[str, Any]]] = {
        "recommended": [], "avoid": [], "avoid_unverified": [], "disputed": [],
    }
    for summary in summaries:
        label = classify_dish(summary)
        if label in lists:
            lists[label].append(summary)
    return lists


def _brief(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "dish": summary["dish"],
        "verdict_counts": summary["verdict_counts"],
        "evidence_level": summary["evidence_level"],
        "ups": [e["up"] for e in summary["evidence"]],
    }


def _verdict_stats(
    summaries: list[dict[str, Any]], only_ups: set[str] | None = None,
) -> dict[str, Any]:
    """菜品判定计数（每位 UP 主对每道菜一票），可限定只统计部分 UP 主"""
    counts = {v: 0 for v in VERDICTS}
    for summary in summaries:
        for e in summary["evidence"]:
            if only_ups is None or e["up"] in only_ups:
                counts[e["verdict"]] += 1
    total = sum(counts.values())
    return {
        "verdicts": total,
        "counts": counts,
        "recommend_rate": round(counts["推荐"] / total * 100, 1) if total else 0.0,
        "avoid_rate": round(counts["踩雷"] / total * 100, 1) if total else 0.0,
    }


# ============================================================
# Tool 实现
# ============================================================


async def _search_dish(args: dict) -> dict:
    """语义搜索菜品，并按 review_id 回查每条结果的出处"""
    city = normalize_city(args["city"])
    query = args["query"]
    sentiment_filter = args.get("sentiment_filter", "all")
    top_k = args.get("top_k", 10)

    # 获取查询向量
    embedding = await llm.get_embedding(query)

    # 多取一倍：管线重跑可能留下同一句原话的多份向量，去重后再截断
    hits = vector.search(
        query_embedding=embedding,
        city=city,
        sentiment_filter=sentiment_filter,
        top_k=top_k * 2,
    )

    sources: dict[str, dict[str, Any]] = {}
    review_ids = [h["review_id"] for h in hits if h.get("review_id")]
    if review_ids:
        try:
            sources = {row["id"]: row for row in await pg.get_reviews_by_ids(review_ids)}
        except Exception as e:
            logger.warning(f"检索结果回查出处失败: {e}")

    results = []
    seen: set[tuple[str, str, str]] = set()
    for hit in hits:
        row = sources.get(hit.get("review_id"))
        quote = row["raw_text"] if row else hit["text"]
        key = (hit["restaurant_name"], hit["dish_name"], normalize(quote))
        if key in seen:
            continue
        seen.add(key)

        item = {
            "dish_name": hit["dish_name"],
            "restaurant_name": hit["restaurant_name"],
            "city": hit["city"],
            "verdict": hit["sentiment"],
            "quote": quote,
            "relevance_score": round(hit["score"], 4),
            "review_id": hit.get("review_id", ""),
        }
        if row:
            item["up_name"] = row.get("up_name", "")
            item.update(_source_fields(row))
        else:
            item["source"] = "出处回查失败"
        results.append(item)
        if len(results) >= top_k:
            break

    return {
        "query": query,
        "city": city,
        "result_count": len(results),
        "results": results,
    }


async def _get_restaurant_review(args: dict) -> dict:
    """餐厅的菜品级证据分布"""
    name = args["restaurant_name"]
    city = normalize_city(args.get("city", ""))

    # 从PG查找餐厅
    rest = await pg.find_restaurant_by_name(name, city)
    if not rest:
        return {"error": f"未找到餐厅: {name}", "suggestion": "请检查餐厅名称或尝试模糊搜索"}

    reviews = await pg.get_reviews_for_restaurant(rest["id"])
    dishes = summarize_dishes(reviews)

    return {
        "restaurant": rest["name"],
        "city": rest["city"],
        "cuisine": rest["cuisine_type"],
        "up_masters_visited": sorted({r["up_name"] for r in reviews if r.get("up_name")}),
        "dish_count": len(dishes),
        "evidence_levels": {
            level: sum(1 for d in dishes if d["evidence_level"] == level)
            for level in ("孤证", "共识", "争议")
        },
        "dishes": dishes,
    }


async def _analyze_restaurant(rest: dict) -> tuple[dict, list[dict[str, Any]]]:
    """辅助方法：单家餐厅的证据画像，同时返回菜品级证据分布供对比使用"""
    reviews = await pg.get_reviews_for_restaurant(rest["id"])
    summaries = summarize_dishes(reviews)
    stats = _verdict_stats(summaries)
    lists = _dish_lists(summaries)

    profile = {
        "id": rest["id"],
        "name": rest["name"],
        "city": rest["city"],
        "district": rest.get("district", ""),
        "address": rest.get("address", ""),
        "cuisine_type": rest.get("cuisine_type", "其他"),
        "price_range": rest.get("price_range", ""),
        "geo_verified": rest.get("geo_verified", False),
        "up_masters_visited": sorted({e["up"] for s in summaries for e in s["evidence"]}),
        "dish_verdicts": stats["verdicts"],
        "sentiment_stats": {
            "recommended": stats["counts"]["推荐"],
            "average": stats["counts"]["一般"],
            "avoid": stats["counts"]["踩雷"],
        },
        "recommend_rate": stats["recommend_rate"],
        "avoid_rate": stats["avoid_rate"],
        "recommended_dishes": [_brief(s) for s in lists["recommended"]],
        "avoid_dishes": [_brief(s) for s in lists["avoid"]],
        "disputed_dishes": [_brief(s) for s in lists["disputed"]],
        # 有人说踩雷、但原话未能在字幕中核验：只给原话，不进黑榜
        "unverified_negative_mentions": [
            {
                "dish": s["dish"],
                "quotes": [
                    {"up": e["up"], "quote": e["quote"]}
                    for e in s["evidence"] if e["verdict"] == "踩雷"
                ],
            }
            for s in lists["avoid_unverified"]
        ],
    }
    return profile, summaries


def _pick(name_a: str, name_b: str, value_a: float, value_b: float, prefer_higher: bool) -> str:
    if value_a == value_b:
        return "持平"
    a_wins = value_a > value_b if prefer_higher else value_a < value_b
    return name_a if a_wins else name_b


async def _compare_restaurants(args: dict) -> dict:
    """横向对比两家餐厅"""
    name_a = args["restaurant_a"].strip()
    name_b = args["restaurant_b"].strip()
    city = normalize_city(args.get("city", ""))

    rest_a = await pg.find_restaurant_by_name(name_a, city)
    rest_b = await pg.find_restaurant_by_name(name_b, city)

    if not rest_a and not rest_b:
        return {"error": f"两家餐厅均未在知识库中找到: '{name_a}', '{name_b}'"}
    if not rest_a:
        return {"error": f"未在知识库中找到餐厅A数据: '{name_a}'"}
    if not rest_b:
        return {"error": f"未在知识库中找到餐厅B数据: '{name_b}'"}

    profile_a, summaries_a = await _analyze_restaurant(rest_a)
    profile_b, summaries_b = await _analyze_restaurant(rest_b)

    # 两家都去过的 UP 主用同一把尺子打分，只比较他们的判定更公平
    shared = sorted(set(profile_a["up_masters_visited"]) & set(profile_b["up_masters_visited"]))
    if shared:
        basis = f"共同评价者：{'、'.join(shared)}（同一个人的标准，更可比）"
        basis_a = _verdict_stats(summaries_a, set(shared))
        basis_b = _verdict_stats(summaries_b, set(shared))
    else:
        basis = "没有共同评价者：跨UP主比较，各人标准可能不一致"
        basis_a = _verdict_stats(summaries_a)
        basis_b = _verdict_stats(summaries_b)

    summary: dict[str, Any] = {
        "restaurant_a": name_a,
        "restaurant_b": name_b,
        "city": city or rest_a["city"],
        "basis": basis,
        "higher_recommendation": None,
        "safer_choice_lower_avoid": None,
    }
    if min(basis_a["verdicts"], basis_b["verdicts"]) < MIN_VERDICTS_FOR_COMPARISON:
        summary["note"] = (
            f"样本不足：用于比较的菜品判定 A 有 {basis_a['verdicts']} 条、"
            f"B 有 {basis_b['verdicts']} 条（每家至少 {MIN_VERDICTS_FOR_COMPARISON} 条），"
            "不给出孰优孰劣的结论"
        )
    else:
        summary["higher_recommendation"] = _pick(
            name_a, name_b,
            basis_a["recommend_rate"], basis_b["recommend_rate"],
            prefer_higher=True,
        )
        summary["safer_choice_lower_avoid"] = _pick(
            name_a, name_b,
            basis_a["avoid_rate"], basis_b["avoid_rate"],
            prefer_higher=False,
        )

    return {
        "comparison_summary": summary,
        "restaurant_a": profile_a,
        "restaurant_b": profile_b,
    }


async def _get_up_taste_profile(args: dict) -> dict:
    """获取 UP主口味画像"""
    up_name = args["up_name"].strip()
    up = await pg.find_up_master_by_name(up_name)
    if not up:
        return {"error": f"未找到 UP 主: '{up_name}'", "suggestion": "请确认UP主名称是否准确"}

    rows = await pg.get_reviews_by_up_master(up["id"])
    if not rows:
        return {
            "up_name": up["name"],
            "bilibili_uid": up["bilibili_uid"],
            "credibility": CREDIBILITY_NOT_COMPUTED,
            "message": "该UP主暂无已入库的探店评价数据",
        }

    # 管线重跑可能留下重复评价：同一视频里的同一道菜只算一次
    latest: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (str(r.get("dish_id") or r.get("dish_name")), str(r.get("video_bvid") or ""))
        current = latest.get(key)
        if current is None or str(r.get("created_at") or "") > str(current.get("created_at") or ""):
            latest[key] = r
    reviews = list(latest.values())

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
    recommend_rate = round(rec_count / total_rev * 100, 1)

    # 只描述表达风格：踩雷给得多不等于更诚实，毒舌本身也是一种内容风格
    if avoid_rate >= 30.0:
        selectivity = "高（经常给出踩雷）"
    elif avoid_rate >= 15.0:
        selectivity = "中"
    elif avoid_rate >= 5.0:
        selectivity = "低"
    else:
        selectivity = "极低（以推荐为主）"

    def _quote_item(r: dict) -> dict:
        return {
            "dish": r["dish_name"],
            "restaurant": r["restaurant_name"],
            "city": r["restaurant_city"],
            "quote": r["raw_text"],
            **_source_fields(r),
        }

    # 已核验的原话排在前面
    by_verified = sorted(reviews, key=lambda r: not r.get("quote_verified"))
    top_recommended = [_quote_item(r) for r in by_verified if r["sentiment"] == "推荐"][:8]
    avoided_dishes = [_quote_item(r) for r in by_verified if r["sentiment"] == "踩雷"][:8]

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
            "credibility": CREDIBILITY_NOT_COMPUTED,
            "style_tags": up.get("style_tags", []),
        },
        "overview": {
            "total_reviews": total_rev,
            "total_restaurants_visited": len(visited_restaurants),
            "visited_cities": sorted(visited_cities),
        },
        "taste_profile": {
            "cuisine_preferences": cuisine_pref,
            "selectivity": selectivity,
            "sentiment_distribution": {
                "recommended": rec_count,
                "average": avg_count,
                "avoid": avoid_count,
                "recommend_rate": f"{recommend_rate}%",
                "avoid_rate": f"{avoid_rate}%",
            },
        },
        "how_to_read": (
            "selectivity 只描述这位UP主给出踩雷的频率（表达风格），不代表可信度。"
            "推荐率越高，单条'推荐'的区分度越低，可作为解读其评价的基线。"
        ),
        "hall_of_fame": {
            "top_recommended_dishes": top_recommended,
            "avoided_dishes": avoided_dishes,
        },
        **graph_extra,
    }


def _pick_quote(recommended: list[dict[str, Any]], max_chars: int = 60) -> dict[str, str] | None:
    """从推荐菜的证据里挑一句原话，优先已核验的"""
    candidates = [
        e for s in recommended for e in s["evidence"] if e["verdict"] == "推荐" and e["quote"]
    ]
    if not candidates:
        return None
    best = next((e for e in candidates if e["quote_verified"]), candidates[0])
    text = best["quote"].strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "…"
    return {"quote": text, "up": best["up"]}


def _evidence_refs(summaries: list[dict[str, Any]], verdict: str) -> list[dict[str, Any]]:
    return [
        {
            "dish": s["dish"],
            "ups": [e["up"] for e in s["evidence"] if e["verdict"] == verdict],
            "video_urls": [e["video_url"] for e in s["evidence"] if e["verdict"] == verdict],
        }
        for s in summaries
    ]


def _match_restaurant(name: str, allowed: dict[str, dict]) -> str | None:
    name = name.strip()
    if not name:
        return None
    if name in allowed:
        return name
    for known in allowed:
        if name in known or known in name:
            return known
    return None


def _ground_itinerary(plan: dict, allowed: dict[str, dict]) -> int:
    """
    删掉行程里不在证据数据中的内容（餐厅、菜品、原话），返回删除的条数

    LLM 只负责排序和组织；它新增的任何事实都不应该出现在结果里。
    """
    removed = 0
    days = plan.get("itinerary")
    if not isinstance(days, list):
        return removed

    for day in days:
        stops = day.get("stops") if isinstance(day, dict) else None
        if not isinstance(stops, list):
            continue
        kept = []
        for stop in stops:
            known = None
            if isinstance(stop, dict):
                known = _match_restaurant(str(stop.get("restaurant", "")), allowed)
            if known is None:
                removed += 1
                continue
            facts = allowed[known]
            pools = {"recommended_dishes": facts["recommended"], "avoid_dishes": facts["avoid"]}
            for field, pool in pools.items():
                dishes = stop.get(field) or []
                if not isinstance(dishes, list):
                    dishes = []
                grounded = [d for d in dishes if isinstance(d, str) and d.strip() in pool]
                removed += len(dishes) - len(grounded)
                stop[field] = grounded

            quote = normalize(str(stop.get("up_master_quote") or ""))
            sources = [normalize(q) for q in facts["quotes"] if normalize(q)]
            if quote and not any(s in quote or quote in s for s in sources):
                stop["up_master_quote"] = ""
                removed += 1
            kept.append(stop)
        day["stops"] = kept
    return removed


async def _generate_itinerary(args: dict) -> dict:
    """生成美食行程：LLM 只负责编排，事实全部来自证据数据"""
    city = normalize_city(args["city"])
    days = args.get("days", 1)
    preferences = args.get("preferences", "")
    budget = args.get("budget", "moderate")

    # 获取城市餐厅数据
    restaurants = await pg.list_restaurants(city=city, limit=30)

    if not restaurants:
        return {"error": f"暂无 {city} 的餐厅数据"}

    rest_summaries = []
    allowed: dict[str, dict] = {}
    for r in restaurants[:25]:
        reviews = await pg.get_reviews_for_restaurant(r["id"])
        summaries = summarize_dishes(reviews)
        lists = _dish_lists(summaries)
        # 行程只安排有UP主推荐证据的餐厅
        if not lists["recommended"]:
            continue
        recommended = lists["recommended"][:4]
        avoid = lists["avoid"][:3]
        quote = _pick_quote(recommended)

        geo_info = ""
        if r.get("district"):
            geo_info += f"[{r['district']}]"
        if r.get("latitude") and r.get("longitude"):
            geo_info += f"(坐标:{r['latitude']:.4f},{r['longitude']:.4f})"
        if r.get("geo_verified"):
            geo_info += "[高德已核验]"

        ups = sorted({e["up"] for s in summaries for e in s["evidence"]})
        line = (
            f"【{r['name']}】{geo_info} 菜系: {r['cuisine_type']}，"
            f"人均: {r['price_range'] or '未知'}，评价UP主: {'、'.join(ups)}"
        )
        line += "，推荐菜: " + "、".join(
            f"{s['dish']}（{s['verdict_counts']['推荐']}位UP主推荐）" for s in recommended
        )
        if avoid:
            line += "，避雷菜: " + "、".join(
                f"{s['dish']}（{s['verdict_counts']['踩雷']}位UP主说踩雷）" for s in avoid
            )
        if quote:
            line += f"，UP主原话: 「{quote['quote']}」——{quote['up']}"
        rest_summaries.append(line)

        allowed[r["name"]] = {
            "recommended": [s["dish"] for s in recommended],
            "avoid": [s["dish"] for s in avoid],
            "quotes": [quote["quote"]] if quote else [],
            "evidence": {
                "recommended": _evidence_refs(recommended, "推荐"),
                "avoid": _evidence_refs(avoid, "踩雷"),
            },
        }

    if not rest_summaries:
        return {"error": f"{city} 暂无有UP主推荐证据的餐厅"}

    restaurant_data = "\n".join(rest_summaries)

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
        temperature=0.2,
        response_format={"type": "json_object"},
    )

    evidence = {name: facts["evidence"] for name, facts in allowed.items()}
    try:
        plan = json.loads(response)
    except json.JSONDecodeError:
        return {"itinerary_text": response, "evidence": evidence}

    removed = _ground_itinerary(plan, allowed)
    if removed:
        plan["grounding_note"] = f"已删除 {removed} 处不在证据数据中的内容"
    plan["evidence"] = evidence
    return plan


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
