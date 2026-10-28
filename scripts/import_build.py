"""Import a build file into your own base or corvette, with a rehearsal and a way back.

The pipeline is deliberately boring: validate the build, locate exactly one
target, mutate a copy of the save in memory, prove that nothing outside the two
allowed paths changed, rebuild the save, repair its metadata, back up the whole
save folder, swap the files, read the result back from disk and verify it again.
Any failure after the swap restores the backup, so a run either lands fully or
changes nothing.

  python import_build.py --build "villa - build.json" --target "My New Base" --dry-run
  python import_build.py --build "villa - build.json" --target "My New Base" --apply
  python import_build.py --build "claw - build.json" --kind corvette --apply
  python import_build.py --build "claw - build.json" --kind corvette --new-ship --ship-name CLAW --apply
  python import_build.py --restore "~/Documents/NMS-save-backups/nms_import_20260918_000225"
"""
from __future__ import annotations

import argparse
import copy
import json
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parent))  # run from anywhere

import nms_save as ns

OBJECT_KEYS = {"At", "ObjectID", "Position", "Timestamp", "Up", "UserData"}
OPTIONAL_KEYS = {"Message"}
ANCHORS = {"planet": "^BASE_FLAG", "corvette": "^U_PARAGON"}
PLACEABLE_FLAG = {"planet": "P", "corvette": "C"}


def validate_build(build: dict[str, Any], kind: str, catalog: dict[str, Any]) -> dict[str, Any]:
    objects = build.get("Objects")
    if not isinstance(objects, list) or not objects:
        raise RuntimeError("build file has no Objects")
    for index, obj in enumerate(objects):
        keys = set(obj) if isinstance(obj, dict) else set()
        if not OBJECT_KEYS <= keys or keys - OBJECT_KEYS - OPTIONAL_KEYS:
            raise RuntimeError(f"part {index} has unexpected fields {sorted(keys)}")
        if not isinstance(obj["ObjectID"], str) or not obj["ObjectID"].startswith("^"):
            raise RuntimeError(f"part {index} has an invalid ObjectID")
        for axis in ("Position", "Up", "At"):
            value = obj[axis]
            if not (isinstance(value, list) and len(value) == 3
                    and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)):
                raise RuntimeError(f"part {index} has an invalid {axis}")
        if type(obj["Timestamp"]) is not int or type(obj["UserData"]) is not int:
            raise RuntimeError(f"part {index} has a non-integer Timestamp/UserData")
        if "Message" in obj and not isinstance(obj["Message"], str):
            raise RuntimeError(f"part {index} has a non-text Message")
    anchor = ANCHORS[kind]
    positions = [i for i, o in enumerate(objects) if o["ObjectID"] == anchor]
    if positions != [0] or any(abs(v) > 0.5 for v in objects[0]["Position"]):
        raise RuntimeError(f"a {kind} build needs exactly one {anchor}, first in the list, at the origin "
                           f"(found {len(positions)}); re-run extract_build.py or transform_build.py")
    ids = {ns.strip(o["ObjectID"]) for o in objects}
    parts_table = catalog.get("base_parts") or {}
    unknown = sorted(i for i in ids if parts_table and i not in parts_table)
    wrong_place = sorted(i for i in ids if i in parts_table and PLACEABLE_FLAG[kind] not in parts_table[i]
                         and i != ns.strip(anchor))
    return {"objects": objects, "ids": ids, "unknown_ids": unknown, "not_placeable_here": wrong_place,
            "objects_sha256": ns.canonical_sha256(objects)}


