"""
B站API客户端封装

功能：
  - 获取UP主视频列表
  - 获取视频详细信息
  - 获取视频字幕信息
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from bilibili_api import Credential, get_selected_client, user, video
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings
from src.models.entities import VideoInfo


class BilibiliClient:
    """B站API客户端"""

    # 请求间隔（秒），避免触发B站412风控
    REQUEST_DELAY: float = 2.0

    def __init__(self) -> None:
        self.credential = Credential(
            sessdata=settings.bilibili.sessdata,
            bili_jct=settings.bilibili.bili_jct,
            buvid3=settings.bilibili.buvid3,
        )
        # 检查是否使用了 curl_cffi 客户端（绕过 TLS 指纹检测）
        client_name, _ = get_selected_client()
        if client_name != "curl_cffi":
            logger.warning(
                f"当前使用 {client_name} 客户端，建议安装 curl-cffi 以绕过B站412风控: "
                f"pip install curl-cffi"
            )
        else:
            logger.info("B站客户端已使用 curl_cffi（TLS指纹伪装）")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def get_up_videos(
        self,
        mid: int,
        page_size: int = 30,
        max_pages: int = 5,
    ) -> list[VideoInfo]:
        """
        获取指定UP主的视频列表

        Args:
            mid: UP主的MID
            page_size: 每页视频数
            max_pages: 最大翻页数

        Returns:
            VideoInfo列表
        """
        u = user.User(uid=mid, credential=self.credential)
        all_videos: list[VideoInfo] = []

        for page in range(1, max_pages + 1):
            try:
                resp = await u.get_videos(pn=page, ps=page_size)
                video_list = resp.get("list", {}).get("vlist", [])

                if not video_list:
                    logger.warning(f"UP主 {mid} 第{page}页无视频，API 原始响应: {resp}")
                    logger.info(f"UP主 {mid} 第{page}页无更多视频，停止翻页")
                    break

                for v in video_list:
                    info = VideoInfo(
                        bvid=v.get("bvid", ""),
                        title=v.get("title", ""),
                        description=v.get("description", ""),
                        duration=v.get("length", 0) if isinstance(v.get("length"), int) else 0,
                        publish_date=str(v.get("created", "")),
                        up_mid=str(mid),
                        up_name=v.get("author", ""),
                        view_count=v.get("play", 0),
                    )
                    all_videos.append(info)

                logger.info(f"UP主 {mid} 第{page}页获取 {len(video_list)} 个视频")

                # 礼貌性延迟，避免触发B站412风控
                await asyncio.sleep(self.REQUEST_DELAY)

            except Exception as e:
                logger.error(f"获取UP主 {mid} 第{page}页视频失败: {e}")
                break

        logger.info(f"UP主 {mid} 共获取 {len(all_videos)} 个视频")
        return all_videos

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def get_video_info(self, bvid: str) -> dict:
        """
        获取视频详细信息

        Args:
            bvid: 视频BV号

        Returns:
            视频详细信息字典
        """
        v = video.Video(bvid=bvid, credential=self.credential)
        info = await v.get_info()
        return info

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def get_video_tags(self, bvid: str) -> list[str]:
        """
        获取视频标签

        Args:
            bvid: 视频BV号

        Returns:
            标签列表
        """
        v = video.Video(bvid=bvid, credential=self.credential)
        try:
            tags_data = await v.get_tags()
            return [tag.get("tag_name", "") for tag in tags_data if tag.get("tag_name")]
        except Exception as e:
            logger.warning(f"获取视频 {bvid} 标签失败: {e}")
            return []

    async def get_video_subtitle_info(self, bvid: str) -> dict:
        """
        获取视频字幕信息（用于判断是否有CC字幕/AI字幕）

        Args:
            bvid: 视频BV号

        Returns:
            字幕信息字典
        """
        v = video.Video(bvid=bvid, credential=self.credential)
        try:
            player_info = await v.get_player_info()
            subtitle_info = player_info.get("subtitle", {})
            return subtitle_info
        except Exception as e:
            logger.warning(f"获取视频 {bvid} 字幕信息失败: {e}")
            return {}
