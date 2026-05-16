"""
Tests pour app.main — durcissement du gestionnaire d'exceptions global
(audit C-02).

Le gestionnaire ne doit JAMAIS divulguer le détail de l'exception, son
type, ni l'URL de la requête dans la réponse HTTP — même quand DEBUG=True.
Le détail complet doit être journalisé côté serveur uniquement.
"""

import asyncio
import json
from unittest.mock import MagicMock

from app.core.config import settings
from app.main import global_exception_handler


def _invoke(exc: Exception, debug: bool):
    """Appelle le gestionnaire avec une requête simulée et retourne (code, body)."""
    request = MagicMock()
    request.method = "GET"
    request.url.path = "/api/v1/secret-internal-path"

    original_debug = settings.DEBUG
    settings.DEBUG = debug
    try:
        response = asyncio.run(global_exception_handler(request, exc))
    finally:
        settings.DEBUG = original_debug
    return response.status_code, json.loads(response.body)


def test_handler_never_leaks_exception_detail():
    """Ni le message, ni le type, ni l'URL ne doivent apparaître dans la réponse."""
    for debug in (True, False):
        status_code, body = _invoke(
            RuntimeError("psql FATAL: password authentication failed for db-host"),
            debug,
        )
        assert status_code == 500
        serialized = json.dumps(body)
        assert "psql" not in serialized, f"exception message leaked (debug={debug})"
        assert "RuntimeError" not in serialized, f"exception type leaked (debug={debug})"
        assert "secret-internal-path" not in serialized, f"request path leaked (debug={debug})"
        assert body.get("detail"), "a generic error message must still be present"


def test_handler_returns_correlation_id():
    """La réponse doit fournir un identifiant de corrélation pour le support."""
    _, body = _invoke(ValueError("boom"), debug=False)
    assert "correlation_id" in body
    assert len(body["correlation_id"]) >= 8
