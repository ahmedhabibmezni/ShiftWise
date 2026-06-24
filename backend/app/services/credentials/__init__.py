"""Credential vault — Fernet-backed encryption for hypervisor secrets.

US4 production-readiness bundle. The vault wraps ``cryptography.fernet``
with rotation support so older keys can decrypt historical ciphertexts
while the current primary key encrypts new ones.

Public surface:

    from app.services.credentials import get_vault
    cipher = get_vault().encrypt("super-secret-pass")
    plain  = get_vault().decrypt(cipher)
"""

from app.services.credentials.vault import CredentialVault, get_vault

__all__ = ["CredentialVault", "get_vault"]
