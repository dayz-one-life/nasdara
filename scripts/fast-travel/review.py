"""Draw every town's arrival points on the topographic map, for eyeballing.

Needs Pillow. Run from the repo root after generate.py:
    python3 scripts/fast-travel/review.py --cache /tmp/nasdara-tiles --out /tmp/fast-travel-review
Writes review-1.png, review-2.png, ... (12 towns each): a 660 m square per
town at zoom 6, the town centre as a black cross and each arrival point as a
red ring.
"""
import argparse
import json
import math
import re
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
URL = "https://static.xam.nu/dayz/maps/nasdara/26.10.15/topographic/{z}/{x}/{y}.webp"
# xam.nu answers 403 without a Referer from its own site.
HEADERS = {"Referer": "https://xam.nu/", "User-Agent": "Mozilla/5.0"}
ZOOM = 6
PX = 256 * 2 ** ZOOM
WORLD_M = 16384.0
HALF = 330      # metres either side of the town centre
CELL = 420


def tile(cache, x, y):
    p = cache / f"{ZOOM}-{x}-{y}.webp"
    if not p.exists():
        try:
            with urllib.request.urlopen(urllib.request.Request(URL.format(z=ZOOM, x=x, y=y), headers=HEADERS), timeout=30) as r:
                p.write_bytes(r.read())
        except urllib.error.HTTPError:   # off the map edge
            return None
    return Image.open(p).convert("RGB")


def to_px(x, z):
    return x / WORLD_M * PX, (1 - z / WORLD_M) * PX


def render(town, points, cache):
    x0, y0 = map(int, to_px(town["x"] - HALF, town["z"] + HALF))
    x1, y1 = map(int, to_px(town["x"] + HALF, town["z"] - HALF))
    im = Image.new("RGB", (x1 - x0, y1 - y0), (60, 60, 60))
    for tx in range(x0 // 256, x1 // 256 + 1):
        for ty in range(y0 // 256, y1 // 256 + 1):
            t = tile(cache, tx, ty)
            if t:
                im.paste(t, (tx * 256 - x0, ty * 256 - y0))
    d = ImageDraw.Draw(im)
    cx, cy = to_px(town["x"], town["z"])
    cx, cy = cx - x0, cy - y0
    d.line((cx - 8, cy, cx + 8, cy), fill="black", width=3)
    d.line((cx, cy - 8, cx, cy + 8), fill="black", width=3)
    for x, z in points:
        px, py = to_px(x, z)
        px, py = px - x0, py - y0
        d.ellipse((px - 10, py - 10, px + 10, py + 10), outline="red", width=4)
    im = im.resize((CELL, CELL))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, len(town["name"]) * 7 + 10, 16), fill="white")
    d.text((5, 2), town["name"], fill="black")
    return im


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    a.cache.mkdir(parents=True, exist_ok=True)
    a.out.mkdir(parents=True, exist_ok=True)
    cells = []
    for town in json.loads((HERE / "towns.json").read_text()):
        slug = re.sub(r"[^a-z0-9]+", "-", town["name"].lower()).strip("-")
        pra = json.loads((ROOT / f"custom/pra-teleport-{slug}.json").read_text())
        cells.append(render(town, pra["safePositions2D"], a.cache))
    cols, per = 4, 12
    for n, start in enumerate(range(0, len(cells), per), 1):
        part = cells[start:start + per]
        sheet = Image.new("RGB", (cols * (CELL + 4), math.ceil(len(part) / cols) * (CELL + 4)), "white")
        for i, c in enumerate(part):
            sheet.paste(c, ((i % cols) * (CELL + 4), (i // cols) * (CELL + 4)))
        sheet.save(a.out / f"review-{n}.png")
        print(a.out / f"review-{n}.png")


if __name__ == "__main__":
    main()
