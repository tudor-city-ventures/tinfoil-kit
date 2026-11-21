"""Sync engine test: runs the real kit.py against the mock internet (tests/mock_remote.py) with tiny
made-up books and models. Covers downloads, resume, checksums, updates, leftover partial downloads,
verify --fix, adopting files already on the drive, offline runs, exit codes, and SETUP.command's choices.
Needs only python3 and curl, so it runs in the quick gate and in cloud sessions.
usage: python3 tests/sync_test.py
"""
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
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


work = Path(tempfile.mkdtemp(prefix="kit-sync-test-"))
R = work / "remote"
for rel, size in (("zim/testmed_en_all_maxi_2026-01.zim", 70_000), ("zim/testsurvival_en_2026-02.zim", 60_000),
                  ("zim/testsurvival_en_2026-05.zim", 61_000), ("hf/tiny/Tiny-Q4_K_M.gguf", 300_000),
                  ("hf/tiny/Tiny-Q8_0.gguf", 200_000), ("hf/tiny_v2/Tiny-Q4_K_M.gguf", 310_000),
                  ("hf/two/Two-Q4_K_M.gguf", 150_000)):
    (R / rel).parent.mkdir(parents=True, exist_ok=True)
    (R / rel).write_bytes(os.urandom(size))
shutil.copy(R / "hf/tiny/Tiny-Q8_0.gguf", R / "hf/tiny_v2/Tiny-Q8_0.gguf")
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
    "settings": {"default_model": "Tiny", "keep_free_gb": 0.001, "downloader": "curl"},
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


def kit(*args, env=env):
    p = subprocess.run([sys.executable, str(drive / "tools" / "kit.py"), "--root", str(drive), *args], env=env,
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

    nowhere = "http://127.0.0.1:9"     # nothing listens there
    off = {**env, "KIT_HF": nowhere, "KIT_KIWIX_CATALOG": nowhere + "/catalog"}
    (drive / ".kit/cache/kiwix-catalog.xml").unlink()
    rc, out = kit("sync", "-y", env=off)
    check("offline: sync stops with one clear message", rc == 1 and "Check that this Mac is online" in out
          and "Problems" not in out and out.count("Kiwix catalog") <= 3, out)
    (drive / ".kit/cache").mkdir(exist_ok=True)
    portal = env["KIT_KIWIX_CATALOG"].replace("/catalog/v2/entries?count=-1", "/wifi-sign-in")
    rc, out = kit("plan", env={**off, "KIT_KIWIX_CATALOG": portal})
    check("Wi-Fi sign-in page: plan says so and nothing is cached",
          rc == 1 and not (drive / ".kit/cache/kiwix-catalog.xml").exists(), out)

    # SETUP.command's choices, with a stand-in ./kit that exits as told
    setup = work / "setup"
    setup.mkdir()
    shutil.copy(TESTS.parent / "SETUP.command", setup)
    (setup / "kit").write_text("""#!/bin/bash
echo "kit $1" >> calls.log
case "$1" in
  plan) exit $PLAN;;
  sync) mkdir -p logs; echo "===== sync started =====" >> logs/sync-2026-01-01.log
        [ $SYNC = 1 ] && printf 'Problems (everything else is done):\n  - models/Big: download failed\nRe-run ./kit sync\n' >> logs/sync-2026-01-01.log
        exit $SYNC;;
  test) exit $TEST;;
esac""")
    (setup / "kit").chmod(0o755)

    def run_setup(plan=0, sync=0, test=0):
        (setup / "calls.log").write_text("")
        p = subprocess.run(["bash", "SETUP.command"], cwd=setup, input="y\nn\n\n", capture_output=True, text=True,
                           timeout=60, env={**os.environ, "PLAN": str(plan), "SYNC": str(sync), "TEST": str(test)})
        return p.returncode, p.stdout, (setup / "calls.log").read_text().split()[1::2]

    rc, out, calls = run_setup()
    check("SETUP: all good", rc == 0 and "All set" in out and calls == ["plan", "sync", "test"], out)
    rc, out, calls = run_setup(sync=1)
    check("SETUP: some downloads failed but the kit works: says so and lists them",
          rc == 1 and "didn't finish" in out and "models/Big: download failed" in out and "All set" not in out, out)
    rc, out, calls = run_setup(sync=1, test=1)
    check("SETUP: checks failed", rc == 1 and "Some checks failed" in out and "models/Big" in out, out)
    rc, out, calls = run_setup(sync=130)
    check("SETUP: Ctrl-C during the download", rc == 130 and "Stopped" in out and calls == ["plan", "sync"], out)
    rc, out, calls = run_setup(plan=1)
    check("SETUP: offline: stops before asking to download", rc == 1 and calls == ["plan"] and "Start downloading" not in out, out)
finally:
    mock.terminate()
    shutil.rmtree(work, ignore_errors=True)

print("\nALL PASSED" if not fails else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
