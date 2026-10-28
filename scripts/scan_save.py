"""Read-only tour of a save: which builds are in it, which are worth copying, where they could go.

Nothing here writes to the save, so it is safe to run even with the game open
(the copies are hash-checked, and a save written mid-copy just asks you to retry).

  python scan_save.py                       # everything, human readable
  python scan_save.py --json report.json    # same data as JSON for further work
  python scan_save.py --save save2.hg       # inspect a specific save file
"""
from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parent))  # run from anywhere

import nms_save as ns

FUNCTIONAL = ("TELEPORT", "PORTAL", "NPC", "TERMINAL", "STORAGE", "BUILDSAVE", "REFINER",
              "LANDINGPAD", "SHIPPAD", "PARAGON", "BEACON")


def describe(base: dict[str, Any], known: set[str], catalog: dict[str, Any]) -> dict[str, Any]:
    objects = base.get("Objects") or []
    ids = Counter(ns.strip(o["ObjectID"]) for o in objects)
    flags = [i for i, o in enumerate(objects) if o.get("ObjectID") == "^BASE_FLAG"]
    anchor = objects[flags[0]]["Position"] if flags else [0.0, 0.0, 0.0]
    origin = (anchor[0], anchor[2])
    reach = max((ns.horizontal(o["Position"], origin) for o in objects), default=0.0)
    heights = [o["Position"][1] - anchor[1] for o in objects] or [0.0]
    products = catalog.get("product_set", set())
    unlearned = sorted(p for p in ids if p in products and p not in known)
    unknown_ids = sorted(p for p in ids if catalog.get("base_parts") and p not in catalog["base_parts"])
    return {
        "name": base.get("Name") or "",
        "type": ns.base_type(base),
        "author": (base.get("Owner") or {}).get("USN") or "",
        "owner_uid": (base.get("Owner") or {}).get("UID") or "",
        "parts": len(objects),
        "base_version": base.get("BaseVersion"),
        "address": base.get("GalacticAddress"),
        "base_flag_index": flags[0] if flags else None,
        "base_flag_count": len(flags),
        "reach_m": round(reach, 1),
        "height_min_m": round(min(heights), 1),
        "height_max_m": round(max(heights), 1),
        "parts_below_anchor": sum(1 for h in heights if h < -2),
        "kinds": len(ids),
        "unlearned_kinds": len(unlearned),
        "unlearned_parts": sum(ids[p] for p in unlearned),
        "ids_not_in_catalog": unknown_ids[:10],
        "functional": {p: c for p, c in sorted(ids.items()) if any(w in p for w in FUNCTIONAL)},
        "top_parts": ids.most_common(6),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only scan of a No Man's Sky save")
    parser.add_argument("--save-root", type=Path)
    parser.add_argument("--profile")
    parser.add_argument("--save", help="save file name, e.g. save.hg (default: the newest)")
    parser.add_argument("--libnom", type=Path)
    parser.add_argument("--json", type=Path, help="also write the full report here")
    parser.add_argument("--since", type=Path, metavar="REPORT.JSON",
                        help="a report from before a tour; cached bases missing from it are marked NEW")
    parser.add_argument("--min-parts", type=int, default=100, help="cached bases below this are summarised only")
    args = parser.parse_args()

    libnom = ns.find_libnom(args.libnom)
    nms_root = ns.locate_nms_root(args.save_root)
    profile = ns.locate_profile(nms_root, args.profile)
    save_name = ns.pick_save_name(profile, args.save)
    print(f"profile : {profile}")
    print("saves   :")
    for row in ns.list_saves(profile):
        mark = " <- reading" if row["name"] == save_name else ""
        print(f"  {row['name']:<10} {row.get('saved_at', row['modified'])}  {row['size']:>9,} bytes{mark}")

    with tempfile.TemporaryDirectory(prefix="nms_scan_") as raw:
        temp_root = Path(raw)
        save, flags, hashes = ns.read_copy(libnom, profile, save_name, temp_root, "scan")
    player = ns.get_player(save)
    known = {ns.strip(k) for k in player.get("KnownProducts", []) if isinstance(k, str)}
    catalog = ns.load_catalog()
    me = profile.name[3:] if profile.name.startswith("st_") else ""

    report: dict[str, Any] = {
        "profile": str(profile), "save": save_name, "save_sha256": hashes[save_name],
        "save_version": save.get("Version"), "playtime": save.get("CommonStateData", {}).get("TotalPlayTime"),
        "known_products": len(player.get("KnownProducts", [])), "analyze": flags,
        "mine": [], "cached": [], "ships": [],
    }
    for index, base in enumerate(player.get("PersistentPlayerBases", [])):
        row = describe(base, known, catalog)
        row["index"] = index
        # record type is the reliable split: External* records are downloaded copies of
        # other players' builds, everything else belongs to this save's player.
        row["mine"] = not str(row["type"]).startswith("External")
        (report["mine"] if row["mine"] else report["cached"]).append(row)
    bases = player.get("PersistentPlayerBases", [])
    records = ns.ship_build_records(player)
    for index, ship in enumerate(player.get("ShipOwnership", [])):
        name = (ship.get("Name") or "").strip()
        resource = (ship.get("Resource") or {}).get("Filename", "")
        build_parts = len(bases[records[index]].get("Objects") or []) if index in records else None
        report["ships"].append({"index": index, "name": name, "model": resource.split("/")[-1],
                                "is_primary": player.get("PrimaryShip") == index,
                                "empty": ns.is_empty_ship_slot(ship), "corvette_build_parts": build_parts})

    print(f"\nsave version {report['save_version']} | playtime {report['playtime']} | known products {report['known_products']}")
    print("\n== your own records ==")
    for row in report["mine"]:
        print(f"  [{row['index']:2}] {str(row['type']):<18} {row['name'][:24]:<26} {row['parts']:>5} parts  "
              f"reach {row['reach_m']:>6.0f} m  height {row['height_min_m']:+.0f}..{row['height_max_m']:+.0f} m")
    previous = set()
    if args.since and args.since.is_file():
        old_report = json.loads(args.since.read_text(encoding="utf-8"))
        previous = {(r.get("name"), r.get("author"), r.get("parts")) for r in old_report.get("cached", [])}
        for row in report["cached"]:
            row["new_since"] = (row["name"], row["author"], row["parts"]) not in previous
        fresh = sum(1 for r in report["cached"] if r.get("new_since"))
        print(f"\ncompared with {args.since.name}: {fresh} of {len(report['cached'])} cached bases are new")

    print("\n== other players' bases cached in this save (these rotate out - copy what you like now) ==")
    for row in sorted(report["cached"], key=lambda r: -r["parts"]):
        if row["parts"] < args.min_parts:
            continue
        mark = "NEW " if row.get("new_since") else ("    " if previous else "")
        print(f"  [{row['index']:2}] {mark}{row['name'][:24]:<26} {row['parts']:>5} parts  by {row['author'][:14]:<16}"
              f" reach {row['reach_m']:>6.0f} m  height {row['height_min_m']:+.0f}..{row['height_max_m']:+.0f} m  "
              f"unlearned {row['unlearned_kinds']} kinds")
        if row["functional"]:
            print(f"        functional: {row['functional']}")
    small = [r for r in report["cached"] if r["parts"] < args.min_parts]
    if small:
        print(f"  (+{len(small)} cached bases under {args.min_parts} parts)")
    print("\n== ships (corvette import targets) ==")
    for row in report["ships"]:
        if row["empty"]:
            print(f"  [{row['index']}] (empty slot - import_build.py --new-ship can put a corvette here)")
            continue
        build = f"  corvette build {row['corvette_build_parts']} parts" if row["corvette_build_parts"] is not None else ""
        print(f"  [{row['index']}] {row['name'][:24]:<26} {row['model']:<28}{build}"
              f"{'  <- currently flown' if row['is_primary'] else ''}")
    free = sum(1 for r in report["ships"] if r["empty"])
    print(f"  {free} of {len(report['ships'])} ship slots free"
          + ("" if free else " - scrap a ship in game before a --new-ship import"))

    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nfull report: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
