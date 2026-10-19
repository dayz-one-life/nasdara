"""One-off: build the masks generate.py reads from xam.nu's Nasdara
topographic tiles.

- water-mask.pbm (zoom 4, 4 m/px): lakes and pools (there is no sea).
- structure-mask.pbm.gz (zoom 5, 2 m/px): anything drawn dark grey or in a
  strong non-green colour: buildings (including the non-lootable ones
  mapgrouppos.xml leaves out), piers, docks, rail track, roads, shipping
  containers, vehicles.

Not imported by generate.py (which stays stdlib-only). Needs Pillow:
    python3 -m pip install pillow
Run from the repo root:
    python3 scripts/fast-travel/build_masks.py --cache /tmp/nasdara-tiles

Tile source is the one dzmap and the one-life site use. The zoom-0 tile is the
whole 16384 m map with no margin, so pixel (i, j) at zoom Z is world
x = i * 16384 / (256 * 2^Z), z = 16384 - j * 16384 / (256 * 2^Z). Checked
against mapgrouppos.xml: house and shed origins land on the buildings the
tiles draw at that alignment.

Nasdara's hill shading is grey too. Buildings draw at grey 80-120 and the
darkest shadow at 130+, so the grey cutoff is 140, not Chernarus's 175, which
flagged whole mountainsides.
"""
import argparse
import gzip
import io
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
URL = "https://static.xam.nu/dayz/maps/nasdara/26.10.15/topographic/{z}/{x}/{y}.webp"
# xam.nu answers 403 without a Referer from its own site.
HEADERS = {"Referer": "https://xam.nu/", "User-Agent": "Mozilla/5.0"}


def is_water(rgb):
    r, g, b = rgb
    return b > r + 25 and b > g + 5 and b > 150


def is_structure(rgb):
    r, g, b = rgb
    hi, lo = max(rgb), min(rgb)
    if hi < 140 and hi - lo < 40:          # dark grey/black: buildings, rail (not hill shade)
        return True
    if lo >= 245:                          # white: bridges and overpasses (terrain tops out ~235)
        return True
    if is_water(rgb) or (g >= r and g >= b):  # water has its own mask; green is vegetation
        return False
    # Strong colour: red/brown roofs, roads, shipping containers, vehicles.
    return hi - lo > 60


def fetch(cache, z, x, y):
    p = cache / f"{z}-{x}-{y}.webp"
    if not p.exists():
        try:
            with urllib.request.urlopen(urllib.request.Request(URL.format(z=z, x=x, y=y), headers=HEADERS), timeout=30) as r:
                p.write_bytes(r.read())
        except urllib.error.HTTPError:
            return None
    return Image.open(io.BytesIO(p.read_bytes())).convert("RGB")


def build(cache, zoom, test):
    tiles = 2 ** zoom
    size = tiles * 256
    bits = bytearray(size * size // 8)
    for ty in range(tiles):
        for tx in range(tiles):
            im = fetch(cache, zoom, tx, ty)
            if im is None:
                continue
            px = im.load()
            for j in range(256):
                for i in range(256):
                    if test(px[i, j]):
                        k = (ty * 256 + j) * size + tx * 256 + i
                        bits[k >> 3] |= 0x80 >> (k & 7)
    return f"P4\n{size} {size}\n".encode() + bytes(bits)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, required=True)
    a = ap.parse_args()
    a.cache.mkdir(parents=True, exist_ok=True)
    (HERE / "water-mask.pbm").write_bytes(build(a.cache, 4, is_water))
    with gzip.open(HERE / "structure-mask.pbm.gz", "wb", compresslevel=9) as f:
        f.write(build(a.cache, 5, is_structure))
    print("wrote water-mask.pbm and structure-mask.pbm.gz")


if __name__ == "__main__":
    main()
