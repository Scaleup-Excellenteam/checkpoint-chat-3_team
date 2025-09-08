import threading
from pathlib import Path
from utils import utc_now, safe_write_json
import json

class StateManager:
    def __init__(self, state_file: str, max_messages_per_room: int):
        self.state_path = Path(state_file)
        self.max_messages_per_room = max_messages_per_room
        self.lock = threading.Lock()
        self.state = {
            "rooms": {},      # room -> {"members": [names], "created_at": iso, "last_updated": iso}
            "messages": {}    # room -> [{"from": str, "body": str, "ts": iso}, ...]
        }
        self.load_state()

    def load_state(self) -> None:
        """Load from disk; if not exists, keep the defaults."""
        if self.state_path.exists():
            try:
                with self.state_path.open("r", encoding="utf-8") as f:
                    on_disk = json.load(f)
                if isinstance(on_disk, dict):
                    self.state.update(on_disk)
            except Exception:
                pass  # if corrupted, keep defaults
        
        # Ensure required keys exist
        self.state.setdefault("rooms", {})
        self.state.setdefault("messages", {})
        # Active members should start empty after restart
        for room, meta in self.state["rooms"].items():
            meta["members"] = []

    def save_state(self) -> None:
        """Save state to disk"""
        with self.lock:
            safe_write_json(self.state_path, self.state)

    def ensure_room(self, room: str) -> None:
        """Ensure room exists in state"""
        with self.lock:
            if room not in self.state["rooms"]:
                now = utc_now()
                self.state["rooms"][room] = {
                    "members": [],
                    "created_at": now,
                    "last_updated": now,
                }
            if room not in self.state["messages"]:
                self.state["messages"][room] = []

    def add_member(self, room: str, name: str) -> None:
        """Add member to room"""
        self.ensure_room(room)
        with self.lock:
            members = self.state["rooms"][room]["members"]
            if name not in members:
                members.append(name)
            self.state["rooms"][room]["last_updated"] = utc_now()
        self.save_state()

    def remove_member(self, room: str, name: str) -> None:
        """Remove member from room"""
        self.ensure_room(room)
        with self.lock:
            members = self.state["rooms"][room]["members"]
            if name in members:
                members.remove(name)
            self.state["rooms"][room]["last_updated"] = utc_now()
        self.save_state()

    def append_message(self, room: str, sender: str, body: str) -> dict:
        """Add message to room and return the message"""
        self.ensure_room(room)
        msg = {"from": sender, "body": body, "ts": utc_now()}
        with self.lock:
            bucket = self.state["messages"][room]
            bucket.append(msg)
            # keep only the last N messages
            if len(bucket) > self.max_messages_per_room:
                del bucket[: len(bucket) - self.max_messages_per_room]
            self.state["rooms"][room]["last_updated"] = msg["ts"]
        self.save_state()
        return msg

    def get_rooms(self) -> dict:
        """Get room member counts"""
        with self.lock:
            return {r: len(meta.get("members", [])) for r, meta in self.state["rooms"].items()}

    def get_room_info(self, room: str) -> dict:
        """Get detailed room information"""
        self.ensure_room(room)
        with self.lock:
            meta = self.state["rooms"][room]
            msg_count = len(self.state["messages"].get(room, []))
            return {
                "name": room,
                "members": list(meta.get("members", [])),
                "created_at": meta.get("created_at"),
                "last_updated": meta.get("last_updated"),
                "message_count": msg_count,
            }

    def get_room_messages(self, room: str, limit: int = 50) -> list:
        """Get room messages (newest first)"""
        self.ensure_room(room)
        with self.lock:
            msgs = list(self.state["messages"].get(room, []))
        return list(reversed(msgs))[:limit]