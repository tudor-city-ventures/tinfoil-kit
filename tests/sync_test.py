"""Sync engine test: runs the real kit.py against the mock internet (tests/mock_remote.py) with tiny
made-up books and models. Covers downloads, resume, checksums, updates, leftover partial downloads,
verify --fix, adopting files already on the drive, offline runs, exit codes, and SETUP.command's choices.
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
    check("offline: sync stops with one clear message", rc == 1 and "Check that this Mac is online" in out
          and "Problems" not in out and out.count("Kiwix catalog") <= 3, out)
    (drive / ".kit/cache").mkdir(exist_ok=True)
    portal = env["KIT_KIWIX_CATALOG"].replace("/catalog/v2/entries?count=-1", "/wifi-sign-in")
    rc, out = kit("plan", env={**off, "KIT_KIWIX_CATALOG": portal})
    check("Wi-Fi sign-in page: plan says so and nothing is cached",
          rc == 1 and not (drive / ".kit/cache/kiwix-catalog.xml").exists(), out)

    # ./kit update: a kit on the drive, its kit.json changed by its owner, and releases of the kit's code
    # published on the mock GitHub. site/kit.json is the copy of kit.json the kit's current version came with.
    up = work / "update" / "TinfoilKit"
    code = {rel: (TESTS.parent / rel).read_bytes() for rel in ("kit", "SETUP.command", "START-HERE.command")}
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
    setup = work / "setup"
    setup.mkdir()
    (setup / "kit").write_text("""#!/bin/bash
echo "kit $1" >> calls.log
case "$1" in
  update) [ "$UPDATE" = 3 ] && sed 's/Step 1 of 2:/Step 1 of 2 (new version):/' SETUP.command > new && cat new > SETUP.command
          exit $UPDATE;;
  plan) exit $PLAN;;
  sync) mkdir -p logs; echo "===== sync started =====" >> logs/sync-2026-01-01.log
        [ $SYNC = 1 ] && printf 'Problems (everything else is done):\n  - models/Big: download failed\nRe-run ./kit sync\n' >> logs/sync-2026-01-01.log
        exit $SYNC;;
  test) exit $TEST;;
esac""")
    (setup / "kit").chmod(0o755)

    def run_setup(plan=0, sync=0, test=0, update=0):
        shutil.copy(TESTS.parent / "SETUP.command", setup)
        (setup / "calls.log").write_text("")
        p = subprocess.run(["bash", "SETUP.command"], cwd=setup, input="y\nn\n\n", capture_output=True, text=True, timeout=60,
                           env={**os.environ, "PLAN": str(plan), "SYNC": str(sync), "TEST": str(test), "UPDATE": str(update)})
        return p.returncode, p.stdout, (setup / "calls.log").read_text().split()[1::2]

    rc, out, calls = run_setup()
    check("SETUP: all good", rc == 0 and "All set" in out and calls == ["update", "plan", "sync", "test"], out)
    rc, out, calls = run_setup(update=3)
    check("SETUP: after updating the kit it starts over on the new SETUP, once",
          rc == 0 and "Step 1 of 2 (new version):" in out and out.count("TINFOIL KIT SETUP") == 1
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
finally:
    mock.terminate()
    shutil.rmtree(work, ignore_errors=True)

print("\nALL PASSED" if not fails else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
