#!/usr/bin/env python3
"""Regenerate frontend/public/og.png, the social preview card.

This is the image Reddit, Hacker News, Slack, and X show when the link is
shared — which is most of the launch plan — so it is worth keeping
reproducible rather than hand-edited. PNG rather than SVG deliberately: most
platforms will not render an SVG og:image.

    python3 tools/make_og_image.py

Requires Pillow. The numbers are baked in rather than read from the database:
this runs at build time, not request time, and a stale "267" is better than a
build step that needs a live connection. Update them when they drift.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1200, 630

# Matches the light palette in frontend/src/styles.css.
BG, INK, ACCENT, MUTED = "#fbfaf9", "#16161a", "#1f5e46", "#6b7280"

COMPANIES = "267"
ROLES = "50,000+"

FONT_DIR = Path("/System/Library/Fonts/Supplemental")


def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    name = "Arial Bold.ttf" if bold else "Arial.ttf"
    return ImageFont.truetype(str(FONT_DIR / name), size)


def main() -> None:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    d = ImageDraw.Draw(img)

    d.rectangle([0, 0, WIDTH, 8], fill=ACCENT)

    # Wordmark, two-toned like the site's header.
    d.text((80, 74), "job", font=font(34), fill=INK)
    d.text((80 + d.textlength("job", font=font(34)), 74), "watch", font=font(34), fill=ACCENT)

    d.text((80, 208), "Every software job,", font=font(76), fill=INK)
    d.text((80, 300), "the day it’s posted", font=font(76), fill=ACCENT)
    d.text(
        (80, 416),
        "Read straight from the source career pages. New means new.",
        font=font(27, bold=False),
        fill=MUTED,
    )

    for x, big, small in (
        (80, COMPANIES, "companies tracked"),
        (400, ROLES, "roles indexed"),
        (760, "Daily", "email digest"),
    ):
        d.text((x, 508), big, font=font(40), fill=INK)
        d.text((x, 560), small, font=font(24, bold=False), fill=MUTED)

    out = Path(__file__).resolve().parent.parent / "frontend" / "public" / "og.png"
    img.save(out, "PNG", optimize=True)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
