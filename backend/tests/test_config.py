"""
Tests de validation pour app.core.config.Settings.

Couvre le durcissement de SECRET_KEY (audit C-01) : l'application doit
refuser de démarrer avec une SECRET_KEY faible, trop courte, ou laissée
à une valeur par défaut/placeholder.
"""

import pytest
from pydantic import ValidationError

from app.core.config import Settings

# Champs obligatoires (sans défaut) requis pour instancier Settings.
_REQUIRED = {
    "DATABASE_HOST": "localhost",
    "DATABASE_NAME": "shiftwise_test",
    "DATABASE_USER": "user",
    "DATABASE_PASSWORD": "pw",
}

_STRONG_KEY = "k" * 48


def _settings(**overrides):
    """Construit une instance Settings sans lire le fichier .env du disque."""
    return Settings(_env_file=None, **{**_REQUIRED, **overrides})


def test_secret_key_strong_value_accepted():
    """Une clé forte (>= 32 caractères, non-placeholder) est acceptée."""
    s = _settings(SECRET_KEY=_STRONG_KEY)
    assert s.SECRET_KEY == _STRONG_KEY


def test_secret_key_too_short_rejected():
    """Une SECRET_KEY de moins de 32 caractères est rejetée."""
    with pytest.raises(ValidationError):
        _settings(SECRET_KEY="short-key-1234")


@pytest.mark.parametrize("weak", [
    "GENEREZ_UNE_CLE_SECRETE_ICI",
    "dev-only-secret-not-for-production",
    "changeme",
    "secret",
])
def test_secret_key_known_placeholder_rejected(weak):
    """Les valeurs par défaut connues sont rejetées même si assez longues."""
    with pytest.raises(ValidationError):
        _settings(SECRET_KEY=weak)


def test_secret_key_is_required(monkeypatch):
    """Omettre SECRET_KEY doit échouer — aucun repli silencieux non sécurisé."""
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **_REQUIRED)
