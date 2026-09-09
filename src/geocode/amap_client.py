"""
高德地图 POI 搜索 & 地理编码

通过餐厅名 + 城市搜索高德 POI，补全精确地址和经纬度。
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from loguru import logger

from config.settings import settings


@dataclass
class GeoResult:
    """地理编码/POI搜索结果"""

    name: str           # 标准化名称
    address: str        # 完整地址
    city: str           # 城市
    district: str       # 区县
    latitude: float     # 纬度
    longitude: float    # 经度
    source: str = ""    # 数据来源: poi / geocode


class AmapClient:
    """高德地图 API 客户端"""

    BASE_URL = "https://restapi.amap.com/v3"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or settings.amap.api_key
        if not self.api_key:
            logger.warning("高德 API Key 未配置，地址补全将跳过")

    async def search_poi(
        self,
        keyword: str,
        city: str = "",
        city_limit: bool = True,
    ) -> GeoResult | None:
        """
        通过关键字搜索 POI

        Args:
            keyword: 搜索关键词（餐厅名）
            city: 城市名（可选，缩小搜索范围）
            city_limit: 是否仅返回该城市的结果

        Returns:
            GeoResult 或 None
        """
        if not self.api_key:
            return None

        params: dict[str, str | int] = {
            "key": self.api_key,
            "keywords": keyword,
            "types": "050000",  # 餐饮类 POI
            "offset": 1,
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
                logger.warning(f"高德 POI 搜索失败 [{keyword}]: {data.get('info')}")
                return None

            pois = data.get("pois")
            if not pois:
                logger.info(f"高德 POI 未找到: {keyword} in {city}")
                return None

            poi = pois[0]
            location = poi.get("location", "0,0")
            lng_str, lat_str = location.split(",")

            result = GeoResult(
                name=poi.get("name", keyword),
                address=poi.get("address", ""),
                city=poi.get("cityname", city) or city,
                district=poi.get("adname", ""),
                latitude=float(lat_str),
                longitude=float(lng_str),
                source="poi",
            )

            logger.info(
                f"高德 POI 匹配: {keyword} → {result.name} "
                f"({result.address}, {result.latitude},{result.longitude})"
            )
            return result

        except Exception as e:
            logger.error(f"高德 API 请求异常 [{keyword}]: {e}")
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
        if not self.api_key:
            return None

        params: dict[str, str] = {
            "key": self.api_key,
            "address": address,
        }
        if city:
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

            return GeoResult(
                name="",
                address=geo.get("formatted_address", address),
                city=geo.get("city", city) or city,
                district=geo.get("district", ""),
                latitude=float(lat_str),
                longitude=float(lng_str),
                source="geocode",
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
        综合解析地址：优先 POI 搜索，失败则尝试地理编码

        Args:
            name: 餐厅名称
            location_hint: 从字幕中提取的地址线索
            city: 城市名

        Returns:
            GeoResult 或 None
        """
        # 从 location_hint 尝试提取城市
        if not city and location_hint:
            city = self._guess_city(location_hint)

        # 优先 POI 搜索
        result = await self.search_poi(name, city)
        if result:
            return result

        # 如果 POI 失败但有地址线索，尝试地理编码
        if location_hint:
            full_address = f"{city} {location_hint} {name}" if city else location_hint
            result = await self.geocode(full_address, city)
            if result:
                return result

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
            "钦州", "柳州", "桂林", "北海",
        ]
        for c in known_cities:
            if c in text:
                return c
        return ""
