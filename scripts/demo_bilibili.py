import asyncio
import os
from dotenv import load_dotenv

from loguru import logger
from src.collector.bilibili_client import BilibiliClient
from src.collector.video_filter import VideoFilter

# 加载环境变量
load_dotenv()

async def main():
    # 测试用的 UP主 MID (例如：品城记 162235956 或者 盗月社 99157282)
    # 你可以改成你喜欢的 UP主 MID
    TEST_MID = 162235956 
    
    logger.info(f"开始测试获取 UP主 {TEST_MID} 的探店视频...")
    
    # 1. 初始化客户端
    client = BilibiliClient()
    
    # 2. 获取视频列表 (测试拉取 1 页，每页 10 个视频)
    logger.info("正在调用 B站 API 拉取视频列表...")
    videos = await client.get_up_videos(mid=TEST_MID, page_size=10, max_pages=1)
    
    if not videos:
        logger.warning("未拉取到视频，请检查网络或 Cookie 配置！")
        return

    logger.info(f"成功拉取到 {len(videos)} 个视频！")
    for v in videos:
        logger.debug(f"- {v.title} (时长: {v.duration}s)")
        
    # 3. 智能筛选探店视频
    logger.info("\n开始进行智能筛选...")
    video_filter = VideoFilter()
    food_videos = video_filter.filter_videos(videos)
    
    logger.info(f"\n✅ 筛选结果：从 {len(videos)} 个视频中筛选出 {len(food_videos)} 个探店视频：")
    for i, v in enumerate(food_videos, 1):
        logger.success(f"{i}. [{v.bvid}] {v.title}")
        
    # 4. (可选) 测试获取第一个筛选出视频的详情和标签
    if food_videos:
        first_video = food_videos[0]
        logger.info(f"\n正在获取第一个探店视频 [{first_video.bvid}] 的标签...")
        tags = await client.get_video_tags(first_video.bvid)
        logger.info(f"获取到的标签: {tags}")

if __name__ == "__main__":
    asyncio.run(main())
