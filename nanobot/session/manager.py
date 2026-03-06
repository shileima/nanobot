"""Session management for conversation history."""

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.utils.helpers import ensure_dir, safe_filename


@dataclass
class Session:
    """
    A conversation session.

    Stores messages in JSONL format for easy reading and persistence.

    Important: Messages are append-only for LLM cache efficiency.
    The consolidation process writes summaries to MEMORY.md/HISTORY.md
    but does NOT modify the messages list or get_history() output.
    """

    key: str  # channel:chat_id
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_consolidated: int = 0  # Number of messages already consolidated to files

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        """Add a message to the session."""
        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        }
        self.messages.append(msg)
        self.updated_at = datetime.now()

    def get_history(self, max_messages: int = 500) -> list[dict[str, Any]]:
        """Return unconsolidated messages for LLM input, aligned to a user turn."""
        unconsolidated = self.messages[self.last_consolidated:]
        sliced = unconsolidated[-max_messages:]

        # Drop leading non-user messages to avoid orphaned tool_result blocks
        for i, m in enumerate(sliced):
            if m.get("role") == "user":
                sliced = sliced[i:]
                break

        out: list[dict[str, Any]] = []
        for m in sliced:
            entry: dict[str, Any] = {"role": m["role"], "content": m.get("content", "")}
            for k in ("tool_calls", "tool_call_id", "name"):
                if k in m:
                    entry[k] = m[k]
            out.append(entry)
        return out

    def clear(self) -> None:
        """Clear all messages and reset session to initial state."""
        self.messages = []
        self.last_consolidated = 0
        self.updated_at = datetime.now()


class SessionManager:
    """
    Manages conversation sessions.

    Sessions are stored as JSONL files in the sessions directory.
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.sessions_dir = ensure_dir(self.workspace / "sessions")
        self.legacy_sessions_dir = Path.home() / ".nanobot" / "sessions"
        self._cache: dict[str, Session] = {}

    def _get_session_path(self, key: str) -> Path:
        """Get the file path for a session."""
        safe_key = safe_filename(key.replace(":", "_"))
        return self.sessions_dir / f"{safe_key}.jsonl"

    def _get_legacy_session_path(self, key: str) -> Path:
        """Legacy global session path (~/.nanobot/sessions/)."""
        safe_key = safe_filename(key.replace(":", "_"))
        return self.legacy_sessions_dir / f"{safe_key}.jsonl"

    def _first_user_message_preview(self, path: Path, first_line: str, max_len: int = 20) -> str | None:
        """Extract first user message content as display name fallback. Reads up to 50 lines."""
        try:
            # Determine whether the first line is metadata so we know the start offset
            first_is_metadata = False
            try:
                first_data = json.loads(first_line)
                first_is_metadata = first_data.get("_type") == "metadata"
            except Exception:
                pass

            with open(path, encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if i == 0 and first_is_metadata:
                        continue  # skip metadata header
                    if i >= 50:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("role") == "user":
                        content = (data.get("content") or "").strip()
                        if content:
                            # Remove newlines, collapse spaces
                            preview = " ".join(content.split())[:max_len]
                            return preview + ("…" if len(preview) >= max_len else "")
            return None
        except Exception:
            return None

    def get_or_create(self, key: str) -> Session:
        """
        Get an existing session or create a new one.

        Args:
            key: Session key (usually channel:chat_id).

        Returns:
            The session.
        """
        if key in self._cache:
            return self._cache[key]

        session = self._load(key)
        if session is None:
            session = Session(key=key)

        self._cache[key] = session
        return session

    def _load(self, key: str) -> Session | None:
        """Load a session from disk."""
        path = self._get_session_path(key)
        if not path.exists():
            legacy_path = self._get_legacy_session_path(key)
            if legacy_path.exists():
                try:
                    shutil.move(str(legacy_path), str(path))
                    logger.info("Migrated session {} from legacy path", key)
                except Exception:
                    logger.exception("Failed to migrate session {}", key)

        if not path.exists():
            return None

        try:
            messages = []
            metadata = {}
            created_at = None
            last_consolidated = 0

            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    data = json.loads(line)

                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        created_at = datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None
                        last_consolidated = data.get("last_consolidated", 0)
                    else:
                        messages.append(data)

            return Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                metadata=metadata,
                last_consolidated=last_consolidated
            )
        except Exception as e:
            logger.warning("Failed to load session {}: {}", key, e)
            return None

    def save(self, session: Session) -> None:
        """Save a session to disk."""
        path = self._get_session_path(session.key)

        with open(path, "w", encoding="utf-8") as f:
            metadata_line = {
                "_type": "metadata",
                "key": session.key,
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "metadata": session.metadata,
                "last_consolidated": session.last_consolidated
            }
            f.write(json.dumps(metadata_line, ensure_ascii=False) + "\n")
            for msg in session.messages:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")

        self._cache[session.key] = session

    def invalidate(self, key: str) -> None:
        """Remove a session from the in-memory cache."""
        self._cache.pop(key, None)

    def delete_session(self, key: str) -> bool:
        """Delete a session from disk and cache. Returns True if deleted."""
        self._cache.pop(key, None)
        path = self._get_session_path(key)
        if path.exists():
            try:
                path.unlink()
                return True
            except OSError:
                return False
        legacy = self._get_legacy_session_path(key)
        if legacy.exists():
            try:
                legacy.unlink()
                return True
            except OSError:
                return False
        return False

    def list_sessions(self) -> list[dict[str, Any]]:
        """
        List all sessions.

        Returns:
            List of session info dicts with key, created_at, updated_at (and path).
        """
        sessions = []
        # Fallback when metadata has no dates (e.g. legacy files): use file mtime
        def _mtime_iso(p: Path) -> str | None:
            try:
                return datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat()
            except OSError:
                return None

        for path in self.sessions_dir.glob("*.jsonl"):
            try:
                with open(path, encoding="utf-8") as f:
                    first_line = f.readline().strip()
                if not first_line:
                    continue
                data = json.loads(first_line)
                key = path.stem.replace("_", ":", 1)
                created_at = None
                updated_at = None
                title = None
                if data.get("_type") == "metadata":
                    key = data.get("key") or key
                    created_at = data.get("created_at")
                    updated_at = data.get("updated_at")
                    title = data.get("metadata", {}).get("title")
                # Fallback: use first user message as display name when title is missing
                if not title:
                    title = self._first_user_message_preview(path, first_line)
                fallback = _mtime_iso(path)
                if not updated_at:
                    updated_at = fallback
                if not created_at:
                    created_at = fallback
                sessions.append({
                    "key": key,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "title": title,
                    "path": str(path),
                })
            except Exception:
                continue

        return sorted(sessions, key=lambda x: x.get("updated_at") or "", reverse=True)
