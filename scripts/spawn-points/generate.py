"""Write Nasdara's fresh spawn groups, one per town, from towns.json.

Run from the repo root:  python3 scripts/spawn-points/generate.py
Stdlib only. In cfgplayerspawnpoints.xml, replaces the fresh spawn bubbles
with one group per town, holding a single <pos> at the town centre, named
after the town with everything but letters and digits dropped
(Dar-e Ardis -> DareArdis). hop and travel are left alone.

A <pos> is the centre of a bubble, not a spawn point: the engine samples a
grid_width x grid_height grid around it at grid_density, drops candidates on
objects, in water or too steep, and scores the rest by distance from players
and infected (see the comments in the file). So one centre per town is enough.

King of the Hill narrows fresh spawns to one of these groups and takes the
hill centre as the mean of its positions, so the group names and centres are
what the bot's KOTH location list refers to.

towns.json is the capital, cities and villages from xam.nu's Nasdara place
data (static.xam.nu/dayz/json/nasdara/1.30-6.json, via the one-life repo's
map-places.json), converted to world metres: x = lng * 64, z = 16384 + lat * 64.
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def ident(name):
    return re.sub(r"[^A-Za-z0-9]", "", name)


def write_fresh_spawns(towns):
    """Swap the groups inside <fresh>'s <generator_posbubbles>."""
    path = ROOT / "cfgplayerspawnpoints.xml"
    xml = path.read_text()
    fresh = xml.index("<fresh>")
    # Match the element, not the mention of it in the comments above it.
    tag = "\n        <generator_posbubbles>"
    start = xml.index(tag, fresh) + len(tag)
    end = xml.index("        </generator_posbubbles>", start)
    assert end < xml.index("</fresh>", fresh)
    # Keep the vanilla comment explaining groups that opens the element.
    body = xml[start:end]
    if body.lstrip().startswith("<!--"):
        start = xml.index("-->", start) + len("-->")
    lines = []
    for t in towns:
        lines.append(f'            <group name="{ident(t["name"])}">')
        lines.append(f'                <pos x="{t["x"]:.6f}" z="{t["z"]:.6f}" />')
        lines.append("            </group>")
    path.write_text(xml[:start] + "\n" + "\n".join(lines) + "\n" + xml[end:])


def main():
    towns = json.loads((HERE / "towns.json").read_text())
    assert len({ident(t["name"]) for t in towns}) == len(towns), "duplicate group names"
    write_fresh_spawns(towns)
    print(f"wrote {len(towns)} fresh spawn groups")


if __name__ == "__main__":
    main()
