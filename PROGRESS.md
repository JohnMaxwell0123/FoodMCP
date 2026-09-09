# 📋 项目进度追踪

> **项目名称：** B站探店视频深度解析与 Agent MCP 服务
> **最后更新：** 2026-08-07
> **当前阶段：** Phase 1 — MVP 概念验证（已完成）→ 作品集交付完成
> **整体进度：** ██████████ 100%（全链路含三库存储 + 地理编码打通，作品集材料已交付）

---

## 🏗️ 已完成的工作

### 2026-07-22 — 作品集交付物整理

**完成内容：** 面向字节跳动 AI 产品经理岗位，完成全套作品集材料。
- [x] `PORTFOLIO.md` — 个人作品集（产品思维 + 架构设计 + 商业模式 + 能力映射）
- [x] `SUMMARY.md` — 一页纸项目概要
- [x] `presentation.html` — 交互式产品演示页
- [x] `portfolio_pdf.html` — PDF 打印版作品集源文件
- [x] 输出两份 PDF：`FoodMCP_个人作品集.pdf`、`贾宇轩-AI产品作品集Claude.pdf`

### 2026-05-18 — 完整 Pipeline 验证（含三库存储 + 高德地理编码）

**完成内容：** 全量 Pipeline 跑通，数据真实写入 PostgreSQL + Neo4j + Milvus，并集成高德 POI 地理编码。
- [x] **新增 `src/geocode/amap_client.py`**：高德地图 POI 搜索 + 地理编码，餐厅名+城市 → 标准化地址/经纬度，已集成进 `pipeline/runner.py`
- [x] **`pg_store.py` 迁移到 psycopg3**：解决 asyncpg 在 Windows 下的连接问题
- [x] 端到端验证（特厨隋卞）：60 视频采集 → 37/60 判定为探店视频 → 处理 2 视频 → **2 餐厅 + 11 菜品** 全部写入三库
- [x] 字幕缓存扩充至 11 个视频（`data/subtitles/`）
- [ ] **发现数据质量问题**：高德 POI 匹配存在误配风险 — "山居满陇" 被匹配到 "北京绿岗山居农家院"（平谷黄松峪乡，与实际上榜餐厅不符），需增加匹配置信度校验

### 2026-05-17 — LLM API 接入 & 端到端 Pipeline 验证

**完成内容：** 配置 DeepSeek + OpenAI 双 API，修复 settings 加载 Bug，成功跑通全链路。
- [x] **LLM/Embedding 双 API 架构**：LLM 走 DeepSeek (`deepseek-chat`)，Embedding 走 OpenAI (`text-embedding-3-small`)
- [x] **修复 `settings.py` .env 加载 Bug**：嵌套 BaseSettings 的 `model_config` 不继承父类 `env_file`，改用 `python-dotenv` 在模块加载时注入 `os.environ`
- [x] **新增 `EmbeddingSettings`**：独立于 LLMSettings，通过 `EMBEDDING_` 前缀读取环境变量
- [x] **`llm_client.py` 双 client 架构**：`self.client`(LLM) 和 `self.embedding_client`(Embedding) 独立配置
- [x] 端到端 Pipeline 验证通：特厨隋卞 → 2/2 视频成功 → 2 餐厅 + 11 菜品 + 详细评价
- [x] 修复 `run_pipeline.py` Windows GBK 编码bug（emoji → ASCII）

### 2026-05-02 — 全链路集成测试 & Bug 修复

**完成内容：** 运行单元测试，修复字幕提取 Bug，优化视频筛选器，完成采集→筛选→字幕端到端验证。
- [x] 单元测试全部通过（11/11）— `pytest tests/ -v`
- [x] **修复 `subtitle_extractor.py` 的 cid Bug**：`get_player_info()` 需要先调用 `get_info()` 获取 cid 参数
- [x] **优化 `video_filter.py` 关键词集**：新增 "好吃"、"网红"、"饺子"、"面馆"、"河鲜" 等关键词；新增新疆/东北等城市覆盖
- [x] 端到端集成测试通过：特厨隋卞（MID: 1462401621）→ 采集 30 视频 → 筛出 10+ 探店视频 → 成功提取 AI 字幕（156 片段，1425 字）
- [x] 确认 Cookie 仍然有效、curl_cffi 客户端正常工作
- [ ] **待解决**：部分 UP 主（品城记、大祥哥来了）视频列表返回空，可能是隐私设置或需要更新 Cookie

