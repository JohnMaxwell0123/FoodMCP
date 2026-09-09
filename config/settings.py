"""
统一配置管理

使用 pydantic-settings 从环境变量 / .env 文件加载配置。
通过 python-dotenv 先将 .env 加载到 os.environ，避免嵌套 BaseSettings 的 env_file 冲突。
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 将 .env 加载到 os.environ，子 Settings 类通过 env_prefix 从环境变量读取
load_dotenv(PROJECT_ROOT / ".env")


class BilibiliSettings(BaseSettings):
    """B站认证凭据"""

    sessdata: str = ""
    bili_jct: str = ""
    buvid3: str = ""

    model_config = SettingsConfigDict(env_prefix="BILIBILI_", extra="ignore")


class LLMSettings(BaseSettings):
    """LLM 配置 (Chat 模型，推荐 DeepSeek)"""

    openai_api_key: str = ""
    openai_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"  # deepseek-chat 自动映射至官方最新版本(如 V3/V4/V4.1)，亦可指定具体版本

    model_config = SettingsConfigDict(extra="ignore")


class EmbeddingSettings(BaseSettings):
    """Embedding 配置 (可独立于 LLM)"""

    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "text-embedding-3-small"
    dimension: int = 1536  # 对应向量维度 (如 text-embedding-3-small=1536, bge-m3=1024, large=3072)

    model_config = SettingsConfigDict(env_prefix="EMBEDDING_", extra="ignore")


class Neo4jSettings(BaseSettings):
    """Neo4j 连接配置"""

    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = ""

    model_config = SettingsConfigDict(env_prefix="NEO4J_", extra="ignore")


class PostgresSettings(BaseSettings):
    """PostgreSQL 连接配置"""

    host: str = "localhost"
    port: int = 5433
    db: str = "food_recommendation"
    user: str = "postgres"
    password: str = ""

    model_config = SettingsConfigDict(env_prefix="POSTGRES_", extra="ignore")

    @property
    def dsn(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"


class MilvusSettings(BaseSettings):
    """Milvus 向量数据库配置"""

    host: str = "localhost"
    port: int = 19530
    collection: str = "food_reviews"

    model_config = SettingsConfigDict(env_prefix="MILVUS_", extra="ignore")


class AmapSettings(BaseSettings):
    """高德地图 API 配置"""

    api_key: str = ""

    model_config = SettingsConfigDict(env_prefix="AMAP_", extra="ignore")


class WhisperSettings(BaseSettings):
    """Whisper ASR 配置"""

    model: str = "large-v3-turbo"  # 推荐 large-v3-turbo (推理速度提升4x且显存低)，亦可选 large-v3 / medium / small
    device: str = "cuda"

    model_config = SettingsConfigDict(env_prefix="WHISPER_", extra="ignore")


class AppSettings(BaseSettings):
    """应用级全局配置"""

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    data_dir: Path = Field(default=PROJECT_ROOT / "data")

    # 子配置
    bilibili: BilibiliSettings = Field(default_factory=BilibiliSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    neo4j: Neo4jSettings = Field(default_factory=Neo4jSettings)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    milvus: MilvusSettings = Field(default_factory=MilvusSettings)
    amap: AmapSettings = Field(default_factory=AmapSettings)
    whisper: WhisperSettings = Field(default_factory=WhisperSettings)

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def ensure_data_dirs(self) -> None:
        """确保数据目录存在"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "videos").mkdir(exist_ok=True)
        (self.data_dir / "subtitles").mkdir(exist_ok=True)
        (self.data_dir / "transcripts").mkdir(exist_ok=True)
        (self.data_dir / "extractions").mkdir(exist_ok=True)


# 全局单例
settings = AppSettings()
