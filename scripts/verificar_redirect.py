#!/usr/bin/env python3
"""Verifica o 301 de `www` para o apex.

Confere o que o Google precisa ver para tratar `www` como duplicata do apex:
DNS do host, código permanente, destino exato, preservação de caminho e query
string, e se nenhuma variante com `www` responde 200.

Uso:
    python scripts/verificar_redirect.py
    python scripts/verificar_redirect.py --apex https://imovanta.com.br
    python scripts/verificar_redirect.py --host www.imovanta.com.br --json

Sai com código 1 quando alguma verificação falha.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urljoin, urlparse

USER_AGENT = (
    "Mozilla/5.0 (compatible; ImovantaSeoCheck/1.0; +https://imovanta.com.br/)"
)
TIMEOUT = 25
REDIRECT_CODES = (301, 302, 307, 308)
PERMANENT_CODES = (301, 308)


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


_OPENER = urllib.request.build_opener(_NoRedirect())


def get(url: str, timeout: int = TIMEOUT) -> tuple[int, dict[str, str]]:
    """GET sem seguir redirecionamentos. Status 0 = falha de rede/DNS."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            headers = {key.lower(): value for key, value in response.headers.items()}
            return response.status, headers
    except urllib.error.HTTPError as exc:
        headers = {key.lower(): value for key, value in exc.headers.items()}
        return exc.code, headers
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        return 0, {"error": str(reason)}


def resolve_host(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return []
    return sorted({info[4][0] for info in infos})


def follow(
    url: str,
    fetcher: Callable[[str], tuple[int, dict[str, str]]] = get,
    max_hops: int = 6,
) -> list[tuple[str, int, str]]:
    """Segue a cadeia de redirecionamentos e devolve (url, status, location)."""
    chain: list[tuple[str, int, str]] = []
    current = url
    for _ in range(max_hops):
        status, headers = fetcher(current)
        location = headers.get("location", "")
        chain.append((current, status, location))
        if status in REDIRECT_CODES and location:
            current = urljoin(current, location)
            continue
        break
    return chain


def normalize(url: str) -> str:
    return url.rstrip("/") if urlparse(url).path not in ("", "/") else url


def check_redirect(
    apex: str = "https://imovanta.com.br",
    host: str = "www.imovanta.com.br",
    *,
    fetcher: Callable[[str], tuple[int, dict[str, str]]] = get,
    resolver: Callable[[str], list[str]] = resolve_host,
    path: str = "/imoveis/rj/rio-de-janeiro/",
    query: str = "?utm_source=www&x=1",
) -> list[Check]:
    apex = apex.rstrip("/")
    checks: list[Check] = []

    addresses = resolver(host)
    checks.append(
        Check(
            f"{host} resolve no DNS",
            bool(addresses),
            ", ".join(addresses) if addresses else "NXDOMAIN (sem registro A/CNAME)",
        )
    )

    apex_status, _ = fetcher(apex + "/")
    checks.append(Check("Apex responde 200", apex_status == 200, f"status {apex_status}"))

    root_chain = follow(f"https://{host}/", fetcher)
    root_url, root_status, root_location = root_chain[0]
    checks.append(
        Check(
            "Raiz com www redireciona de forma permanente",
            root_status in PERMANENT_CODES,
            f"status {root_status}" + (f" -> {root_location}" if root_location else ""),
        )
    )
    checks.append(
        Check(
            "Redirecionamento da raiz aponta para o apex",
            normalize(root_location) == apex + "/",
            f"{root_location or '(sem Location)'} (esperado {apex}/)",
        )
    )

    path_chain = follow(f"https://{host}{path}", fetcher)
    _, path_status, path_location = path_chain[0]
    checks.append(
        Check(
            "Caminho é preservado no redirecionamento",
            path_status in PERMANENT_CODES and urlparse(path_location).path.rstrip("/") == path.rstrip("/"),
            f"{path_status} -> {path_location or '(sem Location)'}",
        )
    )

    query_chain = follow(f"https://{host}{path}{query}", fetcher)
    _, query_status, query_location = query_chain[0]
    checks.append(
        Check(
            "Query string é preservada",
            query_status in PERMANENT_CODES and "utm_source=www" in query_location,
            f"{query_status} -> {query_location or '(sem Location)'}",
        )
    )

    http_chain = follow(f"http://{host}/", fetcher)
    http_final_url, http_final_status, _ = http_chain[-1]
    checks.append(
        Check(
            "http://www termina em https no apex",
            http_final_status == 200 and normalize(http_final_url) == apex + "/",
            f"{http_final_status} em {http_final_url} ({len(http_chain)} salto(s))",
        )
    )

    duplicated = []
    for candidate in ("/", "/imoveis/", "/sitemap.xml"):
        status, _ = fetcher(f"https://{host}{candidate}")
        if status == 200:
            duplicated.append(f"{candidate} -> 200")
    checks.append(
        Check(
            "Nenhuma URL com www responde 200",
            not duplicated,
            ", ".join(duplicated) if duplicated else "todas redirecionam ou falham",
        )
    )
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apex", default="https://imovanta.com.br")
    parser.add_argument("--host", default="www.imovanta.com.br")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    checks = check_redirect(args.apex, args.host)
    failures = [check for check in checks if not check.ok]

    if args.json:
        print(
            json.dumps(
                {
                    "apex": args.apex,
                    "host": args.host,
                    "ok": not failures,
                    "checks": [check.__dict__ for check in checks],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for check in checks:
            mark = "OK  " if check.ok else "FALHA"
            extra = f" — {check.detail}" if check.detail else ""
            print(f"[{mark}] {check.name}{extra}")
        print(f"\n{len(checks) - len(failures)}/{len(checks)} verificações passaram")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
