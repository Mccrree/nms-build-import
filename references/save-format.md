# How the save fits together

Read this before extending the scripts to fields they do not touch yet. Every
statement here was verified against live saves (game builds around save
`Version` 4735-4740, the Voyagers update); anything uncertain is marked as such.

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
10. Ships and corvettes
11. How the ship facts were found

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
| `PlayerSpaceStationBase` | a station build of your own (seen with ~2900 parts spread over 24 km; not handled here) |
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

## 10. Ships and corvettes

**Slots.** `PlayerStateData.ShipOwnership` is a fixed array of 12 slots (the game's
ship limit). An empty slot keeps its place and looks like this:

```
"Name": "", "Resource": {"Filename": "", "Seed": [false, "0x0"], ...},
"Inventory": {"Slots": [], ...}, "Inventory_TechOnly": {"Slots": [], ...}
```

Scrapping a ship clears its slot *in place*: nothing after it renumbers, and the
build records of other corvettes keep pointing at the right ships. The scrapped
ship's inventory layout, class and stat values are left behind in the empty slot;
the game ignores them. `PrimaryShip` is the slot being flown.

**A corvette is two records.** The ship itself sits in `ShipOwnership` with
`Resource.Filename` `MODELS/COMMON/SPACECRAFT/BIGGS/BIGGS.SCENE.MBIN`. Its shape is
a `PlayerShipBase` record in `PersistentPlayerBases` whose `UserData` is the ship's
slot number. Match records to ships by `UserData`, never by list position - cached
bases come and go around them. The game names every such record `Default`; the
ship's real name is `ShipOwnership[slot].Name`. Not every record starts with its
`^U_PARAGON` (one observed record started with a light), so look for it.

**Per-ship fields**, found by comparing three corvettes the game built:

| Field | Value |
|---|---|
| `ShipOwnership[s].Resource.Seed` | `[true, "0x…"]` = creation time in Unix seconds, hex |
| record `Owner.TS` | the same creation time, as an integer |
| record `UserData` | the slot number `s` |
| `Name`, inventories, stat values | whatever the ship has |

Shared or empty on every corvette: `FA8` (`[]`), `Location` (0), `Position` and
`Direction` (defaults), record `RID` (`""` - no server id is needed), record
`Name` (`Default`), `BaseVersion` 8.

`ShipUsesLegacyColours` is a separate 12-entry array, one boolean per slot.

**Creating a ship the game never built works** (verified in game, save Version
4740): fill an empty slot with a copy of an existing corvette's `ShipOwnership`
entry with a new name and a fresh creation-time seed, set that slot's
`ShipUsesLegacyColours` from the same corvette, and append a copy of that
corvette's record with `UserData` = the slot, `Owner.TS` and
`LastUpdateTimestamp` = the creation time, and the build as `Objects`. The ship
shows in the ship list, summons, flies and opens in the corvette editor. That
is what `import_build.py --new-ship` does; it empties the cargo inventory and
keeps the template's installed tech (a ship with no tech at all was not tried).
The in-game check used the template's own parts; a build from a different
corvette passed every tooling check (round trip, read-back, diff) but was not
loaded in game.

**Corvette parts are items, not just blueprints.** `CorvetteStorageInventory`
holds parts by stack (`^B_HAB1_A` ×59 and so on), separately from `KnownProducts`.
A save with every landing-gear blueprint learned (`B_LND_A/B/C`) could not place
landing gear in the corvette builder, and its storage held no `B_LND_*`, thrusters
or generators. Very likely the builder consumes these items - not confirmed. The
import path does not depend on it: placing parts through the save needs only the
blueprints (`KnownProducts`).

`ArchivedShipOwnership` (18 entries, all empty placeholders in the saves seen)
and the `CorvetteEdit*` / `CorvetteDraftShipSeed` fields are editor state; nothing
here touches them.

## 11. How the ship facts were found

None of section 10 was guessed. The method, now `scripts/diff_saves.py`:

1. Snapshot the save (a converted copy) with the game closed.
2. In game, do exactly one thing - scrap one ship - save, quit to desktop.
3. Snapshot again and diff.

The first raw diff had 21,858 changed paths; all but a handful were noise:
`TerrainEditData` (11,501), `DiscoveryManagerData` (6,664), part `Timestamp`s
refreshed on every save (3,320), spawn positions, trade and mission timers, and
cached bases that rotated out. Group paths with list indices collapsed and the
signal is a few lines.

When the game would not do the thing (building a corvette was blocked), comparing
several existing examples answered it instead: three corvettes side by side
showed which fields differ per ship and which are constant, and the seed matched
`Owner.TS` exactly on all three. The result was then written once, with a full
backup, as a clone of an existing corvette, and checked in game before becoming
part of the importer.

## Related state, for reference

Per-system progress lives in `PlayerStateData.Stats` as groups with
`GroupId: "^SYSTEM_STATS"` and an `Address` holding the packed system address -
for example `^EXP_STANDING` (race standing), `^EGUILD_STAND` (guild standing),
`^SP_POI_MISSIONS` (salvage contracts). Nothing in this skill edits them; noted
because it is the same pipeline if you ever extend it, and because the same
"only touch verified paths" rule applies.
