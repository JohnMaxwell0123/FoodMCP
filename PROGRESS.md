# 📋 项目进度追踪

> **项目名称：** B站探店视频深度解析与 Agent MCP 服务
> **最后更新：** 2026-09-09
> **当前阶段：** Phase 1 — MVP 概念验证（已完成）→ GitHub 开源发布
> **整体进度：** ██████████ 100%（全链路打通，三库存储 + 地理编码，已推送到 GitHub 开源）

---

## 🏗️ 已完成的工作

### 2026-09-09 — MCP 核心工具体系进阶扩展 (MCP Tool Suite Expansion)

**完成内容：** 将 MCP Tool 扩充至 5 大工业级工具，实现跨店横向好评避雷对比、UP 主口味画像与排雷苛刻度分析、高德坐标感知的聚类行程规划，全套单元测试扩充至 **37/37 全部通过**。
- [x] **餐厅横向多维对比工具 (`compare_restaurants`)**：
  - 支持传入两家餐厅与目标城市进行多维深度 PK；
  - 聚合 UP 主探访列表、推荐/一般/踩雷分布、计算**好评率与避雷率**；
  - 自动提炼两家餐厅各自的招牌推荐菜（红榜）与踩雷菜品（黑榜），并给出高好评率优先与低避雷率安全选择建议。
- [x] **UP 主探店与口味画像工具 (`get_up_taste_profile`)**：
  - 联表查询 UP 主历史探店餐厅、评价记录与 Neo4j 评价图谱；
  - 统计探店城市足迹与常探**菜系偏好分布及占比**；
  - 依据其历史踩雷率量化评估其**排雷严苛度等级**（如“极高（毒舌/真实/排雷专家）”、“温和”等）；
  - 输出该 UP 主最具共识的盛赞必吃菜与公开踩雷菜品名录（附 UP 主原话语录）。
- [x] **行程规划工具地理感知升级 (`generate_food_tour_itinerary`)**：
  - 整合高德 POI 经纬度坐标（`latitude`, `longitude`）、行政区划及 `geo_verified` 核验标识；
  - 升级 Prompt 路线聚类指引：严格遵循就近聚类原则（同区或相邻街区餐厅编排进同一时段），彻底杜绝跨城两端折返跑。
- [x] **生产级启动容错与强校验 (`startup`)**：
  - 引入 `MCP_STRICT_STORAGE` 环境变量支持：默认环境优雅降级运行，生产严苛模式下若存储连接失败则抛出 `RuntimeError` 快速失败。
- [x] **单元测试与 CI 覆盖**：
  - 新增 `tests/test_mcp.py`（6 个测试），全面覆盖 5 大工具注册、餐厅 PK 逻辑、UP 主画像计算、高德经纬度注入与分发；
  - 全套单元测试从 31/31 扩充至 **37/37 全部通过**。

### 2026-09-09 — 生产级增量调度器与断点续传系统建设 (Pipeline Task State Machine & Resumption)

**完成内容：** 建立基于 PostgreSQL 的视频级 Pipeline 任务状态机，实现历史落盘视频秒级断点跳过、全生命周期阶段追踪、API 限流指数退避重试与 CLI 状态监控看板，全套单元测试扩充至 **31/31 全部通过**。
- [x] **任务生命周期状态机模型升级 (`src/models/entities.py`)**：
  - 新增 `TaskStatus(str, Enum)`：涵盖 `PENDING`, `PROCESSING`, `SUBTITLE_EXTRACTED`, `EXTRACTED`, `STORED`, `SKIPPED`, `FAILED` 状态；
  - 增强 `PipelineTask` 模型：支持由 `VideoInfo` 自动推导 `bvid`, `up_mid`, `title`，自动注入 `updated_at`，并实现字符串状态自动规范化校验器。
- [x] **存储层任务状态机持久化 (`src/storage/pg_store.py`)**：
  - `INIT_SQL` 与增量迁移增加 `pipeline_tasks` 表，记录阶段、重试次数、字幕来源、实体统计与错误信息；
  - 实现 `upsert_pipeline_task`（基于 `bvid` 冲突更新）、`get_pipeline_task` 与 `list_pipeline_tasks`；
  - 实现 `get_completed_bvids`：$O(1)$ 批量获取已完成视频，支撑极速断点续传过滤。
- [x] **调度器断点续传与弹性重试流转 (`src/pipeline/runner.py`)**：
  - 默认开启 `resume=True`，在批量处理前加载 `completed_bvids` 并将已存储视频标记为 `SKIPPED`，杜绝重复抽取与 Token 浪费；
  - 细粒度持久化 `init` -> `subtitle` -> `llm` -> `storage` -> `completed` 阶段流转；
  - 针对瞬时网络抖动和 API RateLimit（B 站 412 / LLM 429）实现指数退避重试保护（1s -> 2s -> 4s）；
  - `_save_report` 扩充输出状态机字段与实体计数。
- [x] **CLI 命令与状态监控面板升级 (`scripts/run_pipeline.py`)**：
  - 增加 `--resume / --no-resume`、`--max-retries` 选项；
  - 增加 `--status` 开关：直接查询并打印指定 UP 主的历史任务分布表格面板；
  - 终端运行摘要区分 `[STORED]`, `[SKIPPED]`, `[FAILED]` 徽标。
