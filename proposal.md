# 🍽️ B站探店视频深度解析与 Agent MCP 服务 — 完整计划书

> **版本：** v1.0 | **日期：** 2026年4月 | **状态：** 规划阶段

---

## 一、执行摘要 (Executive Summary)

本项目旨在构建**首个基于大语言模型（LLM）和 Model Context Protocol（MCP）的"视频级"餐饮点评聚合与检索引擎**。

通过自动化解析B站探店UP主的视频内容，我们将非结构化的视频信息转化为 `城市 → 餐厅 → 菜品 → 评价 → 情绪` 的多维结构化数据，并以标准 MCP 协议对外提供服务，让任何 AI Agent 都能像资深吃货一样精准推荐餐厅与菜品。

### 核心价值主张

| 维度 | 传统点评平台 | 现有B站小程序 | **本项目** |
|------|------------|-------------|-----------|
| 数据粒度 | 餐厅级评分 | 餐厅级分类 | **菜品级语义评价** |
| 搜索能力 | 关键词/标签 | 城市/UP主筛选 | **自然语言语义检索** |
| 评价来源 | 匿名用户 | UP主推荐 | **UP主原话+情绪分析** |
| AI集成 | 无 | 无 | **标准MCP协议接口** |
| 负面信息 | 部分展示 | 通常不体现 | **完整保留踩雷信息** |

---

## 二、市场分析与痛点洞察

### 2.1 市场背景

- B站美食探店类视频年增长率超过 40%，头部UP主单条视频播放量可达百万级
- 用户在选择餐厅时，越来越依赖真实体验视频而非传统图文点评
- 然而视频内容的检索效率极低——用户常常需要看完完整视频才能获得关键信息

### 2.2 现有方案的痛点

#### 痛点一：维度单一，菜品信息缺失

现有小程序仅将数据组织到"餐厅"级别。用户想了解"这家店的水煮鱼到底如何"时，必须自行翻看完整视频。

#### 痛点二：搜索僵化，无法理解复杂意图

当前只支持城市、UP主等简单分类筛选。面对用户的真实需求——

> *"找一家UP主评价锅气很足、且特别强调大肠处理得很干净的鲁菜馆"*

——现有系统完全无法处理。

#### 痛点三：负面评价被系统性忽略

UP主在视频中明确说出"这道爆炒腰花火候欠佳"，但在现有小程序中通常无法体现。这导致用户参考了推荐列表后，依然可能踩雷。

#### 痛点四：信息碎片化

同一家餐厅可能被多个UP主评测，但用户无法快速获得综合评价。信息散落在不同视频中，形成严重的信息孤岛。

### 2.3 差异化优势与护城河

1. **多维细粒度数据建模**：`[城市] - [餐厅] - [菜品] - [UP主评价] - [情绪色彩]` 的深度结构化
2. **语义级检索能力**：基于向量数据库和LLM的模糊语义搜索
3. **完整信息保留**：好评与差评同等权重保留，构建真实可信的评价体系
4. **标准化AI接口**：原生MCP协议支持，即插即用
5. **数据壁垒**：随时间积累的深度结构化数据，构成天然的竞争壁垒

---

## 三、产品架构设计

### 3.1 系统总体架构

```
┌──────────────────────────────────────────────────────────┐
│                    AI Agent 层                            │
│  Claude / ChatGPT / 自研Agent / 第三方开发者               │
└──────────────┬───────────────────────────────────────────┘
               │ MCP Protocol (JSON-RPC)
┌──────────────▼───────────────────────────────────────────┐
│              MCP Server (Python)                         │
│  ┌─────────────┐ ┌─────────────┐ ┌───────────────────┐  │
│  │ search_dish  │ │ get_review  │ │ generate_itinerary│  │
│  │ _by_semantic │ │ _detailed   │ │                   │  │
│  └──────┬──────┘ └──────┬──────┘ └────────┬──────────┘  │
└─────────┼───────────────┼─────────────────┼──────────────┘
          │               │                 │
┌─────────▼───────────────▼─────────────────▼──────────────┐
│                    数据服务层                              │
│  ┌────────────┐  ┌─────────────┐  ┌───────────────────┐  │
│  │ Neo4j      │  │ Milvus/     │  │ PostgreSQL        │  │
│  │ 图数据库    │  │ Qdrant      │  │ 结构化存储         │  │
│  │ (关系网络)  │  │ (向量检索)   │  │ (元数据)          │  │
│  └────────────┘  └─────────────┘  └───────────────────┘  │
└──────────────────────────────────────────────────────────┘
          ▲               ▲                 ▲
          │               │                 │
┌─────────┴───────────────┴─────────────────┴──────────────┐
│                 数据处理流水线 (Pipeline)                   │
│  视频采集 → ASR转写 → LLM信息抽取 → 数据清洗 → 入库       │
└──────────────────────────────────────────────────────────┘
```

