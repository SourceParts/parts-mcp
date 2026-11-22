"""
The landing-page doc/wip endpoints only accept our services (X-Internal-Secret)
or signed-in internal users. The MCP server must send the internal secret from
its environment when it has one, and must never send it otherwise.
"""
from __future__ import annotations

from typing import Any

import pytest

from parts_mcp.tools import wip


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return {"ok": True}


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    calls: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> _Response:
        calls["post"] = (url, kwargs["headers"])
        return _Response()

    def fake_get(url: str, **kwargs: Any) -> _Response:
        calls["get"] = (url, kwargs["headers"])
        return _Response()

    monkeypatch.setattr(wip.httpx, "post", fake_post)
    monkeypatch.setattr(wip.httpx, "get", fake_get)
    return calls


def test_post_sends_internal_secret_when_configured(monkeypatch, captured):
    monkeypatch.setenv("PARTS_INTERNAL_SECRET", "s3cret")
    wip._landing_post("/api/pdf/doc/wip/send", json_payload={"a": 1})
    _, headers = captured["post"]
    assert headers["X-Internal-Secret"] == "s3cret"


def test_get_sends_internal_secret_when_configured(monkeypatch, captured):
    monkeypatch.setenv("PARTS_INTERNAL_SECRET", "s3cret")
    wip._landing_get("/api/pdf/doc/wip/history", params={"client": "x"})
    _, headers = captured["get"]
    assert headers["X-Internal-Secret"] == "s3cret"


def test_no_secret_header_without_configuration(monkeypatch, captured):
    monkeypatch.delenv("PARTS_INTERNAL_SECRET", raising=False)
    wip._landing_post("/api/pdf/doc/wip/send", json_payload={"a": 1})
    _, headers = captured["post"]
    assert "X-Internal-Secret" not in headers


def test_blank_secret_is_not_sent(monkeypatch, captured):
    monkeypatch.setenv("PARTS_INTERNAL_SECRET", "   ")
    wip._landing_get("/api/pdf/doc/wip/history")
    _, headers = captured["get"]
    assert "X-Internal-Secret" not in headers
