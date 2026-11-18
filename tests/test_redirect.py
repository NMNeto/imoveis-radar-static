from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from verificar_redirect import check_redirect, follow  # noqa: E402

APEX = "https://imovanta.com.br"
HOST = "www.imovanta.com.br"


def _configured(request: str) -> tuple[int, dict[str, str]]:
    """Simula Cloudflare com DNS, Always Use HTTPS e Redirect Rule 301."""
    parsed = urlparse(request)
    if parsed.scheme == "http" and parsed.netloc == HOST:
        return 301, {"location": f"https://{HOST}{parsed.path or '/'}"}
    if parsed.netloc == HOST:
        target = APEX + (parsed.path or "/")
        if parsed.query:
            target = f"{target}?{parsed.query}"
        return 301, {"location": target}
    if parsed.netloc == "imovanta.com.br":
        return 200, {}
    return 0, {"error": "NXDOMAIN"}


def _resolver(_host: str) -> list[str]:
    return ["104.21.92.14", "172.67.184.129"]


def _statuses(checks) -> dict[str, bool]:
    return {check.name: check.ok for check in checks}


def test_configured_redirect_passes_every_check():
    checks = check_redirect(APEX, HOST, fetcher=_configured, resolver=_resolver)
    assert all(check.ok for check in checks), [check for check in checks if not check.ok]


def test_missing_dns_record_is_reported():
    checks = check_redirect(APEX, HOST, fetcher=_configured, resolver=lambda _host: [])
    results = _statuses(checks)
    assert results[f"{HOST} resolve no DNS"] is False


def test_serving_200_on_www_is_flagged():
    def duplicate(request: str) -> tuple[int, dict[str, str]]:
        if urlparse(request).netloc == HOST:
            return 200, {}
        return 200, {}

    checks = check_redirect(APEX, HOST, fetcher=duplicate, resolver=_resolver)
    results = _statuses(checks)
    assert results["Nenhuma URL com www responde 200"] is False
    assert results["Raiz com www redireciona de forma permanente"] is False


def test_temporary_redirect_is_not_enough():
    def temporary(request: str) -> tuple[int, dict[str, str]]:
        parsed = urlparse(request)
        if parsed.netloc == HOST:
            return 302, {"location": APEX + (parsed.path or "/")}
        return 200, {}

    checks = check_redirect(APEX, HOST, fetcher=temporary, resolver=_resolver)
    results = _statuses(checks)
    assert results["Raiz com www redireciona de forma permanente"] is False
    assert results["Redirecionamento da raiz aponta para o apex"] is True


def test_follow_resolves_relative_locations_and_stops():
    hops = {
        "http://www.exemplo.com/": (301, {"location": "https://www.exemplo.com/"}),
        "https://www.exemplo.com/": (301, {"location": "/destino"}),
        "https://www.exemplo.com/destino": (200, {}),
    }
    chain = follow("http://www.exemplo.com/", lambda url: hops[url])
    assert [url for url, _, _ in chain] == [
        "http://www.exemplo.com/",
        "https://www.exemplo.com/",
        "https://www.exemplo.com/destino",
    ]
    assert chain[-1][1] == 200