### 3.2 数据模型设计

#### 核心实体

```
Restaurant (餐厅)
├── id: UUID
├── name: String          # 餐厅名称
├── city: String          # 所在城市
├── district: String      # 所在区域
├── address: String       # 详细地址
├── cuisine_type: String  # 菜系分类
├── price_range: String   # 价格区间
├── geo_location: Point   # 经纬度坐标
└── tags: [String]        # 标签 (老字号/网红/苍蝇馆子...)

Dish (菜品)
├── id: UUID
├── name: String          # 菜品名称
├── category: String      # 分类 (凉菜/热菜/主食/甜品...)
├── price: Float          # 价格
├── restaurant_id: FK     # 所属餐厅
└── avg_sentiment: Float  # 综合情绪分 (-1.0 ~ 1.0)

UPMaster (UP主)
├── id: UUID
├── bilibili_uid: String  # B站UID
├── name: String          # UP主名称
├── follower_count: Int   # 粉丝数
├── style_tags: [String]  # 风格标签 (专业/平价/高端...)
└── credibility_score: Float # 可信度评分

Review (评价)
├── id: UUID
├── up_master_id: FK      # 评价者
├── dish_id: FK           # 评价菜品
├── restaurant_id: FK     # 评价餐厅
├── video_bvid: String    # 来源视频BV号
├── timestamp: String     # 视频中的时间戳
├── raw_text: Text        # UP主原话
├── sentiment: Enum       # 推荐/一般/踩雷
├── sentiment_score: Float # 情绪分值
├── aspects: JSON         # 细分维度评价
│   ├── taste: String     # 口味描述
│   ├── texture: String   # 口感描述
│   ├── portion: String   # 分量描述
│   ├── presentation: String # 卖相描述
│   └── value: String     # 性价比描述
└── created_at: DateTime
```

#### 图数据库关系模型 (Neo4j)

```
(UP主)-[:探访{date, video_bvid}]->(餐厅)
(餐厅)-[:提供]->(菜品)
(UP主)-[:评价{sentiment, raw_text}]->(菜品)
(餐厅)-[:位于]->(城市/区域)
(菜品)-[:属于]->(菜系)
```

---

## 四、MCP 服务核心功能设计

### 4.1 Tool 1: `search_dish_by_semantic_review`

**功能：** 按评价语义搜索菜品

```json
{
  "name": "search_dish_by_semantic_review",
  "description": "根据自然语言描述搜索符合条件的菜品及其UP主评价",
  "inputSchema": {
    "type": "object",
    "properties": {
      "city": {
        "type": "string",
        "description": "目标城市"
      },
      "query": {
        "type": "string",
        "description": "自然语言描述，如：红烧肉要肥而不腻、锅气足的炒菜"
      },
      "sentiment_filter": {
        "type": "string",
        "enum": ["all", "recommended", "average", "avoid"],
        "description": "评价倾向筛选"
      },
      "up_master_filter": {
        "type": "array",
        "items": {"type": "string"},
        "description": "限定特定UP主的评价"
      },
      "top_k": {
        "type": "integer",
        "default": 10,
        "description": "返回结果数量"
      }
    },
    "required": ["city", "query"]
  }
}
```

**调用示例：**

```
用户：找一家北京的鲁菜馆，要锅气足，大肠处理得干净的那种

Agent调用：search_dish_by_semantic_review(
  city="北京",
  query="锅气足 大肠处理干净 鲁菜",
  sentiment_filter="recommended"
)
```

### 4.2 Tool 2: `get_restaurant_detailed_review`

**功能：** 获取餐厅的多UP主深度综合点评

