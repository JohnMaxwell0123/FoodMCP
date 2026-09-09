"""
数据采集模块测试

测试 VideoFilter 的关键词匹配和评分逻辑。
"""

from src.collector.video_filter import VideoFilter
from src.models.entities import VideoInfo


class TestVideoFilter:
    """视频筛选器测试"""

    def setup_method(self):
        self.filter = VideoFilter()

    def test_typical_food_video(self):
        """典型探店视频应被识别"""
        video = VideoInfo(
            bvid="BV1test001",
            title="北京探店｜这家鲁菜馆太绝了！人均80吃到撑",
            description="今天来到北京东城区一家老字号鲁菜馆",
            up_mid="12345",
            tags=["美食", "探店", "北京"],
        )
        assert self.filter.is_food_exploration(video) is True

    def test_non_food_video(self):
        """非美食视频应被过滤"""
        video = VideoInfo(
            bvid="BV1test002",
            title="我的世界 1.20 生存实况 第100期",
            description="今天继续挖矿",
            up_mid="12345",
            tags=["游戏", "我的世界"],
        )
        assert self.filter.is_food_exploration(video) is False

    def test_cooking_tutorial_excluded(self):
        """烹饪教程应被排除（排除关键词）"""
        video = VideoInfo(
            bvid="BV1test003",
            title="红烧肉做法教程｜家常菜做法",
            description="今天教大家做红烧肉",
            up_mid="12345",
            tags=["美食", "教程"],
        )
        assert self.filter.is_food_exploration(video) is False

    def test_batch_filter(self):
        """批量筛选应正确过滤"""
        videos = [
            VideoInfo(bvid="BV1a", title="成都探店火锅测评", up_mid="1", tags=["美食"]),
            VideoInfo(bvid="BV1b", title="日常vlog 今天加班了", up_mid="1"),
            VideoInfo(bvid="BV1c", title="上海必吃小吃打卡", up_mid="1", tags=["探店"]),
        ]
        result = self.filter.filter_videos(videos)
        assert len(result) == 2
        assert all(v.is_food_exploration for v in result)

    def test_score_threshold(self):
        """得分阈值应可配置"""
        strict_filter = VideoFilter(score_threshold=0.8)
        video = VideoInfo(
            bvid="BV1test",
            title="吃了个饭",  # 弱信号
            up_mid="1",
        )
        assert strict_filter.is_food_exploration(video) is False
