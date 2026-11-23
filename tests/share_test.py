"""Home network sharing test: the gate in front of the kit's servers (the kit's own program's), ./kit share and
./kit autostart, and the launcher with sharing on. Stand-in servers play the library and the AI. The QR code, the
access codes and Windows' Startup entry are checked in the program's own tests (tools/tinfoilkit/kit_test.go).
Needs python3 and the program (tools/tinfoilkit/build.sh builds it), so it runs in the quick gate and in cloud sessions.
usage: python3 tests/share_test.py
"""

import http.client
import http.server
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
PLAT = {("Linux", "x86_64"): "linux-x64", ("Darwin", "arm64"): "macos-arm64"}.get(
    (platform.system(), platform.machine())
)
PROGRAM = ROOT / "tools" / f"tinfoilkit-{PLAT}"  # the kit's own program for this computer
if not PLAT or not PROGRAM.exists():
    sys.exit("The tests need the kit's program for this computer: tools/tinfoilkit/build.sh builds it")
TRIES = 10  # wrong codes the gate takes from one address before that address waits (tries in gate.go)
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + (f": {detail}" if detail and not ok else ""))
    fails += 0 if ok else 1


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def listening(port):
    """Waits up to 10 seconds for something to listen on port."""
    end = time.time() + 10
    while time.time() < end:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return True
        except OSError:
            time.sleep(0.1)
    return False


def save_access(kit, access):
    """Gives the kit an access code, where ./kit share keeps it."""
    f = kit / "data" / ".kit" / "share.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(access))
    return f


def pretty(code):
    """An access code as the kit shows it: digits in fours."""
    return " ".join(code[i : i + 4] for i in range(0, len(code), 4)) if code.isdigit() else code


def banner_port(kit, port):
    """The gate's port in what ./kit share and the launcher print, looking for the gate from port up."""
    p = subprocess.run(
        [str(PROGRAM), "banner", "--root", str(kit), "--port", str(port)],
        capture_output=True,
        text=True,
        env={**os.environ, "KIT_LAN_IP": "192.168.1.20"},
        timeout=30,
    )
    m = re.search(r"http://192\.168\.1\.20:(\d+)", p.stdout)
    return int(m.group(1)) if m else 0


# ----------------------------------------------------------------------------- the gate
class Upstream(http.server.BaseHTTPRequestHandler):
    """Plays the library (the kit page at /) and the AI (/v1/..., an answer streamed in two parts)."""

    protocol_version = "HTTP/1.1"
    seen = []

    def do_GET(self):
        Upstream.seen.append((self.server.server_address[1], self.command, self.path, dict(self.headers)))
        if self.path.startswith("/v1/chat/completions") or self.command == "POST":
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for part in (b"data: one\n\n", b"data: two\n\n"):
                self.wfile.write(b"%x\r\n%s\r\n" % (len(part), part))
                self.wfile.flush()
                time.sleep(1)
            self.wfile.write(b"0\r\n\r\n")
            return
        if self.path.split("?")[0] == "/":
            body = b"<!doctype html><html><head><title>Tinfoil Kit</title></head><body>the kit page</body></html>"
            ctype = "text/html"
        elif self.path.startswith(("/v1/models", "/props")):
            body, ctype = b'{"data": [{"id": "Tiny"}]}', "application/json"
        else:
            body, ctype = f"path {self.path}".encode(), "text/plain"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", '"v1"')
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    do_POST = do_HEAD = do_GET

    def log_message(self, *a):
        pass


