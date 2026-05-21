"""
US4 — REFRESH_COOKIE_DOMAIN host-only guard (T043, T049).

The constitution forbids a wildcard-subdomain cookie scope. The startup
guard in ``app.main`` MUST refuse to start if ``REFRESH_COOKIE_DOMAIN``
is set to a non-empty value, regardless of how it was supplied.
"""

from __future__ import annotations

import importlib
import logging
import sys

import pytest


def _reload_main_with_cookie_domain(monkeypatch, value: str | None):
    """Force-reload app.main with a patched setting and capture exits."""
    from app.core import config as config_module

    monkeypatch.setattr(
        config_module.settings,
        "REFRESH_COOKIE_DOMAIN",
        value,
        raising=False,
    )
    # Ensure a fresh import so the startup guard runs against the patched value.
    if "app.main" in sys.modules:
        del sys.modules["app.main"]


def test_empty_cookie_domain_does_not_block_startup(monkeypatch, caplog):
    _reload_main_with_cookie_domain(monkeypatch, None)
    caplog.set_level(logging.CRITICAL)

    # Importing should not call sys.exit.
    import app.main  # noqa: F401 — import is the assertion

    critical = [r for r in caplog.records if r.levelno >= logging.CRITICAL]
    assert not any(
        "REFRESH_COOKIE_DOMAIN" in r.getMessage() for r in critical
    )


def test_populated_cookie_domain_aborts_startup(monkeypatch, caplog):
    _reload_main_with_cookie_domain(
        monkeypatch, ".apps.migration.nextstep-it.com",
    )
    caplog.set_level(logging.CRITICAL)

    with pytest.raises(SystemExit) as exc_info:
        import app.main  # noqa: F401 — import triggers the guard

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
    _reload_main_with_cookie_domain(monkeypatch, "")
    caplog.set_level(logging.CRITICAL)

    import app.main  # noqa: F401

    critical = [r for r in caplog.records if r.levelno >= logging.CRITICAL]
    assert not any(
        "REFRESH_COOKIE_DOMAIN" in r.getMessage() for r in critical
    )
