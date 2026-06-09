import os
import json
from dotenv import load_dotenv
from pymongo import MongoClient
from datetime import datetime, timedelta, date
import pytz

load_dotenv(".env")
uri = os.environ.get("MONGODB_URI")
client = MongoClient(uri)
db = client.leetcode_bot
storage = db.storage

def get_doc(key):
    doc = storage.find_one({"_id": key})
    return doc["data"] if doc and "data" in doc else {}

history = get_doc("history.json")
state = get_doc("state.json")

def get_day_problems(username, date_str):
    return history.get(username, {}).get(date_str, [])

week_start_str = state.get("week_start")
week_start = date.fromisoformat(week_start_str) if week_start_str else None
today = datetime.now(tz=pytz.timezone("Asia/Kolkata")).date()

if week_start:
    delta_days = (today - week_start).days
    if delta_days < 0: delta_days = 0
    dates_in_week = [week_start + timedelta(days=i) for i in range(delta_days + 1)]
else:
    dates_in_week = [today]

profiles = [
    {"name": "park-bit"},
    {"name": "lilght01"},
    {"name": "Yuuta_1678"},
    {"name": "vedant_ghate"}
]

for profile in profiles:
    name = profile["name"]
    solved = 0
    easy = 0
    for d in dates_in_week:
        probs = get_day_problems(name, d.isoformat())
        solved += len(probs)
        easy += sum(1 for p in probs if p.get("difficulty") == "Easy")
    print(f"{name}: {solved} solved (Easy: {easy})")
