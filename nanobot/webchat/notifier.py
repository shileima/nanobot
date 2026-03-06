"""Webchat push notifier for scheduled tasks and other server-initiated events."""

from __future__ import annotations

import queue
import threading
from typing import Any


class WebchatNotifier:
    """Thread-safe notifier that broadcasts events to subscribed SSE clients."""

    def __init__(self) -> None:
        self._listeners: list[queue.Queue[dict[str, Any]]] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue[dict[str, Any]]:
        """Create and register a new listener queue. Caller must call unsubscribe when done."""
        q: queue.Queue[dict[str, Any]] = queue.Queue()
        with self._lock:
            self._listeners.append(q)
        return q

    def unsubscribe(self, q: queue.Queue[dict[str, Any]]) -> None:
        """Remove a listener queue."""
        with self._lock:
            if q in self._listeners:
                self._listeners.remove(q)

    def notify(
        self,
        chat_id: str,
        content: str,
        *,
        job_name: str | None = None,
        event_type: str = "scheduled_task",
    ) -> None:
        """Broadcast a notification to all connected webchat clients."""
        event: dict[str, Any] = {
            "type": event_type,
            "chat_id": chat_id,
            "content": content,
        }
        if job_name is not None:
            event["job_name"] = job_name

        with self._lock:
            for listener in self._listeners:
                try:
                    listener.put_nowait(event)
                except queue.Full:
                    pass
