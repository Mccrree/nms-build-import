# How the save fits together

Read this before extending the scripts to fields they do not touch yet. Every
statement here was verified against live saves (game builds around save
`Version` 4735-4738); anything uncertain is marked as such.

## Contents

1. The two files
2. Metadata and why it must be repaired
3. The JSON, readable and not
4. Base records
5. Build geometry
6. Parts, products and why things stay invisible
7. Downloaded bases: what is different
8. Addresses
9. Things that are not in the save

## 1. The two files

A save is `saveN.hg` (a compressed JSON document) plus `mf_saveN.hg` (432 bytes
of encrypted metadata). The game reads the metadata first: sizes, a timestamp,
the slot id, the difficulty tag. A save whose metadata disagrees with the blob
does not load, so the two must always be written together.

## 2. Metadata and why it must be repaired

The metadata is XXTEA-encrypted with a key derived from a *storage slot* number:
`save.hg` is slot 2, `save2.hg` is 3, `saveN.hg` is N+1. Decrypted, the fields
this toolchain touches are:

| Offset | Meaning |
|---|---|
| 4 | format, expected 2004 |
| 56, 84 | decompressed size |
| 60 | compressed size (must equal the .hg byte size) |
| 68 | base version |
| 348 | slot id |
| 356 | Unix timestamp |

libNOM writes a fresh metadata file that is structurally valid but loses slot
identity. The pipeline therefore takes the **game's own** `mf_saveN.hg` as the
template and patches only sizes and timestamp (`nms_save.repair_generated_steam_meta`).
This is the single most important trick here: without it the game may show a
foreign-looking slot or refuse the save. If the format is ever not 2004 or the
file is not 432 bytes, stop - the layout changed and writing would be guesswork.

The timestamp also decides which save the game offers on Continue, so a write
naturally becomes the newest save.

## 3. The JSON, readable and not

`libNOM.io.cli Convert -F Json -J False -Js True` produces JSON with readable
keys (`PlayerStateData`, `PersistentPlayerBases`, `KnownProducts`). Some keys
stay obfuscated (`ekO`, `vR5`, `6H2` …) because no public mapping exists. Treat
those as opaque: copy them through, never edit them.

Round-tripping (JSON -> save -> JSON) is byte-stable in practice, which is why
`stage()` compares the round trip against the intended document before anything
is written.

## 4. Base records

`PlayerStateData.PersistentPlayerBases` is a list of records, each with a type:

| `BaseType` | What it is |
|---|---|
| `HomePlanetBase` | your base on a planet |
| `FreighterBase` | your freighter interior |
| `PlayerShipBase` | your corvette build (paired with `ShipOwnership` via `UserData`) |
| `PlayerSpaceBase` | a space station you claimed (anchor is `^SB_BEACON`) |
| `ExternalPlanetBase` | another player's base, downloaded |
| `ExternalSpaceStationBase` | another player's claimed station |

Each record carries `Name`, `Owner` (UID/USN/platform), `GalacticAddress`,
`Position` (planet-centred), `Forward`, `BaseVersion`, and `Objects`.

An `Objects` entry is exactly: `At`, `ObjectID`, `Position`, `Timestamp`, `Up`,
`UserData`, plus an optional `Message` (used by holo projectors, fossil displays
and signs). Anything else means a malformed build file.

## 5. Build geometry

Positions are metres in a frame local to the base, y up at the base's own
location. A build is therefore portable as a rigid body: translate it to put its
anchor at the origin and it can be dropped on any base computer.

Two details matter:

- **Part scale lives in the length of `Up`/`At`.** Builders scale parts by
  lengthening those vectors. Any transform must preserve their length, which a
  proper rotation does and a mirror does not. `transform_build.py` checks this.
- **Your own bases keep the anchor at index 0 at the origin. Downloaded records
  do not** - their origin sits somewhere else entirely (one measured case: the
  base computer 273 m away). Re-centring is what `extract_build.py` does first.

Curvature is irrelevant at base scale (a 70 m build sees about 0.06 degrees of
planet curve).

## 6. Parts, products and why things stay invisible

`KnownProducts` is the list of blueprints the save has learned. Observed
behaviour: **parts whose product is not in `KnownProducts` can fail to render in
your own base, while the same parts render fine in another player's base.** A
save held all 2996 imported parts and the player still saw holes in the floor
until the products were learned; after learning them the build appeared.

So an import learns every product the build uses. `assets/part_catalog.json`
lists part ids and which products exist, extracted from the game tables, so the
skill does not need the game files unpacked. Ids added by later game updates are
reported as unknown rather than rejected - the save is the authority.

The catalog also records where each part may be placed: `P` planet base, `F`
freighter, `C` corvette, `S` space station. Structural sets (stone, timber) are
planet/freighter parts; a space station annexe accepts a different 707-part
subset, which is why station interiors are out of scope here.

## 7. Downloaded bases: what is different

- **They rotate out.** The save keeps a bounded set of other players' bases and
  replaces them as you travel; a whole cache turned over within a day in
  observation. Extract right after visiting.
- **They can be truncated.** Uploads are capped: three unrelated large bases all
  arrived at exactly 2997 parts, and the game has an "Upload Unavailable (Base
  Limit Exceeded)" message. What you copy is what the server served, which may be
  less than the builder sees.
- **They sometimes carry a `^U_PARAGON`** at the record origin with the same
  UserData as a corvette core. It is not placeable on planets
  (`IsPlaceable=false`), so it is a leftover; drop it.
- **Two base computers** show up occasionally. `extract_build.py` refuses those -
  split the record by hand if you need it.

## 8. Addresses

`GalacticAddress` appears both as a dict (VoxelX/VoxelY/VoxelZ/SolarSystemIndex/
PlanetIndex) and packed into an integer or hex string. The packing, verified
against a save that contains both forms of the same base:

| Bits | Field |
|---|---|
| 0-11 | VoxelX (signed) |
| 12-23 | VoxelZ (signed) |
| 24-31 | VoxelY (signed) |
| 40-51 | SolarSystemIndex |
| 52-55 | PlanetIndex |

`nms_save.pack_address` / `same_system` implement this; it is how you tell
whether two bases share a planet or a system (worth checking before importing a
300 m build next to an existing one).

## 9. Things that are not in the save

- **Terrain.** It is generated from the planet seed; only the player's own
  terrain edits are stored (`TerrainEditData`), separately from bases. Nothing
  can tell you in advance whether a hillside build will fit - that check happens
  in game.
- **What a part looks like.** The tools reason about ids and positions only.
- **Whether the server will accept an edited base on upload.** Untested; treat
  imported builds as private.

## Related state, for reference

Per-system progress lives in `PlayerStateData.Stats` as groups with
`GroupId: "^SYSTEM_STATS"` and an `Address` holding the packed system address -
for example `^EXP_STANDING` (race standing), `^EGUILD_STAND` (guild standing),
`^SP_POI_MISSIONS` (salvage contracts). Nothing in this skill edits them; noted
because it is the same pipeline if you ever extend it, and because the same
"only touch verified paths" rule applies.
