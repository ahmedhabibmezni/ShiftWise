"""
Credential vault — Fernet symmetric encryption with key rotation (US4).

The vault is a thin wrapper around ``cryptography.fernet.MultiFernet`` so
the primary key encrypts new credentials while older keys can still
decrypt historical ciphertexts. Operators rotate by:

1. Generating a new Fernet key.
2. Setting ``SHIFTWISE_FERNET_OLD_KEYS`` to the old primary (comma
   separated if rotating more than once).
3. Setting ``SHIFTWISE_FERNET_KEY`` to the new key.
4. Restarting the backend / workers and rewriting credentials (a
   follow-up data migration walks every row, decrypts via MultiFernet,
   re-encrypts via the new primary).
5. Removing the old key from ``SHIFTWISE_FERNET_OLD_KEYS``.

The encryption key lives in an OpenShift Secret (``shiftwise-credential-key``)
mounted as env vars; the database NEVER stores the key (constitution FR-008).
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import settings


class CredentialVault:
    """Encrypt/decrypt strings using a rotating set of Fernet keys.

    Construct via :func:`get_vault` rather than directly; the singleton
    caches the key parse so callers do not pay the cost on every
    encrypt/decrypt.
    """

    def __init__(self, fernet: MultiFernet, key_version: int):
        self._fernet = fernet
        self._key_version = key_version

    def encrypt(self, plaintext: str) -> bytes:
        """Encrypt a string. Empty/None inputs raise ``ValueError``.

        Returns the raw Fernet token bytes; persist as ``LargeBinary``.
        """
        if not plaintext:
            raise ValueError("Cannot encrypt an empty credential")
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, ciphertext: bytes) -> str:
        """Decrypt a Fernet token. Raises ``InvalidToken`` if tampered or
        keyed by a key no longer in the rotation set.
        """
        if not ciphertext:
            raise ValueError("Cannot decrypt empty ciphertext")
        return self._fernet.decrypt(ciphertext).decode("utf-8")

    def try_decrypt(self, ciphertext: bytes | None) -> str | None:
        """Best-effort decrypt — returns ``None`` instead of raising on
        empty input or tampered ciphertext. Use this only when the caller
        has a meaningful fallback (e.g. legacy plaintext column).
        """
        if not ciphertext:
            return None
        try:
            return self.decrypt(ciphertext)
        except InvalidToken:
            return None

    @property
    def key_version(self) -> int:
        """Numeric identifier persisted alongside each ciphertext.

        Bumps by 1 whenever the primary key rotates; consumers store it
        so a future audit can correlate which key was used to encrypt
        each row.
        """
        return self._key_version

    @staticmethod
    def now_utc() -> datetime:
        """Single source of truth for the encryption timestamp."""
        return datetime.now(timezone.utc)


@lru_cache(maxsize=1)
def get_vault() -> CredentialVault:
    """Return the module-level :class:`CredentialVault` singleton.

    The first call parses the keys from settings. Subsequent calls return
    the cached instance. Call ``get_vault.cache_clear()`` after rotating
    keys at runtime (rarely needed — the standard path is a worker
    restart so a fresh process picks up the new env).
    """
    primary_key = settings.SHIFTWISE_FERNET_KEY
    raw_old = (settings.SHIFTWISE_FERNET_OLD_KEYS or "").strip()
    old_keys = [k.strip() for k in raw_old.split(",") if k.strip()]

    fernets = [Fernet(primary_key.encode())]
    for old in old_keys:
        fernets.append(Fernet(old.encode()))

    return CredentialVault(
        MultiFernet(fernets),
        key_version=1 + len(old_keys),
    )
