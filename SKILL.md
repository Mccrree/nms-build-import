---
name: nms-build-import
description: Copy another player's No Man's Sky base or corvette build into your own save - scan the save for cached builds, extract one, adjust it (rotate/trim/raise), then import it onto a base computer you placed or into a ship, with a hash-verified backup, a rehearsal run, a read-back check and a one-command undo. Use this skill whenever someone mentions No Man's Sky saves, .hg save files, save editing, copying or importing a base, house, villa, freighter room or corvette build, unlocking base parts that do not show up, or asks to make a build they saw in game appear at their own base - even if they only say "I found a great base, can I have it too" or write in Chinese about 无人深空存档/基地导入/护卫舰.
---

# No Man's Sky build import

Copy a build that already exists in a save - a base another player made, or a
corvette design - onto a base computer or ship of your own, without hand-editing
the save.

A No Man's Sky save is one compressed blob plus a separate encrypted metadata
file. Write one without the other, or write it while the game is running, and
the slot is gone. Everything here therefore works on copies, rehearses the full
write before touching anything, and keeps a verified backup with a one-line undo.

## Start by orienting the player

Most people arrive with "can I get that base into my save" and no idea what it
involves. Before touching anything, tell them in their own language:

**What this can do**
- Copy any base your save has already downloaded (bases you flew to, visited
  from the Anomaly teleporter, or your own) onto a base computer you place.
- Copy a corvette build - from your save or from a shared build file.
- Learn the parts the build uses, otherwise some of them stay invisible.
- Adjust before importing: turn it, raise it, trim outlying pieces, drop junk.

**What it cannot do**
- Console saves (PS/Xbox/Switch). PC only: Steam, GOG or Game Pass.
- Reshape terrain. The build arrives at the height it was built at, so a design
  cut into a cliff ends up underground on flat land.
- Space-station interiors: those use a different part set and a different record
  type (`PlayerSpaceBase`), and this skill does not import them.

**What they must do themselves** (they are the only one who can)
1. In game, get the build into their save: fly to it, or teleport to it. The
   save keeps a limited number of other players' bases and rotates them out
   within hours, so extract soon after visiting.
2. Prepare the destination: for a base, place a base computer where they want
   the build and give it a distinctive name; for a corvette, switch to a
   *different* ship first so the target is not the one they are flying.
3. Save in game, then **quit to desktop**. Not alt-tab - the game rewrites the
   save on its own schedule and would overwrite the import.
4. Tell you which build they want.

Then ask the one question that decides the path: **a planet base, or a corvette
build?** Everything after that differs.

Check `references/setup.md` if the tools are not installed yet; it covers
libNOM.io.cli (required), Python 3.10+, and where saves live per platform.

## Rules that keep this safe

These are not ceremony - each one has cost somebody a save at some point:

- **Never write while the game runs.** Every script refuses; do not work around it.
- **Never edit .hg by hand or guess at fields.** Convert to JSON, change only
  known paths, convert back. If a field's meaning is unclear, find it by diffing
  a before/after save rather than assuming.
- **Rehearse, then apply.** `--dry-run` does the whole thing in a temp folder,
  including rebuilding the save and verifying it. Read its output before applying.
- **Every apply makes a full, hash-verified backup first** and prints the undo
  command. Put that command in your report to the player - they will want it.
- **Only two paths may change**: the target's `Objects`, and `KnownProducts`.
  The tools verify this by comparing everything else byte for byte; if that check
  fails, nothing is written.
- **Other people's builds are their work.** Fine to enjoy privately; do not
  re-upload someone else's build as your own.

## Go shopping first: the tour loop

The usual way people get builds is to go looking for them, and the save is what
remembers where they have been. Support that directly:

1. **Before the trip**, take a reference scan so you can tell later what is new:
   `python scripts/scan_save.py --json builds/before-tour.json`
2. **The player tours** - fly to planets, use the Anomaly teleporter's featured
   and nearby-player bases, drop in on anything that looks good. Each visited
   base gets downloaded into the save. Then **save in game**.
3. **Harvest** what the trip brought in:
   ```
   python scripts/scan_save.py --since builds/before-tour.json --json builds/after-tour.json
   python scripts/extract_build.py --all --min-parts 300 --out builds/ --views
   ```
   `--since` marks what appeared since the reference scan; `--all` extracts every
   cached base above a size you choose, one build file each, skipping the ones
   that cannot be anchored (two base computers, for instance) with a note.
4. **Then choose.** Show the player the list with part counts, footprints and
   drawings, and let them pick what to import where.

Scanning and extracting only read copies, so the player does not have to quit for
this - saving in game is enough. Importing is the step that needs the game closed.

