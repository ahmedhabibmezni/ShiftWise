"""
Tests pour le script d'initialisation backend/init_db.py.

Couvre :
- H-04 : l'email admin par défaut doit être un email valide, acceptable par
  le schéma de connexion — sinon le compte seedé ne peut jamais
  s'authentifier (un TLD réservé comme .local est rejeté par EmailStr).
- H-05 : aucun mot de passe par défaut — _prompt_password redemande la
  saisie tant qu'elle est vide ou trop faible.
"""

import pytest

import init_db
from app.schemas.auth import LoginRequest


def test_default_admin_email_is_a_valid_login_email():
    # H-04 : un .local (ou tout TLD réservé) serait rejeté par EmailStr.
    request = LoginRequest(email=init_db.DEFAULT_ADMIN_EMAIL, password="x")
    assert request.email == init_db.DEFAULT_ADMIN_EMAIL


def test_no_default_admin_password_constant():
    # H-05 : la constante de mot de passe par défaut a été supprimée.
    assert not hasattr(init_db, "DEFAULT_ADMIN_CREDENTIALS")


def test_prompt_password_requires_a_strong_value(monkeypatch):
    # Vide, puis faible, puis forte : _prompt_password ne doit accepter que
    # la valeur forte — jamais un repli par défaut.
    answers = iter(["", "weak", "StrongPass1"])
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: next(answers))

    result = init_db._prompt_password()

    assert result == "StrongPass1"
