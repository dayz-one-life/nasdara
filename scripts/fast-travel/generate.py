"""Generate the fast-travel PRA files from towns.json and the map.

Run from the repo root:  python3 scripts/fast-travel/generate.py
Stdlib only. Writes, under custom/:

- pra-teleport-hub.json: a box on every Land_Shed_W1 in mapgrouppos.xml,
  each sending the player into the sky hub.
- pra-teleport-<slug>.json: a box on that town's toilet in the hub, sending the
  player to one of POINTS spots around the town, as safePositions2D (the engine
  puts the player at ground height, SurfaceY).
- labels.json beside this file: toilet position -> hub label, for the
  dayz-pixel-labels skill.

Unlike Chernarus it does not touch cfgplayerspawnpoints.xml: Nasdara's fresh
spawns are one group per town from scripts/spawn-points, which King of the
Hill depends on.

It also prints the playerRestrictedAreaFiles list for cfggameplay.json.

Arrival points keep CLEARANCE from every mapgrouppos.xml object, and, using
the masks from build_masks.py, WATER_BUFFER from water and STRUCTURE_CLEAR
from anything the map draws as a structure, which catches what mapgrouppos.xml
leaves out (non-lootable buildings, piers, rail, roads, containers).

Note the engine sends a walk-in player to the CLOSEST safe position to where
they stand, not a random one (PlayerRestrictedAreaInstance.GetClosestSafePos3D),
so from the hub each town will likely always pick the same one of its points.
"""
import gzip
import json
import math
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

POINTS = 10
WORLD_M = 16384.0
RING = {  # metres from the town centre the arrival points are spread over
    "Hamlet": (40, 110), "Village": (50, 150), "Town": (70, 190),
    "Small City": (90, 230), "Large City": (110, 270),
}
GRID = 10.0              # candidate spacing (m)
CLEARANCE = 30.0         # min metres from any mapgrouppos object
CLEARANCE_FLOOR = 22.0   # relax no further than this
CLEARANCE_STEP = 2.0
MIN_SPACING = 50.0       # min metres between a town's arrival points
WIDEN_STEP = 25          # if they will not fit, push the ring's outer edge out
MAX_WIDEN = 200
LARGE_CLEARANCE = {      # big footprints, matched by substring
    "Tenement": 45.0, "Land_House_2": 40.0, "Apartment": 45.0, "Hangar": 50.0,
    "Warehouse": 45.0, "Industrial": 45.0, "Factory": 50.0, "Castle": 50.0,
}
WATER_BUFFER = 8.0
STRUCTURE_CLEAR = 10.0   # min metres from anything the map draws as a structure

# Hub entrances: class prefix -> PRA box size [x, y, z] (metres). A PRA moves
# a player who logs in inside it, so these only need to catch a logout at the
# object: 3 x 3 m, square so the object's yaw does not matter, and 6 m tall to
# allow for origins above the ground. Nasdara has no well pumps and only 8
# outhouses, so the entrances are every shed, Land_Shed_* (2,189 of them).
BOX = [3, 6, 3]
ENTRANCES = {
    "Land_Shed_": BOX,
}
TOILET_BOX = [0.9, 2.0, 0.9]
# Where a hub entrance drops the player: the open side of the U, as on Livonia
# (same hub, same coordinates).
HUB_ARRIVALS = [[x, 997.471923828125, 93.0] for x in (91.0, 93.0, 95.0, 97.0, 99.0,
                                                      101.0, 103.0, 105.0, 107.0, 109.0)]


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def load_objects():
    pat = re.compile(r'<group name="([^"]+)" pos="([-\d.]+) ([-\d.]+) ([-\d.]+)"')
    return [(m.group(1), float(m.group(2)), float(m.group(3)), float(m.group(4)))
            for m in pat.finditer((ROOT / "mapgrouppos.xml").read_text())]


class Mask:
    """A square PBM bitmap covering the whole map; a set bit means "here"."""

    def __init__(self, data):
        magic, dims, rest = data.split(b"\n", 2)
        assert magic == b"P4"
        w, h = map(int, dims.split())
        assert w == h
        self.size, self.bits = w, rest
        self.px_m = WORLD_M / w

    def at(self, x, z):
        i = int(x / WORLD_M * self.size)
        j = int((1 - z / WORLD_M) * self.size)
        if not (0 <= i < self.size and 0 <= j < self.size):
            return True
        k = j * self.size + i
        return bool(self.bits[k >> 3] & (0x80 >> (k & 7)))

    def near(self, x, z, r):
        """True if any set pixel lies within r metres of (x, z)."""
        n = int(r / self.px_m) + 1
        for di in range(-n, n + 1):
            for dj in range(-n, n + 1):
                dx, dz = di * self.px_m, dj * self.px_m
                if dx * dx + dz * dz <= r * r and self.at(x + dx, z + dz):
                    return True
        return False


def clearance(name, base):
    return max([base] + [v for k, v in LARGE_CLEARANCE.items() if k in name])


