"""Sync engine test: runs the real kit.py against the mock internet (tests/mock_remote.py) with tiny
made-up books and models. Covers downloads, resume, checksums, updates, leftover partial downloads,
verify --fix, adopting files already on the drive, offline runs, exit codes, which release of a program is
taken, ./kit update, SETUP.command's choices, and the launcher's first model and ports.
Needs only python3 and curl, so it runs in the quick gate and in cloud sessions.
usage: python3 tests/sync_test.py
"""
import hashlib
import http.server
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from pathlib import Path

TESTS = Path(__file__).resolve().parent
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + (f": {detail}" if detail and not ok else ""))
    fails += 0 if ok else 1


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


work = Path(tempfile.mkdtemp(prefix="kit sync test "))   # drive names often have spaces ("Samsung T7")
R = work / "remote"
for rel, size in (("zim/testmed_en_all_maxi_2026-01.zim", 70_000), ("zim/testsurvival_en_2026-02.zim", 60_000),
                  ("zim/testsurvival_en_2026-05.zim", 61_000), ("hf/tiny/Tiny-Q4_K_M.gguf", 300_000),
                  ("hf/tiny/Tiny-Q8_0.gguf", 200_000), ("hf/tiny_v2/Tiny-Q4_K_M.gguf", 310_000),
                  ("hf/two/Two-Q4_K_M.gguf", 150_000)):
    (R / rel).parent.mkdir(parents=True, exist_ok=True)
    (R / rel).write_bytes(os.urandom(size))
shutil.copy(R / "hf/tiny/Tiny-Q8_0.gguf", R / "hf/tiny_v2/Tiny-Q8_0.gguf")
for rel in ("gh/llama-b99990-bin-ubuntu-x64.tar.gz", "gh2/photon-1.3.0.jar", "gh2/photon-1.2.1.jar"):   # only looked up, never unpacked
    (R / rel).parent.mkdir(parents=True, exist_ok=True)
    (R / rel).write_bytes(os.urandom(1000))
(R / "FLAKY").touch()   # the first model download drops halfway, so sync has to resume it