def start(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


work = Path(tempfile.mkdtemp(prefix="share-test-"))
running = []  # what this test starts, each in its own process group, so it can stop each with what that started
try:
    kit = work / "kit"
    (kit / "data" / ".kit").mkdir(parents=True)
    lib = start(http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream))
    ai = start(http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream))
    lib_port, ai_port, dead, nport, gport = (
        lib.server_address[1],
        ai.server_address[1],
        free_port(),
        free_port(),
        free_port(),
    )
    running.append(
        subprocess.Popen(
            [str(PROGRAM), "data", "--data", str(kit / "data"), "--port", str(nport), "--library", str(lib_port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    )
    save_access(kit, {"code": "48217736", "key": "ab" * 32})
    gate = subprocess.Popen(
        [
            str(PROGRAM),
            "gate",
            "--root",
            str(kit),
            "--port",
            str(gport),
            "--library",
            str(lib_port),
            "--ai",
            str(ai_port),
            "--data",
            str(nport),
            "--tiles",
            str(lib_port),
            "--routing",
            str(dead),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "KIT_LAN_IP": "192.168.1.20"},  # this computer's address on the home network
        start_new_session=True,
    )
    running.append(gate)
    check("the gate and the notes server start", listening(nport) and listening(gport))

    def req(method, path, body=None, headers=None, read=True):
        c = http.client.HTTPConnection("127.0.0.1", gport, timeout=20)
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        data = r.read() if read else None
        if read:
            c.close()
        return r, data, c

    r, data, _ = req("GET", "/", headers={"Accept": "text/html"})
    check(
        "gate: without the code, the kit page is the access code page",
        r.status == 401 and b"Access code" in data and b"the kit page" not in data,
        f"{r.status}",
    )
    r, data, _ = req("GET", "/ai/v1/models")
    check("gate: without the code, the AI says the code is needed", r.status == 401 and b"access code" in data)
    r, data, _ = req("GET", "/catalog/v2/entries", headers={"Accept": "text/html"})
    check(
        "gate: a deep link comes back to itself after the code",
        r.status == 401 and b'value="/catalog/v2/entries"' in data,
    )

    form = {"Content-Type": "application/x-www-form-urlencoded"}
    r, data, _ = req("POST", "/_kit/login", b"code=11112222&next=/", form)
    check(
        "gate: a wrong code is turned away",
        r.status == 401 and b"didn&#x27;t work" in data,
        f"{r.status} {data[-400:]}",
    )
    r, data, _ = req("POST", "/_kit/login", b"code=4821+7736&next=//evil.example/", form)
    cookie = (r.getheader("Set-Cookie") or "").split(";")[0]
    check(
        "gate: the right code (typed with a space) lets the device in, and never sends it elsewhere",
        r.status == 303
        and r.getheader("Location") == "/"
        and cookie.startswith("tinfoilkit=")
        and "HttpOnly" in r.getheader("Set-Cookie")
        and "SameSite=Lax" in r.getheader("Set-Cookie"),
        f"{r.status} {r.getheader('Location')} {r.getheader('Set-Cookie')}",
    )
    signed = {"Cookie": "other=1; " + cookie, "Accept-Encoding": "gzip", "If-None-Match": '"v1"'}

    Upstream.seen.clear()
    r, data, _ = req("GET", "/?model=Tiny", headers=signed)
    gate_info = data.split(b"window.KIT_GATE = ")[1].split(b";</script>")[0] if b"KIT_GATE" in data else b"{}"
    info = json.loads(gate_info)
    check(
        "gate: the kit page comes through, told it's shared, with the address and the code",
        r.status == 200
        and data.startswith(b"<!doctype html><html><head><script>window.KIT_GATE")
        and b"the kit page" in data
        and info == {"address": f"http://192.168.1.20:{gport}", "code": "4821 7736"},
        data[:120],
    )
    up = Upstream.seen[-1][3] if Upstream.seen else {}
    lower = {k.lower(): v for k, v in up.items()}
    check(
        "gate: the library gets a fresh page, and never the cookie",
        r.getheader("Cache-Control") == "no-store"
        and r.getheader("ETag") is None
        and "cookie" not in lower
        and "if-none-match" not in lower
        and "accept-encoding" not in lower
        and lower.get("host") == f"127.0.0.1:{lib_port}",
        str(up),
    )
    r, data, _ = req("GET", "/", headers={"Host": "evil.example.com:8000", "Accept": "text/html"})
    check(
        "gate: a name a website elsewhere could point here is turned away (DNS rebinding)",
        r.status == 403 and b"doesn't answer to that name" in data,
        f"{r.status} {data}",
    )
    r, data, _ = req("GET", "/ai/v1/models", headers={**signed, "Host": "kit.example.com"})
    check("gate: ...even with the cookie", r.status == 403)
    hosts = ("192.168.1.20:8000", "homeserver.local:8000", "homeserver:8000", "localhost:8000", "kit.lan", "[::1]:8000")
    codes = [req("GET", "/ai/v1/models", headers={**signed, "Host": h})[0].status for h in hosts]
    check("gate: an address, a bare name and a .local or .lan name all work", codes == [200] * len(hosts), str(codes))
    shown = []
    for h in ("192.168.1.31:8000", "homeserver.local:8000"):
        page = req("GET", "/", headers={**signed, "Host": h})[1]
        shown.append(json.loads(page.split(b"window.KIT_GATE = ")[1].split(b";</script>")[0])["address"])
    check(
        "gate: the page passes on the address a device used, or for a name, the address every phone can open",
        shown == ["http://192.168.1.31:8000", f"http://192.168.1.20:{gport}"],
        str(shown),
    )
    r, data, _ = req("HEAD", "/catalog", headers=signed)
    check("gate: HEAD has headers and no body", r.status == 200 and data == b"" and r.getheader("Content-Length"))

    r, data, _ = req("GET", "/ai/v1/models", headers=signed)
    check(
        "gate: /ai/ goes to the AI",
        r.status == 200
        and b"Tiny" in data
        and Upstream.seen[-1][0] == ai_port
        and Upstream.seen[-1][2] == "/v1/models",
        str(Upstream.seen[-1][:3]),
    )
    check(
        "gate: the servers' own permission for other websites is dropped",
        r.getheader("Access-Control-Allow-Origin") is None,
    )
    r, data, _ = req("GET", "/props", headers=signed)
    check(
        "gate: the AI chat page's API at the root goes to the AI too",
        r.status == 200 and Upstream.seen[-1][0] == ai_port,
    )
    n = len(Upstream.seen)
    answers = [
        req(m, p, b"{}" if m == "POST" else None, signed)[:2]
        for m, p in (
            ("GET", "/ai/tools"),
            ("POST", "/ai/tools"),
            ("GET", "/ai//%74ools/"),
            ("GET", "/v1/../tools"),
            ("GET", "/ai/cors-proxy?url=http://192.168.1.1/"),
        )
    ]
    check(
        "gate: llama-server's tools and web proxy stay off for the network, however they're spelled",
        all(r.status == 403 and b"feature_disabled" in d for r, d in answers) and len(Upstream.seen) == n,
        str([(r.status, d[:40]) for r, d in answers]),
    )
    # A browser sends its next request on the same connection: what the gate didn't read mustn't become part of it.
    c = http.client.HTTPConnection("127.0.0.1", gport, timeout=20)
    seq = []
    for path, hdrs in (
        ("/ai/tools", signed),
        ("/ai/v1/models", signed),
        ("/ai/v1/chat/completions", {}),
        ("/ai/v1/models", signed),
    ):
        c.request(
            "POST" if "models" not in path else "GET",
            path,
            body=b'{"messages": []}' if "models" not in path else None,
            headers=hdrs,
        )
        r = c.getresponse()
        r.read()
        seq.append(r.status)
    c.close()
    check(
        "gate: a request answered without reading its body doesn't spoil the next one on the connection",
        seq == [403, 200, 401, 200],
        str(seq),
    )
    r, data, _ = req("GET", "/ai", headers=signed)
    check("gate: /ai becomes /ai/", r.status == 303 and r.getheader("Location") == "/ai/")
    r, data, _ = req("GET", "/tiles/basemap/1/0/0.mvt?x=1", headers=signed)
    check("gate: /tiles/ goes to the map tiles", data == b"path /basemap/1/0/0.mvt?x=1", data)
    r, data, _ = req("GET", "/geocoder/api?q=x", headers=signed)
    check("gate: a server the kit doesn't have says so", r.status == 502 and b"isn't part of this kit" in data)
    r, data, _ = req("GET", "/routing/health", headers=signed)
    check("gate: a server that isn't up yet says so", r.status == 502 and b"isn't running yet" in data)
    (kit / "data" / "notes.txt").unlink(missing_ok=True)
    phone = {**signed, "Content-Type": "application/json", "Origin": f"http://192.168.1.20:{gport}"}
    r, data, _ = req("PUT", "/data/notes", json.dumps({"text": "Written on a phone", "version": ""}).encode(), phone)
    r2, data2, _ = req("GET", "/data/places", headers=signed)
    check(
        "gate: /data/ keeps a phone's notes and pins in the kit's data folder",
        r.status == 200
        and (kit / "data" / "notes.txt").read_text(encoding="utf-8") == "Written on a phone"
        and json.loads(data2) == {"home": None, "pins": []},
        f"{r.status} {data} {data2}",
    )
    r, data, _ = req("GET", "/data/notes")
    check("gate: and only with the access code", r.status == 401, str(r.status))
    r, data, _ = req("GET", "/_kit/qr.svg", headers=signed)
    check(
        "gate: the QR code for the page",
        r.status == 200 and data.startswith(b"<svg") and r.getheader("Content-Type") == "image/svg+xml",
    )

    t0 = time.time()
    r, _, conn = req(
        "POST",
        "/ai/v1/chat/completions",
        b'{"stream": true}',
        {**signed, "Content-Type": "application/json"},
        read=False,
    )
    first = r.read1(100) if hasattr(r, "read1") else r.read(11)
    t_first = time.time() - t0
    rest = r.read()
    conn.close()
    check(
        "gate: the AI's answer streams through as it's written",
        first.startswith(b"data: one") and t_first < 0.8 and b"data: two" in first + rest,
        f"first part after {t_first:.1f}s",
    )

    r, data, _ = req("GET", "/?code=48217736&model=Tiny")
    check(
        "gate: the QR code's link lets the device in and tidies the address",
        r.status == 303
        and r.getheader("Location") == "/?model=Tiny"
        and "tinfoilkit=" in (r.getheader("Set-Cookie") or ""),
    )
    r, data, _ = req("GET", "/?code=11112222")
    check("gate: an old QR code says so", r.status == 401 and b"out of date" in data)
    r, data, _ = req("GET", "/ai/v1/models", headers={"Authorization": "Bearer 48217736"})
    check("gate: programs can use the access code as their API key", r.status == 200 and b"Tiny" in data)
    r, data, _ = req("GET", "/ai/v1/models", headers={"Authorization": "Bearer nope"})
    check("gate: a wrong API key is turned away", r.status == 401)

    f = save_access(kit, {"code": "55556666", "key": "cd" * 32})
    os.utime(f, (time.time() + 5, time.time() + 5))  # a new mtime, even on a coarse clock
    r, data, _ = req("GET", "/ai/v1/models", headers=signed)
    check("gate: a new access code signs every device out", r.status == 401)
    r, data, _ = req("POST", "/_kit/login", b"code=55556666", form)
    check("gate: the new code works", r.status == 303)

    for _ in range(TRIES):
        req("POST", "/_kit/login", b"code=00000000", form)
    r, data, _ = req("POST", "/_kit/login", b"code=55556666", form)
    check(
        f"gate: after {TRIES} wrong codes, a device waits, even with the right one",
        r.status == 429 and b"Too many tries" in data,
    )

    check("./kit share finds the port the gate answers on, from share_port up", banner_port(kit, gport - 3) == gport)
    gate.terminate()
    gate.wait(timeout=10)
    check("...and that it's gone when the kit stops", banner_port(kit, gport - 3) == gport - 3)

    # ------------------------------------------------------------------------- ./kit share and ./kit autostart
    k2 = work / "kit2"  # its code in app/, as a release has it
    (k2 / "app" / "tools").mkdir(parents=True)
    for f in ("kit", "kit.json", "Open Tinfoil Kit.command"):
        shutil.copy(ROOT / f, k2 / "app" / f)
    shutil.copy(PROGRAM, k2 / "app" / "tools")
    kit_line = ["bash", str(k2 / "app" / "kit")]
    mine = k2 / "data" / "kit.json"  # the person's kit.json, a copy of app/kit.json at first
    fake_bin = work / "bin"
    fake_bin.mkdir()
    calls = work / "calls.txt"
    for name in ("systemctl", "loginctl", "launchctl", "sudo"):  # record what would be asked of the system
        (fake_bin / name).write_text(
            f'#!/bin/sh\necho "{name} $*" >> "{calls}"\n'
            + ('[ "$*" = "show-user $(id -un) --property=Linger" ] && echo Linger=no\n' if name == "loginctl" else "")
            + "exit 0\n"
        )
        (fake_bin / name).chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "XDG_CONFIG_HOME": str(work / "config"),
        "KIT_LAN_IP": "192.168.1.20",
    }

    def kit_cmd(*args):
        p = subprocess.run([*kit_line, *args], capture_output=True, text=True, env=env, timeout=60)
        return p.returncode, p.stdout + p.stderr

    before = (k2 / "app" / "kit.json").read_text()
    rc, out = kit_cmd("share")
    check("./kit share: off at first", rc == 0 and "Sharing is off" in out, out)
    rc, out = kit_cmd("share", "on", "--code", "2468-1357", "--qr")
    after = mine.read_text()
    changed = [(a, b) for a, b in zip(before.splitlines(), after.splitlines()) if a != b]
    check(
        "./kit share on: turns the setting on, and changes nothing else in kit.json",
        rc == 0 and changed == [('    "share_on_network": false,', '    "share_on_network": true,')],
        str(changed),
    )
    check(
        "./kit share on: shows the access code and the QR code",
        "Access code: 2468 1357" in out and "\033[30;47m" in out and "home network" in out,
        out,
    )
    check(
        "./kit share on: the access code lives in data/.kit, not kit.json, and app/kit.json is as it was",
        json.loads((k2 / "data" / ".kit" / "share.json").read_text())["code"] == "24681357"
        and "2468" not in after
        and (k2 / "app" / "kit.json").read_text() == before,
    )
    p = subprocess.run(
        " ".join(f'"{w}"' for w in kit_line) + " share --qr | head -1",
        shell=True,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    check(
        "./kit share | head -1: no traceback when the reader stops early",
        "Traceback" not in p.stderr and "panic" not in p.stderr and "goroutine" not in p.stderr,
        p.stderr,
    )
    rc, out = kit_cmd("share", "new-code")
    new = json.loads((k2 / "data" / ".kit" / "share.json").read_text())["code"]
    check(
        "./kit share new-code: a new random 8-digit code",
        rc == 0 and new != "24681357" and len(new) == 8 and pretty(new) in out,
        out,
    )
    rc, out = kit_cmd("share", "on", "--code", "123")
    check("./kit share: refuses a code that's too short", rc != 0 and "6 to 64" in out)
    rc, out = kit_cmd("share", "off")
    check("./kit share off", rc == 0 and '"share_on_network": false' in mine.read_text())

    if sys.platform.startswith("linux"):
        unit = work / "config" / "systemd" / "user" / "tinfoil-kit.service"
        rc, out = kit_cmd("autostart", "on")
        text = unit.read_text() if unit.exists() else ""
        log = calls.read_text() if calls.exists() else ""
        check(
            "./kit autostart on: a systemd user service that runs the launcher, started now and at boot",
            rc == 0
            and f'ExecStart=/bin/bash "{k2}/app/Open Tinfoil Kit.command" --no-browser' in text
            and "Restart=always" in text
            and "systemctl --user enable tinfoil-kit.service" in log
            and "systemctl --user restart tinfoil-kit.service" in log
            and "loginctl enable-linger" in log,
            out + log,
        )
        check("./kit autostart on: says when sharing is off", "Sharing is off" in out, out)
        rc, out = kit_cmd("autostart")
        check("./kit autostart: says it's on", rc == 0 and "starts when this computer starts" in out, out)
        calls.unlink()
        rc, out = kit_cmd("share", "on")
        check(
            "./kit share on: restarts the kit the computer started",
            "try-restart tinfoil-kit.service" in calls.read_text() and "restarted" in out,
            out,
        )
        calls.unlink()
        rc, out = kit_cmd("share", "on")
        check(
            "./kit share on, when it's on already: leaves the running kit be",
            rc == 0 and "already on" in out and not calls.exists(),
            out,
        )
        other = unit.read_text().replace(str(k2), str(work / "elsewhere"))
        unit.write_text(other)
        rc, out = kit_cmd("autostart", "off")
        check(
            "./kit autostart off: leaves another kit's service alone",
            rc == 0 and unit.exists() and "another kit" in out,
            out,
        )
        unit.write_text(text)
        rc, out = kit_cmd("autostart", "off")
        check(
            "./kit autostart off: stops and removes the service",
            rc == 0 and not unit.exists() and "disable --now tinfoil-kit.service" in calls.read_text(),
            out,
        )

    # ------------------------------------------------------------------------- the launcher with sharing on
    fake = work / "fake-kiwix-serve"
    args_seen = work / "kiwix-args.txt"
    fake.write_text(f"""#!{sys.executable}
import http.server, sys
if "--port" not in sys.argv:
    sys.exit(0)
open({str(args_seen)!r}, "w").write(" ".join(sys.argv[1:]))
class Page(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<!doctype html><html><head><title>Tinfoil Kit</title></head><body>library</body></html>"
        self.send_response(200); self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a):
        pass
http.server.HTTPServer(("127.0.0.1", int(sys.argv[sys.argv.index("--port") + 1])), Page).serve_forever()
""")
    fake.chmod(0o755)
    (k2 / "downloads" / "library").mkdir(parents=True)
    (k2 / "downloads" / "library" / "book.zim").touch()
    lport, sport, dport = free_port(), free_port(), free_port()
    cfg = json.loads(mine.read_text())
    cfg["settings"].update(
        library_port=lport, ai_port=free_port(), data_port=dport, share_port=sport, share_on_network=True
    )
    mine.write_text(json.dumps(cfg, indent=2))
    save_access(k2, {"code": "13572468", "key": "ef" * 32})
    p = subprocess.Popen(
        ["bash", str(k2 / "app" / "Open Tinfoil Kit.command"), "--no-browser", "--no-maps"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        stdin=subprocess.DEVNULL,
        env={**env, "KIT_KIWIX_TOOLS_BIN": str(fake)},
        start_new_session=True,
    )
    running.append(p)
    lines = []
    threading.Thread(target=lambda: [lines.append(x) for x in p.stdout], daemon=True).start()
    end = time.time() + 60
    while time.time() < end and not any("Keep this window open" in x for x in lines):
        time.sleep(0.2)
    out = "".join(lines)
    check(
        "launcher, sharing on: prints the home network address and the access code",
        f"On your home network: open http://192.168.1.20:{sport}" in out and "Access code: 1357 2468" in out,
        out,
    )
    check(
        "launcher, sharing on: the library still listens on 127.0.0.1 only",
        args_seen.exists() and "--address 127.0.0.1" in args_seen.read_text(),
        args_seen.read_text() if args_seen.exists() else "",
    )
    gport = sport  # where req() asks
    r, data, _ = req("GET", "/?code=13572468")
    r2, data2, _ = req("GET", "/", headers={"Cookie": (r.getheader("Set-Cookie") or "").split(";")[0]})
    check(
        "launcher, sharing on: the gate asks for the code, then serves the library",
        r.status == 303 and r2.status == 200 and b"library" in data2 and b"KIT_GATE" in data2,
        data2[:200],
    )
    r3, data3, _ = req("GET", "/data/notes", headers={"Cookie": (r.getheader("Set-Cookie") or "").split(";")[0]})
    check(
        "launcher: starts the notes and pins server, which the page finds at its address and the gate at /data/",
        r3.status == 200 and json.loads(data3) == {"text": "", "version": ""} and f"&data={dport}" in out,
        f"{r3.status} {data3}",
    )

    def ask_notes(path, origin):
        c = http.client.HTTPConnection("127.0.0.1", dport, timeout=20)
        c.request("GET", path, headers={"Origin": origin})
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, json.loads(body or b"{}")

    status, share = ask_notes("/share", f"http://127.0.0.1:{lport}")
    check(
        "launcher, sharing on: the kit page on this computer learns the address, the code and the QR code, for Share",
        status == 200
        and share.get("shared") is True
        and share.get("address") == f"http://192.168.1.20:{sport}"
        and share.get("code") == "1357 2468"
        and share.get("qr", "").startswith("<svg"),
        f"{status} {str(share)[:300]}",
    )
    check("launcher, sharing on: ...and no other web page does", ask_notes("/share", "http://evil.example")[0] == 403)
    os.killpg(p.pid, 15)
    try:
        p.wait(timeout=15)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, 9)
    time.sleep(0.5)
    with socket.socket() as s, socket.socket() as s2:
        stopped = s.connect_ex(("127.0.0.1", sport)) != 0 and s2.connect_ex(("127.0.0.1", dport)) != 0
    check("launcher: closing it stops the gate and the notes server too", stopped)

finally:
    for p in running:
        if p.poll() is None:
            os.killpg(p.pid, 9)
    shutil.rmtree(work, ignore_errors=True)

print("\nALL PASSED" if not fails else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
