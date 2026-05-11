"""
Login throttle — Redis-backed sliding-window counter for failed /auth/login
attempts.

Model
-----
Two parallel counters per attempt:

- email-bucket: ``lt:email:<email>``  →  catches a slow credential-stuffing
  attack where the attacker rotates source IPs but always targets the same
  account.
- ip-bucket:    ``lt:ip:<ip>``        →  catches a brute-force burst from a
  single attacker against any account.

Both buckets are simple INCR counters with an EXPIRE — Redis handles the
"sliding window" semantics for free (the key dies when the window elapses).
After ``LOGIN_THROTTLE_MAX_ATTEMPTS`` failures within the window, both new
attempts are short-circuited with ``LockoutActive`` until the window expires.

A successful login deletes both buckets so the legitimate user is not held
hostage by their own typos.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.core.config import settings
from app.core.redis_client import get_redis


_EMAIL_PREFIX = "lt:email:"
_IP_PREFIX = "lt:ip:"


@dataclass(frozen=True)
class LockoutActive:
    """Returned when either bucket is over threshold.

    ``retry_after_seconds`` is the TTL of the more-restrictive (longer) of
    the two locked buckets — what the caller surfaces in the 429 Retry-After
    header.
    """

    retry_after_seconds: int
    locked_by: str  # "email" or "ip" or "email+ip"


def _email_key(email: str) -> str:
    # Lowercased so "Alice@x" and "alice@x" share the bucket.
    return f"{_EMAIL_PREFIX}{email.strip().lower()}"


def _ip_key(ip: str) -> str:
    return f"{_IP_PREFIX}{ip}"


def _max_attempts() -> int:
    return settings.LOGIN_THROTTLE_MAX_ATTEMPTS


def _window_seconds() -> int:
    return settings.LOGIN_THROTTLE_WINDOW_SECONDS


def _enabled() -> bool:
    """Feature flag: max_attempts <= 0 disables throttling entirely.

    Useful for tests and for dev environments where lockout would be
    annoying. Production deployments should leave the default.
    """
    return _max_attempts() > 0


def check_lockout(email: str, ip: Optional[str]) -> Optional[LockoutActive]:
    """Return a LockoutActive when either bucket is over threshold.

    Read-only — does not increment anything. Call before attempting the
    authenticate so a locked-out attacker doesn't even reach bcrypt
    (which is expensive on purpose and would amplify a DoS).
    """
    if not _enabled():
        return None

    r = get_redis()
    threshold = _max_attempts()

    pipe = r.pipeline()
    pipe.get(_email_key(email))
    pipe.ttl(_email_key(email))
    if ip:
        pipe.get(_ip_key(ip))
        pipe.ttl(_ip_key(ip))
    raw = pipe.execute()

    email_count = int(raw[0]) if raw[0] is not None else 0
    email_ttl = int(raw[1]) if raw[1] is not None else 0
    if ip:
        ip_count = int(raw[2]) if raw[2] is not None else 0
        ip_ttl = int(raw[3]) if raw[3] is not None else 0
    else:
        ip_count = 0
        ip_ttl = 0

    email_locked = email_count >= threshold
    ip_locked = ip_count >= threshold

    if not email_locked and not ip_locked:
        return None

    # `ttl()` returns -1 when the key has no expiry, -2 when it doesn't
    # exist. Both are impossible in practice (we always set EX on INCR)
    # but the defensive `max(0, ...)` keeps the header sane.
    retry_after = max(0, max(email_ttl if email_locked else 0, ip_ttl if ip_locked else 0))

    if email_locked and ip_locked:
        locked_by = "email+ip"
    elif email_locked:
        locked_by = "email"
    else:
        locked_by = "ip"

    return LockoutActive(retry_after_seconds=retry_after, locked_by=locked_by)


def record_failure(email: str, ip: Optional[str]) -> None:
    """Increment both buckets and (re)arm their TTL.

    The EXPIRE on every call is intentional: it implements a fixed-window
    rather than a sliding one, but resets the clock when a new attempt
    arrives — making the protection more aggressive against a sustained
    attacker. The trade-off is that a single legitimate typo lengthens
    the lockout by the full window; in practice the count threshold is
    forgiving enough (5 by default) that real users never trip it.
    """
    if not _enabled():
        return

    r = get_redis()
    window = _window_seconds()

    pipe = r.pipeline()
    pipe.incr(_email_key(email))
    pipe.expire(_email_key(email), window)
    if ip:
        pipe.incr(_ip_key(ip))
        pipe.expire(_ip_key(ip), window)
    pipe.execute()


def reset(email: str, ip: Optional[str]) -> None:
    """Drop both counters after a successful authenticate.

    Honest users who fat-fingered their password three times shouldn't be
    one typo away from a 15-minute timeout for the rest of their session.
    """
    if not _enabled():
        return

    r = get_redis()
    keys = [_email_key(email)]
    if ip:
        keys.append(_ip_key(ip))
    r.delete(*keys)
