"""Learn what a field means by letting the game write it: snapshot, act in game, snapshot, diff.

This is how the new-ship import was worked out (see references/save-format.md, "Ships and
corvettes"). Reading only - snapshots are converted copies, the live save is never touched.

  python diff_saves.py snapshot before          # game saved and closed
  ... do exactly one thing in game, save, quit to desktop ...
  python diff_saves.py snapshot after
  python diff_saves.py diff before after         # changed paths, noise grouped and set aside

A raw diff of two saves is ~99% noise (terrain edits, discoveries, part timestamps that refresh on
every save, spawn positions). The report groups paths with list positions collapsed and lists the
known-noisy areas last, so the change you caused stands out.
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parent))  # run from anywhere

import nms_save as ns

DEFAULT_ROOT = ns.SKILL_ROOT / "builds" / "research"
# areas that change on almost every save, whatever you did in game
NOISE = ("TerrainEditData", "DiscoveryManagerData", ".Objects[].Timestamp", "MultiplayerSpawn", "MultiplayerUA",
         "TradingSupplyData", "MissionProgress", "MissionRecurrences", "LastUpdateTimestamp", "SpawnStateData",
         "TeleportEndpoints", "MarkerStack", "Stats[]", "VehicleOwnership[].Position", "VehicleOwnership[].Direction",
         "RefinerBufferData", "LastCheckedForStatResetsTime", "StoredInteractions")


def short(value: Any, limit: int = 160) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + f"... ({len(text)} chars)"


def walk(a: Any, b: Any, path: str, out: list[tuple[str, str]]) -> None:
    if type(a) is not type(b):
        out.append((path, f"{short(a)} -> {short(b)}"))
    elif isinstance(a, dict):
        for key in sorted(set(a) | set(b), key=str):
            sub = f"{path}.{key}"
            if key not in a:
                out.append((sub, f"added {short(b[key])}"))
            elif key not in b:
                out.append((sub, f"removed (was {short(a[key])})"))
            else:
                walk(a[key], b[key], sub, out)
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append((path, f"length {len(a)} -> {len(b)}"))
        for i in range(min(len(a), len(b))):
            walk(a[i], b[i], f"{path}[{i}]", out)
        out += [(f"{path}[{i}]", f"added {short(b[i])}") for i in range(len(a), len(b))]
        out += [(f"{path}[{i}]", f"removed (was {short(a[i])})") for i in range(len(b), len(a))]
    elif a != b:
        out.append((path, f"{short(a)} -> {short(b)}"))


def snapshot(args) -> int:
    folder = args.root / args.label
    if folder.exists():
        raise SystemExit(f"{folder} exists - use a new label")
    libnom = ns.find_libnom(args.libnom)
    profile = ns.locate_profile(ns.locate_nms_root(args.save_root), args.profile)
    save_name = ns.pick_save_name(profile, args.save)
    with tempfile.TemporaryDirectory(prefix="nms_snapshot_") as raw:
        save, _, hashes = ns.read_copy(libnom, profile, save_name, Path(raw), "snapshot")
    folder.mkdir(parents=True)
    (folder / "save.json").write_text(json.dumps(save, ensure_ascii=False, indent=1), encoding="utf-8")
    (folder / "source.json").write_text(json.dumps({"save": str(profile / save_name), "sha256": hashes},
                                                   indent=2), encoding="utf-8")
    print(f"snapshot {args.label}: {profile / save_name} -> {folder}")
    return 0


def diff(args) -> int:
    before = json.loads((args.root / args.before / "save.json").read_text(encoding="utf-8"))
    after = json.loads((args.root / args.after / "save.json").read_text(encoding="utf-8"))
    changes: list[tuple[str, str]] = []
    walk(before, after, "$", changes)
    groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for path, what in changes:
        groups[re.sub(r"\[\d+\]", "[]", path).replace("$.BaseContext.PlayerStateData.", "")].append((path, what))
    noisy = {g for g in groups if any(n in g for n in NOISE)}
    header = [f"{len(changes)} changed paths in {len(groups)} groups ({len(noisy)} groups are usual noise)", ""]
    signal, noise = [], []
    for group in sorted(groups):
        rows = groups[group]
        block = noise if group in noisy else signal
        block.append(f"{'[noise] ' if group in noisy else ''}{group}  ({len(rows)})")
        block += [f"    {path}: {what}" for path, what in rows[:args.per_group]]
    footer = ["", "PersistentPlayerBases positions shift when cached bases rotate in or out: match records by "
              "Name / Owner / UserData, not by index, before concluding a record changed."]
    report = args.root / f"diff {args.before} - {args.after}.txt"
    report.write_text("\n".join(header + signal + [""] + noise + footer) + "\n", encoding="utf-8")
    print("\n".join(header + signal + footer)[:args.max_chars])
    print(f"\n{len(groups) - len(noisy)} signal groups shown; full report with noise: {report}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Snapshot and diff saves to learn what the game writes")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="where snapshots live")
    sub = parser.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("label")
    snap.add_argument("--save-root", type=Path)
    snap.add_argument("--profile")
    snap.add_argument("--save")
    snap.add_argument("--libnom", type=Path)
    snap.set_defaults(run=snapshot)
    cmp_ = sub.add_parser("diff")
    cmp_.add_argument("before")
    cmp_.add_argument("after")
    cmp_.add_argument("--per-group", type=int, default=4, help="example paths printed per group")
    cmp_.add_argument("--max-chars", type=int, default=20000)
    cmp_.set_defaults(run=diff)
    args = parser.parse_args()
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
