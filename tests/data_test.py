"""The server that keeps the kit page's notes, pins and home in the kit's data folder: tools/data.py, then the kit's own
program's (tools/tinfoilkit data), which must pass the same checks. What it saves, what it turns away (other web
pages, other names for this computer, bad input), and that a save is all or nothing."""
import http.client
import json
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
fails = 0
who = ""


def check(name, ok, detail=""):
    global fails
    name = f"{who}: {name}"
    print(("PASS  " + name) if ok else ("FAIL  " + name + (f": {detail}" if detail else "")))
    fails += 0 if ok else 1


def program():
    """The kit's own program for this computer (tools/tinfoilkit-*), if tools/tinfoilkit/build.sh has built it."""
    name = {("Linux", "x86_64"): "linux-x64", ("Darwin", "arm64"): "macos-arm64",
            ("Windows", "AMD64"): "windows-x64.exe"}.get((platform.system(), platform.machine()))
    p = ROOT / "tools" / f"tinfoilkit-{name}"
    return p if name and p.exists() else None


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


lib = 18888
PAGE = f"http://127.0.0.1:{lib}"
port = 0


def req(method, path, body=None, headers=None, raw=None):
    """(status, JSON or None, headers). body is sent as JSON; raw as it is."""
    h = {"Origin": PAGE, **(headers or {})}
    h = {k: v for k, v in h.items() if v is not None}
    payload = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    if payload is not None:
        h.setdefault("Content-Type", "application/json")
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(method, path, body=payload, headers=h)
    r = c.getresponse()
    text = r.read()
    c.close()
    try:
        got = json.loads(text) if text else None
    except ValueError:
        got = text
    return r.status, got, {k.lower(): v for k, v in r.getheaders()}


