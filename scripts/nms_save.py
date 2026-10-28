"""Shared plumbing for reading and writing No Man's Sky saves safely.

Every other script in this skill builds on this module.  The rules it enforces
exist because a No Man's Sky save is a single compressed blob with a separate
encrypted metadata file: a half-written pair is an unrecoverable save, so the
pipeline never edits in place.  It copies, converts, mutates JSON, converts
back, repairs the metadata, verifies, backs up, and only then swaps the files.

Configuration (all optional, flags win over environment):
  NMS_SAVE_ROOT    folder holding the profile folders (default: the OS location)
  NMS_LIBNOM       path to libNOM.io.cli(.exe)
  NMS_BACKUP_ROOT  where timestamped backups go (default: ~/Documents/NMS-save-backups)
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

UINT32_MASK = 0xFFFFFFFF
XXTEA_DELTA = 0x9E3779B9
STEAM_META_MAGIC = 0xEEEEEEBE
SKILL_ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = SKILL_ROOT / "assets" / "part_catalog.json"


# --------------------------------------------------------------------------- hashing


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


# --------------------------------------------------------------------------- Steam metadata (mf_*.hg)


def rotate_left_32(value: int, count: int) -> int:
    return ((value << count) | (value >> (32 - count))) & UINT32_MASK


def steam_meta_key(storage_slot: int) -> list[int]:
    key0 = (rotate_left_32(storage_slot ^ 0x1422CB8C, 13) * 5 + 0xE6546B64) & UINT32_MASK
    return [key0, 0x44415645, 0x5259414E, 0x47524E54]


def meta_storage_slot(save_name: str) -> int:
    """save.hg is storage slot 2, save2.hg is 3, save3.hg is 4 ... (slot 1 holds two saves)."""
    match = re.fullmatch(r"(?:mf_)?save(\d*)\.hg", save_name)
    if not match:
        raise RuntimeError(f"not a save file name: {save_name}")
    return (int(match.group(1)) if match.group(1) else 1) + 1


def decrypt_steam_meta(raw: bytes, storage_slot: int = 2) -> bytes:
    if len(raw) % 4:
        raise RuntimeError("Steam meta length is not uint32-aligned")
    result = list(struct.unpack(f"<{len(raw) // 4}I", raw))
    key = steam_meta_key(storage_slot)
    last = len(result) - 1
    iterations = 8 if len(raw) == 104 else 6
    total = (XXTEA_DELTA * iterations) & UINT32_MASK
    for _ in range(iterations):
        key_index = (total >> 2) & 3
        nxt = result[0]
        for index in range(last, 0, -1):
            previous = result[index - 1]
            mix = ((((nxt >> 3) ^ ((previous << 4) & UINT32_MASK)) + (((nxt << 2) & UINT32_MASK) ^ (previous >> 5)))
                   ^ ((previous ^ key[(index & 3) ^ key_index]) + (nxt ^ total))) & UINT32_MASK
            result[index] = (result[index] - mix) & UINT32_MASK
            nxt = result[index]
        previous = result[last]
        mix = ((((nxt >> 3) ^ ((previous << 4) & UINT32_MASK)) + (((nxt << 2) & UINT32_MASK) ^ (previous >> 5)))
               ^ ((previous ^ key[key_index]) + (nxt ^ total))) & UINT32_MASK
        result[0] = (result[0] - mix) & UINT32_MASK
        total = (total + 0x61C88647) & UINT32_MASK
    plain = struct.pack(f"<{len(result)}I", *result)
    if struct.unpack_from("<I", plain, 0)[0] != STEAM_META_MAGIC:
        raise RuntimeError(f"Steam meta decryption failed for storage slot {storage_slot}")
    return plain


def encrypt_steam_meta(plain: bytes, storage_slot: int = 2) -> bytes:
    if len(plain) % 4:
        raise RuntimeError("Steam meta length is not uint32-aligned")
    if struct.unpack_from("<I", plain, 0)[0] != STEAM_META_MAGIC:
        raise RuntimeError("Steam meta plaintext has an invalid magic value")
    result = list(struct.unpack(f"<{len(plain) // 4}I", plain))
    key = steam_meta_key(storage_slot)
    last = len(result) - 1
    iterations = 8 if len(plain) == 104 else 6
    previous = result[last]
    total = 0
    for _ in range(iterations):
        total = (total + XXTEA_DELTA) & UINT32_MASK
        key_index = (total >> 2) & 3
        for index in range(last):
            nxt = result[index + 1]
            mix = ((((nxt >> 3) ^ ((previous << 4) & UINT32_MASK)) + (((nxt << 2) & UINT32_MASK) ^ (previous >> 5)))
                   ^ ((previous ^ key[(index & 3) ^ key_index]) + (nxt ^ total))) & UINT32_MASK
            result[index] = (result[index] + mix) & UINT32_MASK
            previous = result[index]
        nxt = result[0]
        mix = ((((nxt >> 3) ^ ((previous << 4) & UINT32_MASK)) + (((nxt << 2) & UINT32_MASK) ^ (previous >> 5)))
               ^ ((previous ^ key[(last & 3) ^ key_index]) + (nxt ^ total))) & UINT32_MASK
        result[last] = (result[last] + mix) & UINT32_MASK
        previous = result[last]
    return struct.pack(f"<{len(result)}I", *result)


def repair_generated_steam_meta(template_path: Path, generated_path: Path, save_data_path: Path,
                                output_path: Path, storage_slot: int = 2) -> dict[str, int]:
    """Keep the game's own metadata and update only the three size/time fields.

    libNOM writes a valid save blob but its fresh metadata loses slot identity
    (slot id, difficulty tag, playtime summary).  Taking the game's existing
    mf_*.hg as the template and patching sizes + timestamp is what makes the
    result load as the same save slot instead of a foreign one.
    """
    template = bytearray(decrypt_steam_meta(template_path.read_bytes(), storage_slot))
    generated = decrypt_steam_meta(generated_path.read_bytes(), storage_slot)
    if len(template) != 432 or len(generated) != 432:
        raise RuntimeError("expected a 432-byte Steam meta; this save uses a layout this tool has not verified")
    template_format = struct.unpack_from("<I", template, 4)[0]
    if template_format != 2004 or struct.unpack_from("<I", generated, 4)[0] != template_format:
        raise RuntimeError(f"unexpected Steam meta format {template_format}; refusing to patch metadata")
    decompressed_size = struct.unpack_from("<I", generated, 56)[0]
    compressed_size = save_data_path.stat().st_size
    if struct.unpack_from("<I", generated, 60)[0] != compressed_size:
        raise RuntimeError("generated meta compressed-size field does not match the staged save")
    timestamp = int(time.time())
    struct.pack_into("<I", template, 56, decompressed_size)
    struct.pack_into("<I", template, 60, compressed_size)
    struct.pack_into("<I", template, 84, decompressed_size)
    struct.pack_into("<I", template, 356, timestamp)
    encrypted = encrypt_steam_meta(bytes(template), storage_slot)
    output_path.write_bytes(encrypted)
    if decrypt_steam_meta(output_path.read_bytes(), storage_slot) != bytes(template):
        raise RuntimeError("repaired Steam meta failed encrypt/decrypt verification")
    return {"format": template_format, "decompressed_size": decompressed_size, "compressed_size": compressed_size,
            "timestamp": timestamp, "slot_id": struct.unpack_from("<Q", template, 348)[0],
            "base_version": struct.unpack_from("<I", template, 68)[0]}


def meta_summary(meta_path: Path, save_name: str) -> dict[str, Any]:
    plain = decrypt_steam_meta(meta_path.read_bytes(), meta_storage_slot(save_name))
    stamp = struct.unpack_from("<I", plain, 356)[0]
    return {"format": struct.unpack_from("<I", plain, 4)[0], "slot_id": struct.unpack_from("<Q", plain, 348)[0],
            "timestamp": stamp, "saved_at": datetime.fromtimestamp(stamp).strftime("%Y-%m-%d %H:%M:%S"),
            "compressed_size": struct.unpack_from("<I", plain, 60)[0]}


# --------------------------------------------------------------------------- locating things


def run_checked(command: list[str]) -> str:
    done = subprocess.run(command, check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding="utf-8", errors="replace")
    if done.returncode != 0:
        raise RuntimeError(f"command failed ({done.returncode}):\n{' '.join(command)}\n{done.stdout}")
    return done.stdout


def ensure_game_closed() -> None:
    """A running game rewrites the save on its own schedule and would overwrite the edit."""
    if platform.system() == "Windows":
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq NMS.exe", "/FO", "CSV", "/NH"],
                             check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace").stdout
        if "NMS.exe" in out:
            raise RuntimeError("No Man's Sky is running - save and quit to the desktop first")
    else:
        out = subprocess.run(["pgrep", "-f", "No Man's Sky"], check=False, stdout=subprocess.PIPE,
                             text=True, errors="replace").stdout
        if out.strip():
            raise RuntimeError("No Man's Sky is running - save and quit first")


def locate_nms_root(explicit: Path | None = None) -> Path:
    if explicit:
        root = Path(explicit).expanduser().resolve()
    elif os.environ.get("NMS_SAVE_ROOT"):
        root = Path(os.environ["NMS_SAVE_ROOT"]).expanduser().resolve()
    elif platform.system() == "Windows":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise RuntimeError("APPDATA is not set; pass --save-root")
        root = (Path(appdata) / "HelloGames" / "NMS").resolve()
    else:
        root = (Path.home() / "Library" / "Application Support" / "HelloGames" / "NMS").resolve()
    if not root.is_dir():
        raise RuntimeError(f"save folder not found: {root} (pass --save-root)")
    return root


def locate_profile(nms_root: Path, explicit: str | None = None) -> Path:
    if explicit:
        profile = nms_root / explicit if not Path(explicit).is_absolute() else Path(explicit)
        if not profile.is_dir():
            raise RuntimeError(f"profile folder not found: {profile}")
        return profile
    candidates = [d for d in nms_root.iterdir() if d.is_dir() and any(d.glob("save*.hg"))]
    if not candidates:
        raise RuntimeError(f"no profile folder with save files under {nms_root}")
    candidates.sort(key=lambda d: max(f.stat().st_mtime for f in d.glob("save*.hg")), reverse=True)
    return candidates[0]


def list_saves(profile: Path) -> list[dict[str, Any]]:
    rows = []
    for save in sorted(profile.glob("save*.hg")):
        meta = profile / f"mf_{save.name}"
        row = {"name": save.name, "size": save.stat().st_size,
               "modified": datetime.fromtimestamp(save.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
               "slot": (meta_storage_slot(save.name) - 1 + 1) // 2, "has_meta": meta.is_file()}
        if meta.is_file():
            try:
                row.update(meta_summary(meta, save.name))
            except RuntimeError as error:
                row["meta_error"] = str(error)
        rows.append(row)
    return rows


def pick_save_name(profile: Path, explicit: str | None = None) -> str:
    """Default to the newest save, which is the one the game offers on Continue."""
    if explicit:
        if not (profile / explicit).is_file():
            raise RuntimeError(f"{explicit} not found in {profile}")
        return explicit
    saves = [row for row in list_saves(profile) if row.get("timestamp")]
    if not saves:
        raise RuntimeError(f"no readable saves in {profile}")
    return max(saves, key=lambda row: row["timestamp"])["name"]


def find_libnom(explicit: Path | None = None) -> Path:
    # the release assets carry the platform in the name (libNOM.io.cli.win-x64.exe in 0.14.x)
    names = ["libNOM.io.cli.exe", "libNOM.io.cli", "libNOM.io.cli.win-x64.exe", "libNOM.io.cli.linux-x64",
             "libNOM.io.cli.macos-arm64", "libNOM.io.cli.macos-x64"]
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    if os.environ.get("NMS_LIBNOM"):
        candidates.append(Path(os.environ["NMS_LIBNOM"]).expanduser())
    for base in (Path.cwd(), Path.cwd() / "libNOM", SKILL_ROOT, SKILL_ROOT / "libNOM",
                 Path.home() / "nms-tools", Path.home() / "nms-tools" / "libNOM"):
        candidates.extend(base / name for name in names)
    for name in names:
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise RuntimeError(
        "libNOM.io.cli was not found. Download it from https://github.com/zencq/libNOM.io/releases "
        "(the CLI asset), unzip it, then either set NMS_LIBNOM to the executable or pass --libnom. "
        "See references/setup.md.")


# --------------------------------------------------------------------------- save <-> JSON


def convert_to_human_json(libnom: Path, save_path: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    before = set(output_dir.iterdir())
    run_checked([str(libnom), "Convert", "-I", str(save_path), "-O", str(output_dir),
                 "-F", "Json", "-J", "False", "-Js", "True"])
    created = [p for p in output_dir.iterdir() if p not in before and p.suffix == ".json"]
    if len(created) != 1:
        raise RuntimeError(f"libNOM produced {len(created)} JSON files; expected one")
    return created[0]


def convert_to_steam(libnom: Path, json_path: Path, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    run_checked([str(libnom), "Convert", "-I", str(json_path), "-O", str(output_dir), "-F", "Steam"])
    data = list(output_dir.glob("*.data"))
    meta = list(output_dir.glob("*.meta"))
    if len(data) != 1 or len(meta) != 1:
        raise RuntimeError("libNOM did not produce exactly one Steam data/meta pair")
    return data[0], meta[0]


def analyze_flags(libnom: Path, save_path: Path) -> dict[str, str]:
    flags: dict[str, str] = {}
    for line in run_checked([str(libnom), "Analyze", "-I", str(save_path)]).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            key, value = key.strip(), value.strip()
            if key and value and " " not in key:
                flags[key] = value
    return flags


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("save JSON root is not an object")
    return value


def get_player(save: dict[str, Any]) -> dict[str, Any]:
    player = save.get("BaseContext", {}).get("PlayerStateData")
    if not isinstance(player, dict):
        raise RuntimeError("PlayerStateData is missing - is this a converted NMS save?")
    return player


def base_type(base: dict[str, Any]) -> Any:
    value = base.get("BaseType")
    return value.get("PersistentBaseTypes") if isinstance(value, dict) else value


def read_copy(libnom: Path, profile: Path, save_name: str, temp_root: Path, label: str) -> tuple[dict[str, Any], dict[str, str], dict[str, str]]:
    """Copy save + meta into a temp folder, prove the copies match, and convert to JSON.

    Reading through copies means a game that starts mid-run cannot make the tool
    act on half a file, and the hash check catches exactly that.
    """
    meta_name = f"mf_{save_name}"
    folder = temp_root / f"{label}_copy"
    folder.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for name in (save_name, meta_name):
        source = profile / name
        before = sha256(source)
        shutil.copy2(source, folder / name)
        if not (before == sha256(folder / name) == sha256(source)):
            raise RuntimeError(f"{name} changed while it was being read; try again with the game closed")
        hashes[name] = before
    flags = analyze_flags(libnom, folder / save_name)
    save = load_json(convert_to_human_json(libnom, folder / save_name, temp_root / f"{label}_json"))
    return save, flags, hashes


# --------------------------------------------------------------------------- backups


def tree_manifest(root: Path) -> list[dict[str, Any]]:
    return [{"path": p.relative_to(root).as_posix(), "length": p.stat().st_size, "sha256": sha256(p)}
            for p in sorted(item for item in root.rglob("*") if item.is_file())]


def default_backup_root() -> Path:
    if os.environ.get("NMS_BACKUP_ROOT"):
        return Path(os.environ["NMS_BACKUP_ROOT"]).expanduser()
    return Path.home() / "Documents" / "NMS-save-backups"


def make_backup(nms_root: Path, backup_root: Path, label: str) -> tuple[Path, list[dict[str, Any]]]:
    """Copy the whole save folder and verify every file hash, so a restore is trustworthy."""
    backup_root = Path(backup_root).expanduser().resolve()
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_dir = (backup_root / f"{label}_{datetime.now():%Y%m%d_%H%M%S_%f}").resolve()
    if backup_dir.parent != backup_root:
        raise RuntimeError("resolved backup target escaped the configured backup root")
    backup_nms = backup_dir / "NMS"
    before = tree_manifest(nms_root)
    shutil.copytree(nms_root, backup_nms)
    after = tree_manifest(nms_root)
    manifest = tree_manifest(backup_nms)
    if before != after:
        raise RuntimeError("the save folder changed while the backup was being created")
    if before != manifest:
        raise RuntimeError("backup hash verification failed")
    (backup_dir / "backup-manifest.json").write_text(json.dumps(
        {"created_local": datetime.now().astimezone().isoformat(), "source": str(nms_root),
         "backup": str(backup_nms), "files": manifest}, ensure_ascii=False, indent=2), encoding="utf-8")
    return backup_dir, manifest


def normalize_backup_nms(path: Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    if (resolved / "NMS").is_dir():
        return resolved / "NMS"
    if resolved.name == "NMS" and resolved.is_dir():
        return resolved
    raise RuntimeError("restore path must be a timestamped backup folder or its NMS child")


def restore(backup: Path, nms_root: Path, backup_root: Path) -> dict[str, Any]:
    ensure_game_closed()
    backup_nms = normalize_backup_nms(backup)
    manifest = tree_manifest(backup_nms)
    if not manifest:
        raise RuntimeError("backup folder is empty")
    safety_dir, safety_manifest = make_backup(nms_root, backup_root, "nms_pre_restore_safety")
    for row in manifest:
        source, destination = backup_nms / row["path"], nms_root / row["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    restored = {row["path"]: row for row in tree_manifest(nms_root)}
    for row in manifest:
        if restored.get(row["path"]) != row:
            raise RuntimeError(f"restore verification failed for {row['path']}")
    return {"mode": "restore", "restored_from": str(backup_nms), "restored_to": str(nms_root),
            "restored_file_count": len(manifest), "pre_restore_safety_backup": str(safety_dir),
            "pre_restore_safety_backup_file_count": len(safety_manifest), "verified": True}


# --------------------------------------------------------------------------- the staged write


def stage(libnom: Path, temp_root: Path, source_copy_dir: Path, save_name: str,
          modified: dict[str, Any]) -> dict[str, Any]:
    """Turn edited JSON into a save/meta pair and prove it survives a round trip."""
    modified_json = temp_root / "modified.json"
    modified_json.write_text(json.dumps(modified, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    data_file, meta_file = convert_to_steam(libnom, modified_json, temp_root / "steam")
    staged_dir = temp_root / "staged"
    staged_dir.mkdir(exist_ok=True)
    staged_save, staged_meta = staged_dir / save_name, staged_dir / f"mf_{save_name}"
    shutil.copy2(data_file, staged_save)
    repair = repair_generated_steam_meta(source_copy_dir / f"mf_{save_name}", meta_file, staged_save,
                                         staged_meta, meta_storage_slot(save_name))
    flags = analyze_flags(libnom, staged_save)
    if flags.get("IsCompatible") != "True" or flags.get("IsLoaded") != "True":
        raise RuntimeError(f"libNOM cannot load the staged save: {flags}")
    roundtrip = load_json(convert_to_human_json(libnom, staged_save, temp_root / "roundtrip_json"))
    if roundtrip != modified:
        raise RuntimeError("the staged save changed JSON semantics during the round trip")
    return {"staged_save": staged_save, "staged_meta": staged_meta, "roundtrip": roundtrip,
            "staged_save_sha256": sha256(staged_save), "staged_meta_sha256": sha256(staged_meta),
            "staged_analyze": flags, "meta_repair": repair}


def commit(profile: Path, save_name: str, staged: dict[str, Any], nms_root: Path, backup_root: Path,
           backup_label: str, libnom: Path, temp_root: Path, modified: dict[str, Any],
           verify: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
           source: dict[str, Any]) -> dict[str, Any]:
    """Back up, swap the two files atomically, read the live save back and verify it.

    If anything fails after the swap the backup is restored immediately, so the
    worst case is "nothing changed" rather than a half-applied edit.
    """
    save_path, meta_path = profile / save_name, profile / f"mf_{save_name}"
    original_save, original_meta = sha256(save_path), sha256(meta_path)
    backup_dir, manifest = make_backup(nms_root, backup_root, backup_label)
    if sha256(save_path) != original_save or sha256(meta_path) != original_meta:
        raise RuntimeError("the live save changed after the backup; refusing to write")
    tmp_save = save_path.with_name(save_name + ".skill-new")
    tmp_meta = meta_path.with_name(f"mf_{save_name}.skill-new")
    committed = False
    try:
        shutil.copy2(staged["staged_save"], tmp_save)
        shutil.copy2(staged["staged_meta"], tmp_meta)
        if sha256(tmp_save) != staged["staged_save_sha256"] or sha256(tmp_meta) != staged["staged_meta_sha256"]:
            raise RuntimeError("staged copy hash mismatch")
        os.replace(tmp_meta, meta_path)
        os.replace(tmp_save, save_path)
        committed = True
        live, live_flags, _ = read_copy(libnom, profile, save_name, temp_root, "live")
        if live != modified:
            raise RuntimeError("the live save does not match what was staged")
        semantics = verify(source, live)
    except Exception:
        if committed:
            backup_profile = backup_dir / "NMS" / profile.name
            shutil.copy2(backup_profile / save_name, save_path)
            shutil.copy2(backup_profile / f"mf_{save_name}", meta_path)
        raise
    finally:
        for temporary in (tmp_save, tmp_meta):
            if temporary.exists():
                temporary.unlink()
    return {"written": True, "backup": str(backup_dir), "backup_file_count": len(manifest),
            "save_sha256_before": original_save, "save_sha256_after": sha256(save_path),
            "meta_sha256_before": original_meta, "meta_sha256_after": sha256(meta_path),
            "meta_repair": staged["meta_repair"], "live_analyze": live_flags, "semantic_verification": semantics}


# --------------------------------------------------------------------------- part catalog


def load_catalog() -> dict[str, Any]:
    """IDs only, shipped with the skill so nobody has to unpack the game files.

    A game update can add IDs the catalog has never seen; that is a warning, not
    an error, because the save itself is the authority on what loads.
    """
    if not CATALOG_PATH.is_file():
        return {"base_parts": {}, "products": []}
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    data["product_set"] = set(data.get("products", []))
    return data


def strip(object_id: str) -> str:
    return object_id[1:] if object_id.startswith("^") else object_id


# --------------------------------------------------------------------------- ships


def is_empty_ship_slot(ship: dict[str, Any]) -> bool:
    """Scrapping a ship clears its slot in place: no model, seed flag false. Slots never shift."""
    resource = ship.get("Resource") or {}
    seed = resource.get("Seed") or [False]
    return not resource.get("Filename") and not seed[0]


def is_corvette(ship: dict[str, Any]) -> bool:
    return "/BIGGS/" in ((ship.get("Resource") or {}).get("Filename") or "")


def ship_build_records(player: dict[str, Any]) -> dict[int, int]:
    """ShipOwnership slot -> position of its PlayerShipBase record. The record's UserData is the
    slot number, so match on that, never on list position (cached bases come and go around it)."""
    return {base.get("UserData"): i for i, base in enumerate(player.get("PersistentPlayerBases", []))
            if base_type(base) == "PlayerShipBase"}


# --------------------------------------------------------------------------- misc helpers


def pack_address(address: dict[str, int]) -> int:
    """Pack a GalacticAddress dict the way base records store it (verified against live saves)."""
    return (((address["PlanetIndex"] & 0xF) << 52) | ((address["SolarSystemIndex"] & 0xFFF) << 40)
            | ((address["VoxelY"] & 0xFF) << 24) | ((address["VoxelZ"] & 0xFFF) << 12) | (address["VoxelX"] & 0xFFF))


def address_int(value: Any) -> int | None:
    if isinstance(value, str) and value.startswith("0x"):
        return int(value, 16)
    return value if isinstance(value, int) else None


def same_system(a: Any, b: Any) -> bool:
    ai, bi = address_int(a), address_int(b)
    if ai is None or bi is None:
        return False
    return (ai & ~(0xF << 52)) == (bi & ~(0xF << 52))


def horizontal(position: list[float], origin: tuple[float, float] = (0.0, 0.0)) -> float:
    return ((position[0] - origin[0]) ** 2 + (position[2] - origin[1]) ** 2) ** 0.5
