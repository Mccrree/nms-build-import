"""Draw a build as a plan and an elevation, so you can judge the site before importing.

The save has no terrain in it, so the one thing you can check up front is shape:
how wide the build is, how far below its base computer it reaches (that part ends
up underground on flat land), and whether it is one block or a main building with
outlying annexes.  Points are part positions, not models.

  python make_views.py "villa - build.json"                 # writes ... - views.svg
  python make_views.py "villa - build.json" --out plan.svg
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parent))  # run from anywhere

import nms_save as ns

# categorical colours checked for colour-blind separation and contrast on both themes
COLOURS = ["#2a78d6", "#eb6834", "#1baf7a", "#9aa39f"]
LABELS = ["structure", "furniture & decor", "power & tech", "other"]
INK, INK2, MUTED, HAIR, SURFACE = "#121a18", "#4a5552", "#6f7a76", "#dde3e0", "#fbfcfb"
STRUCTURE = ("FLOOR", "WALL", "ROOF", "RAMP", "STAIR", "DOOR", "WINDOW", "CUBE", "ROOM", "CORRIDOR",
             "ARCH", "PILLAR", "FOUNDATION", "TRIFLOOR", "CANOPY", "HULL", "FRAME", "PANEL")
TECH = ("POWER", "BATTERY", "GENERATOR", "SOLAR", "TELEPORT", "PORTAL", "REFINER", "TERMINAL", "NPC",
        "STORAGE", "LANDINGPAD", "BEACON", "SAVE", "EXTRACTOR", "SILO", "ANTENNA", "PARAGON", "FLAG")
DECOR = ("LIGHT", "LAMP", "PLANT", "TREE", "GRASS", "POSTER", "DECAL", "TABLE", "CHAIR", "SOFA", "BED",
         "SHELF", "RUG", "STATUE", "PLANTER", "AQUARIUM", "CRATE", "BOX", "HOLO", "FLOWER", "BUSH")


def category(object_id: str) -> int:
    name = ns.strip(object_id).upper()
    if any(word in name for word in TECH):
        return 2
    if any(word in name for word in DECOR):
        return 1
    if any(word in name for word in STRUCTURE):
        return 0
    return 3


def write_svg(build: dict[str, Any], out_path: Path) -> Path:
    objects = build["Objects"]
    points = [(o["Position"][0], o["Position"][1], o["Position"][2], category(o["ObjectID"])) for o in objects]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    xmin, xmax = math.floor(min(xs) / 10) * 10 - 5, math.ceil(max(xs) / 10) * 10 + 5
    zmin, zmax = math.floor(min(zs) / 10) * 10 - 5, math.ceil(max(zs) / 10) * 10 + 5
    ymin, ymax = math.floor(min(ys) / 10) * 10 - 2, math.ceil(max(ys) / 10) * 10 + 2
    scale = max(1.0, min(6.0, 740 / max(20.0, xmax - xmin)))
    pad_left, pad_top = 64, 150
    top_w, top_h = (xmax - xmin) * scale, (zmax - zmin) * scale
    width = int(max(820, pad_left + top_w + 48))
    side_top = pad_top + top_h + 90
    height = int(side_top + (ymax - ymin) * scale + 110)

    def tx(value: float) -> float:
        return pad_left + (value - xmin) * scale

    def tz(value: float) -> float:
        return pad_top + (value - zmin) * scale

    def ty(value: float) -> float:
        return side_top + (ymax - value) * scale

    def step(span: float) -> int:
        return 10 if span <= 90 else 20 if span <= 180 else 50 if span <= 450 else 100

    name = build.get("Name", "build")
    author = build.get("Author") or "unknown"
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="0 0 {width} {height}" font-family="system-ui, -apple-system, sans-serif">',
           f'<rect width="{width}" height="{height}" fill="{SURFACE}"/>',
           f'<text x="{pad_left}" y="44" font-size="23" font-weight="700" fill="{INK}">{name} - part layout</text>',
           f'<text x="{pad_left}" y="70" font-size="14" fill="{INK2}">{len(objects)} parts, by {author}. '
           f'Origin is the build\'s own base computer; each dot is one part, not a model.</text>']
    lx = pad_left
    for colour, label in zip(COLOURS, LABELS):
        svg.append(f'<circle cx="{lx + 6}" cy="100" r="5" fill="{colour}"/>')
        svg.append(f'<text x="{lx + 16}" y="105" font-size="13" fill="{INK2}">{label}</text>')
        lx += 26 + len(label) * 7
    svg.append(f'<text x="{pad_left}" y="{pad_top - 12}" font-size="15" font-weight="700" fill="{INK}">'
               f'plan (x right, z down, metres)</text>')
    gx = step(xmax - xmin)
    for value in range(int(math.ceil(xmin / gx) * gx), int(xmax) + 1, gx):
        svg.append(f'<line x1="{tx(value):.1f}" y1="{pad_top}" x2="{tx(value):.1f}" y2="{pad_top + top_h:.1f}" stroke="{HAIR}"/>')
        svg.append(f'<text x="{tx(value):.1f}" y="{pad_top + top_h + 16:.1f}" font-size="11" fill="{MUTED}" text-anchor="middle">{value}</text>')
    gz = step(zmax - zmin)
    for value in range(int(math.ceil(zmin / gz) * gz), int(zmax) + 1, gz):
        svg.append(f'<line x1="{pad_left}" y1="{tz(value):.1f}" x2="{pad_left + top_w:.1f}" y2="{tz(value):.1f}" stroke="{HAIR}"/>')
        svg.append(f'<text x="{pad_left - 8}" y="{tz(value) + 4:.1f}" font-size="11" fill="{MUTED}" text-anchor="end">{value}</text>')
    for group in range(4):
        for x, y, z, kind in points:
            if kind == group:
                svg.append(f'<circle cx="{tx(x):.1f}" cy="{tz(z):.1f}" r="1.6" fill="{COLOURS[group]}" fill-opacity="0.72"/>')
    svg.append(f'<path d="M{tx(0):.1f} {tz(0) - 9:.1f} l9 9 l-9 9 l-9 -9 z" fill="{SURFACE}" stroke="{INK}" stroke-width="2.5"/>')
    svg.append(f'<text x="{tx(0) + 13:.1f}" y="{tz(0) - 10:.1f}" font-size="13" font-weight="700" fill="{INK}">base computer</text>')

    svg.append(f'<text x="{pad_left}" y="{side_top - 18:.1f}" font-size="15" font-weight="700" fill="{INK}">'
               f'elevation (x right, height up; 0 = base computer)</text>')
    gy = step(ymax - ymin)
    for value in range(int(math.ceil(ymin / gy) * gy), int(ymax) + 1, gy):
        svg.append(f'<line x1="{pad_left}" y1="{ty(value):.1f}" x2="{pad_left + top_w:.1f}" y2="{ty(value):.1f}" '
                   f'stroke="{HAIR if value else MUTED}"/>')
        svg.append(f'<text x="{pad_left - 8}" y="{ty(value) + 4:.1f}" font-size="11" fill="{MUTED}" text-anchor="end">{value:+d}</text>')
    for group in range(4):
        for x, y, z, kind in points:
            if kind == group:
                svg.append(f'<circle cx="{tx(x):.1f}" cy="{ty(y):.1f}" r="1.6" fill="{COLOURS[group]}" fill-opacity="0.72"/>')
    svg.append(f'<path d="M{tx(0):.1f} {ty(0) - 9:.1f} l9 9 l-9 9 l-9 -9 z" fill="{SURFACE}" stroke="{INK}" stroke-width="2.5"/>')
    below = sum(1 for y in ys if y < -2)
    svg.append(f'<text x="{pad_left}" y="{ty(ymin) + 28:.1f}" font-size="13" fill="{INK2}">'
               f'highest {max(ys):+.0f} m, lowest {min(ys):+.0f} m, {below} parts more than 2 m below the base computer '
               f'(these end up underground on flat ground).</text>')
    svg.append(f'<line x1="{pad_left}" y1="{height - 38}" x2="{pad_left + 50 * scale:.1f}" y2="{height - 38}" stroke="{INK}" stroke-width="3"/>')
    svg.append(f'<text x="{pad_left + 50 * scale + 10:.1f}" y="{height - 33}" font-size="13" fill="{INK2}">50 m</text>')
    svg.append("</svg>")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(svg), encoding="utf-8")
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Draw a build file as plan + elevation")
    parser.add_argument("build", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    build = json.loads(args.build.read_text(encoding="utf-8"))
    out = args.out or args.build.with_name(args.build.stem.replace(" - build", "") + " - views.svg")
    print(write_svg(build, out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
