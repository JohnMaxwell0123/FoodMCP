"""
LLM 信息抽取模块测试

测试 SchemaValidator 的 JSON 解析和数据清洗逻辑。
"""

from src.extractor.schema_validator import SchemaValidator


class TestSchemaValidator:
    """Schema 校验器测试"""

    def setup_method(self):
        self.validator = SchemaValidator()

    def test_valid_json(self):
        """标准JSON应正确解析"""
        raw = '''
        {
          "restaurants": [
            {
              "name": "老北京涮羊肉",
              "location": "东城区",
              "cuisine_type": "火锅",
              "dishes": [
                {
                  "name": "手切鲜羊肉",
                  "price": "68",
                  "verdict": "推荐",
                  "aspects": {"taste": "鲜嫩", "portion": "量大"},
                  "original_quote": "这羊肉太嫩了，入口即化",
                  "timestamp": "3:20"
                }
              ],
              "overall_impression": "正宗老北京味道"
            }
          ]
        }
        '''
        result = self.validator.validate_extraction(raw)
        assert len(result.restaurants) == 1
        assert result.restaurants[0].name == "老北京涮羊肉"
        assert len(result.restaurants[0].dishes) == 1
        assert result.restaurants[0].dishes[0].verdict == "推荐"
        assert result.confidence > 0.5

    def test_json_in_code_block(self):
        """包裹在代码块中的JSON应能提取"""
        raw = '''
        这是提取结果：

        ```json
        {"restaurants": [{"name": "测试餐厅", "dishes": [{"name": "测试菜", "verdict": "一般", "original_quote": "还行吧"}]}]}
        ```

        以上是所有内容。
        '''
        result = self.validator.validate_extraction(raw)
        assert len(result.restaurants) == 1

    def test_verdict_normalization(self):
        """非标准verdict应被规范化"""
        raw = '''{"restaurants": [{"name": "R1", "dishes": [
            {"name": "D1", "verdict": "好吃推荐", "original_quote": "test"},
            {"name": "D2", "verdict": "太差了", "original_quote": "test"},
            {"name": "D3", "verdict": "还可以", "original_quote": "test"}
        ]}]}'''
        result = self.validator.validate_extraction(raw)
        dishes = result.restaurants[0].dishes
        assert dishes[0].verdict == "推荐"
        assert dishes[1].verdict == "踩雷"
        assert dishes[2].verdict == "一般"

    def test_empty_restaurants(self):
        """空餐厅列表应返回0置信度"""
        raw = '{"restaurants": []}'
        result = self.validator.validate_extraction(raw)
        assert len(result.restaurants) == 0
        assert result.confidence == 0.0

    def test_invalid_json(self):
        """无效JSON应优雅处理"""
        raw = "这不是JSON内容"
        result = self.validator.validate_extraction(raw)
        assert len(result.restaurants) == 0
        assert result.error != ""

    def test_missing_dish_name_skipped(self):
        """缺少菜名的记录应被跳过"""
        raw = '''{"restaurants": [{"name": "R1", "dishes": [
            {"name": "", "verdict": "推荐", "original_quote": "test"},
            {"name": "真实菜品", "verdict": "推荐", "original_quote": "好吃"}
        ]}]}'''
        result = self.validator.validate_extraction(raw)
        assert len(result.restaurants[0].dishes) == 1
        assert result.restaurants[0].dishes[0].name == "真实菜品"