```json
{
  "name": "get_restaurant_detailed_review",
  "description": "获取指定餐厅的所有UP主评价汇总，含菜品级别的好评/差评统计",
  "inputSchema": {
    "type": "object",
    "properties": {
      "restaurant_name": {
        "type": "string",
        "description": "餐厅名称"
      },
      "city": {
        "type": "string",
        "description": "所在城市（用于消歧义）"
      }
    },
    "required": ["restaurant_name"]
  }
}
```

**返回示例：**

```json
{
  "restaurant": "四季民福烤鸭店(故宫店)",
  "city": "北京",
  "cuisine": "北京烤鸭/京菜",
  "overall_score": 4.2,
  "review_count": 5,
  "up_masters_visited": ["UP主A", "UP主B", "UP主C"],
  "dish_reviews": [
    {
      "dish": "招牌烤鸭",
      "avg_sentiment": 0.85,
      "reviews": [
        {"up": "UP主A", "verdict": "推荐", "quote": "皮脆肉嫩，枣木烤制香味十足"},
        {"up": "UP主B", "verdict": "推荐", "quote": "片鸭师傅刀工很好，皮肉分明"}
      ]
    },
    {
      "dish": "芥末鸭掌",
      "avg_sentiment": 0.3,
      "reviews": [
        {"up": "UP主A", "verdict": "一般", "quote": "芥末味太冲，掩盖了鸭掌本味"},
        {"up": "UP主C", "verdict": "踩雷", "quote": "口感偏硬，不推荐"}
      ]
    }
  ]
}
```

### 4.3 Tool 3: `generate_food_tour_itinerary`

**功能：** 基于UP主评价和地理信息生成美食打卡路线

```json
{
  "name": "generate_food_tour_itinerary",
  "description": "结合UP主评价和地理位置，生成结构化美食行程",
  "inputSchema": {
    "type": "object",
    "properties": {
      "city": {"type": "string"},
      "days": {"type": "integer", "default": 1},
      "preferences": {
        "type": "string",
        "description": "偏好描述，如：跟着老饭骨口味走、高性价比、重辣"
      },
      "budget": {
        "type": "string",
        "enum": ["budget", "moderate", "premium"],
        "description": "预算档次"
      },
      "must_include_dishes": {
        "type": "array",
        "items": {"type": "string"},
        "description": "必须包含的菜品类型"
      }
    },
    "required": ["city"]
  }
}
```

### 4.4 扩展 Tools（后续迭代）

| Tool 名称 | 功能描述 |
|-----------|---------|
| `compare_restaurants` | 对比两家餐厅在同类菜品上的UP主评价 |
| `get_up_master_profile` | 获取UP主的探店风格画像和历史推荐 |
| `trending_restaurants` | 获取近期UP主高频推荐的热门餐厅 |
| `dish_controversy_check` | 检查某道菜是否存在UP主评价分歧 |

---

## 五、技术实现详细方案

### 5.1 数据采集与预处理

#### 5.1.1 视频列表采集

```python
# 技术方案要点
- 使用 bilibili-api-python 库获取UP主视频列表
- 解析视频标题、描述、标签，初步筛选探店类视频
- 关键词过滤：探店/测评/美食/试吃/打卡 等
- 采集频率：每日增量更新
```

#### 5.1.2 字幕与语音提取

```
优先级策略：
1. CC字幕（B站官方字幕）→ 直接提取，准确率最高
2. AI自动字幕 → B站已有的AI字幕，可直接获取
3. ASR转写 → 无字幕视频，使用 Whisper large-v3 模型
   - 部署方案：本地GPU / 云端API (如阿里云ASR)
   - 输出格式：带时间戳的SRT/JSON
```

#### 5.1.3 视觉辅助信息（可选增强）

- 视频关键帧提取：识别菜品画面
- OCR识别：提取视频中出现的菜单、价格信息
- 菜品图像识别：辅助确认菜品名称

### 5.2 LLM 信息抽取流水线

#### 5.2.1 Prompt Engineering 方案