### 2026-04-26 — 部署本地数据库环境（Docker Compose）

**完成内容：** 编写 `docker-compose.yml`，成功部署并启动本地多数据库环境。
- [x] 编写 `docker-compose.yml`，集成 PostgreSQL 15、Neo4j 5 和 Milvus 2.4 (Standalone)。
- [x] 配置数据库环境变量（用户名、密码）并与 `.env` 文件保持一致。
- [x] 通过 Docker Desktop 成功启动 5 个容器（`food_postgres`, `food_neo4j`, `milvus-etcd`, `milvus-minio`, `milvus-standalone`），所有服务进入健康运行状态。
- [x] 完成数据库端口映射：PostgreSQL(5432), Neo4j(7474/7687), Milvus(19530/9091)。

### 2026-04-26 — 突破 B站 412 风控

**完成内容：** 安装 `curl_cffi` 后 `bilibili-api-python` v17.4.1 自动切换 TLS 指纹伪装客户端，成功绕过 B 站 412 WAF 拦截。
- [x] 安装 `curl-cffi>=0.15.0`，库自动注册并选择 `CurlCFFIClient`
- [x] 验证通过：视频信息、视频标签、UP 主视频列表、字幕接口均正常返回数据
- [x] 更新 `bilibili_client.py`：移除旧的 UA/Referer hack，增加 `curl_cffi` 启动检查
- [x] 更新 `pyproject.toml`：添加 `curl-cffi` 依赖
- [x] 增加请求间隔至 2 秒防止高频触发风控（连续请求仍可能 412）

### 2026-04-25 — 环境配置与 B站 API 风控排查

**完成内容：** 成功配置了 Python 3.11 conda 环境，安装了所有依赖，并排查了数据采集时的 B 站 412 拦截问题。
- [x] 完成了 `.env` 文件的创建并填入真实用户 B站 Cookie。
- [x] 在 `py311` conda 环境中完成了项目的所有基础依赖和开发依赖安装。
- [x] 编写了 `scripts/demo_bilibili.py` 独立测试脚本。
- [x] 确诊 `bilibili-api-python` 库因 TLS 指纹或缺少 `acw_tc` 被 B站 WAF 全面拦截（返回 412）。

### 2026-04-24 — 项目骨架搭建（对话 14fa3b77）

**完成内容：** 从零搭建了完整的项目代码框架，包含 8 个核心模块共 24 个文件。

#### ✅ Step 1: 项目基础设施
- [x] `pyproject.toml` — 依赖管理（bilibili-api, whisper, openai, neo4j, pymilvus, mcp 等）
- [x] `.env.example` — 环境变量模板（B站凭据/LLM API/数据库连接）
- [x] `.gitignore` — Git 忽略配置
- [x] `README.md` — 项目说明与快速开始指南
- [x] `config/settings.py` — Pydantic Settings 统一配置管理（子配置: Bilibili/LLM/Neo4j/PG/Milvus/Whisper）

#### ✅ Step 2: 数据模型定义
- [x] `src/models/entities.py` — 10+ Pydantic 模型
  - 核心实体: `Restaurant`, `Dish`, `UPMaster`, `Review`, `AspectReview`
  - 枚举: `Sentiment`(推荐/一般/踩雷), `CuisineType`
  - LLM中间模型: `ExtractedDish`, `ExtractedRestaurant`, `ExtractionResult`
  - Pipeline模型: `VideoInfo`, `SubtitleSegment`, `TranscriptResult`, `PipelineTask`

#### ✅ Step 3: B站数据采集模块
- [x] `src/collector/bilibili_client.py` — B站API封装（获取UP主视频列表、视频详情、标签、字幕信息），带 tenacity 重试
- [x] `src/collector/video_filter.py` — 探店视频智能筛选（关键词评分系统，正向/排除关键词，城市bonus，时长惩罚）
- [x] `src/collector/subtitle_extractor.py` — 字幕提取（CC字幕 > AI字幕 优先级选择，httpx下载，本地JSON缓存）

#### ✅ Step 4: ASR 转写模块
- [x] `src/transcriber/whisper_transcriber.py` — Whisper 集成（延迟加载模型，带时间戳输出，结果缓存）

