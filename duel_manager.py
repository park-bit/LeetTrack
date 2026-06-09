import logging
import random
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

class DuelManager:
    def __init__(self, bot) -> None:
        self.bot = bot
        # Maps user discord_id to their active duel data
        self.active_duels: Dict[str, Dict[str, Any]] = {}

    def start_duel(self, user1_id: str, user2_id: str, problem_slug: str, problem_title: str, problem_url: str) -> None:
        duel_data = {
            "user1": user1_id,
            "user2": user2_id,
            "problem_slug": problem_slug,
            "problem_title": problem_title,
            "problem_url": problem_url,
            "start_time": datetime.utcnow()
        }
        self.active_duels[user1_id] = duel_data
        self.active_duels[user2_id] = duel_data

    def get_active_duel(self, user_id: str) -> Optional[Dict[str, Any]]:
        return self.active_duels.get(user_id)

    def close_duel(self, user_id: str) -> None:
        duel = self.active_duels.get(user_id)
        if duel:
            u1 = duel["user1"]
            u2 = duel["user2"]
            self.active_duels.pop(u1, None)
            self.active_duels.pop(u2, None)
