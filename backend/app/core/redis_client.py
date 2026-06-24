"""
Redis client for the auth refresh-token store.

Uses REDIS_AUTH_URL (a logical DB distinct from Celery's broker DB) so the
auth keyspace stays isolated. The client is created lazily and reused.
"""

from __future__ import annotations

import threading
from typing import Optional

import redis

from app.core.config import settings

_client: Optional[redis.Redis] = None
_lock = threading.Lock()


def get_redis() -> redis.Redis:
    """Return the singleton Redis client for the auth store."""
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                _client = redis.Redis.from_url(
                    settings.REDIS_AUTH_URL,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                    health_check_interval=30,
                )
    return _client
