"""Generate the Polenta Meeting Notes app icon.

A bowl of polenta on a warm golden field, with three steam wisps rising like
sound waves: local speech, gently captured. Draws the 1024-pixel master with
Pillow, renders the iconset sizes, and assembles AppIcon.icns with iconutil.

A build-time developer step. Run from the backend directory:

    uv run python ../scripts/make_icon.py
"""

from __future__ import annotations

import math
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[1]
SUPPORT = REPO / "app" / "Support"

S = 1024
MARGIN = 100
RADIUS = 210

GOLD_TOP = (255, 205, 66)
GOLD_BOTTOM = (224, 145, 18)
CREAM = (255, 247, 224)
POLENTA = (255, 224, 130)
BOWL = (252, 252, 245)
BOWL_SHADOW = (233, 226, 205)
STEAM = (255, 255, 255, 235)


def rounded_gold_field() -> Image.Image:
    """The macOS-style rounded square with a vertical golden gradient."""
    gradient = Image.new("RGBA", (S, S))
    for y in range(S):
        t = y / (S - 1)
        row = tuple(
            round(GOLD_TOP[i] + (GOLD_BOTTOM[i] - GOLD_TOP[i]) * t) for i in range(3)
        )
        gradient.paste(Image.new("RGBA", (S, 1), row + (255,)), (0, y))

    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (MARGIN, MARGIN, S - MARGIN, S - MARGIN), radius=RADIUS, fill=255
    )
    field = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    field.paste(gradient, mask=mask)
    return field


def draw_bowl(draw: ImageDraw.ImageDraw) -> None:
    cx = S // 2
    rim_y = 560
    bowl_w = 480

    # The mound of polenta cresting over the rim.
    draw.ellipse((cx - 195, rim_y - 105, cx + 195, rim_y + 45), fill=POLENTA)

    # The bowl: the lower half of an ellipse, with a soft base.
    draw.pieslice(
        (cx - bowl_w // 2, rim_y - 190, cx + bowl_w // 2, rim_y + 260),
        start=0, end=180, fill=BOWL,
    )
    draw.rounded_rectangle((cx - 110, rim_y + 244, cx + 110, rim_y + 292),
                           radius=24, fill=BOWL_SHADOW)
    # The rim.
    draw.ellipse((cx - bowl_w // 2, rim_y - 32, cx + bowl_w // 2, rim_y + 40),
                 fill=BOWL)
    draw.ellipse((cx - bowl_w // 2 + 26, rim_y - 18, cx + bowl_w // 2 - 26, rim_y + 26),
                 fill=POLENTA)


def draw_steam(image: Image.Image) -> None:
    """Three wisps, each a gentle sine curve, rising off the bowl."""
    overlay = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for offset, (top, bottom) in zip((-118, 0, 118), ((250, 430), (205, 415), (250, 430))):
        cx = S // 2 + offset
        points = []
        for step in range(41):
            t = step / 40
            y = bottom - (bottom - top) * t
            x = cx + 26 * math.sin(t * math.pi * 1.75)
            points.append((x, y))
        draw.line(points, fill=STEAM, width=30, joint="curve")
        draw.ellipse((points[0][0] - 15, points[0][1] - 15,
                      points[0][0] + 15, points[0][1] + 15), fill=STEAM)
        draw.ellipse((points[-1][0] - 15, points[-1][1] - 15,
                      points[-1][0] + 15, points[-1][1] + 15), fill=STEAM)
    image.alpha_composite(overlay)


def build_master() -> Image.Image:
    image = rounded_gold_field()
    draw = ImageDraw.Draw(image)
    draw_bowl(draw)
    draw_steam(image)
    return image


def write_icns(master: Image.Image) -> None:
    SUPPORT.mkdir(parents=True, exist_ok=True)
    master.save(SUPPORT / "AppIcon.png")

    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "AppIcon.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            master.resize((size, size), Image.LANCZOS).save(
                iconset / f"icon_{size}x{size}.png")
            master.resize((size * 2, size * 2), Image.LANCZOS).save(
                iconset / f"icon_{size}x{size}@2x.png")
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(SUPPORT / "AppIcon.icns")],
            check=True,
        )
    print("wrote", SUPPORT / "AppIcon.icns")


if __name__ == "__main__":
    write_icns(build_master())
