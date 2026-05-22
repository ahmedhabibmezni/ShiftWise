"""
US4 — CredentialVault round-trip + rotation (T041).
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.services.credentials.vault import CredentialVault


def _vault_with_keys(*keys: bytes) -> CredentialVault:
    fernets = [Fernet(k) for k in keys]
    return CredentialVault(MultiFernet(fernets), key_version=len(keys))


def test_vault_round_trip_returns_original():
    key = Fernet.generate_key()
    vault = _vault_with_keys(key)

    cipher = vault.encrypt("super-secret-pass!")
    assert isinstance(cipher, bytes)
    assert b"super-secret-pass" not in cipher  # encrypted, not encoded

    assert vault.decrypt(cipher) == "super-secret-pass!"


def test_vault_rejects_empty_inputs():
    vault = _vault_with_keys(Fernet.generate_key())
    with pytest.raises(ValueError):
        vault.encrypt("")
    with pytest.raises(ValueError):
        vault.decrypt(b"")


def test_vault_rejects_tampered_ciphertext():
    vault = _vault_with_keys(Fernet.generate_key())
    cipher = vault.encrypt("plaintext")
    # Flip a byte in the middle of the token.
    tampered = cipher[:20] + bytes([cipher[20] ^ 0x01]) + cipher[21:]

    with pytest.raises(InvalidToken):
        vault.decrypt(tampered)


def test_try_decrypt_returns_none_on_tampered_input():
    vault = _vault_with_keys(Fernet.generate_key())
    assert vault.try_decrypt(b"") is None
    assert vault.try_decrypt(None) is None
    assert vault.try_decrypt(b"definitely-not-a-fernet-token") is None


def test_vault_supports_key_rotation_via_multifernet():
    old_key = Fernet.generate_key()
    new_key = Fernet.generate_key()

    old_vault = _vault_with_keys(old_key)
    cipher_old = old_vault.encrypt("legacy-secret")

    # New vault has the new key as primary AND the old one for read-back.
    rotated = _vault_with_keys(new_key, old_key)
    assert rotated.decrypt(cipher_old) == "legacy-secret"

    # New writes use the new key — cycling them back through the rotated
    # vault still works after the old key is dropped.
    cipher_new = rotated.encrypt("new-secret")
    new_only = _vault_with_keys(new_key)
    assert new_only.decrypt(cipher_new) == "new-secret"


def test_vault_decrypts_fail_when_old_key_dropped_too_early():
    """Sanity check on the rotation procedure: after dropping the old
    key from the rotation set, ciphertexts encrypted under it can no
    longer be decrypted. This catches an operator who rotates keys
    without re-encrypting historical rows.
    """
    old_key = Fernet.generate_key()
    new_key = Fernet.generate_key()

    old_vault = _vault_with_keys(old_key)
    cipher_old = old_vault.encrypt("legacy-secret")

    new_only = _vault_with_keys(new_key)
    with pytest.raises(InvalidToken):
        new_only.decrypt(cipher_old)


def test_key_version_reflects_rotation_set_size():
    one = _vault_with_keys(Fernet.generate_key())
    two = _vault_with_keys(Fernet.generate_key(), Fernet.generate_key())

    assert one.key_version == 1
    assert two.key_version == 2