port = free_port()
base = f"http://127.0.0.1:{port}"
mock = subprocess.Popen([sys.executable, str(TESTS / "mock_remote.py"), str(port)], env={**os.environ, "KIT_TEST_WORK": str(work)},
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
env = {**os.environ, "KIT_KIWIX_CATALOG": f"{base}/catalog/v2/entries?count=-1", "KIT_KIWIX_RELEASES": base + "/release/{product}/",
       "KIT_GITHUB_API": base, "KIT_HF": base, "KIT_ADOPTIUM_API": base + "/adoptium", "KIT_MAVEN": base + "/maven",
       "KIT_NPM": base + "/npm", "KIT_GITHUB_WEB": base + "/ghweb", "KIT_PROTOMAPS_BUILDS": base + "/protomaps/builds.json",
       "KIT_PROTOMAPS_BUILD_BASE": base + "/protomaps", "KIT_PHOTON_DUMPS": base + "/photon/"}

drive = work / "drive" / "TinfoilKit"
shutil.copytree(TESTS.parent / "tools", drive / "tools")
cfg = {
    "settings": {"default_model": "Tiny", "keep_free_gb": 0.001, "keep_free_gb_this_computer": 0.001, "downloader": "curl"},
    "models": [
        {"id": "Tiny", "type": "hf", "repo": "test/Tiny-GGUF", "files": ["*-Q4_K_M.gguf", "*-Q8_0.gguf"], "priority": 1},
        {"id": "Two", "type": "hf", "repo": "test/Two-GGUF", "files": ["*-Q4_K_M.gguf"]},
        {"id": "Ambiguous", "type": "hf", "repo": "test/Tiny-GGUF", "files": ["Tiny-*.gguf"]},
    ],
    "library": [
        {"zim": "testmed_en_all_maxi", "priority": 1},
        {"zim": "testsurvival_en"},
        {"zim": "does_not_exist_en"},
        {"zim": "disabled_one_en", "enabled": False},
    ],
}


def write_cfg():
    (drive / "kit.json").write_text(json.dumps(cfg, indent=1))


def kit(*args, env=env, root=None):
    root = root or drive
    p = subprocess.run([sys.executable, str(root / "tools" / "kit.py"), "--root", str(root), *args], env=env,
                       stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180)
    return p.returncode, p.stdout + p.stderr


def state():
    return json.loads((drive / ".kit" / "state.json").read_text())


def same(drive_rel, remote_rel):
    p = drive / drive_rel
    return p.exists() and sha(p) == sha(R / remote_rel)


try:
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    write_cfg()

    rc, out = kit("plan")
    check("plan lists new items and broken entries", rc == 0 and out.count("NEW") == 4 and out.count("ERROR") == 2, out)

    rc, out = kit("sync", "-y")
    check("sync exits 1 when entries are broken", rc == 1, f"exit {rc}")
    check("sync names the broken entries", "models/Ambiguous" in out and "library/does_not_exist_en" in out, out[-800:])
    check("an interrupted download resumes", not (R / "FLAKY").exists() and same("models/Tiny/Tiny-Q4_K_M.gguf", "hf/tiny/Tiny-Q4_K_M.gguf"))
    check("books and models downloaded intact",
          same("library/testmed_en_all_maxi_2026-01.zim", "zim/testmed_en_all_maxi_2026-01.zim")
          and same("library/testsurvival_en_2026-02.zim", "zim/testsurvival_en_2026-02.zim")
          and same("models/Tiny/Tiny-Q4_K_M.gguf", "hf/tiny/Tiny-Q4_K_M.gguf")
          and same("models/Tiny/Tiny-Q8_0.gguf", "hf/tiny/Tiny-Q8_0.gguf")
          and same("models/Two/Two-Q4_K_M.gguf", "hf/two/Two-Q4_K_M.gguf"), out)
    check("no partial downloads left", not list(drive.rglob("*.partial")), str(list(drive.rglob("*.partial"))))
    check("portal page built", (drive / ".kit" / "portal.html").exists())

    cfg["models"] = [m for m in cfg["models"] if m["id"] != "Ambiguous"]
    cfg["library"] = [z for z in cfg["library"] if z["zim"] != "does_not_exist_en"]
    write_cfg()
    rc, out = kit("sync", "-y")
    check("second sync has nothing to do", rc == 0 and "Everything is up to date." in out, out)

    rc, out = kit("verify")
    check("verify passes", rc == 0 and "All 5 files OK" in out, out)
    book = drive / "library/testmed_en_all_maxi_2026-01.zim"
    data = bytearray(book.read_bytes())
    data[1000] ^= 0xFF
    book.write_bytes(bytes(data))
    rc, out = kit("verify")
    check("verify finds a corrupt book", rc == 1 and "CORRUPT" in out, out)
    rc, out = kit("verify", "--fix")
    check("verify --fix removes it", rc == 1 and not book.exists(), out)
    rc, out = kit("sync", "-y")
    check("sync replaces it", rc == 0 and same("library/testmed_en_all_maxi_2026-01.zim", "zim/testmed_en_all_maxi_2026-01.zim"), out)

    # aria2c (optional, faster) fills a file in several places at once, so a download it was stopped on can already
    # be full length. Its record beside the file says it isn't whole. A stand-in aria2c finishes the job.
    fakebin = work / "bin"
    fakebin.mkdir()
    (fakebin / "aria2c").write_text(f"""#!{sys.executable}
import pathlib, sys, urllib.request
out = pathlib.Path(sys.argv[sys.argv.index("-d") + 1]) / sys.argv[sys.argv.index("-o") + 1]
out.write_bytes(urllib.request.urlopen(sys.argv[-1]).read())
pathlib.Path(str(out) + ".aria2").unlink()
""")
    (fakebin / "aria2c").chmod(0o755)
    model = drive / "models/Two/Two-Q4_K_M.gguf"
    model.unlink()
    partial = model.with_name(model.name + ".partial")
    partial.write_bytes(os.urandom((R / "hf/two/Two-Q4_K_M.gguf").stat().st_size))
    record = partial.with_name(partial.name + ".aria2")
    record.touch()
    cfg["settings"]["downloader"] = "aria2c"
    write_cfg()
    rc, out = kit("sync", "-y", env={**env, "PATH": f"{fakebin}{os.pathsep}{env['PATH']}"})
    cfg["settings"]["downloader"] = "curl"
    write_cfg()
    check("aria2c: a full-length download it hadn't finished is resumed, not taken as done",
          rc == 0 and same("models/Two/Two-Q4_K_M.gguf", "hf/two/Two-Q4_K_M.gguf") and not record.exists(), out)

    # Which release of a program: llama.cpp's builds are its nightly prereleases, but Photon's newest release
    # here is a beta, and a beta is taken only when there's nothing else.
    rt = work / "runtimes"
    shutil.copytree(TESTS.parent / "tools", rt / "tools")
    (rt / "kit.json").write_text(json.dumps({"runtimes": [
        {"id": "llama.cpp-linux-x64", "type": "github", "repo": "ggml-org/llama.cpp", "asset": "llama-*-bin-ubuntu-x64.tar.gz"},
        {"id": "photon", "type": "github", "repo": "komoot/photon", "asset": "photon-[0-9]*.jar"}]}))
    rc, out = kit("plan", root=rt)
    check("plan: llama.cpp's nightly build, and Photon's full release rather than its newer beta",
          rc == 0 and "b99990" in out and "1.3.0" in out and "2.0.0-beta" not in out, out)

    (drive / ".kit" / "state.json").unlink()
    rc, out = kit("sync", "-y")
    check("lost state: files on the drive are checked and kept, not downloaded again",
          rc == 0 and out.count("found ") == 5 and "downloading" not in out, out)

    # Three months later. Plant leftovers an interrupted sync could have left behind:
    # a book download from an older edition, a model download of the old file under the same name,
    # and a download for a book that's switched off (kept, in case it's switched back on).
    old_book = drive / "library/testsurvival_en_2025-11.zim.partial"
    old_book.write_bytes(os.urandom(1000))
    stale_model = drive / "models/Tiny/Tiny-Q4_K_M.gguf.partial"
    stale_model.write_bytes(os.urandom(100_000))
    off_book = drive / "library/disabled_one_en_2026-01.zim.partial"
    off_book.write_bytes(os.urandom(1000))
    too_big = drive / "library/testsurvival_en_2026-05.zim.partial"   # not tracked, and bigger than the real file
    too_big.write_bytes(os.urandom(70_000))
    st = state()
    st["partials"] = {
        "library/testsurvival_en_2025-11.zim.partial": {"item": "library/testsurvival_en", "tag": "2025-11|999"},
        "models/Tiny/Tiny-Q4_K_M.gguf.partial": {"item": "models/Tiny", "tag": sha(R / "hf/tiny/Tiny-Q4_K_M.gguf")},
        "library/disabled_one_en_2026-01.zim.partial": {"item": "library/disabled_one_en", "tag": "2026-01|1000"},
    }
    (drive / ".kit" / "state.json").write_text(json.dumps(st))
    (R / "STATE_V2").touch()
    (drive / ".kit/cache/kiwix-catalog.xml").unlink()
    rc, out = kit("sync", "-y")
    check("update: new editions installed", rc == 0 and same("library/testsurvival_en_2026-05.zim", "zim/testsurvival_en_2026-05.zim")
          and same("models/Tiny/Tiny-Q4_K_M.gguf", "hf/tiny_v2/Tiny-Q4_K_M.gguf"), out)
    check("update: old edition removed", not (drive / "library/testsurvival_en_2026-02.zim").exists(), out)
    check("update: a partial download of an older edition is deleted", not old_book.exists(), out)
    check("update: a partial download of an older file isn't resumed into the new one", "discarding" in out, out)
    check("update: a switched-off book's partial download is kept", off_book.exists())
    check("update: a partial download bigger than the new file starts over", out.count("discarding") == 2, out)
    check("update: leftovers are forgotten", sorted(state().get("partials", {})) == ["library/disabled_one_en_2026-01.zim.partial"],
          str(state().get("partials")))

    rc, out = kit("status")
    check("status, including the switched-off book's unfinished download",
          rc == 0 and "Last complete sync" in out and "library/disabled_one_en_2026-01.zim.partial" in out, out)

    # How much room the kit needs, before anything is looked up online: the builder's sizes for what's switched on.
    (drive / "site").mkdir()
    (drive / "site" / "sources.json").write_text(json.dumps({"sources": [
        {"id": "Tiny", "bytes": 2 * 10**9}, {"id": "Two", "bytes": 3 * 10**9}, {"id": "testmed_en_all_maxi", "bytes": 4 * 10**9},
        {"id": "disabled_one_en", "bytes": 100 * 10**9}, {"id": "maps", "bytes": 20 * 10**9}]}))
    rc, out = kit("estimate")
    check("estimate: the builder's sizes of what's switched on, plus 1 GB of programs", rc == 0 and out.strip() == "10", out)
    shutil.rmtree(drive / "site")

    # On the computer's own disk (the one with the home folder) the kit leaves more room free than on a drive.
    (work / "home").mkdir()
    cfg["settings"]["keep_free_gb_this_computer"] = 10**9     # more than any disk has
    write_cfg()
    rc, out = kit("plan", env={**env, "HOME": str(work / "home")})
    check("on the computer's own disk, the kit keeps keep_free_gb_this_computer free", "WARNING: that leaves less" in out, out)
    shm = Path("/dev/shm")
    if shm.is_dir() and shm.stat().st_dev != work.stat().st_dev:
        rc, out = kit("plan", env={**env, "HOME": str(shm)})
        check("on a drive, keep_free_gb_this_computer doesn't apply", rc == 0 and "WARNING" not in out, out)
    cfg["settings"]["keep_free_gb_this_computer"] = 0.001
    write_cfg()

    junk = [drive / "library" / "._junk.zim", drive / "models" / "Tiny" / "._Tiny-Q4_K_M.gguf"]
    for j in junk:
        j.write_bytes(b"\0\5\26\7")   # macOS's metadata files on exFAT start like this
    books = len(list((drive / "library").glob("[!.]*.zim")))
    rc, out = kit("test")
    check("test: clears macOS's ._ files before starting the servers",
          not any(j.exists() for j in junk) and f"library files present: {books} .zim files" in out, out)

    nowhere = "http://127.0.0.1:9"     # nothing listens there
    off = {**env, "KIT_HF": nowhere, "KIT_KIWIX_CATALOG": nowhere + "/catalog"}
    (drive / ".kit/cache/kiwix-catalog.xml").unlink()
    rc, out = kit("sync", "-y", env=off)
    check("offline: sync stops with one clear message", rc == 1 and "Check that this computer is online" in out
          and "Problems" not in out and out.count("Kiwix catalog") <= 3, out)
    (drive / ".kit/cache").mkdir(exist_ok=True)
    portal = env["KIT_KIWIX_CATALOG"].replace("/catalog/v2/entries?count=-1", "/wifi-sign-in")
    rc, out = kit("plan", env={**off, "KIT_KIWIX_CATALOG": portal})
    check("Wi-Fi sign-in page: plan says so and nothing is cached",
          rc == 1 and not (drive / ".kit/cache/kiwix-catalog.xml").exists(), out)

    # ./kit update: a kit on the drive, its kit.json changed by its owner, and releases of the kit's code
    # published on the mock GitHub. site/kit.json is the copy of kit.json the kit's current version came with.
    up = work / "update" / "TinfoilKit"
    code = {rel: (TESTS.parent / rel).read_bytes() for rel in ("kit", "SETUP.command", "START-HERE.command", "UNINSTALL.command")}
    code.update({p.relative_to(TESTS.parent).as_posix(): p.read_bytes() for p in (TESTS.parent / "tools").rglob("*")
                 if p.is_file() and "__pycache__" not in p.parts})
    for rel, data in code.items():
        (up / rel).parent.mkdir(parents=True, exist_ok=True)
        (up / rel).write_bytes(data)
    base_cfg = {"settings": {"default_model": "Tiny", "context_size": 8192},
                "models": [{"id": "Tiny", "repo": "test/Tiny-GGUF", "files": ["*-Q4_K_M.gguf"]},
                           {"id": "Two", "repo": "test/Two-GGUF", "files": ["*-Q4_K_M.gguf"]}],
                "library": [{"zim": "testmed_en_all_maxi"}, {"zim": "gone_en"}, {"zim": "testsurvival_en"}]}
    (up / "site").mkdir()
    (up / "site" / "kit.json").write_text(json.dumps(base_cfg, indent=1))
    mine = json.loads(json.dumps(base_cfg))
    mine["settings"]["default_model"] = "Two"
    mine["library"][0]["enabled"] = False           # switched off
    mine["library"][1]["enabled"] = True            # switched on, then dropped by the new version
    mine["library"].append({"zim": "mine_en"})      # added by hand
    mine_text = json.dumps(mine, indent=1)
    (up / "kit.json").write_text(mine_text)
    v2_cfg = json.loads(json.dumps(base_cfg))
    v2_cfg["settings"]["context_size"] = 16384
    v2_cfg["models"][1]["note"] = "new in v2"
    v2_cfg["library"] = [z for z in v2_cfg["library"] if z["zim"] != "gone_en"] + [{"zim": "new_en"}]

    def publish(tag, files, links=(), body=""):
        """A release on the mock GitHub, packed the way GitHub packs one: everything under one top folder."""
        (R / "gh").mkdir(exist_ok=True)
        name = f"kit-{tag}-{len(list((R / 'gh').glob('kit-*')))}.tar.gz"
        with tarfile.open(R / "gh" / name, "w:gz") as tf:
            for rel, data in files.items():
                info = tarfile.TarInfo(f"tudor-city-ventures-tinfoilkit-abc1234/{rel}")
                info.size, info.mode = len(data), 0o755 if rel in ("kit", "SETUP.command") or rel.endswith(".sh") else 0o644
                tf.addfile(info, io.BytesIO(data))
            for rel, target in links:
                info = tarfile.TarInfo(f"tudor-city-ventures-tinfoilkit-abc1234/{rel}")
                info.type, info.linkname = tarfile.SYMTYPE, target
                tf.addfile(info)
        (R / "kit").mkdir(exist_ok=True)
        (R / "kit" / "release.json").write_text(json.dumps({"tag_name": tag, "tarball_url": f"{base}/gh/{name}", "body": body}))

    def kit_json(cfg):
        text = json.dumps(cfg, indent=4).encode()
        return {"kit.json": text, "site/kit.json": text}

    rc, out = kit("update", root=up)
    check("kit update: no release published yet: says so, changes nothing", rc == 0 and "No version of the kit is published" in out, out)
    rc, out = kit("update", root=up, env={**env, "KIT_GITHUB_API": "http://127.0.0.1:9"})
    check("kit update: offline: says so", rc == 1 and "Couldn't reach GitHub" in out, out)
    good = {**code, **kit_json(v2_cfg), "docs/v2.txt": b"v2"}
    # A copy from GitHub carries its commit in kit.py, and one taken from the main branch can be newer than the release.
    sha = "a" * 40
    (up / "tools/kit.py").write_bytes(code["tools/kit.py"].replace(b'KIT_COMMIT = "$Format:%H$"', f'KIT_COMMIT = "{sha}"'.encode()))
    (R / "kit" / "compare").mkdir(parents=True)
    publish("v1.9", good)
    (R / "kit" / "compare" / f"v1.9...{sha}").write_text('{"status": "ahead"}')
    rc, out = kit("update", root=up)
    check("kit update: a copy newer than the latest release stays", rc == 0 and "newer than its latest release (v1.9)" in out
          and not (up / "docs").exists(), out)
    (R / "kit" / "compare" / f"v1.9...{sha}").write_text('{"status": "identical"}')
    rc, out = kit("update", root=up)
    check("kit update: a copy of the latest release notes its version, installs nothing", rc == 0 and "newest version (v1.9)" in out
          and not (up / "docs").exists() and json.loads((up / ".kit/state.json").read_text())["kit_version"] == "v1.9", out)
    # Each with the reason it gives, so a check that stops working can't hide behind a later one.
    bad = {"a link": (dict(files=good, links=[("tools/evil", "kit.py")]), "a link in it"),
           "a path outside its folder": (dict(files={**good, "../../escaped.txt": b"x"}), "unexpected path"),
           "a missing file": (dict(files={k: v for k, v in good.items() if k != "tools/launch.sh"}), "missing tools/launch.sh"),
           "a kit.py this Python can't run": (dict(files={**good, "tools/kit.py": b"def broken(:\n"}), "won't run")}
    for what, (release, why) in bad.items():
        publish("v2", **release)
        rc, out = kit("update", root=up)
        check(f"kit update: a release with {what} is refused and nothing changes",
              rc == 1 and "couldn't install version v2" in out and why in out and not (up / "docs").exists()
              and not (work / "escaped.txt").exists() and (up / "kit.json").read_text() == mine_text, out)
    publish("v2", good, body="Faster answers.\nBetter maps.")
    (up / "kit.json").write_text(mine_text.replace('"Two"', '"Two",', 1))
    rc, out = kit("update", root=up)
    check("kit update: a typo in kit.json stops it before anything changes", rc == 1 and "syntax error on line" in out
          and not (up / "docs").exists(), out)
    (up / "kit.json").write_text(mine_text)
    rc, out = kit("update", root=up)
    merged = json.loads((up / "kit.json").read_text())
    check("kit update: installs the release, shows what's new", rc == 3 and "Installed version v2" in out and "Better maps." in out
          and (up / "docs/v2.txt").exists() and json.loads((up / ".kit/state.json").read_text())["kit_version"] == "v2", out)
    check("kit update: kit.json keeps this drive's choices and gets the release's changes",
          merged["settings"] == {"default_model": "Two", "context_size": 16384} and merged["models"][1]["note"] == "new in v2"
          and [(z["zim"], z.get("enabled", True)) for z in merged["library"]]
          == [("testmed_en_all_maxi", False), ("testsurvival_en", True), ("new_en", True), ("mine_en", True)], json.dumps(merged))
    rc, out = kit("update", root=up)
    check("kit update: already the newest", rc == 0 and "This is the newest version (v2)" in out, out)
    v3_cfg = {**v2_cfg, "settings": {**v2_cfg["settings"], "context_size": 32768}}
    publish("v3", {**code, **kit_json(v3_cfg), "docs/v3.txt": b"v3"})
    rc, out = kit("update", root=up)
    merged = json.loads((up / "kit.json").read_text())
    check("kit update: the next release removes files the last one installed and still keeps the choices",
          rc == 3 and not (up / "docs/v2.txt").exists() and (up / "docs/v3.txt").exists()
          and merged["settings"] == {"default_model": "Two", "context_size": 32768} and merged["library"][-1] == {"zim": "mine_en"}, out)
    (up / "kit.json").write_text((up / "site/kit.json").read_text())
    rc, out = kit("update", "--force", root=up)
    check("kit update: a kit.json nobody changed becomes the release's, byte for byte",
          rc == 3 and (up / "kit.json").read_bytes() == json.dumps(v3_cfg, indent=4).encode(), out)
    (up / ".git").mkdir()
    rc, out = kit("update", root=up)
    check("kit update: leaves a git checkout to git", rc == 0 and "git pull" in out, out)

    # SETUP.command's choices, with a stand-in ./kit that exits as told. Its update rewrites SETUP.command in
    # place, the hard case for bash, which reads a script as it goes.
    stand_in = """#!/bin/bash
case "$1" in drives|place) exec python3 "@KIT_PY@" --root "$(pwd)" "$@";; esac    # the real ones
echo "kit $1" >> calls.log
case "$1" in
  estimate) echo "${ESTIMATE:-1}";;
  update) [ "$UPDATE" = 3 ] && sed 's/Step 2 of 3:/Step 2 of 3 (new version):/' SETUP.command > new && cat new > SETUP.command
          exit $UPDATE;;
  plan) exit $PLAN;;
  sync) mkdir -p logs; echo "===== sync started =====" >> logs/sync-2026-01-01.log
        [ $SYNC = 1 ] && printf 'Problems (everything else is done):\n  - models/Big: download failed\nRe-run ./kit sync\n' >> logs/sync-2026-01-01.log
        exit $SYNC;;
  test) exit $TEST;;
  share|autostart) echo "$*" >> home.log;;
esac""".replace("@KIT_PY@", str(TESTS.parent / "tools" / "kit.py"))

    def kit_folder(path, git=False):
        """A kit's code as Download ZIP leaves it (or a git checkout), with the stand-in ./kit."""
        path.mkdir(parents=True)
        shutil.copy(TESTS.parent / "SETUP.command", path)
        (path / "kit").write_text(stand_in)
        (path / "kit").chmod(0o755)
        (path / "tools").mkdir()
        (path / "tools" / "kit.py").write_text("# stand-in\n")
        (path / "GUIDE.md").write_text("guide\n")
        if git:
            (path / ".git").mkdir()
        return path

    setup = kit_folder(work / "setup")
    (setup / ".kit").mkdir()     # set up before, so SETUP doesn't ask where it goes

    def run_setup(plan=0, sync=0, test=0, update=0, folder=setup, answers="y\nn\n\n", args=(), **env_extra):
        shutil.copy(TESTS.parent / "SETUP.command", folder)
        (folder / "calls.log").write_text("")
        (folder / "home.log").write_text("")
        p = subprocess.run(["bash", str(folder / "SETUP.command"), *args], input=answers, capture_output=True, text=True, timeout=60,
                           env={**os.environ, "PLAN": str(plan), "SYNC": str(sync), "TEST": str(test), "UPDATE": str(update),
                                **env_extra})
        return p.returncode, p.stdout, (folder / "calls.log").read_text().split()[1::2]

    rc, out, calls = run_setup()
    check("SETUP: all good", rc == 0 and "All set" in out and calls == ["update", "plan", "sync", "test"]
          and "Step 1 of 3: the kit is on" in out and "where should the kit go" not in out, out)
    (setup / ".kit" / "state.json").write_text('{"items": {}, "last_sync": "2026-01-01T00:00:00"}')
    rc, out, calls = run_setup()
    check("SETUP: set up before: says it's an update, and how to update next time",
          rc == 0 and "TINFOIL KIT UPDATE" in out and "TINFOIL KIT SETUP" not in out
          and "whenever you want the newest AI models" in out and calls == ["update", "plan", "sync", "test"], out)
    (setup / ".kit" / "state.json").unlink()
    rc, out, calls = run_setup(update=3)
    check("SETUP: after updating the kit it starts over on the new SETUP, once",
          rc == 0 and "Step 2 of 3 (new version):" in out and out.count("TINFOIL KIT SETUP") == 1
          and calls == ["update", "plan", "sync", "test"], out)
    rc, out, calls = run_setup(update=1)
    check("SETUP: the kit's own update failed: carries on", rc == 0 and "All set" in out and calls == ["update", "plan", "sync", "test"], out)
    rc, out, calls = run_setup(sync=1)
    check("SETUP: some downloads failed but the kit works: says so and lists them",
          rc == 1 and "didn't finish" in out and "models/Big: download failed" in out and "All set" not in out, out)
    rc, out, calls = run_setup(sync=1, test=1)
    check("SETUP: checks failed", rc == 1 and "Some checks failed" in out and "models/Big" in out, out)
    rc, out, calls = run_setup(sync=130)
    check("SETUP: Ctrl-C during the download", rc == 130 and "Stopped" in out and calls == ["update", "plan", "sync"], out)
    rc, out, calls = run_setup(plan=1)
    check("SETUP: offline: stops before asking to download", rc == 1 and calls == ["update", "plan"] and "Start downloading" not in out, out)
    home = ["share on", "autostart on", "share"]
    check("SETUP: a normal setup doesn't share the kit or start it with the computer", (setup / "home.log").read_text() == "")
    rc, out, calls = run_setup(args=("--home-server",), answers="y\n\n")
    check("SETUP --home-server: shares the kit, starts it with the computer, shows the address, and doesn't open it",
          rc == 0 and calls[:4] == ["update", "plan", "sync", "test"] and (setup / "home.log").read_text().splitlines() == home
          and "Home server" in out and "Open the kit now" not in out and "double-click START-HERE" not in out, out)
    rc, out, calls = run_setup(update=3, args=("--home-server",), answers="y\n\n")
    check("SETUP --home-server: still a home server after the kit updates itself and starts over",
          rc == 0 and "(new version)" in out and (setup / "home.log").read_text().splitlines() == home, out)
    rc, out, calls = run_setup(sync=1, args=("--home-server",), answers="y\n\n")
    check("SETUP --home-server: some downloads failed but the kit works: shares it anyway",
          rc == 1 and "didn't finish" in out and (setup / "home.log").read_text().splitlines() == home, out)
    rc, out, calls = run_setup(test=1, args=("--home-server",), answers="y\n\n")
    check("SETUP --home-server: checks failed: doesn't share it", rc == 1 and (setup / "home.log").read_text() == "", out)

    # The first run asks where the kit goes, moves it there, and the copy there does the rest. Drives are folders
    # in a stand-in for /Volumes; /dev/shm, a different disk, stands in for a drive the kit has to be copied to.
    roomy = work / "roomy"
    roomy.mkdir()
    (roomy / "df").write_text("#!/bin/sh\necho 'Filesystem 1024-blocks Used Available Capacity Mounted on'\n"
                              "echo 'disk 2000000000 1000000000 1000000000 50% /'\n")
    (roomy / "df").chmod(0o755)

    def first_run(answers, drives=(), git=False, home_kit=None, **env_extra):
        """SETUP's first run, on a computer whose disk has 1 TB free (a stand-in df)."""
        place = work / "place"
        shutil.rmtree(place, ignore_errors=True)
        home, vols = place / "home", place / "Volumes"
        home.mkdir(parents=True)
        vols.mkdir()
        for d in drives:
            (vols / d).mkdir()
        if home_kit == "kit":
            kit_folder(home / "TinfoilKit")
        elif home_kit == "other":
            (home / "TinfoilKit").mkdir()
            (home / "TinfoilKit" / "notes.txt").write_text("mine")
        dl = kit_folder(place / "Downloads" / "tinfoilkit-main", git=git)
        (dl / "calls.log").write_text("")
        p = subprocess.run(["bash", str(dl / "SETUP.command")], input=answers, capture_output=True, text=True, timeout=60,
                           env={**os.environ, "HOME": str(home), "KIT_DRIVES": str(env_extra.pop("KIT_DRIVES", vols)),
                                "PATH": f"{roomy}:{os.environ['PATH']}",
                                "PLAN": "0", "SYNC": "0", "TEST": "0", "UPDATE": "0", **env_extra})
        return p.returncode, p.stdout + p.stderr, dl, home, vols    # ./kit place says what it did on stderr

    def placed_ok(where):
        log = where / "calls.log"
        return ((where / "SETUP.command").exists() and (where / "kit").exists() and (where / "tools/kit.py").exists()
                and (where / ".kit").is_dir() and log.exists() and log.read_text().split()[1::2][-4:] == ["update", "plan", "sync", "test"])

    rc, out, dl, home, vols = first_run("2\ny\nn\n\n")
    check("SETUP first run: this computer: the kit moves to TinfoilKit in the home folder and sets up there",
          rc == 0 and "where should the kit go" in out and "needs about 1 GB" in out and placed_ok(home / "TinfoilKit")
          and not dl.exists() and "Moved the kit to this computer" in out and out.count("TINFOIL KIT SETUP") == 1
          and "All set" in out, out)
    rc, out, _, _, _ = first_run("1\n1\ny\nn\n\n", drives=["SAMSUNG T7"])
    check("SETUP first run: a drive: lists it, the kit moves to TinfoilKit at its top and sets up there",
          rc == 0 and "1  SAMSUNG T7 (" in out and "Look again" in out and placed_ok(vols / "SAMSUNG T7" / "TinfoilKit")
          and "Moved the kit to the drive SAMSUNG T7" in out and "All set" in out, out)
    rc, out, _, home, _ = first_run("1\n2\ny\nn\n\n")
    check("SETUP first run: no drive plugged in: says so, and offers this computer instead",
          rc == 0 and "No external drive is plugged in" in out and placed_ok(home / "TinfoilKit"), out)
    rc, out, _, home, _ = first_run("2\ny\ny\nn\n\n", ESTIMATE="999999")
    check("SETUP first run: too little room on this computer: says so, and goes ahead when told to",
          rc == 0 and "too little for all of it" in out and "leaves 50 GB free" in out and placed_ok(home / "TinfoilKit"), out)
    rc, out, dl, home, _ = first_run("2\nn\n1\n2\ny\ny\nn\n\n", ESTIMATE="999999")
    check("SETUP first run: too little room: a no goes to the drives instead", rc == 0 and "No external drive" in out
          and placed_ok(home / "TinfoilKit"), out)
    rc, out, dl, home, _ = first_run("2\ny\nn\n\n", git=True)
    check("SETUP first run: a git checkout on this computer stays where it is",
          rc == 0 and placed_ok(dl) and not (home / "TinfoilKit").exists(), out)
    rc, out, dl, home, _ = first_run("2\ny\nn\n\n", home_kit="kit")
    check("SETUP first run: a kit already in the home folder: carries on with that one",
          rc == 0 and "already a Tinfoil Kit" in out and placed_ok(home / "TinfoilKit") and dl.exists(), out)
    rc, out, dl, home, _ = first_run("2\n", home_kit="other")
    check("SETUP first run: someone else's TinfoilKit folder is left alone",
          rc == 1 and "isn't a Tinfoil Kit" in out and (home / "TinfoilKit" / "notes.txt").read_text() == "mine"
          and dl.exists() and not (home / "TinfoilKit" / "SETUP.command").exists(), out)
    rc, out, _, _, _ = first_run("3\n")
    check("SETUP first run: a wrong answer asks again, and a closed window stops it", rc == 1 and "Type a number from 1 to 2" in out, out)
    shm = Path("/dev/shm")
    # (Docker mounts /dev/shm noexec, where the copied ./kit can't run.)
    if (shm.is_dir() and os.access(shm, os.W_OK) and shm.stat().st_dev != work.stat().st_dev
            and not os.statvfs(shm).f_flag & getattr(os, "ST_NOEXEC", 8)):
        drv = Path(tempfile.mkdtemp(prefix="kit drives ", dir=shm))
        try:
            (drv / "USB DRIVE").mkdir()
            rc, out, dl, _, _ = first_run("1\n1\ny\nn\n\n", KIT_DRIVES=drv, ESTIMATE="0")
            check("SETUP first run: a drive that's another disk: the kit is copied over, and the download removed",
                  rc == 0 and placed_ok(drv / "USB DRIVE" / "TinfoilKit") and not dl.exists() and "Moved the kit" in out
                  and not (drv / "USB DRIVE" / "TinfoilKit.partial").exists(), out)
            shutil.rmtree(drv / "USB DRIVE" / "TinfoilKit")
            rc, out, dl, _, _ = first_run("1\n1\ny\nn\n\n", git=True, KIT_DRIVES=drv, ESTIMATE="0")
            check("SETUP first run: a git checkout is copied to the drive, .git and all, and stays where it was",
                  rc == 0 and placed_ok(drv / "USB DRIVE" / "TinfoilKit") and (drv / "USB DRIVE" / "TinfoilKit" / ".git").is_dir()
                  and dl.exists() and "Use that copy from now on" in out, out)
        finally:
            shutil.rmtree(drv, ignore_errors=True)
    else:
        print("skip  SETUP first run: copying to another disk (no usable /dev/shm here)")

    # UNINSTALL.command: removes the kit and its downloads, only when asked, and stops the kit if it's running.
    def uninstall(*args, answers="", kit_files=True):
        gone = work / "gone" / "TinfoilKit"
        shutil.rmtree(gone.parent, ignore_errors=True)
        (gone / "models" / "Tiny").mkdir(parents=True)
        (gone / "models" / "Tiny" / "Tiny.gguf").write_bytes(os.urandom(5000))
        (gone / "library").mkdir()
        (gone / "library" / "book.zim").write_bytes(os.urandom(5000))
        shutil.copy(TESTS.parent / "UNINSTALL.command", gone)
        if kit_files:
            (gone / "kit").write_text(f'#!/bin/bash\necho "$*" >> "{work / "uninstall-kit.log"}"\n')
            (gone / "kit").chmod(0o755)
            (gone / "tools").mkdir()
            (gone / "tools" / "kit.py").write_text("# kit\n")
        (gone.parent / "keep.txt").write_text("not the kit's")
        p = subprocess.run(["bash", str(gone / "UNINSTALL.command"), *args], input=answers, capture_output=True, text=True,
                           timeout=60, env={**os.environ, "HOME": str(work)})
        return p.returncode, p.stdout, gone

    kit_log = work / "uninstall-kit.log"
    kit_log.write_text("")
    rc, out, gone = uninstall(answers="\n\n")
    check("UNINSTALL: says what it deletes, and just Return keeps everything",
          rc == 0 and "This deletes Tinfoil Kit" in out and "can't be undone" in out and "Kept" in out
          and (gone / "models/Tiny/Tiny.gguf").exists() and kit_log.read_text() == "", out)
    rc, out, gone = uninstall(answers="yes\n\n")
    check("UNINSTALL: anything but delete keeps it", rc == 0 and "Kept" in out and (gone / "library/book.zim").exists(), out)
    rc, out, gone = uninstall(answers="delete\n\n")
    check("UNINSTALL: typing delete removes the kit and its downloads, and nothing beside it",
          rc == 0 and not gone.exists() and (gone.parent / "keep.txt").exists() and "Tinfoil Kit is gone" in out, out)
    check("UNINSTALL: a home server's kit stops starting with the computer first", kit_log.read_text() == "autostart off\n",
          kit_log.read_text())
    rc, out, gone = uninstall(answers="delete\n\n", kit_files=False)
    check("UNINSTALL: refuses a folder that isn't a kit", rc == 1 and gone.exists() and "doesn't look like a Tinfoil Kit" in out, out)
    rc, out, gone = uninstall(answers="DELETE\n\n")
    check("UNINSTALL: DELETE in capitals works too", rc == 0 and not gone.exists(), out)

    def running_kit():
        """A kit whose AI server is running (a stand-in that sleeps), removed with --yes."""
        gone = work / "gone" / "TinfoilKit"
        shutil.rmtree(gone.parent, ignore_errors=True)
        srv = gone / "bin" / "llama.cpp-test" / "llama-server"
        srv.parent.mkdir(parents=True)
        srv.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(300)\n")
        srv.chmod(0o755)
        proc = subprocess.Popen([str(srv)])
        shutil.copy(TESTS.parent / "UNINSTALL.command", gone)
        (gone / "kit").write_text("#!/bin/bash\n")
        (gone / "tools").mkdir()
        (gone / "tools" / "kit.py").write_text("# kit\n")
        time.sleep(0.5)
        p = subprocess.run(["bash", str(gone / "UNINSTALL.command"), "--yes"], capture_output=True, text=True, timeout=60,
                           stdin=subprocess.DEVNULL, env={**os.environ, "HOME": str(work)})
        try:
            proc.wait(timeout=10)
            stopped = True
        except subprocess.TimeoutExpired:
            proc.kill()
            stopped = False
        return p.returncode, p.stdout, gone, stopped

    rc, out, gone, stopped = running_kit()
    check("UNINSTALL --yes: no question, stops the kit's running programs, removes it all",
          rc == 0 and stopped and not gone.exists() and "Stopping the kit" in out and "Press Return" not in out, out)

    # The launcher's first model, by the computer's memory. A stand-in for a running kit answers on both
    # server ports, so the launcher reuses them and only picks the model and prints the address.
    class RunningKit(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'{"data": []}' if self.path.startswith("/v1/models") else b"<title>Tinfoil Kit</title>"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    running = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RunningKit)
    threading.Thread(target=running.serve_forever, daemon=True).start()
    rport = running.server_address[1]
    lk = work / "launch"
    (lk / "tools").mkdir(parents=True)
    shutil.copy(TESTS.parent / "tools" / "launch.sh", lk / "tools")
    (lk / "kit.json").write_text(json.dumps({"settings": {"default_model": "Big", "library_port": rport, "ai_port": rport}}))
    for name, gb in (("Big", 18), ("Mid", 12), ("Small", 5)):
        (lk / "models" / name).mkdir(parents=True)
        with open(lk / "models" / name / f"{name}-Q4_K_M.gguf", "wb") as f:
            f.truncate(gb * 10**9)   # sparse, so it takes no space

    def launch(mem_gb, *args):
        p = subprocess.run(["bash", str(lk / "tools" / "launch.sh"), "--no-browser", *args], capture_output=True, text=True,
                           timeout=60, stdin=subprocess.DEVNULL, env={**os.environ, "KIT_MEMORY_MB": str(mem_gb * 1024)})
        out = p.stdout + p.stderr
        return (out.split("?model=")[1].split("&")[0] if "?model=" in out else ""), out

    for mem_gb, want in ((32, "Big"), (24, "Mid"), (16, "Small"), (4, "Small")):
        got, out = launch(mem_gb)
        check(f"launcher: {mem_gb} GB of memory starts {want}", got == want and (want == "Big" or f"{mem_gb} GB of memory" in out), out)
    got, out = launch(16, "--model=Big")
    check("launcher: --model wins over memory", got == "Big", out)
    (lk / "kit.json").write_text(json.dumps({"settings": {"default_model": "Gone", "library_port": rport, "ai_port": rport}}))
    got, out = launch(24)
    check("launcher: without the default model, the biggest that fits", got == "Mid" and "too little" not in out, out)

    # ./kit fit: which model this computer runs, and asking before downloading the ones too big for it.
    fk = work / "fit"
    shutil.copytree(TESTS.parent / "tools", fk / "tools")
    fit_json = """{
  "settings": {"default_model": "Big"},
  "models": [
    {
      "id": "Big",
      "type": "hf",
      "note": "Default. ~18 GB"
    },
    {
      "id": "Mid",
      "type": "hf",
      "note": "Mid-size. ~7.2 GB"
    },
    {
      "id": "Small",
      "type": "hf",
      "note": "Small. ~5.3 GB"
    }
  ]
}
"""
    (fk / "kit.json").write_text(fit_json)

    def fit(mem_gb, *args, answers=""):
        p = subprocess.run([sys.executable, str(fk / "tools" / "kit.py"), "--root", str(fk), "fit", *args], input=answers,
                           capture_output=True, text=True, timeout=60, env={**os.environ, "KIT_MEMORY_MB": str(mem_gb * 1024)})
        return p.returncode, p.stdout + p.stderr

    rc, out = fit(32)
    check("kit fit: enough memory for the default model", rc == 0 and "32 GB of memory, so its AI will be Big" in out
          and "can't run" not in out, out)
    rc, out = fit(16)
    check("kit fit: too little for the default: the biggest that fits, and which ones it can't run (changes nothing)",
          rc == 0 and "its AI will be Mid" in out and "It can't run Big: it needs 32 GB of memory or more" in out
          and "./kit fit --skip" in out and (fk / "kit.json").read_text() == fit_json, out)
    rc, out = fit(16, "--ask", answers="\n")
    on = {m["id"]: m.get("enabled", True) for m in json.loads((fk / "kit.json").read_text())["models"]}
    added = [line for line in (fk / "kit.json").read_text().splitlines() if line not in fit_json.splitlines()]
    check("kit fit --ask: just Return skips them, in kit.json, changing only that line",
          rc == 0 and "Download them anyway? [y/N]" in out and on == {"Big": False, "Mid": True, "Small": True}
          and added == ['      "enabled": false,'], out)
    rc, out = fit(16, "--ask")
    check("kit fit --ask: doesn't ask again about a skipped one", rc == 0 and "?" not in out and "Big" not in out, out)
    rc, out = fit(64, "--ask", answers="\n")
    check("kit fit --ask: a computer with more memory offers them back, and kit.json is as it was",
          rc == 0 and "skipped before on a computer with less memory" in out and "Its AI will be Big." in out
          and (fk / "kit.json").read_text() == fit_json, out)
    rc, out = fit(16, "--ask", answers="y\n")
    check("kit fit --ask: yes keeps them", rc == 0 and (fk / "kit.json").read_text() == fit_json, out)
    rc, out = fit(8, "--json")
    report = json.loads(out)
    check("kit fit --json: on 8 GB nothing fits, so the smallest, and the rest are too big",
          rc == 0 and report["runs"] == "Small" and report["too_big"] == ["Big", "Mid"], out)
    (fk / ".kit" / "state.json").write_text(json.dumps({"items": {"models/Big": {}}}))
    rc, out = fit(16, "--skip")
    check("kit fit --skip: leaves alone a model that's already downloaded", rc == 0 and "can't run" not in out
          and (fk / "kit.json").read_text() == fit_json, out)

    # Another program on the library's port (the mock internet, here): the library starts on the next one.
    fake = work / "fake-kiwix-serve"
    fake.write_text(f"""#!{sys.executable}
import http.server, sys, threading
if "--port" not in sys.argv:
    sys.exit(0)
class Page(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"<title>Tinfoil Kit</title>")
    def log_message(self, *a):
        pass
server = http.server.HTTPServer(("127.0.0.1", int(sys.argv[sys.argv.index("--port") + 1])), Page)
threading.Timer(3, server.shutdown).start()
server.serve_forever()
""")
    fake.chmod(0o755)
    (lk / "library").mkdir()
    (lk / "library" / "book.zim").touch()
    (lk / "kit.json").write_text(json.dumps({"settings": {"default_model": "Big", "library_port": port, "ai_port": rport}}))
    p = subprocess.run(["bash", str(lk / "tools" / "launch.sh"), "--no-browser"], capture_output=True, text=True, timeout=60,
                       stdin=subprocess.DEVNULL, env={**os.environ, "KIT_KIWIX_TOOLS_BIN": str(fake)})
    out = p.stdout + p.stderr
    check("launcher: another program on the library's port: it moves to the next free one",
          f"using port {port}, so the library uses" in out and "Library:  ready" in out and f":{port}/" not in out, out)

    # Windows has no unzip, and its tar may not read bzip2 (the address database): the kit unpacks in Python there.
    import importlib.util
    import zipfile
    spec = importlib.util.spec_from_file_location("kitpy", TESTS.parent / "tools" / "kit.py")
    kp = sys.modules["kitpy"] = importlib.util.module_from_spec(spec)    # dataclasses look the module up
    spec.loader.exec_module(kp)
    ex = work / "extract"
    ex.mkdir()
    with zipfile.ZipFile(ex / "a.zip", "w") as z:
        z.writestr("prog-1/bin/prog.exe", b"MZ")
        info = zipfile.ZipInfo("prog-1/bin/tool")
        info.external_attr = 0o100755 << 16
        z.writestr(info, b"#!")
    with tarfile.open(ex / "db.tar.bz2", "w:bz2") as tf:
        for name, data in (("photon_data/node_1/a.bin", b"x" * 5000), ("photon_data/b.txt", b"hi")):
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    kp.unzip_py(ex / "a.zip", ex / "z")
    check("unzip in Python: files land in place and programs stay runnable",
          (ex / "z/prog-1/bin/prog.exe").read_bytes() == b"MZ" and os.access(ex / "z/prog-1/bin/tool", os.X_OK))
    kp.untar_py(ex / "db.tar.bz2", ex / "t", "bz2")
    check("untar in Python: a bzip2 database unpacks", (ex / "t/photon_data/node_1/a.bin").stat().st_size == 5000
          and (ex / "t/photon_data/b.txt").read_bytes() == b"hi")
    for bad in ("../escape.txt", "/abs.txt", "C:/win.txt", "ok/../../escape.txt"):
        with zipfile.ZipFile(ex / "bad.zip", "w") as z:
            z.writestr(bad, b"no")
        try:
            kp.unzip_py(ex / "bad.zip", ex / "bad")
            refused = False
        except RuntimeError:
            refused = True
        check(f"unzip in Python refuses a path outside the folder: {bad}", refused and not (work / "escape.txt").exists())
    path = os.environ["PATH"]
    try:
        os.environ["PATH"] = str(ex / "empty")    # no unzip or tar: the Python fallback takes over
        target = ex / "prog"
        kp.extract_archive(ex / "a.zip", "a.zip", target)
        check("extracting without unzip installed", (target / "prog-1/bin/prog.exe").exists())
    finally:
        os.environ["PATH"] = path
finally:
    mock.terminate()
    shutil.rmtree(work, ignore_errors=True)

print("\nALL PASSED" if not fails else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