Harvest the same day. The save keeps a bounded set of other players' bases and
quietly replaces them as you travel; a build file on disk is permanent, a cached
base is not.

## Workflow A - planet base

1. **Scan** to see what the save holds:
   `python scripts/scan_save.py`
   It prints your own bases and every cached build with part count, footprint,
   height range and how many part kinds you have not learned. Cached bases are
   the import candidates.

2. **Extract immediately** - the cache rotates:
   `python scripts/extract_build.py --name "EXACT NAME" --out builds/ --views`
   (or `--all` after a tour, see above)
   This re-centres the build on its own base computer (downloaded records do not
   keep it at the origin), drops parts that duplicate another part exactly,
   writes `builds/<name> - build.json`, a stats file, and an SVG plan/elevation.

3. **Judge the fit before importing.** From the stats and the drawing:
   - `reach_m` is how far the build spreads; the base computer must sit where
     that much space exists.
   - `parts_below_anchor` is how much hangs below the base computer - that is
     the part that vanishes into flat ground.
   - `clusters` shows whether it is one building or a main block plus annexes
     200 m away; annexes are what people usually trim.
   Tell the player these numbers and ask what they want kept. Do not decide
   silently for them when a big chunk would be dropped.

4. **Adjust if needed** (optional):
   `python scripts/transform_build.py "builds/x - build.json" --trim 45 --drop-id U_PARAGON --out "builds/x main - build.json"`
   Useful flags: `--rotate DEG` to face it differently, `--lift M` to raise it
   out of the ground, `--trim RADIUS` to keep only the core, `--drop-id`.
   `U_PARAGON` is a corvette core that the game sometimes leaves in downloaded
   planet bases - it cannot be placed on a planet, so drop it.

5. **Rehearse, then write**:
   ```
   python scripts/import_build.py --build "builds/x - build.json" --target "BASE NAME" --dry-run
   python scripts/import_build.py --build "builds/x - build.json" --target "BASE NAME" --apply
   ```
   The import replaces that base's parts and learns every part the build uses
   (`--no-learn` to skip, but expect missing pieces in game). It writes a change
   log next to the build file with hashes, the backup path and the undo command.

6. **Report back**: what changed (parts before -> after, products learned), that
   only the two allowed paths changed, what to check in game (buried or floating
   sections, teleporter, frame rate), and the undo command. Ask them to look and
   come back - a second pass with `--lift` or `--rotate` is cheap.

## Workflow B - corvette

1. The player must be flying a **different** ship, then save and quit. The
   importer refuses the active ship because the game holds it in memory and
   would write it back over the import.

2. Get a build file, either from the save itself
   (`python scripts/extract_build.py --corvette --out builds/`) or from a shared
   corvette build JSON. A valid corvette build has exactly one `^U_PARAGON` at
   the origin, first in the list; `extract_build.py` enforces that, and for a
   downloaded file `import_build.py` checks it before doing anything.

3. Import:
   ```
   python scripts/import_build.py --build "builds/claw - build.json" --kind corvette --dry-run
   python scripts/import_build.py --build "builds/claw - build.json" --kind corvette --apply
   ```
   Add `--ship-index N` when the save has several ship build records (the scan
   prints them). Learning the parts matters here too - unlearned parts can be
   invisible in your own ship.

4. In game: load, look at the ship in the corvette editor, fly it. If parts are
   missing, it is almost always unlearned products - re-run without `--no-learn`.

## Drawings

`python scripts/make_views.py "builds/x - build.json"` writes an SVG with a plan
and an elevation. Worth doing before any import that spreads beyond ~60 m: it is
the fastest way for the player to see "this needs a hillside" or "this second
building is 240 m away". Send the SVG to the player; it opens in any browser.

## Reporting to the player

Write in the player's language, and keep it concrete:
- what you changed, in parts and product counts, and what you deliberately left out
- that only the target base/ship and the learned-parts list changed
- what to look at in game, including anything you could not verify (terrain fit,
  teleporters, performance with very large builds)
- the exact undo command
- for another player's build, a line that it is their work

State plainly when something is unverifiable from the save - terrain, water
level, whether a mini-portal pair still works. Guessing here reads as confidence
the data does not support.

## References

- `references/setup.md` - installing libNOM.io.cli, Python, save locations, Steam Cloud
- `references/save-format.md` - how saves, slots, metadata, base records and part
  IDs fit together; read before extending these tools to new fields
- `references/troubleshooting.md` - the failures that actually happen, and what they mean
- `assets/part_catalog.json` - part and product IDs used for validation and for
  deciding what can be learned; IDs the game added later are reported, not rejected
