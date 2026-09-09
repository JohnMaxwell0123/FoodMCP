"""
向量数据库存储 (Milvus)

负责存储评价文本的 Embedding 向量，支持语义检索。
"""

from __future__ import annotations

from loguru import logger
from pymilvus import (
    Collection, CollectionSchema, DataType, FieldSchema,
    connections, utility,
)

from config.settings import settings

EMBEDDING_DIM = 1536  # text-embedding-3-small 维度


class VectorStore:
    """Milvus 向量数据库管理"""

    def __init__(
        self,
        collection_name: str | None = None,
        dimension: int | None = None,
    ) -> None:
        self.collection_name = collection_name or settings.milvus.collection
        self.dimension = dimension or settings.embedding.dimension
        self._collection: Collection | None = None

    def connect(self) -> None:
        connections.connect(host=settings.milvus.host, port=str(settings.milvus.port))
        logger.info("Milvus 连接已建立")

    def close(self) -> None:
        connections.disconnect("default")

    def init_collection(self) -> None:
        """初始化集合（如不存在）"""
        if utility.has_collection(self.collection_name):
            self._collection = Collection(self.collection_name)
            self._collection.load()
            logger.info(f"Milvus 集合 '{self.collection_name}' 已加载")
            return

        fields = [
            FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=36),
            FieldSchema(name="review_id", dtype=DataType.VARCHAR, max_length=36),
            FieldSchema(name="dish_name", dtype=DataType.VARCHAR, max_length=255),
            FieldSchema(name="restaurant_name", dtype=DataType.VARCHAR, max_length=255),
            FieldSchema(name="city", dtype=DataType.VARCHAR, max_length=100),
            FieldSchema(name="sentiment", dtype=DataType.VARCHAR, max_length=20),
            FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=2000),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self.dimension),
        ]
        schema = CollectionSchema(fields, description="美食评价向量")
        self._collection = Collection(self.collection_name, schema)

        # 创建 HNSW 索引
        index_params = {"metric_type": "COSINE", "index_type": "HNSW",
                        "params": {"M": 16, "efConstruction": 256}}
        self._collection.create_index("embedding", index_params)
        self._collection.load()
        logger.info(f"Milvus 集合 '{self.collection_name}' 创建完成")

    def insert(self, data: list[dict]) -> None:
        """
        插入向量数据

        data 中每条记录需包含: id, review_id, dish_name, restaurant_name,
        city, sentiment, text, embedding
        """
        if not data:
            return
        entities = [
            [d["id"] for d in data],
            [d["review_id"] for d in data],
            [d["dish_name"] for d in data],
            [d["restaurant_name"] for d in data],
            [d["city"] for d in data],
            [d["sentiment"] for d in data],
            [d["text"] for d in data],
            [d["embedding"] for d in data],
        ]
        self._collection.insert(entities)
        self._collection.flush()
        logger.info(f"Milvus 插入 {len(data)} 条记录")

    def search(
        self,
        query_embedding: list[float],
        city: str = "",
        sentiment_filter: str = "",
        top_k: int = 10,
    ) -> list[dict]:
        """
        语义检索

        Args:
            query_embedding: 查询向量
            city: 城市过滤
            sentiment_filter: 情感过滤
            top_k: 返回数量

        Returns:
            匹配结果列表
        """
        # 构建过滤表达式
        filters = []
        if city:
            filters.append(f'city == "{city}"')
        if sentiment_filter and sentiment_filter != "all":
            sentiment_map = {"recommended": "推荐", "average": "一般", "avoid": "踩雷"}
            sv = sentiment_map.get(sentiment_filter, sentiment_filter)
            filters.append(f'sentiment == "{sv}"')
        expr = " and ".join(filters) if filters else ""

        search_params = {"metric_type": "COSINE", "params": {"ef": 128}}
        results = self._collection.search(
            data=[query_embedding],
            anns_field="embedding",
            param=search_params,
            limit=top_k,
            expr=expr or None,
            output_fields=["review_id", "dish_name", "restaurant_name",
                           "city", "sentiment", "text"],
        )

        hits = []
        for hit in results[0]:
            hits.append({
                "id": hit.id,
                "score": hit.score,
                "review_id": hit.entity.get("review_id"),
                "dish_name": hit.entity.get("dish_name"),
                "restaurant_name": hit.entity.get("restaurant_name"),
                "city": hit.entity.get("city"),
                "sentiment": hit.entity.get("sentiment"),
                "text": hit.entity.get("text"),
            })
        return hits
