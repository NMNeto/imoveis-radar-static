#!/usr/bin/env python3
"""Gera a imagem de compartilhamento (Open Graph) de 1200x630.

Uso:
    python scripts/gerar_og_image.py
    python scripts/gerar_og_image.py --out public/static/og-image.png

A imagem é um asset estático: só precisa ser regerada quando a marca mudar.
Requer Pillow (requirements-dev.txt).
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WIDTH, HEIGHT = 1200, 630
BG = "#ffffff"
NAVY = "#0b2f6f"
MUTED = "#66707a"
ORANGE = "#f26b0f"
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / name), size)


def _centered(draw: ImageDraw.ImageDraw, text: str, font, y: int, fill: str) -> None:
    left, _, right, _ = draw.textbbox((0, 0), text, font=font)
    draw.text(((WIDTH - (right - left)) / 2 - left, y), text, font=font, fill=fill)


def build(logo_path: Path) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)

    logo = Image.open(logo_path).convert("RGBA")
    logo_width = 560
    logo_height = round(logo.height * logo_width / logo.width)
    logo = logo.resize((logo_width, logo_height), Image.LANCZOS)
    image.paste(logo, ((WIDTH - logo_width) // 2, 74), logo)

    _centered(
        draw,
        "Imóveis de leilão e retomados",
        _font("DejaVuSans-Bold.ttf", 54),
        350,
        NAVY,
    )
    _centered(
        draw,
        "Caixa · Banco do Brasil · Santander · Itaú",
        _font("DejaVuSans.ttf", 32),
        432,
        MUTED,
    )
    _centered(
        draw,
        "imovanta.com.br",
        _font("DejaVuSans-Bold.ttf", 28),
        520,
        MUTED,
    )
    draw.rectangle([0, HEIGHT - 14, WIDTH, HEIGHT], fill=ORANGE)
    return image


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--logo",
        type=Path,
        default=PROJECT_ROOT / "public" / "static" / "logo-imovanta.png",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "public" / "static" / "og-image.png",
    )
    args = parser.parse_args(argv)
    image = build(args.logo)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.out, format="PNG", optimize=True)
    print(f"Imagem gerada: {args.out} ({image.width}x{image.height})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