- [x] **单元测试全量通过**：
  - 新增 `tests/test_pipeline_state.py`（6 个用例），测试模型自动推导、状态规范化、SQL 构造、断点跳过与异常捕获；
  - 全套单元测试从 25/25 扩充至 **31/31 全部通过**。

### 2026-09-09 — 工业级 LLM 抽取 Eval 评测体系与黄金测试集建设

**完成内容：** 建立标准化 LLM 抽取 Eval 评测框架与黄金基准数据集，提供自动化 NER F1、情感混淆矩阵、原文引用保真度（Faithfulness）与幻觉率打分，全套单元测试扩充至 25/25 全部通过。
- [x] **黄金基准数据集沉淀**：
  - 打造 `data/eval/golden_dataset.json`，涵盖单店深度探店、多店扫街、暗讽踩雷反转、地域菜系细分等 8 类高难度探店切片样本；
  - 精标标准餐厅、菜品、正负面 Verdict 倾向与原文字幕引用片段。
- [x] **四维核心评测引擎实现 (`src/eval/evaluator.py`)**：
  - **实体识别指标 (NER)**：基于 RapidFuzz 模糊匹配计算餐厅与菜品的 Precision、Recall 和 F1-Score；
  - **情感三分类指标**：计算整体准确率 Accuracy、3x3 混淆矩阵以及 Macro-F1；专门建立**“踩雷误报为推荐率 (False Recommendation Rate)”**高危缺陷监控；
  - **保真度与抗幻觉率 (Faithfulness)**：基于字符连续性与模糊滑动检测 UP 主原话是否存在于原文字幕中，精准捕获 LLM 凭空捏造原话的幻觉；
  - **Schema 完备率**：统计 JSON 一次性合规解析率。
- [x] **评测 CLI 工具与自动报告生成 (`scripts/run_eval.py`)**：
  - 支持调用真实大模型（如 `deepseek-chat`）评测，支持 `--mock` 离线快速验证；
  - 基于 Rich 打造专业终端图表面板（综合指标表 + 混淆矩阵表）；
  - 自动输出 Markdown (`.md`) 与 JSON (`.json`) 格式的评测基准报告，适配 CI/CD 与开源 Showcase。
- [x] **单元测试与 CI 覆盖**：
  - 新增 `tests/test_eval.py`（5 个用例），测试完美匹配、漏检误检、情感错判、幻觉捕获与报告导出；
  - 全套单元测试从 20/20 扩充至 **25/25 全部通过**。

### 2026-09-09 — 基础筑基与数据治理（高德置信度门禁 + 实体去重聚合）

**完成内容：** 解决高德 POI 误匹配脏数据污染、实体菜品/餐厅去重断裂导致图谱共识失效、长文本字幕硬截断问题，全套单元测试扩充至 20/20 全部通过。
- [x] **高德 POI 置信度校验与优雅降级**：
  - 引入 `RapidFuzz` 计算文本相似度（Token Set Ratio / Partial Ratio / Ratio）；
  - 引入城市强约束校验（跨城施加 $-0.50$ 重罚，同城加成）与餐饮分类加成；
  - 建立三级置信度门禁：$\ge 0.70$ 高置信度采纳，$< 0.45$ 坚决拒纳错误 POI 并降级为城市中心坐标，彻底根除“山居满陇”匹配为农家院问题；
  - 实体模型与 PG 表结构扩充 `geo_verified` 标识。
- [x] **实体去重与知识图谱拓扑聚合**：
  - `dishes` 表新增联合唯一键约束 `CONSTRAINT uq_dishes_restaurant_name UNIQUE (restaurant_id, name)`；
  - 重写 `upsert_dish`：通过 `ON CONFLICT (restaurant_id, name) DO UPDATE` 平滑累加并平滑计算多 UP 主的情感分，`RETURNING id` 确保返回持久化唯一 ID；
  - 重构 `find_restaurant_by_name`：实现“同城精确 → 全局精确 → 同城模糊 → 全局模糊”的多级消歧匹配；
  - 修复 `runner.py`：统一使用持久化 ID 连接评价与 Neo4j 图节点，图谱真正具备多 UP 主共识能力。
- [x] **长文本处理能力扩充**：Prompt 字幕截断保护上限从 8,000 字符提升至 32,000 字符，释放长视频上下文。
- [x] **依赖与测试规范化**：
  - `pyproject.toml` 补齐 `psycopg[binary]>=3.1.0` 与 `rapidfuzz>=3.0.0`；
  - 新增 `tests/test_amap.py` 与 `tests/test_storage_dedup.py`，全套测试从 11/11 扩充至 **20/20 全部通过**。

### 2026-09-09 — GitHub 开源发布与规范化就绪

