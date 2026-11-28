"""Sync engine test: runs the kit's own program (tools/tinfoilkit-*, which tools/tinfoilkit/build.sh builds)
against the mock internet (tests/mock_remote.py) with tiny made-up books and models. Covers downloads, resume,
checksums, updates, leftover partial downloads, verify --fix, adopting files already on the drive, offline runs, exit
codes, which release of a program is taken, ./kit update, the ./kit wrapper, SETUP.command's choices, UNINSTALL, the
launcher's first model and ports, and ./kit copy.
Needs python3, curl and the built program, so it runs in the quick gate and in cloud sessions.
usage: python3 tests/sync_test.py
"""

import base64
import difflib
import hashlib
import http.client
import http.server
import io
import json
import os
import platform
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
import urllib.request
from pathlib import Path

TESTS = Path(__file__).resolve().parent
CODE = TESTS.parent / "kit"  # the kit's code
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + (f": {detail}" if detail and not ok else ""))
    fails += 0 if ok else 1


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PLAT = {("Linux", "x86_64"): "linux-x64", ("Darwin", "arm64"): "macos-arm64"}.get(
    (platform.system(), platform.machine())
)
PROGRAM = CODE / "tools" / f"tinfoilkit-{PLAT}"  # the kit's own program for this computer
if not PLAT or not PROGRAM.exists():
    sys.exit("The tests need the kit's program for this computer: kit/tools/tinfoilkit/build.sh builds it")
# What the program keeps at the top of a kit's own folder, beside app, downloads and data
TOP = ["Open Tinfoil Kit for Windows.bat", "Open Tinfoil Kit.command", "Read me first.txt"]


def kit_cmd(code, root, *args):
    """The command line for a ./kit command in the kit folder root, with its code in the folder code."""
    return [str(code / "tools" / PROGRAM.name), "--root", str(root), *args]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def new_kit(root):
    """A kit folder: the code in app/ with the standard list (app/kit.json), and data/ for the person's kit.json. No
    builder's list (tools/sources.json): a test that needs one writes its own."""
    shutil.copytree(CODE / "tools", root / "app" / "tools", ignore=shutil.ignore_patterns("sources.json"))
    shutil.copy(CODE / "kit.json", root / "app" / "kit.json")
    (root / "data").mkdir(parents=True, exist_ok=True)
    return root


work = Path(tempfile.mkdtemp(prefix="kit sync test "))  # drive names often have spaces ("Samsung T7")
R = work / "remote"
for rel, size in (
    ("zim/testmed_en_all_maxi_2026-01.zim", 70_000),
    ("zim/testsurvival_en_2026-02.zim", 60_000),
    ("zim/testsurvival_en_2026-05.zim", 61_000),
    ("hf/tiny/Tiny-Q4_K_M.gguf", 300_000),
    ("hf/tiny/Tiny-Q8_0.gguf", 200_000),
    ("hf/tiny_v2/Tiny-Q4_K_M.gguf", 310_000),
    ("hf/two/Two-Q4_K_M.gguf", 150_000),
):
    (R / rel).parent.mkdir(parents=True, exist_ok=True)
    (R / rel).write_bytes(os.urandom(size))
shutil.copy(R / "hf/tiny/Tiny-Q8_0.gguf", R / "hf/tiny_v2/Tiny-Q8_0.gguf")
# Programs and map data that are only looked up, never unpacked, so random bytes will do.
for rel in (
    "gh/llama-b99990-bin-ubuntu-x64.tar.gz",
    "gh2/photon-1.3.0.jar",
    "gh2/photon-1.2.1.jar",
    "adoptium/OpenJDK21U-jre_x64_linux_hotspot_21.0.9_10.tar.gz",
    "photon/north-america/usa/photon-db-usa-1.3-latest.tar.bz2",
    "geofabrik/us-northeast-latest.osm.pbf",
    "geofabrik/new-york-latest.osm.pbf",
    "geofabrik/new-jersey-latest.osm.pbf",
):
    (R / rel).parent.mkdir(parents=True, exist_ok=True)
    (R / rel).write_bytes(os.urandom(1000))
(R / "FLAKY").touch()  # the first model download drops halfway, so sync has to resume it