```markdown
## System Prompt（核心提取指令）

你是一个专业的美食视频分析师。请仔细阅读以下B站探店视频的字幕文本，
从中提取结构化的餐厅和菜品评价信息。

### 提取要求：
1. 识别视频中提到的所有餐厅（可能有多家）
2. 提取每家餐厅中被评价的每道菜品
3. 判断UP主对每道菜品的态度：推荐/一般/踩雷
4. 保留UP主的原话作为评价依据
5. 提取价格、地址等元信息（如有提及）

### 输出格式：
{
  "restaurants": [{
    "name": "餐厅名",
    "location": "地址/区域",
    "cuisine_type": "菜系",
    "dishes": [{
      "name": "菜品名",
      "price": "价格（如有）",
      "verdict": "推荐/一般/踩雷",
      "aspects": {
        "taste": "口味评价",
        "texture": "口感评价",
        "portion": "分量评价",
        "presentation": "卖相评价",
        "value": "性价比评价"
      },
      "original_quote": "UP主原话",
      "timestamp": "大致时间段"
    }],
    "overall_impression": "对餐厅整体评价"
  }]
}
```

#### 5.2.2 模型选择策略

| 场景 | 推荐模型 | 理由 |
|------|---------|------|
| 高精度提取 | GPT-4o / Claude 3.5 | 理解能力强，JSON格式遵循度高 |
| 批量处理 | Qwen2.5-72B / Llama-3-70B | 开源可本地部署，成本可控 |
| 轻量快速 | Qwen2.5-7B (微调版) | 针对美食评价场景微调后性价比最优 |

#### 5.2.3 质量保障机制

- **LLM输出校验**：JSON Schema 验证 + 字段完整性检查
- **置信度评分**：对每条提取结果给出置信度，低于阈值的标记人工复核
- **交叉验证**：多模型提取结果对比，取交集作为高置信度数据
- **人工抽检**：定期随机抽样验证提取准确率，目标 >90%

### 5.3 存储与检索架构

#### 5.3.1 Neo4j 图数据库

**用途：** 存储实体关系，支持关系查询

```cypher
// 示例查询：找到所有UP主都推荐的餐厅
MATCH (u:UPMaster)-[r:REVIEWED]->(d:Dish)<-[:SERVES]-(rest:Restaurant)
WHERE r.sentiment = '推荐' AND rest.city = '北京'
WITH rest, COUNT(DISTINCT u) AS up_count
WHERE up_count >= 3
RETURN rest.name, up_count
ORDER BY up_count DESC
```

#### 5.3.2 向量数据库 (Milvus / Qdrant)

**用途：** 存储评价文本的 Embedding 向量，支持语义检索

```python
# 技术要点
- Embedding 模型：text-embedding-3-small 或 bge-large-zh-v1.5
- 向量维度：1024 / 1536
- 索引类型：HNSW（高召回率）
- 检索策略：向量相似度 + 元数据过滤（城市、菜系等）
```

#### 5.3.3 PostgreSQL

**用途：** 存储结构化元数据、用户数据、系统配置

### 5.4 MCP Server 实现

```python
# 技术栈
- 语言：Python 3.11+
- MCP SDK：mcp-python (官方SDK)
- 异步框架：asyncio
- 数据库驱动：neo4j-driver, pymilvus, asyncpg
```

---

## 六、数据安全与合规

### 6.1 数据采集合规

- 遵循B站 robots.txt 和API使用协议
- 控制采集频率，避免对B站服务器造成压力
- 仅采集公开可见的视频内容
- 不存储完整视频文件，仅保留文本信息

### 6.2 版权与内容归属

- 所有评价内容标注UP主来源和原视频链接
- 在服务中明确标注"内容来源于B站UP主视频"
- 提供UP主内容下架申请通道

### 6.3 数据存储安全

- 数据库访问权限控制
- API 调用频率限制与认证
- 定期数据备份

---

## 七、商业模式

### 7.1 To C 场景

| 模式 | 描述 | 预期收入 |
|------|------|---------|
| AI平台插件 | 作为ChatGPT/Claude的MCP工具 | 按调用次数收费 |
| 独立小程序 | 美食问答Agent小程序 | 广告+订阅制 |
| 高级功能订阅 | 个性化路线规划、UP主口味匹配 | 月费制 |

### 7.2 To B 场景

| 模式 | 描述 | 预期收入 |
|------|------|---------|
| 数据API授权 | 向大众点评/高德等平台提供视频评价摘要 | 按调用量计费 |
| 商家舆情报告 | 为餐饮商家提供UP主评价监控 | SaaS订阅 |
| 定制分析服务 | 为连锁餐饮品牌提供竞品分析 | 项目制 |

---

## 八、实施路线图

