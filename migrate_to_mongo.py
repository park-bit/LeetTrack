import json
from pathlib import Path
from pymongo import MongoClient
import os
from dotenv import load_dotenv

# Load the URI from .env
load_dotenv(".env")
uri = os.environ.get("MONGODB_URI")

if not uri:
    print("MONGODB_URI not found in .env")
    exit(1)

client = MongoClient(uri)
db = client.leetcode_bot
storage = db.storage

def push_file(file_path: Path, doc_id: str):
    if not file_path.exists():
        print(f"Skipping {file_path} (does not exist)")
        return
    with file_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
        storage.update_one(
            {"_id": doc_id},
            {"$set": {"data": data}},
            upsert=True
        )
        print(f"Migrated {file_path} to MongoDB document '{doc_id}'")

print("Starting migration from local JSON files to MongoDB...")

# Migrate profiles
push_file(Path("profiles.json"), "profiles.json")

# Migrate state
data_dir = Path("data")
push_file(data_dir / "state.json", "state.json")
push_file(data_dir / "streaks.json", "streaks.json")
push_file(data_dir / "user_stats.json", "user_stats.json")
push_file(data_dir / "history.json", "history.json")

print("Migration complete! All your local data is now in the cloud.")
