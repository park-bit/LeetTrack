import os
import json
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(".env")
uri = os.environ.get("MONGODB_URI")
client = MongoClient(uri)
db = client.leetcode_bot
storage = db.storage

doc = storage.find_one({"_id": "state.json"})
if doc and "data" in doc:
    print(json.dumps(doc["data"], indent=2))
