"""The Mac app's file work (mac/app.sh): finding the kit, setting one up, updating, removing, remembering it and moving
the app to Applications, in a made-up home folder with stand-ins for open, xattr and ditto. Plus its icon. The window
code needs a Mac to build: the drive test runs it there (tests/drive_test.sh mac).
usage: python3 tests/mac_test.py
"""
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + (f": {detail}" if detail and not ok else ""))
    fails += 0 if ok else 1


def make_kit(folder, books=False):
    for f in ("kit", "tools/kit.py", "SETUP.command", "UNINSTALL.command"):
        (folder / f).parent.mkdir(parents=True, exist_ok=True)
        (folder / f).write_text(f)
    if books:
        (folder / "library").mkdir()
        (folder / "library" / "wikipedia.zim").write_text("zim")
    return folder


work = Path(tempfile.mkdtemp())
try:
    home, volumes, bin_ = work / "home", work / "Volumes", work / "bin"
    res = work / "Tinfoil Kit.app" / "Contents" / "Resources"
    for d in (home, volumes, bin_, res):
        d.mkdir(parents=True)
    shutil.copy(ROOT / "mac" / "app.sh", res / "app.sh")
    make_kit(res / "kit")
    (res / "kit" / "GUIDE.md").write_text("guide")
    log = work / "calls.log"
    for name, body in {
        "open": 'echo "open $*" >> "$LOG"',
        "xattr": 'echo "xattr $*" >> "$LOG"',
        "ditto": '[ "$1" = --noqtn ] && shift; cp -R "$1" "$2"',
    }.items():
        (bin_ / name).write_text("#!/bin/sh\n" + body + "\n")
        (bin_ / name).chmod(0o755)
    env = dict(os.environ, HOME=str(home), LOG=str(log), PATH=f"{bin_}:{os.environ['PATH']}",
               KIT_VOLUMES=str(volumes), KIT_APP_OPEN=str(bin_ / "open"), KIT_APPLICATIONS=str(work / "Applications"))
    support = home / "Library" / "Application Support" / "TinfoilKit"

    def app(*args):
        log.write_text("")
        r = subprocess.run(["bash", str(res / "app.sh"), *args], env=env, capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout, log.read_text()

    def found():
        return [tuple(line.split("\t")) for line in app("find")[1].splitlines()]

    check("find: no kit anywhere", found() == [], found())

    home_kit = make_kit(home / "TinfoilKit", books=True)
    check("find: a kit with books in the home folder is ready, on this Mac",
          found() == [("ready", str(home_kit), "this Mac")], found())

    drive_kit = make_kit(volumes / "My Drive" / "TinfoilKit")
    (volumes / "Other").mkdir()
    check("find: a kit on a drive that setup stopped before any books is unfinished, and the drive is named",
          ("unfinished", str(drive_kit), "the drive My Drive") in found() and len(found()) == 2, found())

    rc, _, _ = app("remember", str(drive_kit))
    check("remember: the kit it opened", rc == 0 and (support / "last-kit").read_text() == f"{drive_kit}\n")
    check("find: the kit it opened last comes first, and once",
          found() == [("unfinished", str(drive_kit), "the drive My Drive"), ("ready", str(home_kit), "this Mac")], found())

    shutil.rmtree(volumes / "My Drive")
    check("find: the drive it opened last isn't plugged in",
          found() == [("unplugged", str(drive_kit), "the drive My Drive"), ("ready", str(home_kit), "this Mac")], found())

    (volumes / "My Drive").mkdir()
    check("find: a drive plugged in without the kit on it any more: not listed",
          found() == [("ready", str(home_kit), "this Mac")], found())

    app("remember", str(home / "Gone" / "TinfoilKit"))
    check("find: a kit on this Mac that's been deleted: not listed", found() == [("ready", str(home_kit), "this Mac")])

    (support / "python" / "bin").mkdir(parents=True)
    (support / "python" / "bin" / "python3").write_text("SETUP's Python")
    stale = support / "Setup" / "TinfoilKit"
    stale.mkdir(parents=True)
    (stale / "left-over").write_text("from a setup that stopped")
    rc, _, calls = app("setup")
    check("setup: copies the kit out of the app, fresh", rc == 0 and (stale / "SETUP.command").is_file()
          and (stale / "GUIDE.md").read_text() == "guide" and not (stale / "left-over").exists(), calls)
    check("setup: lifts the downloaded mark from the copy, then opens its SETUP in Terminal",
          calls.splitlines() == [f"xattr -dr com.apple.quarantine {stale}", f"xattr -d com.apple.quarantine {stale}/SETUP.command",
                                 f"open {stale}/SETUP.command"], calls)
    check("setup: leaves the Python SETUP got", (support / "python" / "bin" / "python3").is_file())

    rc, _, calls = app("setup", str(home_kit))
    check("setup KIT: carries on with that kit, copying nothing", rc == 0 and calls.splitlines()[-1] == f"open {home_kit}/SETUP.command", calls)
    _, _, calls = app("update", str(home_kit))
    check("update: SETUP in Terminal", calls.splitlines()[-1] == f"open {home_kit}/SETUP.command", calls)
    _, _, calls = app("remove", str(home_kit))
    check("remove: UNINSTALL in Terminal", calls.splitlines()[-1] == f"open {home_kit}/UNINSTALL.command", calls)

    old = work / "Applications" / "Tinfoil Kit.app"
    (old / "Contents").mkdir(parents=True)
    (old / "Contents" / "old-version").write_text("1.0")
    rc, out, _ = app("move", str(work / "Tinfoil Kit.app"))
    check("move: into Applications, over an older copy", rc == 0 and out.strip() == str(old)
          and (old / "Contents" / "Resources" / "app.sh").is_file() and not (old / "Contents" / "old-version").exists()
          and not old.with_name("Tinfoil Kit.app.partial").exists(), out)
    env["KIT_APPLICATIONS"] = str(work / "no-such-folder")
    rc, out, _ = app("move", str(work / "Tinfoil Kit.app"))
    mine = home / "Applications" / "Tinfoil Kit.app"
    check("move: into the user's own Applications when the main one is out of reach",
          rc == 0 and out.strip() == str(mine) and (mine / "Contents" / "Resources" / "kit" / "kit").is_file(), out)

    rc, out, _ = app("nonsense")
    check("an unknown command says how to use it", rc == 2 and "app.sh find" in out, out)

    icns = (ROOT / "mac" / "AppIcon.icns").read_bytes()
    chunks, i = {}, 8
    while i + 8 <= len(icns):
        kind, size = struct.unpack(">4sI", icns[i:i + 8])
        chunks[kind.decode()] = icns[i + 8:i + size]
        i += max(size, 8)
    sizes = {k: struct.unpack(">II", v[16:24])[0] for k, v in chunks.items() if v[:8] == b"\x89PNG\r\n\x1a\n"}
    check("the icon: every size macOS asks for, from 16 to 1024 pixels",
          icns[:4] == b"icns" and struct.unpack(">I", icns[4:8])[0] == len(icns)
          and sizes == {"icp4": 16, "icp5": 32, "ic11": 32, "icp6": 64, "ic12": 64, "ic07": 128, "ic08": 256,
                        "ic13": 256, "ic09": 512, "ic14": 512, "ic10": 1024}, sizes)
finally:
    shutil.rmtree(work, ignore_errors=True)

print("\nALL PASSED" if not fails else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
