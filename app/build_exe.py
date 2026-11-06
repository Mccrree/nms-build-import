"""Build the Windows release: NMS-Build-Import.exe plus the bundled libNOM, licences and guide.

  python app/build_exe.py --libnom D:\\nms-tools\\libNOM\\libNOM.io.cli.win-x64.exe

Needs PyInstaller (pip install pyinstaller). Output, ignored by git:
  dist/NMS-Build-Import-<version>-win64/       the folder players unzip
  dist/NMS-Build-Import-<version>-win64.zip    the file to publish
libNOM is copied only if it matches the pinned 0.14.2 hash, so a release never ships a binary
nobody checked.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APP = REPO / "app"
LIBNOM_NAME = "libNOM.io.cli.win-x64.exe"
LIBNOM_SHA256 = "df81bef41618aaa63c8bbb7010117d21c4dd80803df3f34a561c4de73b92c189"  # release 0.14.2


def app_version() -> str:
    for line in (APP / "nms_app.py").read_text(encoding="utf-8").splitlines():
        if line.startswith("APP_VERSION"):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("APP_VERSION not found in nms_app.py")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the NMS Build Import Windows release")
    parser.add_argument("--libnom", type=Path, required=True, help=f"path to {LIBNOM_NAME} (0.14.2)")
    args = parser.parse_args()
    if sha256(args.libnom) != LIBNOM_SHA256:
        raise SystemExit(f"{args.libnom} is not libNOM.io.cli 0.14.2 (sha256 mismatch); download it again")

    version = app_version()
    work = REPO / "build" / "pyinstaller"
    dist = REPO / "dist"
    name = f"NMS-Build-Import-{version}-win64"
    out = dist / name
    shutil.rmtree(out, ignore_errors=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
                    "--name", "NMS-Build-Import", "--paths", str(REPO / "scripts"),
                    "--add-data", f"{REPO / 'assets' / 'part_catalog.json'}{';' if sys.platform == 'win32' else ':'}assets",
                    "--hidden-import", "make_views", "--distpath", str(out), "--workpath", str(work / "work"),
                    "--specpath", str(work), str(APP / "nms_app.py")], check=True)

    (out / "libNOM").mkdir()
    shutil.copy2(args.libnom, out / "libNOM" / LIBNOM_NAME)
    for extra in ("LICENSE.txt", "NOTICE.txt"):
        shutil.copy2(APP / "third_party" / "libNOM.io" / extra, out / "libNOM" / extra)
    shutil.copy2(APP / "README-使用说明.txt", out / "README-使用说明.txt")
    shutil.copy2(REPO / "LICENSE", out / "LICENSE.txt")

    archive = dist / f"{name}.zip"
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(out.rglob("*")):
            if path.is_file():
                bundle.write(path, f"{name}/{path.relative_to(out).as_posix()}")
    exe = out / "NMS-Build-Import.exe"
    print(f"\n{exe}  {exe.stat().st_size / 1e6:.1f} MB  sha256 {sha256(exe)}")
    print(f"{archive}  {archive.stat().st_size / 1e6:.1f} MB  sha256 {sha256(archive)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