def locate_target(save: dict[str, Any], kind: str, name: str | None, index: int | None,
                  allow_active: bool) -> dict[str, Any]:
    player = ns.get_player(save)
    bases = player.get("PersistentPlayerBases")
    if not isinstance(bases, list):
        raise RuntimeError("PersistentPlayerBases is missing")
    if kind == "planet":
        matches = [i for i, b in enumerate(bases)
                   if ns.base_type(b) == "HomePlanetBase" and b.get("Name") == name]
        if len(matches) != 1:
            raise RuntimeError(f"expected exactly one planet base of yours named {name!r}, found {len(matches)}. "
                               f"Place a base computer in game, name it, save and quit, then run scan_save.py")
        position = matches[0]
        objects = bases[position].get("Objects") or []
        if not objects or objects[0].get("ObjectID") != "^BASE_FLAG" or any(abs(v) > 0.5 for v in objects[0]["Position"]):
            raise RuntimeError("the target base does not start with its base computer at the origin")
    else:
        matches = [i for i, b in enumerate(bases) if ns.base_type(b) == "PlayerShipBase"]
        if index is not None:
            matches = [i for i in matches if bases[i].get("UserData") == index]
        if len(matches) != 1:
            raise RuntimeError(f"expected exactly one corvette build record, found {len(matches)}; "
                               f"pass --ship-index to choose one")
        position = matches[0]
        ship_index = bases[position].get("UserData")
        if player.get("PrimaryShip") == ship_index and not allow_active:
            raise RuntimeError("that corvette is the ship you are currently flying. Switch to another ship in game, "
                               "save and quit, then run again (or pass --allow-active if you know better)")
        objects = bases[position].get("Objects") or []
    base = bases[position]
    return {"index": position, "path": f"BaseContext.PlayerStateData.PersistentPlayerBases[{position}].Objects",
            "name": base.get("Name"), "type": ns.base_type(base), "base_version": base.get("BaseVersion"),
            "objects_before": len(objects), "objects_sha256_before": ns.canonical_sha256(objects)}


def plan_new_ship(save: dict[str, Any], ship_name: str, template_slot: int | None, to_slot: int | None,
                  now: int) -> dict[str, Any]:
    """A corvette the game never built, in an empty ship slot - verified in game (save Version 4740).

    The ship entry is a copy of a corvette you already own: same model, its installed tech,
    empty cargo, a new name, and a seed equal to the creation time in Unix seconds (that is what
    the game itself writes). The build record is a copy of that corvette's PlayerShipBase with
    UserData pointing at the new slot and Owner.TS = the same creation time.
    """
    player = ns.get_player(save)
    ships = player.get("ShipOwnership")
    colours = player.get("ShipUsesLegacyColours")
    if not isinstance(ships, list) or not isinstance(colours, list) or len(colours) != len(ships):
        raise RuntimeError("ShipOwnership / ShipUsesLegacyColours are missing or do not line up")
    records = ns.ship_build_records(player)
    bases = player["PersistentPlayerBases"]
    # prefer corvettes whose record starts with its ^U_PARAGON core, the layout verified in game
    owned = sorted((s for s in range(len(ships)) if ns.is_corvette(ships[s]) and s in records),
                   key=lambda s: ((bases[records[s]].get("Objects") or [{}])[0].get("ObjectID") != "^U_PARAGON", s))
    if template_slot is None:
        if not owned:
            raise RuntimeError("a new corvette is copied from one you already own, and this save has none")
        template_slot = owned[0]
    elif template_slot not in owned:
        raise RuntimeError(f"slot {template_slot} is not a corvette with a build record; corvettes: {owned}")
    empty = [s for s, ship in enumerate(ships) if ns.is_empty_ship_slot(ship)]
    if to_slot is None:
        if not empty:
            raise RuntimeError(f"all {len(ships)} ship slots are taken. Scrap or sell a ship you do not need in "
                               f"game (slots stay in place, nothing else moves), save, quit, and run again")
        to_slot = empty[0]
    elif to_slot not in empty:
        raise RuntimeError(f"slot {to_slot} is not empty; empty slots: {empty}")
    if to_slot in records:
        raise RuntimeError(f"a ship build record already points at empty slot {to_slot}; refusing to guess")
    seed = f"0x{now:X}"
    if any(((s.get("Resource") or {}).get("Seed") or [False, ""])[1:2] == [seed] for s in ships):
        raise RuntimeError("seed collision with an existing ship - wait a second and run again")

    ownership = copy.deepcopy(ships[template_slot])
    ownership["Name"] = ship_name
    ownership["Resource"]["Seed"] = [True, seed]
    for inventory in ("Inventory", "Inventory_Cargo"):  # tech travels with the copy, cargo does not
        if isinstance(ownership.get(inventory), dict):
            ownership[inventory]["Slots"] = []
    record = copy.deepcopy(player["PersistentPlayerBases"][records[template_slot]])
    record.pop("Objects", None)  # the build supplies the parts
    record["UserData"] = to_slot
    record["Owner"]["TS"] = now
    record["LastUpdateTimestamp"] = now
    position = len(player["PersistentPlayerBases"])
    return {"index": position, "slot": to_slot, "template_slot": template_slot,
            "template_name": ships[template_slot].get("Name"), "ownership": ownership, "record": record,
            "colour": colours[template_slot], "seed": seed,
            "path": f"BaseContext.PlayerStateData.PersistentPlayerBases[{position}] (new)",
            "name": ship_name, "type": f"new corvette in ship slot {to_slot}",
            "base_version": record.get("BaseVersion"), "objects_before": 0,
            "objects_sha256_before": ns.canonical_sha256([])}


