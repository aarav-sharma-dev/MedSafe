"""Shared test configuration: every test runs hermetically.

Real network calls made MedSafe's UI tests slow and flaky (page renders can
touch RxNorm, openFDA, and - once a GEMINI_API_KEY exists in `.env` - Gemini).
This fixture guarantees tests exercise the designed offline fallbacks instead:

* `GEMINI_API_KEY` is pinned to "" (config.load_dotenv never overrides an
  existing env var, so the repo `.env` cannot re-enable it mid-test).
* Outbound sockets are disabled, so any accidental network call fails fast
  and falls into the same code path as being offline.
* HTTP/AI timeouts are shrunk so even a missed patch cannot stall a run.
"""

from __future__ import annotations

import socket

import pytest

import config


@pytest.fixture(autouse=True)
def hermetic_env(monkeypatch):
    # Empty-string key reads as "not configured" and blocks .env re-injection.
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("OPENFDA_API_KEY", "")
    monkeypatch.setenv("MEDSAFE_HTTP_TIMEOUT", "2")
    monkeypatch.setenv("MEDSAFE_AI_TIMEOUT", "2")
    # config reads timeouts at import time; patch the module values too.
    monkeypatch.setattr(config, "HTTP_TIMEOUT", 2.0, raising=False)
    monkeypatch.setattr(config, "AI_TIMEOUT", 2.0, raising=False)

    def _no_network(*args, **kwargs):
        raise OSError("Outbound network is disabled during tests")

    monkeypatch.setattr(socket, "create_connection", _no_network)
    monkeypatch.setattr(socket.socket, "connect", _no_network)
    yield