def checks(server_cmd):
    global port
    work = Path(tempfile.mkdtemp(prefix="data-test-"))
    data, port = work / "kit" / "data", free_port()
    data.mkdir(parents=True)
    server = subprocess.Popen(server_cmd + ["--data", str(data), "--port", str(port), "--library", str(lib)],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        run(server, server_cmd, work, data)
    finally:
        if server.poll() is None:
            server.kill()
        shutil.rmtree(work, ignore_errors=True)


def run(server, server_cmd, work, data):
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            break
        except OSError:
            time.sleep(0.1)
    s, got, h = req("GET", "/")
    check("it answers the kit's page, and says what it is", s == 200 and got == {"name": "Tinfoil Kit", "notes": "/notes", "places": "/places"}
          and h.get("access-control-allow-origin") == PAGE, f"{s} {got} {h}")
    s, got, h = req("GET", "/", headers={"Origin": None})
    check("and a program on this computer (no Origin), without a CORS header", s == 200 and "access-control-allow-origin" not in h)
    s, got, _ = req("GET", "/notes", headers={"Origin": "http://evil.example"})
    check("another web page is turned away", s == 403, str(s))
    s, got, _ = req("GET", "/notes", headers={"Origin": f"http://127.0.0.1:{lib + 1}"})
    check("so is a page on another of this computer's ports", s == 403, str(s))
    s, got, _ = req("GET", "/notes", headers={"Host": f"evil.example:{port}"})
    check("a website's own name pointed at this computer is turned away (DNS rebinding)", s == 403, str(s))
    s, _, h = req("GET", "/notes", headers={"Origin": f"http://localhost:{lib}", "Host": f"localhost:{port}"})
    check("localhost works too", s == 200 and h.get("access-control-allow-origin") == f"http://localhost:{lib}")
    s, _, h = req("OPTIONS", "/notes", headers={"Access-Control-Request-Method": "PUT", "Access-Control-Request-Headers": "content-type"})
    check("the page may save (preflight)", s == 204 and "PUT" in h.get("access-control-allow-methods", "")
          and h.get("access-control-allow-headers", "").lower() == "content-type", f"{s} {h}")
    s, _, _ = req("OPTIONS", "/notes", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "PUT"})
    check("another web page may not", s == 403, str(s))

    s, got, _ = req("GET", "/notes")
    check("no notes yet", s == 200 and got == {"text": "", "version": ""}, str(got))
    s, got, _ = req("PUT", "/notes", {"text": "Sam: no penicillin.\nMeet at the library.", "version": ""})
    v1 = got and got.get("version")
    check("saving notes writes data/notes.txt", s == 200 and (data / "notes.txt").read_text(encoding="utf-8") == "Sam: no penicillin.\nMeet at the library."
          and isinstance(v1, str) and len(v1) == 16, f"{s} {got}")
    s, got, _ = req("PUT", "/notes", {"text": "An old edit", "version": ""})
    check("a save that began from older notes gets them back instead of writing over them", s == 409
          and got.get("text") == "Sam: no penicillin.\nMeet at the library." and got.get("version") == v1
          and (data / "notes.txt").read_text(encoding="utf-8").startswith("Sam"), f"{s} {got}")
    s, got, _ = req("PUT", "/notes", {"text": "Ünïcødé ✓ 日本", "version": v1})
    check("from the version it has, a save goes through, in UTF-8", s == 200 and (data / "notes.txt").read_text(encoding="utf-8") == "Ünïcødé ✓ 日本")
    (data / "notes.txt").write_bytes("﻿Edited in Notepad".encode("utf-8"))
    s, got, _ = req("GET", "/notes")
    check("notes edited in a text editor, BOM and all", got["text"] == "Edited in Notepad", repr(got["text"]))
    s, got, _ = req("PUT", "/notes", {"text": "x" * 100_001, "version": got["version"]})
    check("notes over 100,000 characters are refused", s == 400, str(s))
    s, got, _ = req("PUT", "/notes", raw=b"just text", headers={"Content-Type": "text/plain"})
    check("a save that isn't JSON is refused (and other pages can't send it without asking first)", s == 415, str(s))
    s, got, _ = req("PUT", "/notes", raw=b"[1, 2]")
    check("JSON that isn't an object is refused", s == 400, str(s))
    s, got, _ = req("PUT", "/notes", raw=b"{}", headers={"Content-Length": "2000000"})
    check("a body over 1 MB is refused before it's read", s == 413, str(s))
    s, got, _ = req("POST", "/notes", {"text": "x"})
    s2, _, _ = req("GET", "/nothing")
    check("other methods and paths: 405 and 404", s == 405 and s2 == 404, f"{s} {s2}")

    s, got, _ = req("GET", "/places")
    check("no home or pins yet", s == 200 and got == {"home": None, "pins": []}, str(got))
    s, got, _ = req("PUT", "/places/home", {"lat": 40.7, "lon": -74.0, "label": "Our house", "zoom": 13})
    check("home saved in data/places.json", s == 200 and got["home"] == {"lat": 40.7, "lon": -74.0, "label": "Our house", "zoom": 13}
          and json.loads((data / "places.json").read_text(encoding="utf-8"))["home"]["label"] == "Our house", str(got))
    s, _, _ = req("PUT", "/places/home", {"lat": 91, "lon": 0})
    s2, _, _ = req("PUT", "/places/home", {"lat": 40, "lon": 0, "zoom": 40})
    check("a home that isn't on Earth, or a zoom no map has, is refused", s == 400 and s2 == 400, f"{s} {s2}")
    pin = {"name": "Meeting place", "note": "Behind the gym", "lat": 40.73, "lon": -73.98}
    s, got, _ = req("PUT", "/places/pins/a1", pin)
    s, got, _ = req("PUT", "/places/pins/b2", {**pin, "name": "Spring", "lat": 40.8})
    check("pins saved", s == 200 and [p["id"] for p in got["pins"]] == ["a1", "b2"], str(got))
    s, got, _ = req("PUT", "/places/pins/a1", {**pin, "name": "Family meeting place"})
    check("saving a pin again changes it, in its place", [p["name"] for p in got["pins"]] == ["Family meeting place", "Spring"], str(got))
    s, _, _ = req("PUT", "/places/pins/a1", {**pin, "name": "  "})
    s2, _, _ = req("PUT", "/places/pins/a1", {**pin, "note": "n" * 5001})
    s3, _, _ = req("PUT", "/places/pins/a%2F..%2Fx", pin)
    check("a pin needs a name, a note of 5,000 characters at most, and an id of letters, digits, - and _",
          (s, s2, s3) == (400, 400, 404), f"{s} {s2} {s3}")
    s, got, _ = req("DELETE", "/places/pins/b2")
    check("deleting a pin", s == 200 and [p["id"] for p in got["pins"]] == ["a1"] and got["home"]["label"] == "Our house", str(got))
    raw = json.loads((data / "places.json").read_text(encoding="utf-8"))
    raw["mine"] = {"kept": True}
    (data / "places.json").write_text("\ufeff" + json.dumps(raw), encoding="utf-8")    # as Notepad saves it
    s, got, _ = req("PUT", "/places/pins/c3", pin)
    check("whatever else someone put in places.json stays, even saved in Notepad",
          s == 200 and json.loads((data / "places.json").read_text(encoding="utf-8")).get("mine") == {"kept": True}, f"{s} {got}")
    raw = json.loads((data / "places.json").read_text(encoding="utf-8"))
    raw["pins"] = [{"id": f"p{i}", "name": "x", "note": "", "lat": 1, "lon": 1} for i in range(1000)]
    (data / "places.json").write_text(json.dumps(raw), encoding="utf-8")
    s, got, _ = req("PUT", "/places/pins/one-more", pin)
    s2, _, _ = req("PUT", "/places/pins/p5", pin)
    check("1,000 pins at most, and those can still change", s == 400 and "1,000" in got["error"] and s2 == 200, f"{s} {s2}")
    check("each save replaces the file whole: no half-written file left behind", not list(data.glob("*.new")), str(list(data.glob("*"))))

    (data / "places.json").write_text("{ not json", encoding="utf-8")
    s, got, _ = req("GET", "/places")
    s2, _, _ = req("PUT", "/places/pins/a1", pin)
    check("a places.json it can't read: says so, and leaves it as it is", s == 500 and s2 == 500 and "text editor" in got["error"]
          and (data / "places.json").read_text(encoding="utf-8") == "{ not json", f"{s} {s2} {got}")
    shutil.rmtree(data)
    s, got, _ = req("PUT", "/notes", {"text": "after", "version": ""})
    check("with the data folder gone (the drive unplugged, the kit removed), a save fails and starts no new folder",
          s == 500 and "Couldn't save" in got["error"] and not data.exists(), f"{s} {got}")
    server.terminate()
    out = server.communicate(timeout=10)[0]
    check("it said where it keeps them, and logged what failed", f"Notes and pins on port {port}" in out and "couldn't save" in out, out[-300:])
    p = subprocess.run(server_cmd + ["--data", str(work / "nowhere"), "--port", str(port), "--library", str(lib)],
                       capture_output=True, text=True, timeout=30)
    check("without a data folder, it doesn't start", p.returncode != 0 and "no data folder" in p.stderr, p.stderr)


who = "data.py"
checks([sys.executable, str(ROOT / "tools" / "data.py")])
PROGRAM = program()
if PROGRAM:
    who = "data (Go)"
    checks([str(PROGRAM), "data"])
else:
    print("SKIP  the kit's own program: not built (tools/tinfoilkit/build.sh)")

print("\nALL PASSED" if not fails else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
