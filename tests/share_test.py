"""Home network sharing test: the QR code, the gate in front of the kit's servers (tools/share.py), ./kit share
and ./kit autostart, and the launcher with sharing on. Stand-in servers play the library and the AI.
Needs only python3, so it runs in the quick gate and in cloud sessions.
usage: python3 tests/share_test.py
"""
import contextlib
import hashlib
import http.client
import http.server
import io
import json
import os
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
sys.path.insert(0, str(ROOT / "tools"))
import share  # noqa: E402

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + (f": {detail}" if detail and not ok else ""))
    fails += 0 if ok else 1


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ----------------------------------------------------------------------------- QR code
# These codes were checked against Project Nayuki's QR Code generator (the same modules for every mask, and the
# same mask chosen) and read back with the jsQR decoder. A change that alters them needs that check again.
def fingerprint(g):
    return hashlib.sha256("".join("1" if v else "0" for row in g for v in row).encode()).hexdigest()[:16]


KNOWN = {"http://192.168.1.20:8000/?code=48217736": (29, "3b09359ec7d0cf46"),
         "http://my-home-server.local:8000/?code=99887766": (33, "9be85ad5baee3e22"),
         "x" * 150: (49, "1336208e16162851")}
for text, (size, fp) in KNOWN.items():
    g = share.qr_code(text)
    check(f"QR code for a {len(text)}-character text: version {(size - 17) // 4}, as checked",
          len(g) == size and fingerprint(g) == fp, f"{len(g)} modules, {fingerprint(g)}")
g = share.qr_code("http://10.0.0.5:8000/?code=12345678")
finder = [[True] * 7] + [[True] + [False] * 5 + [True]] + [[True, False, True, True, True, False, True]] * 3 + \
         [[True] + [False] * 5 + [True]] + [[True] * 7]
check("QR code: finder patterns in three corners", all([row[:7] for row in g[:7]] == finder and
      [row[-7:] for row in g[:7]] == finder and [row[:7] for row in g[-7:]] == finder for _ in [0]))
