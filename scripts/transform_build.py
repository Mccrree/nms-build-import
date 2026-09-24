"""Adjust a build file before importing it: turn it, move it, trim it, drop parts.

The anchor (the build's base computer, or a ship's core) always stays at the
origin, because that is the point the game pins to the base computer you placed.
Everything else moves around it.  Rotations are rigid - distances between parts
and the length of every orientation vector are preserved, so the build cannot be
warped or mirrored; NMS stores part scale in the length of Up/At, which is why
that check matters.

  python transform_build.py in.json --rotate 90 --out turned.json
  python transform_build.py in.json --trim 45 --drop-id U_PARAGON --out main-only.json
  python transform_build.py in.json --lift 8 --offset 10 0 -5 --out lifted.json
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


def rotate_xz(vector: list[float], radians: float) -> list[float]:
    sin, cos = math.sin(radians), math.cos(radians)
    x, y, z = vector
    return [x * cos + z * sin, y, -x * sin + z * cos]


def main() -> int:
    parser = argparse.ArgumentParser(description="Rotate / move / trim a build file")
    parser.add_argument("build", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rotate", type=float, default=0.0, metavar="DEG",
                        help="turn the build around the anchor (positive = clockwise seen from above)")
    parser.add_argument("--offset", type=float, nargs=3, metavar=("X", "Y", "Z"),
                        help="move every part except the anchor by this many metres")
    parser.add_argument("--lift", type=float, default=0.0, metavar="M",
                        help="raise (+) or lower (-) every part except the anchor")
    parser.add_argument("--trim", type=float, metavar="RADIUS",
                        help="keep only parts within this horizontal distance of the anchor")
    parser.add_argument("--drop-id", action="append", default=[], metavar="ID",
                        help="drop every part with this ObjectID, e.g. U_PARAGON")
    parser.add_argument("--name", help="name to store in the new build file")
    args = parser.parse_args()

    build = json.loads(args.build.read_text(encoding="utf-8"))
    objects: list[dict[str, Any]] = build["Objects"]
    if not objects:
        raise SystemExit("build has no parts")
    anchor_id = objects[0]["ObjectID"]
    if objects[0]["Position"] != [0.0, 0.0, 0.0]:
        raise SystemExit("the first part is not at the origin - extract the build with extract_build.py first")

    result: list[dict[str, Any]] = []
    kept_indices: list[int] = []
    dropped = {"id": 0, "trim": 0}
    radians = math.radians(args.rotate)
    dx, dy, dz = (args.offset or [0.0, 0.0, 0.0])
    dy += args.lift
    drop_ids = {ns.strip(i) for i in args.drop_id}

    for index, obj in enumerate(objects):
        if index and ns.strip(obj["ObjectID"]) in drop_ids:
            dropped["id"] += 1
            continue
        moved = dict(obj)
        if radians:
            moved["Position"] = rotate_xz(obj["Position"], radians)
            moved["Up"] = rotate_xz(obj["Up"], radians)
            moved["At"] = rotate_xz(obj["At"], radians)
        if index and (dx or dy or dz):
            moved["Position"] = [moved["Position"][0] + dx, moved["Position"][1] + dy, moved["Position"][2] + dz]
        if index and args.trim is not None and ns.horizontal(moved["Position"]) > args.trim:
            dropped["trim"] += 1
            continue
        # NMS stores part scale in the length of Up/At, so a transform that changes
        # either length would silently resize parts. Check each part against itself.
        for axis in ("Up", "At"):
            if abs(math.dist(obj[axis], [0, 0, 0]) - math.dist(moved[axis], [0, 0, 0])) > 1e-4:
                raise SystemExit(f"{axis} length changed on part {index} - part scale would be corrupted; aborting")
        result.append(moved)
        kept_indices.append(index)

    if result[0]["ObjectID"] != anchor_id or [round(v, 6) for v in result[0]["Position"]] != [0.0, 0.0, 0.0]:
        raise SystemExit("the anchor moved; refusing to write")
    if radians and not (dx or dy or dz):
        # a rotation is rigid: the same pairs of parts must stay the same distance apart
        step = max(1, len(kept_indices) // 200)
        sample = kept_indices[::step][:200]
        worst = 0.0
        for first, second in zip(sample, sample[1:]):
            worst = max(worst, abs(math.dist(objects[first]["Position"], objects[second]["Position"])
                                   - math.dist(result[kept_indices.index(first)]["Position"],
                                               result[kept_indices.index(second)]["Position"])))
        if worst > 1e-3:
            raise SystemExit(f"rotation changed distances between parts by {worst:.4f} m; aborting")

    changes = []
    if args.rotate:
        changes.append(f"rotated {args.rotate:g}deg")
    if dx or dy or dz:
        changes.append(f"offset {dx:g},{dy:g},{dz:g} m")
    if args.trim is not None:
        changes.append(f"trimmed to {args.trim:g} m ({dropped['trim']} parts removed)")
    if drop_ids:
        changes.append(f"dropped {sorted(drop_ids)} ({dropped['id']} parts)")
    build["Objects"] = result
    build["Name"] = args.name or build.get("Name", "build")
    build["Transformed"] = "; ".join(changes) or "no change"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(build, ensure_ascii=False, indent=1), encoding="utf-8")
    heights = [o["Position"][1] for o in result]
    print(f"{len(objects)} -> {len(result)} parts | {build['Transformed']}")
    print(f"reach {max(ns.horizontal(o['Position']) for o in result):.0f} m, "
          f"height {min(heights):+.0f}..{max(heights):+.0f} m")
    print(f"written: {args.out}  sha256 {ns.sha256(args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