### Phase 1：MVP 概念验证（第1个月）

**目标：** 验证数据Pipeline的可行性和提取准确率

- [ ] 选定 3-5 个头部探店UP主
- [ ] 锁定 1-2 个重点城市（北京/上海）
- [ ] 完成视频采集脚本开发
- [ ] 完成 ASR 转写模块集成
- [ ] 设计并调优 LLM 提取 Prompt
- [ ] 建立数据质量评估标准
- [ ] 完成 100+ 视频的试提取，准确率 ≥ 85%

**交付物：** 可运行的数据Pipeline原型 + 质量评估报告

### Phase 2：MCP 服务构建（第2-3个月）

**目标：** 搭建完整的MCP服务并完成功能验证

- [ ] 部署 Neo4j + 向量数据库
- [ ] 实现三个核心 MCP Tools
- [ ] 编写单元测试和集成测试
- [ ] 在 Claude Desktop 中完成端到端测试
- [ ] 编写 API 文档和使用指南

**交付物：** 可对外提供服务的 MCP Server + 文档

### Phase 3：扩大规模与优化（第4-6个月）

**目标：** 扩大数据覆盖范围，优化服务质量

- [ ] 引入自动化定时任务（Airflow/Celery）
- [ ] 扩展至 5+ 城市、20+ UP主
- [ ] 优化检索精度和响应速度
- [ ] 开发用户反馈闭环机制
- [ ] 探索商业化合作

**交付物：** 生产级服务 + 商业化方案

---

## 九、风险评估与应对

| 风险 | 概率 | 影响 | 应对策略 |
|------|------|------|---------|
| B站API限制或封禁 | 中 | 高 | 多账号轮换、控制频率、备用爬虫方案 |
| LLM提取准确率不足 | 中 | 高 | 持续优化Prompt、引入微调模型、人工校验 |
| UP主内容版权争议 | 低 | 高 | 标注来源、提供下架通道、法律咨询 |
| 数据量增长带来的成本 | 中 | 中 | 分级存储、按需扩容、优化模型选择 |
| 竞品出现 | 低 | 中 | 快速迭代、深耕数据质量、建立用户粘性 |

---

## 十、团队与资源需求

### 最小可行团队

| 角色 | 人数 | 职责 |
|------|------|------|
| 全栈工程师 | 1-2 | 数据Pipeline + MCP Server开发 |
| AI/NLP工程师 | 1 | Prompt优化 + 模型微调 |
| 产品经理 | 0.5 | 需求定义 + 用户测试 |

### 基础设施预算（月度）

| 项目 | 预估费用 |
|------|---------|
| 云服务器（GPU） | ¥2,000-5,000 |
| LLM API 调用 | ¥1,000-3,000 |
| 数据库托管 | ¥500-1,500 |
| 其他工具 | ¥500 |
| **合计** | **¥4,000-10,000** |

---

## 附录

### A. 目标UP主候选列表（示例）

| UP主 | 粉丝量级 | 特点 | 覆盖城市 |
|------|---------|------|---------|
| 老饭骨 | 千万级 | 专业厨师视角 | 北京为主 |
| 盗月社 | 百万级 | 全国巡回探店 | 全国 |
| 小翔哥 | 千万级 | 生活方式类 | 多城市 |
| 特厨隋卞 | 百万级 | 专业测评 | 上海为主 |

### B. 技术栈汇总

```
数据采集：bilibili-api-python, yt-dlp, requests
语音识别：OpenAI Whisper (large-v3)
大语言模型：GPT-4o / Qwen2.5 / Llama-3
向量模型：bge-large-zh-v1.5 / text-embedding-3-small
图数据库：Neo4j 5.x
向量数据库：Milvus 2.x / Qdrant
关系数据库：PostgreSQL 16
MCP框架：mcp-python SDK
任务调度：Apache Airflow / Celery
部署：Docker + Kubernetes
监控：Prometheus + Grafana
```

### C. 参考资料

- [Model Context Protocol 官方文档](https://modelcontextprotocol.io/)
- [B站API非官方文档](https://github.com/SocialSisterYi/bilibili-API-collect)
- [OpenAI Whisper](https://github.com/openai/whisper)
- [Neo4j 图数据库](https://neo4j.com/)
- [Milvus 向量数据库](https://milvus.io/)
