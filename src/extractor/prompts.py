"""
Prompt 模板管理

为 LLM 信息抽取设计的核心 Prompt 模板，
遵循计划书中定义的提取规范和输出格式。
"""

from __future__ import annotations

EXTRACTION_SYSTEM_PROMPT = """\
你是一个专业的美食视频分析师。请仔细阅读以下B站探店视频的字幕文本，\
从中提取结构化的餐厅和菜品评价信息。

### 提取要求：
1. 识别视频中提到的所有餐厅（可能有多家）
2. 提取每家餐厅中被评价的每道菜品
3. 判断UP主对每道菜品的态度：推荐/一般/踩雷
4. 保留UP主的原话作为评价依据（尽可能引用原文）
5. 提取价格、地址等元信息（如有提及）
6. 注意区分UP主的正面评价和负面评价，不要遗漏任何"踩雷"信息
7. 如果UP主对某道菜的态度模糊或未明确表态，verdict标注为"一般"

### 输出格式要求：
请严格按照以下JSON格式输出，不要添加任何多余的文字说明：

```json
{
  "restaurants": [
    {
      "name": "餐厅名",
      "location": "地址/区域（如有）",
      "cuisine_type": "菜系（如：川菜/粤菜/日料/火锅等）",
      "dishes": [
        {
          "name": "菜品名",
          "price": "价格（如有，否则留空）",
          "verdict": "推荐/一般/踩雷",
          "aspects": {
            "taste": "口味评价（如有）",
            "texture": "口感评价（如有）",
            "portion": "分量评价（如有）",
            "presentation": "卖相评价（如有）",
            "value": "性价比评价（如有）"
          },
          "original_quote": "UP主的原话",
          "timestamp": "大致时间段（如有）"
        }
      ],
      "overall_impression": "UP主对餐厅的整体评价"
    }
  ]
}
```

### 注意事项：
- 如果字幕中没有明确的探店/测评内容，返回空的 restaurants 数组
- 菜品名称要准确，不要臆造
- verdict（评价）必须是：推荐、一般、踩雷 三者之一
- original_quote 尽量保留UP主的原话风格
- aspects 中没有提及的维度留空字符串即可
"""

EXTRACTION_USER_PROMPT_TEMPLATE = """\
以下是B站UP主 **{up_name}** 的探店视频 **《{video_title}》** 的字幕文本：

---
{transcript_text}
---

请从上述字幕中提取所有餐厅和菜品的评价信息，严格按照JSON格式输出。
"""

# 用于语义搜索时的查询改写 Prompt
QUERY_REWRITE_PROMPT = """\
你是一个美食搜索查询优化专家。用户输入了一个自然语言的美食搜索请求，\
请将其改写为更适合向量检索的关键短语。

用户查询：{query}

请输出3-5个关键短语，每行一个，用于在美食评价数据库中进行语义检索。\
重点提取：菜品特征、口味描述、烹饪方式、食材关键词。
"""

# 用于生成美食行程的 Prompt
ITINERARY_SYSTEM_PROMPT = """\
你是一个美食行程规划专家。根据提供的餐厅和菜品评价数据，\
为用户生成合理的美食打卡路线。

### 规划原则：
1. 考虑餐厅间的地理距离，安排合理的路线顺序
2. 合理分配早餐/午餐/下午茶/晚餐/宵夜时段
3. 优先推荐UP主评价正面的餐厅和菜品
4. 标注每家餐厅的必点菜品和避雷菜品
5. 提供预估人均消费

### 输出格式：
```json
{
  "city": "城市",
  "days": 1,
  "total_budget_estimate": "预估总花费",
  "itinerary": [
    {
      "day": 1,
      "stops": [
        {
          "order": 1,
          "meal_type": "午餐",
          "restaurant": "餐厅名",
          "recommended_dishes": ["必点菜1", "必点菜2"],
          "avoid_dishes": ["避雷菜"],
          "budget_per_person": "人均",
          "up_master_quote": "UP主推荐语",
          "tips": "注意事项"
        }
      ]
    }
  ]
}
```
"""


class PromptBuilder:
    """Prompt 构建器"""

    @staticmethod
    def build_extraction_prompt(
        up_name: str,
        video_title: str,
        transcript_text: str,
        max_text_length: int = 8000,
    ) -> tuple[str, str]:
        """
        构建信息提取的 System + User Prompt

        Args:
            up_name: UP主名称
            video_title: 视频标题
            transcript_text: 字幕文本
            max_text_length: 字幕文本最大长度（防止超出上下文窗口）

        Returns:
            (system_prompt, user_prompt) 元组
        """
        # 截断过长文本
        if len(transcript_text) > max_text_length:
            transcript_text = transcript_text[:max_text_length] + "\n\n[...文本已截断...]"

        user_prompt = EXTRACTION_USER_PROMPT_TEMPLATE.format(
            up_name=up_name,
            video_title=video_title,
            transcript_text=transcript_text,
        )

        return EXTRACTION_SYSTEM_PROMPT, user_prompt

    @staticmethod
    def build_query_rewrite_prompt(query: str) -> str:
        """构建查询改写 Prompt"""
        return QUERY_REWRITE_PROMPT.format(query=query)

    @staticmethod
    def build_itinerary_prompt(
        city: str,
        restaurant_data: str,
        preferences: str = "",
        days: int = 1,
        budget: str = "moderate",
    ) -> tuple[str, str]:
        """
        构建美食行程生成 Prompt

        Returns:
            (system_prompt, user_prompt) 元组
        """
        user_prompt = (
            f"请为 **{city}** 规划 {days} 天的美食行程。\n\n"
            f"用户偏好：{preferences or '无特殊偏好'}\n"
            f"预算档次：{budget}\n\n"
            f"以下是可选的餐厅和菜品评价数据：\n\n{restaurant_data}"
        )

        return ITINERARY_SYSTEM_PROMPT, user_prompt
