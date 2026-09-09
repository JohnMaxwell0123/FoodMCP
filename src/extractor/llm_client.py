"""
LLM API 客户端

支持 OpenAI 兼容接口，可对接 GPT-4o、Qwen、Llama 等模型。
提供统一的聊天补全和 Embedding 接口。
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings
from src.extractor.prompts import PromptBuilder
from src.extractor.schema_validator import SchemaValidator
from src.models.entities import ExtractionResult


class LLMClient:
    """LLM API 客户端 (LLM 和 Embedding 可独立配置)"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        embedding_model: str | None = None,
        embedding_api_key: str | None = None,
        embedding_base_url: str | None = None,
    ) -> None:
        self.model = model or settings.llm.llm_model
        self.embedding_model = embedding_model or settings.embedding.model
        self.client = AsyncOpenAI(
            api_key=api_key or settings.llm.openai_api_key,
            base_url=base_url or settings.llm.openai_base_url,
        )
        self.embedding_client = AsyncOpenAI(
            api_key=embedding_api_key or settings.embedding.api_key,
            base_url=embedding_base_url or settings.embedding.base_url,
        )
        self.validator = SchemaValidator()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=15),
    )
    async def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        response_format: dict | None = None,
    ) -> str:
        """
        发送聊天补全请求

        Args:
            system_prompt: 系统提示
            user_prompt: 用户提示
            temperature: 温度参数
            max_tokens: 最大输出token
            response_format: 响应格式（如 {"type": "json_object"}）

        Returns:
            模型回复文本
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if response_format:
            kwargs["response_format"] = response_format

        response = await self.client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""

        logger.debug(
            f"LLM 响应: model={self.model}, "
            f"tokens={response.usage.total_tokens if response.usage else 'N/A'}"
        )

        return content

    async def extract_from_transcript(
        self,
        up_name: str,
        video_title: str,
        transcript_text: str,
    ) -> ExtractionResult:
        """
        从字幕文本中提取餐厅和菜品信息

        Args:
            up_name: UP主名称
            video_title: 视频标题
            transcript_text: 字幕全文

        Returns:
            ExtractionResult
        """
        system_prompt, user_prompt = PromptBuilder.build_extraction_prompt(
            up_name=up_name,
            video_title=video_title,
            transcript_text=transcript_text,
        )

        try:
            response_text = await self.chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.1,
                response_format={"type": "json_object"},
            )

            # 解析并验证 JSON
            result = self.validator.validate_extraction(response_text)
            logger.info(
                f"信息提取完成: 《{video_title}》 → "
                f"{len(result.restaurants)} 个餐厅, "
                f"{sum(len(r.dishes) for r in result.restaurants)} 道菜品"
            )
            return result

        except Exception as e:
            logger.error(f"信息提取失败: {e}")
            return ExtractionResult(error=str(e))

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def get_embedding(self, text: str) -> list[float]:
        """
        获取文本的 Embedding 向量

        Args:
            text: 输入文本

        Returns:
            向量列表
        """
        response = await self.embedding_client.embeddings.create(
            model=self.embedding_model,
            input=text,
        )
        return response.data[0].embedding

    async def get_embeddings_batch(
        self,
        texts: list[str],
        batch_size: int = 32,
    ) -> list[list[float]]:
        """
        批量获取 Embedding 向量

        Args:
            texts: 文本列表
            batch_size: 每批大小

        Returns:
            向量列表
        """
        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            response = await self.embedding_client.embeddings.create(
                model=self.embedding_model,
                input=batch,
            )
            batch_embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(batch_embeddings)
            logger.debug(f"Embedding 批次 {i // batch_size + 1}: {len(batch)} 条")

        return all_embeddings
