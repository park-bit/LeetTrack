import asyncio
import os
from datetime import datetime
import pytz
from dotenv import load_dotenv
from pymongo import MongoClient

from leetcode_fetcher import LeetCodeFetcher
import config

load_dotenv(".env")

async def main():
    uri = os.environ.get("MONGODB_URI")
    client = MongoClient(uri)
    db = client.leetcode_bot
    storage = db.storage

    # Load history
    doc = storage.find_one({"_id": "history.json"})
    history = doc.get("data", {}) if doc else {}

    doc_profiles = storage.find_one({"_id": "profiles.json"})
    profiles = doc_profiles.get("data", []) if doc_profiles else []

    # Monday June 8th 2026 midnight IST
    tz = pytz.timezone(config.TIMEZONE)
    start_ts = tz.localize(datetime(2026, 6, 8)).timestamp()

    async with LeetCodeFetcher() as fetcher:
        for profile in profiles:
            name = profile["name"]
            url = profile["leetcode_url"]
            print(f"Fetching recent submissions for {name}...")
            subs = await fetcher.get_recent_submissions(url, limit=20)
            
            if name not in history:
                history[name] = {}

            added_count = 0
            for s in subs:
                if s.timestamp < start_ts:
                    continue
                
                dt = datetime.fromtimestamp(s.timestamp, tz=tz)
                d_str = dt.date().isoformat()

                if d_str not in history[name]:
                    history[name][d_str] = []

                # Check if it's already there
                exists = any(p.get("slug") == s.slug for p in history[name][d_str])
                if not exists:
                    # Fetch difficulty
                    diff, tags = await fetcher._get_problem_info(s.slug)
                    
                    history[name][d_str].append({
                        "slug": s.slug,
                        "title": s.title,
                        "difficulty": diff,
                        "url": f"https://leetcode.com/problems/{s.slug}/",
                        "lang": s.lang,
                        "timestamp": s.timestamp,
                        "tags": tags,
                    })
                    added_count += 1
                    print(f"  -> Added {s.slug} to {d_str} ({diff})")
            
            print(f"Finished {name}: backfilled {added_count} missing submissions.")

    storage.update_one({"_id": "history.json"}, {"$set": {"data": history}}, upsert=True)
    print("Successfully pushed updated history to MongoDB!")

if __name__ == "__main__":
    asyncio.run(main())
