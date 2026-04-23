"""Conversation memory and context management for multi-turn diagnosis."""

from __future__ import annotations

import json
from typing import Dict, List, Any
from pathlib import Path
from datetime import datetime, timezone


TRACES_DIR = Path(__file__).resolve().parents[2] / "backend" / "traces" / "conversations"


class ConversationMemory:
    def __init__(self):
        self.history = []

    def add_user(self, text: str):
        self.history.append(("user", text))

    def add_ai(self, text: str):
        self.history.append(("ai", text))

    def get_context(self):
        context = ""
        for role, msg in self.history[-6:]:
            context += f"{role}: {msg}\n"
        return context