def clear_spots(cx, cz, lo, hi, objects, water, structures, base):
    near = [o for o in objects if math.hypot(o[1] - cx, o[3] - cz) < hi + 60]
    steps = int(hi // GRID) + 1
    out = []
    for i in range(-steps, steps + 1):
        for j in range(-steps, steps + 1):
            x, z = cx + i * GRID, cz + j * GRID
            if not lo <= math.hypot(x - cx, z - cz) <= hi:
                continue
            if any((x - o[1]) ** 2 + (z - o[3]) ** 2 < clearance(o[0], base) ** 2 for o in near):
                continue
            if water.near(x, z, WATER_BUFFER) or structures.near(x, z, STRUCTURE_CLEAR):
                continue
            out.append((x, z))
    return out


def spread(spots, cx, cz, south):
    """Farthest-point sampling, seeded with the spot nearest `south` metres due
    south of the centre, so the picks spread around the town."""
    pick = [min(spots, key=lambda p: math.hypot(p[0] - cx, p[1] - (cz - south)))]
    while len(pick) < POINTS:
        pick.append(max(spots, key=lambda p: min(math.hypot(p[0] - q[0], p[1] - q[1]) for q in pick)))
    gap = min(math.hypot(a[0] - b[0], a[1] - b[1]) for i, a in enumerate(pick) for b in pick[i + 1:])
    return pick, gap


def arrival_points(town, objects, water, structures):
    """POINTS clear, dry spots around the town, at least MIN_SPACING apart.
    Relaxes building clearance first, then widens the ring outward."""
    lo, hi = RING[town["category"]]
    cx, cz = town["x"], town["z"]
    for extra in range(0, MAX_WIDEN + 1, WIDEN_STEP):
        base = CLEARANCE
        while True:
            spots = clear_spots(cx, cz, lo, hi + extra, objects, water, structures, base)
            if len(spots) >= POINTS:
                pick, gap = spread(spots, cx, cz, (lo + hi + extra) / 2)
                if gap >= MIN_SPACING:
                    return [[round(x, 1), round(z, 1)] for x, z in pick], base, hi + extra
            if base <= CLEARANCE_FLOOR:
                break
            base -= CLEARANCE_STEP
    raise SystemExit(f"{town['name']}: no {POINTS} clear dry spots {MIN_SPACING} m apart "
                     f"within {hi + MAX_WIDEN} m")


def toilet_order(toilets):
    """Livonia's reading order, as seen from the middle of the U facing its
    closed end: up the left arm, across the base, down the right arm."""
    def key(t):
        x, _, z = t["pos"]
        if x < 87:
            return (0, z)
        if z > 110:
            return (1, x)
        return (2, -z)
    return sorted(toilets, key=key)


def dump(path, obj):
    path.write_text(json.dumps(obj, indent=4) + "\n")


def main():
    towns = json.loads((HERE / "towns.json").read_text())
    objects = load_objects()
    water = Mask((HERE / "water-mask.pbm").read_bytes())
    structures = Mask(gzip.decompress((HERE / "structure-mask.pbm.gz").read_bytes()))
    hub = json.loads((ROOT / "custom/teleports.json").read_text())["Objects"]
    toilets = toilet_order([o for o in hub if o["name"] == "Land_Misc_Toilet_Mobile"])
    assert len(toilets) == len(towns), (len(toilets), len(towns))

    boxes, counts = [], {}
    for name, x, y, z in objects:
        for prefix, size in ENTRANCES.items():
            if name.startswith(prefix):
                boxes.append([size, [0, 0, 0], [x, y, z]])
                counts[prefix] = counts.get(prefix, 0) + 1
    dump(ROOT / "custom/pra-teleport-hub.json",
         {"areaName": "TeleportToHub", "PRABoxes": boxes, "safePositions3D": HUB_ARRIVALS})
    print("hub entrances:", counts, "total", len(boxes))

    files, labels = ["./custom/pra-teleport-hub.json"], []
    for town, toilet in zip(towns, toilets):
        pts, used, reach = arrival_points(town, objects, water, structures)
        slug = slugify(town["name"])
        ident = re.sub(r"[^A-Za-z0-9]", "", town["name"])
        dump(ROOT / f"custom/pra-teleport-{slug}.json", {
            "areaName": "TeleportTo" + ident,
            "PRABoxes": [[TOILET_BOX, [0, 0, 0], toilet["pos"]]],
            "safePositions2D": pts,
        })
        files.append(f"./custom/pra-teleport-{slug}.json")
        labels.append({"name": town["label"], "pos": toilet["pos"]})
        print(f"{town['name']:16} toilet {toilet['pos'][0]:5.0f},{toilet['pos'][2]:4.0f}  "
              f"clearance {used:2.0f} m  reach {reach:3d} m  {pts}")
    dump(HERE / "labels.json", labels)
    print(json.dumps(files, indent="\t"))


if __name__ == "__main__":
    main()
