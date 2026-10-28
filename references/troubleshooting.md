# When something goes wrong

Ordered roughly by how often it happens.

## "No Man's Sky is running - save and quit to the desktop first"

Alt-tabbing is not enough. The game keeps the save in memory and rewrites it, so
an edit made now is either lost or half-applied. Save in game, quit to desktop,
run again.

## "libNOM.io.cli was not found"

See `setup.md`. Quickest fix: download the CLI, then
`set NMS_LIBNOM=C:\path\to\libNOM.io.cli.win-x64.exe` (or `export` on macOS) and
re-run. The release file names carry the platform; the scripts look for those
names as well as plain `libNOM.io.cli(.exe)`.

## "expected exactly one planet base of yours named 'X', found 0"

Three usual causes, in order:
1. The base computer was placed but the game was not saved afterwards - the
   record only exists once the game writes the save.
2. The name differs (trailing space, different case, or the game's default name).
   Run `scan_save.py` and copy the name it prints exactly.
3. The edit is looking at the wrong save file - `scan_save.py` shows which one it
   read; pass `--save save2.hg` if the player's last save was a manual one.

## "save.hg is <hash>, expected <other hash>"

The game wrote the save between the scan and the import - usually because it was
still open. Re-run the scan and the import; the guard exists so an import cannot
silently act on stale data.

## Parts are missing in game after an import

In order of likelihood:
1. **Unlearned products.** The save holds the parts but the game does not draw
   them. Re-run the import without `--no-learn`, or run it again - it is
   idempotent and will add the missing products.
2. **Below the terrain.** Check `parts_below_anchor` in the extract stats. On
   flat ground a hillside build buries its lower floors. Re-import with
   `transform_build.py --lift 10` (or whatever the elevation drawing suggests).
3. **Not placeable in that context.** The importer warns when a build uses parts
   the catalog marks as not placeable on a planet/corvette. Those are usually
   fine to drop with `--drop-id`.

## "all 12 ship slots are taken"

A `--new-ship` import needs an empty slot. Scrap or sell a ship you do not need in
game (empty its inventory first), save, quit, run again. Slots are cleared in
place, so no other ship or corvette build is affected.

## "a new corvette is copied from one you already own, and this save has none"

The new ship copies the model and tech of a corvette you own. Get one corvette the
normal way first; after that every further corvette can be imported.

## "this save has N corvette builds - pick one with --ship-index"

`extract_build.py --corvette` needs to know which ship. The message lists slot
numbers with ship names; `scan_save.py` shows the same in its ships section.

## The corvette builder will not place landing gear (or thrusters)

Not a blueprint problem if the scan shows the parts learned. The builder appears
to consume part items from `CorvetteStorageInventory`, and a save that could not
place landing gear held none (see `save-format.md`, section 10). Either get the
parts in game, or skip building a placeholder: `import_build.py --new-ship` creates
the ship directly.

## The build faces the wrong way

Nothing is mirrored - the transform is rigid and verified. What you can change
is the heading: `transform_build.py --rotate 90` (positive is clockwise seen
from above), then re-import. Re-importing over your own imported base is normal;
the change log from the previous run tells you what it replaced.

## "expected exactly one ^BASE_FLAG ... found 2"

A downloaded record contains two base computers, which the game does allow but a
single-anchor import cannot represent. Decide which one is the real anchor and
remove the other from the build JSON by hand, or extract a trimmed version.

## The cached base I wanted is gone

It rotated out. The save keeps a limited set of other players' bases; flying
around replaces them. Visit it again in game, save, quit, and extract
immediately. Once extracted, the build file is yours to keep.

## "expected a 432-byte Steam meta" / "unexpected Steam meta format"

The game changed its metadata layout, most likely after an update. Stop. Do not
write. Everything else in the pipeline still reads fine, so you can scan and
extract; importing needs the layout re-verified first (see `save-format.md`).

## Steam asks about a cloud conflict on launch

Choose the **local** files. The edited save is the local one. This happens
because Steam noticed the file changed while the game was closed.

## The import finished but the game loads the old state

The game loads the newest save. If the player made a newer manual save after the
import (or the import targeted `save.hg` while their newest is `save2.hg`), the
old state is simply a different file. Check `scan_save.py`'s save list, then
re-run the import against the save they actually load with `--save save2.hg`.

## I want everything back

Every apply prints and logs this:

```
python scripts/import_build.py --restore "<backup folder>"
```

It takes a safety backup of the current state first, restores every file, and
verifies each hash against the backup manifest. Progress made after the import
is lost - that is what "back to before" means, and it is worth saying out loud
to the player before running it.
