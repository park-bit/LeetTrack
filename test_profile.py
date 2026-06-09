import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

async def test():
    name = "park-bit"
    from leetcode_fetcher import LeetCodeFetcher
    async with LeetCodeFetcher() as fetcher:
        
        print("Fetching stats...")
        stats = await fetcher.get_user_stats(name)
    print("Stats fetched:", stats)

    print("Generating chart...")
    import functools
    from chart_generator import generate_profile_donut_chart
    
    loop = asyncio.get_event_loop()
    buf = await loop.run_in_executor(
        None,
        functools.partial(
            generate_profile_donut_chart,
            stats.easy_solved,
            stats.medium_solved,
            stats.hard_solved,
            name
        ),
    )
    print("Chart generated! Size:", len(buf.getvalue()))

if __name__ == "__main__":
    asyncio.run(test())