#### ✅ Step 5: LLM 信息抽取模块
- [x] `src/extractor/prompts.py` — 3套Prompt模板（信息提取/查询改写/行程规划），PromptBuilder 工具类
- [x] `src/extractor/llm_client.py` — OpenAI兼容API客户端（chat + embedding + batch embedding），extract_from_transcript 高级方法
- [x] `src/extractor/schema_validator.py` — JSON提取（纯JSON/代码块/混合文本），数据清洗（verdict规范化），置信度评分

#### ✅ Step 6: 存储层
- [x] `src/storage/pg_store.py` — PostgreSQL（DDL初始化4张表+索引，asyncpg连接池，餐厅/菜品/UP主/评价 CRUD + upsert）
- [x] `src/storage/neo4j_store.py` — Neo4j 图数据库（约束初始化，MERGE节点，创建关系边，多UP主推荐查询，评价图谱查询）
- [x] `src/storage/vector_store.py` — Milvus 向量数据库（HNSW索引，COSINE相似度，元数据过滤，语义检索）

#### ✅ Step 7: Pipeline 编排
- [x] `src/pipeline/runner.py` — 端到端Pipeline（视频采集→筛选→字幕→LLM抽取→三库存储），运行报告JSON输出
- [x] `scripts/run_pipeline.py` — Click CLI入口（--up-mid / --city / --limit / --skip-store）

#### ✅ Step 8: MCP Server
- [x] `src/mcp_server/server.py` — 3个核心MCP Tool:
  - `search_dish_by_semantic_review` — 语义搜索菜品（向量检索+元数据过滤）
  - `get_restaurant_detailed_review` — 餐厅详细评价（PG+Neo4j联合查询）
  - `generate_food_tour_itinerary` — 美食行程规划（LLM生成）

#### ✅ 测试
- [x] `tests/test_collector.py` — VideoFilter 单元测试（5个用例）
- [x] `tests/test_extractor.py` — SchemaValidator 单元测试（6个用例）

---

## 📂 当前项目结构

```
foodrecomandation/
├── config/
│   ├── __init__.py
│   └── settings.py                # Pydantic Settings 配置
├── src/
│   ├── models/
│   │   └── entities.py            # 所有数据模型
│   ├── collector/
│   │   ├── bilibili_client.py     # B站API
│   │   ├── video_filter.py        # 视频筛选
│   │   └── subtitle_extractor.py  # 字幕提取
│   ├── transcriber/
│   │   └── whisper_transcriber.py # ASR转写
│   ├── extractor/
│   │   ├── prompts.py             # Prompt模板
│   │   ├── llm_client.py          # LLM客户端（DeepSeek + OpenAI 双API）
│   │   └── schema_validator.py    # Schema校验
│   ├── geocode/
│   │   └── amap_client.py         # 高德地图 POI 搜索 & 地理编码
│   ├── storage/
│   │   ├── pg_store.py            # PostgreSQL（psycopg3）
│   │   ├── neo4j_store.py         # Neo4j
│   │   └── vector_store.py        # Milvus
│   ├── pipeline/
│   │   └── runner.py              # Pipeline编排（含地理编码步骤）
│   └── mcp_server/
│       └── server.py              # MCP Server（3个Tool）
├── scripts/
│   ├── run_pipeline.py            # CLI入口
│   └── demo_bilibili.py           # B站API独立测试脚本
├── tests/
│   ├── test_collector.py
│   └── test_extractor.py
├── data/
│   ├── subtitles/                 # 字幕缓存（11个视频）
│   ├── extractions/               # Pipeline 运行报告
│   └── pipeline.log               # 运行日志
├── docker-compose.yml             # PG + Neo4j + Milvus 一键部署
├── pyproject.toml
├── .env.example
├── .gitignore
├── README.md
├── proposal.md                    # 项目计划书
├── PORTFOLIO.md                   # 个人作品集
├── SUMMARY.md                     # 一页纸项目概要
├── presentation.html              # 交互式演示页
└── portfolio_pdf.html             # PDF 打印版作品集
```

---

## ⏭️ 待完成工作（优先级排序）

