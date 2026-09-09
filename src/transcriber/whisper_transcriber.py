"""
Whisper ASR 语音转写

功能：
  - 使用 OpenAI Whisper 模型对无字幕视频进行语音转写
  - 支持本地 GPU 推理或远程 API 调用
  - 输出带时间戳的字幕片段
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from loguru import logger

from config.settings import settings
from src.models.entities import SubtitleSegment, TranscriptResult


class WhisperTranscriber:
    """Whisper 语音转写器"""

    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        """
        Args:
            model_name: Whisper 模型名称 (tiny/base/small/medium/large-v3)
            device: 推理设备 (cuda/cpu)
            cache_dir: 转写结果缓存目录
        """
        self.model_name = model_name or settings.whisper.model
        self.device = device or settings.whisper.device
        self.cache_dir = cache_dir or (settings.data_dir / "transcripts")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._model = None

    def _load_model(self):
        """延迟加载 Whisper 模型（避免未使用时占用显存）"""
        if self._model is None:
            try:
                import whisper

                logger.info(f"加载 Whisper 模型: {self.model_name} (device={self.device})")
                self._model = whisper.load_model(self.model_name, device=self.device)
                logger.info("Whisper 模型加载完成")
            except ImportError:
                logger.error("whisper 未安装，请运行: pip install openai-whisper")
                raise
            except Exception as e:
                logger.error(f"Whisper 模型加载失败: {e}")
                raise

    def transcribe(self, audio_path: str | Path) -> TranscriptResult:
        """
        转写音频文件

        Args:
            audio_path: 音频文件路径（支持 mp3/wav/m4a 等）

        Returns:
            TranscriptResult
        """
        audio_path = Path(audio_path)
        if not audio_path.exists():
            logger.error(f"音频文件不存在: {audio_path}")
            return TranscriptResult(
                video_bvid=audio_path.stem,
                source="whisper",
            )

        # 检查缓存
        cached = self._load_cache(audio_path.stem)
        if cached:
            logger.info(f"从缓存加载转写结果: {audio_path.stem}")
            return cached

        # 加载模型并转写
        self._load_model()
        logger.info(f"开始转写: {audio_path}")

        try:
            result = self._model.transcribe(
                str(audio_path),
                language="zh",
                task="transcribe",
                verbose=False,
            )
        except Exception as e:
            logger.error(f"转写失败: {e}")
            return TranscriptResult(
                video_bvid=audio_path.stem,
                source="whisper",
            )

        # 解析结果
        segments = []
        for seg in result.get("segments", []):
            segments.append(
                SubtitleSegment(
                    start=seg["start"],
                    end=seg["end"],
                    text=seg["text"].strip(),
                )
            )

        transcript = TranscriptResult(
            video_bvid=audio_path.stem,
            source="whisper",
            language="zh",
            segments=segments,
            full_text=result.get("text", "").strip(),
        )

        # 缓存结果
        self._save_cache(audio_path.stem, transcript)
        logger.info(
            f"转写完成: {audio_path.stem} "
            f"(片段数={len(segments)}, 总字数={len(transcript.full_text)})"
        )

        return transcript

    def transcribe_for_video(self, bvid: str, audio_path: str | Path) -> TranscriptResult:
        """
        为指定视频转写音频

        Args:
            bvid: 视频BV号
            audio_path: 音频文件路径

        Returns:
            TranscriptResult (带正确的 video_bvid)
        """
        result = self.transcribe(audio_path)
        result.video_bvid = bvid
        return result

    def _load_cache(self, key: str) -> TranscriptResult | None:
        """从缓存加载转写结果"""
        cache_file = self.cache_dir / f"{key}.json"
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                return TranscriptResult(**data)
            except Exception:
                return None
        return None

    def _save_cache(self, key: str, result: TranscriptResult) -> None:
        """缓存转写结果"""
        cache_file = self.cache_dir / f"{key}.json"
        try:
            cache_file.write_text(
                result.model_dump_json(indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"缓存转写结果失败 [{key}]: {e}")
