"""
database.py
-----------
A database adapter that handles persistent storage for the bot.

If MONGODB_URI is provided in config, it uses MongoDB Atlas.
If not, it falls back to local JSON files.
This allows the bot to run on ephemeral free hosts (like Render)
without losing data.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger(__name__)

class DatabaseManager:
    """
    Singleton-style manager for database access.
    Automatically routes read/write operations to either MongoDB or local files.
    """
    _instance: DatabaseManager | None = None
    
    def __new__(cls) -> DatabaseManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance
        
    def _init(self) -> None:
        self.use_mongo = bool(config.MONGODB_URI)
        self.db = None
        
        if self.use_mongo:
            try:
                from pymongo import MongoClient
                # Connecting to MongoDB synchronously
                self.client = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=5000)
                # Verify connection
                self.client.admin.command('ping')
                self.db = self.client.leetcode_bot
                self.storage = self.db.storage
                logger.info("MongoDB connected successfully. Using cloud storage.")
            except Exception as exc:
                logger.error("Failed to connect to MongoDB: %s. Falling back to local storage.", exc)
                self.use_mongo = False

    # ------------------------------------------------------------------
    # Core Adapter Methods
    # ------------------------------------------------------------------

    def read_data(self, key: str, path: Path, default: Any) -> Any:
        """
        Read data. If MongoDB is enabled, looks up the document by 'key'.
        Otherwise, reads from the local JSON file at 'path'.
        """
        if self.use_mongo and self.storage is not None:
            try:
                doc = self.storage.find_one({"_id": key})
                if doc and "data" in doc:
                    return doc["data"]
                return default
            except Exception as exc:
                logger.error("MongoDB read error for %s: %s", key, exc)
                return default
        else:
            return self._read_json(path, default)

    def write_data(self, key: str, path: Path, data: Any) -> None:
        """
        Write data. If MongoDB is enabled, upserts the document by 'key'.
        Otherwise, writes to the local JSON file at 'path'.
        """
        if self.use_mongo and self.storage is not None:
            try:
                # Upsert: Update if exists, insert if not
                self.storage.update_one(
                    {"_id": key},
                    {"$set": {"data": data}},
                    upsert=True
                )
            except Exception as exc:
                logger.error("MongoDB write error for %s: %s", key, exc)
                # Fallback to local write if mongo fails
                self._write_json(path, data)
        else:
            self._write_json(path, data)

    # ------------------------------------------------------------------
    # Local JSON Helpers (from original state_manager)
    # ------------------------------------------------------------------

    def _read_json(self, path: Path, default: Any) -> Any:
        """Read JSON from *path*, returning *default* on any error."""
        if not path.exists():
            logger.warning("File not found, using default: %s", path)
            return default
        try:
            with path.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Corrupt/unreadable JSON at %s (%s) — using default.", path, exc)
            self._backup_corrupted(path)
            return default

    def _write_json(self, path: Path, data: Any) -> None:
        """Atomically write *data* as JSON to *path*."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, default=str)
            tmp.replace(path)
        except OSError as exc:
            logger.error("Failed to write %s: %s", path, exc)
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            raise

    def _backup_corrupted(self, path: Path) -> None:
        """Rename a corrupt file so it can be inspected later."""
        backup = path.with_suffix(f".corrupted.{int(datetime.now().timestamp())}")
        try:
            shutil.copy2(path, backup)
            logger.info("Backed up corrupted file to %s", backup)
        except OSError:
            pass
