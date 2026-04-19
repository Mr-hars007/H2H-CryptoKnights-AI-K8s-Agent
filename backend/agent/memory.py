"""Conversation memory and context management for multi-turn diagnosis."""

from __future__ import annotations

import json
from typing import Dict, List, Any
from pathlib import Path
from datetime import datetime, timezone


TRACES_DIR = Path(__file__).resolve().parents[2] / "backend" / "traces" / "conversations"


class ConversationMemory:
    """Manages conversation history and context across multiple diagnosis queries."""

    def __init__(self, conversation_id: str = None, max_turns: int = 20):
        """
        Initialize conversation memory.

        Args:
            conversation_id: Unique ID for this conversation (auto-generated if None)
            max_turns: Maximum number of turns to keep in memory
        """
        from uuid import uuid4

        self.conversation_id = conversation_id or str(uuid4())
        self.max_turns = max_turns
        self.messages: List[Dict[str, Any]] = []
        self.context: Dict[str, Any] = {
            "namespace": "ai-ops",
            "focus_services": [],
            "known_issues": [],
            "attempted_fixes": [],
        }

    def add_user_message(self, text: str) -> None:
        """Add user message to history."""
        self.messages.append({
            "role": "user",
            "content": text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def add_assistant_message(self, diagnosis: str, trace: List[Dict] = None) -> None:
        """Add assistant response to history."""
        self.messages.append({
            "role": "assistant",
            "content": diagnosis,
            "trace": trace or [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def update_context(self, updates: Dict[str, Any]) -> None:
        """Update conversation context."""
        self.context.update(updates)

    def get_summary(self) -> str:
        """Get a summary of the conversation so far for context."""
        lines = [f"Conversation ID: {self.conversation_id}"]
        lines.append(f"Turns: {len(self.messages)}")
        lines.append(f"Context: {json.dumps(self.context, indent=2)}")
        lines.append("\nRecent messages:")
        
        # Show last 4 messages (2 exchanges) for context
        for msg in self.messages[-4:]:
            role = msg["role"].upper()
            content = msg["content"][:200]
            lines.append(f"{role}: {content}...")
        
        return "\n".join(lines)

    def get_full_context(self) -> str:
        """Get full conversation context as a string for the LLM."""
        if not self.messages:
            return "No previous conversation context."
        
        context_lines = ["Previous conversation context:"]
        for msg in self.messages[-6:]:  # Last 3 exchanges
            role = msg["role"].upper()
            content = msg["content"][:300]
            context_lines.append(f"{role}: {content}")
        
        return "\n".join(context_lines)

    def save(self, filepath: Path = None) -> str:
        """
        Save conversation to disk.

        Returns:
            Path to saved file
        """
        if filepath is None:
            TRACES_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            filepath = TRACES_DIR / f"conversation_{self.conversation_id}_{timestamp}.json"
        
        data = {
            "conversation_id": self.conversation_id,
            "messages": self.messages,
            "context": self.context,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        
        return str(filepath)

    @classmethod
    def load(cls, filepath: Path) -> ConversationMemory:
        """Load conversation from disk."""
        with open(filepath, "r") as f:
            data = json.load(f)
        
        memory = cls(conversation_id=data["conversation_id"])
        memory.messages = data["messages"]
        memory.context = data["context"]
        return memory


class ConversationState:
    """Tracks the current state within a diagnosis conversation."""

    def __init__(self):
        self.mode: str = "diagnosis"  # 'diagnosis' or 'chaos'
        self.namespace: str = "ai-ops"
        self.active_scenario: str | None = None
        self.last_action: str | None = None
        self.issue_confirmed: bool = False
        self.root_cause_identified: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary."""
        return {
            "mode": self.mode,
            "namespace": self.namespace,
            "active_scenario": self.active_scenario,
            "last_action": self.last_action,
            "issue_confirmed": self.issue_confirmed,
            "root_cause_identified": self.root_cause_identified,
        }

    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load state from dictionary."""
        self.mode = data.get("mode", "diagnosis")
        self.namespace = data.get("namespace", "ai-ops")
        self.active_scenario = data.get("active_scenario")
        self.last_action = data.get("last_action")
        self.issue_confirmed = data.get("issue_confirmed", False)
        self.root_cause_identified = data.get("root_cause_identified", False)