def plan_unlocks(save: dict[str, Any], ids: set[str], catalog: dict[str, Any], learn: bool) -> list[str]:
    """Parts whose blueprint you have not learned can stay invisible in your own base,
    even though the save holds them - learning them is what makes the build show up."""
    if not learn:
        return []
    player = ns.get_player(save)
    known = {ns.strip(k) for k in player.get("KnownProducts", []) if isinstance(k, str)}
    products = catalog.get("product_set", set())
    return sorted(i for i in ids if i in products and i not in known)


def mutate(save: dict[str, Any], target: dict[str, Any], objects: list[dict[str, Any]],
           unlocks: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    result = copy.deepcopy(save)
    player = ns.get_player(result)
    player["PersistentPlayerBases"][target["index"]]["Objects"] = copy.deepcopy(objects)
    known = player.setdefault("KnownProducts", [])
    before = len(known)
    have = {ns.strip(k) for k in known if isinstance(k, str)}
    added = [f"^{i}" for i in unlocks if i not in have]
    known.extend(added)
    return result, {"objects_after": len(objects), "known_products_before": before,
                    "known_products_after": len(known), "added_known_products": [ns.strip(a) for a in added]}


def mutate_new_ship(save: dict[str, Any], target: dict[str, Any], objects: list[dict[str, Any]],
                    unlocks: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    result = copy.deepcopy(save)
    player = ns.get_player(result)
    player["ShipOwnership"][target["slot"]] = copy.deepcopy(target["ownership"])
    player["ShipUsesLegacyColours"][target["slot"]] = target["colour"]
    player["PersistentPlayerBases"].append(dict(copy.deepcopy(target["record"]), Objects=copy.deepcopy(objects)))
    known = player.setdefault("KnownProducts", [])
    before = len(known)
    have = {ns.strip(k) for k in known if isinstance(k, str)}
    added = [f"^{i}" for i in unlocks if i not in have]
    known.extend(added)
    return result, {"objects_after": len(objects), "known_products_before": before,
                    "known_products_after": len(known), "added_known_products": [ns.strip(a) for a in added],
                    "new_ship": {"slot": target["slot"], "name": target["name"], "seed": target["seed"],
                                 "copied_from_slot": target["template_slot"],
                                 "copied_from_name": target["template_name"]}}


def make_new_ship_verifier(target: dict[str, Any], objects: list[dict[str, Any]], added: list[str]):
    slot = target["slot"]
    record = dict(target["record"], Objects=objects)

    def verify(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        before_player, after_player = ns.get_player(before), ns.get_player(after)
        if after_player["ShipOwnership"][slot] != target["ownership"]:
            raise RuntimeError("the new ship slot does not match the plan")
        if after_player["ShipUsesLegacyColours"][slot] != target["colour"]:
            raise RuntimeError("ShipUsesLegacyColours for the new slot does not match the plan")
        if after_player["PersistentPlayerBases"][:-1] != before_player["PersistentPlayerBases"]:
            raise RuntimeError("existing base and ship records changed")
        if after_player["PersistentPlayerBases"][-1] != record:
            raise RuntimeError("the new ship build record does not match the plan")
        old, new = before_player.get("KnownProducts", []), after_player.get("KnownProducts", [])
        if new[:len(old)] != old or [ns.strip(k) for k in new[len(old):]] != added:
            raise RuntimeError("KnownProducts changed other than by the planned additions")

        def masked(save: dict[str, Any], appended: bool) -> dict[str, Any]:
            clone = copy.deepcopy(save)
            player = ns.get_player(clone)
            player["ShipOwnership"][slot] = "<edited>"
            player["ShipUsesLegacyColours"][slot] = "<edited>"
            player["KnownProducts"] = "<edited>"
            if appended:
                player["PersistentPlayerBases"].pop()
            return clone

        masked_before = masked(before, False)
        if masked_before != masked(after, True):
            raise RuntimeError("something outside the allowed paths changed")
        return {"only_allowed_paths_changed": True,
                "allowed_paths": [f"BaseContext.PlayerStateData.ShipOwnership[{slot}]",
                                  f"BaseContext.PlayerStateData.ShipUsesLegacyColours[{slot}]",
                                  target["path"], "BaseContext.PlayerStateData.KnownProducts"],
                "objects_equal_build": True, "learned_now": added,
                "protected_sha256": ns.canonical_sha256(masked_before)}

    return verify


def make_verifier(target: dict[str, Any], objects: list[dict[str, Any]], added: list[str]):
    def verify(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        before_player, after_player = ns.get_player(before), ns.get_player(after)
        if after_player["PersistentPlayerBases"][target["index"]]["Objects"] != objects:
            raise RuntimeError("the target's parts do not equal the build")
        old, new = before_player.get("KnownProducts", []), after_player.get("KnownProducts", [])
        if new[:len(old)] != old:
            raise RuntimeError("existing KnownProducts entries changed")
        if [ns.strip(k) for k in new[len(old):]] != added:
            raise RuntimeError("KnownProducts additions differ from the plan")

        def masked(save: dict[str, Any]) -> dict[str, Any]:
            clone = copy.deepcopy(save)
            player = ns.get_player(clone)
            player["PersistentPlayerBases"][target["index"]]["Objects"] = "<edited>"
            player["KnownProducts"] = "<edited>"
            return clone

        masked_before = masked(before)
        if masked_before != masked(after):
            raise RuntimeError("something outside the two allowed paths changed")
        return {"only_allowed_paths_changed": True,
                "allowed_paths": [target["path"], "BaseContext.PlayerStateData.KnownProducts"],
                "objects_equal_build": True, "learned_now": added,
                "protected_sha256": ns.canonical_sha256(masked_before)}

    return verify


def write_log(path: Path, payload: dict[str, Any]) -> Path:
    target, mutation = payload["target"], payload["mutation"]
    lines = [
        "No Man's Sky build import - change log",
        f"when            : {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"save            : {payload['save']}",
        f"build file      : {payload['build_file']} (sha256 {payload['build_sha256']})",
        f"build author    : {payload.get('build_author') or 'unknown'}",
        "",
        f"target          : {target['type']} {target['name']!r} ({target['path']})",
        f"parts           : {target['objects_before']} -> {mutation['objects_after']}",
        f"known products  : {mutation['known_products_before']} -> {mutation['known_products_after']} "
        f"(+{len(mutation['added_known_products'])})",
    ]
    if mutation.get("new_ship"):
        ship = mutation["new_ship"]
        lines.append(f"new ship        : slot {ship['slot']} {ship['name']!r}, seed {ship['seed']}, tech copied from "
                     f"slot {ship['copied_from_slot']} {ship['copied_from_name']!r}")
    lines += [
        "",
        f"save.hg    sha256 {payload['save_sha256_before']} -> {payload['save_sha256_after']}",
        f"mf_save.hg sha256 {payload['meta_sha256_before']} -> {payload['meta_sha256_after']}",
        f"backup          : {payload['backup']} ({payload['backup_file_count']} files, each hash verified)",
        f"unchanged sha256: {payload['semantic_verification']['protected_sha256']} (everything outside the two paths)",
        f"read back       : {', '.join(f'{k}={v}' for k, v in payload['live_analyze'].items())}",
        "",
        "undo (game fully closed):",
        f"  python import_build.py --restore \"{payload['backup']}\"",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a build into your own base or corvette")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="rehearse the whole write in a temp folder")
    mode.add_argument("--apply", action="store_true", help="back up, write, verify")
    mode.add_argument("--restore", type=Path, metavar="BACKUP", help="put a backup back")
    parser.add_argument("--build", type=Path)
    parser.add_argument("--kind", choices=["planet", "corvette"], default="planet")
    parser.add_argument("--target", help="name of your own planet base to overwrite")
    parser.add_argument("--ship-index", type=int, help="ShipOwnership index for a corvette import")
    parser.add_argument("--new-ship", action="store_true",
                        help="corvette only: create a new ship in an empty slot instead of replacing one")
    parser.add_argument("--ship-name", help="name for the new ship (default: the build's name)")
    parser.add_argument("--template-slot", type=int,
                        help="with --new-ship: the corvette whose model and tech the new ship copies")
    parser.add_argument("--to-slot", type=int, help="with --new-ship: which empty slot (default: the first)")
    parser.add_argument("--no-learn", action="store_true", help="do not add the build's parts to KnownProducts")
    parser.add_argument("--allow-active", action="store_true", help="allow importing into the ship you are flying")
    parser.add_argument("--expect-save-sha256", help="refuse to run if the save changed since you checked it")
    parser.add_argument("--save-root", type=Path)
    parser.add_argument("--profile")
    parser.add_argument("--save")
    parser.add_argument("--libnom", type=Path)
    parser.add_argument("--backup-root", type=Path, default=None)
    parser.add_argument("--log", type=Path, help="where to write the change log (default: next to the build file)")
    args = parser.parse_args()

    backup_root = args.backup_root or ns.default_backup_root()
    nms_root = ns.locate_nms_root(args.save_root)
    if args.restore:
        print(json.dumps(ns.restore(args.restore, nms_root, backup_root), ensure_ascii=False, indent=2))
        return 0

    if not args.build or (args.kind == "planet" and not args.target):
        raise SystemExit("--build is required, and --target is required for a planet base import")
    if args.new_ship and args.kind != "corvette":
        raise SystemExit("--new-ship needs --kind corvette (a planet base needs a base computer you placed)")
    ns.ensure_game_closed()
    libnom = ns.find_libnom(args.libnom)
    profile = ns.locate_profile(nms_root, args.profile)
    save_name = ns.pick_save_name(profile, args.save)
    build = json.loads(args.build.read_text(encoding="utf-8"))
    catalog = ns.load_catalog()
    checked = validate_build(build, args.kind, catalog)
    if checked["unknown_ids"]:
        print(f"note: {len(checked['unknown_ids'])} part ids are not in the bundled catalog "
              f"(newer game content is fine): {checked['unknown_ids'][:6]}")
    if checked["not_placeable_here"]:
        print(f"warning: {len(checked['not_placeable_here'])} part kinds are not normally placeable in a "
              f"{args.kind} build: {checked['not_placeable_here'][:6]} - they may not appear in game")

    with tempfile.TemporaryDirectory(prefix="nms_import_") as raw:
        temp_root = Path(raw)
        source, flags, hashes = ns.read_copy(libnom, profile, save_name, temp_root, "source")
        if args.expect_save_sha256 and hashes[save_name].upper() != args.expect_save_sha256.upper():
            raise SystemExit(f"save.hg is {hashes[save_name]}, expected {args.expect_save_sha256}; re-scan first")
        if args.new_ship:
            # every corvette build record is called "Default" by the game, so that is no name
            ship_name = (args.ship_name or (build.get("Name") if build.get("Name") not in (None, "", "Default") else None)
                         or args.build.stem.replace(" - build", ""))
            target = plan_new_ship(source, ship_name, args.template_slot, args.to_slot, int(time.time()))
        else:
            target = locate_target(source, args.kind, args.target, args.ship_index, args.allow_active)
        if build.get("BaseVersion") is not None and target["base_version"] != build["BaseVersion"]:
            print(f"warning: build BaseVersion {build['BaseVersion']} vs target {target['base_version']}; "
                  f"parts from an older game build can sit at slightly wrong heights")
        unlocks = plan_unlocks(source, checked["ids"], catalog, not args.no_learn)
        if args.new_ship:
            modified, mutation = mutate_new_ship(source, target, checked["objects"], unlocks)
            verify = make_new_ship_verifier(target, checked["objects"], mutation["added_known_products"])
        else:
            modified, mutation = mutate(source, target, checked["objects"], unlocks)
            verify = make_verifier(target, checked["objects"], mutation["added_known_products"])
        verify(source, modified)
        staged = ns.stage(libnom, temp_root, temp_root / "source_copy", save_name, modified)
        summary = {
            "mode": "apply" if args.apply else "dry-run", "save": str(profile / save_name),
            "save_sha256_before": hashes[save_name], "build_file": str(args.build),
            "build_sha256": ns.sha256(args.build), "build_author": build.get("Author"),
            "target": {k: v for k, v in target.items() if k not in ("ownership", "record")},
            "mutation": mutation, "staged_analyze": staged["staged_analyze"],
            # verifying the round-tripped save proves the rebuilt file, not just the in-memory edit
            "semantic_verification": verify(source, staged["roundtrip"]),
        }
        if args.dry_run:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            print("\nrehearsal only - nothing on disk changed. Re-run with --apply to write it.")
            return 0
        committed = ns.commit(profile, save_name, staged, nms_root, backup_root,
                              f"nms_import_{args.kind}", libnom, temp_root, modified, verify, source)
        summary.update(committed)
        summary["mode"] = "apply"
        log_path = args.log or args.build.with_name(args.build.stem.replace(" - build", "") + " - change log.txt")
        summary["change_log"] = str(write_log(log_path, summary))
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    print(f"\ndone. Undo with:  python import_build.py --restore \"{summary['backup']}\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