port = free_port()
base = f"http://127.0.0.1:{port}"
mock = subprocess.Popen(
    [sys.executable, str(TESTS / "mock_remote.py"), str(port)],
    env={**os.environ, "KIT_TEST_WORK": str(work)},
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
env = {
    **os.environ,
    "KIT_KIWIX_CATALOG": f"{base}/catalog/v2/entries?count=-1",
    "KIT_KIWIX_RELEASES": base + "/release/{product}/",
    "KIT_GITHUB_API": base,
    "KIT_HF": base,
    "KIT_ADOPTIUM_API": base + "/adoptium",
    "KIT_MAVEN": base + "/maven",
    "KIT_NPM": base + "/npm",
    "KIT_GITHUB_WEB": base + "/ghweb",
    "KIT_PROTOMAPS_BUILDS": base + "/protomaps/builds.json",
    "KIT_PROTOMAPS_BUILD_BASE": base + "/protomaps",
    "KIT_PHOTON_DUMPS": base + "/photon/",
    "KIT_GEOFABRIK": base + "/geofabrik",
    "KIT_PART_MIN": "16384",  # so the books and models here, 60 to 310 KB, come over several connections in 16 KB parts
}

drive = work / "drive" / "TinfoilKit"
listed = -(-70_000 // 1024) * 1024  # testmed's size in the catalog: Kiwix rounds each up to a whole KiB
new_kit(drive)
cfg = {
    "settings": {"default_model": "Tiny", "keep_free_gb": 0.001, "keep_free_gb_this_computer": 0.001},
    "models": [
        {
            "id": "Tiny",
            "type": "hf",
            "repo": "test/Tiny-GGUF",
            "files": ["*-Q4_K_M.gguf", "*-Q8_0.gguf"],
            "priority": 1,
        },
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
    (drive / "data" / "kit.json").write_text(json.dumps(cfg, indent=1))


def kit(*args, env=env, root=None):
    """A ./kit command in the kit folder root: its code in its app folder, or at its top in a kit from before app/."""
    root = root or drive
    code = root / "app" if (root / "app" / "tools").is_dir() else root
    p = subprocess.run(
        kit_cmd(code, root, *args), env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180
    )
    return p.returncode, p.stdout + p.stderr


def state():
    return json.loads((drive / "data" / ".kit" / "state.json").read_text())


def same(drive_rel, remote_rel):
    p = drive / "downloads" / drive_rel
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
    check(
        "plan --essentials: the AI this computer runs and the most important books, nothing else",
        rc == 0
        and out.count("NEW") == 2
        and "Tiny" in out
        and "testmed_en_all_maxi" in out
        and "Two" not in out
        and "testsurvival" not in out
        and "ERROR" not in out,
        out,
    )
    kit("essentials", "on")
    rc, out = kit("plan")
    kit("essentials", "off")
    check(
        "plan with essentials_only set: just those, and it says so",
        rc == 0
        and out.count("NEW") == 2
        and "Just the essentials" in out
        and "Two" not in out
        and json.loads((drive / "data" / "kit.json").read_text()) == cfg,
        out,
    )

    rc, out = kit("sync", "-y")
    check("sync exits 1 when entries are broken", rc == 1, f"exit {rc}")
    check("sync names the broken entries", "models/Ambiguous" in out and "library/does_not_exist_en" in out, out[-800:])
    check(
        "an interrupted download resumes",
        not (R / "FLAKY").exists() and same("models/Tiny/Tiny-Q4_K_M.gguf", "hf/tiny/Tiny-Q4_K_M.gguf"),
    )
    check(
        "books and models downloaded intact",
        same("library/testmed_en_all_maxi_2026-01.zim", "zim/testmed_en_all_maxi_2026-01.zim")
        and same("library/testsurvival_en_2026-02.zim", "zim/testsurvival_en_2026-02.zim")
        and same("models/Tiny/Tiny-Q4_K_M.gguf", "hf/tiny/Tiny-Q4_K_M.gguf")
        and same("models/Tiny/Tiny-Q8_0.gguf", "hf/tiny/Tiny-Q8_0.gguf")
        and same("models/Two/Two-Q4_K_M.gguf", "hf/two/Two-Q4_K_M.gguf"),
        out,
    )
    catalog = subprocess.run(["curl", "-fsS", env["KIT_KIWIX_CATALOG"]], capture_output=True, text=True).stdout
    check(
        "books listed at sizes rounded up to a whole KiB, as Kiwix's catalog does, download on the first try",
        f'testmed_en_all_maxi_2026-01.zim.meta4" length="{listed}"' in catalog
        and "download interrupted (exit 0" not in out,
        out,
    )
    check("no partial downloads left", not list(drive.rglob("*.partial")), str(list(drive.rglob("*.partial"))))
    check(
        "portal page built, with no refresh date while a sync hasn't finished cleanly",
        "window.KIT_REFRESHED = null;" in (drive / "data" / ".kit" / "portal.html").read_text(),
    )

    cfg["models"] = [m for m in cfg["models"] if m["id"] != "Ambiguous"]
    cfg["library"] = [z for z in cfg["library"] if z["zim"] != "does_not_exist_en"]
    write_cfg()
    rc, out = kit("sync", "-y")
    check("second sync has nothing to do", rc == 0 and "Everything is up to date." in out, out)
    top = sorted(p.name for p in drive.iterdir())
    check(
        "once the kit is set up, its folder has a launcher for each computer and Read me first.txt beside its three",
        top == [*TOP, "app", "data", "downloads"]
        and "open app and double-click SETUP.command" in (drive / "Read me first.txt").read_text(),
        top,
    )
    check(
        "the page shows when everything was last brought up to date",
        f'window.KIT_REFRESHED = "{state().get("last_sync")}";'
        in (drive / "data" / ".kit" / "portal.html").read_text(),
    )
    # A file kit.json stops listing for an item (Gemma 4's drafts) goes, as an old version does, once the rest is in.
    cfg["models"][0]["files"] = ["*-Q4_K_M.gguf"]
    write_cfg()
    rc, out = kit("sync", "-y")
    check(
        "a file kit.json no longer lists for a model is deleted, and the rest kept",
        rc == 0
        and "Removed Tiny-Q8_0.gguf from Tiny: kit.json no longer lists it." in out
        and not (drive / "downloads" / "models/Tiny/Tiny-Q8_0.gguf").exists()
        and list(state()["items"]["models/Tiny"]["files"]) == ["Tiny-Q4_K_M.gguf"]
        and same("models/Tiny/Tiny-Q4_K_M.gguf", "hf/tiny/Tiny-Q4_K_M.gguf"),
        out,
    )
    cfg["models"][0]["files"] = ["*-Q4_K_M.gguf", "*-Q8_0.gguf"]
    write_cfg()
    rc, out = kit("sync", "-y")
    check(
        "listed again, it downloads again",
        rc == 0 and same("models/Tiny/Tiny-Q8_0.gguf", "hf/tiny/Tiny-Q8_0.gguf"),
        out,
    )

    # SETUP's first run gets the essentials first, then the rest.
    ess = work / "essentials"
    new_kit(ess)
    (ess / "data" / "kit.json").write_text(
        json.dumps({"settings": cfg["settings"], "models": [cfg["models"][1]], "library": cfg["library"][:2]})
    )
    rc, out = kit("sync", "-y", "--essentials", root=ess)
    ess_state = json.loads((ess / "data" / ".kit" / "state.json").read_text())
    check(
        "sync --essentials: gets only those, and doesn't count as a complete sync",
        rc == 0
        and (ess / "downloads" / "models/Two/Two-Q4_K_M.gguf").exists()
        and list((ess / "downloads" / "library").glob("testmed_*.zim"))
        and not list((ess / "downloads" / "library").glob("testsurvival_*"))
        and "last_sync" not in ess_state,
        out,
    )
    rc, out = kit("sync", "-y", root=ess)
    check(
        "sync after the essentials: gets the rest",
        rc == 0
        and list((ess / "downloads" / "library").glob("testsurvival_*.zim"))
        and "last_sync" in json.loads((ess / "data" / ".kit" / "state.json").read_text()),
        out,
    )

    # Before that, it gets the try-it kit (./kit starter): this computer's programs, the map, and the AI and books
    # marked "starter", even ones that are switched off (samples). The full sync after it removes the samples.
    tk = work / "try"
    new_kit(tk)
    (tk / "data" / "kit.json").write_text(
        json.dumps(
            {
                "settings": {**cfg["settings"], "starter_only": True},
                "models": [{**cfg["models"][0], "starter": True, "enabled": False}, cfg["models"][1]],
                "library": [{**cfg["library"][0], "starter": True}, cfg["library"][1]],
            }
        )
    )
    (tk / "app" / "tools" / "sources.json").write_text(
        json.dumps(
            {
                "sources": [
                    {"id": "Tiny", "bytes": 2 * 10**9},
                    {"id": "Two", "bytes": 3 * 10**9},
                    {"id": "testmed_en_all_maxi", "bytes": 4 * 10**9},
                    {"id": "testsurvival_en", "bytes": 60 * 10**9},
                ]
            }
        )
    )
    rc, out = kit("plan", root=tk)
    st = json.loads((tk / "data" / ".kit" / "state.json").read_text())
    rc2, out2 = kit("plan", root=tk)
    check(
        "plan before a kit's first download: times the connection on the biggest file, once, and says how long it takes",
        rc == 0
        and "Checking how fast this connection is" in out
        and "That takes about a minute at this connection's speed" in out
        and st.get("download_speed", 0) > 0
        and "Checking how fast" not in out2
        and "That takes about a minute" in out2,
        out + out2,
    )
    rc2, out2 = kit("estimate", root=tk)
    check(
        "plan on a try-it kit: the AI and books marked starter, even one that's switched off, and nothing else",
        rc == 0
        and out.count("NEW") == 2
        and "Tiny" in out
        and "testmed_en_all_maxi" in out
        and "Two" not in out
        and "testsurvival" not in out
        and rc2 == 0
        and out2.strip() == "7",
        out + out2,
    )
    (tk / "downloads" / "library").mkdir(parents=True)
    (tk / "downloads" / "library" / "testsurvival_en_2026-02.zim.partial").write_bytes(
        (R / "zim/testsurvival_en_2026-02.zim").read_bytes()[:1000]
    )
    rc, out = kit("sync", "-y", root=tk)
    st = json.loads((tk / "data" / ".kit" / "state.json").read_text())
    check(
        "sync on a try-it kit: just those, it counts as a complete one, and another item's unfinished download stays",
        rc == 0
        and (tk / "downloads" / "models/Tiny/Tiny-Q4_K_M.gguf").exists()
        and not (tk / "downloads" / "models/Two").exists()
        and list((tk / "downloads" / "library").glob("testmed_*.zim"))
        and not list((tk / "downloads" / "library").glob("testsurvival_*.zim"))
        and (tk / "downloads" / "library" / "testsurvival_en_2026-02.zim.partial").exists()
        and "last_sync" in st,
        out,
    )
    st["download_speed"] = 10 * 10**6
    (tk / "data" / ".kit" / "state.json").write_text(json.dumps(st))
    rc, out = kit("starter", root=tk)
    rc2, out2 = kit("estimate", "--rest", root=tk)
    check(
        "kit starter and estimate --rest: how big the rest is, and how long it takes at the speed measured",
        rc == 0
        and "Just the try-it kit" in out
        and "The rest is about 64 GB more: about 2 hours at this connection's speed (10.0 MB/s)" in out
        and "./kit starter off" in out
        and rc2 == 0
        and out2 == "64\tabout 2 hours at this connection's speed (10.0 MB/s)\n",
        out + out2,
    )
    rc, out = kit("starter", "off", root=tk)
    rc2, out2 = kit("plan", root=tk)
    check(
        "kit starter off: everything switched on, and plan says how long it takes",
        rc == 0
        and "starter_only" not in (tk / "data" / "kit.json").read_text()
        and "To get just the try-it kit" in out
        and "Two" in out2
        and "That takes about a minute at this connection's speed (10.0 MB/s)." in out2,
        out + out2,
    )
    rc, out = kit("sync", "-y", root=tk)
    st = json.loads((tk / "data" / ".kit" / "state.json").read_text())
    check(
        "the full sync after it gets the rest, then removes the sample nobody picked and keeps the book they did",
        rc == 0
        and (tk / "downloads" / "models/Two/Two-Q4_K_M.gguf").exists()
        and not (tk / "downloads" / "models/Tiny").exists()
        and "models/Tiny" not in st["items"]
        and "Removed Tiny" in out
        and list((tk / "downloads" / "library").glob("testmed_*.zim"))
        and list((tk / "downloads" / "library").glob("testsurvival_*.zim"))
        and "library/testmed_en_all_maxi" in st["items"],
        out,
    )

    # Wikipedia in sizes: until kit.json's Wikipedia is in, the try-it kit gets its best articles' opening paragraphs and
    # the essentials their text; once it's in, those go. (The mock's catalog lists any Wikipedia in remote/zim.)
    wikis = {
        "wikipedia_en_top_mini_2026-01.zim": 20_000,
        "wikipedia_en_top_nopic_2026-01.zim": 30_000,
        "wikipedia_en_top_maxi_2026-01.zim": 40_000,
        "wikipedia_en_all_maxi_2026-01.zim": 50_000,
    }
    for z, size in wikis.items():
        (R / "zim" / z).write_bytes(os.urandom(size))
    wk = new_kit(work / "wiki sizes")
    (wk / "app" / "tools" / "sources.json").write_text(
        json.dumps({"sources": [{"id": "testmed_en_all_maxi", "bytes": 10**9}]})
    )

    def wk_cfg(**settings):
        (wk / "data" / "kit.json").write_text(
            json.dumps(
                {
                    "settings": {**cfg["settings"], **settings},
                    "models": [],
                    "library": [
                        {**cfg["library"][0], "starter": True},
                        {"zim": "wikipedia_en_all_maxi", "priority": 2},
                    ],
                }
            )
        )

    def wk_has():
        return sorted(p.name.rsplit("_", 1)[0] for p in (wk / "downloads" / "library").glob("wikipedia_*.zim"))

    wk_cfg()
    sizes = [kit("estimate", *a, root=wk)[1].strip() for a in (("--starter",), ("--essentials",), ())]
    check(
        "estimate: the try-it kit and the essentials count the smaller Wikipedia standing in for kit.json's",
        sizes == ["2", "5", "130"],
        str(sizes),
    )
    wk_cfg(starter_only=True)
    rc, out = kit("sync", "-y", root=wk)
    check(
        "Wikipedia sizes: the try-it kit gets the best articles' opening paragraphs, in kit.json's language",
        rc == 0 and wk_has() == ["wikipedia_en_top_mini"],
        out,
    )
    wk_cfg(essentials_only=True)
    rc, out = kit("sync", "-y", root=wk)
    check(
        "Wikipedia sizes: the essentials get their text, and the try-it kit's goes",
        rc == 0 and wk_has() == ["wikipedia_en_top_nopic"],
        out,
    )
    wk_cfg()
    rc, out = kit("sync", "-y", root=wk)
    check(
        "Wikipedia sizes: all of it comes, then the one standing in for it goes",
        rc == 0
        and wk_has() == ["wikipedia_en_all_maxi"]
        and "Removed wikipedia_en_top_nopic: kit.json has wikipedia_en_all_maxi instead." in out,
        out,
    )
    rc, out = kit("region", "--wikipedia-size", "top", root=wk)
    rc2, out2 = kit("sync", "-y", root=wk)
    check(
        "Wikipedia sizes: another size comes in, and the old one goes once it's in",
        rc == rc2 == 0 and wk_has() == ["wikipedia_en_top_maxi"] and "Removed wikipedia_en_all_maxi" in out2,
        out + out2,
    )
    for z in wikis:
        (R / "zim" / z).unlink()

    rc, out = kit("verify")
    check("verify passes", rc == 0 and "All 5 files OK" in out, out)
    book = drive / "downloads" / "library/testmed_en_all_maxi_2026-01.zim"
    data = bytearray(book.read_bytes())
    data[1000] ^= 0xFF
    book.write_bytes(bytes(data))
    rc, out = kit("verify")
    check("verify finds a corrupt book", rc == 1 and "CORRUPT" in out, out)
    rc, out = kit("verify", "--fix")
    check("verify --fix removes it", rc == 1 and not book.exists(), out)
    rc, out = kit("sync", "-y")
    check(
        "sync replaces it",
        rc == 0 and same("library/testmed_en_all_maxi_2026-01.zim", "zim/testmed_en_all_maxi_2026-01.zim"),
        out,
    )
    # A whole book left as an unfinished download, as syncs that took Kiwix's rounded sizes for exact ones left them
    book.rename(book.with_name(book.name + ".partial"))
    st = state()
    del st["items"]["library/testmed_en_all_maxi"]
    st["partials"] = {
        "library/testmed_en_all_maxi_2026-01.zim.partial": {
            "item": "library/testmed_en_all_maxi",
            "tag": f"2026-01|{listed}",
        }
    }
    (drive / "data" / ".kit" / "state.json").write_text(json.dumps(st))
    rc, out = kit("sync", "-y")
    check(
        "a whole book left as an unfinished download is checked and kept, not downloaded again",
        rc == 0
        and "resuming at 70.0 KB" in out
        and "discarding" not in out
        and same("library/testmed_en_all_maxi_2026-01.zim", "zim/testmed_en_all_maxi_2026-01.zim"),
        out,
    )

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
    model = drive / "downloads" / "models/Two/Two-Q4_K_M.gguf"
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
    check(
        "aria2c: a full-length download it hadn't finished is resumed, not taken as done",
        rc == 0 and same("models/Two/Two-Q4_K_M.gguf", "hf/two/Two-Q4_K_M.gguf") and not record.exists(),
        out,
    )

    def served(name=None):
        """The stretches of a file (or of any) the mock internet sent since the last look, leaving out asking for
        its size."""
        log = R / "served.log"
        lines = log.read_text().splitlines() if log.exists() else []
        log.write_text("")
        return [
            (int(a), int(b)) if name else (n, int(a), int(b))
            for n, a, b in (x.split() for x in lines)
            if name in (None, n) and int(b) - int(a) > 1
        ]

    # Several connections at once, each with its own part of the file. Ctrl-C partway keeps what arrived, and a record
    # of which parts that was; the next sync fetches only the rest.
    model = drive / "downloads" / "models/Tiny/Tiny-Q4_K_M.gguf"
    model.unlink()
    partial = model.with_name(model.name + ".partial")
    record = partial.with_name(partial.name + ".parts")
    served("Tiny-Q4_K_M.gguf")
    (R / "SLOW").touch()
    p = subprocess.Popen(
        kit_cmd(drive / "app", drive, "sync", "-y"),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
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
    left_open = [
        x
        for x in subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout.splitlines()
        if x.startswith("curl") and "Range: bytes" in x and f"127.0.0.1:{port}/" in x
    ]
    sent = served("Tiny-Q4_K_M.gguf")
    check(
        "Ctrl-C partway through a download in parts: what arrived stays, with its record, and no connection is left open",
        p.returncode == 130
        and rec.get("size") == 300_000
        and 0 < arrived < 300_000
        and not left_open
        and len(sent) > 2,
        out + json.dumps(rec) + str(left_open),
    )
    rc, out = kit("sync", "-y")
    again = served("Tiny-Q4_K_M.gguf")
    check(
        "the next sync fetches only the parts that hadn't arrived",
        rc == 0
        and same("models/Tiny/Tiny-Q4_K_M.gguf", "hf/tiny/Tiny-Q4_K_M.gguf")
        and not record.exists()
        and sum(b - a for a, b in again) >= 300_000 - arrived
        and not any(a < d1 and d0 < b for a, b in again for d0, d1 in rec["done"]),
        out + str(again),
    )

    # Near the end, a connection with nothing left to fetch takes the second half of what another has left
    (drive / "downloads" / "models/Two/Two-Q4_K_M.gguf").unlink()
    (R / "SLOW").touch()
    rc, out = kit("sync", "-y")
    (R / "SLOW").unlink()
    again = served("Two-Q4_K_M.gguf")
    check(
        "near the end, an idle connection takes half of another's part",
        rc == 0
        and same("models/Two/Two-Q4_K_M.gguf", "hf/two/Two-Q4_K_M.gguf")
        and any(a % 16384 for a, b in again if a < 147_456),
        out + str(again),
    )

    # A download one connection began (one before this kit got parts, or "downloader": "curl") carries on in parts
    model.unlink()
    partial.write_bytes((R / "hf/tiny/Tiny-Q4_K_M.gguf").read_bytes()[:100_000])
    rc, out = kit("sync", "-y")
    again = served("Tiny-Q4_K_M.gguf")
    check(
        "a download one connection began carries on in parts, without fetching its start again",
        rc == 0
        and same("models/Tiny/Tiny-Q4_K_M.gguf", "hf/tiny/Tiny-Q4_K_M.gguf")
        and len(again) > 2
        and min(a for a, b in again) == 100_000
        and sum(b - a for a, b in again) >= 200_000,
        out + str(again),
    )

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
    check(
        '"downloader": "curl" carries on a download in parts from the end of its first stretch, in one piece',
        rc == 0
        and same("models/Tiny/Tiny-Q4_K_M.gguf", "hf/tiny/Tiny-Q4_K_M.gguf")
        and not record.exists()
        and again == [(50_000, 300_000)],
        out + str(again),
    )

    # A server that sends only whole files, though it says how big one is: one connection after all
    model.unlink()
    (R / "NO_PARTS").touch()
    rc, out = kit("sync", "-y")
    (R / "NO_PARTS").unlink()
    check(
        "a server that won't send parts of a file: it comes in one piece",
        rc == 0
        and same("models/Tiny/Tiny-Q4_K_M.gguf", "hf/tiny/Tiny-Q4_K_M.gguf")
        and not record.exists()
        and (0, 300_000) in served("Tiny-Q4_K_M.gguf"),
        out,
    )

    # Which release of a program: llama.cpp's builds are its nightly prereleases, but Photon's newest release
    # here is a beta, and a beta is taken only when there's nothing else.
    rt = work / "runtimes"
    new_kit(rt)
    programs = [
        {
            "id": "llama.cpp-linux-x64",
            "type": "github",
            "repo": "ggml-org/llama.cpp",
            "asset": "llama-*-bin-ubuntu-x64.tar.gz",
        },
        {"id": "photon", "type": "github", "repo": "komoot/photon", "asset": "photon-[0-9]*.jar"},
        {"id": "java-linux-x64", "type": "adoptium", "os": "linux", "arch": "x64"},
    ]
    (rt / "data" / "kit.json").write_text(json.dumps({"settings": {"pin_programs": False}, "runtimes": programs}))
    rc, out = kit("plan", root=rt)
    check(
        "plan: llama.cpp's nightly build, and Photon's full release rather than its newer beta",
        rc == 0 and "b99990" in out and "1.3.0" in out and "2.0.0-beta" not in out and "jdk-21.0.9+10" in out,
        out,
    )

    # A release names each program's build and its checksum (tools/pins.json): sync takes that build rather than
    # a newer one, and refuses a file that changed after it was pinned.
    def pin(**pins):
        (rt / "app" / "tools" / "pins.json").write_text(json.dumps({"_readme": ["test"], **pins}))

    llama, photon_old = sha(R / "gh/llama-b99990-bin-ubuntu-x64.tar.gz"), sha(R / "gh2/photon-1.2.1.jar")
    java = sha(R / "adoptium/OpenJDK21U-jre_x64_linux_hotspot_21.0.9_10.tar.gz")
    (rt / "data" / "kit.json").write_text(json.dumps({"runtimes": programs}))
    pin(
        photon={"version": "1.2.1", "sha256": photon_old},
        **{
            "llama.cpp-linux-x64": {"version": "b99990", "sha256": llama},
            "java-linux-x64": {"version": "jdk-21.0.9+10", "sha256": java},
        },
    )
    rc, out = kit("plan", root=rt)
    check(
        "pins: plan takes the pinned builds, not Photon's newest release",
        rc == 0
        and "b99990" in out
        and "1.2.1" in out
        and "1.3.0" not in out
        and "jdk-21.0.9+10" in out
        and "error" not in out,
        out,
    )
    pin(photon={"version": "1.2.1", "sha256": "0" * 64})
    rc, out = kit("plan", root=rt)
    check(
        "pins: a file that changed after it was pinned is refused",
        "changed after this version of the kit pinned it" in out and "1.3.0" not in out,
        out,
    )
    pin(
        **{
            "llama.cpp-linux-x64": {"version": "b12345", "sha256": llama},
            "java-linux-x64": {"version": "jdk-21.0.1+12"},
        }
    )
    rc, out = kit("plan", root=rt)
    check(
        "pins: a pinned build its publisher took down says so",
        "no longer publishes b12345" in out and "no longer publishes Java jdk-21.0.1+12 for linux x64" in out,
        out,
    )
    (rt / "data" / "kit.json").write_text(json.dumps({"settings": {"pin_programs": False}, "runtimes": programs}))
    rc, out = kit("plan", root=rt)
    check('pins: "pin_programs": false takes the newest builds', rc == 0 and "b99990" in out and "1.3.0" in out, out)
    # Photon opens only address databases made for its own version: when none is published for the pinned one,
    # the kit takes the Photon release that opens the newest database.
    (rt / "data" / "kit.json").write_text(json.dumps({"runtimes": programs, "maps": {"enabled": True}}))
    pin(photon={"version": "2.0.0-beta", "sha256": "0" * 64})
    rc, out = kit("plan", root=rt)
    check(
        "pins: a pinned Photon with no address database gives way to the release that opens the newest one",
        re.search(r"photon\s.*1\.3\.0", out) and "2.0.0-beta" not in out and re.search(r"geocoder\s.*1\.3/", out),
        out,
    )
    (rt / "data" / "kit.json").write_text(
        json.dumps({"runtimes": programs, "maps": {"enabled": True, "region": ["us/new-york", "us/new-jersey"]}})
    )
    rc, out = kit("plan", root=rt)
    check(
        "plan: places nearby: directions from both places' road data, one map of both, one address search",
        rc == 0
        and re.search(r"routing\s.*new-york\+new-jersey", out)
        and re.search(r"basemap\s.*New York and New Jersey", out)
        and len(re.findall(r"geocoder\s", out)) == 1,
        out,
    )

    # ./kit pins, before a release: the newest builds and their checksums
    (rt / "data" / "kit.json").write_text(json.dumps({"runtimes": programs}))
    pin(photon={"version": "1.2.1", "sha256": photon_old})
    rc, out = kit("pins", root=rt)
    pins = json.loads((rt / "app" / "tools" / "pins.json").read_text())
    check(
        "./kit pins: the newest build of each program, with its publisher's SHA-256",
        rc == 0
        and pins.get("llama.cpp-linux-x64") == {"version": "b99990", "sha256": llama}
        and pins.get("photon") == {"version": "1.3.0", "sha256": sha(R / "gh2/photon-1.3.0.jar")}
        and pins.get("java-linux-x64") == {"version": "jdk-21.0.9+10", "sha256": java}
        and "photon: 1.2.1 -> 1.3.0" in out
        and "llama.cpp-linux-x64: not pinned -> b99990" in out,
        out,
    )
    pin(photon={"version": "1.3.0", "sha256": "0" * 64})
    rc, out = kit("pins", root=rt)
    check(
        "./kit pins: a file replaced under the same version keeps its old pin, and the run fails",
        rc != 0
        and json.loads((rt / "app" / "tools" / "pins.json").read_text())["photon"]["sha256"] == "0" * 64
        and "replaced a file it had already published" in out,
        out,
    )

    (drive / "data" / ".kit" / "state.json").unlink()
    rc, out = kit("sync", "-y")
    check(
        "lost state: files on the drive are checked and kept, not downloaded again",
        rc == 0 and out.count("found ") == 5 and "downloading" not in out,
        out,
    )

    # A kit an older version set up, from before app/, downloads/ and data/: its code, kit.json (the person's) and
    # downloads all at its top, as that version's ./kit update leaves it with this version's code. Its state.json has
    # fewer keys; it calls the model Tiny, where kit.json now says Tiny-Mini; and it has a book that's switched off now,
    # which the try-it kit lists. The first command moves it all into the three folders, by renaming, and the sync after
    # that downloads none of it again: the model moves to its new folder, and the book stays.
    old = work / "old" / "TinfoilKit"
    shutil.copytree(CODE / "tools", old / "tools")
    for f in ("kit", "SETUP.command", "GUIDE.md"):
        shutil.copy(CODE / f, old)
    old_std = {"settings": {}, "models": [], "library": [{"zim": "testsurvival_en"}]}  # the standard list it came with
    (old / "site").mkdir()
    (old / "site" / "kit.json").write_text(json.dumps(old_std))
    (old / "v1-notes.txt").write_text("a file the older version's update installed")
    (old / "my-notes.txt").write_text("the person's own")
    (old / "models" / "Tiny").mkdir(parents=True)
    (old / "library").mkdir()
    shutil.copy(R / "hf/tiny/Tiny-Q4_K_M.gguf", old / "models" / "Tiny")
    for z in ("testmed_en_all_maxi_2026-01.zim", "testsurvival_en_2026-02.zim"):
        shutil.copy(R / "zim" / z, old / "library")
    (old / "logs").mkdir()
    (old / "logs" / "sync-2025-12-01.log").write_text("an older sync\n")
    (old / ".kit" / "downloads").mkdir(parents=True)
    (old / ".kit" / "downloads" / "photon.tar.bz2.partial").write_bytes(b"part")
    (old / ".kit" / "update").mkdir()
    (old / ".kit" / "update" / "kit").write_text("an update that stopped partway")

    def had(version, dest, *names):
        return {
            "version": version,
            "dest": dest,
            "files": {n: {"size": (old / dest / n).stat().st_size, "sha256": sha(old / dest / n)} for n in names},
        }

    (old / ".kit" / "state.json").write_text(
        json.dumps(
            {
                "version": 1,
                "last_sync": "2026-01-01T00:00:00",
                "items": {
                    "models/Tiny": had("1", "models/Tiny", "Tiny-Q4_K_M.gguf"),
                    "library/testmed_en_all_maxi": had("2026-01", "library", "testmed_en_all_maxi_2026-01.zim"),
                    "library/testsurvival_en": had("2026-02", "library", "testsurvival_en_2026-02.zim"),
                },
                "kit_files": ["GUIDE.md", "SETUP.command", "kit", "site/kit.json", "tools/pins.json", "v1-notes.txt"],
                "partials": {".kit/downloads/photon.tar.bz2.partial": {"item": "maps/geocoder", "tag": "1.3"}},
            }
        )
    )
    mine = {
        "settings": dict(cfg["settings"]),
        "models": [
            {"id": "Tiny-Mini", "type": "hf", "repo": "test/Tiny-GGUF", "files": ["*-Q4_K_M.gguf"], "priority": 1}
        ],
        "library": [{"zim": "testmed_en_all_maxi", "enabled": False, "starter": True}, {"zim": "testsurvival_en"}],
    }
    (old / "kit.json").write_text(json.dumps(mine))
    # From a copy of the program elsewhere, which KIT_CODE tells where the code is, as SETUP-Windows.bat runs it:
    # Windows won't move the folder of a program that's running.
    elsewhere = work / "elsewhere" / PROGRAM.name
    elsewhere.parent.mkdir()
    shutil.copy2(PROGRAM, elsewhere)
    p = subprocess.run(
        [str(elsewhere), "--root", str(old), "layout"],
        env={**env, "KIT_CODE": str(old)},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )
    rc, out = p.returncode, p.stdout + p.stderr
    top = sorted(f.name for f in old.iterdir())
    st = json.loads((old / "data" / ".kit" / "state.json").read_text())
    check(
        "an older kit moves into app, downloads and data, by renaming: its code, downloads, kit.json, logs and records; "
        "an update that stopped partway goes, and a file of the person's at its top stays",
        rc == 0
        and top == [*TOP, "app", "data", "downloads", "my-notes.txt"]
        and (old / "app" / "tools" / "pins.json").is_file()
        and (old / "app" / "SETUP.command").is_file()
        and (old / "app" / "v1-notes.txt").is_file()
        and json.loads((old / "data" / "kit.json").read_text()) == mine
        and json.loads((old / "app" / "kit.json").read_text()) == old_std
        and json.loads((old / "data" / ".kit" / "kit.base.json").read_text()) == old_std
        and (old / "downloads" / "models" / "Tiny" / "Tiny-Q4_K_M.gguf").is_file()
        and len(list((old / "downloads" / "library").glob("*.zim"))) == 2
        and (old / "downloads" / ".partial" / "photon.tar.bz2.partial").read_bytes() == b"part"
        and (old / "data" / "logs" / "sync-2025-12-01.log").is_file()
        and not (old / "data" / ".kit" / "update").exists()
        and "kit_files" not in st
        and list(st["partials"]) == [".partial/photon.tar.bz2.partial"]
        and "Nothing downloads again" in out,
        out + str(top),
    )
    rc, out = kit("layout", root=old)
    check("kit layout on a kit that's laid out already: does nothing, and says nothing", rc == 0 and out == "", out)
    p = subprocess.run(
        [str(PROGRAM), "--root", str(old), "region", "--find", "andorra"],
        env={**env, "KIT_CODE": str(old)},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )
    check(
        "a KIT_CODE left set doesn't send the kit's own program, in its tools folder, to where the code was",
        p.returncode == 0 and "andorra" in p.stdout,
        p.stdout + p.stderr,
    )
    served()
    rc, out = kit("sync", "-y", root=old)
    sent = served()
    st = json.loads((old / "data" / ".kit" / "state.json").read_text())
    check(
        "a kit an older version set up: nothing downloads again, a renamed model moves to its new folder, and a book "
        "that's switched off stays",
        rc == 0
        and not sent
        and "moved it here from models/Tiny" in out
        and (old / "downloads" / "models/Tiny-Mini/Tiny-Q4_K_M.gguf").exists()
        and not (old / "downloads" / "models/Tiny").exists()
        and sorted(st["items"]) == ["library/testmed_en_all_maxi", "library/testsurvival_en", "models/Tiny-Mini"]
        and (old / "downloads" / "library/testmed_en_all_maxi_2026-01.zim").exists(),
        out + str(sent),
    )

    # The app folder can be deleted any time for a new version's, and downloads/ and data/ stay as they are. The new
    # version's changes to the standard list go into the person's kit.json, and their own choices stay.
    on_drive = sorted(p.relative_to(old).as_posix() for p in (old / "downloads").rglob("*"))
    shutil.rmtree(old / "app")
    new_kit(old)
    v2_std = {
        "settings": {"context_size": 4096},
        "models": [],
        "library": [{"zim": "testsurvival_en"}, {"zim": "new_en"}],
    }
    (old / "app" / "kit.json").write_text(json.dumps(v2_std))
    rc, out = kit("status", root=old)
    now = json.loads((old / "data" / "kit.json").read_text())
    check(
        "a new version's app folder in place of the old one: downloads stay as they are, and kit.json gets the new "
        "version's changes and keeps the person's",
        rc == 0
        and sorted(p.relative_to(old).as_posix() for p in (old / "downloads").rglob("*")) == on_drive
        and now["settings"] == {"context_size": 4096, **cfg["settings"]}
        and now["models"] == mine["models"]
        and [(z["zim"], z.get("enabled", True)) for z in now["library"]]
        == [("testsurvival_en", True), ("new_en", True), ("testmed_en_all_maxi", False)],
        out + json.dumps(now),
    )

    # A new download's app folder put into a kit from before the three folders: it takes the old code's place, and
    # the kit's downloads and kit.json move into theirs.
    drop = work / "drop" / "TinfoilKit"
    shutil.copytree(CODE / "tools", drop / "tools")
    shutil.copy(CODE / "kit", drop)
    (drop / "site").mkdir()
    (drop / "site" / "kit.json").write_text(json.dumps(old_std))
    (drop / "kit.json").write_text(json.dumps(mine))
    (drop / "library").mkdir()
    (drop / "library" / "book.zim").write_text("a book")
    (drop / ".kit").mkdir()
    (drop / ".kit" / "state.json").write_text(json.dumps({"version": 1, "items": {}}))
    new_kit(drop)
    (drop / "app" / "kit.json").write_text(json.dumps(v2_std))
    rc, out = kit("status", root=drop)
    top = sorted(f.name for f in drop.iterdir())
    check(
        "an app folder put into an older kit: the old code goes, the downloads and kit.json move, and kit.json gets "
        "the new version's changes",
        rc == 0
        and top == [*TOP, "app", "data", "downloads"]
        and (drop / "app" / "kit").is_file()
        and (drop / "downloads" / "library" / "book.zim").read_text() == "a book"
        and json.loads((drop / "data" / "kit.json").read_text())["settings"]["context_size"] == 4096,
        out + str(top),
    )

    # An app folder put on its own in a folder with things of its own (the Desktop, say): that folder is never taken for
    # an older kit, and the home folder is never taken for the kit's folder at all.
    general = work / "general"
    new_kit(general)
    for d in ("bin", "models", "logs"):
        (general / d).mkdir()
    rc, out = kit("status", root=general)
    check(
        "an app folder beside folders of the person's called bin, models and logs: they stay where they are",
        rc == 0
        and all((general / d).is_dir() for d in ("bin", "models", "logs"))
        and not (general / "downloads").exists(),
        out,
    )
    rc, out = kit("status", root=general, env={**env, "HOME": str(general)})
    check(
        "the home folder is never the kit's folder: it says what to do instead",
        rc == 1 and "can't use" in out and "folder called TinfoilKit" in out,
        out,
    )
    flat = work / "flat"  # GitHub's Download ZIP: the code at its top, never set up
    shutil.copytree(CODE / "tools", flat / "tools")
    shutil.copy(CODE / "kit", flat)
    shutil.copy(CODE / "kit.json", flat)
    for d in ("models", "maps"):
        (flat / d).mkdir()
    rc, out = kit("status", root=flat)
    check(
        "a fresh download with its code at its top, beside folders of the person's called models and maps: only the "
        "code moves, into app, and the folders stay",
        rc == 0
        and (flat / "app" / "tools" / "pins.json").is_file()
        and (flat / "data" / "kit.json").is_file()
        and all((flat / d).is_dir() for d in ("models", "maps"))
        and not (flat / "downloads").exists(),
        out,
    )
    whole = work / "whole"  # all of a release's code at its top: every part of it is code, so nothing stays beside app
    whole.mkdir()
    tar = shutil.which("git") and subprocess.run(["git", "-C", str(CODE), "archive", "HEAD"], capture_output=True)
    if tar and tar.returncode == 0:  # not in CI's bash 3.2 container, which has no git
        subprocess.run(["tar", "-x", "-C", str(whole)], input=tar.stdout, check=True)
        shutil.rmtree(whole / "tools")  # this code, not the last commit's
        shutil.copytree(CODE / "tools", whole / "tools", ignore=shutil.ignore_patterns("__pycache__"))
        rc, out = kit("status", root=whole)
        left = sorted(p.name for p in whole.iterdir())
        check(
            "all of a release's code at a folder's top moves into app, so the folder holds just the kit's folders",
            rc == 0 and left == ["app", "data"],
            f"{left}\n{out}",
        )

    # Months later. Plant leftovers an interrupted sync could have left behind:
    # a book download from an older edition, a model download of the old file under the same name,
    # and a download for a book that's switched off (kept, in case it's switched back on).
    old_book = drive / "downloads" / "library/testsurvival_en_2025-11.zim.partial"
    old_book.write_bytes(os.urandom(1000))
    stale_model = drive / "downloads" / "models/Tiny/Tiny-Q4_K_M.gguf.partial"
    stale_model.write_bytes(os.urandom(100_000))
    off_book = drive / "downloads" / "library/disabled_one_en_2026-01.zim.partial"
    off_book.write_bytes(os.urandom(1000))
    # not tracked, and bigger than the real file
    too_big = drive / "downloads" / "library/testsurvival_en_2026-05.zim.partial"
    too_big.write_bytes(os.urandom(70_000))
    st = state()
    st["partials"] = {
        "library/testsurvival_en_2025-11.zim.partial": {"item": "library/testsurvival_en", "tag": "2025-11|999"},
        "models/Tiny/Tiny-Q4_K_M.gguf.partial": {"item": "models/Tiny", "tag": sha(R / "hf/tiny/Tiny-Q4_K_M.gguf")},
        "library/disabled_one_en_2026-01.zim.partial": {"item": "library/disabled_one_en", "tag": "2026-01|1000"},
    }
    (drive / "data" / ".kit" / "state.json").write_text(json.dumps(st))
    (R / "STATE_V2").touch()
    (drive / "data" / ".kit/cache/kiwix-catalog.xml").unlink()
    # A book with refresh_days keeps the edition it has until that one is so many days old.
    survival = next(z for z in cfg["library"] if z["zim"] == "testsurvival_en")
    survival["refresh_days"] = 30
    write_cfg()
    rc, out = kit("plan")
    line = next((x for x in out.splitlines() if "testsurvival_en" in x), "")
    check(
        "refresh_days: a new edition of a book installed this month waits, and the plan says how to get it now",
        line.split()[:1] == ["later"] and "2026-02   (2026-05 waits until" in line and "./kit sync --only NAME" in out,
        out,
    )
    rc, out = kit("plan", "--only", "testsurvival")
    check("refresh_days: naming it in --only gets the new edition now", "UPDATE  testsurvival_en" in out, out)
    book = drive / "downloads" / "library/testsurvival_en_2026-02.zim"
    book.rename(book.with_suffix(".gone"))
    rc, out = kit("plan")
    check("refresh_days: a book whose file is missing doesn't wait", "UPDATE  testsurvival_en" in out, out)
    book.with_suffix(".gone").rename(book)
    st = state()
    st["items"]["library/testsurvival_en"]["updated"] = "2025-12-01T09:00:00"
    (drive / "data" / ".kit" / "state.json").write_text(json.dumps(st))
    rc, out = kit("plan")
    check("refresh_days: once the edition is that old, the new one downloads", "UPDATE  testsurvival_en" in out, out)
    del survival["refresh_days"]
    write_cfg()
    rc, out = kit("sync", "-y")
    check(
        "update: new editions installed",
        rc == 0
        and same("library/testsurvival_en_2026-05.zim", "zim/testsurvival_en_2026-05.zim")
        and same("models/Tiny/Tiny-Q4_K_M.gguf", "hf/tiny_v2/Tiny-Q4_K_M.gguf"),
        out,
    )
    check(
        "update: old edition removed", not (drive / "downloads" / "library/testsurvival_en_2026-02.zim").exists(), out
    )
    check("update: a partial download of an older edition is deleted", not old_book.exists(), out)
    check("update: a partial download of an older file isn't resumed into the new one", "discarding" in out, out)
    check("update: a switched-off book's partial download is kept", off_book.exists())
    check("update: a partial download bigger than the new file starts over", out.count("discarding") == 2, out)
    check(
        "update: leftovers are forgotten",
        sorted(state().get("partials", {})) == ["library/disabled_one_en_2026-01.zim.partial"],
        str(state().get("partials")),
    )

    # what macOS writes beside a file on exFAT
    finder = drive / "downloads" / "library/._disabled_one_en_2026-01.zim.partial"
    finder.write_bytes(b"\0\5\26\7")
    rc, out = kit("status")
    finder.unlink()
    check(
        "status, including the switched-off book's unfinished download, but not macOS's ._ file beside it",
        rc == 0
        and "Last complete sync" in out
        and "library/disabled_one_en_2026-01.zim.partial" in out
        and "._disabled" not in out,
        out,
    )

    # How much room the kit needs, before anything is looked up online: the builder's sizes for what's switched on.
    (drive / "app" / "tools" / "sources.json").write_text(
        json.dumps(
            {
                "sources": [
                    {"id": "Tiny", "bytes": 2 * 10**9},
                    {"id": "Two", "bytes": 3 * 10**9},
                    {"id": "testmed_en_all_maxi", "bytes": 4 * 10**9},
                    {"id": "disabled_one_en", "bytes": 100 * 10**9},
                    {"id": "maps", "bytes": 20 * 10**9},
                ]
            }
        )
    )
    rc, out = kit("estimate")
    check(
        "estimate: the builder's sizes of what's switched on, plus 1 GB of programs",
        rc == 0 and out.strip() == "10",
        out,
    )
    (drive / "app" / "tools" / "sources.json").unlink()

    # On the computer's own disk (the one with the home folder) the kit leaves more room free than on a drive.
    (work / "home").mkdir()
    cfg["settings"]["keep_free_gb_this_computer"] = 10**9  # more than any disk has
    write_cfg()
    rc, out = kit("plan", env={**env, "HOME": str(work / "home")})
    check(
        "on the computer's own disk, the kit keeps keep_free_gb_this_computer free",
        "WARNING: that leaves less" in out,
        out,
    )
    shm = Path("/dev/shm")
    if shm.is_dir() and shm.stat().st_dev != work.stat().st_dev:
        rc, out = kit("plan", env={**env, "HOME": str(shm)})
        check("on a drive, keep_free_gb_this_computer doesn't apply", rc == 0 and "WARNING" not in out, out)
    cfg["settings"]["keep_free_gb_this_computer"] = 0.001
    write_cfg()

    junk = [
        drive / "downloads" / "library" / "._junk.zim",
        drive / "downloads" / "models" / "Tiny" / "._Tiny-Q4_K_M.gguf",
    ]
    for j in junk:
        j.parent.mkdir(parents=True, exist_ok=True)
        j.write_bytes(b"\0\5\26\7")  # macOS's metadata files on exFAT start like this
    books = len(list((drive / "downloads" / "library").glob("[!.]*.zim")))
    rc, out = kit("test")
    check(
        "test: clears macOS's ._ files before starting the servers",
        not any(j.exists() for j in junk) and f"library files present: {books} .zim files" in out,
        out,
    )

    nowhere = "http://127.0.0.1:9"  # nothing listens there
    off = {**env, "KIT_HF": nowhere, "KIT_KIWIX_CATALOG": nowhere + "/catalog"}
    (drive / "data" / ".kit/cache/kiwix-catalog.xml").unlink()
    rc, out = kit("sync", "-y", env=off)
    check(
        "offline: sync stops with one clear message",
        rc == 1
        and "Check that this computer is online" in out
        and "Problems" not in out
        and out.count("Kiwix catalog") <= 3,
        out,
    )
    (drive / "data" / ".kit/cache").mkdir(exist_ok=True)
    portal = env["KIT_KIWIX_CATALOG"].replace("/catalog/v2/entries?count=-1", "/wifi-sign-in")
    rc, out = kit("plan", env={**off, "KIT_KIWIX_CATALOG": portal})
    check(
        "Wi-Fi sign-in page: plan says so and nothing is cached",
        rc == 1 and not (drive / "data" / ".kit/cache/kiwix-catalog.xml").exists(),
        out,
    )

    # ./kit remove: what an item downloaded goes, for its space, and it's switched off so sync doesn't get it again.
    rc, out = kit("remove", "nothing-such")
    check(
        "remove: a name the kit doesn't have changes nothing",
        rc == 2 and "Nothing in the kit is called nothing-such" in out,
        out,
    )
    before = (drive / "data" / "kit.json").read_text()
    rc, out = kit("remove", "Two")
    check(
        "remove: without a keyboard or --yes it lists what it would delete, and deletes nothing",
        rc == 1
        and "This deletes:" in out
        and "Two" in out
        and "--yes" in out
        and (drive / "downloads" / "models/Two").is_dir()
        and (drive / "data" / "kit.json").read_text() == before,
        out,
    )
    rc, out = kit("remove", "Two", "--yes")
    now = json.loads((drive / "data" / "kit.json").read_text())
    check(
        "remove --yes: a model's folder goes, the kit forgets it, and it's switched off in kit.json",
        rc == 0
        and "Freed" in out
        and not (drive / "downloads" / "models/Two").exists()
        and "models/Two" not in state()["items"]
        and [m.get("enabled", True) for m in now["models"] if m["id"] == "Two"] == [False]
        and now["settings"].get("picked") is True
        and "| Two |" not in (drive / "downloads" / "INVENTORY.md").read_text(),
        out,
    )
    cfg["library"][1]["enabled"] = False  # testsurvival_en, switched off by hand: still on the drive
    write_cfg()
    rc, out = kit("plan")
    rc2, out2 = kit("status")
    check(
        "plan and status say what's switched off but still in the kit, and how to free it",
        "Still in the kit, switched off: testsurvival_en" in out
        and "./kit remove" in out
        and "Still in the kit, switched off: testsurvival_en" in out2,
        out + out2,
    )
    rc, out = kit("remove", "testsurvival", "--yes")
    check(
        "remove: a book (by its name up to the first underscore) goes, and the books beside it stay",
        rc == 0
        and not list((drive / "downloads" / "library").glob("testsurvival_en_*"))
        and (drive / "downloads" / "library/testmed_en_all_maxi_2026-01.zim").is_file()
        and "library/testsurvival_en" not in state()["items"],
        out,
    )
    rc, out = kit("remove", "disabled_one_en", "--yes")
    check(
        "remove: an unfinished download goes too",
        rc == 0
        and "unfinished download" in out
        and not list((drive / "downloads" / "library").glob("disabled_one_en_*"))
        and not state().get("partials"),
        out,
    )
    cfg["library"].append({"zim": "never_got_en"})
    write_cfg()
    rc, out = kit("remove", "never_got_en")
    now = json.loads((drive / "data" / "kit.json").read_text())
    check(
        "remove: something with nothing downloaded is just switched off",
        rc == 0
        and "nothing to delete" in out
        and [z.get("enabled", True) for z in now["library"] if z["zim"] == "never_got_en"] == [False],
        out,
    )

    # Ed25519 (RFC 8032's reference code, section 6), just enough to sign the test releases below the way
    # .github/release.sh signs real ones with ssh-keygen. (The kit's own checks of signatures are its Go tests.)
    ED_P = 2**255 - 19
    ED_L = 2**252 + 27742317777372353535851937790883648493
    ED_D = -121665 * pow(121666, ED_P - 2, ED_P) % ED_P

    def ed_add(p, q):
        a, b = (p[1] - p[0]) * (q[1] - q[0]) % ED_P, (p[1] + p[0]) * (q[1] + q[0]) % ED_P
        c, d = 2 * p[3] * q[3] * ED_D % ED_P, 2 * p[2] * q[2] % ED_P
        e, f, g, h = b - a, d - c, d + c, b + a
        return e * f, g * h, f * g, e * h

    def ed_mul(s, p):
        q = (0, 1, 1, 0)
        while s:
            if s & 1:
                q = ed_add(q, p)
            p, s = ed_add(p, p), s >> 1
        return q

    def ed_base():
        y = 4 * pow(5, ED_P - 2, ED_P) % ED_P
        x2 = (y * y - 1) * pow(ED_D * y * y + 1, ED_P - 2, ED_P) % ED_P
        x = pow(x2, (ED_P + 3) // 8, ED_P)
        if (x * x - x2) % ED_P:
            x = x * pow(2, (ED_P - 1) // 4, ED_P) % ED_P
        x = ED_P - x if x & 1 else x
        return x, y, 1, x * y % ED_P

    ED_B = ed_base()

    def ssh_str(b):
        return len(b).to_bytes(4, "big") + b

    def ssh_sign(seed, data, namespace=b"tinfoilkit-release"):
        """Sign data the way ssh-keygen -Y sign does, with the Ed25519 key made from seed. Returns the signature file and
        the key's line for tools/release-signers."""
        h = hashlib.sha512(seed).digest()
        a = int.from_bytes(h[:32], "little") & (2**254 - 8) | 2**254

        def enc(pt):
            zi = pow(pt[2], ED_P - 2, ED_P)
            return ((pt[1] * zi % ED_P) | (pt[0] * zi % ED_P & 1) << 255).to_bytes(32, "little")

        pub = enc(ed_mul(a, ED_B))
        msg = (
            b"SSHSIG" + ssh_str(namespace) + ssh_str(b"") + ssh_str(b"sha512") + ssh_str(hashlib.sha512(data).digest())
        )
        r = int.from_bytes(hashlib.sha512(h[32:] + msg).digest(), "little") % ED_L
        big_r = enc(ed_mul(r, ED_B))
        sig = big_r + ((r + int.from_bytes(hashlib.sha512(big_r + pub + msg).digest(), "little") * a) % ED_L).to_bytes(
            32, "little"
        )
        key = ssh_str(b"ssh-ed25519") + ssh_str(pub)
        blob = (
            b"SSHSIG\0\0\0\1"
            + ssh_str(key)
            + ssh_str(namespace)
            + ssh_str(b"")
            + ssh_str(b"sha512")
            + ssh_str(ssh_str(b"ssh-ed25519") + ssh_str(sig))
        )
        b64 = base64.b64encode(blob).decode()
        armored = "\n".join(
            [
                "-----BEGIN SSH SIGNATURE-----",
                *(b64[i : i + 70] for i in range(0, len(b64), 70)),
                "-----END SSH SIGNATURE-----",
                "",
            ]
        )
        return (
            armored.encode(),
            f'tinfoilkit-release namespaces="tinfoilkit-release" ssh-ed25519 {base64.b64encode(key).decode()} test\n',
        )

    signer = ssh_sign(b"k" * 32, b"")[1]  # the kit's release key

    # ./kit update: a kit on the drive, its kit.json (data/kit.json) changed by its owner, and releases of the kit's code
    # published on the mock GitHub. app/kit.json is the standard list the kit's current version came with.
    up = work / "update" / "TinfoilKit"
    code = {
        rel: (CODE / rel).read_bytes()
        for rel in ("kit", "SETUP.command", "Open Tinfoil Kit.command", "UNINSTALL.command")
    }
    code.update(
        {
            p.relative_to(CODE).as_posix(): p.read_bytes()
            for p in (CODE / "tools").rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        }
    )
    code["tools/release-signers"] = signer.encode()  # this kit's key, and the one each test release brings
    for rel, data in code.items():
        (up / "app" / rel).parent.mkdir(parents=True, exist_ok=True)
        (up / "app" / rel).write_bytes(data)
        if rel.startswith("tools/tinfoilkit-"):
            (up / "app" / rel).chmod(0o755)
    base_cfg = {
        "settings": {"default_model": "Tiny", "context_size": 8192},
        "models": [
            {"id": "Tiny", "repo": "test/Tiny-GGUF", "files": ["*-Q4_K_M.gguf"]},
            {"id": "Two", "repo": "test/Two-GGUF", "files": ["*-Q4_K_M.gguf"]},
        ],
        "library": [{"zim": "testmed_en_all_maxi"}, {"zim": "gone_en"}, {"zim": "testsurvival_en"}],
    }
    (up / "app" / "site").mkdir()
    (up / "app" / "site" / "kit.json").write_text(json.dumps(base_cfg, indent=1))
    (up / "app" / "kit.json").write_text(json.dumps(base_cfg, indent=1))
    (up / "downloads" / "library").mkdir(parents=True)
    (up / "downloads" / "library" / "book.zim").write_text("a book")
    (up / "data" / "notes").mkdir(parents=True)
    (up / "data" / "notes" / "plan.txt").write_text("meet at the school")
    mine = json.loads(json.dumps(base_cfg))
    mine["settings"]["default_model"] = "Two"
    mine["library"][0]["enabled"] = False  # switched off
    mine["library"][1]["enabled"] = True  # switched on, then dropped by the new version
    mine["library"].append({"zim": "mine_en"})  # added by hand
    mine_text = json.dumps(mine, indent=1)
    (up / "data" / "kit.json").write_text(mine_text)
    v2_cfg = json.loads(json.dumps(base_cfg))
    v2_cfg["settings"]["context_size"] = 16384
    v2_cfg["models"][1]["note"] = "new in v2"
    v2_cfg["library"] = [z for z in v2_cfg["library"] if z["zim"] != "gone_en"] + [{"zim": "new_en"}]

    def publish(tag, files, links=(), body="", seed=b"k" * 32, signed=True, changed=False):
        """A release on the mock GitHub as .github/release.sh makes one: everything under one top folder, and its
        signature beside it. changed: the archive is swapped for another after it was signed. Returns the archive's
        name in the mock's gh folder."""
        (R / "gh").mkdir(exist_ok=True)
        name = f"kit-{tag}-{len(list((R / 'gh').glob('kit-*.gz')))}.tar.gz"

        def pack(files):
            with tarfile.open(R / "gh" / name, "w:gz") as tf:
                for rel, data in files.items():
                    info = tarfile.TarInfo(f"tinfoilkit-{tag}/{rel}")
                    info.size, info.mode = (
                        len(data),
                        0o755
                        if rel in ("kit", "SETUP.command") or rel.endswith(".sh") or rel.startswith("tools/tinfoilkit-")
                        else 0o644,
                    )
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
        (R / "kit").mkdir(exist_ok=True)  # GitHub's own source archive is listed too, and must never be used
        (R / "kit" / "release.json").write_text(
            json.dumps({"tag_name": tag, "assets": assets, "body": body, "tarball_url": f"{base}/gh/{name}"})
        )
        return name

    def kit_tty(answer, *args):
        """./kit at a keyboard, where someone types answer."""
        import pty

        keyboard, tty = pty.openpty()
        os.write(keyboard, answer.encode())
        try:
            p = subprocess.run(
                kit_cmd(up / "app", up, *args), env=env, stdin=tty, capture_output=True, text=True, timeout=180
            )
        finally:
            os.close(keyboard)
            os.close(tty)
        return p.returncode, p.stdout + p.stderr

    def kit_json(cfg):
        text = json.dumps(cfg, indent=4).encode()
        return {"kit.json": text, "site/kit.json": text}

    rc, out = kit("update", root=up)
    check(
        "kit update: no release published yet: says so, changes nothing",
        rc == 0 and "No version of the kit is published" in out,
        out,
    )
    rc, out = kit("update", root=up, env={**env, "KIT_GITHUB_API": "http://127.0.0.1:9"})
    check("kit update: offline: says so", rc == 1 and "Couldn't reach GitHub" in out, out)
    good = {**code, **kit_json(v2_cfg), "docs/v2.txt": b"v2"}
    # A copy from GitHub carries its commit in tools/commit, and one taken from the main branch can be newer than the
    # release.
    sha = "a" * 40
    (up / "app" / "tools" / "commit").write_text(sha + "\n")
    (R / "kit" / "compare").mkdir(parents=True)
    publish("v1.9", good)
    (R / "kit" / "compare" / f"v1.9...{sha}").write_text('{"status": "ahead"}')
    rc, out = kit("update", root=up)
    check(
        "kit update: a copy newer than the latest release stays",
        rc == 0 and "newer than its latest release (v1.9)" in out and not (up / "app" / "docs").exists(),
        out,
    )
    (R / "kit" / "compare" / f"v1.9...{sha}").write_text('{"status": "identical"}')
    rc, out = kit("update", root=up)
    check(
        "kit update: a copy of the latest release notes its version, installs nothing",
        rc == 0
        and "newest version (v1.9)" in out
        and not (up / "app" / "docs").exists()
        and json.loads((up / "data" / ".kit/state.json").read_text())["kit_version"] == "v1.9",
        out,
    )
    # Each with the reason it gives, so a check that stops working can't hide behind a later one.
    bad = {
        "a link": (dict(files=good, links=[("tools/evil", "pins.json")]), "a link in it"),
        "a path outside its folder": (dict(files={**good, "../../escaped.txt": b"x"}), "unexpected path"),
        "a missing file": (
            dict(files={k: v for k, v in good.items() if k != "tools/portal.html"}),
            "missing tools/portal.html",
        ),
        "a program this computer can't run": (
            dict(files={**good, f"tools/{PROGRAM.name}": b"\x7fELF broken"}),
            "won't run",
        ),
        "no signature": (dict(files=good, signed=False), "isn't signed (the release has no tinfoilkit-v2.tar.gz"),
        "another key's signature": (dict(files=good, seed=b"o" * 32), "isn't signed with the kit's release key"),
        "an archive swapped after it was signed": (
            dict(files=good, changed=True),
            "isn't signed with the kit's release key",
        ),
        "no key to check the next one": (
            dict(files={**good, "tools/release-signers": b"# none\n"}),
            "no release key (tools/release-signers)",
        ),
    }
    for what, (release, why) in bad.items():
        publish("v2", **release)
        rc, out = kit("update", root=up)
        check(
            f"kit update: a release with {what} is refused and nothing changes",
            rc == 1
            and "couldn't install version v2" in out
            and why in out
            and not (up / "app" / "docs").exists()
            and not (work / "escaped.txt").exists()
            and (up / "data" / "kit.json").read_text() == mine_text,
            out,
        )
    (up / "app" / "tools/release-signers").write_text("# none\n")
    publish("v2", good)
    rc, out = kit("update", root=up)
    check(
        "kit update: a copy with no release key refuses every release",
        rc == 1 and "no release key to check it with" in out and not (up / "app" / "docs").exists(),
        out,
    )
    (up / "app" / "tools/release-signers").write_text(signer)
    publish("v2", good, body="Faster answers.\nBetter maps.")
    (up / "data" / "kit.json").write_text(mine_text.replace('"Two"', '"Two",', 1))
    rc, out = kit("update", root=up)
    check(
        "kit update: a typo in kit.json stops it before anything changes",
        rc == 1 and "syntax error on line" in out and not (up / "app" / "docs").exists(),
        out,
    )
    (up / "data" / "kit.json").write_text(mine_text)
    rc, out = kit_tty("n\n", "update")
    check(
        "kit update: at a keyboard it shows what's new and asks first, and no keeps this version",
        rc == 0
        and "Better maps." in out
        and "Install it now?" in out
        and "This version stays" in out
        and not (up / "app" / "docs").exists()
        and (up / "data" / "kit.json").read_text() == mine_text,
        out,
    )
    rc, out = kit("update", root=up)
    merged = json.loads((up / "data" / "kit.json").read_text())
    check(
        "kit update: installs the release in the app folder, shows what's new, and leaves downloads and data alone",
        rc == 3
        and "Installed version v2" in out
        and "Better maps." in out
        and (up / "app" / "docs/v2.txt").exists()
        and json.loads((up / "data" / ".kit/state.json").read_text())["kit_version"] == "v2"
        and sorted(f.name for f in up.iterdir()) == [*TOP, "app", "data", "downloads"]
        and (up / "downloads" / "library" / "book.zim").read_text() == "a book"
        and (up / "data" / "notes" / "plan.txt").read_text() == "meet at the school",
        out,
    )
    check(
        "kit update: kit.json keeps this drive's choices and gets the release's changes",
        merged["settings"] == {"default_model": "Two", "context_size": 16384}
        and merged["models"][1]["note"] == "new in v2"
        and [(z["zim"], z.get("enabled", True)) for z in merged["library"]]
        == [("testmed_en_all_maxi", False), ("testsurvival_en", True), ("new_en", True), ("mine_en", True)],
        json.dumps(merged),
    )
    rc, out = kit("update", root=up)
    check("kit update: already the newest", rc == 0 and "This is the newest version (v2)" in out, out)
    v3_cfg = {**v2_cfg, "settings": {**v2_cfg["settings"], "context_size": 32768}}
    publish("v3", {**code, **kit_json(v3_cfg), "docs/v3.txt": b"v3"})
    rc, out = kit_tty("n\n", "update", "--yes")
    merged = json.loads((up / "data" / "kit.json").read_text())
    check(
        "kit update: --yes doesn't ask, and the next release removes files the last one installed and still keeps the choices",
        rc == 3
        and "Install it now?" not in out
        and not (up / "app" / "docs/v2.txt").exists()
        and (up / "app" / "docs/v3.txt").exists()
        and merged["settings"] == {"default_model": "Two", "context_size": 32768}
        and merged["library"][-1] == {"zim": "mine_en"},
        out,
    )
    (up / "data" / "kit.json").write_text((up / "app" / "kit.json").read_text())
    v4_cfg = {**v3_cfg, "settings": {**v3_cfg["settings"], "context_size": 65536}}
    publish("v4", {**code, **kit_json(v4_cfg)})
    rc, out = kit("update", root=up)
    check(
        "kit update: a kit.json nobody changed becomes the release's, byte for byte",
        rc == 3 and (up / "data" / "kit.json").read_bytes() == json.dumps(v4_cfg, indent=4).encode(),
        out,
    )
    if shutil.which("ssh-keygen"):  # a release signed by OpenSSH's ssh-keygen, as .github/release.sh signs them
        key = work / "release-key"
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], stdin=subprocess.DEVNULL, check=True
        )
        openssh = (
            'tinfoilkit-release namespaces="tinfoilkit-release" '
            + " ".join((work / "release-key.pub").read_text().split()[:2])
            + "\n"
        )
        (up / "app" / "tools" / "release-signers").write_text(openssh)
        name = publish("v5", {**code, **kit_json(v4_cfg), "tools/release-signers": openssh.encode()})
        (R / "gh" / f"{name}.sig").unlink()
        subprocess.run(
            ["ssh-keygen", "-q", "-Y", "sign", "-f", str(key), "-n", "tinfoilkit-release", str(R / "gh" / name)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=True,
        )
        rc, out = kit("update", root=up)
        check(
            "kit update: a release ssh-keygen signed, as .github/release.sh signs them, installs",
            rc == 3 and "Installed version v5" in out,
            out,
        )
    elif os.environ.get("CI"):
        check("kit update: ssh-keygen is here to sign a release with", False)
    else:
        print("skipped: a release ssh-keygen signed (no ssh-keygen here)")
    checkout = work / "checkout" / "kit"  # the repository's kit/
    shutil.copytree(CODE / "tools", checkout / "tools")
    shutil.copy(CODE / "kit.json", checkout)
    (checkout.parent / ".git").mkdir(exist_ok=True)
    rc, out = kit("update", root=checkout)
    check(
        "kit update: leaves a git checkout to git, and the checkout's kit.json as it is",
        rc == 0
        and "git pull" in out
        and (checkout / "kit.json").read_text() == (CODE / "kit.json").read_text()
        and (checkout / "data" / "kit.json").is_file(),
        out,
    )

    # SETUP.command's choices, with a stand-in ./kit that exits as told. Its update rewrites SETUP.command in
    # place, the hard case for bash, which reads a script as it goes. Its space says what SPACE does (all of it, the
    # essentials, GB free, GB in all, GB all of it needs, GB the essentials need, GB worth leaving free), or for a
    # drive what SPACE_DRIVE does, and its estimate says 8 GB, or with --rest 380 GB in about 4 hours (TOOK, if set,
    # says how long instead: "" when it couldn't time the connection). Calls go in the kit's data/calls.log
    # (essentials on as essentials-on, starter off as starter-off), all but space, estimate and --help (SETUP's check
    # that the kit's program runs), and every call goes in data/args.log with its options.
    def space(*v):
        return "\t".join(map(str, v))

    roomy = space("fits", "fits", 900, 1000, 400, 100, 50)
    stand_in = """#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"; KIT="$DIR"    # as the real one finds the kit folder
case "$(basename "$DIR")" in app) [ -e "$DIR/.git" ] || KIT="$(dirname "$DIR")";; esac
case "$1" in drives|kits|place|region|pick) exec "@PROGRAM@" --root "$KIT" "$@";; esac    # the real ones
[ -f "$KIT/data/kit.json" ] || { mkdir -p "$KIT/data"; cp "$DIR/kit.json" "$KIT/data/kit.json"; }    # as the real one does
cd "$KIT" || exit 1
echo "$*" >> data/args.log
c="$1"; case " $* " in *" --essentials "*) c="$1-essentials";; esac
case "$1" in essentials|starter) c="$1-$2";; esac
case "$1" in space|estimate|--help) ;; *) echo "kit $c" >> data/calls.log;; esac
took="about 4 hours at this connection's speed (24.0 MB/s)"    # (an apostrophe in a case breaks bash's parse)
case "$1" in
  space) case "$2" in "${KIT_DRIVES:-/nowhere}"/*) echo "${SPACE_DRIVE:-$SPACE}";; *) echo "$SPACE";; esac;;
  estimate) case " $* " in *" --rest "*) printf '%s\t%s\n' 380 "${TOOK-$took}";;
                                     *) echo 8;; esac;;
  essentials|starter) python3 - "$1" "$2" <<'PY'
import json, sys
c = json.load(open("data/kit.json"))
c.setdefault("settings", {})[sys.argv[1] + "_only"] = True if sys.argv[2] == "on" else None
c["settings"] = {k: v for k, v in c["settings"].items() if v is not None}
json.dump(c, open("data/kit.json", "w"), indent=1)
PY
              ;;
  update) [ "$UPDATE" = 3 ] && sed 's/Step [$]KIT_STEP of/Step $KIT_STEP (new version) of/' "$DIR/SETUP.command" > new \\
            && cat new > "$DIR/SETUP.command" && rm new
          exit $UPDATE;;
  plan) exit $PLAN;;
  sync) mkdir -p data/logs; echo "===== sync started =====" >> data/logs/sync-2026-01-01.log
        [ $SYNC = 1 ] && printf 'Problems (everything else is done):\n  - models/Big: download failed\nRe-run ./kit sync\n' >> data/logs/sync-2026-01-01.log
        exit $SYNC;;
  test) exit $TEST;;
  share|autostart) echo "$*" >> data/home.log;;
esac""".replace("@PROGRAM@", str(PROGRAM))

    def kit_folder(path, git=False):
        """A kit as Download ZIP leaves it, its code in app/, with the stand-in ./kit. git: a git checkout at path, whose
        kit/ is its own kit folder, which this returns."""
        code = path / "kit" if git else path / "app"
        code.mkdir(parents=True)
        shutil.copy(CODE / "SETUP.command", code)
        (code / "kit").write_text(stand_in)
        (code / "kit").chmod(0o755)
        (code / "tools").mkdir()
        (code / "tools" / "pins.json").write_text("{}\n")
        (code / "GUIDE.md").write_text("guide\n")
        shutil.copy(CODE / "kit.json", code)  # the standard list: data/kit.json starts as a copy
        shutil.copy(CODE / "tools" / "sources.json", code / "tools")  # for ./kit pick --ask
        if git:  # a developer's: the website and the license beside kit/, and npm's packages and ruff's cache in both
            (code / "tools" / "commit").write_text("$Format:%H$\n")  # (what git archive fills in)
            for d in ("node_modules/prettier", ".ruff_cache/0.17.5", "kit/node_modules/prettier", "kit/.ruff_cache/0"):
                (path / d).mkdir(parents=True)
                (path / d / "index.js").write_text("")
            (path / "site" / ".next").mkdir(parents=True)
            for f in ("LICENSE", "README.md", "THIRD-PARTY.md"):
                (path / f).write_text(f + "\n")
            if shutil.which("git"):  # a real one, with a commit (not in CI's bash 3.2 container, which has no git)
                me = ["-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false"]
                for args in (["init", "-q"], ["add", "-A"], [*me, "commit", "-qm", "test"]):
                    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)
            else:
                (path / ".git").mkdir()
        return code if git else path

    setup = kit_folder(work / "setup")
    (setup / "downloads").mkdir()  # set up before, so SETUP doesn't ask where it goes
    (setup / "data" / ".kit").mkdir(parents=True)
    mine = setup / "data" / "kit.json"  # what goes in the kit: SETUP changes this one, never app/kit.json

    def run_setup(plan=0, sync=0, test=0, update=0, folder=setup, answers="\ny\nn\n\n", args=(), **env_extra):
        shutil.copy(CODE / "SETUP.command", folder / "app")
        for log in ("calls.log", "home.log", "args.log"):
            (folder / "data" / log).write_text("")
        p = subprocess.run(
            ["bash", str(folder / "app" / "SETUP.command"), *args],
            input=answers,
            capture_output=True,
            text=True,
            timeout=60,
            env={
                **os.environ,
                "PLAN": str(plan),
                "SYNC": str(sync),
                "TEST": str(test),
                "UPDATE": str(update),
                "SPACE": roomy,
                **env_extra,
            },
        )
        return p.returncode, p.stdout, (folder / "data" / "calls.log").read_text().split()[1::2]

    first = ["update", "fit", "starter-on", "plan", "sync", "test"]  # the try-it kit
    rest = ["starter-off", "essentials-off", "plan", "sync", "test"]  # the rest of the kit
    asked = ("[Y/n]", "[y/N]", "Type a number", "Press Return")
    rc, out, calls = run_setup()
    check(
        "SETUP the first time: the try-it kit, checked, then how big the rest is, how long it takes, and how to get it",
        rc == 0
        and calls == first
        and '"starter_only": true' in mine.read_text()
        and "Step 1 of 2: the kit is on" in out
        and "Step 2 of 2: a small kit to try first (about 8 GB)" in out
        and "The whole kit is about 380 GB: about 4 hours at this connection's speed (24.0 MB/s). That comes later, "
        "after you've tried this."
        in out
        and out.index("The whole kit is about 380 GB") < out.index("Start downloading?")
        and "The try-it kit works" in out
        and "Turn off Wi-Fi and try it" in out
        and "The rest of the kit is about 380 GB more: about 4 hours at this connection's speed (24.0 MB/s)" in out
        and f'run bash "{setup}/app/SETUP.command" again: it asks what you want in the kit, then gets that' in out
        and (setup / "app" / "kit.json").read_text() == (CODE / "kit.json").read_text()
        and "Open the kit now?" in out
        and "All set" not in out
        and "where should the kit go" not in out,
        out,
    )
    (setup / "data" / ".kit" / "state.json").write_text('{"items": {}, "last_sync": "2026-01-01T00:00:00"}')
    rc, out, calls = run_setup(answers="\n\ny\nn\n\n", KIT_MEMORY_MB="32768")
    c = json.loads(mine.read_text())
    check(
        "SETUP again on the try-it kit: asks the kit builder's questions, shows what it gets, and gets the rest",
        rc == 0
        and calls == ["update", "fit"] + rest
        and "Step 2 of 3: the rest of the kit" in out
        and "What goes in the kit?" in out
        and "Here's what it gets:" in out
        and "Start downloading?" in out
        and "Step 3 of 3: start everything offline" in out
        and "All set" in out
        and "starter_only" not in c["settings"]
        and c["settings"].get("picked") is True,
        out,
    )
    update_calls = ["update", "fit", "plan", "sync", "test"]
    rc, out, calls = run_setup()
    check(
        "SETUP after that: says it's an update, and how to update next time",
        rc == 0
        and "TINFOIL KIT UPDATE" in out
        and "TINFOIL KIT SETUP" not in out
        and "The kit keeps working while it downloads." in out
        and "Step 3 of 3: start everything" in out
        and "whenever you want the newest AI models" in out
        and calls == update_calls,
        out,
    )

    # A new download of SETUP, where a kit was set up before: it updates that one, without asking anything else first
    kits_home = work / "kits home"
    before = kit_folder(kits_home / "TinfoilKit")
    (before / "downloads").mkdir()
    (before / "data" / ".kit").mkdir(parents=True)
    (before / "data" / ".kit" / "state.json").write_text(
        json.dumps(
            {
                "last_sync": "2026-11-01T10:00:00",
                "items": {"library/big": {"dest": "library", "files": {"big.zim": {"size": 5 * 10**9}}}},
            }
        )
    )
    new = kit_folder(work / "kits download" / "TinfoilKit")
    p = subprocess.run(
        ["bash", str(new / "app" / "SETUP.command")],
        input="\n\ny\nn\n\n",
        capture_output=True,
        text=True,
        timeout=60,
        env={
            **os.environ,
            "HOME": str(kits_home),
            "KIT_DRIVES": str(work / "no drives"),
            "SPACE": roomy,
            "PLAN": "0",
            "SYNC": "0",
            "TEST": "0",
            "UPDATE": "0",
        },
    )
    calls = (
        (before / "data" / "calls.log").read_text().split()[1::2] if (before / "data" / "calls.log").exists() else []
    )
    check(
        "SETUP from a new download, with a kit set up before: it updates that kit, so nothing it has downloads again",
        p.returncode == 0
        and f"There's a Tinfoil Kit on this computer already: {before} (5 GB, last updated 2026-11-01)." in p.stdout
        and "TINFOIL KIT UPDATE" in p.stdout
        and "where should the kit go" not in p.stdout
        and calls == update_calls
        and not (new / "data" / "calls.log").is_file(),
        p.stdout + p.stderr,
    )
    shutil.rmtree(before / "app")  # deleted, for a new version's
    (before / "data" / "my-notes.txt").write_text("mine")
    p = subprocess.run(
        ["bash", str(new / "app" / "SETUP.command")],
        input="\n\ny\nn\n\n",
        capture_output=True,
        text=True,
        timeout=60,
        env={
            **os.environ,
            "HOME": str(kits_home),
            "KIT_DRIVES": str(work / "no drives"),
            "SPACE": roomy,
            "PLAN": "0",
            "SYNC": "0",
            "TEST": "0",
            "UPDATE": "0",
        },
    )
    calls = (before / "data" / "calls.log").read_text().split()[1::2]
    check(
        "SETUP from a new download, with a kit whose app folder was deleted: puts its own app folder there and "
        "updates that kit, whose downloads and data stay",
        p.returncode == 0
        and "without its app folder: this version's is in it now" in p.stdout + p.stderr
        and "TINFOIL KIT UPDATE" in p.stdout
        and calls[-len(update_calls) :] == update_calls
        and (before / "app" / "SETUP.command").is_file()
        and (before / "data" / "my-notes.txt").read_text() == "mine"
        and (before / "downloads").is_dir()
        and not (before / "app.partial").exists(),
        p.stdout + p.stderr,
    )

    def try_kit(**settings):
        c = json.loads((CODE / "kit.json").read_text())
        c["settings"].update(starter_only=True, **settings)
        mine.write_text(json.dumps(c, indent=1))

    try_kit(picked=True)
    rc, out, calls = run_setup(answers="\nn\n\n")
    check(
        "SETUP again on a try-it kit, picked before: doesn't ask again, and a no to downloading keeps the try-it kit",
        rc == 0
        and "What goes in the kit?" not in out
        and "AI models:" in out
        and calls == ["update", "fit", "starter-off", "essentials-off", "plan", "starter-on"]
        and '"starter_only": true' in mine.read_text(),
        out,
    )
    rc, out, calls = run_setup(answers="\n2\n\n", SPACE=space("no", "fits", 300, 1000, 400, 100, 100))
    check(
        "SETUP again on a try-it kit that all of it won't fit: offers the essentials or not now, and not now keeps it",
        rc == 1
        and "1  Just the essentials" in out
        and "2  Not now" in out
        and "Somewhere else" not in out
        and "The try-it kit keeps working" in out
        and calls == ["update", "fit"]
        and '"starter_only": true' in mine.read_text(),
        out,
    )
    rc, out, calls = run_setup(answers="\n1\ny\nn\n\n", SPACE=space("no", "fits", 300, 1000, 400, 100, 100))
    check(
        "SETUP again on a try-it kit that all of it won't fit: the essentials, when chosen",
        rc == 0
        and calls == ["update", "fit", "starter-off", "essentials-on", "plan", "sync", "test"]
        and '"essentials_only": true' in mine.read_text(),
        out,
    )
    try_kit()
    rc, out, calls = run_setup(args=("--yes",), answers="")
    argv = (setup / "data" / "args.log").read_text().splitlines()
    check(
        "SETUP --yes on a try-it kit: gets the rest, asking nothing",
        rc == 0
        and calls == ["update", "fit"] + rest
        and "fit --restore --skip-too-big" in argv
        and "pick --ask" not in argv
        and not any(a in out for a in asked)
        and "All set" in out,
        out,
    )

    def essentials_only():
        c = json.loads((CODE / "kit.json").read_text())
        c["settings"]["essentials_only"] = True
        mine.write_text(json.dumps(c, indent=1))

    essentials_only()
    rc, out, calls = run_setup(answers="\ny\ny\nn\n\n")
    check(
        "SETUP: an update of just the essentials, now that the rest fits: offers it, and a yes gets it",
        rc == 0
        and "now there's room for the rest (about 400 GB more)" in out
        and calls == ["update", "fit", "essentials-off", "plan", "sync", "test"],
        out,
    )
    essentials_only()
    rc, out, calls = run_setup(answers="\n\ny\nn\n\n")
    check(
        "SETUP: an update of just the essentials: just Return keeps it that way",
        rc == 0 and "room for the rest" in out and calls == update_calls and "essentials_only" in mine.read_text(),
        out,
    )
    rc, out, calls = run_setup(args=("--yes",), answers="")
    check(
        "SETUP --yes: an update of just the essentials, now that the rest fits: says how to get it, asks nothing",
        rc == 0
        and "To get it too: ./kit essentials off, then SETUP again." in out
        and calls == update_calls
        and not any(a in out for a in asked)
        and "update --yes" in (setup / "data" / "args.log").read_text().splitlines(),
        out,
    )
    rc, out, calls = run_setup(args=("--even-if-tight", "--yes"), answers="")
    check(
        "SETUP --even-if-tight: an update of just the essentials gets the rest",
        rc == 0 and calls == ["update", "fit", "essentials-off", "plan", "sync", "test"],
        out,
    )
    rc, out, calls = run_setup(args=("--essentials", "--yes"), answers="")
    check(
        "SETUP --essentials: an update of all of it gets just the essentials from now on",
        rc == 0
        and calls == ["update", "fit", "plan", "sync", "test"]
        and '"essentials_only": true' in mine.read_text()
        and "Just the essentials: about" in out,
        out,
    )
    rc, out, calls = run_setup(SPACE=space("no", "fits", 300, 1000, 400, 100, 50))
    check(
        "SETUP: an update of just the essentials, and the rest still doesn't fit: doesn't offer it",
        rc == 0 and "room for the rest" not in out and calls == update_calls,
        out,
    )
    shutil.copy(CODE / "kit.json", mine)
    (setup / "data" / ".kit" / "state.json").unlink()
    rc, out, calls = run_setup(update=3)
    check(
        "SETUP: after updating the kit it starts over on the new SETUP, once",
        rc == 0
        and "Step 2 (new version) of 2: a small kit to try first" in out
        and out.count("TINFOIL KIT SETUP") == 1
        and out.count("Maps are for") == 1
        and calls == first,
        out,
    )
    rc, out, calls = run_setup(update=1)
    check(
        "SETUP: the kit's own update failed: carries on",
        rc == 0 and "The try-it kit works" in out and calls == first,
        out,
    )
    rc, out, calls = run_setup(sync=1)
    check(
        "SETUP: some downloads failed but the kit works: says so and lists them",
        rc == 1 and "didn't finish" in out and "models/Big: download failed" in out and "try-it kit works" not in out,
        out,
    )
    rc, out, calls = run_setup(sync=1, test=1)
    check(
        "SETUP: checks failed: stops after the try-it kit",
        rc == 1 and "Some checks failed" in out and "models/Big" in out and calls == first,
        out,
    )
    rc, out, calls = run_setup(sync=130)
    check("SETUP: Ctrl-C during the download", rc == 130 and "Stopped" in out and calls == first[:5], out)
    rc, out, calls = run_setup(plan=1)
    check(
        "SETUP: offline: stops before asking to download",
        rc == 1 and calls == first[:4] and "Start downloading" not in out,
        out,
    )
    rc, out, calls = run_setup(TOOK="")
    check(
        "SETUP the first time, when the connection couldn't be timed: the kit to try takes minutes on a fast one",
        rc == 0
        and "It takes minutes on a fast connection." in out
        and "The whole kit is" not in out
        and calls == first,
        out,
    )
    home = ["share on", "autostart on", "share"]
    check(
        "SETUP: a normal setup doesn't share the kit or start it with the computer",
        (setup / "data" / "home.log").read_text() == "",
    )
    rc, out, calls = run_setup(args=("--home-server",), answers="\ny\n\n")
    check(
        "SETUP --home-server: the try-it kit and right after it the rest, then shares the kit, starts it with the "
        "computer, shows the address, and doesn't open it",
        rc == 0
        and calls == first + rest + ["share", "autostart", "share"]
        and (setup / "data" / "home.log").read_text().splitlines() == home
        and "Then it gets the rest. The whole kit is about 380 GB: about 4 hours at this connection's speed (24.0 MB/s)."
        in out
        and "Step 3 of 3: the rest of the kit" in out
        and "Home server" in out
        and "Open the kit now" not in out
        and "double-click Open Tinfoil Kit" not in out,
        out,
    )
    rc, out, calls = run_setup(update=3, args=("--home-server",), answers="\ny\n\n")
    check(
        "SETUP --home-server: still a home server after the kit updates itself and starts over",
        rc == 0 and "(new version)" in out and (setup / "data" / "home.log").read_text().splitlines() == home,
        out,
    )
    rc, out, calls = run_setup(sync=1, args=("--home-server",), answers="\ny\n\n")
    check(
        "SETUP --home-server: some downloads failed but the kit works: shares it anyway",
        rc == 1 and "didn't finish" in out and (setup / "data" / "home.log").read_text().splitlines() == home,
        out,
    )
    rc, out, calls = run_setup(test=1, args=("--home-server",), answers="\ny\n\n")
    check(
        "SETUP --home-server: checks failed: doesn't share it",
        rc == 1 and (setup / "data" / "home.log").read_text() == "",
        out,
    )
    rc, out, calls = run_setup(answers="Bavaria\nAustria\nBavaria\n\n1\ny\nn\n\n")
    c = json.loads(mine.read_text())
    check(
        "SETUP: says where the maps are for, and changes the place, places nearby and Wikipedia's language when told",
        rc == 0
        and "Maps are for US Northeast" in out
        and "Another place for your map" in out
        and "Maps: Germany: Bayern and Austria" in out
        and c["maps"]["region"] == ["bayern", "austria"]
        and [z["zim"][:17] for z in c["library"] if z["zim"].startswith("wikipedia_")] == ["wikipedia_de_all_"],
        out,
    )
    shutil.copy(CODE / "kit.json", mine)
    rc, out, calls = run_setup(args=("--yes",), answers="")
    argv = (setup / "data" / "args.log").read_text().splitlines()
    check(
        "SETUP --yes the first time: asks nothing, gets the try-it kit, says how to open it and get the rest, and closes",
        rc == 0
        and calls == first
        and "update --yes" in argv
        and "fit --restore --skip-too-big" in argv
        and not any(a in out for a in asked)
        and "Start downloading" not in out
        and "Open the kit now" not in out
        and f'When you\'re ready for it: bash "{setup}/app/SETUP.command" --yes' in out
        and f'To open it: bash "{setup}/app/Open Tinfoil Kit.command"' in out,
        out,
    )
    rc, out, calls = run_setup(
        args=(
            "--region",
            "texas",
            "--wikipedia",
            "es",
            "--skip",
            "maps",
            "--add",
            "gutenberg_en_all",
            "--share",
            "--yes",
        ),
        answers="",
    )
    c = json.loads(mine.read_text())
    check(
        "SETUP --region, --wikipedia, --skip, --add and --share: kit.json changes, and the kit is shared",
        rc == 0
        and c["maps"]["region"] == "us/texas"
        and c["maps"]["enabled"] is False
        and [z["zim"][:17] for z in c["library"] if z["zim"].startswith("wikipedia_")] == ["wikipedia_es_all_"]
        and {k: v for k, v in c["library"][-1].items() if k in ("enabled", "essential")} == {"essential": True}
        and (setup / "data" / "home.log").read_text().splitlines() == ["share on", "share"]
        and "Sharing:" in out
        and "Open the kit now" not in out
        and "it gets it" not in out,
        out,
    )
    shutil.copy(CODE / "kit.json", mine)
    rc, out, calls = run_setup(args=("--no-ai", "--yes"), answers="")
    argv = (setup / "data" / "args.log").read_text().splitlines()
    check(
        "SETUP --no-ai: every AI model off, and fit doesn't put one back",
        rc == 0
        and all(m.get("enabled") is False for m in json.loads(mine.read_text())["models"])
        and "fit" in argv
        and "fit --restore --skip-too-big" not in argv,
        out,
    )
    shutil.copy(CODE / "kit.json", mine)
    rc, out, calls = run_setup(args=("--yes", "--skip", "wikipedia,nothing-such"), answers="")
    check(
        "SETUP --skip with a name the kit doesn't have: stops before downloading, and kit.json is as it was",
        rc == 1
        and "Nothing in the kit is called nothing-such" in out
        and calls == ["update"]
        and mine.read_text() == (CODE / "kit.json").read_text(),
        out,
    )
    rc, out, calls = run_setup(args=("--bogus",), answers="")
    rc2, out2, calls2 = run_setup(args=("--drive",), answers="")
    rc3, out3, _ = run_setup(args=("--help",), answers="")
    rc4, out4, calls4 = run_setup(args=("--essentials", "--everything"), answers="")
    check(
        "SETUP: an option it doesn't have, one without its value, or two presets stop it at once; --help lists them",
        rc == rc2 == rc4 == 2
        and calls == calls2 == calls4 == []
        and rc3 == 0
        and "--yes" in out3
        and "--drive PATH" in out3
        and "--even-if-tight" in out3,
        out + out3,
    )

    # ./kit runs the kit's own program for this computer, made runnable first (as a download leaves it). When that
    # won't run here, or there's none and nothing to build it with, it says what to do. With Go, it builds the program
    # when there's none (GitHub's Download ZIP), and in a git checkout whose source is newer than its program.
    def wrapper(folder, build=None):
        """A copy of ./kit in folder, with a stand-in tools/tinfoilkit/build.sh whose program prints build."""
        (folder / "tools" / "tinfoilkit").mkdir(parents=True)
        shutil.copy(CODE / "kit", folder / "kit")
        if build:
            (folder / "tools" / "tinfoilkit" / "build.sh").write_text(
                f"""printf '#!/bin/sh\\n[ "$1" = version ] || echo {build} "$@"\\n' > "$(dirname "$0")/../{PROGRAM.name}"\n"""
            )
        return folder

    go_bin = work / "wrapper" / "go"  # a stand-in for Go: ./kit only looks for it
    go_bin.mkdir(parents=True)
    (go_bin / "go").write_text("#!/bin/sh\n")
    (go_bin / "go").chmod(0o755)

    def wrapped(folder, **e):
        p = subprocess.run(
            ["bash", str(folder / "kit"), "plan"],
            capture_output=True,
            text=True,
            env={**os.environ, "PATH": f"{go_bin}:{os.environ['PATH']}", **e},
        )
        return p.returncode, p.stdout.strip(), p.stderr

    dl = wrapper(work / "wrapper" / "download" / "app")
    prog = dl / "tools" / PROGRAM.name
    prog.write_text('#!/bin/sh\n[ "$1" = version ] && exit "${WONT_RUN:-0}"\necho program "$@"\n')  # not runnable yet
    rc, out, err = wrapped(dl)
    check(
        "./kit runs the kit's own program, made runnable first (as a download leaves it), on the kit folder",
        rc == 0 and out == f"program --root {dl.parent} plan" and os.access(prog, os.X_OK),
        out + err,
    )
    rc, out, err = wrapped(dl, WONT_RUN="1")
    check(
        "./kit: a program that won't run on this computer: says to download the kit again",
        rc == 1 and "doesn't run on this computer" in err and "https://tinfoilkit.com" in err,
        out + err,
    )
    prog.unlink()
    rc, out, err = wrapped(dl)
    check(
        "./kit with no program and nothing to build it with: says where to get the kit, or how to build it",
        rc == 1 and "https://tinfoilkit.com" in err and "tools/tinfoilkit/build.sh" in err,
        out + err,
    )
    zipped = wrapper(work / "wrapper" / "zip" / "app", build="built")
    rc, out, err = wrapped(zipped)
    rc2, out2, err2 = wrapped(zipped)
    check(
        "./kit with no program, and Go: builds it, then runs it, and only once outside a git checkout",
        rc == 0
        and out == f"built --root {zipped.parent} plan"
        and "Building the kit's program" in err
        and rc2 == 0
        and "Building" not in err2,
        out + err + err2,
    )
    co = wrapper(work / "wrapper" / "checkout" / "kit", build="rebuilt")  # the repository's kit/
    (co.parent / ".git").mkdir()
    (co / "tools" / PROGRAM.name).write_text('#!/bin/sh\n[ "$1" = version ] || echo built before "$@"\n')
    then = time.time() - 60
    os.utime(co / "tools" / "tinfoilkit" / "build.sh", (then, then))
    os.utime(co / "tools" / PROGRAM.name, (then + 30, then + 30))
    rc, out, err = wrapped(co)
    (co / "tools" / "tinfoilkit" / "kit.go").write_text("package main\n")  # an edit since the program was built
    rc2, out2, err2 = wrapped(co)
    check(
        "./kit in a git checkout: runs the program it has, and builds it again once its source changes",
        rc == 0 and out == f"built before --root {co} plan" and rc2 == 0 and out2 == f"rebuilt --root {co} plan",
        out + err + out2 + err2,
    )

    # The first run asks where the kit goes, moves it there, and the copy there does the rest. Drives are folders
    # in a stand-in for /Volumes; /dev/shm, a different disk, stands in for a drive the kit has to be copied to.
    def first_run(answers, drives=(), git=False, home_kit=None, where="\n1\n", args=(), beside=None, **env_extra):
        """SETUP's first run. ./kit space says what SPACE (this computer) and SPACE_DRIVE (drives) say. where: the
        answers to "Where do you live?" and "How much of Wikipedia?" (Return keeps the kit's place, 1 all of it)."""
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
        if beside:  # the app folder was put in a folder with other things in it
            (dl / beside).write_text("not the kit's")
        (dl / "data").mkdir()
        (dl / "data" / "calls.log").write_text("")
        p = subprocess.run(
            ["bash", str((dl if git else dl / "app") / "SETUP.command"), *args],
            input=where + answers,
            capture_output=True,
            text=True,
            timeout=60,
            env={
                **os.environ,
                "HOME": str(home),
                "KIT_DRIVES": str(env_extra.pop("KIT_DRIVES", vols)),
                "SPACE": roomy,
                "PLAN": "0",
                "SYNC": "0",
                "TEST": "0",
                "UPDATE": "0",
                **env_extra,
            },
        )
        return p.returncode, p.stdout + p.stderr, dl, home, vols  # ./kit place says what it did on stderr

    def placed_ok(where, essentials=False, then_rest=False):
        """Set up at where: the try-it kit, and right after it the rest if told, with just the essentials or all."""
        log = where / "data" / "calls.log"
        # (fit was before the kit moved; how much fits, after ./kit update)
        tail = first[:1] + ["essentials-on" if essentials else "essentials-off"] + first[2:]
        if then_rest:
            tail += ["starter-off", "essentials-on" if essentials else "essentials-off"] + rest[2:]
        code = where if (where / ".git").exists() or (where.parent / ".git").exists() else where / "app"
        return (
            (code / "SETUP.command").exists()
            and (code / "kit").exists()
            and (code / "tools/pins.json").exists()
            and (where / "downloads").is_dir()
            and log.exists()
            and log.read_text().split()[1::2][-len(tail) :] == tail
            and ('"essentials_only": true' in (where / "data" / "kit.json").read_text()) == essentials
        )

    rc, out, dl, home, vols = first_run("2\ny\nn\n\n")
    check(
        "SETUP first run: this computer: says what fits, moves the kit to TinfoilKit in the home folder, sets up there",
        rc == 0
        and "Step 2 of 3: where should the kit go?" in out
        and "All of the kit is about 400 GB" in out
        and "Just the essentials (the AI" in out
        and "Its disk has 900 GB free of 1.0 TB: room for all of it" in out
        and placed_ok(home / "TinfoilKit")
        and not dl.exists()
        and "Moved the kit to this computer" in out
        and out.count("TINFOIL KIT SETUP") == 1
        and "Step 3 of 3: a small kit to try first" in out
        and "The try-it kit works" in out
        and (home / "TinfoilKit" / "data" / "calls.log").read_text().split()[1::2][:3]
        == ["fit", "update", "essentials-off"],
        out,
    )
    rc, out, _, _, _ = first_run("1\n1\ny\nn\n\n", drives=["SAMSUNG T7"])
    check(
        "SETUP first run: a drive: lists it with what fits, the kit moves to TinfoilKit at its top and sets up there",
        rc == 0
        and "1  SAMSUNG T7 (" in out
        and "900 GB free of 1.0 TB): room for all of it" in out
        and "Look again" in out
        and placed_ok(vols / "SAMSUNG T7" / "TinfoilKit")
        and "Moved the kit to the drive SAMSUNG T7" in out
        and "The try-it kit works" in out,
        out,
    )
    rc, out, _, home, _ = first_run("1\n2\ny\nn\n\n")
    check(
        "SETUP first run: no drive plugged in: says so, and offers this computer instead",
        rc == 0 and "No external drive is plugged in" in out and placed_ok(home / "TinfoilKit"),
        out,
    )
    small = space("no", "fits", 300, 1000, 400, 100, 100)
    rc, out, _, home, _ = first_run("2\n1\ny\nn\n\n", SPACE=small)
    check(
        "SETUP first run: all of it won't fit on this computer: offers just the essentials, and gets only those",
        rc == 0
        and "room for the essentials, not all of it" in out
        and "it needs about 400 GB plus some to spare, and 300 GB is free" in out
        and placed_ok(home / "TinfoilKit", essentials=True)
        and "The rest of the essentials is about 380 GB more" in out,
        out,
    )
    rc, out, _, home, _ = first_run("2\n2\n2\n1\ny\nn\n\n", SPACE=small)
    check(
        "SETUP first run: all of it won't fit: somewhere else goes to the drives",
        rc == 0 and "No external drive" in out and placed_ok(home / "TinfoilKit", essentials=True),
        out,
    )
    rc, out, _, home, _ = first_run("2\n2\ny\nn\n\n", SPACE=space("tight", "fits", 450, 1000, 400, 100, 100))
    check(
        "SETUP first run: all of it fits, but leaves too little free: warns, and goes ahead when told to",
        rc == 0
        and "room for all of it, but that leaves only 50 GB free" in out
        and "Better to leave at least 100 GB, so this computer keeps running well" in out
        and placed_ok(home / "TinfoilKit"),
        out,
    )
    rc, out, _, home, _ = first_run("2\n1\ny\nn\n\n", SPACE=space("no", "tight", 150, 1000, 400, 100, 100))
    check(
        "SETUP first run: only the essentials fit, leaving too little free: warns, and goes ahead when told to",
        rc == 0
        and "Only the essentials fit on this computer, and they leave only 50 GB free" in out
        and placed_ok(home / "TinfoilKit", essentials=True),
        out,
    )
    rc, out, dl, home, _ = first_run("2\n", SPACE=space("no", "no", 50, 1000, 400, 100, 100))
    check(
        "SETUP first run: not even the essentials fit: says so, and asks for somewhere else",
        rc == 1
        and "not enough room, even for the essentials" in out
        and "There isn't room on this computer" in out
        and "No external drive" in out
        and dl.exists()
        and not (home / "TinfoilKit").exists(),
        out,
    )
    rc, out, _, home, _ = first_run(
        "1\n1\n3\ny\nn\n\n", drives=["STICK"], SPACE_DRIVE=space("no", "no", 20, 64, 400, 100, 10)
    )
    check(
        "SETUP first run: a drive too small even for the essentials: says so, and this computer is still an option",
        rc == 0
        and "STICK (" in out
        and "20 GB free of 64 GB): not enough room, even for the essentials" in out
        and "There isn't room on STICK" in out
        and placed_ok(home / "TinfoilKit"),
        out,
    )
    rc, out, dl, home, _ = first_run("2\ny\nn\n\n", git=True)
    check(
        "SETUP first run: a git checkout on this computer stays where it is",
        rc == 0 and placed_ok(dl) and not (home / "TinfoilKit").exists(),
        out,
    )
    rc, out, dl, home, _ = first_run("2\ny\nn\n\n", home_kit="kit")
    check(
        "SETUP first run: a kit already in the home folder: carries on with that one",
        rc == 0 and "already a Tinfoil Kit" in out and placed_ok(home / "TinfoilKit") and dl.exists(),
        out,
    )
    rc, out, dl, home, _ = first_run("2\n", home_kit="other")
    check(
        "SETUP first run: someone else's TinfoilKit folder is left alone",
        rc == 1
        and "isn't a Tinfoil Kit" in out
        and (home / "TinfoilKit" / "notes.txt").read_text() == "mine"
        and dl.exists()
        and sorted(f.name for f in (home / "TinfoilKit").iterdir()) == ["notes.txt"],
        out,
    )
    rc, out, dl, home, _ = first_run("2\n", beside="taxes.pdf")
    check(
        "SETUP first run: an app folder put in a folder with other things in it: neither moves, and it says why",
        rc == 1
        and "isn't in a folder of its own" in out
        and (dl / "taxes.pdf").exists()
        and (dl / "app").is_dir()
        and not (home / "TinfoilKit").exists(),
        out,
    )
    rc, out, _, _, _ = first_run("3\n")
    check(
        "SETUP first run: a wrong answer asks again, and a closed window stops it",
        rc == 1 and "Type a number from 1 to 2" in out,
        out,
    )

    def placed_cfg(where):
        c = json.loads((where / "data" / "kit.json").read_text())
        return c["maps"].get("region"), [z["zim"] for z in c["library"] if z["zim"].startswith("wikipedia_")]

    rc, out, dl, home, _ = first_run("2\ny\nn\n\n", where="Atlantis\nUSA\nTexas\n\n1\n1\n")
    check(
        "SETUP first run: asks where you live first, says when it can't tell, and sets the maps and Wikipedia",
        rc == 0
        and "Step 1 of 3: where do you live?" in out
        and 'No place called "Atlantis"' in out
        and '"USA" matches' in out
        and "Maps: Texas" in out
        and "Step 2 of 3: where should the kit go" in out
        and "Step 3 of 3: a small kit to try first" in out
        and placed_ok(home / "TinfoilKit")
        and placed_cfg(home / "TinfoilKit") == ("us/texas", ["wikipedia_en_all_maxi"]),
        out,
    )
    rc, out, dl, home, _ = first_run("2\ny\nn\n\n", where="Georgia\n1\n\n2\n1\n")
    check(
        "SETUP first run: a name two places share: asks which, then which language",
        rc == 0
        and "Which one?" in out
        and "Georgia (United States)" in out
        and "Georgia (Europe)" in out
        and "Which language should Wikipedia be in?" in out
        and placed_cfg(home / "TinfoilKit") == ("us/georgia", ["wikipedia_es_all_maxi"]),
        out,
    )
    rc, out, dl, home, _ = first_run("2\ny\nn\n\n", where="\n4\n")
    check(
        "SETUP first run: asks how much of Wikipedia, with the sizes Kiwix makes in its language, and sets it",
        rc == 0
        and "How much of Wikipedia?" in out
        and "  1  All of it, with pictures (127 GB)" in out
        and "  5  The best 50,000 articles' opening paragraphs (0.3 GB)" in out
        and placed_ok(home / "TinfoilKit")
        and placed_cfg(home / "TinfoilKit") == ("us-northeast", ["wikipedia_en_top_nopic"]),
        out,
    )
    rc, out, dl, home, _ = first_run(
        "", where="", args=("--region", "texas", "--wikipedia-size", "top", "--this-computer", "--yes")
    )
    check(
        "SETUP --wikipedia-size: sets it, asking nothing",
        rc == 0
        and "How much of Wikipedia?" not in out
        and placed_cfg(home / "TinfoilKit") == ("us/texas", ["wikipedia_en_top_maxi"]),
        out,
    )
    rc, out, dl, home, _ = first_run("", where="", args=("--region", "texas", "--this-computer", "--yes"))
    k = home / "TinfoilKit"
    check(
        "SETUP --region texas --this-computer --yes: asks nothing, sets up in the home folder, doesn't open the kit",
        rc == 0
        and placed_ok(k)
        and not dl.exists()
        and placed_cfg(k) == ("us/texas", ["wikipedia_en_all_maxi"])
        and "update --yes" in (k / "data" / "args.log").read_text().splitlines()
        and not any(a in out for a in asked)
        and "Open the kit now" not in out
        and "The try-it kit works" in out,
        out,
    )
    t7 = work / "place" / "Volumes" / "SAMSUNG T7"
    rc, out, dl, home, _ = first_run(
        "",
        where="",
        drives=["SAMSUNG T7"],
        args=(
            "--drive",
            str(t7),
            "--essentials",
            "--models",
            "Gemma-4-E4B",
            "--skip",
            "maps",
            "--add",
            "gutenberg_en_all,wikipedia",
            "--no-pause",
            "--yes",
        ),
    )
    t7_cfg = t7 / "TinfoilKit" / "data" / "kit.json"
    c = json.loads(t7_cfg.read_text()) if t7_cfg.exists() else {}
    check(
        "SETUP --drive --essentials --models --skip --add --no-pause --yes: on the drive, the try-it kit, then just the "
        "essentials plus what was added",
        rc == 0
        and placed_ok(t7 / "TinfoilKit", essentials=True, then_rest=True)
        and "What goes in it:" in out
        and "Step 4 of 4: the rest of the kit" in out
        and [m["id"] for m in c["models"] if m.get("enabled", True)] == ["Gemma-4-E4B"]
        and c["maps"]["enabled"] is False
        and [z["zim"] for z in c["library"] if z.get("essential")] == ["wikipedia_en_all_maxi", "gutenberg_en_all"],
        out,
    )
    rc, out, dl, home, _ = first_run("", where="", args=("--drive", str(t7.parent / "NOPE"), "--yes"))
    check(
        "SETUP --drive with no drive there, --yes: says so and stops",
        rc == 1 and "There's no drive at" in out and dl.exists() and not (home / "TinfoilKit").exists(),
        out,
    )
    rc, out, dl, home, _ = first_run("2\ny\nn\n\n", args=("--drive", str(t7.parent / "NOPE")))
    check(
        "SETUP --drive with no drive there: says so, then asks where",
        rc == 0 and "There's no drive at" in out and placed_ok(home / "TinfoilKit"),
        out,
    )
    rc, out, dl, home, _ = first_run("", where="", args=("--this-computer", "--yes"), SPACE=small)
    check(
        "SETUP --yes: all of it won't fit with room to spare: just the essentials, and says so",
        rc == 0 and "So it gets just the essentials" in out and placed_ok(home / "TinfoilKit", essentials=True),
        out,
    )
    rc, out, dl, home, _ = first_run("", where="", args=("--even-if-tight", "--this-computer", "--yes"), SPACE=small)
    rc2, out2, dl2, home2, _ = first_run(
        "", where="", args=("--this-computer", "--yes"), SPACE=space("no", "no", 50, 1000, 400, 100, 100)
    )
    check(
        "SETUP --yes: all of it with --even-if-tight, or even the essentials, won't fit: stops before moving anything",
        rc == rc2 == 1
        and dl.exists()
        and dl2.exists()
        and not (home / "TinfoilKit").exists()
        and "There isn't room on this computer, even for the essentials" in out2,
        out + out2,
    )
    rc, out, dl, home, _ = first_run("", where="", args=("--region", "texas", "--yes"))
    check(
        "SETUP --yes the first time, with neither --drive nor --this-computer: says to choose one, and changes nothing",
        rc == 2
        and "--drive PATH for an external drive (recommended)" in out
        and "or --this-computer for the home folder here" in out
        and dl.exists()
        and not (home / "TinfoilKit").exists(),
        out,
    )
    rc, out, dl, home, _ = first_run("", where="", args=("--essentials", "--this-computer", "-y"))
    check(
        "SETUP --essentials -y the first time: just the essentials, and like any first run it stops after the try-it kit",
        rc == 0
        and placed_ok(home / "TinfoilKit", essentials=True)
        and "Step 3 of 3: a small kit to try first" in out
        and "The rest of the essentials is about" in out
        and not any(a in out for a in asked),
        out,
    )
    rc, out, dl, home, _ = first_run("", where="", args=("--no-pause", "--this-computer", "--yes"))
    check(
        "SETUP --no-pause the first time: straight on to the rest after the try-it kit",
        rc == 0 and placed_ok(home / "TinfoilKit", then_rest=True) and "Step 4 of 4: the rest of the kit" in out,
        out,
    )
    rc, out, dl, home, _ = first_run("2\ny\nn\n\n", where="Texas\n\n1\n1\n", home_kit="kit")
    check(
        "SETUP first run: a kit already in the home folder gets the place chosen in the download",
        rc == 0 and "already a Tinfoil Kit" in out and placed_cfg(home / "TinfoilKit")[0] == "us/texas",
        out,
    )
    shm = Path("/dev/shm")
    # (Docker mounts /dev/shm noexec, where the copied ./kit can't run.)
    if (
        shm.is_dir()
        and os.access(shm, os.W_OK)
        and shm.stat().st_dev != work.stat().st_dev
        and not os.statvfs(shm).f_flag & getattr(os, "ST_NOEXEC", 8)
    ):
        drv = Path(tempfile.mkdtemp(prefix="kit drives ", dir=shm))
        try:
            (drv / "USB DRIVE").mkdir()
            rc, out, dl, _, _ = first_run("1\n1\ny\nn\n\n", KIT_DRIVES=drv)
            check(
                "SETUP first run: a drive that's another disk: the kit is copied over, and the download removed",
                rc == 0
                and placed_ok(drv / "USB DRIVE" / "TinfoilKit")
                and not dl.exists()
                and "Moved the kit" in out
                and not (drv / "USB DRIVE" / "TinfoilKit.partial").exists(),
                out,
            )
            shutil.rmtree(drv / "USB DRIVE" / "TinfoilKit")
            rc, out, dl, _, _ = first_run("1\n1\ny\nn\n\n", git=True, KIT_DRIVES=drv)
            tk = drv / "USB DRIVE" / "TinfoilKit"
            check(
                "SETUP first run: a git checkout's code is copied to the drive as its app folder, and the checkout "
                "stays where it was; it gets the license, README and THIRD-PARTY.md, as a release does, and .git, the "
                "website, npm's packages and ruff's cache stay behind",
                rc == 0
                and placed_ok(tk)
                and not (tk / "app" / ".git").exists()
                and dl.exists()
                and "Use that copy from now on" in out
                and (tk / "app" / "tools" / "sources.json").exists()
                and all((tk / "app" / f).read_text() == f + "\n" for f in ("LICENSE", "README.md", "THIRD-PARTY.md"))
                and not (tk / "app" / "node_modules").exists()
                and not (tk / "app" / ".ruff_cache").exists()
                and not (tk / "app" / "site").exists(),
                out,
            )
            if shutil.which("git"):
                head = subprocess.run(["git", "-C", str(dl), "rev-parse", "HEAD"], capture_output=True, text=True)
                check(
                    "the copy knows the checkout's commit, as a release knows its own, for ./kit update",
                    (tk / "app" / "tools" / "commit").read_text() == head.stdout,
                    (tk / "app" / "tools" / "commit").read_text(),
                )
        finally:
            shutil.rmtree(drv, ignore_errors=True)
    else:
        print("skip  SETUP first run: copying to another disk (no usable /dev/shm here)")

    # UNINSTALL.command: removes the kit and its downloads, only when asked, and stops the kit if it's running.
    def uninstall(*args, answers="", kit_files=True, name="TinfoilKit", beside=None):
        gone = work / "gone" / name
        shutil.rmtree(gone.parent, ignore_errors=True)
        (gone / "downloads" / "models" / "Tiny").mkdir(parents=True)
        (gone / "downloads" / "models" / "Tiny" / "Tiny.gguf").write_bytes(os.urandom(5000))
        (gone / "downloads" / "library").mkdir()
        (gone / "downloads" / "library" / "book.zim").write_bytes(os.urandom(5000))
        (gone / "data").mkdir()
        (gone / "data" / "kit.json").write_text("{}")
        (gone / "app").mkdir()
        shutil.copy(CODE / "UNINSTALL.command", gone / "app")
        if kit_files:
            (gone / "app" / "kit").write_text(f'#!/bin/bash\necho "$*" >> "{work / "uninstall-kit.log"}"\n')
            (gone / "app" / "kit").chmod(0o755)
            (gone / "app" / "tools").mkdir()
            (gone / "app" / "tools" / "pins.json").write_text("{}\n")
        (gone.parent / "keep.txt").write_text("not the kit's")
        for b in [beside] if isinstance(beside, str) else beside or ():
            (gone / b).write_text("mine")
        p = subprocess.run(
            ["bash", str(gone / "app" / "UNINSTALL.command"), *args],
            input=answers,
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, "HOME": str(work)},
        )
        return p.returncode, p.stdout, gone

    kit_log = work / "uninstall-kit.log"
    kit_log.write_text("")
    app_note = work / "Library" / "Application Support" / "TinfoilKit"  # where the Mac app keeps where the kit is
    app_note.mkdir(parents=True)
    (app_note / "last-kit").write_text("the kit\n")
    rc, out, gone = uninstall(answers="\n\n")
    check(
        "UNINSTALL: says what it deletes, and just Return keeps everything",
        rc == 0
        and "This deletes Tinfoil Kit" in out
        and "can't be undone" in out
        and "Kept" in out
        and app_note.exists()
        and (gone / "downloads" / "models/Tiny/Tiny.gguf").exists()
        and kit_log.read_text() == "",
        out,
    )
    rc, out, gone = uninstall(answers="yes\n\n")
    check(
        "UNINSTALL: anything but delete keeps it",
        rc == 0 and "Kept" in out and (gone / "downloads" / "library/book.zim").exists(),
        out,
    )
    rc, out, gone = uninstall(answers="delete\n\n")
    check(
        "UNINSTALL: typing delete removes the kit, its downloads and the Mac app's note of it, and nothing beside it",
        rc == 0
        and not gone.exists()
        and (gone.parent / "keep.txt").exists()
        and "Tinfoil Kit is gone" in out
        and not app_note.exists(),
        out,
    )
    check(
        "UNINSTALL: a home server's kit stops starting with the computer first",
        kit_log.read_text() == "autostart off\n",
        kit_log.read_text(),
    )
    check("UNINSTALL: with nothing running, it doesn't say it's stopping the kit", "Stopping the kit" not in out, out)
    rc, out, gone = uninstall(answers="delete\n\n", kit_files=False)
    check(
        "UNINSTALL: refuses a folder that isn't a kit",
        rc == 1 and gone.exists() and "doesn't look like a Tinfoil Kit" in out,
        out,
    )
    rc, out, gone = uninstall(answers="DELETE\n\n")
    check("UNINSTALL: DELETE in capitals works too", rc == 0 and not gone.exists(), out)
    rc, out, gone = uninstall(answers="delete\n\n", name="Desktop", beside="taxes.pdf")
    check(
        "UNINSTALL: an app folder put in a folder with other things in it: deletes nothing, and says why",
        rc == 1 and "isn't in a folder of its own" in out and (gone / "taxes.pdf").exists() and (gone / "app").is_dir(),
        out,
    )
    rc, out, gone = uninstall(answers="delete\n\n", beside="my-notes.txt")
    rc2, out2, gone2 = uninstall(answers="delete\n\n", name="Old kit", beside=TOP)
    check(
        "UNINSTALL: a TinfoilKit folder goes whole, and so does a renamed one that holds just the kit (with the files "
        "beside its three folders)",
        rc == rc2 == 0 and not gone.exists() and not gone2.exists(),
        out + out2,
    )

    def running_kit():
        """A kit whose AI server and own program are running (stand-ins that sleep), removed with --yes."""
        gone = work / "gone" / "TinfoilKit"
        shutil.rmtree(gone.parent, ignore_errors=True)
        procs = []
        for srv in (
            gone / "downloads" / "bin" / "llama.cpp-test" / "llama-server",
            gone / "app" / "tools" / "tinfoilkit-test",
        ):
            srv.parent.mkdir(parents=True, exist_ok=True)
            srv.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(300)\n")
            srv.chmod(0o755)
            procs.append(subprocess.Popen([str(srv)]))
        shutil.copy(CODE / "UNINSTALL.command", gone / "app")
        (gone / "app" / "kit").write_text("#!/bin/bash\n")
        (gone / "app" / "tools" / "pins.json").write_text("{}\n")
        time.sleep(0.5)
        p = subprocess.run(
            ["bash", str(gone / "app" / "UNINSTALL.command"), "--yes"],
            capture_output=True,
            text=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
            env={**os.environ, "HOME": str(work)},
        )
        stopped = True
        for proc in procs:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                stopped = False
        return p.returncode, p.stdout, gone, stopped

    rc, out, gone, stopped = running_kit()
    check(
        "UNINSTALL --yes: no question, stops the kit's running servers and its own program, removes it all",
        rc == 0
        and stopped
        and not gone.exists()
        and "Stopping the kit" in out
        and "Press Return" not in out
        and "notes and pins" in out,
        out,
    )

    # The launcher's first model, by the computer's memory. A stand-in for a running kit answers on its library, AI
    # and notes ports, so the launcher reuses them and only picks the model and prints the address.
    class RunningKit(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            # the library's page, and the notes
            body = (
                b'{"data": []}'
                if self.path.startswith("/v1/models")
                else b'{"name": "Tinfoil Kit", "notes": "/notes", "places": "/places"}'
            )
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
    (lk / "app" / "tools").mkdir(parents=True)
    for f in ("kit", "Open Tinfoil Kit.command"):
        shutil.copy(CODE / f, lk / "app")
    shutil.copy(PROGRAM, lk / "app" / "tools")
    launcher = lk / "app" / "Open Tinfoil Kit.command"
    (lk / "data").mkdir()
    (lk / "data" / "kit.json").write_text(
        json.dumps({"settings": {"default_model": "Big", "library_port": rport, "ai_port": rport, "data_port": rport}})
    )
    for name, gb in (("Big", 18), ("Mid", 12), ("Small", 5)):
        (lk / "downloads" / "models" / name).mkdir(parents=True)
        with open(lk / "downloads" / "models" / name / f"{name}-Q4_K_M.gguf", "wb") as f:
            f.truncate(gb * 10**9)  # sparse, so it takes no space

    def launch(mem_gb, *args):
        p = subprocess.run(
            ["bash", str(launcher), "--no-browser", *args],
            capture_output=True,
            text=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
            env={**os.environ, "KIT_MEMORY_MB": str(mem_gb * 1024)},
        )
        out = p.stdout + p.stderr
        return (out.split("?model=")[1].split("&")[0] if "?model=" in out else ""), out

    for mem_gb, want in ((32, "Big"), (24, "Mid"), (16, "Small"), (4, "Small")):
        got, out = launch(mem_gb)
        check(
            f"launcher: {mem_gb} GB of memory starts {want}",
            got == want and (want == "Big" or f"{mem_gb} GB of memory" in out),
            out,
        )
    got, out = launch(16, "--model=Big")
    check("launcher: --model wins over memory", got == "Big", out)
    (lk / "data" / "kit.json").write_text(
        json.dumps({"settings": {"default_model": "Gone", "library_port": rport, "ai_port": rport, "data_port": rport}})
    )
    got, out = launch(24)
    check("launcher: without the default model, the biggest that fits", got == "Mid" and "too little" not in out, out)

    # ./kit fit: which model this computer runs, and asking before downloading the ones too big for it.
    fk = work / "fit"
    new_kit(fk)
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
    (fk / "data" / "kit.json").write_text(fit_json)

    def fit(mem_gb, *args, answers=""):
        p = subprocess.run(
            kit_cmd(fk / "app", fk, "fit", *args),
            input=answers,
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, "KIT_MEMORY_MB": str(mem_gb * 1024)},
        )
        return p.returncode, p.stdout + p.stderr

    rc, out = fit(32)
    check(
        "kit fit: enough memory for the default model",
        rc == 0 and "32 GB of memory, so its AI will be Big" in out and "can't run" not in out,
        out,
    )
    rc, out = fit(16)
    check(
        "kit fit: too little for the default: the biggest that fits, and which ones it can't run (changes nothing)",
        rc == 0
        and "its AI will be Mid" in out
        and "It can't run Big: it needs 32 GB of memory or more" in out
        and "./kit fit --skip-too-big" in out
        and (fk / "data" / "kit.json").read_text() == fit_json,
        out,
    )
    rc, out = fit(16, "--ask", answers="\n")
    on = {m["id"]: m.get("enabled", True) for m in json.loads((fk / "data" / "kit.json").read_text())["models"]}
    added = [line for line in (fk / "data" / "kit.json").read_text().splitlines() if line not in fit_json.splitlines()]
    check(
        "kit fit --ask: just Return skips them, in kit.json, changing only the lines that say so",
        rc == 0
        and "Download them anyway? [y/N]" in out
        and on == {"Big": False, "Mid": True, "Small": True}
        and added == ['    "models_off_for_memory": ["Big"],', '      "enabled": false,'],
        out,
    )
    rc, out = fit(16, "--ask")
    check("kit fit --ask: doesn't ask again about a skipped one", rc == 0 and "?" not in out and "Big" not in out, out)
    rc, out = fit(64, "--ask", answers="\n")
    check(
        "kit fit --ask: a computer with more memory offers them back, and kit.json is as it was",
        rc == 0
        and "skipped before on a computer with less memory" in out
        and "Its AI will be Big." in out
        and (fk / "data" / "kit.json").read_text() == fit_json,
        out,
    )
    rc, out = fit(16, "--ask", answers="y\n")
    check("kit fit --ask: yes keeps them", rc == 0 and (fk / "data" / "kit.json").read_text() == fit_json, out)
    rc, out = fit(8, "--json")
    report = json.loads(out)
    check(
        "kit fit --json: on 8 GB nothing fits, so the smallest, and the rest are too big",
        rc == 0 and report["runs"] == "Small" and report["too_big"] == ["Big", "Mid"],
        out,
    )
    (fk / "data" / ".kit").mkdir(exist_ok=True)
    (fk / "data" / ".kit" / "state.json").write_text(json.dumps({"items": {"models/Big": {}}}))
    rc, out = fit(16, "--skip-too-big")
    check(
        "kit fit --skip-too-big: leaves alone a model that's already downloaded",
        rc == 0 and "can't run" not in out and (fk / "data" / "kit.json").read_text() == fit_json,
        out,
    )
    (fk / "data" / ".kit" / "state.json").unlink()
    named = fit_json.replace('"id": "Big",', '"id": "Big",\n      "essential": true,')
    (fk / "data" / "kit.json").write_text(named)
    rc, out = fit(16, "--skip-too-big")
    check(
        "kit fit --skip-too-big: keeps a model asked for by name",
        rc == 0 and "Big comes anyway, as asked" in out and (fk / "data" / "kit.json").read_text() == named,
        out,
    )
    (fk / "data" / "kit.json").write_text(fit_json)

    # ./kit essentials on|off: just the essentials from now on, or everything again.
    rc, out = kit("essentials", "on", root=fk)
    check(
        "kit essentials on: one line in kit.json's settings",
        rc == 0
        and "Just the essentials" in out
        and json.loads((fk / "data" / "kit.json").read_text())["settings"]["essentials_only"] is True
        and len((fk / "data" / "kit.json").read_text().splitlines()) == len(fit_json.splitlines()) + 1,
        out,
    )
    rc, out = kit("essentials", "off", root=fk)
    check(
        "kit essentials off: kit.json as it was",
        rc == 0 and "Everything" in out and (fk / "data" / "kit.json").read_text() == fit_json,
        out,
    )

    # ./kit pick: what goes in the kit, by name (SETUP's --no-ai, --models, --skip and --add).
    pk = work / "pick"
    new_kit(pk)
    shutil.copy(CODE / "kit.json", pk / "data" / "kit.json")
    before = (pk / "data" / "kit.json").read_text()
    rc, out = kit(
        "pick", "--models", "gemma-4-e4b", "--skip", "stackexchange", "--add", "gutenberg_en_all Wikipedia", root=pk
    )
    c = json.loads((pk / "data" / "kit.json").read_text())
    diff = list(difflib.ndiff(before.splitlines(), (pk / "data" / "kit.json").read_text().splitlines()))
    added, gone = [x for x in diff if x.startswith("+ ")], [x for x in diff if x.startswith("- ")]
    se = [z for z in c["library"] if ".stackexchange.com_" in z["zim"]]
    check(
        "kit pick: just that model, every Stack Exchange site off, and the adds on, changing only the lines that say so",
        rc == 0
        and [m["id"] for m in c["models"] if m.get("enabled", True)] == ["Gemma-4-E4B"]
        and len(se) == 10
        and all(z.get("enabled") is False for z in se)
        and "enabled" not in c["library"][-1]
        and len(added) == 18
        and len(gone) == 12
        and all('"enabled": false' in x or '"essential": true' in x or '"picked": true' in x for x in added)
        and c["settings"]["picked"] is True
        and "AI models: Gemma-4-E4B." in out,
        out,
    )
    now = (pk / "data" / "kit.json").read_text()
    rc, out = kit("pick", "--add", "libretexts,nothing-such", root=pk)
    rc2, out2 = kit("pick", "--models", "wikipedia", root=pk)
    check(
        "kit pick: a name the kit doesn't have changes nothing, and says what there is",
        rc == rc2 == 2
        and "Nothing in the kit is called nothing-such" in out
        and "Books: mdwiki_en_all_maxi" in out
        and "No AI model is called wikipedia" in out2
        and (pk / "data" / "kit.json").read_text() == now,
        out + out2,
    )

    # ./kit pick with a preset, as the kit builder writes it: what goes in starts over from the standard list
    # (app/kit.json), where you live and Wikipedia come with it, and what's named after it changes that.
    shutil.copy(CODE / "kit.json", pk / "data" / "kit.json")
    std = json.loads((CODE / "kit.json").read_text())
    builder = ("--essentials", "--region", "texas", "--wikipedia", "en,es", "--wikipedia-size", "top-text")
    builder += ("--skip", "ifixit_en_all", "--add", "wiktionary_en_all_nopic")
    rc, out = kit("pick", *builder, root=pk)
    once = (pk / "data" / "kit.json").read_text()
    c = json.loads(once)
    lib = {z["zim"]: z for z in c["library"]}
    wikis = ["wikipedia_en_top_nopic", "wikipedia_es_top_nopic"]
    rc2, out2 = kit("pick", *builder, root=pk)
    check(
        "kit pick with the builder's options: just the essentials, with Wikipedia whole in the size said, and the same "
        "again changes nothing",
        rc == rc2 == 0
        and c["settings"].get("essentials_only") is True
        and c["settings"].get("picked") is True
        and c["maps"]["region"] == "us/texas"
        and [z for z in lib if z.startswith("wikipedia_")] == wikis
        and all(lib[z].get("essential") is True for z in wikis + ["wiktionary_en_all_nopic"])
        and lib["ifixit_en_all"].get("enabled") is False
        and "Just the essentials: about" in out
        and (pk / "data" / "kit.json").read_text() == once,
        out + out2,
    )
    c["maps"]["label"] = "Home turf"  # set by hand: saying the same place again keeps it
    (pk / "data" / "kit.json").write_text(json.dumps(c, indent=1))
    rc, out = kit("pick", "--recommended", "--region", "texas", root=pk)
    c = json.loads((pk / "data" / "kit.json").read_text())
    std_on = {z["zim"]: z.get("enabled", True) for z in std["library"]}
    check(
        "kit pick --recommended: what goes in starts over from the standard list; where you live, Wikipedia and the "
        "map's own settings stay",
        rc == 0
        and "essentials_only" not in c["settings"]
        and c["maps"]["region"] == "us/texas"
        and c["maps"]["label"] == "Home turf"
        and [z["zim"] for z in c["library"] if z["zim"].startswith("wikipedia_")] == wikis
        and not any(e.get("essential") for s in ("models", "library") for e in c[s])
        and all(z.get("enabled", True) == std_on.get(z["zim"], True) for z in c["library"] if z["zim"] not in wikis)
        and all(m.get("enabled", True) for m in c["models"]),
        out,
    )
    rc, out = kit("pick", "--everything", root=pk)
    c = json.loads((pk / "data" / "kit.json").read_text())
    check(
        "kit pick --everything: every AI model and book, the biggest collections too, and the map",
        rc == 0
        and all(e.get("enabled", True) for s in ("models", "library") for e in c[s])
        and c["maps"]["enabled"] is True
        and "essentials_only" not in c["settings"],
        out,
    )
    shutil.copy(CODE / "kit.json", pk / "data" / "kit.json")
    rc, out = kit("pick", "--essentials", root=pk)
    c = json.loads((pk / "data" / "kit.json").read_text())
    p = subprocess.run(
        kit_cmd(pk / "app", pk, "estimate", "--json"),
        capture_output=True,
        text=True,
        env={**os.environ, "KIT_MEMORY_MB": str(64 * 1024)},
    )
    items = json.loads(p.stdout)["items"] if p.returncode == 0 else []
    check(
        "kit pick --essentials: Wikipedia's best articles stand in for all of it, and estimate --json lists what comes",
        rc == 0
        and c["settings"].get("essentials_only") is True
        and not any(z.get("essential") for z in c["library"])
        and "library/wikipedia_en_top_nopic" in items
        and "library/wikipedia_en_all_maxi" not in items
        and "models/Inkling-2-Mini" in items
        and "maps/basemap" in items
        and "library/gutenberg_en_all" not in items,
        out + p.stdout + p.stderr,
    )
    now = (pk / "data" / "kit.json").read_text()
    rc, out = kit("pick", "--essentials", "--everything", root=pk)
    rc2, out2 = kit("pick", "--wikipedia-size", "huge", root=pk)
    rc3, out3 = kit("pick", "--recommended", "--region", "atlantis", root=pk)
    check(
        "kit pick: two presets, a size Wikipedia doesn't come in, or a place it doesn't know: changes nothing",
        rc == 2
        and "Choose one of --recommended, --essentials and --everything" in out
        and rc2 == rc3 == 1
        and "doesn't come in a size called 'huge'" in out2
        and 'No place matches "atlantis"' in out3
        and (pk / "data" / "kit.json").read_text() == now,
        out + out2 + out3,
    )

    # ./kit pick --ask: the kit builder's choices, asked in a terminal: a preset, or each part. A preset is the
    # standard list's (app/kit.json): what it switches on, with just the essentials for Essentials.
    ak = work / "ask"
    new_kit(ak)
    (ak / "app" / "kit.json").write_text(
        json.dumps(
            {
                "settings": {},
                "models": [{"id": "Tiny", "type": "hf"}, {"id": "Two", "type": "hf", "enabled": False}],
                "library": [
                    {"zim": "testmed_en_all_maxi", "priority": 1},
                    {"zim": "testsurvival_en", "enabled": False},
                    {"zim": "wikipedia_en_all_maxi"},
                ],
            },
            indent=1,
        )
    )
    ask_json = json.dumps(
        {
            "settings": {},
            "models": [{"id": "Tiny", "type": "hf"}, {"id": "Two", "type": "hf"}],
            "library": [{"zim": "testmed_en_all_maxi", "priority": 1}, {"zim": "testsurvival_en"}],
        },
        indent=1,
    )
    (ak / "data" / "kit.json").write_text(ask_json)
    (ak / "app" / "tools" / "sources.json").write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "id": "Tiny",
                        "group": "AI models",
                        "title": "Tiny AI",
                        "bytes": 2 * 10**9,
                        "presets": ["recommended", "essentials", "everything"],
                    },
                    {
                        "id": "Two",
                        "group": "AI models",
                        "title": "Two AI",
                        "bytes": 3 * 10**9,
                        "presets": ["everything"],
                    },
                    {
                        "id": "testmed_en_all_maxi",
                        "group": "Medicine",
                        "title": "Medicine",
                        "bytes": 4 * 10**9,
                        "presets": ["recommended", "essentials", "everything", "no-ai"],
                    },
                    {
                        "id": "testsurvival_en",
                        "group": "Survival",
                        "title": "Survival",
                        "bytes": 60 * 10**9,
                        "presets": ["everything", "no-ai"],
                    },
                ]
            }
        )
    )

    def ask(answers):
        p = subprocess.run(
            kit_cmd(ak / "app", ak, "pick", "--ask"),
            input=answers,
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, "KIT_MEMORY_MB": str(32 * 1024)},
        )
        c = json.loads((ak / "data" / "kit.json").read_text())
        return (
            p.returncode,
            p.stdout + p.stderr,
            sorted(e.get("id", e.get("zim")) for s in ("models", "library") for e in c[s] if e.get("enabled", True)),
            c["settings"],
        )

    rc, out, on, settings = ask("\n")
    check(
        "kit pick --ask: lists the builder's presets with their sizes, and Return takes Recommended",
        rc == 0
        and "1  Recommended: what we'd take. About 7 GB." in out
        and "3  Everything:" in out
        and "5  Choose each part" in out
        and on == ["Tiny", "testmed_en_all_maxi"]
        and settings == {"picked": True},
        out,
    )
    rc, out, on, _ = ask("9\n4\n")
    check(
        "kit pick --ask: a number it doesn't have asks again; No AI is Recommended with every model off",
        rc == 0 and "Type a number from 1 to 5" in out and on == ["testmed_en_all_maxi"],
        out,
    )
    rc, out, on, settings = ask("5\n1 4\n\n")
    check(
        "kit pick --ask: choose each part, by group, switching them with their numbers",
        rc == 0
        and "AI models" in out
        and "[ ] Tiny AI (2.0 GB)" in out
        and "[ ] Survival (60.0 GB)" in out
        and on == ["Tiny", "testmed_en_all_maxi", "testsurvival_en"]
        and "essentials_only" not in settings,
        out,
    )
    # Essentials takes Wikipedia's best articles while the rest waits, as the kit builder does
    (ak / "data" / "kit.json").write_text(
        json.dumps(
            {
                "settings": {},
                "models": [{"id": "Tiny", "type": "hf"}],
                "library": [{"zim": "testmed_en_all_maxi", "priority": 1}, {"zim": "wikipedia_en_all_maxi"}],
            }
        )
    )
    src = json.loads((ak / "app" / "tools" / "sources.json").read_text())
    (ak / "app" / "tools" / "sources.json").write_text(
        json.dumps(
            {
                "sources": src["sources"]
                + [
                    {
                        "id": "wikipedia_en_all_maxi",
                        "group": "Reference",
                        "title": "Wikipedia",
                        "bytes": 127 * 10**9,
                        "presets": ["recommended", "essentials", "everything", "no-ai"],
                    }
                ]
            }
        )
    )
    rc, out, on, settings = ask("2\n")
    check(
        "kit pick --ask: Essentials gets just the essentials, Wikipedia's best articles among them, sized that way",
        rc == 0
        and "Recommended: what we'd take. About 134 GB." in out
        and "and Wikipedia's best articles. About 10 GB." in out
        and on == ["Tiny", "testmed_en_all_maxi", "wikipedia_en_all_maxi"]
        and settings.get("essentials_only") is True
        and "Just the essentials: about 10 GB, of 134 GB in all" in out,
        out,
    )
    c = json.loads((ak / "data" / "kit.json").read_text())
    c["library"][1]["zim"] = "wikipedia_en_top_nopic"
    (ak / "data" / "kit.json").write_text(json.dumps(c))
    rc, out, on, _ = ask("5\n\n")
    check(
        "kit pick --ask: choose each part shows the kit's Wikipedia, in its size",
        rc == 0 and "[x] Wikipedia: English, the best 50,000 articles, text only (2.7 GB)" in out,
        out,
    )

    # The kit builder's No AI preset switches every model off: ./kit test doesn't ask for one
    noai = work / "noai"
    new_kit(noai)
    (noai / "data" / "kit.json").write_text(
        json.dumps(
            {"settings": {}, "models": [{"id": "Tiny", "enabled": False}], "library": [], "maps": {"enabled": False}}
        )
    )
    rc, out = kit("test", root=noai)
    check(
        "test: a kit with every model off doesn't ask for one",
        "models present" not in out and "without the AI" in out,
        out,
    )

    # Another program on the library's port: the library starts on the next one. Both ports are below the range a
    # computer picks the local end of an outgoing connection from (32768 and up on Linux, 49152 on a Mac): a port held
    # by such an end looks free, since nothing answers there, but no server can start on it. The fake library quits
    # soon after the launcher's first look, which ends the launcher, however slow the computer is.
    class Other(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"another program")

        def log_message(self, *a):
            pass

    for other_port in range(20000, 32000, 2):
        try:
            other = http.server.ThreadingHTTPServer(("127.0.0.1", other_port), Other)
        except OSError:
            continue
        try:
            with socket.socket() as s:
                s.bind(("127.0.0.1", other_port + 1))
            break
        except OSError:
            other.server_close()
    threading.Thread(target=other.serve_forever, daemon=True).start()
    fake = work / "fake-kiwix-serve"
    fake.write_text(f"""#!{sys.executable}
import http.server, sys, threading
if "--port" not in sys.argv:
    sys.exit(0)
def stop(after):
    t = threading.Timer(after, server.shutdown)
    t.daemon = True
    t.start()
class Page(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"<title>Tinfoil Kit</title>")
        stop(2)
    def log_message(self, *a):
        pass
server = http.server.HTTPServer(("127.0.0.1", int(sys.argv[sys.argv.index("--port") + 1])), Page)
stop(30)
server.serve_forever()
""")
    fake.chmod(0o755)
    (lk / "downloads" / "library").mkdir()
    (lk / "downloads" / "library" / "book.zim").touch()
    (lk / "data" / "kit.json").write_text(
        json.dumps(
            {"settings": {"default_model": "Big", "library_port": other_port, "ai_port": rport, "data_port": rport}}
        )
    )
    p = subprocess.run(
        ["bash", str(launcher), "--no-browser"],
        capture_output=True,
        text=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
        env={**os.environ, "KIT_KIWIX_TOOLS_BIN": str(fake)},
    )
    out = p.stdout + p.stderr
    check(
        "launcher: another program on the library's port: it moves to the next free one",
        f"using port {other_port}, so the library uses" in out
        and "Library:  ready" in out
        and f":{other_port}/" not in out,
        out,
    )
    other.shutdown()
    other.server_close()

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
        (lk / "data" / "kit.json").write_text(
            json.dumps(
                {"settings": {"default_model": "Big", "library_port": lport, "ai_port": rport, "data_port": rport}}
            )
        )
        p = subprocess.Popen(
            ["bash", str(launcher), "--no-browser"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            stdin=subprocess.DEVNULL,
            env={**os.environ, "KIT_KIWIX_TOOLS_BIN": str(refusing)},
        )
        lines = []
        threading.Thread(target=lambda: [lines.append(x) for x in p.stdout], daemon=True).start()
        end = time.time() + 60
        while time.time() < end and not any("Keep this window open" in x for x in lines):
            time.sleep(0.2)
        try:
            pages = [urllib.request.urlopen(f"http://127.0.0.1:{lport}/", timeout=10).read() for _ in range(3)]
        except OSError as e:
            pages = [str(e).encode()]
        out = "".join(lines)
        check(
            "launcher: a library server that won't use 127.0.0.1 listens on ::1, and the library answers at 127.0.0.1",
            "forwards 127.0.0.1" in out
            and "Library:  ready" in out
            and f"Open:     http://127.0.0.1:{lport}/" in out
            and all(pg.startswith(b"<title>Tinfoil Kit</title>") and len(pg) == 200026 for pg in pages),
            out,
        )
        p.terminate()
        try:
            p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            p.kill()
        time.sleep(0.5)
        with socket.socket() as s:
            stopped = s.connect_ex(("127.0.0.1", lport)) != 0
        check("launcher: closing it stops the library's forwarder too", stopped)
        (noai / "downloads" / "library").mkdir(parents=True, exist_ok=True)
        (noai / "downloads" / "library" / "book.zim").touch()
        rc, out = kit("test", root=noai, env={**env, "KIT_KIWIX_TOOLS_BIN": str(refusing)})
        check(
            "test: a library server that won't use 127.0.0.1 is tested on ::1, where the launcher runs it",
            "PASS  library server starts" in out and "tested on ::1" in out,
            out,
        )

    # Where you live: ./kit region and the list of places in tools/regions.json (the real one)
    rk = work / "region kit"
    new_kit(rk)
    regions = json.loads((CODE / "tools" / "regions.json").read_text())
    shutil.copy(CODE / "kit.json", rk / "data" / "kit.json")

    def rk_cfg():
        c = json.loads((rk / "data" / "kit.json").read_text())
        return c["maps"], [z for z in c["library"] if z["zim"].startswith("wikipedia_")]

    def ids(out):
        return [line.split("\t")[0] for line in out.splitlines() if "\t" in line]

    rc, out = kit("region", root=rk)
    check(
        "region: says where the maps are for and Wikipedia's language",
        rc == 0 and "Maps are for US Northeast" in out and "Wikipedia is in English" in out,
        out,
    )
    rc, out = kit("region", "--find", "georgia", root=rk)
    check("region --find: a name two places share lists both", rc == 0 and ids(out) == ["us/georgia", "georgia"], out)
    rc, out = kit("region", "--find", "UK", root=rk)
    check("region --find: what people call a country", rc == 0 and ids(out)[:1] == ["united-kingdom"], out)
    rc, out = kit("region", "--find", "Munich", root=rk)
    check("region --find: a big town finds its place", rc == 0 and ids(out) == ["bayern"], out)
    rc, out = kit("region", "--find", root=rk)
    check("region --find with nothing lists every place", rc == 0 and len(ids(out)) == len(regions["regions"]) > 200)
    rc, out = kit("region", "Washington", root=rk)
    check(
        "region: a name two places share asks which",
        rc == 1 and "could be" in out and "us/district-of-columbia" in out and "us/washington" in out,
        out,
    )
    rc, out = kit("region", "georgia", root=rk)
    check("region: an id is that place (SETUP passes ids)", rc == 0 and rk_cfg()[0]["region"] == "georgia", out)
    rc, out = kit("region", "Atlantis", root=rk)
    check("region: a place it doesn't know", rc == 1 and 'No place matches "Atlantis"' in out, out)
    rc, out = kit("region", "--languages", "Bavaria", root=rk)
    check(
        "region --languages: the place's own first, then English",
        rc == 0 and out.startswith("de\t") and any(line.startswith("en\t") for line in out.splitlines()),
        out,
    )
    rc, out = kit("region", "--languages", "Malawi", root=rk)
    check(
        "region --languages: a small Wikipedia comes only with English",
        rc == 0 and [line.split("\t")[0] for line in out.splitlines()] == ["en", "ny,en"],
        out,
    )
    was = rk_cfg()[1]
    rc, out = kit("region", "Bavaria", "--wikipedia", "de,en", root=rk)
    maps, wiki = rk_cfg()
    lib = json.loads((rk / "data" / "kit.json").read_text())["library"]
    check(
        "region: sets the maps and swaps Wikipedia in place, keeping its settings",
        rc == 0
        and "Maps: Germany: Bayern" in out
        and "Address search: all of Germany." in out
        and maps["region"] == "bayern"
        and [z["zim"] for z in wiki] == ["wikipedia_de_all_maxi", "wikipedia_en_all_maxi"]
        and lib.index(wiki[0])
        == [z["zim"] for z in json.loads((CODE / "kit.json").read_text())["library"]].index(was[0]["zim"])
        and all(
            {k: v for k, v in z.items() if k not in ("zim", "note")}
            == {k: v for k, v in was[0].items() if k not in ("zim", "note")}
            for z in wiki
        ),
        out,
    )
    both_gb = int(kit("estimate", root=rk)[1].strip())
    rc, out = kit("region", "--wikipedia", "de", "Bavaria", root=rk)
    de_gb = int(kit("estimate", root=rk)[1].strip())
    check("region: the estimate follows Wikipedia's languages", rc == 0 and de_gb < both_gb - 100, (both_gb, de_gb))
    rc, out = kit("region", "Texas", root=rk)
    check(
        "region: without --wikipedia, Wikipedia stays as it is",
        rc == 0
        and rk_cfg()[0]["region"] == "us/texas"
        and [z["zim"] for z in rk_cfg()[1]] == ["wikipedia_de_all_maxi"],
        out,
    )
    rc, out = kit("region", "Texas", "--wikipedia", "xx", root=rk)
    check(
        "region: a language Wikipedia doesn't come in",
        rc == 1 and "doesn't come in 'xx'" in out and rk_cfg()[0]["region"] == "us/texas",
        out,
    )
    # How much of Wikipedia
    kit("region", "--wikipedia", "en", root=rk)
    rc, out = kit("region", "--sizes", root=rk)
    sizes = [line.split("\t") for line in out.splitlines()]
    check(
        "region --sizes: the sizes Kiwix makes in its languages, biggest first, with GB",
        rc == 0
        and [s[0] for s in sizes] == ["all", "all-text", "top", "top-text", "top-intros"]
        and sizes[0][1] == "All of it, with pictures"
        and float(sizes[3][2]) < 10 < float(sizes[1][2]),
        out,
    )
    was, full_gb = rk_cfg()[1][0], int(kit("estimate", root=rk)[1].strip())
    rc, out = kit("region", "--wikipedia-size", "top-text", root=rk)
    now = rk_cfg()[1]
    check(
        "region --wikipedia-size: swaps Wikipedia for that size in place, keeping its settings, and leaves the maps be",
        rc == 0
        and [z["zim"] for z in now] == ["wikipedia_en_top_nopic"]
        and "the best 50,000 articles, text only" in out
        and {k: v for k, v in now[0].items() if k not in ("zim", "note")}
        == {k: v for k, v in was.items() if k not in ("zim", "note")}
        and "Maps:" not in out
        and rk_cfg()[0]["region"] == "us/texas"
        and int(kit("estimate", root=rk)[1].strip()) < full_gb - 100,
        out,
    )
    rc, out = kit("region", root=rk)
    check(
        "region: says how much of Wikipedia",
        rc == 0 and "Wikipedia is in English: the best 50,000 articles, text only" in out,
        out,
    )
    rc, out = kit("region", "Bavaria", "--wikipedia", "de,en", root=rk)
    check(
        "region: a new language comes in the size Wikipedia has",
        rc == 0
        and [z["zim"] for z in rk_cfg()[1]] == ["wikipedia_de_top_nopic", "wikipedia_en_top_nopic"]
        and "German and English, the best 50,000" in out,
        out,
    )
    rc, out = kit("region", "--wikipedia-size", "huge", root=rk)
    check(
        "region --wikipedia-size: a size it doesn't know",
        rc == 1 and "all, all-text, top, top-text, top-intros" in out,
        out,
    )
    rc, out = kit("region", "Texas", "--wikipedia", "de", "--wikipedia-size", "all", root=rk)
    check(
        "region: a place, a language and a size at once",
        rc == 0
        and rk_cfg()[0]["region"] == "us/texas"
        and [z["zim"] for z in rk_cfg()[1]] == ["wikipedia_de_all_maxi"],
        out,
    )
    wide = next(r for r in regions["regions"] if r.get("addresses_wide"))
    rc, out = kit("region", wide["id"], root=rk)
    check(
        "region: a place with only a continent's address search says so, and how big it is",
        rc == 0 and f"Address search: all of {wide['addresses']}" in out and "Just the essentials leave it out" in out,
        out,
    )
    # Places nearby, after where you live: someone near a state line wants the next state's streets and directions too
    rc, out = kit("region", "New York, New Jersey", root=rk)
    check(
        "region: places nearby after commas: maps and directions for each, home and address search from the first",
        rc == 0
        and rk_cfg()[0]["region"] == ["us/new-york", "us/new-jersey"]
        and "Maps: New York and New Jersey." in out
        and "Address search: all of the United States." in out
        and "Not for" not in out
        and "Home: New York" in out,
        out,
    )
    rc, out = kit("region", root=rk)
    check("region: says which places the maps are for", rc == 0 and "Maps are for New York and New Jersey" in out, out)
    # as cmd hands SETUP-Windows.bat new-york,new-jersey
    rc, out = kit("region", "us/new-york", "us/new-jersey", "us/new-york", root=rk)
    check(
        "region: ids with spaces between them are places too, each once",
        rc == 0 and rk_cfg()[0]["region"] == ["us/new-york", "us/new-jersey"],
        out,
    )
    rc, out = kit("region", "Bavaria, Austria", root=rk)
    check(
        "region: a place in another country is on the map, and address search is the first place's",
        rc == 0
        and rk_cfg()[0]["region"] == ["bayern", "austria"]
        and "Address search: all of Germany." in out
        and "Not for Austria: the kit has one address search, the first place's." in out,
        out,
    )
    rc, out = kit("region", "Texas, Atlantis", root=rk)
    check(
        "region: a place it doesn't know among several changes nothing",
        rc == 1 and 'No place matches "Atlantis"' in out and rk_cfg()[0]["region"] == ["bayern", "austria"],
        out,
    )
    rc, out = kit("region", "--languages", root=rk)
    check("region --languages: where you live's, the first place's", rc == 0 and out.startswith("de\t"), out)
    rc, out = kit("region", "US Northeast (CT, MA, ME, NH, NJ, NY, PA, RI, VT)", root=rk)
    check("region: a place whose name has commas in it", rc == 0 and rk_cfg()[0]["region"] == "us-northeast", out)

    # ./kit copy: a copy of a kit on another drive, as much as fits. The kit is made here as a sync leaves one: the
    # programs for each computer (this one's are stand-ins that run the mocks, so the copy's own test passes), the map
    # with directions and address search, two AI models and five books. KIT_DRIVES holds the drives plugged in, both
    # KIT_DRIVE_BYTES big and formatted as KIT_DRIVE_FORMAT says.
    drives = work / "Volumes"
    big = new_kit(drives / "BIG ONE" / "TinfoilKit")
    items = {}

    def put(key, dest, tree, **record):
        """An item as a sync leaves it: its files in downloads/dest (a number makes a file that big with nothing in it,
        which takes no room here), and its record."""
        for rel, data in tree.items():
            p = big / "downloads" / dest / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(data, int):
                with open(p, "wb") as f:
                    f.truncate(data)
            else:
                p.write_bytes(data)
                p.chmod(0o755 if data.startswith(b"#!") else 0o644)
        items[key] = {"version": "1", "dest": dest, "updated": "2026-11-20T10:00:00Z", **record}

    def files(key, dest, tree):
        sums = {n: "0" * 64 if isinstance(d, int) else hashlib.sha256(d).hexdigest() for n, d in tree.items()}
        put(
            key,
            dest,
            tree,
            files={n: {"size": d if isinstance(d, int) else len(d), "sha256": sums[n]} for n, d in tree.items()},
        )

    def program(key, dest, tree, version="1.0"):
        """A program unpacked: the version in use, which CURRENT names, beside the one before it."""
        tree = {
            "CURRENT": f"{version}\n".encode(),
            "0.9/old": b"the version before",
            **{f"{version}/{r}": d for r, d in tree.items()},
        }
        put(
            key,
            dest,
            tree,
            current=version,
            versions=[version, "0.9"],
            archive="program.tar.gz",
            archive_sha256="0" * 64,
        )

    stand_in = (
        f"#!{sys.executable}\nimport http.server, os, re, sys\na = sys.argv[1:]\nport = int(a[a.index('--port') + 1])\n"
    )
    kiwix = (
        stand_in
        + """page = open(a[a.index("--customIndex") + 1], "rb").read().replace(b"{{=<% %>=}}", b"")
books = [os.path.basename(z)[:-4] for z in a if z.endswith(".zim")]
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/catalog"):
            body = "".join(f'<entry><link type="text/html" href="/content/{b}"/></entry>' for b in books).encode()
        else:
            body = b"<item>Water</item>" if self.path.startswith("/search") else page
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a):
        pass
http.server.ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
"""
    )
    llama = (
        stand_in
        + """ids = re.findall(r"^\\[(.+)\\]$", open(a[a.index("--models-preset") + 1]).read(), re.M)
class H(http.server.BaseHTTPRequestHandler):
    def reply(self, body):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body.encode())
    def do_GET(self):
        self.reply('{"data": [' + ", ".join('{"id": "%s"}' % i for i in ids) + "]}")
    def do_POST(self):
        self.reply('{"choices": [{"message": {"content": "OK"}}]}')
    def do_OPTIONS(self):
        self.reply("")
    def log_message(self, *a):
        pass
http.server.ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
"""
    )
    for computer, exe in (("macos-arm64", ""), ("windows-x64", ".exe"), ("linux-x64", "")):
        me = computer == PLAT
        program(
            f"runtimes/llama.cpp-{computer}",
            f"bin/llama.cpp-{computer}",
            {f"build/bin/llama-server{exe}": llama.encode() if me else b"llama", "build/bin/libggml.so": b"lib" * 900},
        )
        program(
            f"runtimes/kiwix-tools-{computer}",
            f"bin/kiwix-tools-{computer}",
            {f"kiwix-serve{exe}": kiwix.encode() if me else b"kiwix"},
        )
        java = (TESTS / "fakes" / "java").read_bytes() if me else b"java"
        program(f"runtimes/java-{computer}", f"bin/java-{computer}", {f"jdk-21.0.9+10-jre/bin/java{exe}": java})
        pmtiles = (TESTS / "fakes" / "pmtiles").read_bytes() if me else b"pmtiles"
        program(f"runtimes/pmtiles-{computer}", f"bin/pmtiles-{computer}", {f"pmtiles{exe}": pmtiles})
    files("runtimes/graphhopper", "bin/graphhopper", {"graphhopper-web-11.0.jar": b"jar" * 1000})
    files("runtimes/photon", "bin/photon", {"photon-1.3.0.jar": b"jar" * 1000})
    program(
        "maps/maplibre-gl",
        "maps/viewer/maplibre-gl",
        {"package/dist/maplibre-gl.js": b"//", "package/dist/maplibre-gl.css": b"/**/"},
    )
    program("maps/protomaps-basemaps", "maps/viewer/protomaps-basemaps", {"package/dist/basemaps.js": b"// style"})
    program(
        "maps/basemaps-assets",
        "maps/viewer/basemaps-assets",
        {
            "a/fonts/Noto Sans Regular/0-255.pbf": b"font",
            "a/sprites/v4/light.json": b"{}",
            "a/sprites/v4/light.png": b"png",
        },
    )
    files("maps/basemap", "maps/tiles", {"basemap.pmtiles": os.urandom(150_000)})
    roads = os.urandom(5000)
    put(
        "maps/routing",
        "maps/routing",
        {
            "ny.osm.pbf": roads,
            "graph-cache/properties": b"graph",
            "gh-serve.yml": b"x: 1\n",
            "graph-cache.old/edges": b"old",
        },
        files={"ny.osm.pbf": {"size": 5000, "sha256": hashlib.sha256(roads).hexdigest()}},
        unpacked_size=5,
    )
    put("maps/geocoder", "maps/geocoder", {"photon_data/node_1/index": os.urandom(400_000)}, unpacked_size=400_000)
    files("models/Small", "models/Small", {"Small-Q4_K_M.gguf": os.urandom(250_000)})
    files("models/Big", "models/Big", {"Big-Q4_K_M.gguf": 3 * 10**9})
    books = {"medicine_en_all": 90_000, "water_en": 50_000, "wikipedia_en_top_nopic": 120_000, "crafts_en": 60_000}
    for zim, size in {**books, "wikipedia_en_all_maxi": 4 * 10**9}.items():
        files(f"library/{zim}", "library", {f"{zim}_2026-11.zim": os.urandom(size) if size < 10**9 else size})
    (big / "downloads" / "library" / "crafts_en_2026-12.zim.partial").write_bytes(b"a newer one, partway")
    (big / "data" / ".kit").mkdir(parents=True)
    (big / "data" / ".kit" / "state.json").write_text(json.dumps({"last_sync": "2026-11-20T10:00:00Z", "items": items}))
    (big / "data" / "kit.json").write_text(
        json.dumps(
            {
                "settings": {"default_model": "Big", "share_on_network": True},
                "models": [{"id": "Big", "priority": 1}, {"id": "Small", "priority": 1}],
                "maps": {"enabled": True, "region": "us/new-york"},
                "library": [
                    {"zim": "medicine_en_all", "priority": 1},
                    {"zim": "water_en", "priority": 1},
                    {"zim": "wikipedia_en_top_nopic"},
                    {"zim": "crafts_en", "priority": 3},
                    {"zim": "wikipedia_en_all_maxi"},
                ],
            },
            indent=2,
        )
    )
    (big / "app" / "tools" / "sources.json").write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "id": "medicine_en_all",
                        "title": "Medicine",
                        "group": "Health",
                        "why": "For when there's no doctor.",
                    },
                    {"id": "water_en", "title": "Water", "group": "Survival", "why": "Finding it and making it safe."},
                    {"id": "Small", "title": "Small AI", "why": "Runs on any laptop."},
                ]
            }
        )
    )
    notes = "Water shutoff is behind the boiler.\n"
    (big / "data" / "notes.txt").write_text(notes)
    (big / "data" / "places.json").write_text(json.dumps({"pins": [{"lat": 40.7, "lon": -74, "label": "Aunt Sue"}]}))
    kit("layout", root=big)  # (every command keeps the launchers beside its three folders)

    small = drives / "LITTLE ONE"
    (small / "photos").mkdir(parents=True)
    (small / "photos" / "beach.jpg").write_bytes(b"jpg")
    copied = small / "TinfoilKit"
    job = big / "data" / ".kit" / "copy.json"
    copy_env = {**env, "KIT_DRIVES": str(drives), "KIT_DRIVE_BYTES": str(2 * 10**9), "KIT_DRIVE_FORMAT": "ExFAT"}
    copy_env.update(KIT_TEST_DIR=str(TESTS), KIT_TEST_WORK=str(work))  # for the stand-ins for Java and pmtiles

    def copy(*args, **e):
        return kit("copy", *args, env={**copy_env, **e}, root=big)

    def in_copy(rel):
        return (copied / rel).exists()

    def copy_cfg():
        return json.loads((copied / "data" / "kit.json").read_text())

    rc, out = copy("--json")
    info = json.loads(out) if rc == 0 else {}
    parts = {p["id"]: p for p in info.get("parts", [])}
    check(
        "copy --json: what the kit has, the programs first, and the drives it could go on, but not its own",
        rc == 0
        and list(parts)[:3] == ["programs", "map", "addresses"]
        and parts["map"]["title"] == "Map with directions"
        and parts["programs"]["why"].endswith("for Mac, Windows and Linux.")
        and parts["medicine_en_all"]["title"] == "Medicine"
        and parts["wikipedia_en_top_nopic"]["title"] == "Wikipedia"
        and parts["wikipedia_en_top_nopic"]["essential"]
        and not parts["crafts_en"]["essential"]
        and parts["Big"]["bytes"] > 3 * 10**9
        and info["ai"] == "Small"
        and info["notes"]
        and [(d["name"], d["mustErase"], d["kit"]) for d in info["drives"]] == [("LITTLE ONE", None, False)],
        out,
    )

    rc, out = copy("LITTLE ONE", "--essentials", "--ai", "--yes")
    state_copy = (
        json.loads((copied / "data" / ".kit" / "state.json").read_text()) if in_copy("data/.kit/state.json") else {}
    )
    check(
        "copy --essentials --ai: the programs, the essential books and the smallest AI, then it reads them back and starts it",
        rc == 0
        and "3 books: Medicine, Water, Wikipedia" in out
        and "Small AI" in out
        and "All " in out
        and "files read back right" in out
        and "PASS  model answers" in out
        and "FAIL" not in out
        and "Done: LITTLE ONE has a Tinfoil Kit of its own, for Mac, Windows and Linux." in out,
        out,
    )
    check(
        "the copy: every computer's programs, in the version in use, the books and the AI, and none of the rest",
        all(in_copy(f"downloads/bin/llama.cpp-{c}/1.0") for c in ("macos-arm64", "windows-x64", "linux-x64"))
        and not in_copy("downloads/bin/llama.cpp-linux-x64/0.9")
        and in_copy("app/tools/tinfoilkit-windows-x64.exe")
        and (copied / "downloads/library/water_en_2026-11.zim").read_bytes()
        == (big / "downloads/library/water_en_2026-11.zim").read_bytes()
        and in_copy("downloads/models/Small/Small-Q4_K_M.gguf")
        and not in_copy("downloads/models/Big")
        and not in_copy("downloads/maps")
        and not in_copy("downloads/library/crafts_en_2026-11.zim")
        and not in_copy("downloads/library/crafts_en_2026-12.zim.partial")
        and not in_copy("data/notes.txt")
        and sorted(p.name for p in copied.iterdir()) == [*TOP, "app", "data", "downloads"]
        and (small / "photos" / "beach.jpg").exists()
        and not (small / "TinfoilKit.partial").exists(),
        sorted(str(p.relative_to(copied)) for p in copied.rglob("*") if "downloads" in str(p)),
    )
    c = copy_cfg()
    check(
        "the copy's kit.json switches on just what it has, its records list just that, and it's someone else's home network",
        [m.get("enabled", True) for m in c["models"]] == [False, True]
        and [z.get("enabled", True) for z in c["library"]] == [True, True, True, False, False]
        and c["maps"]["enabled"] is False
        and c["settings"]["default_model"] == "Small"
        and c["settings"]["share_on_network"] is False
        and c["settings"]["picked"] is True
        and sorted(state_copy.get("items", {}))
        == [
            "library/medicine_en_all",
            "library/water_en",
            "library/wikipedia_en_top_nopic",
            "models/Small",
            *(
                f"runtimes/{p}-{c}"
                for p in ("kiwix-tools", "llama.cpp")
                for c in ("linux-x64", "macos-arm64", "windows-x64")
            ),
        ]
        and state_copy["items"]["runtimes/llama.cpp-linux-x64"]["versions"] == ["1.0"],
        json.dumps(c) + json.dumps(sorted(state_copy.get("items", {}))),
    )
    card = (copied / "data" / ".kit" / "card.html").read_text() if in_copy("data/.kit/card.html") else ""
    check(
        "the copy has a card to print, and this kit keeps one for its page, with how to start it on each computer",
        "An AI and a library that work without the internet, all on the drive <b>LITTLE ONE</b>." in card
        and "Open Tinfoil Kit for Windows" in card
        and "Ask and AI chat, with the AI Small AI" in card
        and "3 books: Medicine, Water, Wikipedia" in card
        and (big / "data" / ".kit" / "card.html").read_text() == card
        and json.loads(job.read_text())["step"] == "done"
        and json.loads(job.read_text())["works"] is True,
        card,
    )

    before = sorted(str(f.relative_to(copied)) for f in copied.rglob("*"))
    rc, out = copy("LITTLE ONE", "--maps", "--notes", "--json")
    plan = json.loads(out) if rc == 0 else {}
    check(
        "copy DRIVE --json: what that copy would be and what it does to the drive, without copying",
        plan.get("drive") == "LITTLE ONE"
        and plan.get("parts", [])[:1] == ["programs"]
        and "map" in plan.get("parts", [])
        and plan.get("replace") is True
        and plan.get("erase") is False
        and plan.get("notes") is True
        and "The copy replaces it" in plan.get("warning", "")
        and plan.get("bytes", 0) > 0
        and sorted(str(f.relative_to(copied)) for f in copied.rglob("*")) == before,
        out,
    )
    rc, out = copy("LITTLE ONE", "--maps", "--notes")
    check(
        "copy to a drive with a kit: says it replaces it, keeping its notes, and doesn't without the drive's name",
        rc == 1
        and "  Your notes, home and map pins, if it has none of its own" in out
        and "LITTLE ONE has a Tinfoil Kit already. The copy replaces it" in out
        and 'To go ahead, add --erase "LITTLE ONE".' in out
        and in_copy("downloads/models/Small"),
        out,
    )
    rc, out = copy("LITTLE ONE", "--maps", "--notes", "--erase", "little one")
    c = copy_cfg()
    check(
        "copy --maps --notes --erase NAME: replaces the kit there with the map, its address search and the notes, and tests the map",
        rc == 0
        and "Map with directions" in out
        and "Address search" in out
        and "PASS  directions work" in out
        and "PASS  address search works" in out
        and "FAIL" not in out
        and not in_copy("downloads/models/Small")
        and in_copy("downloads/maps/geocoder/photon_data/node_1/index")
        and in_copy("downloads/maps/routing/graph-cache/properties")
        and not in_copy("downloads/maps/routing/graph-cache.old")
        and not in_copy("downloads/maps/viewer/maplibre-gl/0.9")
        and (copied / "data" / "notes.txt").read_text() == notes
        and c["maps"]["enabled"] is True
        and "geocoder_country" not in c["maps"]
        and [m.get("enabled", True) for m in c["models"]] == [False, False]
        and (small / "photos" / "beach.jpg").exists(),
        out,
    )
    (big / "data" / "notes.txt").write_text("changed since")
    rc, out = copy("LITTLE ONE", "--essentials", "--notes", "--erase", "LITTLE ONE")
    check(
        "a copy never overwrites the notes on a kit it replaces",
        rc == 0 and (copied / "data" / "notes.txt").read_text() == notes and not in_copy("downloads/maps"),
        out,
    )
    (big / "data" / "notes.txt").write_text(notes)

    # Stopped partway: a copy carries on, and a file that reads back wrong is copied again
    os.rename(copied, small / "TinfoilKit.partial")
    water = small / "TinfoilKit.partial" / "downloads" / "library" / "water_en_2026-11.zim"
    water.write_bytes(b"x" * water.stat().st_size)
    rc, out = copy("--json")
    info = json.loads(out) if rc == 0 else {}
    rc, out = copy("LITTLE ONE", "--essentials", "--yes")
    check(
        "a copy that stopped partway carries on, and a file that reads back wrong is copied again",
        rc == 0
        and info["drives"][0]["partial"] is True
        and "1 of them didn't read back as they went in. Copying those again..." in out
        and (copied / "downloads/library/water_en_2026-11.zim").read_bytes()
        == (big / "downloads/library/water_en_2026-11.zim").read_bytes()
        and not (small / "TinfoilKit.partial").exists(),
        out,
    )

    # A drive too full for the copy: it must be erased first
    (small / "movie.mp4").write_bytes(b"m")
    os.truncate(small / "movie.mp4", 1_500_000_000)
    rc, out = copy("LITTLE ONE", "--maps", "--yes")
    check(
        "a drive too full for the copy: it needs erasing first, and says everything on it goes, naming what's there",
        rc == 1
        and "LITTLE ONE has" in out
        and "so it needs erasing first. Everything on LITTLE ONE goes, including TinfoilKit, movie.mp4 and photos."
        in out
        and 'To go ahead, add --erase "LITTLE ONE".' in out
        and (small / "photos" / "beach.jpg").exists(),
        out,
    )
    rc, out = copy("LITTLE ONE", "--maps", "--erase", "LITTLE ONE")
    check(
        "erased, it takes the copy",
        rc == 0
        and "Erasing LITTLE ONE as exFAT..." in out
        and not (small / "photos").exists()
        and not (small / "movie.mp4").exists()
        and in_copy("downloads/maps/tiles/basemap.pmtiles"),
        out,
    )

    rc, out = copy("LITTLE ONE", "--everything", "--add", "Big", "--yes", KIT_DRIVE_FORMAT="MS-DOS (FAT32)")
    check(
        "a drive that can't hold big files: it needs erasing; and what doesn't fit even then says so",
        rc == 1 and "That's 3.0 GB" in out and "has room for" in out and "Pick less." in out,
        out,
    )
    rc, out = copy("LITTLE ONE", "--essentials", "--yes", KIT_DRIVE_FORMAT="MS-DOS (FAT32)")
    check(
        "a drive that can't hold big files: it needs erasing first",
        rc == 1 and "LITTLE ONE needs erasing first: it's formatted as MS-DOS (FAT32), which can't hold" in out,
        out,
    )
    rc, out = copy("LITTLE ONE", "--only", "water,maps", "--yes", "--erase", "LITTLE ONE")
    c = copy_cfg()
    check(
        "copy --only: just those, and the programs",
        rc == 0
        and "1 book: Water" in out
        and "Map with directions" in out
        and "Address search" not in out
        and c["maps"]["geocoder_country"] == ""
        and not in_copy("downloads/maps/geocoder")
        and "SKIP  address search" in out,
        out,
    )
    rc, out = copy("LITTLE ONE", "--only", "atlantis", "--yes")
    check(
        "copy --only: a name the kit doesn't have says so", rc == 1 and "This kit has no atlantis to copy." in out, out
    )

    # At a keyboard: it asks which drive, what goes on it, the AI and the notes, then for the drive's name
    import pty

    keyboard, tty = pty.openpty()
    os.write(keyboard, b"1\n1\ny\ny\nlittle one\n")
    try:
        p = subprocess.run(
            kit_cmd(big / "app", big, "copy"), env=copy_env, stdin=tty, capture_output=True, text=True, timeout=180
        )
    finally:
        os.close(keyboard)
        os.close(tty)
    out = p.stdout + p.stderr
    check(
        "copy at a keyboard: which drive, what goes on it, the AI and the notes, then the drive's name to replace its kit",
        p.returncode == 0
        and "Add the AI too? Small AI" in out
        and "What goes on LITTLE ONE?" in out
        and "Copy your notes and map pins too?" in out
        and "Type LITTLE ONE to go ahead" in out
        and in_copy("downloads/models/Small")
        and (copied / "data" / "notes.txt").exists(),
        out,
    )

    # A TinfoilKit folder with other things in it is never replaced
    (copied / "my letters").mkdir()
    rc, out = copy("--json")
    info = json.loads(out) if rc == 0 else {}
    check(
        "a TinfoilKit folder with other things in it is never replaced: only erasing the drive, once asked",
        rc == 0 and info["drives"][0]["mustErase"] == "its TinfoilKit folder has other things in it besides the kit",
        out,
    )
    (copied / "my letters").rmdir()

    # Damaged on this kit: it says which, and how to fix it
    w = big / "downloads" / "library" / "crafts_en_2026-11.zim"
    good = w.read_bytes()
    w.write_bytes(b"y" * len(good))
    rc, out = copy("LITTLE ONE", "--only", "crafts", "--yes", "--erase", "LITTLE ONE")
    check(
        "a file this kit has that isn't what it downloaded: the copy stops and says how to fix it",
        rc == 1
        and "This kit's own copy of crafts_en is damaged: downloads/library/crafts_en_2026-11.zim" in out
        and "verify --fix" in out
        and not in_copy("downloads/library/crafts_en_2026-11.zim"),
        out,
    )
    w.write_bytes(good)

    # Make a copy, on the kit page: its page asks the notes server, on that server's own address, which runs ./kit
    # copy and follows copy.json
    (drives / "PAGE ONE").mkdir()
    dport = free_port()
    notes = subprocess.Popen(
        [str(big / "app" / "tools" / PROGRAM.name), "data", "--data", str(big / "data"), "--port", str(dport)]
        + ["--library", "18888"],
        env=copy_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    def page(method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", dport, timeout=150)
        h = {"Origin": f"http://127.0.0.1:{dport}", **({"Content-Type": "application/json"} if body else {})}
        c.request(method, path, body=json.dumps(body).encode() if body else None, headers=h)
        r = c.getresponse()
        text = r.read()
        c.close()
        return r.status, json.loads(text) if text.startswith(b"{") else text

    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", dport), timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        _, info = page("GET", "/copy/info")
        _, plan = page("GET", "/copy/plan?drive=PAGE+ONE&preset=essentials&ai=1")
        status, job = page("PUT", "/copy/job", {"drive": str(drives / "PAGE ONE"), "preset": "essentials", "ai": True})
        for _ in range(600):
            if status != 200 or not job.get("running"):
                break
            time.sleep(0.2)
            status, job = page("GET", "/copy/job")
        _, card = page("GET", "/copy/card")
        check(
            "Make a copy: the page gets the drives and a plan, then the copy it starts is followed to the end, with its card",
            "PAGE ONE" in [d["name"] for d in info.get("drives", [])]
            and plan.get("parts", [])[:2] == ["programs", "Small"]
            and plan.get("erase") is False
            and plan.get("replace") is False
            and job.get("step") == "done"
            and job.get("works") is True
            and job.get("card") is True
            and b"Open Tinfoil Kit for Windows" in card
            and (drives / "PAGE ONE" / "TinfoilKit" / "downloads" / "models" / "Small").exists(),
            json.dumps(plan) + json.dumps(job),
        )
        status, job = page("PUT", "/copy/job", {"drive": str(drives / "PAGE ONE"), "preset": "maps"})
        for _ in range(100):
            if status != 200 or not job.get("running"):
                break
            time.sleep(0.2)
            status, job = page("GET", "/copy/job")
        check(
            "the kit on a drive is replaced only once the drive's name is typed",
            job.get("step") == "failed" and 'add --erase "PAGE ONE"' in job.get("message", ""),
            json.dumps(job),
        )
    finally:
        notes.kill()
finally:
    mock.terminate()
    shutil.rmtree(work, ignore_errors=True)

print("\nALL PASSED" if not fails else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
