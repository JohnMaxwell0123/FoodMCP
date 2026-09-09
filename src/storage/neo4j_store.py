"""
Neo4j 图数据库存储

维护实体关系网络:
  - (UP主)-[:探访]->(餐厅)
  - (餐厅)-[:提供]->(菜品)
  - (UP主)-[:评价]->(菜品)
  - (餐厅)-[:位于]->(城市)
"""

from __future__ import annotations

from loguru import logger
from neo4j import AsyncGraphDatabase, AsyncDriver

from config.settings import settings
from src.models.entities import Dish, Restaurant, Review, UPMaster


class Neo4jStore:
    """Neo4j 图数据库管理"""

    def __init__(self) -> None:
        self._driver: AsyncDriver | None = None

    async def connect(self) -> None:
        self._driver = AsyncGraphDatabase.driver(
            settings.neo4j.uri,
            auth=(settings.neo4j.user, settings.neo4j.password),
        )
        async with self._driver.session() as session:
            await session.run("RETURN 1")
        logger.info("Neo4j 连接已建立")

    async def close(self) -> None:
        if self._driver:
            await self._driver.close()

    async def init_constraints(self) -> None:
        constraints = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (r:Restaurant) REQUIRE r.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Dish) REQUIRE d.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (u:UPMaster) REQUIRE u.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (c:City) REQUIRE c.name IS UNIQUE",
        ]
        async with self._driver.session() as session:
            for c in constraints:
                await session.run(c)
        logger.info("Neo4j 约束初始化完成")

    async def merge_restaurant(self, restaurant: Restaurant) -> None:
        query = """
            MERGE (r:Restaurant {id: $id})
            SET r.name=$name, r.city=$city, r.district=$district,
                r.address=$address, r.cuisine_type=$cuisine_type,
                r.price_range=$price_range, r.tags=$tags
            WITH r
            MERGE (c:City {name: $city})
            MERGE (r)-[:位于]->(c)
        """
        async with self._driver.session() as session:
            await session.run(query, id=restaurant.id, name=restaurant.name,
                city=restaurant.city, district=restaurant.district,
                address=restaurant.address, cuisine_type=restaurant.cuisine_type,
                price_range=restaurant.price_range, tags=restaurant.tags)

    async def merge_dish(self, dish: Dish, restaurant_id: str) -> None:
        query = """
            MERGE (d:Dish {id: $id})
            SET d.name=$name, d.category=$category, d.price=$price,
                d.avg_sentiment=$avg_sentiment
            WITH d
            MATCH (r:Restaurant {id: $restaurant_id})
            MERGE (r)-[:提供]->(d)
        """
        async with self._driver.session() as session:
            await session.run(query, id=dish.id, name=dish.name,
                category=dish.category, price=dish.price,
                avg_sentiment=dish.avg_sentiment, restaurant_id=restaurant_id)

    async def merge_up_master(self, up: UPMaster) -> None:
        query = """
            MERGE (u:UPMaster {id: $id})
            SET u.bilibili_uid=$bilibili_uid, u.name=$name,
                u.follower_count=$follower_count, u.style_tags=$style_tags
        """
        async with self._driver.session() as session:
            await session.run(query, id=up.id, bilibili_uid=up.bilibili_uid,
                name=up.name, follower_count=up.follower_count,
                style_tags=up.style_tags)

    async def create_review_relations(self, review: Review, video_bvid: str) -> None:
        query = """
            MATCH (u:UPMaster {id: $up_id})
            MATCH (r:Restaurant {id: $rest_id})
            MATCH (d:Dish {id: $dish_id})
            MERGE (u)-[:探访 {video_bvid: $bvid}]->(r)
            MERGE (u)-[rev:评价 {review_id: $rev_id}]->(d)
            SET rev.sentiment=$sentiment, rev.raw_text=$raw_text,
                rev.sentiment_score=$score, rev.video_bvid=$bvid
        """
        async with self._driver.session() as session:
            await session.run(query, up_id=review.up_master_id,
                rest_id=review.restaurant_id, dish_id=review.dish_id,
                rev_id=review.id, bvid=video_bvid,
                sentiment=review.sentiment.value, raw_text=review.raw_text,
                score=review.sentiment_score)

    async def find_highly_recommended(self, city: str, min_ups: int = 2, limit: int = 10) -> list[dict]:
        query = """
            MATCH (u:UPMaster)-[rev:评价]->(d:Dish)<-[:提供]-(r:Restaurant)
            WHERE r.city=$city AND rev.sentiment='推荐'
            WITH r, COUNT(DISTINCT u) AS cnt, COLLECT(DISTINCT u.name) AS ups
            WHERE cnt >= $min_ups
            RETURN r.name AS name, r.cuisine_type AS cuisine, cnt, ups
            ORDER BY cnt DESC LIMIT $limit
        """
        async with self._driver.session() as session:
            result = await session.run(query, city=city, min_ups=min_ups, limit=limit)
            return await result.data()

    async def get_restaurant_graph(self, restaurant_id: str) -> dict:
        query = """
            MATCH (r:Restaurant {id: $rid})-[:提供]->(d:Dish)
            OPTIONAL MATCH (u:UPMaster)-[rev:评价]->(d)
            RETURN r.name AS rest, d.name AS dish, d.avg_sentiment AS score,
                   u.name AS up_name, rev.sentiment AS verdict, rev.raw_text AS quote
            ORDER BY d.name
        """
        async with self._driver.session() as session:
            result = await session.run(query, rid=restaurant_id)
            records = await result.data()
        dishes: dict[str, dict] = {}
        for rec in records:
            dn = rec["dish"]
            if dn not in dishes:
                dishes[dn] = {"name": dn, "avg_sentiment": rec["score"], "reviews": []}
            if rec.get("up_name"):
                dishes[dn]["reviews"].append({"up": rec["up_name"], "verdict": rec["verdict"], "quote": rec["quote"]})
        return {"restaurant": records[0]["rest"] if records else "", "dishes": list(dishes.values())}
