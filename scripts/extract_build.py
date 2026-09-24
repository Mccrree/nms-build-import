"""Copy a build out of a save into a portable build file.

Two reasons this exists as its own step:

* Downloaded copies of other players' bases live in the save only until the game
  needs the slot for somewhere else you fly past - they rotate out within hours.
  Extract first, decide later.
* A downloaded base does not keep its base computer at the record origin, while
  your own base always does.  The extract re-centres every part on the build's
  own anchor so it can be dropped onto any base computer you place.

  python extract_build.py --name "WHITE COASTLINE VILLA" --out builds/
  python extract_build.py --index 12 --out builds/ --views
  python extract_build.py --corvette --out builds/      # your ship's build
"""
from __future__ import annotations

import argparse
import json
import math
import tempfile
from collections import Counter, deque
from pathlib import Path
from typing import Any

import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parent))  # run from anywhere

import nms_save as ns

PLANET_ANCHOR = "^BASE_FLAG"
CORVETTE_ANCHOR = "^U_PARAGON"


def clusters(objects: list[dict[str, Any]], cell: float = 12.0) -> list[list[int]]:
    """Group parts that are within a cell of each other, to separate a main building
    from outlying annexes - the choice of what to keep usually follows these groups."""
    cells: dict[tuple[int, int], list[int]] = {}
    for index, obj in enumerate(objects):
        key = (int(obj["Position"][0] // cell), int(obj["Position"][2] // cell))
        cells.setdefault(key, []).append(index)
    seen: set[tuple[int, int]] = set()
    groups: list[list[int]] = []
    for start in cells:
        if start in seen:
            continue
        queue, group = deque([start]), []
        seen.add(start)
        while queue:
            cx, cz = queue.popleft()
            group += cells[(cx, cz)]
            for dx in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    neighbour = (cx + dx, cz + dz)
                    if neighbour in cells and neighbour not in seen:
                        seen.add(neighbour)
                        queue.append(neighbour)
        groups.append(group)
    groups.sort(key=len, reverse=True)
    return groups


def summarise(objects: list[dict[str, Any]], known: set[str], catalog: dict[str, Any]) -> dict[str, Any]:
    ids = Counter(ns.strip(o["ObjectID"]) for o in objects)
    products = catalog.get("product_set", set())
    unlearned = sorted(p for p in ids if p in products and p not in known)
    horiz = [ns.horizontal(o["Position"]) for o in objects]
    heights = [o["Position"][1] for o in objects]
    groups = clusters(objects)
    group_rows = []
    for group in groups[:6]:
        xs = [objects[i]["Position"][0] for i in group]
        zs = [objects[i]["Position"][2] for i in group]
        ys = [objects[i]["Position"][1] for i in group]
        cx, cz = sum(xs) / len(group), sum(zs) / len(group)
        group_rows.append({"parts": len(group), "centre_distance_m": round(math.hypot(cx, cz), 1),
                           "span_m": [round(max(xs) - min(xs), 1), round(max(zs) - min(zs), 1)],
                           "height_m": [round(min(ys), 1), round(max(ys), 1)],
                           "has_anchor": any(objects[i]["Position"] == [0.0, 0.0, 0.0] for i in group)})
    return {
        "parts": len(objects), "kinds": len(ids),
        "reach_m": round(max(horiz), 1), "reach_95pct_m": round(sorted(horiz)[int(0.95 * len(horiz))], 1),
        "height_m": [round(min(heights), 1), round(max(heights), 1)],
        "parts_below_anchor": sum(1 for h in heights if h < -2),
        "unlearned_kinds": len(unlearned), "unlearned_parts": sum(ids[p] for p in unlearned),
        "unlearned": unlearned,
        "ids_not_in_catalog": sorted(p for p in ids if catalog.get("base_parts") and p not in catalog["base_parts"]),
        "top_parts": ids.most_common(10), "clusters": group_rows,
        "distance_histogram": {str(r): sum(1 for d in horiz if d <= r) for r in (25, 50, 75, 100, 150, 200, 300)},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract a build from a save into a build file")
    picker = parser.add_mutually_exclusive_group(required=True)
    picker.add_argument("--name", help="exact base name as shown by scan_save.py")
    picker.add_argument("--index", type=int, help="PersistentPlayerBases index")
    picker.add_argument("--corvette", action="store_true", help="extract the ship build (PlayerShipBase)")
    picker.add_argument("--all", action="store_true",
                        help="extract every cached base of another player (use after a tour; the cache rotates)")
    parser.add_argument("--min-parts", type=int, default=100,
                        help="with --all, skip bases smaller than this (default 100)")
    parser.add_argument("--out", type=Path, required=True, help="folder for the build file")
    parser.add_argument("--save-root", type=Path)
    parser.add_argument("--profile")
    parser.add_argument("--save")
    parser.add_argument("--libnom", type=Path)
    parser.add_argument("--keep-duplicates", action="store_true",
                        help="keep parts that sit at the same spot and rotation as an earlier one")
    parser.add_argument("--views", action="store_true", help="also write an SVG plan/elevation next to the build")
    args = parser.parse_args()

    libnom = ns.find_libnom(args.libnom)
    profile = ns.locate_profile(ns.locate_nms_root(args.save_root), args.profile)
    save_name = ns.pick_save_name(profile, args.save)
    with tempfile.TemporaryDirectory(prefix="nms_extract_") as raw:
        save, _, _ = ns.read_copy(libnom, profile, save_name, Path(raw), "extract")
    player = ns.get_player(save)
    bases = player.get("PersistentPlayerBases", [])

    if args.corvette:
        matches = [b for b in bases if ns.base_type(b) == "PlayerShipBase" and b.get("Objects")]
        if len(matches) != 1:
            raise SystemExit(f"expected exactly one ship build record, found {len(matches)}")
        targets = [(matches[0], CORVETTE_ANCHOR)]
    elif args.index is not None:
        targets = [(bases[args.index], PLANET_ANCHOR)]
    elif args.all:
        # after a tour: everything another player built that is big enough to be worth keeping
        targets = [(b, PLANET_ANCHOR) for b in bases
                   if str(ns.base_type(b)).startswith("External") and len(b.get("Objects") or []) >= args.min_parts]
        if not targets:
            raise SystemExit(f"no cached base of another player has {args.min_parts}+ parts. Visit some bases in "
                             f"game, save, and run again - the save only keeps what you have been near recently.")
        print(f"extracting {len(targets)} cached bases with {args.min_parts}+ parts\n")
    else:
        matches = [b for b in bases if b.get("Name") == args.name]
        if len(matches) != 1:
            raise SystemExit(f"expected exactly one base named {args.name!r}, found {len(matches)}")
        targets = [(matches[0], PLANET_ANCHOR)]

    known = {ns.strip(k) for k in player.get("KnownProducts", []) if isinstance(k, str)}
    catalog = ns.load_catalog()
    args.out.mkdir(parents=True, exist_ok=True)
    written, skipped = [], []
    for base, anchor_id in targets:
        try:
            written.append(extract_one(base, anchor_id, args, save_name, profile, known, catalog))
        except ValueError as error:
            skipped.append((base.get("Name") or "(unnamed)", str(error)))
            if len(targets) == 1:
                raise SystemExit(str(error))
            print(f"skipped {base.get('Name') or '(unnamed)'}: {error}")
    if len(targets) > 1:
        print(f"\n{len(written)} build files in {args.out}" + (f", {len(skipped)} skipped" if skipped else ""))
    return 0


def extract_one(base: dict[str, Any], anchor_id: str, args, save_name: str, profile: Path,
                known: set[str], catalog: dict[str, Any]) -> Path:
    objects = base.get("Objects") or []
    if not objects:
        raise ValueError("that record has no parts")
    anchors = [i for i, o in enumerate(objects) if o["ObjectID"] == anchor_id]
    if len(anchors) != 1:
        raise ValueError(f"expected exactly one {anchor_id} in the build, found {len(anchors)}; "
                         f"a build with two base computers has to be split by hand first")
    ax, ay, az = objects[anchors[0]]["Position"]

    moved = [dict(o, Position=[o["Position"][0] - ax, o["Position"][1] - ay, o["Position"][2] - az]) for o in objects]
    ordered = [moved[anchors[0]]] + [m for i, m in enumerate(moved) if i != anchors[0]]
    drift = max(abs((objects[i]["Position"][axis] - objects[0]["Position"][axis])
                    - (moved[i]["Position"][axis] - moved[0]["Position"][axis]))
                for i in range(len(objects)) for axis in range(3))
    if drift > 1e-6:
        raise ValueError(f"re-centring changed the shape (drift {drift}); aborting")

    kept, dropped = [], []
    seen: set[tuple] = set()
    for obj in ordered:
        key = (obj["ObjectID"], tuple(round(v, 2) for v in obj["Position"] + obj["Up"] + obj["At"]))
        if key in seen and not args.keep_duplicates:
            dropped.append(obj)
        else:
            kept.append(obj)
            seen.add(key)

    stats = summarise(kept, known, catalog)
    name = base.get("Name") or ("corvette" if args.corvette else f"base-{id(base) % 10000}")
    safe = "".join(c for c in name if c.isalnum() or c in " -_()").strip() or "build"
    build = {
        "Name": name,
        "BuildKind": "corvette" if args.corvette else "planet",
        "BaseVersion": base.get("BaseVersion"),
        "Author": (base.get("Owner") or {}).get("USN") or "",
        "Source": f"{ns.base_type(base)} taken from {save_name} on {profile.name}; re-centred on {anchor_id}",
        "Removed": f"{len(dropped)} duplicate parts" if dropped else "",
        "Objects": kept,
    }
    path = args.out / f"{safe} - build.json"
    path.write_text(json.dumps(build, ensure_ascii=False, indent=1), encoding="utf-8")
    report = {"build_file": str(path), "sha256": ns.sha256(path), "dropped_duplicates": len(dropped), **stats}
    (args.out / f"{safe} - stats.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{name}: {stats['parts']} parts, {stats['kinds']} kinds, by {build['Author'] or 'unknown'}")
    print(f"  footprint: reach {stats['reach_m']} m (95% within {stats['reach_95pct_m']} m), "
          f"height {stats['height_m'][0]}..{stats['height_m'][1]} m, {stats['parts_below_anchor']} parts below the anchor")
    print(f"  to display everything you must learn {stats['unlearned_kinds']} part kinds ({stats['unlearned_parts']} parts)")
    if stats["ids_not_in_catalog"]:
        print(f"  ids the bundled catalog does not know (newer game content?): {stats['ids_not_in_catalog'][:8]}")
    for i, row in enumerate(stats["clusters"]):
        print(f"  group {i}: {row['parts']} parts, centre {row['centre_distance_m']} m out, "
              f"span {row['span_m'][0]}x{row['span_m'][1]} m, height {row['height_m'][0]}..{row['height_m'][1]} m"
              f"{'  <- holds the anchor' if row['has_anchor'] else ''}")
    print(f"  written: {path}")

    if args.views:
        import make_views
        svg = make_views.write_svg(build, args.out / f"{safe} - views.svg")
        print(f"  schematic: {svg}")
    return path


if __name__ == "__main__":
    raise SystemExit(main())
