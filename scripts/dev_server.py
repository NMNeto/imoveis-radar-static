#!/usr/bin/env python3
"""Servidor local de pré-visualização do site estático.

Serve ``public/`` e implementa o mesmo ``/api/image`` da Pages Function para
que as imagens de BB/Santander/Itaú apareçam durante os testes e screenshots.
Não faz parte do deploy.
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import os
import tempfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_HOSTS = {
    "shi.santander.com.br",
    "www.seuimovelbb.com.br",
    "cdn.frazaoleiloes.com.br",
    "imagens.portalzuk.com.br",
    "cdn1.megaleiloes.com.br",
    "cdn-biasi.blueintra.com",
    "armazupleilaovipprd.blob.core.windows.net",
    "www.itau.com.br",
}
MAX_BYTES = 20 * 1024 * 1024
CACHE_DIR = PROJECT_ROOT / "data" / "logs" / "image-cache"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/158.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("dev-server")


def load_header_rules(public_dir: Path):
    """Lê o _headers do Pages para o preview local refletir produção."""
    path = public_dir / "_headers"
    if not path.exists():
        return []
    rules = []
    current = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if not raw[0].isspace():
            current = (raw.strip(), [])
            rules.append(current)
            continue
        if current is not None and ":" in raw:
            name, value = raw.strip().split(":", 1)
            current[1].append((name.strip(), value.strip()))
    return rules


def load_redirect_rules(public_dir: Path):
    """Lê o _redirects do Pages (formato: origem destino [status])."""
    path = public_dir / "_redirects"
    if not path.exists():
        return []
    rules = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        status = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 302
        rules.append((parts[0], parts[1], status))
    return rules


def match_redirect(rules, path: str):
    for source, target, status in rules:
        if source == path:
            return target, status
        if "*" in source and source.count("*") == 1:
            prefix, suffix = source.split("*", 1)
            if path.startswith(prefix) and path.endswith(suffix):
                middle = path[len(prefix) : len(path) - len(suffix) if suffix else None]
                return target.replace(":splat", middle), status
    return None


def _matches(pattern: str, path: str) -> bool:
    path = path.split("?", 1)[0]
    if pattern == "/*":
        return True
    if pattern.endswith("*"):
        return path.startswith(pattern[:-1])
    return path == pattern


class Handler(SimpleHTTPRequestHandler):
    header_rules = []
    redirect_rules = []

    def __init__(self, *args, directory: str | None = None, **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    def end_headers(self):
        # Aplica as regras do _headers no preview local (mesmo formato do
        # Cloudflare Pages). O deploy real continua usando public/_headers.
        for pattern, headers in self.header_rules:
            if _matches(pattern, self.path):
                for name, value in headers:
                    self.send_header(name, value)
        super().end_headers()

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/image":
            self._serve_image(parse_qs(parsed.query))
            return
        rule = match_redirect(self.redirect_rules, parsed.path)
        if rule:
            target, status = rule
            if 300 <= status < 400:
                self.send_response(status)
                self.send_header("Location", target)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.path = target + (f"?{parsed.query}" if parsed.query else "")
        self._resolve_pretty_html()
        super().do_GET()

    def _resolve_pretty_html(self):
        """Reproduz o Pages: /foo serve foo.html."""
        path = urlparse(self.path).path
        if path.endswith("/") or "." in Path(path).name:
            return
        candidate = Path(self.directory) / path.lstrip("/")
        if candidate.is_file():
            return
        html = candidate.with_name(candidate.name + ".html")
        if html.is_file():
            self.path = path + ".html"

    def _serve_image(self, query):
        values = query.get("url") or []
        if not values:
            self._json(400, {"ok": False, "error": "Parâmetro url obrigatório"})
            return
        target = values[0]
        parsed = urlparse(target)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in ALLOWED_HOSTS
            or (parsed.port not in (None, 443))
        ):
            self._json(400, {"ok": False, "error": "URL de imagem não permitida"})
            return
        key = hashlib.sha256(target.encode("utf-8")).hexdigest()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        for candidate in CACHE_DIR.glob(f"{key}.*"):
            self._send_file(candidate)
            return
        try:
            response = requests.get(target, headers=HEADERS, timeout=25, stream=True)
            response.raise_for_status()
            content_type = (
                (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            )
            if not content_type.startswith("image/"):
                raise ValueError(f"conteúdo não é imagem: {content_type!r}")
            extension = {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/webp": ".webp",
                "image/gif": ".gif",
            }.get(content_type, ".img")
            with tempfile.NamedTemporaryFile(
                "wb", dir=CACHE_DIR, delete=False
            ) as handle:
                size = 0
                for chunk in response.iter_content(64 * 1024):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ValueError("imagem maior que 20 MB")
                    handle.write(chunk)
                temp_name = handle.name
            path = CACHE_DIR / f"{key}{extension}"
            os.replace(temp_name, path)
            self._send_file(path)
        except Exception as exc:
            logger.warning("Falha na imagem %s: %s", target, exc)
            self._json(502, {"ok": False, "error": "Não foi possível carregar a imagem"})

    def _send_file(self, path: Path):
        content_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }.get(path.suffix.lower(), "application/octet-stream")
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=604800")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status: int, payload: dict):
        import json

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):  # noqa: A002
        logger.info("%s - %s", self.address_string(), format % args)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--public", type=Path, default=PROJECT_ROOT / "public")
    args = parser.parse_args()
    Handler.header_rules = load_header_rules(args.public)
    Handler.redirect_rules = load_redirect_rules(args.public)
    handler = lambda *a, **kw: Handler(*a, directory=str(args.public), **kw)  # noqa: E731
    server = ThreadingHTTPServer((args.host, args.port), handler)
    logger.info("Servindo %s em http://%s:%s", args.public, args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
