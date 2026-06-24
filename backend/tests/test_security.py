"""
Tests pour app.core.security — création et décodage des tokens JWT.

Couvre la migration python-jose -> PyJWT (audit H-35) : le comportement
doit être préservé — aller-retour valide, rejet des tokens corrompus et
des tokens expirés.
"""

from datetime import timedelta

from app.core.security import create_access_token, decode_token, verify_token_type


def test_access_token_round_trip():
    token = create_access_token(subject="42")
    payload = decode_token(token)
    assert payload is not None
    assert payload["sub"] == "42"
    assert payload["type"] == "access"
    assert verify_token_type(payload, "access") is True
    assert verify_token_type(payload, "refresh") is False


def test_decode_rejects_garbage_token():
    assert decode_token("not.a.real.token") is None
    assert decode_token("") is None
    assert decode_token("eyJhbGciOiJIUzI1NiJ9.tampered.signature") is None


def test_decode_rejects_expired_token():
    expired = create_access_token(subject="9", expires_delta=timedelta(seconds=-1))
    assert decode_token(expired) is None
