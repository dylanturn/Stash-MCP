"""Event bus for content change notifications."""

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

# Event types
CONTENT_CREATED = "content_created"
CONTENT_UPDATED = "content_updated"
CONTENT_DELETED = "content_deleted"
CONTENT_MOVED = "content_moved"

# Simple event bus
_listeners: list[Callable] = []


def add_listener(callback: Callable) -> None:
    """Register a listener for content change events."""
    _listeners.append(callback)


def emit(event_type: str, path: str, **kwargs: str) -> None:
    """Emit a content change event to all registered listeners."""
    for listener in _listeners:
        try:
            listener(event_type, path, **kwargs)
        except Exception as e:
            logger.error(f"Event listener error: {e}")
