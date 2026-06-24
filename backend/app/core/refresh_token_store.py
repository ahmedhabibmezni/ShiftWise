"""
Refresh-token family store (Redis-backed) with reuse detection.

Model (OAuth 2.1 BCP, RFC 6749 §4.12.2):

- /login creates a *family* identified by family_id (uuid4). Every token
  issued in the family carries (family_id, jti).
- /refresh: the presented (family_id, jti) MUST exist. Consume it (DEL),
  mint a new jti, return both.
- If a refresh arrives with a missing jti while the family meta is still
  alive, treat it as reuse: the legitimate client already rotated, so the
  request comes from an attacker holding a stale copy. Wipe the family and
  force re-login.
- /logout deletes the whole family.

Keys
----
- `rt:fam:<family_id>:<jti>` -> user_id. TTL = refresh token TTL.
- `rt:fam:<family_id>:meta` -> hash {user_id, created_at}. Same TTL.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Optional

from app.core.config import settings
from app.core.redis_client import get_redis

_FAM_PREFIX = "rt:fam:"


def _jti_key(family_id: str, jti: str) -> str:
    return f"{_FAM_PREFIX}{family_id}:{jti}"


def _meta_key(family_id: str) -> str:
    return f"{_FAM_PREFIX}{family_id}:meta"


def _family_pattern(family_id: str) -> str:
    return f"{_FAM_PREFIX}{family_id}:*"


def _refresh_ttl_seconds() -> int:
    return settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600


@dataclass(frozen=True)
class RotateOk:
    user_id: int
    new_jti: str


@dataclass(frozen=True)
class RotateReuseDetected:
    """jti missing but family meta alive -> presumed attacker. Family wiped."""

    user_id: int


@dataclass(frozen=True)
class RotateUnknown:
    """Family does not exist (expired or never issued). Plain 401."""


RotateResult = RotateOk | RotateReuseDetected | RotateUnknown


def create_family(user_id: int) -> tuple[str, str]:
    """Create a new family and return (family_id, jti)."""
    r = get_redis()
    family_id = uuid.uuid4().hex
    jti = uuid.uuid4().hex
    ttl = _refresh_ttl_seconds()

    pipe = r.pipeline()
    pipe.set(_jti_key(family_id, jti), str(user_id), ex=ttl)
    pipe.hset(
        _meta_key(family_id),
        mapping={"user_id": str(user_id), "created_at": str(int(time.time()))},
    )
    pipe.expire(_meta_key(family_id), ttl)
    pipe.execute()

    return family_id, jti


def rotate(family_id: str, jti: str, user_id: int) -> RotateResult:
    """Consume (family_id, jti) and rotate to a new jti.

    Concurrency model: DEL is atomic. If two parallel refreshes present the
    same jti, exactly one wins; the loser sees DEL=0 and a live family meta,
    which is precisely the reuse signal. A correct client must single-flight
    its refresh, so this can only happen in attack scenarios.
    """
    r = get_redis()
    old_key = _jti_key(family_id, jti)
    meta_key = _meta_key(family_id)

    existed = r.delete(old_key)
    if existed:
        meta_user_id = r.hget(meta_key, "user_id")
        if meta_user_id is None or int(meta_user_id) != user_id:
            # Family meta gone or owner mismatch -> treat as unknown.
            return RotateUnknown()

        new_jti = uuid.uuid4().hex
        ttl = _refresh_ttl_seconds()
        pipe = r.pipeline()
        pipe.set(_jti_key(family_id, new_jti), str(user_id), ex=ttl)
        pipe.expire(meta_key, ttl)
        pipe.execute()
        return RotateOk(user_id=user_id, new_jti=new_jti)

    meta_user_id = r.hget(meta_key, "user_id")
    if meta_user_id is not None:
        revoke_family(family_id)
        return RotateReuseDetected(user_id=int(meta_user_id))

    return RotateUnknown()


def revoke_family(family_id: str) -> int:
    """Wipe every key for a family. Returns count of deleted keys."""
    r = get_redis()
    deleted = 0
    for key in r.scan_iter(match=_family_pattern(family_id), count=100):
        deleted += r.delete(key)
    return deleted


def family_user_id(family_id: str) -> Optional[int]:
    """Return user_id owning a family, or None if unknown."""
    r = get_redis()
    val = r.hget(_meta_key(family_id), "user_id")
    return int(val) if val is not None else None
