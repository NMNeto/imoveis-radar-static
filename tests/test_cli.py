from __future__ import annotations

import json

from imoveis_radar import cli
from imoveis_radar.publish import load_previous_items


def test_cli_builds_and_validates(paths):
    code = cli.main(
        [
            "--skip-collect",
            "--no-geocode",
            "--allow-source-drop",
            "--chunk-size",
            "100",
            "--project-root",
            str(paths.root),
            "--data-dir",
            str(paths.data),
            "--public-dir",
            str(paths.public),
            "--json",
        ]
    )
    assert code == 0
    manifest = json.loads((paths.public_data / "manifest.json").read_text(encoding="utf-8"))
    items = load_previous_items(paths)
    assert manifest["total"] == 6
    assert len(items) == 6
    assert (paths.public_data / "busca_imoveis.csv").exists()
    assert any(item["id"] == "1001" for item in items)

    code = cli.main(
        [
            "--validate-only",
            "--project-root",
            str(paths.root),
            "--data-dir",
            str(paths.data),
            "--public-dir",
            str(paths.public),
        ]
    )
    assert code == 0


def test_cli_dry_run_does_not_publish(paths):
    code = cli.main(
        [
            "--skip-collect",
            "--no-geocode",
            "--allow-source-drop",
            "--dry-run",
            "--chunk-size",
            "100",
            "--project-root",
            str(paths.root),
            "--data-dir",
            str(paths.data),
            "--public-dir",
            str(paths.public),
            "--json",
        ]
    )
    assert code == 0
    assert not (paths.public_data / "manifest.json").exists()


def test_cli_generates_sitemap_from_published_pages(paths):
    (paths.public / "index.html").write_text(
        "<html><body>home</body></html>", encoding="utf-8"
    )
    (paths.public / "404.html").write_text(
        '<html><head><meta name="robots" content="noindex"></head></html>',
        encoding="utf-8",
    )
    code = cli.main(
        [
            "--skip-collect",
            "--no-geocode",
            "--allow-source-drop",
            "--chunk-size",
            "100",
            "--project-root",
            str(paths.root),
            "--data-dir",
            str(paths.data),
            "--public-dir",
            str(paths.public),
            "--json",
        ]
    )
    assert code == 0
    sitemap = (paths.public / "sitemap.xml").read_text(encoding="utf-8")
    assert "<loc>https://imovanta.com.br/</loc>" in sitemap
    assert "404" not in sitemap
