"""
字幕提取模块

功能：
  - 从B站视频提取 CC 字幕 / AI 自动字幕
  - 将字幕转换为统一的 TranscriptResult 格式
  - 字幕缓存到本地文件

优先级策略:
  1. CC字幕（人工字幕）→ 准确率最高
  2. AI自动字幕 → B站自动生成
  3. 返回空结果 → 交由 Whisper ASR 处理
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
from bilibili_api import Credential, video
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings
from src.models.entities import SubtitleSegment, TranscriptResult


class SubtitleExtractor:
    """B站字幕提取器"""

    def __init__(self, cache_dir: Path | None = None) -> None:
        self.credential = Credential(
            sessdata=settings.bilibili.sessdata,
            bili_jct=settings.bilibili.bili_jct,
            buvid3=settings.bilibili.buvid3,
        )
        self.cache_dir = cache_dir or (settings.data_dir / "subtitles")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    async def extract(self, bvid: str) -> TranscriptResult:
        """
        提取视频字幕

        按优先级尝试：CC字幕 → AI字幕 → 空结果

        Args:
            bvid: 视频BV号

        Returns:
            TranscriptResult
        """
        # 先检查缓存
        cached = self._load_cache(bvid)
        if cached:
            logger.info(f"从缓存加载字幕: {bvid}")
            return cached

        # 获取字幕列表
        subtitle_list = await self._get_subtitle_list(bvid)

        if not subtitle_list:
            logger.warning(f"视频 {bvid} 无可用字幕，需要ASR转写")
            return TranscriptResult(video_bvid=bvid, source="none")

        # 按优先级选择字幕
        selected = self._select_best_subtitle(subtitle_list)
        if not selected:
            return TranscriptResult(video_bvid=bvid, source="none")

        # 下载并解析字幕
        subtitle_url = selected.get("subtitle_url", "")
        if subtitle_url.startswith("//"):
            subtitle_url = "https:" + subtitle_url

        segments = await self._download_subtitle(subtitle_url)

        source = "cc" if selected.get("type", "") == "manual" else "ai"
        result = TranscriptResult(
            video_bvid=bvid,
            source=source,
            language=selected.get("lan", "zh"),
            segments=segments,
            full_text=" ".join(seg.text for seg in segments),
        )

        # 缓存到本地
        self._save_cache(bvid, result)
        logger.info(f"字幕提取完成: {bvid} (来源={source}, 片段数={len(segments)})")

        return result

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def _get_subtitle_list(self, bvid: str) -> list[dict]:
        """获取视频的字幕列表"""
        try:
            v = video.Video(bvid=bvid, credential=self.credential)
            # 先获取视频信息以取得 cid（get_player_info 需要 cid 参数）
            info = await v.get_info()
            cid = info.get("cid")
            if not cid:
                pages = info.get("pages", [])
                if pages:
                    cid = pages[0].get("cid")
            if not cid:
                logger.warning(f"视频 {bvid} 无法获取 cid，跳过字幕提取")
                return []
            player_info = await v.get_player_info(cid=cid)
            subtitles = player_info.get("subtitle", {}).get("subtitles", [])
            return subtitles
        except Exception as e:
            logger.error(f"获取字幕列表失败 [{bvid}]: {e}")
            return []

    def _select_best_subtitle(self, subtitle_list: list[dict]) -> dict | None:
        """
        按优先级选择最佳字幕

        优先级: 中文CC字幕 > 中文AI字幕 > 其他语言
        """
        # 按语言和类型排序
        zh_manual = [s for s in subtitle_list if "zh" in s.get("lan", "") and s.get("type") == "manual"]
        zh_auto = [s for s in subtitle_list if "zh" in s.get("lan", "") and s.get("type") != "manual"]
        others = [s for s in subtitle_list if "zh" not in s.get("lan", "")]

        if zh_manual:
            return zh_manual[0]
        if zh_auto:
            return zh_auto[0]
        if others:
            return others[0]
        return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def _download_subtitle(self, url: str) -> list[SubtitleSegment]:
        """下载并解析字幕文件"""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=15.0)
                resp.raise_for_status()
                data = resp.json()

            segments = []
            for item in data.get("body", []):
                seg = SubtitleSegment(
                    start=item.get("from", 0.0),
                    end=item.get("to", 0.0),
                    text=item.get("content", "").strip(),
                )
                if seg.text:
                    segments.append(seg)

            return segments

        except Exception as e:
            logger.error(f"下载字幕失败: {e}")
            return []

    def _load_cache(self, bvid: str) -> TranscriptResult | None:
        """从缓存加载字幕"""
        cache_file = self.cache_dir / f"{bvid}.json"
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                return TranscriptResult(**data)
            except Exception:
                return None
        return None

    def _save_cache(self, bvid: str, result: TranscriptResult) -> None:
        """缓存字幕到本地"""
        cache_file = self.cache_dir / f"{bvid}.json"
        try:
            cache_file.write_text(
                result.model_dump_json(indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"缓存字幕失败 [{bvid}]: {e}")
