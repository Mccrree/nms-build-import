# Setup

One-time, ten minutes. Everything after that is running scripts.

## 1. A PC save

Works with saves written by the PC game on Steam - that is what every write here
was verified on - and GOG, which uses the same files and folder (`DefaultUser`
profile). Game Pass keeps saves elsewhere (`%LOCALAPPDATA%\Packages\HelloGames…`)
in a different container format, which these scripts neither find nor write.
Console saves (PS, Xbox, Switch) are not accessible, and there is no way around that.

| Platform | Save folder |
|---|---|
| Windows | `%APPDATA%\HelloGames\NMS\` |
| macOS | `~/Library/Application Support/HelloGames/NMS/` |

Inside it is one profile folder per account: `st_<steam id>` for Steam,
`DefaultUser` for GOG. The scripts find it automatically; `--save-root` and
`--profile` override.

Files in the profile folder come in pairs - the save itself plus its metadata:

| File | What it is |
|---|---|
| `save.hg` + `mf_save.hg` | slot 1, autosave |
| `save2.hg` + `mf_save2.hg` | slot 1, manual save |
| `save3.hg` / `save4.hg` … | slot 2, and so on |

The game loads whichever is newest, which is why the tools default to the newest
save and why the metadata timestamp matters after a write.

## 2. Python 3.10 or newer

`python --version`. Nothing else to install - the scripts use only the standard
library.

## 3. libNOM.io.cli

This is what converts a save to JSON and back. Without it nothing here runs.

1. Download the CLI from https://github.com/zencq/libNOM.io/releases - take the
   `libNOM.io.cli.<platform>` asset for your OS (`libNOM.io.cli.win-x64.exe` on
   Windows, ~71 MB, a single executable), not the `.nupkg` library. Release 0.14.2
   reads and writes Voyagers saves (Version 4740). GitHub shows a sha256 digest for
   each asset; compare it after downloading.
2. Put it somewhere permanent, e.g. `C:\nms-tools\libNOM\` or `~/nms-tools/libNOM/`.
3. Point the scripts at it, either by environment variable or per run:

```
setx NMS_LIBNOM "C:\nms-tools\libNOM\libNOM.io.cli.win-x64.exe"   # Windows, new shells
export NMS_LIBNOM=~/nms-tools/libNOM/libNOM.io.cli.macos-arm64     # macOS shells
```

The scripts also look in the current folder, `./libNOM/`, `~/nms-tools/`, the
skill folder, and `PATH`.

## 4. Where backups go

Default `~/Documents/NMS-save-backups`. Override with `NMS_BACKUP_ROOT` or
`--backup-root`. Each apply creates a timestamped folder holding a full copy of
the save folder plus a manifest with a hash for every file, so a restore can be
verified rather than hoped for. They are small; keep several.

## 5. Check it works

```
python scripts/scan_save.py
```

Expect a list of save files, your own bases, and any other players' bases the
save has cached. If that prints, the whole toolchain is working.

## Steam Cloud

Editing a save while Steam is closed can make Steam notice a difference on the
next launch. If it asks which version to use, choose the **local** files - that
is the edited save. Nothing else needs to change; cloud sync keeps working.

## Keeping the game closed

The game writes the save on its own schedule, so a write while it runs is simply
lost - or worse, half-applied. The scripts check for a running game and refuse.
Save in game, quit to the desktop, then run.
