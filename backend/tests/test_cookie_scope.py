"""
US4 — REFRESH_COOKIE_DOMAIN host-only guard (T043, T049).

The constitution forbids a wildcard-subdomain cookie scope. The lifespan
guard in ``app.main`` MUST refuse to start the FastAPI process if
``REFRESH_COOKIE_DOMAIN`` is set to a non-empty value, regardless of
how it was supplied.

The guard runs in the FastAPI ``lifespan`` (not at module import) so
that Celery workers and ad-hoc scripts importing ``app.main``
transitively do NOT get killed by an API-layer setting. Tests exercise
the guard by driving the lifespan generator directly.
"""

from __future__ import annotations

import asyncio
import logging

import pytest


async def _run_lifespan_once() -> None:
    """Enter ``app.main.lifespan(app)`` and immediately exit.

    Any ``sys.exit`` raised in the startup block propagates out of the
    ``async with`` as a ``SystemExit`` exception, which the test catches.
    """
    from app.main import app, lifespan

    async with lifespan(app):
        return None


def _patch_cookie_domain(monkeypatch, value: str | None) -> None:
    from app.core import config as config_module

    monkeypatch.setattr(
        config_module.settings,
        "REFRESH_COOKIE_DOMAIN",
        value,
        raising=False,
    )


def test_empty_cookie_domain_does_not_block_startup(monkeypatch, caplog):
    _patch_cookie_domain(monkeypatch, None)
    caplog.set_level(logging.CRITICAL)

    asyncio.run(_run_lifespan_once())

    critical = [r for r in caplog.records if r.levelno >= logging.CRITICAL]
    assert not any(
        "REFRESH_COOKIE_DOMAIN" in r.getMessage() for r in critical
    )


def test_populated_cookie_domain_aborts_startup(monkeypatch, caplog):
    _patch_cookie_domain(monkeypatch, ".apps.migration.nextstep-it.com")
    caplog.set_level(logging.CRITICAL)

    with pytest.raises(SystemExit) as exc_info:
        asyncio.run(_run_lifespan_once())

    assert exc_info.value.code == 1
    assert any(
        "REFRESH_COOKIE_DOMAIN" in r.getMessage()
        for r in caplog.records
        if r.levelno >= logging.CRITICAL
    )


def test_empty_string_cookie_domain_is_treated_as_unset(monkeypatch, caplog):
    """An operator who passes the env var as `REFRESH_COOKIE_DOMAIN=` (no
    value) must not be punished — empty string is "unset" in production
    deployment overlays where the variable is declared but blank.
    """
    _patch_cookie_domain(monkeypatch, "")
    caplog.set_level(logging.CRITICAL)

    asyncio.run(_run_lifespan_once())

    critical = [r for r in caplog.records if r.levelno >= logging.CRITICAL]
    assert not any(
        "REFRESH_COOKIE_DOMAIN" in r.getMessage() for r in critical
    )


def test_celery_worker_importing_app_main_does_not_exit(monkeypatch):
    """Regression — the previous module-level guard killed any process
    that imported ``app.main`` (including Celery workers that pulled it
    in transitively). The lifespan-scoped guard must NOT fire on a bare
    import.
    """
    _patch_cookie_domain(monkeypatch, ".apps.example.com")
    # A bare import must not raise SystemExit even with the bad setting.
    import app.main  # noqa: F401 — the import itself is the assertion
