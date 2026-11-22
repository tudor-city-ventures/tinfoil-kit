"""Sync engine test: runs the real kit.py against the mock internet (tests/mock_remote.py) with tiny
made-up books and models. Covers downloads, resume, checksums, updates, leftover partial downloads,
verify --fix, adopting files already on the drive, offline runs, exit codes, which release of a program is
taken, ./kit update, SETUP.command's choices, and the launcher's first model and ports.
Needs only python3 and curl, so it runs in the quick gate and in cloud sessions.
usage: python3 tests/sync_test.py
"""
import base64
import bz2
import contextlib
import difflib
import hashlib
import http.server
import importlib.util
import io
import json
import os
import re
import shutil
import signal
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
for rel in ("gh/llama-b99990-bin-ubuntu-x64.tar.gz", "gh2/photon-1.3.0.jar", "gh2/photon-1.2.1.jar",   # only looked up, never unpacked
            "adoptium/OpenJDK21U-jre_x64_linux_hotspot_21.0.9_10.tar.gz", "photon/north-america/usa/photon-db-usa-1.3-latest.tar.bz2",
            "geofabrik/us-northeast-latest.osm.pbf"):
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
       "KIT_PROTOMAPS_BUILD_BASE": base + "/protomaps", "KIT_PHOTON_DUMPS": base + "/photon/", "KIT_GEOFABRIK": base + "/geofabrik",
       "KIT_PART_MIN": "16384"}    # so the books and models here, 60 to 310 KB, come over several connections in 16 KB parts

