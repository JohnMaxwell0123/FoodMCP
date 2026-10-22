"""
测试全局配置

MCP Server 在模块导入时即创建 LLM 客户端，openai SDK 缺少 Key 会直接报错；
单元测试不调用真实 API，这里注入占位 Key（不覆盖已有环境变量）。
"""

import os

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("EMBEDDING_API_KEY", "test-key")
