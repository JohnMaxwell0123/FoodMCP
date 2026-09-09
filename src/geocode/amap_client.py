"""
高德地图 POI 搜索 & 地理编码

通过餐厅名 + 城市搜索高德 POI，补全精确地址和经纬度。
引入 RapidFuzz 字符串相似度核验与三级置信度门禁，防止误匹配脏数据。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from loguru import logger
from rapidfuzz import fuzz

from config.settings import settings


@dataclass
class GeoResult:
    """地理编码/POI搜索结果"""

    name: str  # 标准化名称
    address: str  # 完整地址
    city: str  # 城市
    district: str  # 区县
    latitude: float  # 纬度
    longitude: float  # 经度
    source: str = ""  # 数据来源: poi / geocode / city_fallback
    confidence: float = 0.0  # 匹配置信度 (0.0 ~ 1.0)
    is_verified: bool = False  # 是否为高置信度核验通过


class AmapClient:
    """高德地图 API 客户端"""

    BASE_URL = "https://restapi.amap.com/v3"

    # 置信度阈值门禁
    CONFIDENCE_HIGH: float = 0.70  # 高置信度：采纳精确 POI 与经纬度
    CONFIDENCE_LOW: float = 0.45  # 低于此阈值坚决拒绝采纳，转入降级

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or settings.amap.api_key
        if not self.api_key:
            logger.warning("高德 API Key 未配置，地址补全将跳过")

    @staticmethod
    def calculate_confidence(
        query_name: str,
        poi_name: str,
        target_city: str = "",
        poi_city: str = "",
        poi_type: str = "",
    ) -> float:
        """
        计算高德 POI 匹配的置信度得分 (0.0 ~ 1.0)

        维度：
          1. 字符集合相似度 (Token Set Ratio) 与子串覆盖率
          2. 餐厅名相互包含奖励
          3. 城市强约束校验（跨城施加重罚）
          4. 餐饮分类加成
        """
        if not query_name or not poi_name:
            return 0.0

        q_clean = query_name.strip()
        p_clean = poi_name.strip()

        # 1. 基础名称相似度计算
        token_score = fuzz.token_set_ratio(q_clean, p_clean) / 100.0
        partial_score = fuzz.partial_ratio(q_clean, p_clean) / 100.0
        ratio_score = fuzz.ratio(q_clean, p_clean) / 100.0

        base_score = 0.5 * token_score + 0.3 * partial_score + 0.2 * ratio_score

        # 2. 包含匹配奖励（例如 "四季民福" in "四季民福烤鸭店(故宫店)"）
        bonus = 0.0
        if q_clean in p_clean or p_clean in q_clean:
            bonus += 0.15

        # 3. 城市一致性约束
        city_penalty = 0.0
        if target_city and target_city not in ("未知", ""):
            if poi_city:
                # 检查城市是否吻合
                if target_city in poi_city or poi_city in target_city:
                    bonus += 0.10
                else:
                    # 跨城重罚，直接拦截严重误匹配
                    city_penalty -= 0.50
            else:
                city_penalty -= 0.10

        # 4. POI 餐饮类型加成 (05xxxx 为高德餐饮类分类代码)
        if "餐饮" in poi_type or "美食" in poi_type or poi_type.startswith("05"):
            bonus += 0.05

        final_score = base_score + bonus + city_penalty
        return round(min(1.0, max(0.0, final_score)), 3)

    async def search_poi(
        self,
        keyword: str,
        city: str = "",
        city_limit: bool = True,
        recall_size: int = 5,
    ) -> GeoResult | None:
        """
        通过关键字搜索 POI，召回多条候选并按置信度择优

        Args:
            keyword: 搜索关键词（餐厅名）
            city: 城市名（可选，缩小搜索范围）
            city_limit: 是否仅返回该城市的结果
            recall_size: 候选召回数量

        Returns:
            GeoResult 或 None
        """
        if not self.api_key or not keyword.strip():
            return None

        clean_keyword = keyword.strip()
        params: dict[str, str | int] = {
            "key": self.api_key,
            "keywords": clean_keyword,
            "types": "050000",  # 餐饮类 POI
            "offset": recall_size,
            "page": 1,
            "extensions": "base",
        }
        if city and city != "未知":
            params["city"] = city
            if city_limit:
                params["citylimit"] = "true"

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.BASE_URL}/place/text", params=params)
                resp.raise_for_status()
                data = resp.json()

            if data.get("status") != "1":
                logger.warning(f"高德 POI 搜索失败 [{clean_keyword}]: {data.get('info')}")
                return None

            pois = data.get("pois", [])
            if not pois:
                logger.info(f"高德 POI 未找到: {clean_keyword} in {city}")
                return None

            # 对多条候选进行置信度评估
            best_poi: dict[str, Any] | None = None
            best_confidence = -1.0

            for poi in pois:
                p_name = poi.get("name", "")
                p_city = poi.get("cityname", "")
                p_type = poi.get("type", "")

                conf = self.calculate_confidence(
                    query_name=clean_keyword,
                    poi_name=p_name,
                    target_city=city,
                    poi_city=p_city,
                    poi_type=p_type,
                )

                if conf > best_confidence:
                    best_confidence = conf
                    best_poi = poi

            # 门禁过滤：置信度过低时坚决拒绝采纳
            if best_confidence < self.CONFIDENCE_LOW or not best_poi:
                logger.warning(
                    f"高德 POI 拒绝采纳 (置信度过低 {best_confidence:.2f} < {self.CONFIDENCE_LOW}): "
                    f"{clean_keyword} (Top Candidate: {best_poi.get('name') if best_poi else 'None'})"
                )
                return None

            location = best_poi.get("location", "0,0")
            lng_str, lat_str = location.split(",")
            is_verified = best_confidence >= self.CONFIDENCE_HIGH

            result = GeoResult(
                name=best_poi.get("name", clean_keyword),
                address=best_poi.get("address", ""),
                city=best_poi.get("cityname", city) or city,
                district=best_poi.get("adname", ""),
                latitude=float(lat_str),
                longitude=float(lng_str),
                source="poi",
                confidence=best_confidence,
                is_verified=is_verified,
            )

            logger.info(
                f"高德 POI 匹配成功 (conf={result.confidence:.2f}, verified={result.is_verified}): "
                f"{clean_keyword} → {result.name} ({result.address})"
            )
            return result

        except Exception as e:
            logger.error(f"高德 API 请求异常 [{clean_keyword}]: {e}")
            return None

    async def geocode(self, address: str, city: str = "") -> GeoResult | None:
        """
        地理编码：地址文本 → 经纬度

        Args:
            address: 地址文本
            city: 城市（可选）

        Returns:
            GeoResult 或 None
        """
        if not self.api_key or not address.strip():
            return None

        params: dict[str, str] = {
            "key": self.api_key,
            "address": address.strip(),
        }
        if city and city != "未知":
            params["city"] = city

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.BASE_URL}/geocode/geo", params=params)
                resp.raise_for_status()
                data = resp.json()

            if data.get("status") != "1":
                return None

            geocodes = data.get("geocodes")
            if not geocodes:
                return None

            geo = geocodes[0]
            location = geo.get("location", "0,0")
            lng_str, lat_str = location.split(",")
            level = geo.get("level", "")

            # 城市级降级还是具体门牌
            is_city_level = level in ("市", "城市", "省", "区县")
            source = "city_fallback" if is_city_level else "geocode"

            return GeoResult(
                name="",
                address=geo.get("formatted_address", address),
                city=geo.get("city", city) or city,
                district=geo.get("district", ""),
                latitude=float(lat_str),
                longitude=float(lng_str),
                source=source,
                confidence=0.5 if not is_city_level else 0.3,
                is_verified=False,
            )

        except Exception as e:
            logger.error(f"高德地理编码异常 [{address}]: {e}")
            return None

    async def resolve_address(
        self,
        name: str,
        location_hint: str = "",
        city: str = "",
    ) -> GeoResult | None:
        """
        综合解析地址：优先带置信度的 POI 搜索，失败则尝试地址编码或城市中心降级

        Args:
            name: 餐厅名称
            location_hint: 从字幕中提取的地址线索
            city: 城市名

        Returns:
            GeoResult 或 None
        """
        # 从 location_hint 尝试推断城市
        if not city and location_hint:
            city = self._guess_city(location_hint)

        # 1. 优先 POI 搜索（带置信度门禁）
        result = await self.search_poi(name, city=city)
        if result and result.is_verified:
            return result

        # 2. 若 POI 搜索仅有中等置信度，但有详细地址线索，尝试地址编码辅助
        if location_hint:
            full_address = f"{city} {location_hint} {name}" if city else f"{location_hint} {name}"
            geo_res = await self.geocode(full_address, city=city)
            if geo_res and geo_res.source != "city_fallback":
                return geo_res

        # 3. 若 POI 具备中置信度，且无更优地理编码，采纳为未核验结果
        if result:
            return result

        # 4. 彻底未匹配时：若已知目标城市，优雅降级为城市中心坐标，绝不采纳假 POI
        if city and city != "未知":
            city_geo = await self.geocode(city, city=city)
            if city_geo:
                city_geo.name = name
                city_geo.source = "city_fallback"
                city_geo.is_verified = False
                logger.info(f"高德地址解析降级为城市中心坐标: {name} in {city}")
                return city_geo

        return None

    @staticmethod
    def _guess_city(text: str) -> str:
        """从文本中推断城市"""
        known_cities = [
            "北京", "上海", "广州", "深圳", "杭州", "成都", "重庆",
            "南京", "武汉", "西安", "长沙", "天津", "苏州", "厦门",
            "青岛", "大连", "昆明", "贵阳", "南宁", "哈尔滨", "沈阳",
            "郑州", "济南", "福州", "合肥", "南昌", "太原", "石家庄",
            "长春", "兰州", "银川", "西宁", "海口", "乌鲁木齐",
            "钦州", "柳州", "桂林", "北海", "佛山", "潮州", "汕头", "顺德",
        ]
        for c in known_cities:
            if c in text:
                return c
        return ""