### 🔴 高优先级（下一步）
- [x] 创建虚拟环境并安装依赖 (`pip install -e ".[dev]"`) — *已在 conda py311 环境完成*
- [x] 配置 `.env` 文件（填入真实的B站凭据） — *已完成*
- [x] 绕过 B 站 412 风控 — *已通过安装 `curl-cffi` 解决*
- [x] 运行单元测试验证核心逻辑 (`pytest tests/ -v`) — *11/11 通过*
- [x] 部署本地数据库（Docker Compose: PostgreSQL + Neo4j + Milvus）
- [x] **配置 LLM API Key** — *已完成：DeepSeek (LLM) + OpenAI (Embedding) 双 API*
- [x] **端到端 Pipeline 验证** — *已完成：--skip-store 模式跑通*
- [x] **完整 Pipeline 含数据库存储** — *已完成：2/2 视频成功写入 PG + Neo4j + Milvus*
- [x] ~~修复 Windows 兼容性：pg_store 从 asyncpg 迁移到 psycopg3~~ — *已完成（05-18）*
- [x] **集成高德地理编码** — *已完成（05-18），餐厅自动补全地址/经纬度*
- [ ] **修复高德 POI 误匹配**：增加匹配置信度校验（名称相似度 + 城市/商圈约束），误配时降级为"仅城市级"坐标

### 🟡 中优先级
- [ ] 选定 3-5 个目标UP主进行试采集
- [x] 端到端 Pipeline 调试（先用 `--skip-store` 模式） — *已完成*
- [ ] LLM 提取 Prompt 调优（基于实际字幕数据）
- [ ] 数据质量评估（准确率目标 ≥ 85%）

### 🟢 低优先级（Phase 2）
- [ ] 编写集成测试
- [x] 添加 Docker Compose 配置文件
- [ ] 实现 Airflow/Celery 定时任务
- [ ] 扩展 MCP Tool（compare_restaurants, trending_restaurants 等）
- [ ] 性能优化（批量处理、并发控制）

---

## 🔧 技术债务 & 已知问题
- ~~**已解决**：B站 412 风控 — 安装 `curl-cffi` 后自动使用 `CurlCFFIClient` 绕过 TLS 指纹检测~~
- ~~**已解决**：`subtitle_extractor.py` 的 `_get_subtitle_list` 缺少 cid 参数导致字幕提取失败~~
- ~~**已解决**：asyncpg 在 Windows 下连接 PostgreSQL 失败 — 已迁移到 psycopg3~~
- ~~**已解决**：本地 Windows PostgreSQL 与 Docker PostgreSQL 端口 5432 冲突 — 改用 5433~~
- **新发现（05-18）**：高德 POI 匹配可能误配（例："山居满陇" → "北京绿岗山居农家院"），错误坐标会污染地理数据，需加置信度校验
- **注意**：高频请求（连续多个 UP 主无间隔）仍可能触发 412，需保持 ≥2s 请求间隔
- **注意**：部分 UP 主视频列表可能返回空（隐私设置或 API 限制），需要在 Pipeline 中做容错处理
- `neo4j_store.py` 中的 MERGE 关系查询在大数据量下可能需要优化索引
- `vector_store.py` 的 EMBEDDING_DIM 硬编码为 1536，如切换 embedding 模型需调整
- Pipeline 缺少断点续传机制（中断后需重新处理）
- MCP Server 的 startup 中数据库连接失败只是 warning，生产环境应改为 fatal

---

## 📌 重要设计决策记录
1. **三库架构**: PostgreSQL(结构化元数据) + Neo4j(关系图谱) + Milvus(向量检索)
2. **字幕优先级**: CC字幕 > AI自动字幕 > Whisper ASR
3. **LLM输出校验**: 支持纯JSON / ```json代码块 / 混合文本三种格式的提取
4. **Verdict规范化**: 非标准评价（如"好吃推荐""太差了"）自动映射为 推荐/一般/踩雷
5. **MCP协议**: 使用 mcp-python 官方SDK，通过 stdio_server 通信
6. **双API架构**: DeepSeek (`deepseek-chat`) 做 LLM 抽取 + OpenAI (`text-embedding-3-small`) 做 Embedding，成本与效果平衡
7. **地理编码**: 高德 POI 搜索补全餐厅地址/经纬度（餐厅名+城市 → 标准化坐标），为行程规划 Tool 提供地理数据
8. **PG 驱动**: asyncpg → psycopg3（Windows 兼容性），连接端口 5433 避开本地 PG 冲突
