from __future__ import annotations

from pathlib import Path

from imoveis_radar.collect import CollectionContext, collect_all, download_caixa
from imoveis_radar.config import RunOptions


class FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_skip_collect_uses_existing_files(paths):
    options = RunOptions(skip_collect=True, sources=("caixa", "bb"), allow_source_drop=True)
    context = CollectionContext()
    try:
        statuses, successful = collect_all(paths, options, context, persist=False)
    finally:
        context.cleanup()
    assert successful == {"caixa", "bb"}
    assert statuses["caixa"].rows == 3
    assert statuses["bb"].rows == 1


def test_caixa_download_success_is_atomic(paths, monkeypatch):
    raw = paths.raw_csv("caixa").read_bytes()

    def fake_get(*args, **kwargs):
        return FakeResponse(raw)

    monkeypatch.setattr("imoveis_radar.collect.requests.get", fake_get)
    options = RunOptions(allow_source_drop=True, http_retries=1, min_caixa_bytes=1)
    context = CollectionContext()
    try:
        status = download_caixa(paths, options, context, persist=True)
    finally:
        context.cleanup()
    assert status.ok
    assert status.rows == 3
    assert paths.raw_csv("caixa").read_bytes() == raw


def test_caixa_captcha_keeps_previous(paths, monkeypatch):
    raw = paths.raw_csv("caixa").read_bytes()

    def fake_get(*args, **kwargs):
        return FakeResponse(b"<html>captcha</html>" + b"x" * 200_000)

    monkeypatch.setattr("imoveis_radar.collect.requests.get", fake_get)
    options = RunOptions(allow_source_drop=True, http_retries=1)
    context = CollectionContext()
    try:
        status = download_caixa(paths, options, context, persist=True)
    finally:
        context.cleanup()
    assert status.ok is False
    assert paths.raw_csv("caixa").read_bytes() == raw
    assert "CAPTCHA" in (status.last_error or "")