drive = work / "drive" / "TinfoilKit"
listed = -(-70_000 // 1024) * 1024    # testmed's size in the catalog: Kiwix rounds each up to a whole KiB
shutil.copytree(TESTS.parent / "tools", drive / "tools")
cfg = {
    "settings": {"default_model": "Tiny", "keep_free_gb": 0.001, "keep_free_gb_this_computer": 0.001},
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
    rc, out = kit("plan", "--essentials")
    check("plan --essentials: the AI this computer runs and the most important books, nothing else",
          rc == 0 and out.count("NEW") == 2 and "Tiny" in out and "testmed_en_all_maxi" in out and "Two" not in out
          and "testsurvival" not in out and "ERROR" not in out, out)
    kit("essentials", "on")
    rc, out = kit("plan")
    kit("essentials", "off")
    check("plan with essentials_only set: just those, and it says so", rc == 0 and out.count("NEW") == 2
          and "Just the essentials" in out and "Two" not in out and json.loads((drive / "kit.json").read_text()) == cfg, out)

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
    catalog = subprocess.run(["curl", "-fsS", env["KIT_KIWIX_CATALOG"]], capture_output=True, text=True).stdout
    check("books listed at sizes rounded up to a whole KiB, as Kiwix's catalog does, download on the first try",
          f'testmed_en_all_maxi_2026-01.zim.meta4" length="{listed}"' in catalog and "download interrupted (exit 0" not in out, out)
    check("no partial downloads left", not list(drive.rglob("*.partial")), str(list(drive.rglob("*.partial"))))
    check("portal page built, with no refresh date while a sync hasn't finished cleanly",
          "window.KIT_REFRESHED = null;" in (drive / ".kit" / "portal.html").read_text())

    cfg["models"] = [m for m in cfg["models"] if m["id"] != "Ambiguous"]
    cfg["library"] = [z for z in cfg["library"] if z["zim"] != "does_not_exist_en"]
    write_cfg()
    rc, out = kit("sync", "-y")
    check("second sync has nothing to do", rc == 0 and "Everything is up to date." in out, out)
    check("the page shows when everything was last brought up to date",
          f'window.KIT_REFRESHED = "{state().get("last_sync")}";' in (drive / ".kit" / "portal.html").read_text())

    # SETUP's first run gets the essentials first, then the rest.
    ess = work / "essentials"
    shutil.copytree(TESTS.parent / "tools", ess / "tools")
    (ess / "kit.json").write_text(json.dumps({"settings": cfg["settings"], "models": [cfg["models"][1]],
                                              "library": cfg["library"][:2]}))
    rc, out = kit("sync", "-y", "--essentials", root=ess)
    ess_state = json.loads((ess / ".kit" / "state.json").read_text())
    check("sync --essentials: gets only those, and doesn't count as a complete sync",
          rc == 0 and (ess / "models/Two/Two-Q4_K_M.gguf").exists() and list((ess / "library").glob("testmed_*.zim"))
          and not list((ess / "library").glob("testsurvival_*")) and "last_sync" not in ess_state, out)
    rc, out = kit("sync", "-y", root=ess)
    check("sync after the essentials: gets the rest", rc == 0 and list((ess / "library").glob("testsurvival_*.zim"))
          and "last_sync" in json.loads((ess / ".kit" / "state.json").read_text()), out)

    # Before that, it gets the try-it kit (./kit starter): this computer's programs, the map, and the AI and books
    # marked "starter", even ones that are switched off (samples). The full sync after it removes the samples.
    tk = work / "try"
    shutil.copytree(TESTS.parent / "tools", tk / "tools")
    (tk / "kit.json").write_text(json.dumps({"settings": {**cfg["settings"], "starter_only": True},
                                             "models": [{**cfg["models"][0], "starter": True, "enabled": False}, cfg["models"][1]],
                                             "library": [{**cfg["library"][0], "starter": True}, cfg["library"][1]]}))
    (tk / "site").mkdir()
    (tk / "site" / "sources.json").write_text(json.dumps({"sources": [
        {"id": "Tiny", "bytes": 2 * 10**9}, {"id": "Two", "bytes": 3 * 10**9}, {"id": "testmed_en_all_maxi", "bytes": 4 * 10**9},
        {"id": "testsurvival_en", "bytes": 60 * 10**9}]}))
    rc, out = kit("plan", root=tk)
    rc2, out2 = kit("estimate", root=tk)
    check("plan on a try-it kit: the AI and books marked starter, even one that's switched off, and nothing else",
          rc == 0 and out.count("NEW") == 2 and "Tiny" in out and "testmed_en_all_maxi" in out and "Two" not in out
          and "testsurvival" not in out and rc2 == 0 and out2.strip() == "7", out + out2)
    (tk / "library").mkdir()
    (tk / "library" / "testsurvival_en_2026-02.zim.partial").write_bytes((R / "zim/testsurvival_en_2026-02.zim").read_bytes()[:1000])
    rc, out = kit("sync", "-y", root=tk)
    st = json.loads((tk / ".kit" / "state.json").read_text())
    check("sync on a try-it kit: just those, it counts as a complete one, and another item's unfinished download stays",
          rc == 0 and (tk / "models/Tiny/Tiny-Q4_K_M.gguf").exists() and not (tk / "models/Two").exists()
          and list((tk / "library").glob("testmed_*.zim")) and not list((tk / "library").glob("testsurvival_*.zim"))
          and (tk / "library" / "testsurvival_en_2026-02.zim.partial").exists() and "last_sync" in st, out)
    st["download_speed"] = 10 * 10**6
    (tk / ".kit" / "state.json").write_text(json.dumps(st))
    rc, out = kit("starter", root=tk)
    rc2, out2 = kit("estimate", "--rest", root=tk)
    check("kit starter and estimate --rest: how big the rest is, and how long it takes at the speed measured",
          rc == 0 and "Just the try-it kit" in out and "The rest is about 64 GB more: about 2 hours at this connection's speed "
          "(10.0 MB/s)" in out and "./kit starter off" in out
          and rc2 == 0 and out2 == "64\tabout 2 hours at this connection's speed (10.0 MB/s)\n", out + out2)
    rc, out = kit("starter", "off", root=tk)
    rc2, out2 = kit("plan", root=tk)
    check("kit starter off: everything switched on, and plan says how long it takes",
          rc == 0 and "starter_only" not in (tk / "kit.json").read_text() and "To get just the try-it kit" in out
          and "Two" in out2 and "That takes about a minute at this connection's speed (10.0 MB/s)." in out2, out + out2)
    rc, out = kit("sync", "-y", root=tk)
    st = json.loads((tk / ".kit" / "state.json").read_text())
    check("the full sync after it gets the rest, then removes the sample nobody picked and keeps the book they did",
          rc == 0 and (tk / "models/Two/Two-Q4_K_M.gguf").exists() and not (tk / "models/Tiny").exists()
          and "models/Tiny" not in st["items"] and "Removed Tiny" in out and list((tk / "library").glob("testmed_*.zim"))
          and list((tk / "library").glob("testsurvival_*.zim")) and "library/testmed_en_all_maxi" in st["items"], out)

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
    # A whole book left as an unfinished download, as syncs that took Kiwix's rounded sizes for exact ones left them
    book.rename(book.with_name(book.name + ".partial"))
    st = state()
    del st["items"]["library/testmed_en_all_maxi"]
    st["partials"] = {"library/testmed_en_all_maxi_2026-01.zim.partial": {"item": "library/testmed_en_all_maxi",
                                                                           "tag": f"2026-01|{listed}"}}
    (drive / ".kit" / "state.json").write_text(json.dumps(st))
    rc, out = kit("sync", "-y")
    check("a whole book left as an unfinished download is checked and kept, not downloaded again",
          rc == 0 and "resuming at 70.0 KB" in out and "discarding" not in out
          and same("library/testmed_en_all_maxi_2026-01.zim", "zim/testmed_en_all_maxi_2026-01.zim"), out)

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
    del cfg["settings"]["downloader"]
    write_cfg()
    check("aria2c: a full-length download it hadn't finished is resumed, not taken as done",
          rc == 0 and same("models/Two/Two-Q4_K_M.gguf", "hf/two/Two-Q4_K_M.gguf") and not record.exists(), out)

    def served(name=None):
        """The stretches of a file (or of any) the mock internet sent since the last look, leaving out asking for
        its size."""
        log = R / "served.log"
        lines = log.read_text().splitlines() if log.exists() else []
        log.write_text("")
        return [(int(a), int(b)) if name else (n, int(a), int(b)) for n, a, b in (x.split() for x in lines)
                if name in (None, n) and int(b) - int(a) > 1]

    # Several connections at once, each with its own part of the file. Ctrl-C partway keeps what arrived, and a record
    # of which parts that was; the next sync fetches only the rest.
    model = drive / "models/Tiny/Tiny-Q4_K_M.gguf"
    model.unlink()
    partial = model.with_name(model.name + ".partial")
    record = partial.with_name(partial.name + ".parts")
    served("Tiny-Q4_K_M.gguf")
    (R / "SLOW").touch()
    p = subprocess.Popen([sys.executable, str(drive / "tools" / "kit.py"), "--root", str(drive), "sync", "-y"], env=env,
                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for _ in range(400):
        if record.exists() and partial.exists() and partial.stat().st_size:
            break
        time.sleep(0.05)
    time.sleep(0.5)
    p.send_signal(signal.SIGINT)
    out = p.communicate(timeout=60)[0]
    (R / "SLOW").unlink()
    rec = json.loads(record.read_text()) if record.exists() else {}
    arrived = sum(b - a for a, b in rec.get("done", []))
    left_open = [x for x in subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout.splitlines()
                 if x.startswith("curl") and "Range: bytes" in x and f"127.0.0.1:{port}/" in x]
    sent = served("Tiny-Q4_K_M.gguf")
    check("Ctrl-C partway through a download in parts: what arrived stays, with its record, and no connection is left open",
          p.returncode == 130 and rec.get("size") == 300_000 and 0 < arrived < 300_000 and not left_open and len(sent) > 2,
          out + json.dumps(rec) + str(left_open))
    rc, out = kit("sync", "-y")
    again = served("Tiny-Q4_K_M.gguf")
    check("the next sync fetches only the parts that hadn't arrived",
          rc == 0 and same("models/Tiny/Tiny-Q4_K_M.gguf", "hf/tiny/Tiny-Q4_K_M.gguf") and not record.exists()
          and sum(b - a for a, b in again) >= 300_000 - arrived
          and not any(a < d1 and d0 < b for a, b in again for d0, d1 in rec["done"]), out + str(again))

    # Near the end, a connection with nothing left to fetch takes the second half of what another has left
    (drive / "models/Two/Two-Q4_K_M.gguf").unlink()
    (R / "SLOW").touch()
    rc, out = kit("sync", "-y")
    (R / "SLOW").unlink()
    again = served("Two-Q4_K_M.gguf")
    check("near the end, an idle connection takes half of another's part",
          rc == 0 and same("models/Two/Two-Q4_K_M.gguf", "hf/two/Two-Q4_K_M.gguf")
          and any(a % 16384 for a, b in again if a < 147_456), out + str(again))

    # A download one connection began (one before this kit got parts, or "downloader": "curl") carries on in parts
    model.unlink()
    partial.write_bytes((R / "hf/tiny/Tiny-Q4_K_M.gguf").read_bytes()[:100_000])
    rc, out = kit("sync", "-y")
    again = served("Tiny-Q4_K_M.gguf")
    check("a download one connection began carries on in parts, without fetching its start again",
          rc == 0 and same("models/Tiny/Tiny-Q4_K_M.gguf", "hf/tiny/Tiny-Q4_K_M.gguf") and len(again) > 2
          and min(a for a, b in again) == 100_000 and sum(b - a for a, b in again) >= 200_000, out + str(again))

    # ...and the other way: with "downloader": "curl", a download in parts keeps what arrived from the start, then one
    # connection fetches the rest
    model.unlink()
    data = (R / "hf/tiny/Tiny-Q4_K_M.gguf").read_bytes()
    partial.write_bytes(data[:50_000] + os.urandom(50_000) + data[100_000:150_000])
    record.write_text(json.dumps({"size": 300_000, "done": [[0, 50_000], [100_000, 150_000]]}))
    cfg["settings"]["downloader"] = "curl"
    write_cfg()
    rc, out = kit("sync", "-y")
    del cfg["settings"]["downloader"]
    write_cfg()
    again = served("Tiny-Q4_K_M.gguf")
    check('"downloader": "curl" carries on a download in parts from the end of its first stretch, in one piece',
          rc == 0 and same("models/Tiny/Tiny-Q4_K_M.gguf", "hf/tiny/Tiny-Q4_K_M.gguf") and not record.exists()
          and again == [(50_000, 300_000)], out + str(again))

    # A server that sends only whole files, though it says how big one is: one connection after all
    model.unlink()
    (R / "NO_PARTS").touch()
    rc, out = kit("sync", "-y")
    (R / "NO_PARTS").unlink()
    check("a server that won't send parts of a file: it comes in one piece",
          rc == 0 and same("models/Tiny/Tiny-Q4_K_M.gguf", "hf/tiny/Tiny-Q4_K_M.gguf") and not record.exists()
          and (0, 300_000) in served("Tiny-Q4_K_M.gguf"), out)

    # Which release of a program: llama.cpp's builds are its nightly prereleases, but Photon's newest release
    # here is a beta, and a beta is taken only when there's nothing else.
    rt = work / "runtimes"
    shutil.copytree(TESTS.parent / "tools", rt / "tools")
    programs = [
        {"id": "llama.cpp-linux-x64", "type": "github", "repo": "ggml-org/llama.cpp", "asset": "llama-*-bin-ubuntu-x64.tar.gz"},
        {"id": "photon", "type": "github", "repo": "komoot/photon", "asset": "photon-[0-9]*.jar"},
        {"id": "java-linux-x64", "type": "adoptium", "os": "linux", "arch": "x64"}]
    (rt / "kit.json").write_text(json.dumps({"settings": {"pin_programs": False}, "runtimes": programs}))
    rc, out = kit("plan", root=rt)
    check("plan: llama.cpp's nightly build, and Photon's full release rather than its newer beta",
          rc == 0 and "b99990" in out and "1.3.0" in out and "2.0.0-beta" not in out and "jdk-21.0.9+10" in out, out)

    # A release names each program's build and its checksum (tools/pins.json): sync takes that build rather than
    # a newer one, and refuses a file that changed after it was pinned.
    def pin(**pins):
        (rt / "tools" / "pins.json").write_text(json.dumps({"_readme": ["test"], **pins}))
    llama, photon_old = sha(R / "gh/llama-b99990-bin-ubuntu-x64.tar.gz"), sha(R / "gh2/photon-1.2.1.jar")
    java = sha(R / "adoptium/OpenJDK21U-jre_x64_linux_hotspot_21.0.9_10.tar.gz")
    (rt / "kit.json").write_text(json.dumps({"runtimes": programs}))
    pin(photon={"version": "1.2.1", "sha256": photon_old}, **{"llama.cpp-linux-x64": {"version": "b99990", "sha256": llama},
                                                               "java-linux-x64": {"version": "jdk-21.0.9+10", "sha256": java}})
    rc, out = kit("plan", root=rt)
    check("pins: plan takes the pinned builds, not Photon's newest release", rc == 0 and "b99990" in out
          and "1.2.1" in out and "1.3.0" not in out and "jdk-21.0.9+10" in out and "error" not in out, out)
    pin(photon={"version": "1.2.1", "sha256": "0" * 64})
    rc, out = kit("plan", root=rt)
    check("pins: a file that changed after it was pinned is refused",
          "changed after this version of the kit pinned it" in out and "1.3.0" not in out, out)
    pin(**{"llama.cpp-linux-x64": {"version": "b12345", "sha256": llama}, "java-linux-x64": {"version": "jdk-21.0.1+12"}})
    rc, out = kit("plan", root=rt)
    check("pins: a pinned build its publisher took down says so", "no longer publishes b12345" in out
          and "no longer publishes Java jdk-21.0.1+12 for linux x64" in out, out)
    (rt / "kit.json").write_text(json.dumps({"settings": {"pin_programs": False}, "runtimes": programs}))
    rc, out = kit("plan", root=rt)
    check("pins: \"pin_programs\": false takes the newest builds", rc == 0 and "b99990" in out and "1.3.0" in out, out)
    # Photon opens only address databases made for its own version: when none is published for the pinned one,
    # the kit takes the Photon release that opens the newest database.
    (rt / "kit.json").write_text(json.dumps({"runtimes": programs, "maps": {"enabled": True}}))
    pin(photon={"version": "2.0.0-beta", "sha256": "0" * 64})
    rc, out = kit("plan", root=rt)
    check("pins: a pinned Photon with no address database gives way to the release that opens the newest one",
          re.search(r"photon\s.*1\.3\.0", out) and "2.0.0-beta" not in out and re.search(r"geocoder\s.*1\.3/", out), out)

    # ./kit pins, before a release: the newest builds and their checksums
    (rt / "kit.json").write_text(json.dumps({"runtimes": programs}))
    pin(photon={"version": "1.2.1", "sha256": photon_old})
    rc, out = kit("pins", root=rt)
    pins = json.loads((rt / "tools" / "pins.json").read_text())
    check("./kit pins: the newest build of each program, with its publisher's SHA-256", rc == 0
          and pins.get("llama.cpp-linux-x64") == {"version": "b99990", "sha256": llama}
          and pins.get("photon") == {"version": "1.3.0", "sha256": sha(R / "gh2/photon-1.3.0.jar")}
          and pins.get("java-linux-x64") == {"version": "jdk-21.0.9+10", "sha256": java}
          and "photon: 1.2.1 -> 1.3.0" in out and "llama.cpp-linux-x64: not pinned -> b99990" in out, out)
    pin(photon={"version": "1.3.0", "sha256": "0" * 64})
    rc, out = kit("pins", root=rt)
    check("./kit pins: a file replaced under the same version keeps its old pin, and the run fails", rc != 0
          and json.loads((rt / "tools" / "pins.json").read_text())["photon"]["sha256"] == "0" * 64
          and "replaced a file it had already published" in out, out)

    (drive / ".kit" / "state.json").unlink()
    rc, out = kit("sync", "-y")
    check("lost state: files on the drive are checked and kept, not downloaded again",
          rc == 0 and out.count("found ") == 5 and "downloading" not in out, out)

    # A kit an older version set up. Its state.json has fewer keys; it calls the model Tiny, where kit.json now says
    # Tiny-Mini; and it has a book that's switched off now, which the try-it kit lists. The new version downloads none
    # of it again: the model moves to its new folder, and the book stays.
    old = work / "old" / "TinfoilKit"
    shutil.copytree(TESTS.parent / "tools", old / "tools")
    (old / "models" / "Tiny").mkdir(parents=True)
    (old / "library").mkdir()
    shutil.copy(R / "hf/tiny/Tiny-Q4_K_M.gguf", old / "models" / "Tiny")
    for z in ("testmed_en_all_maxi_2026-01.zim", "testsurvival_en_2026-02.zim"):
        shutil.copy(R / "zim" / z, old / "library")

    def had(version, dest, *names):
        return {"version": version, "dest": dest,
                "files": {n: {"size": (old / dest / n).stat().st_size, "sha256": sha(old / dest / n)} for n in names}}
    (old / ".kit").mkdir()
    (old / ".kit" / "state.json").write_text(json.dumps({"version": 1, "last_sync": "2026-01-01T00:00:00", "items": {
        "models/Tiny": had("1", "models/Tiny", "Tiny-Q4_K_M.gguf"),
        "library/testmed_en_all_maxi": had("2026-01", "library", "testmed_en_all_maxi_2026-01.zim"),
        "library/testsurvival_en": had("2026-02", "library", "testsurvival_en_2026-02.zim")}}))
    (old / "kit.json").write_text(json.dumps({"settings": cfg["settings"], "models": [
        {"id": "Tiny-Mini", "type": "hf", "repo": "test/Tiny-GGUF", "files": ["*-Q4_K_M.gguf"], "priority": 1}],
        "library": [{"zim": "testmed_en_all_maxi", "enabled": False, "starter": True}, {"zim": "testsurvival_en"}]}))
    served()
    rc, out = kit("sync", "-y", root=old)
    sent = served()
    st = json.loads((old / ".kit" / "state.json").read_text())
    check("a kit an older version set up: nothing downloads again, a renamed model moves to its new folder, and a book "
          "that's switched off stays", rc == 0 and not sent and "moved it here from models/Tiny" in out
          and (old / "models/Tiny-Mini/Tiny-Q4_K_M.gguf").exists() and not (old / "models/Tiny").exists()
          and sorted(st["items"]) == ["library/testmed_en_all_maxi", "library/testsurvival_en", "models/Tiny-Mini"]
          and (old / "library/testmed_en_all_maxi_2026-01.zim").exists(), out + str(sent))

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
    # A book with refresh_days keeps the edition it has until that one is so many days old.
    survival = next(z for z in cfg["library"] if z["zim"] == "testsurvival_en")
    survival["refresh_days"] = 30
    write_cfg()
    rc, out = kit("plan")
    line = next((x for x in out.splitlines() if "testsurvival_en" in x), "")
    check("refresh_days: a new edition of a book installed this month waits, and the plan says how to get it now",
          line.split()[:1] == ["later"] and "2026-02   (2026-05 waits until" in line and "./kit sync --only NAME" in out, out)
    rc, out = kit("plan", "--only", "testsurvival")
    check("refresh_days: naming it in --only gets the new edition now", "UPDATE  testsurvival_en" in out, out)
    book = drive / "library/testsurvival_en_2026-02.zim"
    book.rename(book.with_suffix(".gone"))
    rc, out = kit("plan")
    check("refresh_days: a book whose file is missing doesn't wait", "UPDATE  testsurvival_en" in out, out)
    book.with_suffix(".gone").rename(book)
    st = state()
    st["items"]["library/testsurvival_en"]["updated"] = "2025-12-01T09:00:00"
    (drive / ".kit" / "state.json").write_text(json.dumps(st))
    rc, out = kit("plan")
    check("refresh_days: once the edition is that old, the new one downloads", "UPDATE  testsurvival_en" in out, out)
    del survival["refresh_days"]
    write_cfg()
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

    finder = drive / "library/._disabled_one_en_2026-01.zim.partial"    # what macOS writes beside a file on exFAT
    finder.write_bytes(b"\0\5\26\7")
    rc, out = kit("status")
    finder.unlink()
    check("status, including the switched-off book's unfinished download, but not macOS's ._ file beside it",
          rc == 0 and "Last complete sync" in out and "library/disabled_one_en_2026-01.zim.partial" in out
          and "._disabled" not in out, out)

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

    junk = [drive / "library" / "._junk.zim", drive / "models" / "Tiny" / "._Tiny-Q4_K_M.gguf",
            drive / ".git" / "objects" / "pack" / "._pack-1.idx"]
    for j in junk:
        j.parent.mkdir(parents=True, exist_ok=True)
        j.write_bytes(b"\0\5\26\7")   # macOS's metadata files on exFAT start like this
    books = len(list((drive / "library").glob("[!.]*.zim")))
    rc, out = kit("test")
    shutil.rmtree(drive / ".git")
    check("test: clears macOS's ._ files before starting the servers, and from a checkout's .git",
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

    spec = importlib.util.spec_from_file_location("kitpy", TESTS.parent / "tools" / "kit.py")
    kp = sys.modules["kitpy"] = importlib.util.module_from_spec(spec)    # dataclasses look the module up
    spec.loader.exec_module(kp)

    # pins.yml's commit job holds a new tools/pins.json to the committed note and to the programs it knows
    check("tools/pins.json carries kit.py's note",
          json.loads((TESTS.parent / "tools" / "pins.json").read_text())["_readme"] == kp.PINS_README)
    viewer = [m["id"] for m in kp.maps_items({"maps": {"enabled": True}}) if m["type"] in kp.PINNED_TYPES]
    check("pins.yml knows every map viewer program kit.py pins",
          viewer and all(f'"{i}"' in (TESTS.parent / ".github" / "workflows" / "pins.yml").read_text() for i in viewer), viewer)

    def ssh_str(b):
        return len(b).to_bytes(4, "big") + b

    def ssh_sign(seed, data, namespace=b"tinfoilkit-release", claim=None):
        """Sign data the way ssh-keygen -Y sign does, with the Ed25519 key made from seed (RFC 8032), saying it's
        claim's key if given. Returns the signature file and the key's line for tools/release-signers."""
        h = hashlib.sha512(seed).digest()
        a = int.from_bytes(h[:32], "little") & (2**254 - 8) | 2**254

        def enc(pt):
            zi = pow(pt[2], kp.ED_P - 2, kp.ED_P)
            return ((pt[1] * zi % kp.ED_P) | (pt[0] * zi % kp.ED_P & 1) << 255).to_bytes(32, "little")
        pub = enc(kp.ed_mul(a, kp.ED_B))
        msg = b"SSHSIG" + ssh_str(namespace) + ssh_str(b"") + ssh_str(b"sha512") + ssh_str(hashlib.sha512(data).digest())
        r = int.from_bytes(hashlib.sha512(h[32:] + msg).digest(), "little") % kp.ED_L
        big_r = enc(kp.ed_mul(r, kp.ED_B))
        sig = big_r + ((r + int.from_bytes(hashlib.sha512(big_r + pub + msg).digest(), "little") * a) % kp.ED_L).to_bytes(32, "little")
        key = ssh_str(b"ssh-ed25519") + ssh_str(pub)
        blob = (b"SSHSIG\0\0\0\1" + ssh_str(ssh_str(b"ssh-ed25519") + ssh_str(claim or pub)) + ssh_str(namespace) + ssh_str(b"") + ssh_str(b"sha512")
                + ssh_str(ssh_str(b"ssh-ed25519") + ssh_str(sig)))
        b64 = base64.b64encode(blob).decode()
        armored = "\n".join(["-----BEGIN SSH SIGNATURE-----", *(b64[i:i + 70] for i in range(0, len(b64), 70)),
                             "-----END SSH SIGNATURE-----", ""])
        return armored.encode(), f'tinfoilkit-release namespaces="tinfoilkit-release" ssh-ed25519 {base64.b64encode(key).decode()} test\n'

    # The signature check against RFC 8032's test vectors, and the ways a signature can be wrong.
    for pub, msg, sig in (("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
                           "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
                          ("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
                           "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00")):
        pub, msg, sig = bytes.fromhex(pub), bytes.fromhex(msg), bytes.fromhex(sig)
        flipped = bytes([sig[0] ^ 1]) + sig[1:]
        plus_l = sig[:32] + (int.from_bytes(sig[32:], "little") + kp.ED_L).to_bytes(32, "little")
        check(f"Ed25519: RFC 8032's signature of {len(msg)} byte(s) checks out; another message, a changed byte or S + L doesn't",
              kp.ed25519_ok(pub, msg, sig) and not kp.ed25519_ok(pub, msg + b"x", sig)
              and not kp.ed25519_ok(pub, msg, flipped) and not kp.ed25519_ok(pub, msg, plus_l))
    signed = work / "signed"
    (signed / "tools").mkdir(parents=True)
    sig_file, signer = ssh_sign(b"k" * 32, b"release")
    (signed / "tools" / "release-signers").write_text("# comment\n" + signer)

    def verified(data, sig):
        try:
            kp.verify_release(signed, data, sig)
            return "ok"
        except ValueError as e:
            return str(e)
    other_sig, _ = ssh_sign(b"o" * 32, b"release")
    forged, _ = ssh_sign(b"o" * 32, b"release", claim=kp.release_keys(signed / "tools" / "release-signers")[0])
    check("release signature: the kit's key checks out", verified(b"release", sig_file) == "ok", verified(b"release", sig_file))
    check("release signature: another file, key, namespace or a damaged signature is refused, and so is another key "
          "claiming to be the kit's",
          "isn't signed with the kit's release key" in verified(b"release!", sig_file)
          and "isn't signed with the kit's release key" in verified(b"release", other_sig)
          and "isn't signed with the kit's release key" in verified(b"release", forged)
          and "isn't signed with the kit's release key" in verified(b"release", ssh_sign(b"k" * 32, b"release", b"file")[0])
          and "damaged" in verified(b"release", sig_file[:-60]) and "damaged" in verified(b"release", b""))
    if shutil.which("ssh-keygen"):    # the signatures agree with OpenSSH's
        (signed / "release").write_bytes(b"release")
        (signed / "release.sig").write_bytes(sig_file)
        p = subprocess.run(["ssh-keygen", "-Y", "verify", "-f", str(signed / "tools" / "release-signers"), "-I", "tinfoilkit-release",
                            "-n", "tinfoilkit-release", "-s", str(signed / "release.sig")], input=b"release", capture_output=True)
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(signed / "key")], stdin=subprocess.DEVNULL, check=True)
        (signed / "release.sig").unlink()
        subprocess.run(["ssh-keygen", "-q", "-Y", "sign", "-f", str(signed / "key"), "-n", "tinfoilkit-release", str(signed / "release")],
                       stdin=subprocess.DEVNULL, capture_output=True, check=True)
        (signed / "tools" / "release-signers").write_text(f'tinfoilkit-release ssh-ed25519 {(signed / "key.pub").read_text().split()[1]}\n')
        check("release signature: ssh-keygen accepts the kit's signatures and the kit accepts ssh-keygen's",
              p.returncode == 0 and verified(b"release", (signed / "release.sig").read_bytes()) == "ok",
              p.stderr.decode() + verified(b"release", (signed / "release.sig").read_bytes()))
    elif os.environ.get("CI"):
        check("release signature: ssh-keygen is here to cross-check the signatures", False)
    else:
        print("skipped: checking signatures against OpenSSH (no ssh-keygen here)")

    # ./kit update: a kit on the drive, its kit.json changed by its owner, and releases of the kit's code
    # published on the mock GitHub. site/kit.json is the copy of kit.json the kit's current version came with.
    up = work / "update" / "TinfoilKit"
    code = {rel: (TESTS.parent / rel).read_bytes() for rel in ("kit", "SETUP.command", "Open Tinfoil Kit.command", "UNINSTALL.command")}
    code.update({p.relative_to(TESTS.parent).as_posix(): p.read_bytes() for p in (TESTS.parent / "tools").rglob("*")
                 if p.is_file() and "__pycache__" not in p.parts})
    code["tools/release-signers"] = signer.encode()    # this kit's key, and the one each test release brings
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

    def publish(tag, files, links=(), body="", seed=b"k" * 32, signed=True, changed=False):
        """A release on the mock GitHub as .github/release.sh makes one: everything under one top folder, and its
        signature beside it. changed: the archive is swapped for another after it was signed."""
        (R / "gh").mkdir(exist_ok=True)
        name = f"kit-{tag}-{len(list((R / 'gh').glob('kit-*.gz')))}.tar.gz"

        def pack(files):
            with tarfile.open(R / "gh" / name, "w:gz") as tf:
                for rel, data in files.items():
                    info = tarfile.TarInfo(f"tinfoilkit-{tag}/{rel}")
                    info.size, info.mode = len(data), 0o755 if rel in ("kit", "SETUP.command") or rel.endswith(".sh") else 0o644
                    tf.addfile(info, io.BytesIO(data))
                for rel, target in links:
                    info = tarfile.TarInfo(f"tinfoilkit-{tag}/{rel}")
                    info.type, info.linkname = tarfile.SYMTYPE, target
                    tf.addfile(info)
        pack(files)
        (R / "gh" / f"{name}.sig").write_bytes(ssh_sign(seed, (R / "gh" / name).read_bytes())[0])
        if changed:
            pack({**files, "tools/extra.txt": b"added after signing"})
        assets = [{"name": f"tinfoilkit-{tag}.tar.gz", "browser_download_url": f"{base}/gh/{name}"}]
        if signed:
            assets.append({"name": f"tinfoilkit-{tag}.tar.gz.sig", "browser_download_url": f"{base}/gh/{name}.sig"})
        (R / "kit").mkdir(exist_ok=True)    # GitHub's own source archive is listed too, and must never be used
        (R / "kit" / "release.json").write_text(json.dumps({"tag_name": tag, "assets": assets, "body": body,
                                                            "tarball_url": f"{base}/gh/{name}"}))

    def kit_tty(answer, *args):
        """./kit at a keyboard, where someone types answer."""
        import pty
        keyboard, tty = pty.openpty()
        os.write(keyboard, answer.encode())
        try:
            p = subprocess.run([sys.executable, str(up / "tools" / "kit.py"), "--root", str(up), *args], env=env, stdin=tty,
                               capture_output=True, text=True, timeout=180)
        finally:
            os.close(keyboard)
            os.close(tty)
        return p.returncode, p.stdout + p.stderr

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
           "a kit.py this Python can't run": (dict(files={**good, "tools/kit.py": b"def broken(:\n"}), "won't run"),
           "no signature": (dict(files=good, signed=False), "isn't signed (the release has no tinfoilkit-v2.tar.gz"),
           "another key's signature": (dict(files=good, seed=b"o" * 32), "isn't signed with the kit's release key"),
           "an archive swapped after it was signed": (dict(files=good, changed=True), "isn't signed with the kit's release key"),
           "no key to check the next one": (dict(files={**good, "tools/release-signers": b"# none\n"}),
                                            "no release key (tools/release-signers)")}
    for what, (release, why) in bad.items():
        publish("v2", **release)
        rc, out = kit("update", root=up)
        check(f"kit update: a release with {what} is refused and nothing changes",
              rc == 1 and "couldn't install version v2" in out and why in out and not (up / "docs").exists()
              and not (work / "escaped.txt").exists() and (up / "kit.json").read_text() == mine_text, out)
    (up / "tools/release-signers").write_text("# none\n")
    publish("v2", good)
    rc, out = kit("update", root=up)
    check("kit update: a copy with no release key refuses every release", rc == 1 and "no release key to check it with" in out
          and not (up / "docs").exists(), out)
    (up / "tools/release-signers").write_text(signer)
    publish("v2", good, body="Faster answers.\nBetter maps.")
    (up / "kit.json").write_text(mine_text.replace('"Two"', '"Two",', 1))
    rc, out = kit("update", root=up)
    check("kit update: a typo in kit.json stops it before anything changes", rc == 1 and "syntax error on line" in out
          and not (up / "docs").exists(), out)
    (up / "kit.json").write_text(mine_text)
    rc, out = kit_tty("n\n", "update")
    check("kit update: at a keyboard it shows what's new and asks first, and no keeps this version",
          rc == 0 and "Better maps." in out and "Install it now?" in out and "This version stays" in out
          and not (up / "docs").exists() and (up / "kit.json").read_text() == mine_text, out)
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
    rc, out = kit_tty("n\n", "update", "--yes")
    merged = json.loads((up / "kit.json").read_text())
    check("kit update: --yes doesn't ask, and the next release removes files the last one installed and still keeps the choices",
          rc == 3 and "Install it now?" not in out and not (up / "docs/v2.txt").exists() and (up / "docs/v3.txt").exists()
          and merged["settings"] == {"default_model": "Two", "context_size": 32768} and merged["library"][-1] == {"zim": "mine_en"}, out)
    (up / "kit.json").write_text((up / "site/kit.json").read_text())
    rc, out = kit("update", "--force", root=up)
    check("kit update: a kit.json nobody changed becomes the release's, byte for byte",
          rc == 3 and (up / "kit.json").read_bytes() == json.dumps(v3_cfg, indent=4).encode(), out)
    (up / ".git").mkdir()
    rc, out = kit("update", root=up)
    check("kit update: leaves a git checkout to git", rc == 0 and "git pull" in out, out)

    # SETUP.command's choices, with a stand-in ./kit that exits as told. Its update rewrites SETUP.command in
    # place, the hard case for bash, which reads a script as it goes. Its space says what SPACE does (all of it, the
    # essentials, GB free, GB in all, GB all of it needs, GB the essentials need, GB worth leaving free), or for a
    # drive what SPACE_DRIVE does, and its estimate says 8 GB, or with --rest 380 GB in about 4 hours. Calls go in
    # calls.log (essentials on as essentials-on, starter off as starter-off), all but space and estimate, and every
    # call goes in args.log with its options.
    def space(*v):
        return "\t".join(map(str, v))
    roomy = space("fits", "fits", 900, 1000, 400, 100, 50)
    stand_in = """#!/bin/bash
case "$1" in drives|kits|place|region|pick) exec python3 "@KIT_PY@" --root "$(pwd)" "$@";; esac    # the real ones
echo "$*" >> args.log
c="$1"; case " $* " in *" --essentials "*) c="$1-essentials";; esac
case "$1" in essentials|starter) c="$1-$2";; esac
case "$1" in space|estimate) ;; *) echo "kit $c" >> calls.log;; esac
case "$1" in
  space) case "$2" in "${KIT_DRIVES:-/nowhere}"/*) echo "${SPACE_DRIVE:-$SPACE}";; *) echo "$SPACE";; esac;;
  estimate) case " $* " in *" --rest "*) printf '%s\t%s\n' 380 "about 4 hours at this connection's speed (24.0 MB/s)";;
                                     *) echo 8;; esac;;
  essentials|starter) python3 - "$1" "$2" <<'PY'
import json, sys
c = json.load(open("kit.json"))
c.setdefault("settings", {})[sys.argv[1] + "_only"] = True if sys.argv[2] == "on" else None
c["settings"] = {k: v for k, v in c["settings"].items() if v is not None}
json.dump(c, open("kit.json", "w"), indent=1)
PY
              ;;
  update) [ "$UPDATE" = 3 ] && sed 's/Step [$]KIT_STEP of/Step $KIT_STEP (new version) of/' SETUP.command > new && cat new > SETUP.command
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
        shutil.copy(TESTS.parent / "kit.json", path)     # ./kit region changes it
        (path / "site").mkdir()
        shutil.copy(TESTS.parent / "site" / "sources.json", path / "site")    # for ./kit pick --ask
        if git:    # a developer's, with npm's packages and a website build in it
            (path / ".git").mkdir()
            for d in ("node_modules/prettier", "site/node_modules/next", "site/.next"):
                (path / d).mkdir(parents=True)
                (path / d / "index.js").write_text("")
        return path

    setup = kit_folder(work / "setup")
    (setup / ".kit").mkdir()     # set up before, so SETUP doesn't ask where it goes

    def run_setup(plan=0, sync=0, test=0, update=0, folder=setup, answers="\ny\nn\n\n", args=(), **env_extra):
        shutil.copy(TESTS.parent / "SETUP.command", folder)
        for log in ("calls.log", "home.log", "args.log"):
            (folder / log).write_text("")
        p = subprocess.run(["bash", str(folder / "SETUP.command"), *args], input=answers, capture_output=True, text=True, timeout=60,
                           env={**os.environ, "PLAN": str(plan), "SYNC": str(sync), "TEST": str(test), "UPDATE": str(update),
                                "SPACE": roomy, **env_extra})
        return p.returncode, p.stdout, (folder / "calls.log").read_text().split()[1::2]

    first = ["update", "fit", "starter-on", "plan", "sync", "test"]    # the try-it kit
    rest = ["starter-off", "essentials-off", "plan", "sync", "test"]    # the rest of the kit
    asked = ("[Y/n]", "[y/N]", "Type a number", "Press Return")
    rc, out, calls = run_setup()
    check("SETUP the first time: the try-it kit, checked, then how big the rest is, how long it takes, and how to get it",
          rc == 0 and calls == first and '"starter_only": true' in (setup / "kit.json").read_text()
          and "Step 1 of 2: the kit is on" in out and "Step 2 of 2: a small kit to try first (about 8 GB)" in out
          and "The try-it kit works" in out and "Turn off Wi-Fi and try it" in out
          and "The rest of the kit is about 380 GB more: about 4 hours at this connection's speed (24.0 MB/s)" in out
          and "run bash SETUP.command again: it asks what you want in the kit, then gets that" in out
          and "Open the kit now?" in out and "All set" not in out and "where should the kit go" not in out, out)
    (setup / ".kit" / "state.json").write_text('{"items": {}, "last_sync": "2026-01-01T00:00:00"}')
    rc, out, calls = run_setup(answers="\n\ny\nn\n\n", KIT_MEMORY_MB="32768")
    c = json.loads((setup / "kit.json").read_text())
    check("SETUP again on the try-it kit: asks the kit builder's questions, shows what it gets, and gets the rest",
          rc == 0 and calls == ["update", "fit"] + rest and "Step 2 of 3: the rest of the kit" in out
          and "What goes in the kit?" in out and "Here's what it gets:" in out and "Start downloading?" in out
          and "Step 3 of 3: start everything offline" in out and "All set" in out
          and "starter_only" not in c["settings"] and c["settings"].get("picked") is True, out)
    update_calls = ["update", "fit", "plan", "sync", "test"]
    rc, out, calls = run_setup()
    check("SETUP after that: says it's an update, and how to update next time",
          rc == 0 and "TINFOIL KIT UPDATE" in out and "TINFOIL KIT SETUP" not in out and "Step 3 of 3: start everything" in out
          and "whenever you want the newest AI models" in out and calls == update_calls, out)

    # A new download of SETUP, where a kit was set up before: it updates that one, without asking anything else first
    kits_home = work / "kits home"
    before = kit_folder(kits_home / "TinfoilKit")
    (before / ".kit").mkdir()
    (before / ".kit" / "state.json").write_text(json.dumps({"last_sync": "2026-11-01T10:00:00", "items": {
        "library/big": {"dest": "library", "files": {"big.zim": {"size": 5 * 10**9}}}}}))
    new = kit_folder(work / "kits download" / "TinfoilKit")
    p = subprocess.run(["bash", str(new / "SETUP.command")], input="\n\ny\nn\n\n", capture_output=True, text=True, timeout=60,
                       env={**os.environ, "HOME": str(kits_home), "KIT_DRIVES": str(work / "no drives"), "SPACE": roomy,
                            "PLAN": "0", "SYNC": "0", "TEST": "0", "UPDATE": "0"})
    calls = (before / "calls.log").read_text().split()[1::2] if (before / "calls.log").exists() else []
    check("SETUP from a new download, with a kit set up before: it updates that kit, so nothing it has downloads again",
          p.returncode == 0 and f"There's a Tinfoil Kit on this computer already: {before} (5 GB, last updated 2026-11-01)."
          in p.stdout and "TINFOIL KIT UPDATE" in p.stdout and "where should the kit go" not in p.stdout
          and calls == update_calls and not (new / "calls.log").is_file(), p.stdout + p.stderr)

    def try_kit(**settings):
        c = json.loads((TESTS.parent / "kit.json").read_text())
        c["settings"].update(starter_only=True, **settings)
        (setup / "kit.json").write_text(json.dumps(c, indent=1))
    try_kit(picked=True)
    rc, out, calls = run_setup(answers="\nn\n\n")
    check("SETUP again on a try-it kit, picked before: doesn't ask again, and a no to downloading keeps the try-it kit",
          rc == 0 and "What goes in the kit?" not in out and "AI models:" in out
          and calls == ["update", "fit", "starter-off", "essentials-off", "plan", "starter-on"]
          and '"starter_only": true' in (setup / "kit.json").read_text(), out)
    rc, out, calls = run_setup(answers="\n2\n\n", SPACE=space("no", "fits", 300, 1000, 400, 100, 100))
    check("SETUP again on a try-it kit that all of it won't fit: offers the essentials or not now, and not now keeps it",
          rc == 1 and "1  Just the essentials" in out and "2  Not now" in out and "Somewhere else" not in out
          and "The try-it kit keeps working" in out and calls == ["update", "fit"]
          and '"starter_only": true' in (setup / "kit.json").read_text(), out)
    rc, out, calls = run_setup(answers="\n1\ny\nn\n\n", SPACE=space("no", "fits", 300, 1000, 400, 100, 100))
    check("SETUP again on a try-it kit that all of it won't fit: the essentials, when chosen",
          rc == 0 and calls == ["update", "fit", "starter-off", "essentials-on", "plan", "sync", "test"]
          and '"essentials_only": true' in (setup / "kit.json").read_text(), out)
    try_kit()
    rc, out, calls = run_setup(args=("--yes",), answers="")
    argv = (setup / "args.log").read_text().splitlines()
    check("SETUP --yes on a try-it kit: gets the rest, asking nothing",
          rc == 0 and calls == ["update", "fit"] + rest and "fit --restore --skip" in argv and "pick --ask" not in argv
          and not any(a in out for a in asked) and "All set" in out, out)

    def essentials_only():
        c = json.loads((TESTS.parent / "kit.json").read_text())
        c["settings"]["essentials_only"] = True
        (setup / "kit.json").write_text(json.dumps(c, indent=1))
    essentials_only()
    rc, out, calls = run_setup(answers="\ny\ny\nn\n\n")
    check("SETUP: an update of just the essentials, now that the rest fits: offers it, and a yes gets it",
          rc == 0 and "now there's room for the rest (about 400 GB more)" in out
          and calls == ["update", "fit", "essentials-off", "plan", "sync", "test"], out)
    essentials_only()
    rc, out, calls = run_setup(answers="\n\ny\nn\n\n")
    check("SETUP: an update of just the essentials: just Return keeps it that way",
          rc == 0 and "room for the rest" in out and calls == update_calls and "essentials_only" in (setup / "kit.json").read_text(), out)
    rc, out, calls = run_setup(args=("--yes",), answers="")
    check("SETUP --yes: an update of just the essentials, now that the rest fits: says how to get it, asks nothing",
          rc == 0 and "SETUP --all gets it" in out and calls == update_calls and not any(a in out for a in asked)
          and "update --yes" in (setup / "args.log").read_text().splitlines(), out)
    rc, out, calls = run_setup(args=("--all", "--yes"), answers="")
    check("SETUP --all: an update of just the essentials gets the rest",
          rc == 0 and calls == ["update", "fit", "essentials-off", "plan", "sync", "test"], out)
    rc, out, calls = run_setup(args=("--essentials", "--yes"), answers="")
    check("SETUP --essentials: an update of all of it gets just the essentials from now on",
          rc == 0 and calls == ["update", "fit", "essentials-on", "plan", "sync", "test"]
          and "essentials_only" in (setup / "kit.json").read_text(), out)
    rc, out, calls = run_setup(SPACE=space("no", "fits", 300, 1000, 400, 100, 50))
    check("SETUP: an update of just the essentials, and the rest still doesn't fit: doesn't offer it",
          rc == 0 and "room for the rest" not in out and calls == update_calls, out)
    shutil.copy(TESTS.parent / "kit.json", setup)
    (setup / ".kit" / "state.json").unlink()
    rc, out, calls = run_setup(update=3)
    check("SETUP: after updating the kit it starts over on the new SETUP, once",
          rc == 0 and "Step 2 (new version) of 2: a small kit to try first" in out and out.count("TINFOIL KIT SETUP") == 1
          and out.count("Maps are for") == 1 and calls == first, out)
    rc, out, calls = run_setup(update=1)
    check("SETUP: the kit's own update failed: carries on", rc == 0 and "The try-it kit works" in out and calls == first, out)
    rc, out, calls = run_setup(sync=1)
    check("SETUP: some downloads failed but the kit works: says so and lists them",
          rc == 1 and "didn't finish" in out and "models/Big: download failed" in out and "try-it kit works" not in out, out)
    rc, out, calls = run_setup(sync=1, test=1)
    check("SETUP: checks failed: stops after the try-it kit", rc == 1 and "Some checks failed" in out and "models/Big" in out
          and calls == first, out)
    rc, out, calls = run_setup(sync=130)
    check("SETUP: Ctrl-C during the download", rc == 130 and "Stopped" in out and calls == first[:5], out)
    rc, out, calls = run_setup(plan=1)
    check("SETUP: offline: stops before asking to download", rc == 1 and calls == first[:4] and "Start downloading" not in out, out)
    home = ["share on", "autostart on", "share"]
    check("SETUP: a normal setup doesn't share the kit or start it with the computer", (setup / "home.log").read_text() == "")
    rc, out, calls = run_setup(args=("--home-server",), answers="\ny\n\n")
    check("SETUP --home-server: the try-it kit and right after it the rest, then shares the kit, starts it with the "
          "computer, shows the address, and doesn't open it",
          rc == 0 and calls == first + rest + ["share", "autostart", "share"] and (setup / "home.log").read_text().splitlines() == home
          and "Step 3 of 3: the rest of the kit" in out and "Home server" in out and "Open the kit now" not in out
          and "double-click Open Tinfoil Kit" not in out, out)
    rc, out, calls = run_setup(update=3, args=("--home-server",), answers="\ny\n\n")
    check("SETUP --home-server: still a home server after the kit updates itself and starts over",
          rc == 0 and "(new version)" in out and (setup / "home.log").read_text().splitlines() == home, out)
    rc, out, calls = run_setup(sync=1, args=("--home-server",), answers="\ny\n\n")
    check("SETUP --home-server: some downloads failed but the kit works: shares it anyway",
          rc == 1 and "didn't finish" in out and (setup / "home.log").read_text().splitlines() == home, out)
    rc, out, calls = run_setup(test=1, args=("--home-server",), answers="\ny\n\n")
    check("SETUP --home-server: checks failed: doesn't share it", rc == 1 and (setup / "home.log").read_text() == "", out)
    rc, out, calls = run_setup(answers="Bavaria\n1\ny\nn\n\n")
    c = json.loads((setup / "kit.json").read_text())
    check("SETUP: says where the maps are for, and changes the place and Wikipedia's language when told",
          rc == 0 and "Maps are for US Northeast" in out and "Maps: Germany: Bayern" in out and c["maps"]["region"] == "bayern"
          and [z["zim"][:17] for z in c["library"] if z["zim"].startswith("wikipedia_")] == ["wikipedia_de_all_"], out)
    shutil.copy(TESTS.parent / "kit.json", setup)
    rc, out, calls = run_setup(args=("--yes",), answers="")
    argv = (setup / "args.log").read_text().splitlines()
    check("SETUP --yes the first time: asks nothing, gets the try-it kit, says how to open it and get the rest, and closes",
          rc == 0 and calls == first and "update --yes" in argv and "fit --restore --skip" in argv
          and not any(a in out for a in asked) and "Start downloading" not in out and "Open the kit now" not in out
          and f'When you\'re ready for it: bash "{setup}/SETUP.command" --yes' in out
          and f'To open it: bash "{setup}/Open Tinfoil Kit.command"' in out, out)
    rc, out, calls = run_setup(args=("--region", "texas", "--wikipedia", "es", "--skip", "maps", "--add", "gutenberg_en_all",
                                     "--share", "--yes"), answers="")
    c = json.loads((setup / "kit.json").read_text())
    check("SETUP --region, --wikipedia, --skip, --add and --share: kit.json changes, and the kit is shared",
          rc == 0 and c["maps"]["region"] == "us/texas" and c["maps"]["enabled"] is False
          and [z["zim"][:17] for z in c["library"] if z["zim"].startswith("wikipedia_")] == ["wikipedia_es_all_"]
          and {k: v for k, v in c["library"][-1].items() if k in ("enabled", "essential")} == {"essential": True}
          and (setup / "home.log").read_text().splitlines() == ["share on", "share"] and "Sharing:" in out
          and "Open the kit now" not in out and "it gets it" not in out, out)
    shutil.copy(TESTS.parent / "kit.json", setup)
    rc, out, calls = run_setup(args=("--no-ai", "--yes"), answers="")
    argv = (setup / "args.log").read_text().splitlines()
    check("SETUP --no-ai: every AI model off, and fit doesn't put one back",
          rc == 0 and all(m.get("enabled") is False for m in json.loads((setup / "kit.json").read_text())["models"])
          and "fit" in argv and "fit --restore --skip" not in argv, out)
    shutil.copy(TESTS.parent / "kit.json", setup)
    rc, out, calls = run_setup(args=("--yes", "--skip", "wikipedia,nothing-such"), answers="")
    check("SETUP --skip with a name the kit doesn't have: stops before downloading, and kit.json is as it was",
          rc == 1 and "Nothing in the kit is called nothing-such" in out and calls == ["update"]
          and (setup / "kit.json").read_text() == (TESTS.parent / "kit.json").read_text(), out)
    rc, out, calls = run_setup(args=("--bogus",), answers="")
    rc2, out2, calls2 = run_setup(args=("--drive",), answers="")
    rc3, out3, _ = run_setup(args=("--help",), answers="")
    check("SETUP: an option it doesn't have, or one without its value, stops it at once; --help lists them",
          rc == 2 and rc2 == 2 and calls == calls2 == [] and rc3 == 0 and "--yes" in out3 and "--drive PATH" in out3, out + out3)

    # A Mac without Python: SETUP gets the kit's own (a stand-in archive here), checked against its SHA-256.
    mac = work / "mac"
    for d, xcode in (("bin", 2), ("dev", 0)):    # dev: a Mac with Apple's developer tools
        (mac / d).mkdir(parents=True)
        for name, body in {"uname": 'case "$1" in -m) echo arm64;; *) echo Darwin;; esac',
                           "xcode-select": f"exit {xcode}", "open": "exit 0"}.items():
            (mac / d / name).write_text(f"#!/bin/sh\n{body}\n")
            (mac / d / name).chmod(0o755)
    (mac / "src" / "python" / "bin").mkdir(parents=True)
    (mac / "src" / "python" / "bin" / "python3").write_text('#!/bin/sh\necho "own python $*"\n')
    (mac / "src" / "python" / "bin" / "python3").chmod(0o755)
    tgz = mac / "python.tar.gz"
    with tarfile.open(tgz, "w:gz") as t:
        t.add(mac / "src" / "python", arcname="python")
    sha = hashlib.sha256(tgz.read_bytes()).hexdigest()
    py_home = mac / "home" / "Library" / "Application Support" / "TinfoilKit"
    on_mac = {"PATH": f"{mac / 'bin'}:{os.environ['PATH']}", "HOME": str(mac / "home"), "KIT_OWN_PYTHON": "1",
              "KIT_MAC_PYTHON_URL": tgz.as_uri(), "KIT_MAC_PYTHON_SHA256": sha}
    rc, out, calls = run_setup(plan=1, answers="", **on_mac)
    check("SETUP on a Mac without Python: gets the kit's own, checks it, and carries on",
          rc == 1 and "First, the kit gets the Python" in out and "this Mac" in out and calls == first[:4]
          and (py_home / "python" / "bin" / "python3").exists() and (py_home / "python" / ".kit-sha256").read_text().strip() == sha
          and not (py_home / "python.partial").exists() and not (py_home / "python.tar.gz").exists(), out)
    rc, out, calls = run_setup(plan=1, answers="", **on_mac)
    check("SETUP on a Mac: the kit's Python is there: no download", calls == first[:4] and "Python" not in out, out)
    (py_home / "python" / ".kit-sha256").write_text("an older build\n")
    rc, out, calls = run_setup(plan=1, answers="", **{**on_mac, "KIT_MAC_PYTHON_URL": (mac / "nothing.tar.gz").as_uri()})
    check("SETUP on a Mac: a newer Python that can't be had: keeps the one it has",
          calls == first[:4] and "Couldn't download it" in out and "keeps using the Python it has" in out
          and (py_home / "python" / "bin" / "python3").exists(), out)
    rc, out, calls = run_setup(plan=1, answers="", **on_mac)
    check("SETUP on a Mac: a newer Python: replaces the old one",
          calls == first[:4] and "a newer Python" in out and (py_home / "python" / ".kit-sha256").read_text().strip() == sha, out)
    shutil.rmtree(py_home)
    rc, out, calls = run_setup(plan=1, answers="", **{**on_mac, "KIT_MAC_PYTHON_SHA256": "0" * 64})
    check("SETUP on a Mac: a download that doesn't match its checksum isn't used, and SETUP stops",
          rc == 1 and "checksum doesn't match" in out and calls == [] and not (py_home / "python").exists(), out)
    real_kit = TESTS.parent / "kit"
    shutil.copytree(mac / "src" / "python", py_home / "python")
    p = subprocess.run([str(real_kit), "--help"], capture_output=True, text=True, env={**os.environ, "HOME": str(mac / "home")})
    check("./kit runs on the kit's own Python when SETUP got one",
          p.stdout.strip() == f"own python {TESTS.parent / 'tools' / 'kit.py'} --root {TESTS.parent} --help", p.stdout + p.stderr)
    shutil.rmtree(py_home)
    if shutil.which("python3", path="/usr/bin:/bin") == "/usr/bin/python3":
        p = subprocess.run([str(real_kit), "--help"], capture_output=True, text=True,
                           env={**os.environ, "HOME": str(mac / "home"), "PATH": f"{mac / 'bin'}:/usr/bin:/bin"})
        check("./kit on a Mac without Apple's developer tools or the kit's Python: says to double-click SETUP",
              p.returncode == 1 and "Double-click SETUP.command" in p.stdout, p.stdout + p.stderr)
        p = subprocess.run([str(real_kit), "--help"], capture_output=True, text=True,
                           env={**os.environ, "HOME": str(mac / "home"), "PATH": f"{mac / 'dev'}:/usr/bin:/bin"})
        check("./kit on a Mac with Apple's developer tools: runs on its python3", p.returncode == 0 and "usage" in p.stdout,
              p.stdout + p.stderr)
    else:
        print("skip  ./kit on a Mac's /usr/bin/python3 (no /usr/bin/python3 here)")

    # The first run asks where the kit goes, moves it there, and the copy there does the rest. Drives are folders
    # in a stand-in for /Volumes; /dev/shm, a different disk, stands in for a drive the kit has to be copied to.
    def first_run(answers, drives=(), git=False, home_kit=None, where="\n", args=(), **env_extra):
        """SETUP's first run. ./kit space says what SPACE (this computer) and SPACE_DRIVE (drives) say. where: the
        answers to "Where do you live?" (Return keeps the kit's place)."""
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
        p = subprocess.run(["bash", str(dl / "SETUP.command"), *args], input=where + answers, capture_output=True, text=True,
                           timeout=60,
                           env={**os.environ, "HOME": str(home), "KIT_DRIVES": str(env_extra.pop("KIT_DRIVES", vols)),
                                "SPACE": roomy, "PLAN": "0", "SYNC": "0", "TEST": "0", "UPDATE": "0", **env_extra})
        return p.returncode, p.stdout + p.stderr, dl, home, vols    # ./kit place says what it did on stderr

    def placed_ok(where, essentials=False, then_rest=False):
        """Set up at where: the try-it kit, and right after it the rest if told, with just the essentials or all."""
        log = where / "calls.log"
        tail = first[:1] + first[2:]    # (fit was before the kit moved)
        if then_rest:
            tail += ["starter-off", "essentials-on" if essentials else "essentials-off"] + rest[2:]
        return ((where / "SETUP.command").exists() and (where / "kit").exists() and (where / "tools/kit.py").exists()
                and (where / ".kit").is_dir() and log.exists() and log.read_text().split()[1::2][-len(tail):] == tail
                and ('"essentials_only": true' in (where / "kit.json").read_text()) == essentials)

    rc, out, dl, home, vols = first_run("2\ny\nn\n\n")
    check("SETUP first run: this computer: says what fits, moves the kit to TinfoilKit in the home folder, sets up there",
          rc == 0 and "Step 2 of 3: where should the kit go?" in out and "All of the kit is about 400 GB" in out
          and "Just the essentials (the AI" in out and "Its disk has 900 GB free of 1.0 TB: room for all of it" in out
          and placed_ok(home / "TinfoilKit") and not dl.exists() and "Moved the kit to this computer" in out
          and out.count("TINFOIL KIT SETUP") == 1 and "Step 3 of 3: a small kit to try first" in out
          and "The try-it kit works" in out
          and (home / "TinfoilKit" / "calls.log").read_text().split()[1::2][:2] == ["fit", "essentials-off"], out)
    rc, out, _, _, _ = first_run("1\n1\ny\nn\n\n", drives=["SAMSUNG T7"])
    check("SETUP first run: a drive: lists it with what fits, the kit moves to TinfoilKit at its top and sets up there",
          rc == 0 and "1  SAMSUNG T7 (" in out and "900 GB free of 1.0 TB): room for all of it" in out and "Look again" in out
          and placed_ok(vols / "SAMSUNG T7" / "TinfoilKit") and "Moved the kit to the drive SAMSUNG T7" in out
          and "The try-it kit works" in out, out)
    rc, out, _, home, _ = first_run("1\n2\ny\nn\n\n")
    check("SETUP first run: no drive plugged in: says so, and offers this computer instead",
          rc == 0 and "No external drive is plugged in" in out and placed_ok(home / "TinfoilKit"), out)
    small = space("no", "fits", 300, 1000, 400, 100, 100)
    rc, out, _, home, _ = first_run("2\n1\ny\nn\n\n", SPACE=small)
    check("SETUP first run: all of it won't fit on this computer: offers just the essentials, and gets only those",
          rc == 0 and "room for the essentials, not all of it" in out and "it needs about 400 GB plus some to spare, and 300 GB is free" in out
          and placed_ok(home / "TinfoilKit", essentials=True) and "The rest of the essentials is about 380 GB more" in out, out)
    rc, out, _, home, _ = first_run("2\n2\n2\n1\ny\nn\n\n", SPACE=small)
    check("SETUP first run: all of it won't fit: somewhere else goes to the drives", rc == 0 and "No external drive" in out
          and placed_ok(home / "TinfoilKit", essentials=True), out)
    rc, out, _, home, _ = first_run("2\n2\ny\nn\n\n", SPACE=space("tight", "fits", 450, 1000, 400, 100, 100))
    check("SETUP first run: all of it fits, but leaves too little free: warns, and goes ahead when told to",
          rc == 0 and "room for all of it, but that leaves only 50 GB free" in out
          and "Better to leave at least 100 GB, so this computer keeps running well" in out and placed_ok(home / "TinfoilKit"), out)
    rc, out, _, home, _ = first_run("2\n1\ny\nn\n\n", SPACE=space("no", "tight", 150, 1000, 400, 100, 100))
    check("SETUP first run: only the essentials fit, leaving too little free: warns, and goes ahead when told to",
          rc == 0 and "Only the essentials fit on this computer, and they leave only 50 GB free" in out
          and placed_ok(home / "TinfoilKit", essentials=True), out)
    rc, out, dl, home, _ = first_run("2\n", SPACE=space("no", "no", 50, 1000, 400, 100, 100))
    check("SETUP first run: not even the essentials fit: says so, and asks for somewhere else",
          rc == 1 and "not enough room, even for the essentials" in out and "There isn't room on this computer" in out
          and "No external drive" in out and dl.exists() and not (home / "TinfoilKit").exists(), out)
    rc, out, _, home, _ = first_run("1\n1\n3\ny\nn\n\n", drives=["STICK"], SPACE_DRIVE=space("no", "no", 20, 64, 400, 100, 10))
    check("SETUP first run: a drive too small even for the essentials: says so, and this computer is still an option",
          rc == 0 and "STICK (" in out and "20 GB free of 64 GB): not enough room, even for the essentials" in out
          and "There isn't room on STICK" in out and placed_ok(home / "TinfoilKit"), out)
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

    def placed_cfg(where):
        c = json.loads((where / "kit.json").read_text())
        return c["maps"].get("region"), [z["zim"] for z in c["library"] if z["zim"].startswith("wikipedia_")]

    rc, out, dl, home, _ = first_run("2\ny\nn\n\n", where="Atlantis\nUSA\nTexas\n1\n")
    check("SETUP first run: asks where you live first, says when it can't tell, and sets the maps and Wikipedia",
          rc == 0 and "Step 1 of 3: where do you live?" in out and 'No place called "Atlantis"' in out
          and '"USA" matches' in out and "Maps: Texas" in out and "Step 2 of 3: where should the kit go" in out
          and "Step 3 of 3: a small kit to try first" in out and placed_ok(home / "TinfoilKit")
          and placed_cfg(home / "TinfoilKit") == ("us/texas", ["wikipedia_en_all_maxi"]), out)
    rc, out, dl, home, _ = first_run("2\ny\nn\n\n", where="Georgia\n1\n2\n")
    check("SETUP first run: a name two places share: asks which, then which language",
          rc == 0 and "Which one?" in out and "Georgia (United States)" in out and "Georgia (Europe)" in out
          and "Which language should Wikipedia be in?" in out
          and placed_cfg(home / "TinfoilKit") == ("us/georgia", ["wikipedia_es_all_maxi"]), out)
    rc, out, dl, home, _ = first_run("", where="", args=("--region", "texas", "--this-computer", "--yes"))
    k = home / "TinfoilKit"
    check("SETUP --region texas --this-computer --yes: asks nothing, sets up in the home folder, doesn't open the kit",
          rc == 0 and placed_ok(k) and not dl.exists() and placed_cfg(k) == ("us/texas", ["wikipedia_en_all_maxi"])
          and "update --yes" in (k / "args.log").read_text().splitlines() and not any(a in out for a in asked)
          and "Open the kit now" not in out and "The try-it kit works" in out, out)
    t7 = work / "place" / "Volumes" / "SAMSUNG T7"
    rc, out, dl, home, _ = first_run("", where="", drives=["SAMSUNG T7"], args=(
        "--drive", str(t7), "--essentials", "--models", "Gemma-4-E4B", "--skip", "maps", "--add", "gutenberg_en_all,wikipedia",
        "--yes"))
    c = json.loads((t7 / "TinfoilKit" / "kit.json").read_text()) if (t7 / "TinfoilKit" / "kit.json").exists() else {}
    check("SETUP --drive --essentials --models --skip --add --yes: on the drive, the try-it kit, then just the essentials "
          "plus what was added",
          rc == 0 and placed_ok(t7 / "TinfoilKit", essentials=True, then_rest=True) and "What goes in it:" in out
          and "Step 4 of 4: the rest of the kit" in out
          and [m["id"] for m in c["models"] if m.get("enabled", True)] == ["Gemma-4-E4B"] and c["maps"]["enabled"] is False
          and [z["zim"] for z in c["library"] if z.get("essential")] == ["wikipedia_en_all_maxi", "gutenberg_en_all"], out)
    rc, out, dl, home, _ = first_run("", where="", args=("--drive", str(t7.parent / "NOPE"), "--yes"))
    check("SETUP --drive with no drive there, --yes: says so and stops", rc == 1 and "There's no drive at" in out
          and dl.exists() and not (home / "TinfoilKit").exists(), out)
    rc, out, dl, home, _ = first_run("2\ny\nn\n\n", args=("--drive", str(t7.parent / "NOPE")))
    check("SETUP --drive with no drive there: says so, then asks where", rc == 0 and "There's no drive at" in out
          and placed_ok(home / "TinfoilKit"), out)
    rc, out, dl, home, _ = first_run("", where="", args=("--yes",), SPACE=small)
    check("SETUP --yes: all of it won't fit with room to spare: just the essentials, and says so",
          rc == 0 and "So it gets just the essentials" in out and placed_ok(home / "TinfoilKit", essentials=True), out)
    rc, out, dl, home, _ = first_run("", where="", args=("--all", "--yes"), SPACE=small)
    rc2, out2, dl2, home2, _ = first_run("", where="", args=("--yes",), SPACE=space("no", "no", 50, 1000, 400, 100, 100))
    check("SETUP --yes: all of it with --all, or even the essentials, won't fit: stops before moving anything",
          rc == rc2 == 1 and dl.exists() and dl2.exists() and not (home / "TinfoilKit").exists()
          and "There isn't room on this computer, even for the essentials" in out2, out + out2)
    rc, out, dl, home, _ = first_run("2\ny\nn\n\n", where="Texas\n1\n", home_kit="kit")
    check("SETUP first run: a kit already in the home folder gets the place chosen in the download",
          rc == 0 and "already a Tinfoil Kit" in out and placed_cfg(home / "TinfoilKit")[0] == "us/texas", out)
    shm = Path("/dev/shm")
    # (Docker mounts /dev/shm noexec, where the copied ./kit can't run.)
    if (shm.is_dir() and os.access(shm, os.W_OK) and shm.stat().st_dev != work.stat().st_dev
            and not os.statvfs(shm).f_flag & getattr(os, "ST_NOEXEC", 8)):
        drv = Path(tempfile.mkdtemp(prefix="kit drives ", dir=shm))
        try:
            (drv / "USB DRIVE").mkdir()
            rc, out, dl, _, _ = first_run("1\n1\ny\nn\n\n", KIT_DRIVES=drv)
            check("SETUP first run: a drive that's another disk: the kit is copied over, and the download removed",
                  rc == 0 and placed_ok(drv / "USB DRIVE" / "TinfoilKit") and not dl.exists() and "Moved the kit" in out
                  and not (drv / "USB DRIVE" / "TinfoilKit.partial").exists(), out)
            shutil.rmtree(drv / "USB DRIVE" / "TinfoilKit")
            rc, out, dl, _, _ = first_run("1\n1\ny\nn\n\n", git=True, KIT_DRIVES=drv)
            tk = drv / "USB DRIVE" / "TinfoilKit"
            check("SETUP first run: a git checkout is copied to the drive, .git and all, and stays where it was; "
                  "npm's packages and the website's build stay behind",
                  rc == 0 and placed_ok(tk) and (tk / ".git").is_dir() and dl.exists() and "Use that copy from now on" in out
                  and (tk / "site" / "sources.json").exists() and not (tk / "node_modules").exists()
                  and not (tk / "site" / "node_modules").exists() and not (tk / "site" / ".next").exists(), out)
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
    own_python = work / "Library" / "Application Support" / "TinfoilKit"    # what SETUP gets for a Mac without Python
    (own_python / "python" / "bin").mkdir(parents=True)
    (own_python / "python" / "bin" / "python3").write_text("#!/bin/sh\n")
    rc, out, gone = uninstall(answers="\n\n")
    check("UNINSTALL: says what it deletes, and just Return keeps everything",
          rc == 0 and "This deletes Tinfoil Kit" in out and "can't be undone" in out and "Kept" in out
          and "Also the Python it downloaded" in out and own_python.exists()
          and (gone / "models/Tiny/Tiny.gguf").exists() and kit_log.read_text() == "", out)
    rc, out, gone = uninstall(answers="yes\n\n")
    check("UNINSTALL: anything but delete keeps it", rc == 0 and "Kept" in out and (gone / "library/book.zim").exists(), out)
    rc, out, gone = uninstall(answers="delete\n\n")
    check("UNINSTALL: typing delete removes the kit, its downloads and its Python, and nothing beside it",
          rc == 0 and not gone.exists() and (gone.parent / "keep.txt").exists() and "Tinfoil Kit is gone" in out
          and not own_python.exists(), out)
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
  "settings": {
    "default_model": "Big"
  },
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
    check("kit fit --ask: just Return skips them, in kit.json, changing only the lines that say so",
          rc == 0 and "Download them anyway? [y/N]" in out and on == {"Big": False, "Mid": True, "Small": True}
          and added == ['    "models_off_for_memory": ["Big"],', '      "enabled": false,'], out)
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
    (fk / ".kit").mkdir(exist_ok=True)
    (fk / ".kit" / "state.json").write_text(json.dumps({"items": {"models/Big": {}}}))
    rc, out = fit(16, "--skip")
    check("kit fit --skip: leaves alone a model that's already downloaded", rc == 0 and "can't run" not in out
          and (fk / "kit.json").read_text() == fit_json, out)
    (fk / ".kit" / "state.json").unlink()
    named = fit_json.replace('"id": "Big",', '"id": "Big",\n      "essential": true,')
    (fk / "kit.json").write_text(named)
    rc, out = fit(16, "--skip")
    check("kit fit --skip: keeps a model asked for by name", rc == 0 and "Big comes anyway, as asked" in out
          and (fk / "kit.json").read_text() == named, out)
    (fk / "kit.json").write_text(fit_json)

    # ./kit essentials on|off: just the essentials from now on, or everything again.
    rc, out = kit("essentials", "on", root=fk)
    check("kit essentials on: one line in kit.json's settings", rc == 0 and "Just the essentials" in out
          and json.loads((fk / "kit.json").read_text())["settings"]["essentials_only"] is True
          and len((fk / "kit.json").read_text().splitlines()) == len(fit_json.splitlines()) + 1, out)
    rc, out = kit("essentials", "off", root=fk)
    check("kit essentials off: kit.json as it was", rc == 0 and "Everything" in out and (fk / "kit.json").read_text() == fit_json, out)

    # ./kit pick: what goes in the kit, by name (SETUP's --no-ai, --models, --skip and --add).
    pk = work / "pick"
    shutil.copytree(TESTS.parent / "tools", pk / "tools")
    shutil.copy(TESTS.parent / "kit.json", pk)
    before = (pk / "kit.json").read_text()
    rc, out = kit("pick", "--models", "gemma-4-e4b", "--skip", "stackexchange", "--add", "gutenberg_en_all Wikipedia", root=pk)
    c = json.loads((pk / "kit.json").read_text())
    diff = list(difflib.ndiff(before.splitlines(), (pk / "kit.json").read_text().splitlines()))
    added, gone = [x for x in diff if x.startswith("+ ")], [x for x in diff if x.startswith("- ")]
    se = [z for z in c["library"] if ".stackexchange.com_" in z["zim"]]
    check("kit pick: just that model, every Stack Exchange site off, and the adds on, changing only the lines that say so",
          rc == 0 and [m["id"] for m in c["models"] if m.get("enabled", True)] == ["Gemma-4-E4B"]
          and len(se) == 10 and all(z.get("enabled") is False for z in se) and "enabled" not in c["library"][-1]
          and len(added) == 18 and len(gone) == 12
          and all('"enabled": false' in x or '"essential": true' in x or '"picked": true' in x for x in added)
          and c["settings"]["picked"] is True and "AI models: Gemma-4-E4B." in out, out)
    items = {i.key: i for i in kp.items_from_config(kp.load_config(pk))}
    runs = {"runs": "Inkling-2-Mini", "smallest": "Inkling-2-Mini"}
    check("kit pick: what's asked for by name comes even with just the essentials",
          all(kp.essential(items[k], runs) for k in ("library/gutenberg_en_all", "library/wikipedia_en_all_maxi",
                                                     "models/Gemma-4-E4B"))
          and not kp.essential(items["library/wiktionary_en_all_nopic"], runs))
    now = (pk / "kit.json").read_text()
    rc, out = kit("pick", "--add", "libretexts,nothing-such", root=pk)
    rc2, out2 = kit("pick", "--models", "wikipedia", root=pk)
    check("kit pick: a name the kit doesn't have changes nothing, and says what there is",
          rc == rc2 == 2 and "Nothing in the kit is called nothing-such" in out and "Books: mdwiki_en_all_maxi" in out
          and "No AI model is called wikipedia" in out2 and (pk / "kit.json").read_text() == now, out + out2)

    # ./kit pick --ask: the kit builder's choices, asked in a terminal: a preset, or each part.
    ak = work / "ask"
    shutil.copytree(TESTS.parent / "tools", ak / "tools")
    ask_json = json.dumps({"settings": {}, "models": [{"id": "Tiny", "type": "hf"}, {"id": "Two", "type": "hf"}],
                           "library": [{"zim": "testmed_en_all_maxi"}, {"zim": "testsurvival_en"}]}, indent=1)
    (ak / "kit.json").write_text(ask_json)
    (ak / "site").mkdir()
    (ak / "site" / "sources.json").write_text(json.dumps({"sources": [
        {"id": "Tiny", "group": "AI models", "title": "Tiny AI", "bytes": 2 * 10**9, "presets": ["recommended", "essentials", "everything"]},
        {"id": "Two", "group": "AI models", "title": "Two AI", "bytes": 3 * 10**9, "presets": ["everything"]},
        {"id": "testmed_en_all_maxi", "group": "Medicine", "title": "Medicine", "bytes": 4 * 10**9,
         "presets": ["recommended", "essentials", "everything", "no-ai"]},
        {"id": "testsurvival_en", "group": "Survival", "title": "Survival", "bytes": 60 * 10**9, "presets": ["everything", "no-ai"]}]}))

    def ask(answers):
        p = subprocess.run([sys.executable, str(ak / "tools" / "kit.py"), "--root", str(ak), "pick", "--ask"], input=answers,
                           capture_output=True, text=True, timeout=60, env={**os.environ, "KIT_MEMORY_MB": str(32 * 1024)})
        c = json.loads((ak / "kit.json").read_text())
        return p.returncode, p.stdout + p.stderr, sorted(e.get("id", e.get("zim")) for s in ("models", "library")
                                                          for e in c[s] if e.get("enabled", True)), c["settings"]
    rc, out, on, settings = ask("\n")
    check("kit pick --ask: lists the builder's presets with their sizes, and Return takes Recommended",
          rc == 0 and "1  Recommended: what we'd take. About 7 GB." in out and "3  Everything:" in out
          and "5  Choose each part" in out and on == ["Tiny", "testmed_en_all_maxi"] and settings == {"picked": True}, out)
    rc, out, on, _ = ask("9\n4\n")
    check("kit pick --ask: a number it doesn't have asks again; No AI switches every model off",
          rc == 0 and "Type a number from 1 to 5" in out and on == ["testmed_en_all_maxi", "testsurvival_en"], out)
    rc, out, on, _ = ask("5\n1 4\n\n")
    check("kit pick --ask: choose each part, by group, switching them with their numbers",
          rc == 0 and "AI models" in out and "[ ] Tiny AI (2.0 GB)" in out and "[x] Survival (60.0 GB)" in out
          and on == ["Tiny", "testmed_en_all_maxi"], out)

    # ./kit space: whether the kit, or just its essentials, fits on a disk and leaves 10% of the computer's (5% of a
    # drive's) free. A made-up 1000 GB disk, a kit of 300 GB and essentials of 40 GB.
    import types
    saved = kp.estimate_gb, kp.on_this_computer, kp.shutil
    kp.estimate_gb = lambda root, cfg, essentials=None: 40 if essentials else 300
    for computer, free, full, ess in ((True, 500, "fits", "fits"), (True, 380, "tight", "fits"), (True, 320, "no", "fits"),
                                      (True, 130, "no", "tight"), (True, 80, "no", "no"), (False, 340, "tight", "fits"),
                                      (False, 360, "fits", "fits")):
        kp.on_this_computer = lambda p, c=computer: c
        kp.shutil = types.SimpleNamespace(disk_usage=lambda p, f=free: types.SimpleNamespace(total=1000 * 10**9, free=f * 10**9))
        sp = kp.space_at(work / "nowhere" / "TinfoilKit", work, {"settings": {}})
        check(f"kit space: {free} GB free of 1000 on {'this computer' if computer else 'a drive'}: kit {full}, essentials {ess}",
              (sp["full"], sp["essentials"]) == (full, ess), json.dumps(sp))
    kp.estimate_gb, kp.on_this_computer, kp.shutil = saved

    # The kit builder's No AI preset switches every model off: ./kit test doesn't ask for one
    noai = work / "noai"
    shutil.copytree(TESTS.parent / "tools", noai / "tools")
    (noai / "kit.json").write_text(json.dumps({"settings": {}, "models": [{"id": "Tiny", "enabled": False}],
                                               "library": [], "maps": {"enabled": False}}))
    rc, out = kit("test", root=noai)
    check("test: a kit with every model off doesn't ask for one", "models present" not in out and "without the AI" in out, out)

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

    # A library server that won't use 127.0.0.1, as kiwix-serve 3.8 says when the loopback has a second IPv4 address (it
    # keeps only the last one of each interface): the launcher starts it on ::1 and forwards 127.0.0.1 to it, so the
    # library answers at 127.0.0.1, where the page and every server's CORS rule expect it.
    refusing = work / "refusing-kiwix-serve"
    refusing.write_text(f"""#!{sys.executable}
import http.server, socket, sys
a = sys.argv[1:]
if "--port" not in a:
    sys.exit(0)
port, address = int(a[a.index("--port") + 1]), a[a.index("--address") + 1]
if address != "::1":
    sys.exit("ERROR: IP address is not available on this system: " + address)
class Page(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<title>Tinfoil Kit</title>" + b"x" * 200000
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a):
        pass
class Server(http.server.ThreadingHTTPServer):
    address_family = socket.AF_INET6
Server(("::1", port), Page).serve_forever()
""")
    refusing.chmod(0o755)
    try:
        with socket.socket(socket.AF_INET6) as s:
            s.bind(("::1", 0))
        ipv6 = True
    except OSError:
        ipv6 = False
    if not ipv6:
        print("  SKIP  launcher: a library server that won't use 127.0.0.1 (this computer has no IPv6 to try ::1 on)")
    else:
        lport = free_port()
        (lk / "kit.json").write_text(json.dumps({"settings": {"default_model": "Big", "library_port": lport, "ai_port": rport}}))
        p = subprocess.Popen(["bash", str(lk / "tools" / "launch.sh"), "--no-browser"], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, stdin=subprocess.DEVNULL,
                             env={**os.environ, "KIT_KIWIX_TOOLS_BIN": str(refusing)})
        lines = []
        threading.Thread(target=lambda: [lines.append(x) for x in p.stdout], daemon=True).start()
        end = time.time() + 60
        while time.time() < end and not any("Keep this window open" in x for x in lines):
            time.sleep(0.2)
        try:
            pages = [kp.http_get(f"http://127.0.0.1:{lport}/") for _ in range(3)]
        except kp.HttpError as e:
            pages = [str(e).encode()]
        out = "".join(lines)
        check("launcher: a library server that won't use 127.0.0.1 listens on ::1, and the library answers at 127.0.0.1",
              "forwards 127.0.0.1" in out and "Library:  ready" in out and f"Open:     http://127.0.0.1:{lport}/" in out
              and all(pg.startswith(b"<title>Tinfoil Kit</title>") and len(pg) == 200026 for pg in pages), out)
        p.terminate()
        try:
            p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            p.kill()
        time.sleep(0.5)
        with socket.socket() as s:
            stopped = s.connect_ex(("127.0.0.1", lport)) != 0
        check("launcher: closing it stops the library's forwarder too", stopped)
        (noai / "library").mkdir(exist_ok=True)
        (noai / "library" / "book.zim").touch()
        rc, out = kit("test", root=noai, env={**env, "KIT_KIWIX_TOOLS_BIN": str(refusing)})
        check("test: a library server that won't use 127.0.0.1 is tested on ::1, where the launcher runs it",
              "PASS  library server starts" in out and "tested on ::1" in out, out)

    # Building the directions network: memory for it sized to the computer, and built again on disk if it runs out.
    m = dict(kp.MAPS_DEFAULTS)
    heaps = []
    for mb in ("8192", "16384", "65536", "0"):
        os.environ["KIT_MEMORY_MB"] = mb
        heaps.append(kp.import_heap(m))
    os.environ.pop("KIT_MEMORY_MB")
    check("directions build: 60% of memory up to 12 GB, and 12 GB when it can't tell, unless kit.json says",
          heaps == ["4g", "9g", "12g", "12g"] and kp.import_heap({**m, "routing_import_heap": "20g"}) == "20g", str(heaps))
    gh_dir = work / "routing"
    gh_dir.mkdir()
    fake_java = gh_dir / "java"
    fake_java.write_text('#!/bin/bash\necho "$@" >> calls.log\n'
                         'grep -q "default_type: RAM_STORE" gh-import.yml && [ -n "$OOM_ALWAYS$OOM_IN_MEMORY" ] && exit 3\n'
                         '[ -n "$OOM_ALWAYS" ] && exit 3\n[ -n "$CRASH" ] && exit 1\n'
                         'mkdir -p graph-cache.new && echo graph > graph-cache.new/properties\n')
    fake_java.chmod(0o755)

    def build(**env_vars):
        (gh_dir / "calls.log").unlink(missing_ok=True)
        os.environ.update(env_vars)
        try:
            kp.build_routing(fake_java, gh_dir / "graphhopper-web.jar", m, gh_dir)
            result = "built"
        except RuntimeError as e:
            result = str(e)
        finally:
            for k in env_vars:
                os.environ.pop(k)
        calls = (gh_dir / "calls.log").read_text().splitlines()
        return result, calls
    result, calls = build()
    check("directions build: in memory the first time, stopping if Java runs out",
          result == "built" and len(calls) == 1 and "-XX:+ExitOnOutOfMemoryError" in calls[0], f"{result} {calls}")
    result, calls = build(OOM_IN_MEMORY="1")
    check("directions build: out of memory in memory: built again on disk",
          result == "built" and len(calls) == 2 and "default_type: MMAP" in (gh_dir / "gh-import.yml").read_text(), f"{result} {calls}")
    result, calls = build(OOM_ALWAYS="1")
    check("directions build: out of memory on disk too: says what to do", "Close other apps" in result and len(calls) == 2, result)
    result, calls = build(CRASH="1")
    check("directions build: any other failure isn't retried", "failed (exit 1)" in result and len(calls) == 1, result)

    # Windows has no unzip, and its tar may not read bzip2 (the address database): the kit unpacks in Python there.
    import zipfile
    ex = work / "extract"
    ex.mkdir()
    with zipfile.ZipFile(ex / "a.zip", "w") as z:
        z.writestr("prog-1/bin/prog.exe", b"MZ")
        info = zipfile.ZipInfo("prog-1/bin/tool")
        info.external_attr = 0o100755 << 16
        z.writestr(info, b"#!")
    tar = io.BytesIO()
    with tarfile.open(fileobj=tar, mode="w") as tf:
        for name, data in (("photon_data/node_1/a.bin", b"x" * 5000), ("photon_data/b.txt", b"hi")):
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    tar = tar.getvalue()    # in two compressed parts, as pbzip2 and lbzip2 make it: Photon's databases come that way
    (ex / "db.tar.bz2").write_bytes(bz2.compress(tar[:3000]) + bz2.compress(tar[3000:]))
    kp.unzip_py(ex / "a.zip", ex / "z")
    check("unzip in Python: files land in place and programs stay runnable",
          (ex / "z/prog-1/bin/prog.exe").read_bytes() == b"MZ" and os.access(ex / "z/prog-1/bin/tool", os.X_OK))
    kp.untar_py(ex / "db.tar.bz2", ex / "t", "bz2")
    check("untar in Python: a bzip2 database in several parts unpacks (pbzip2 makes those)", (ex / "t/photon_data/node_1/a.bin").stat().st_size == 5000
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
    # A Mac's or Linux PC's programs come with links, which exFAT can't hold: set up from Windows, they're copies.
    with tarfile.open(ex / "links.tar.gz", "w:gz") as tf:
        for name, kind, target in (("lib/libfoo.dylib", tarfile.SYMTYPE, "libfoo.1.dylib"),    # a link to a link
                                   ("lib/libfoo.1.dylib", tarfile.SYMTYPE, "libfoo.1.2.dylib"),
                                   ("lib/libfoo.1.2.dylib", tarfile.REGTYPE, ""),
                                   ("lib/hard.dylib", tarfile.LNKTYPE, "lib/libfoo.1.2.dylib"),
                                   ("legal", tarfile.SYMTYPE, "lib"),    # a folder
                                   ("out", tarfile.SYMTYPE, "../../outside.txt"), ("abs", tarfile.SYMTYPE, "/etc/passwd"),
                                   ("loop", tarfile.SYMTYPE, ".")):
            ti = tarfile.TarInfo(name)
            ti.type, ti.linkname = kind, target
            ti.size = 3 if kind == tarfile.REGTYPE else 0
            tf.addfile(ti, io.BytesIO(b"lib") if kind == tarfile.REGTYPE else None)
    kp.untar_py(ex / "links.tar.gz", ex / "l", "gz")
    copies = [ex / "l" / n for n in ("lib/libfoo.dylib", "lib/libfoo.1.dylib", "lib/hard.dylib", "legal/libfoo.dylib")]
    check("untar in Python: links become copies, of a link and of a folder too",
          all(p.exists() and p.read_bytes() == b"lib" and not p.is_symlink() for p in copies)
          and not any(os.path.lexists(ex / "l" / n) for n in ("out", "abs", "loop")), sorted(map(str, (ex / "l").rglob("*"))))
    with zipfile.ZipFile(ex / "links.zip", "w") as z:
        z.writestr("bin/llama-server", b"prog")
        info = zipfile.ZipInfo("bin/llama")
        info.external_attr = 0o120777 << 16
        z.writestr(info, "llama-server")
    kp.unzip_py(ex / "links.zip", ex / "lz")
    check("unzip in Python: a link becomes a copy",
          (ex / "lz/bin/llama").read_bytes() == b"prog" and not (ex / "lz/bin/llama").is_symlink())
    path = os.environ["PATH"]
    try:
        os.environ["PATH"] = str(ex / "empty")    # no unzip or tar: the Python fallback takes over
        target = ex / "prog"
        kp.extract_archive(ex / "a.zip", "a.zip", target)
        check("extracting without unzip installed", (target / "prog-1/bin/prog.exe").exists())
    finally:
        os.environ["PATH"] = path

    # Where you live: ./kit region and the list of places in tools/regions.json (the real one)
    rk = work / "region kit"
    shutil.copytree(TESTS.parent / "tools", rk / "tools")
    shutil.copy(TESTS.parent / "kit.json", rk / "kit.json")

    def rk_cfg():
        c = json.loads((rk / "kit.json").read_text())
        return c["maps"], [z for z in c["library"] if z["zim"].startswith("wikipedia_")]

    def ids(out):
        return [line.split("\t")[0] for line in out.splitlines() if "\t" in line]

    rc, out = kit("region", root=rk)
    check("region: says where the maps are for and Wikipedia's language", rc == 0 and "Maps are for US Northeast" in out
          and "Wikipedia is in English" in out, out)
    rc, out = kit("region", "--find", "georgia", root=rk)
    check("region --find: a name two places share lists both", rc == 0 and ids(out) == ["us/georgia", "georgia"], out)
    rc, out = kit("region", "--find", "UK", root=rk)
    check("region --find: what people call a country", rc == 0 and ids(out)[:1] == ["united-kingdom"], out)
    rc, out = kit("region", "--find", "Munich", root=rk)
    check("region --find: a big town finds its place", rc == 0 and ids(out) == ["bayern"], out)
    rc, out = kit("region", "--find", root=rk)
    check("region --find with nothing lists every place", rc == 0 and len(ids(out)) == len(kp.regions()["regions"]) > 200)
    rc, out = kit("region", "Washington", root=rk)
    check("region: a name two places share asks which", rc == 1 and "could be" in out and "us/district-of-columbia" in out
          and "us/washington" in out, out)
    rc, out = kit("region", "georgia", root=rk)
    check("region: an id is that place (SETUP passes ids)", rc == 0 and rk_cfg()[0]["region"] == "georgia", out)
    rc, out = kit("region", "Atlantis", root=rk)
    check("region: a place it doesn't know", rc == 1 and 'No place matches "Atlantis"' in out, out)
    rc, out = kit("region", "--languages", "Bavaria", root=rk)
    check("region --languages: the place's own first, then English", rc == 0 and out.startswith("de\t")
          and any(line.startswith("en\t") for line in out.splitlines()), out)
    rc, out = kit("region", "--languages", "Malawi", root=rk)
    check("region --languages: a small Wikipedia comes only with English",
          rc == 0 and [line.split("\t")[0] for line in out.splitlines()] == ["en", "ny,en"], out)
    was = rk_cfg()[1]
    rc, out = kit("region", "Bavaria", "--wikipedia", "de,en", root=rk)
    maps, wiki = rk_cfg()
    lib = json.loads((rk / "kit.json").read_text())["library"]
    check("region: sets the maps and swaps Wikipedia in place, keeping its settings",
          rc == 0 and "Maps: Germany: Bayern" in out and "Address search: all of Germany." in out and maps["region"] == "bayern"
          and [z["zim"] for z in wiki] == ["wikipedia_de_all_maxi", "wikipedia_en_all_maxi"]
          and lib.index(wiki[0]) == [z["zim"] for z in json.loads((TESTS.parent / "kit.json").read_text())["library"]].index(was[0]["zim"])
          and all({k: v for k, v in z.items() if k not in ("zim", "note")} == {k: v for k, v in was[0].items() if k not in ("zim", "note")}
                  for z in wiki), out)
    both_gb = int(kit("estimate", root=rk)[1].strip())
    rc, out = kit("region", "--wikipedia", "de", "Bavaria", root=rk)
    de_gb = int(kit("estimate", root=rk)[1].strip())
    check("region: the estimate follows Wikipedia's languages", rc == 0 and de_gb < both_gb - 100, (both_gb, de_gb))
    rc, out = kit("region", "Texas", root=rk)
    check("region: without --wikipedia, Wikipedia stays as it is",
          rc == 0 and rk_cfg()[0]["region"] == "us/texas" and [z["zim"] for z in rk_cfg()[1]] == ["wikipedia_de_all_maxi"], out)
    rc, out = kit("region", "Texas", "--wikipedia", "xx", root=rk)
    check("region: a language Wikipedia doesn't come in", rc == 1 and "doesn't come in 'xx'" in out
          and rk_cfg()[0]["region"] == "us/texas", out)
    wide = next(r for r in kp.regions()["regions"] if r.get("addresses_wide"))
    rc, out = kit("region", wide["id"], root=rk)
    check("region: a place with only a continent's address search says so, and how big it is",
          rc == 0 and f"Address search: all of {wide['addresses']}" in out and "Just the essentials leave it out" in out, out)
    kp_cfg = json.loads((rk / "kit.json").read_text())
    geo = next(i for i in kp.items_from_config(kp_cfg) if i.id == "geocoder")
    without = kp.estimate_gb(rk, kp_cfg, True)
    wide["addresses_wide"] = False
    with_it = kp.estimate_gb(rk, kp_cfg, True)
    wide["addresses_wide"] = True
    check("region: just the essentials leave out a continent's address search",
          geo.cfg["wide"] and not kp.essential(geo, {"runs": "", "smallest": ""})
          and abs(with_it - without - wide["mb"]["addresses"] / 1000) <= 1, (with_it, without, wide["mb"]))

    # the maps settings a place gives, and what kit.json can still change by hand
    m = kp.maps_settings({"maps": {"enabled": True, "region": "us/texas"}})
    check("maps_settings: a place's map, directions, address search and home",
          m["label"] == "Texas" and m["routing_osm_pbf"].endswith("/north-america/us/texas/texas-latest.osm.pbf")
          and m["geocoder_country"] == "us" and not m["geocoder_wide"] and m["home"]["label"] == "Houston, TX"
          and m["units"] == "imperial" and m["lang"] == "en", m)
    m = kp.maps_settings({"maps": {"enabled": True, "region": "us/texas", "detail_maxzoom": 14,
                                   "home": {"label": "Mine", "lat": 1, "lon": 2}}})
    check("maps_settings: kit.json's own keys win", m["detail_maxzoom"] == 14 and m["home"]["label"] == "Mine"
          and m["home"]["zoom"] == 10 and m["label"] == "Texas", m)
    m = kp.maps_settings({"maps": {"enabled": True, "region": wide["id"], "geocoder_country": "de"}})
    check("maps_settings: an address search set by hand isn't a continent's", m["geocoder_country"] == "de" and not m["geocoder_wide"])
    check("maps_settings: a place the kit doesn't know", "region_error" in kp.maps_settings({"maps": {"region": "atlantis"}}))
    bare = next(r for r in kp.regions()["regions"] if "photon" not in r)
    check("maps: no address search item where nobody publishes one",
          not [i for i in kp.maps_items({"maps": {"enabled": True, "region": bare["id"]}}) if i["id"] == "geocoder"], bare["id"])
    # ./kit test after just the essentials, as SETUP's first run does: an address search that isn't coming, or that
    # comes later, isn't a failure
    no_map = work / "no map yet"
    no_map.mkdir()

    def map_checks(place):
        seen, out = [], io.StringIO()
        with contextlib.redirect_stdout(out):
            kp.test_maps(no_map, kp.maps_settings({"maps": {"enabled": True, "region": place}}),
                         lambda name, ok, detail="": seen.append(name), [], no_map)
        return seen, out.getvalue()
    seen, out = map_checks(bare["id"])
    check("test: no address search check where nobody publishes one",
          "address search installed" not in seen and "SKIP  address search: nobody publishes one" in out, out)
    seen, out = map_checks(wide["id"])
    check("test: a continent's address search, which comes after the essentials, isn't missing yet",
          "address search installed" not in seen and "SKIP  address search: not here yet" in out, out)
    seen, out = map_checks("us/texas")
    check("test: a place's own address search must be there", "address search installed" in seen, out)
    check("find_regions: a state's name", [r["id"] for r in kp.find_regions("New York")][:1] == ["us/new-york"])
    check("regions: every place's road data is a Geofabrik extract, with a home inside its box",
          all(kp.region_maps(r)["routing_osm_pbf"].startswith(kp.GEOFABRIK) and r["bbox"][0] <= r["home"]["lon"] <= r["bbox"][2]
              and r["bbox"][1] <= r["home"]["lat"] <= r["bbox"][3] and all(c in kp.regions()["languages"] for c in r["langs"])
              for r in kp.regions()["regions"]))

    # Given a size rounded up to a whole KiB, download() takes a file a hair short of it once the server has nothing more
    # (its checksum decides), whether it starts from nothing or from the whole file a sync before left.
    book, part = R / "zim/testmed_en_all_maxi_2026-01.zim", work / "rounded" / "book.zim.partial"
    part.parent.mkdir()
    took = []
    for _ in range(2):
        try:
            kp.download(f"{base}/zim/{book.name}", part, listed, "curl")
            took.append(part.read_bytes() == book.read_bytes())
        except RuntimeError as e:
            took.append(str(e))
    check("download: a size rounded up to a whole KiB doesn't fail a whole file", took == [True, True], str(took))

    # a Wikipedia in the old language goes once the new one is in
    wr = work / "wiki swap"
    (wr / "zim").mkdir(parents=True)
    (wr / "zim" / "wikipedia_en_all_maxi_2026-01.zim").write_bytes(b"en")
    st = {"items": {"library/wikipedia_en_all_maxi": {"dest": "zim", "files": {"wikipedia_en_all_maxi_2026-01.zim": {}}},
                    "library/testmed_en_all_maxi": {"dest": "zim", "files": {}}}}
    items = kp.items_from_config({"settings": {}, "library": [{"zim": "wikipedia_de_all_maxi"}, {"zim": "testmed_en_all_maxi"}]})
    kp.drop_replaced_wikipedias(wr, st, items)
    check("Wikipedia swap: the old one stays until the new one is in", "library/wikipedia_en_all_maxi" in st["items"]
          and (wr / "zim" / "wikipedia_en_all_maxi_2026-01.zim").exists())
    st["items"]["library/wikipedia_de_all_maxi"] = {"dest": "zim", "files": {"wikipedia_de_all_maxi_2026-01.zim": {}}}
    kp.drop_replaced_wikipedias(wr, st, items)
    check("Wikipedia swap: then the old one goes, and nothing else", "library/wikipedia_en_all_maxi" not in st["items"]
          and not (wr / "zim" / "wikipedia_en_all_maxi_2026-01.zim").exists() and "library/testmed_en_all_maxi" in st["items"])

    # Geofabrik's -latest can point at a file that isn't up yet: then the day before's
    saved_head, asked = kp.http_head, []

    def fake_head(url, *a, **k):
        asked.append(url)
        if url.endswith("-latest.osm.pbf") or len(asked) < 3:
            raise kp.HttpError(url, "curl: (22) The requested URL returned error: 404", 404)
        return {"content-length": "5"}
    try:
        kp.http_head = fake_head
        url, h = kp.geofabrik_head("https://download.geofabrik.de/europe/romania/romania-latest.osm.pbf")
        day = (kp.dt.date.today() - kp.dt.timedelta(days=2)).strftime("%y%m%d")
        check("Geofabrik: a missing latest file falls back to the newest dated one",
              url == f"https://download.geofabrik.de/europe/romania/romania-{day}.osm.pbf" and h["content-length"] == "5", asked)
        asked.clear()
        kp.http_head = lambda url, *a, **k: (_ for _ in ()).throw(kp.HttpError(url, "404", 404))
        try:
            kp.geofabrik_head("https://download.geofabrik.de/x/y-latest.osm.pbf")
            check("Geofabrik: no file at all is an error", False)
        except kp.HttpError:
            check("Geofabrik: no file at all is an error", True)
    finally:
        kp.http_head = saved_head
finally:
    mock.terminate()
    shutil.rmtree(work, ignore_errors=True)

print("\nALL PASSED" if not fails else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