svg = share.qr_svg(g)
check("QR code as SVG", svg.startswith("<svg") and svg.count("h1v1h-1z") == sum(map(sum, g)))
text = share.qr_text(g)
check("QR code for a terminal: black on white, two rows to a line",
      "\033[30;47m" in text and len(text.splitlines()) == (len(g) + 4 + 1) // 2)

# ----------------------------------------------------------------------------- the access code
check("access codes: digits read in fours", share.pretty_code("48217736") == "4821 7736")
check("access codes: spaces and dashes don't matter", share.clean_code(" 4821-7736 ") == "48217736")
check("access codes: 6 to 64 letters or digits", share.valid_code("abc123") and not share.valid_code("12345")
      and not share.valid_code("1234567!"))
check("home network: private, link-local and Tailscale addresses, not the internet",
      all(share.on_home_network(ip) for ip in ("192.168.1.5", "10.2.3.4", "172.20.0.9", "127.0.0.1", "100.101.1.2"))
      and not any(share.on_home_network(ip) for ip in ("8.8.8.8", "172.32.0.1", "1.1.1.1", "nonsense")))


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
try:
    kit = work / "kit"
    (kit / ".kit").mkdir(parents=True)
    share.save_access(kit, {"code": "48217736", "key": "ab" * 32})
    lib = start(http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream))
    ai = start(http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream))
    lib_port, ai_port, dead = lib.server_address[1], ai.server_address[1], free_port()
    gate = start(share.Gate(kit, 0, {"library": lib_port, "ai": ai_port, "tiles": lib_port, "routing": dead}))
    gport = gate.server_address[1]

    def req(method, path, body=None, headers=None, read=True):
        c = http.client.HTTPConnection("127.0.0.1", gport, timeout=20)
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        data = r.read() if read else None
        if read:
            c.close()
        return r, data, c

    r, data, _ = req("GET", "/", headers={"Accept": "text/html"})
    check("gate: without the code, the kit page is the access code page", r.status == 401 and b"Access code" in data
          and b"the kit page" not in data, f"{r.status}")
    r, data, _ = req("GET", "/ai/v1/models")
    check("gate: without the code, the AI says the code is needed", r.status == 401 and b"access code" in data)
    r, data, _ = req("GET", "/catalog/v2/entries", headers={"Accept": "text/html"})
    check("gate: a deep link comes back to itself after the code", r.status == 401 and b'value="/catalog/v2/entries"' in data)

    form = {"Content-Type": "application/x-www-form-urlencoded"}
    r, data, _ = req("POST", "/_kit/login", b"code=11112222&next=/", form)
    check("gate: a wrong code is turned away", r.status == 401 and b"didn&#x27;t work" in data, f"{r.status} {data[-400:]}")
    r, data, _ = req("POST", "/_kit/login", b"code=4821+7736&next=//evil.example/", form)
    cookie = (r.getheader("Set-Cookie") or "").split(";")[0]
    check("gate: the right code (typed with a space) lets the device in, and never sends it elsewhere",
          r.status == 303 and r.getheader("Location") == "/" and cookie.startswith("tinfoilkit=")
          and "HttpOnly" in r.getheader("Set-Cookie") and "SameSite=Lax" in r.getheader("Set-Cookie"),
          f"{r.status} {r.getheader('Location')} {r.getheader('Set-Cookie')}")
    signed = {"Cookie": "other=1; " + cookie, "Accept-Encoding": "gzip", "If-None-Match": '"v1"'}

    Upstream.seen.clear()
    r, data, _ = req("GET", "/?model=Tiny", headers=signed)
    gate_info = data.split(b"window.KIT_GATE = ")[1].split(b";</script>")[0] if b"KIT_GATE" in data else b"{}"
    info = json.loads(gate_info)
    check("gate: the kit page comes through, told it's shared, with the address and the code",
          r.status == 200 and data.startswith(b"<!doctype html><html><head><script>window.KIT_GATE") and
          b"the kit page" in data and info.get("code") == "4821 7736" and info.get("address", "").startswith("http://"),
          data[:120])
    up = Upstream.seen[-1][3] if Upstream.seen else {}
    lower = {k.lower(): v for k, v in up.items()}
    check("gate: the library gets a fresh page, and never the cookie",
          r.getheader("Cache-Control") == "no-store" and r.getheader("ETag") is None and "cookie" not in lower
          and "if-none-match" not in lower and "accept-encoding" not in lower and lower.get("host") == f"127.0.0.1:{lib_port}",
          str(up))
    r, data, _ = req("GET", "/", headers={"Host": "evil.example.com:8000", "Accept": "text/html"})
    check("gate: a name a website elsewhere could point here is turned away (DNS rebinding)",
          r.status == 403 and b"doesn't answer to that name" in data, f"{r.status} {data}")
    r, data, _ = req("GET", "/ai/v1/models", headers={**signed, "Host": "kit.example.com"})
    check("gate: ...even with the cookie", r.status == 403)
    hosts = ("192.168.1.20:8000", "homeserver.local:8000", "homeserver:8000", "localhost:8000", "kit.lan", "[::1]:8000")
    codes = [req("GET", "/ai/v1/models", headers={**signed, "Host": h})[0].status for h in hosts]
    check("gate: an address, a bare name and a .local or .lan name all work", codes == [200] * len(hosts), str(codes))
    r, data, _ = req("HEAD", "/catalog", headers=signed)
    check("gate: HEAD has headers and no body", r.status == 200 and data == b"" and r.getheader("Content-Length"))

    r, data, _ = req("GET", "/ai/v1/models", headers=signed)
    check("gate: /ai/ goes to the AI", r.status == 200 and b"Tiny" in data and Upstream.seen[-1][0] == ai_port
          and Upstream.seen[-1][2] == "/v1/models", str(Upstream.seen[-1][:3]))
    check("gate: the servers' own permission for other websites is dropped", r.getheader("Access-Control-Allow-Origin") is None)
    r, data, _ = req("GET", "/props", headers=signed)
    check("gate: the AI chat page's API at the root goes to the AI too", r.status == 200 and Upstream.seen[-1][0] == ai_port)
    n = len(Upstream.seen)
    answers = [req(m, p, b"{}" if m == "POST" else None, signed)[:2] for m, p in
               (("GET", "/ai/tools"), ("POST", "/ai/tools"), ("GET", "/ai//%74ools/"), ("GET", "/v1/../tools"),
                ("GET", "/ai/cors-proxy?url=http://192.168.1.1/"))]
    check("gate: llama-server's tools and web proxy stay off for the network, however they're spelled",
          all(r.status == 403 and b"feature_disabled" in d for r, d in answers) and len(Upstream.seen) == n,
          str([(r.status, d[:40]) for r, d in answers]))
    # A browser sends its next request on the same connection: what the gate didn't read mustn't become part of it.
    c = http.client.HTTPConnection("127.0.0.1", gport, timeout=20)
    seq = []
    for path, hdrs in (("/ai/tools", signed), ("/ai/v1/models", signed), ("/ai/v1/chat/completions", {}),
                       ("/ai/v1/models", signed)):
        c.request("POST" if "models" not in path else "GET", path,
                  body=b'{"messages": []}' if "models" not in path else None, headers=hdrs)
        r = c.getresponse()
        r.read()
        seq.append(r.status)
    c.close()
    check("gate: a request answered without reading its body doesn't spoil the next one on the connection",
          seq == [403, 200, 401, 200], str(seq))
    r, data, _ = req("GET", "/ai", headers=signed)
    check("gate: /ai becomes /ai/", r.status == 303 and r.getheader("Location") == "/ai/")
    r, data, _ = req("GET", "/tiles/basemap/1/0/0.mvt?x=1", headers=signed)
    check("gate: /tiles/ goes to the map tiles", data == b"path /basemap/1/0/0.mvt?x=1", data)
    r, data, _ = req("GET", "/geocoder/api?q=x", headers=signed)
    check("gate: a server the kit doesn't have says so", r.status == 502 and b"isn't part of this kit" in data)
    r, data, _ = req("GET", "/routing/health", headers=signed)
    check("gate: a server that isn't up yet says so", r.status == 502 and b"isn't running yet" in data)
    r, data, _ = req("GET", "/_kit/qr.svg", headers=signed)
    check("gate: the QR code for the page", r.status == 200 and data.startswith(b"<svg") and r.getheader("Content-Type") == "image/svg+xml")

    t0 = time.time()
    r, _, conn = req("POST", "/ai/v1/chat/completions", b'{"stream": true}',
                     {**signed, "Content-Type": "application/json"}, read=False)
    first = r.read1(100) if hasattr(r, "read1") else r.read(11)
    t_first = time.time() - t0
    rest = r.read()
    conn.close()
    check("gate: the AI's answer streams through as it's written",
          first.startswith(b"data: one") and t_first < 0.8 and b"data: two" in first + rest, f"first part after {t_first:.1f}s")

    r, data, _ = req("GET", "/?code=48217736&model=Tiny")
    check("gate: the QR code's link lets the device in and tidies the address",
          r.status == 303 and r.getheader("Location") == "/?model=Tiny" and "tinfoilkit=" in (r.getheader("Set-Cookie") or ""))
    r, data, _ = req("GET", "/?code=11112222")
    check("gate: an old QR code says so", r.status == 401 and b"out of date" in data)
    r, data, _ = req("GET", "/ai/v1/models", headers={"Authorization": "Bearer 48217736"})
    check("gate: programs can use the access code as their API key", r.status == 200 and b"Tiny" in data)
    r, data, _ = req("GET", "/ai/v1/models", headers={"Authorization": "Bearer nope"})
    check("gate: a wrong API key is turned away", r.status == 401)

    share.save_access(kit, {"code": "55556666", "key": "cd" * 32})
    os.utime(share.access_file(kit), (time.time() + 5, time.time() + 5))    # a new mtime, even on a coarse clock
    r, data, _ = req("GET", "/ai/v1/models", headers=signed)
    check("gate: a new access code signs every device out", r.status == 401)
    r, data, _ = req("POST", "/_kit/login", b"code=55556666", form)
    check("gate: the new code works", r.status == 303)

    for _ in range(share.TRIES):
        req("POST", "/_kit/login", b"code=00000000", form)
    r, data, _ = req("POST", "/_kit/login", b"code=55556666", form)
    check(f"gate: after {share.TRIES} wrong codes, a device waits, even with the right one",
          r.status == 429 and b"Too many tries" in data)
    gate.failures.clear()
    check("./kit share finds the port the gate answers on", share.gate_port(gport) == gport)
    gate.shutdown()
    gate.server_close()
    check("...and that it's gone when the kit stops", share.gate_port(gport) != gport)

    # ------------------------------------------------------------------------- ./kit share and ./kit autostart
    k2 = work / "kit2"
    (k2 / "tools").mkdir(parents=True)
    for f in ("kit", "kit.json"):
        shutil.copy(ROOT / f, k2 / f)
    for f in ("kit.py", "share.py", "launch.sh"):
        shutil.copy(ROOT / "tools" / f, k2 / "tools" / f)
    fake_bin = work / "bin"
    fake_bin.mkdir()
    calls = work / "calls.txt"
    for name in ("systemctl", "loginctl", "launchctl", "sudo"):    # record what would be asked of the system
        (fake_bin / name).write_text(f'#!/bin/sh\necho "{name} $*" >> "{calls}"\n'
                                     + ('[ "$*" = "show-user $(id -un) --property=Linger" ] && echo Linger=no\n'
                                        if name == "loginctl" else "") + "exit 0\n")
        (fake_bin / name).chmod(0o755)
    env = {**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}", "XDG_CONFIG_HOME": str(work / "config"),
           "KIT_LAN_IP": "192.168.1.20"}

    def kit_cmd(*args):
        p = subprocess.run(["bash", str(k2 / "kit"), *args], capture_output=True, text=True, env=env, timeout=60)
        return p.returncode, p.stdout + p.stderr

    before = (k2 / "kit.json").read_text()
    rc, out = kit_cmd("share")
    check("./kit share: off at first", rc == 0 and "Sharing is off" in out, out)
    rc, out = kit_cmd("share", "on", "--code", "2468-1357", "--qr")
    after = (k2 / "kit.json").read_text()
    changed = [(a, b) for a, b in zip(before.splitlines(), after.splitlines()) if a != b]
    check("./kit share on: turns the setting on, and changes nothing else in kit.json",
          rc == 0 and changed == [('    "share_on_network": false,', '    "share_on_network": true,')], str(changed))
    check("./kit share on: shows the access code and the QR code",
          "Access code: 2468 1357" in out and "\033[30;47m" in out and "home network" in out, out)
    check("./kit share on: the access code lives in .kit, not kit.json",
          json.loads(share.access_file(k2).read_text())["code"] == "24681357" and "2468" not in after)
    p = subprocess.run(f'bash "{k2}/kit" share --qr | head -1', shell=True, capture_output=True, text=True, env=env, timeout=60)
    check("./kit share | head -1: no traceback when the reader stops early", "Traceback" not in p.stderr, p.stderr)
    rc, out = kit_cmd("share", "new-code")
    new = json.loads(share.access_file(k2).read_text())["code"]
    check("./kit share new-code: a new random 8-digit code", rc == 0 and new != "24681357" and len(new) == 8
          and share.pretty_code(new) in out, out)
    rc, out = kit_cmd("share", "on", "--code", "123")
    check("./kit share: refuses a code that's too short", rc != 0 and "6 to 64" in out)
    rc, out = kit_cmd("share", "off")
    check("./kit share off", rc == 0 and '"share_on_network": false' in (k2 / "kit.json").read_text())

    if sys.platform.startswith("linux"):
        unit = work / "config" / "systemd" / "user" / "tinfoil-kit.service"
        rc, out = kit_cmd("autostart", "on")
        text = unit.read_text() if unit.exists() else ""
        log = calls.read_text() if calls.exists() else ""
        check("./kit autostart on: a systemd user service that runs the launcher, started now and at boot",
              rc == 0 and f'ExecStart=/bin/bash "{k2}/tools/launch.sh" --no-browser' in text and "Restart=always" in text
              and "systemctl --user enable tinfoil-kit.service" in log and "systemctl --user restart tinfoil-kit.service" in log
              and "loginctl enable-linger" in log, out + log)
        check("./kit autostart on: says when sharing is off", "Sharing is off" in out, out)
        rc, out = kit_cmd("autostart")
        check("./kit autostart: says it's on", rc == 0 and "starts when this computer starts" in out, out)
        calls.unlink()
        rc, out = kit_cmd("share", "on")
        check("./kit share on: restarts the kit the computer started",
              "try-restart tinfoil-kit.service" in calls.read_text() and "restarted" in out, out)
        calls.unlink()
        rc, out = kit_cmd("share", "on")
        check("./kit share on, when it's on already: leaves the running kit be",
              rc == 0 and "already on" in out and not calls.exists(), out)
        other = unit.read_text().replace(str(k2), str(work / "elsewhere"))
        unit.write_text(other)
        rc, out = kit_cmd("autostart", "off")
        check("./kit autostart off: leaves another kit's service alone", rc == 0 and unit.exists() and "another kit" in out, out)
        unit.write_text(share.systemd_unit(k2))
        rc, out = kit_cmd("autostart", "off")
        check("./kit autostart off: stops and removes the service", rc == 0 and not unit.exists()
              and "disable --now tinfoil-kit.service" in calls.read_text(), out)
        odd = Path("/tmp/a kit 100% $HOME")
        check("systemd service: a folder with spaces, % and $ survives systemd's quoting",
              f'"{str(odd).replace("%", "%%").replace("$", "$$")}/tools/launch.sh"' in share.systemd_unit(odd))

    # ------------------------------------------------------------------------- Windows: the Startup folder
    # What share.py writes there and reads back. The drive test runs the real thing on Windows.
    win, said, started = work / "Tinfoil Kit 100% café", io.StringIO(), []
    win.mkdir()
    saved = os.environ.get("APPDATA")
    share.WINDOWS, os.environ["APPDATA"] = True, str(work / "Roaming")
    os.startfile = started.append    # Windows runs the new entry, which starts the kit now
    try:
        with contextlib.redirect_stdout(said):
            rc = share.autostart(win, "on")
        entry = work / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Tinfoil Kit.cmd"
        text = entry.read_bytes().decode("utf-8") if entry.exists() else ""
        bat = str(win / "Open Tinfoil Kit for Windows.bat").replace("%", "%%")
        check("Windows: ./kit autostart on puts Open Tinfoil Kit for Windows.bat in the Startup folder, minimized, no browser",
              rc == 0 and f'if exist "{bat}" start "Tinfoil Kit" /min "{bat}" --no-browser\r\n' in text, text)
        check("Windows: the Startup entry is CRLF and UTF-8, for a folder named in any language",
              text.count("\n") == text.count("\r\n") and "chcp 65001" in text and "café" in text)
        check("Windows: ./kit autostart on starts the kit now too", started == [str(entry)], str(started))
        check("Windows: and says it starts as you sign in", "whenever you sign in" in said.getvalue(), said.getvalue())
        check("Windows: reads the entry back, % and all, in any case",
              share.autostart_state(win) == "on" and share.autostart_state(Path(str(win).upper())) == "on")
        check("Windows: another kit folder's entry is another's", share.autostart_state(work / "elsewhere") == "other")
        check("Windows: a sharing change doesn't restart the kit (which window Windows started can't be told)",
              share.restart_if_autostarted(win) is False)
        check("Windows: kit commands are .\\kit.cmd", share.kit_cmd("share on") == ".\\kit.cmd share on"
              and ".\\kit.cmd autostart off" in text)
        check("Windows: no .local name", share.local_name() == "")
        with contextlib.redirect_stdout(io.StringIO()):
            share.autostart(work / "elsewhere", "off")
            kept = entry.exists()
            share.autostart(win, "off")
        check("Windows: ./kit autostart off removes this kit's entry, and only this kit's", kept and not entry.exists())
    finally:
        share.WINDOWS = False
        del os.startfile
        if saved is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = saved

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
    (k2 / "library").mkdir()
    (k2 / "library" / "book.zim").touch()
    lport, sport = free_port(), free_port()
    cfg = json.loads((k2 / "kit.json").read_text())
    cfg["settings"].update(library_port=lport, ai_port=free_port(), share_port=sport, share_on_network=True)
    (k2 / "kit.json").write_text(json.dumps(cfg, indent=2))
    share.save_access(k2, {"code": "13572468", "key": "ef" * 32})
    p = subprocess.Popen(["bash", str(k2 / "tools" / "launch.sh"), "--no-browser", "--no-maps"], stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, stdin=subprocess.DEVNULL,
                         env={**env, "KIT_KIWIX_TOOLS_BIN": str(fake)}, start_new_session=True)
    lines = []
    threading.Thread(target=lambda: [lines.append(x) for x in p.stdout], daemon=True).start()
    end = time.time() + 60
    while time.time() < end and not any("Keep this window open" in x for x in lines):
        time.sleep(0.2)
    out = "".join(lines)
    check("launcher, sharing on: prints the home network address and the access code",
          f"On your home network: open http://192.168.1.20:{sport}" in out and "Access code: 1357 2468" in out, out)
    check("launcher, sharing on: the library still listens on 127.0.0.1 only",
          args_seen.exists() and "--address 127.0.0.1" in args_seen.read_text(), args_seen.read_text() if args_seen.exists() else "")
    gport = sport
    r, data, _ = req("GET", "/?code=13572468")
    r2, data2, _ = req("GET", "/", headers={"Cookie": (r.getheader("Set-Cookie") or "").split(";")[0]})
    check("launcher, sharing on: the gate asks for the code, then serves the library",
          r.status == 303 and r2.status == 200 and b"library" in data2 and b"KIT_GATE" in data2, data2[:200])
    os.killpg(p.pid, 15)
    try:
        p.wait(timeout=15)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, 9)
    time.sleep(0.5)
    with socket.socket() as s:
        stopped = s.connect_ex(("127.0.0.1", sport)) != 0
    check("launcher: closing it stops the gate too", stopped)
finally:
    shutil.rmtree(work, ignore_errors=True)

print("\nALL PASSED" if not fails else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