**完成内容：** 完成项目开源安全审计、配置规范化、旗舰级 README 打造并成功上线 GitHub。
- [x] **开源安全审计**：更新 `.gitignore`，隔离 `.env`、`data/`、`scratch/`、临时大文件与日志，零泄露真实凭据
- [x] **配置模版对齐**：同步 `.env.example`，补充 DeepSeek + OpenAI 双 API、高德地图 Key 与 PostgreSQL 5433 端口配置
- [x] **开源许可**：创建正式 MIT `LICENSE`（Copyright 2026 John Maxwell）
- [x] **开源旗舰级 README**：全新打造涵盖痛点四象限、竞品对比、系统全景 Mermaid 架构图、5 大核心攻坚亮点、MCP 配置与设计文档导航的顶级门面
- [x] **自动化测试验证**：`py311` 环境下 11/11 单元测试全部通过
- [x] **GitHub 仓库建立与推送**：成功创建并推送到官方仓库 [JohnMaxwell0123/FoodMCP](https://github.com/JohnMaxwell0123/FoodMCP)

### 2026-07-22 — 产品设计与架构材料整理

**完成内容：** 完成全套产品设计白皮书、一页纸架构概要与交互式演示材料。
- [x] `PORTFOLIO.md` — 产品设计白皮书（产品思维 + 架构设计 + 商业模式）
- [x] `SUMMARY.md` — 一页纸项目架构概要
- [x] `presentation.html` — 交互式产品演示页
- [x] `portfolio_pdf.html` — 打印版设计白皮书源文件

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
├── PORTFOLIO.md                   # 产品设计白皮书
├── SUMMARY.md                     # 一页纸项目概要
├── presentation.html              # 交互式演示页
└── portfolio_pdf.html             # 打印版设计白皮书
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
- [x] **修复高德 POI 误匹配** — *已完成（09-09），RapidFuzz 相似度核验 + 城市强约束 + 三级门禁与降级*

### 🟡 中优先级
- [ ] 选定 3-5 个目标UP主进行试采集
- [x] 端到端 Pipeline 调试（先用 `--skip-store` 模式） — *已完成*
- [x] 构建 Ground Truth 黄金测试集与 LLM 自动化 Eval 评测脚本 — *已完成（09-09）*
- [ ] LLM 提取 Prompt 调优（基于实际字幕数据）
- [x] 实现 Pipeline 任务持久化与断点续传机制 (--resume) — *已完成（09-09）*

### 🟢 低优先级（Phase 2）
- [ ] 编写集成测试
- [x] 添加 Docker Compose 配置文件
- [ ] 实现 Airflow/Celery 定时任务
- [x] 扩展 MCP Tool（compare_restaurants, get_up_taste_profile 等） — *已完成（09-09）*
- [ ] 补齐 B 站视频音频流下载器与 Whisper 转写闭环

---

## 🔧 技术债务 & 已知问题
- ~~**已解决**：B站 412 风控 — 安装 `curl-cffi` 后自动使用 `CurlCFFIClient` 绕过 TLS 指纹检测~~
- ~~**已解决**：`subtitle_extractor.py` 的 `_get_subtitle_list` 缺少 cid 参数导致字幕提取失败~~
- ~~**已解决**：asyncpg 在 Windows 下连接 PostgreSQL 失败 — 已迁移到 psycopg3 并补充 pyproject.toml 声明~~
- ~~**已解决**：本地 Windows PostgreSQL 与 Docker PostgreSQL 端口 5432 冲突 — 改用 5433~~
- ~~**已解决**：高德 POI 匹配误配（"山居满陇" → 农家院）— 已引入 RapidFuzz 相似度门禁 + 城市强约束校验 + 城市中心优雅降级~~
- ~~**已解决**：菜品与餐厅去重断裂 — `dishes` 表建立 `(restaurant_id, name)` 联合唯一索引与评分聚合，`runner.py` 全链路统一使用持久化 ID~~
- ~~**已解决**：长视频字幕 8000 字符硬截断 — 已提升至 32000 字符保护上限~~
- ~~**已解决**：`vector_store.py` 的 EMBEDDING_DIM 硬编码为 1536 — 已在 settings.embedding.dimension 中动态读取配置~~
- ~~**已解决**：Pipeline 缺少断点续传机制 — 已实现 pipeline_tasks 状态持久化、--resume 断点跳过与指数退避重试~~
- ~~**已解决**：MCP Server 的 startup 中数据库连接失败只是 warning — 已引入 MCP_STRICT_STORAGE 强校验环境变量开关~~
- **注意**：高频请求（连续多个 UP 主无间隔）仍可能触发 412，需保持 ≥2s 请求间隔
- **注意**：部分 UP 主视频列表可能返回空（隐私设置或 API 限制），需要在 Pipeline 中做容错处理
- `neo4j_store.py` 中的 MERGE 关系查询在大数据量下可能需要优化索引

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
9. **任务状态机与断点续传**: PostgreSQL `pipeline_tasks` 表记录阶段与重试，默认 `--resume` 秒级跳过已落盘视频，并在网络抖动/限流时启用指数退避重试保护。
10. **MCP 核心工具体系**: 扩充至 5 大工业级 Tool，支持跨店横向评价对比、UP 主口味偏好与排雷严苛度画像、以及基于高德真实 POI 坐标就近聚类规划的美食路线。
