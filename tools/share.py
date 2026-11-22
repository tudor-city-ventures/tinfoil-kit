#!/usr/bin/env python3
"""Shares Tinfoil Kit with the phones and laptops on a home network.

The kit's servers only ever listen on 127.0.0.1. With sharing on, this gate listens on the network instead:
it asks for the access code, then hands each request to a server by its path (/ai, /tiles, /geocoder and
/routing; everything else is the library and the kit page). It also draws the QR code that opens the kit on a
phone, and starts the kit with the computer, for a home server (Linux: a systemd service, Mac: a LaunchAgent,
Windows: its Startup folder). Standard library only, like kit.py.

  python3 tools/share.py serve --root KIT --port 8000 --library 8888 --ai 8080 [--tiles N --geocoder N --routing N]
  python3 tools/share.py banner --root KIT --port 8000 [--qr]     the address, the access code and the QR code
./kit share and ./kit autostart (kit.cmd on Windows) use the rest.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import html
import http.client
import http.server
import ipaddress
import json
import os
import plistlib
import posixpath
import re
import secrets
import shutil
import socket
import socketserver
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Dict, List, Optional, Tuple

WINDOWS, MAC = os.name == "nt", sys.platform == "darwin"


def kit_cmd(args: str) -> str:
    """A kit command as this computer runs it."""
    return (".\\kit.cmd " if WINDOWS else "./kit ") + args


# ----------------------------------------------------------------------------- QR code
# Byte mode at error correction level M, following ISO/IEC 18004. An address needs version 3 or 4.
# Per version: error correction codewords in each block, and the number of blocks.
ECC_PER_BLOCK = (0, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26,
                 26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28)
BLOCKS = (0, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16,
          17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49)
MASKS = (lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0,
         lambda x, y: (x + y) % 3 == 0, lambda x, y: (x // 3 + y // 2) % 2 == 0,
         lambda x, y: x * y % 2 + x * y % 3 == 0, lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
         lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0)

Grid = List[List[bool]]


def _gf_mul(x: int, y: int) -> int:
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _ecc(data: List[int], degree: int) -> List[int]:
    """Reed-Solomon error correction codewords for one block."""
    gen, root = [0] * (degree - 1) + [1], 1
    for _ in range(degree):
        for j in range(degree):
            gen[j] = _gf_mul(gen[j], root)
            if j + 1 < degree:
                gen[j] ^= gen[j + 1]
        root = _gf_mul(root, 2)
    rem = [0] * degree
    for b in data:
        factor = b ^ rem.pop(0)
        rem.append(0)
        for i, coef in enumerate(gen):
            rem[i] ^= _gf_mul(coef, factor)
    return rem


def _raw_modules(ver: int) -> int:
    """Modules left for data and error correction once the fixed patterns are drawn."""
    n = (16 * ver + 128) * ver + 64
    if ver >= 2:
        align = ver // 7 + 2
        n -= (25 * align - 10) * align - 55
        if ver >= 7:
            n -= 36
    return n


def _codewords(data: bytes) -> Tuple[int, List[int]]:
    """The smallest version that holds data, and its codewords: data, then error correction, interleaved."""
    for ver in range(1, 41):
        capacity = _raw_modules(ver) // 8 - ECC_PER_BLOCK[ver] * BLOCKS[ver]
        count_bits = 8 if ver < 10 else 16
        if 4 + count_bits + 8 * len(data) <= capacity * 8:
            break
    else:
        raise ValueError("too long for a QR code")
    bits = [0, 1, 0, 0] + [(len(data) >> i) & 1 for i in reversed(range(count_bits))]
    for b in data:
        bits += [(b >> i) & 1 for i in reversed(range(8))]
    bits += [0] * min(4, capacity * 8 - len(bits))
    bits += [0] * (-len(bits) % 8)
    words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(words) < capacity:
        words.append(pad)
        pad ^= 0xEC ^ 0x11
    nblocks, ecc = BLOCKS[ver], ECC_PER_BLOCK[ver]
    raw = _raw_modules(ver) // 8
    short = nblocks - raw % nblocks          # blocks with one data codeword fewer come first
    blocks, k = [], 0
    for i in range(nblocks):
        n = raw // nblocks - ecc + (0 if i < short else 1)
        blocks.append(words[k:k + n])
        k += n
    out = [b[i] for i in range(len(blocks[-1])) for b in blocks if i < len(b)]
    eccs = [_ecc(b, ecc) for b in blocks]
    return ver, out + [e[i] for i in range(ecc) for e in eccs]


def _penalty(g: Grid) -> int:
    """How hard a masked code is to scan: long runs, 2x2 blocks, finder look-alikes, dark/light balance."""
    size, score = len(g), 0

    def finder_like(h: List[int]) -> int:
        n = h[1]
        core = n > 0 and h[2] == h[4] == h[5] == n and h[3] == n * 3
        return int(core and h[0] >= n * 4 and h[6] >= n) + int(core and h[6] >= n * 4 and h[0] >= n)

    for line in [list(r) for r in g] + [list(c) for c in zip(*g)]:
        color, run, hist = False, 0, [0] * 7

        def push(length: int) -> None:
            if hist[0] == 0:
                length += size                   # the light border before the first run
            hist.insert(0, length)
            hist.pop()

        for v in line:
            if v == color:
                run += 1
                score += 3 if run == 5 else 1 if run > 5 else 0
            else:
                push(run)
                if not color:
                    score += finder_like(hist) * 40
                color, run = v, 1
        if color:
            push(run)
            run = 0
        push(run + size)                         # the light border after the last run
        score += finder_like(hist) * 40
    score += 3 * sum(g[y][x] == g[y][x + 1] == g[y + 1][x] == g[y + 1][x + 1]
                     for y in range(size - 1) for x in range(size - 1))
    dark, total = sum(map(sum, g)), size * size
    return score + 10 * ((abs(dark * 20 - total * 10) + total - 1) // total - 1)


def qr_code(text: str, mask: Optional[int] = None) -> Grid:
    """The QR code for text, as rows of modules (True is dark), without the quiet zone around it."""
    ver, words = _codewords(text.encode("utf-8"))
    size = 4 * ver + 17
    grid = [[False] * size for _ in range(size)]
    fixed = [[False] * size for _ in range(size)]

    def put(g: Grid, x: int, y: int, dark: int) -> None:
        g[y][x] = bool(dark)
        fixed[y][x] = True

    for i in range(size):                        # timing patterns
        put(grid, 6, i, i % 2 == 0)
        put(grid, i, 6, i % 2 == 0)
    for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):    # finder patterns and their light borders
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                if 0 <= cx + dx < size and 0 <= cy + dy < size:
                    put(grid, cx + dx, cy + dy, max(abs(dx), abs(dy)) not in (2, 4))
    if ver > 1:                                  # alignment patterns
        n = ver // 7 + 2
        step = 26 if ver == 32 else (ver * 4 + n * 2 + 1) // (n * 2 - 2) * 2
        pos = [6] + [size - 7 - i * step for i in reversed(range(n - 1))]
        for i, ax in enumerate(pos):
            for j, ay in enumerate(pos):
                if (i, j) not in ((0, 0), (0, n - 1), (n - 1, 0)):
                    for dy in range(-2, 3):
                        for dx in range(-2, 3):
                            put(grid, ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)

    def format_bits(g: Grid, m: int) -> None:    # level M (0b00) and the mask, with their own error correction
        rem = m
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (m << 10 | rem) ^ 0x5412
        for i in range(6):
            put(g, 8, i, bits >> i & 1)
        put(g, 8, 7, bits >> 6 & 1)
        put(g, 8, 8, bits >> 7 & 1)
        put(g, 7, 8, bits >> 8 & 1)
        for i in range(9, 15):
            put(g, 14 - i, 8, bits >> i & 1)
        for i in range(8):
            put(g, size - 1 - i, 8, bits >> i & 1)
        for i in range(8, 15):
            put(g, 8, size - 15 + i, bits >> i & 1)
        put(g, 8, size - 8, 1)

    format_bits(grid, 0)                         # reserves its modules; redrawn with the chosen mask
    if ver >= 7:
        rem = ver
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        bits = ver << 12 | rem
        for i in range(18):
            put(grid, size - 11 + i % 3, i // 3, bits >> i & 1)
            put(grid, i // 3, size - 11 + i % 3, bits >> i & 1)
    i, total, right = 0, len(words) * 8, size - 1
    while right >= 1:                            # data goes up and down two columns at a time, skipping column 6
        if right == 6:
            right = 5
        for vert in range(size):
            for j in range(2):
                x = right - j
                y = size - 1 - vert if ((right + 1) & 2) == 0 else vert
                if not fixed[y][x] and i < total:
                    grid[y][x] = bool(words[i >> 3] >> (7 - (i & 7)) & 1)
                    i += 1
        right -= 2

    def masked(m: int) -> Grid:
        g = [[grid[y][x] ^ (not fixed[y][x] and MASKS[m](x, y)) for x in range(size)] for y in range(size)]
        format_bits(g, m)
        return g

    if mask is not None:
        return masked(mask)
    return min((masked(m) for m in range(8)), key=_penalty)


def qr_text(g: Grid, border: int = 2) -> str:
    """The QR code for a terminal, two rows of modules to a line, drawn black on white (ANSI colors) so it
    scans in a dark terminal too."""
    n = len(g)

    def dark(x: int, y: int) -> bool:
        return 0 <= x - border < n and 0 <= y - border < n and g[y - border][x - border]

    blocks = {(False, False): " ", (True, False): "▀", (False, True): "▄", (True, True): "█"}
    rows = range(0, n + 2 * border, 2)
    return "\n".join("  \033[30;47m" + "".join(blocks[dark(x, y), dark(x, y + 1)] for x in range(n + 2 * border))
                     + "\033[0m" for y in rows)


def qr_svg(g: Grid, border: int = 4) -> str:
    n = len(g) + 2 * border
    path = "".join(f"M{x + border},{y + border}h1v1h-1z" for y, row in enumerate(g) for x, v in enumerate(row) if v)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" shape-rendering="crispEdges">'
            f'<rect width="{n}" height="{n}" fill="#fff"/><path d="{path}" fill="#000"/></svg>')


# ----------------------------------------------------------------------------- the access code and the address

def access_file(root: Path) -> Path:
    return root / ".kit" / "share.json"


def save_access(root: Path, access: Dict[str, str]) -> None:
    p = access_file(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(access) + "\n", encoding="utf-8")
    try:
        tmp.chmod(0o600)                         # exFAT keeps no permissions
    except OSError:
        pass
    os.replace(tmp, p)


def load_access(root: Path, create: bool = True) -> Dict[str, str]:
    """The access code, and the key that signs the cookie a device gets once it has typed the code.
    In .kit/, never kit.json: people share kit.json files."""
    try:
        access = json.loads(access_file(root).read_text(encoding="utf-8"))
        if access.get("code") and access.get("key"):
            return access
    except (OSError, ValueError):
        pass
    if not create:
        return {}
    access = {"code": new_code(), "key": secrets.token_hex(32)}
    save_access(root, access)
    return access


def new_code() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(8))


def clean_code(text: str) -> str:
    return re.sub(r"[\s-]", "", text or "")


def valid_code(text: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9]{6,64}", clean_code(text)))


def pretty_code(code: str) -> str:
    """8 digits read better as two groups: 4821 7736."""
    return " ".join(code[i:i + 4] for i in range(0, len(code), 4)) if code.isdigit() else code


def lan_ips() -> List[str]:
    """This computer's IPv4 addresses on its network, the likeliest first. Asking which address a route
    to the router would use sends nothing, and works offline. KIT_LAN_IP picks one by hand."""
    if os.environ.get("KIT_LAN_IP"):
        return [os.environ["KIT_LAN_IP"]]
    found: List[str] = []

    def add(ip: str) -> None:
        ip = ip.strip()
        if ip and ip not in found and on_home_network(ip) and not ip.startswith(("127.", "169.254.")):
            found.append(ip)

    for probe in ("192.168.0.1", "10.0.0.1", "172.16.0.1"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((probe, 9))
                add(s.getsockname()[0])
        except OSError:
            pass
    if WINDOWS:    # the addresses of every network this PC is on
        try:
            for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
                add(ip)
        except OSError:
            pass
        return found
    cmds = ([["ipconfig", "getifaddr", i] for i in ("en0", "en1", "bridge100")] if MAC else [["hostname", "-I"]])
    for cmd in cmds:
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        for ip in out.split():
            add(ip)
    return found


def local_name() -> str:
    """name.local, when other devices can find this computer by name (Bonjour on a Mac, Avahi on Linux). Phones
    can't find a Windows PC by name."""
    if WINDOWS:
        return ""
    if MAC:
        try:
            name = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True,
                                  timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            name = ""
    else:
        name = socket.gethostname().split(".")[0] if Path("/run/avahi-daemon/pid").exists() else ""
    return f"{name}.local" if re.fullmatch(r"[A-Za-z0-9-]+", name or "") else ""


HOME_NETWORKS = [ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",     # home networks
    "127.0.0.0/8", "169.254.0.0/16",                     # this computer, and networks with no router
    "100.64.0.0/10")]                                     # carrier-grade NAT and Tailscale


def on_home_network(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if a.version == 6:
        a = a.ipv4_mapped or a
    return a.version == 4 and any(a in n for n in HOME_NETWORKS)


# Names only a home network hands out. A website elsewhere can't point one of these at this computer.
LOCAL_SUFFIXES = (".local", ".lan", ".home", ".internal", ".localdomain", ".home.arpa", ".fritz.box", ".ts.net")


def local_host(host: str) -> bool:
    """Whether a Host header names this computer the way a home network does: an address, a bare name like
    homeserver, or a name like homeserver.local. A web page elsewhere can point a name it owns at this computer
    and reach the gate as its own site (DNS rebinding), so other names are turned away."""
    name = host.strip().lower()
    name = (name[1:].split("]")[0] if name.startswith("[") else name.rsplit(":", 1)[0]).rstrip(".")
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return "." not in name or name.endswith(LOCAL_SUFFIXES)


def join_url(host: str, code: str) -> str:
    """The link in the QR code: it opens the kit and lets the device in."""
    return f"http://{host}/?code={urllib.parse.quote(code)}"


def gate_port(port: int) -> int:
    """The port the gate answers on: share_port, or the next free one the launcher took because another program
    had it. 0 when the kit isn't shared right now."""
    for p in range(port, port + 10):
        c = http.client.HTTPConnection("127.0.0.1", p, timeout=1)
        try:
            c.request("HEAD", "/")
            if c.getresponse().getheader("Server") == "TinfoilKit":
                return p
        except OSError:
            pass
        finally:
            c.close()
    return 0


def banner(root: Path, port: int, qr: bool) -> str:
    port = gate_port(port) or port
    code = load_access(root)["code"]
    ips = lan_ips()
    if not ips:
        return (f"  Sharing is on (access code {pretty_code(code)}), but this computer isn't on a home network.\n"
                f"  Connect it to your Wi-Fi or router (no internet needed), then run {kit_cmd('share')} to see its\n"
                "  address.")
    lines = [f"  On your home network: open http://{ips[0]}:{port} on a phone or laptop",
             f"  Access code: {pretty_code(code)}"]
    name = local_name()
    if name:
        lines.append(f"  Laptops can also use http://{name}:{port}")
    if qr and colors_on():
        lines += ["  Or scan this with a phone's camera:", "", qr_text(qr_code(join_url(f"{ips[0]}:{port}", code))), ""]
    return "\n".join(lines)


def colors_on() -> bool:
    """Whether the terminal draws the QR code's colors. Windows' console does once a program asks it to."""
    if not WINDOWS:
        return True
    try:
        import ctypes
        k = ctypes.windll.kernel32
        out, mode = k.GetStdHandle(-11), ctypes.c_uint32()    # standard output
        # 4: ENABLE_VIRTUAL_TERMINAL_PROCESSING, which draws colors
        return bool(k.GetConsoleMode(out, ctypes.byref(mode)) and k.SetConsoleMode(out, mode.value | 4))
    except (AttributeError, OSError):
        return False


# ----------------------------------------------------------------------------- the gate

COOKIE = "tinfoilkit"
ROUTES = ("ai", "tiles", "geocoder", "routing")
# llama-server's own chat page may ask for its API at the root; the library has nothing at these paths.
AI_PATHS = ("/v1/", "/props", "/models", "/slots", "/health", "/completion", "/tokenize", "/detokenize",
            "/apply-template", "/infill", "/embedding", "/rerank", "/lora-adapters", "/metrics")
# llama-server features that run things on this computer (tools, a web proxy). The kit leaves them off; if someone
# turns them on for themselves, they still stay off for the network. Same answer llama-server gives when they're off.
AI_OFF = ("/tools", "/cors-proxy")
AI_OFF_ANSWER = b'{"error": {"message": "this feature is disabled", "type": "feature_disabled"}}'

DROP_REQUEST = {"connection", "keep-alive", "proxy-authorization", "proxy-connection", "te", "trailer",
                "transfer-encoding", "upgrade", "host", "cookie", "authorization", "origin", "referer", "content-length"}
DROP_RESPONSE = {"connection", "keep-alive", "transfer-encoding", "server", "date", "trailer", "upgrade"}
MAX_BODY = 64 * 10**6           # a photo for the AI goes up as base64
TRIES, TRIES_WINDOW = 10, 600   # wrong codes allowed from one address in 10 minutes


def ai_off(path: str) -> bool:
    """Is this one of AI_OFF, however it's spelled? llama-server decodes %74ools as /tools."""
    p = re.sub("/+", "/", "/" + urllib.parse.unquote(path.split("?", 1)[0].split("#", 1)[0]))
    return posixpath.normpath(p) in AI_OFF


LOGIN = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer"><title>Tinfoil Kit</title><link rel="icon" href="data:,">
<style>
/* the website's look, like the kit's own page: paper, ink and signal orange */
:root { --bg:#f3f0e6; --panel:#eae6d8; --ink:#1c1f1a; --ink2:#3a3e36; --olive:#4a5a2a; --signal:#d9531e; --bad:#9a3a10;
  --line:#1c1f1a; --btn-line:#1c1f1a; color-scheme:light dark;
  --sans:"IBM Plex Sans", system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --mono:"IBM Plex Mono", ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace; }
@media (prefers-color-scheme: dark) { :root { --bg:#1c1f1a; --panel:#262a23; --ink:#f3f0e6; --ink2:#cfcbbe; --olive:#a9b87a;
  --signal:#e4672f; --bad:#e0884f; --line:#cfcbbe; --btn-line:#e4672f; } }
* { box-sizing:border-box; }
body { margin:0; min-height:100vh; display:grid; place-items:center; padding:16px; background:var(--bg); color:var(--ink);
  font:16px/1.5 var(--sans); -webkit-font-smoothing:antialiased; }
main { width:100%; max-width:26rem; border:2px solid var(--line); }
h1 { margin:0; padding:12px 20px; border-bottom:2px solid var(--line); background:var(--panel);
  font:600 16px var(--mono); letter-spacing:.04em; text-transform:uppercase; }
form { padding:20px; }
p { margin:0 0 18px; color:var(--ink2); }
label { display:block; margin-bottom:6px; font:600 13px var(--mono); letter-spacing:.06em; text-transform:uppercase;
  color:var(--olive); }
input { width:100%; min-height:52px; padding:0 14px; font:500 22px var(--mono); letter-spacing:.12em; color:var(--ink);
  background:var(--bg); border:2px solid var(--line); border-radius:4px; }
button { width:100%; min-height:52px; margin-top:14px; font:600 17px var(--sans); color:#1c1f1a; background:#e4672f;
  border:2px solid var(--btn-line); border-radius:4px; cursor:pointer; }
button:hover { background:#ea7038; }
:focus-visible { outline:3px solid var(--signal); outline-offset:2px; }
.err { color:var(--bad); font-weight:600; }
</style></head>
<body><main>
<h1>Tinfoil Kit</h1>
<form method="post" action="/_kit/login">
<p>This kit is shared on your home network. Enter the access code shown on the computer it runs on.</p>
@@ERROR@@
<label for="code">Access code</label>
<input id="code" name="code" inputmode="numeric" autocomplete="off" autocapitalize="off" spellcheck="false" required autofocus>
<input type="hidden" name="next" value="@@NEXT@@">
<button type="submit">Open the kit</button>
</form>
</main></body></html>
"""


class Gate(http.server.ThreadingHTTPServer):
    daemon_threads = True
    # On Windows it would let the gate share a port another program is listening on, instead of failing.
    allow_reuse_address = not WINDOWS

    def __init__(self, root: Path, port: int, ports: Dict[str, int]):
        self.root, self.port, self.ports = root, port, ports
        self.lock = threading.Lock()
        self.failures: Dict[str, List[float]] = {}
        self._access: Tuple[float, str, str] = (-1.0, "", "")
        super().__init__(("0.0.0.0", port), Handler)

    def server_bind(self) -> None:
        # Without http.server's lookup of this computer's own name (name.local): on a Mac, where the gate starts
        # with the computer, that would ask to "find devices on local networks", and answering them needs no such thing.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]

    def access(self) -> Tuple[str, str]:
        """The access code and the cookie that proves it, read again whenever ./kit share changes the code."""
        try:
            mtime = access_file(self.root).stat().st_mtime
        except OSError:
            mtime = 0.0
        with self.lock:
            if mtime != self._access[0]:
                a = load_access(self.root)
                cookie = hmac.new(bytes.fromhex(a["key"]), a["code"].encode(), hashlib.sha256).hexdigest()
                self._access = (mtime, a["code"], cookie)
            return self._access[1], self._access[2]

    def too_many(self, ip: str) -> bool:
        now = time.time()
        with self.lock:
            recent = [t for t in self.failures.get(ip, []) if now - t < TRIES_WINDOW]
            self.failures[ip] = recent
            return len(recent) >= TRIES

    def failed(self, ip: str) -> None:
        now = time.time()
        with self.lock:
            for k in [k for k, v in self.failures.items() if not v or now - v[-1] >= TRIES_WINDOW]:
                del self.failures[k]
            self.failures.setdefault(ip, []).append(now)


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    body_read = False
    server: Gate

    def version_string(self) -> str:
        return "TinfoilKit"

    def log_request(self, code: object = "-", size: object = "-") -> None:
        pass    # the request line can hold the access code (the QR code's link)

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {self.client_address[0]} {fmt % args}\n")

    def do_GET(self) -> None:
        self.body_read = False
        try:
            self.respond()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, socket.timeout):
            self.close_connection = True    # the browser left (a stopped answer, a closed tab)

    do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_GET

    # -- answering

    def send(self, status: int, ctype: str, body: bytes, headers: Tuple[Tuple[str, str], ...] = ()) -> None:
        self.send_response(status)
        for k, v in (("Content-Type", ctype), ("Content-Length", str(len(body))), ("Cache-Control", "no-store"),
                     *headers):
            self.send_header(k, v)
        if self.close_connection or not self.body_read and (self.headers.get("Transfer-Encoding") or
                                   (self.headers.get("Content-Length") or "0").strip() not in ("", "0")):
            # Answered without reading what the device sent (turned away, or llama-server's tools): the rest of
            # it would be read as the next request on this connection, so close it instead.
            self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def redirect(self, where: str, cookie: str = "") -> None:
        headers = [("Location", where)]
        if cookie:
            headers.append(("Set-Cookie", f"{COOKIE}={cookie}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Lax"))
        self.send(303, "text/plain; charset=utf-8", b"", tuple(headers))

    def login_page(self, status: int, nxt: str, error: str = "") -> None:
        body = LOGIN.replace("@@ERROR@@", f'<p class="err" role="alert">{html.escape(error)}</p>' if error else "")
        body = body.replace("@@NEXT@@", html.escape(nxt, quote=True))
        self.send(status, "text/html; charset=utf-8", body.encode())

    def public_host(self) -> str:
        """The address other devices can reach the kit at: the one this device used, unless that was this computer."""
        host = self.headers.get("Host", "")
        name = host.rsplit(":", 1)[0].strip("[]")
        if not name or name in ("localhost", "::1") or name.startswith("127."):
            ips = lan_ips()
            return f"{ips[0]}:{self.server.port}" if ips else host
        return host

    # -- the access code

    def body(self) -> Optional[bytes]:
        self.body_read = True
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            parts, total = [], 0
            while True:
                size = int(self.rfile.readline(1024).split(b";")[0].strip() or b"0", 16)
                if not size:
                    while self.rfile.readline(1024).strip():
                        pass    # trailers
                    break
                total += size
                if total > MAX_BODY:
                    raise ValueError
                parts.append(self.rfile.read(size))
                self.rfile.readline(16)
            return b"".join(parts)
        n = int(self.headers.get("Content-Length") or 0)
        if n < 0 or n > MAX_BODY:
            raise ValueError
        return self.rfile.read(n) if n else None

    def code_ok(self, given: str, code: str) -> Optional[bool]:
        """True or False, or None when this device has had too many tries."""
        ip = self.client_address[0]
        if self.server.too_many(ip):
            return None
        if hmac.compare_digest(clean_code(given).encode(), code.encode()):
            return True
        self.server.failed(ip)
        return False

    def signed_in(self, code: str, cookie: str) -> Optional[bool]:
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE and hmac.compare_digest(v.encode(), cookie.encode()):
                return True
        auth = self.headers.get("Authorization", "")
        if auth[:7].lower() == "bearer ":    # for programs: the access code as the API key
            return self.code_ok(auth[7:], code)
        return False

    # -- routing

    def respond(self) -> None:
        if not on_home_network(self.client_address[0]):
            self.close_connection = True
            return self.send(403, "text/plain; charset=utf-8", b"Tinfoil Kit only answers devices on its home network.\n")
        if not local_host(self.headers.get("Host", "")):
            self.close_connection = True
            ips = lan_ips()
            where = f" Open http://{ips[0]}:{self.server.server_address[1]} instead." if ips else ""
            return self.send(403, "text/plain; charset=utf-8", f"Tinfoil Kit doesn't answer to that name.{where}\n".encode())
        url = urllib.parse.urlsplit(self.path)
        code, cookie = self.server.access()
        if url.path == "/_kit/login" and self.command == "POST":
            try:
                form = urllib.parse.parse_qs((self.body() or b"")[:4096].decode("utf-8", "replace"))
            except ValueError:
                return self.send(413, "text/plain; charset=utf-8", b"Too big.\n")
            nxt = form.get("next", ["/"])[0]
            if not nxt.startswith("/") or nxt.startswith("//") or "\\" in nxt:
                nxt = "/"
            ok = self.code_ok(form.get("code", [""])[0], code)
            if ok:
                return self.redirect(nxt, cookie)
            return self.login_page(429 if ok is None else 401, nxt, "Too many tries. Wait a few minutes, then try again."
                                   if ok is None else "That code didn't work. Check it and try again.")
        query = urllib.parse.parse_qsl(url.query, keep_blank_values=True)
        given = [v for k, v in query if k == "code"]
        if given and self.command in ("GET", "HEAD"):    # the QR code's link: let the device in, then tidy the address
            rest = urllib.parse.urlencode([(k, v) for k, v in query if k != "code"])
            ok = self.code_ok(given[0], code)
            if ok:
                return self.redirect(url.path + ("?" + rest if rest else ""), cookie)
            return self.login_page(429 if ok is None else 401, url.path + ("?" + rest if rest else ""),
                                   "Too many tries. Wait a few minutes, then try again." if ok is None
                                   else "That link's access code is out of date. Ask for the new one.")
        ok = self.signed_in(code, cookie)
        if not ok:
            if ok is None:
                return self.send(429, "application/json", b'{"error": "too many wrong access codes, wait a few minutes"}')
            if self.command == "GET" and (url.path == "/" or "text/html" in self.headers.get("Accept", "")):
                return self.login_page(401, self.path)
            return self.send(401, "application/json", b'{"error": "this needs the kit\'s access code"}')
        if url.path == "/_kit/qr.svg":
            return self.send(200, "image/svg+xml", qr_svg(qr_code(join_url(self.public_host(), code))).encode())
        if url.path == "/ai":
            return self.redirect("/ai/")
        name, path = "library", self.path
        for r in ROUTES:
            if url.path.startswith(f"/{r}/"):
                name, path = r, self.path[len(r) + 1:]
                break
        else:
            if url.path.startswith(AI_PATHS):
                name = "ai"
        if name == "ai" and ai_off(path):
            return self.send(403, "application/json", AI_OFF_ANSWER)
        self.proxy(name, path, inject=(name == "library" and url.path == "/" and self.command == "GET"), code=code)

    def proxy(self, name: str, path: str, inject: bool, code: str) -> None:
        port = self.server.ports.get(name)
        what = {"library": "The library", "ai": "The AI", "tiles": "The map", "geocoder": "Address search",
                "routing": "Directions"}[name]
        try:
            body = self.body()
        except ValueError:
            self.close_connection = True
            return self.send(413, "text/plain; charset=utf-8", b"Too big.\n")
        if not port:
            return self.send(502, "text/plain; charset=utf-8", f"{what} isn't part of this kit.\n".encode())
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=900)    # a model can think for minutes
        try:
            conn.putrequest(self.command, path, skip_host=True, skip_accept_encoding=True)
            conn.putheader("Host", f"127.0.0.1:{port}")
            for k, v in self.headers.items():
                low = k.lower()
                if low in DROP_REQUEST or (inject and low in ("accept-encoding", "if-none-match", "if-modified-since")):
                    continue
                conn.putheader(k, v)
            if body is not None:
                conn.putheader("Content-Length", str(len(body)))
            conn.endheaders(body)
            resp = conn.getresponse()
        except OSError:
            conn.close()
            return self.send(502, "text/plain; charset=utf-8",
                             f"{what} isn't running yet. It can take a minute to start: try again soon.\n".encode())
        try:
            self.relay(resp, inject, code)
        finally:
            conn.close()

    def relay(self, resp: http.client.HTTPResponse, inject: bool, code: str) -> None:
        headers = [(k, v) for k, v in resp.getheaders()
                   if k.lower() not in DROP_RESPONSE and not k.lower().startswith("access-control-")]
        if inject and resp.status == 200 and "text/html" in (resp.getheader("Content-Type") or ""):
            # The kit page: tell it that it came through the gate, so it asks the gate for the AI and the map.
            info = {"address": "http://" + self.public_host(), "code": pretty_code(code)}
            tag = b"<script>window.KIT_GATE = " + json.dumps(info).replace("</", "<\\/").encode() + b";</script>"
            data = resp.read()
            i = data.find(b"<head>")
            data = data[:i + 6] + tag + data[i + 6:] if i >= 0 else tag + data
            keep = [(k, v) for k, v in headers if k.lower() not in ("content-length", "etag", "last-modified", "cache-control")]
            self.send_response(resp.status, resp.reason)
            for k, v in keep + [("Content-Length", str(len(data))), ("Cache-Control", "no-store")]:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)
            return
        empty = self.command == "HEAD" or resp.status in (204, 304) or resp.status < 200
        stream = not empty and resp.getheader("Content-Length") is None    # an answer the AI writes as it goes
        self.send_response(resp.status, resp.reason)
        for k, v in headers:
            self.send_header(k, v)
        if stream:
            self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        if empty:
            return
        while True:
            data = resp.read1(65536) if stream else resp.read(65536)
            if not data:
                break
            self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data) if stream else data)
        if stream:
            self.wfile.write(b"0\r\n\r\n")


def serve(root: Path, port: int, ports: Dict[str, int]) -> None:
    load_access(root)
    try:
        gate = Gate(root, port, ports)
    except OSError as e:
        sys.exit(f"Can't share on port {port}: {e.strerror}")
    print(f"Sharing on port {port}: " + ", ".join(f"{k} {v}" for k, v in ports.items()), flush=True)
    stay_awake()
    try:
        gate.serve_forever()
    except KeyboardInterrupt:
        pass


def stay_awake() -> None:
    """Windows goes to sleep after a while with nobody at the keyboard, and the kit with it. The launcher keeps a Mac
    or Linux PC awake. On Windows the gate asks Windows not to sleep while it runs (the screen can still turn off)."""
    if WINDOWS:
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)    # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        except (AttributeError, OSError):
            pass


# ----------------------------------------------------------------------------- start with the computer

SERVICE = "tinfoil-kit.service"
AGENT = "com.tinfoilkit.kit"


def launcher(root: Path) -> Path:
    return root / "Open Tinfoil Kit for Windows.bat" if WINDOWS else root / "tools" / "launch.sh"


def systemd_unit(root: Path) -> str:
    """A systemd user service: it runs as you, without sudo, and from boot when lingering is on."""
    arg = str(launcher(root)).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$")
    return ("[Unit]\nDescription=Tinfoil Kit: the offline AI, library and maps\n\n"
            "[Service]\n"
            f'ExecStart=/bin/bash "{arg}" --no-browser\n'
            # It comes back if it stops, or finds the kit already running in a window and leaves it be.
            "Restart=always\nRestartSec=30\n\n"
            "[Install]\nWantedBy=default.target\n")


def unit_file() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user" / SERVICE


def agent_file() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{AGENT}.plist"


def startup_file() -> Path:
    """Windows runs what's in this folder when you sign in."""
    roaming = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(roaming) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Tinfoil Kit.cmd"


def startup_script(root: Path) -> str:
    """Open Tinfoil Kit for Windows.bat, minimized, if the kit is still there (a drive can be unplugged). In UTF-8
    (chcp 65001) for a folder named in any language, with % doubled since cmd reads it as its own."""
    bat = str(launcher(root)).replace("%", "%%")
    return ("@echo off\r\nchcp 65001 >nul\r\n"
            f"rem Starts Tinfoil Kit when you sign in to Windows. {kit_cmd('autostart off')} removes this.\r\n"
            f'if exist "{bat}" start "Tinfoil Kit" /min "{bat}" --no-browser\r\n')


def autostart_file() -> Path:
    return startup_file() if WINDOWS else agent_file() if MAC else unit_file()


def _run(cmd: List[str], env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return subprocess.CompletedProcess(cmd, 127, "", str(e))


def _user_env() -> Dict[str, str]:
    """systemctl --user finds your systemd through XDG_RUNTIME_DIR, which su and some SSH setups leave unset."""
    env = dict(os.environ)
    run_dir = f"/run/user/{os.getuid()}"
    if not env.get("XDG_RUNTIME_DIR") and os.path.isdir(run_dir):
        env["XDG_RUNTIME_DIR"] = run_dir
    return env


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return _run(["systemctl", "--user", *args], _user_env())


def _user() -> str:
    import getpass
    return getpass.getuser()


def _lingering() -> bool:
    return "Linger=yes" in _run(["loginctl", "show-user", _user(), "--property=Linger"]).stdout


def _linger() -> bool:
    """Let your services run from boot, before anyone logs in. Without sudo where systemd allows it."""
    for cmd in (["loginctl", "enable-linger"], ["sudo", "-n", "loginctl", "enable-linger", _user()]):
        if _run(cmd).returncode == 0:
            for _ in range(20):    # systemd starts your services; wait for it to answer
                if os.path.exists(f"/run/user/{os.getuid()}/systemd/private"):
                    break
                time.sleep(0.5)
            return True
    return False


def ours(text: str, root: Path) -> bool:
    if WINDOWS:    # where names are the same in any case
        return str(launcher(root)).lower() in text.lower()
    return str(launcher(root)) in text


def autostart_state(root: Path) -> str:
    """'on', 'off' or 'other' (set up for a different kit folder)."""
    try:
        text = autostart_file().read_text(encoding="utf-8")
    except OSError:
        return "off"
    if WINDOWS:
        text = text.replace("%%", "%")
    elif not MAC:
        text = text.replace("%%", "%").replace("$$", "$").replace('\\"', '"').replace("\\\\", "\\")
    return "on" if ours(text, root) else "other"


def autostart(root: Path, action: str) -> int:
    """./kit autostart on|off|status. Returns the exit code."""
    if action == "status":
        state = autostart_state(root)
        if state == "on":
            print("The kit starts when you sign in to this PC." if WINDOWS else
                  "The kit starts when this computer starts" + (" (once you log in)." if MAC else "." if _lingering()
                  else f", once you log in (see {kit_cmd('autostart on')} to start it before)."))
        elif state == "other":
            print(f"Another kit folder starts with this computer (see {autostart_file()}).")
        else:
            print(f"The kit doesn't start by itself. {kit_cmd('autostart on')} makes it start with this computer.")
        return 0
    if action == "off":
        state = autostart_state(root)
        if state == "other":
            print("Starting with the computer is set up for another kit folder, so it's left as it is.")
            return 0
        if state == "off":
            print("The kit already doesn't start by itself.")
            return 0
        if WINDOWS:    # which window is the one it started can't be told
            startup_file().unlink(missing_ok=True)
            print("The kit no longer starts when you sign in. If it's running, close its window to stop it.")
            return 0
        if MAC:
            _run(["launchctl", "bootout", f"gui/{os.getuid()}/{AGENT}"])
            agent_file().unlink(missing_ok=True)
        else:
            _systemctl("disable", "--now", SERVICE)
            unit_file().unlink(missing_ok=True)
            _systemctl("daemon-reload")
        print("The kit no longer starts by itself, and the copy it started has stopped.")
        return 0
    (root / "logs").mkdir(exist_ok=True)
    if WINDOWS:
        return _startup_on(root)
    if MAC:
        return _launchd_on(root)
    return _systemd_on(root)


def _systemd_on(root: Path) -> int:
    if not shutil.which("systemctl"):
        print("This computer has no systemd, so ./kit autostart can't set this up. Start the kit from your own\n"
              "startup script instead:  bash " + str(launcher(root)) + " --no-browser")
        return 1
    f = unit_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(systemd_unit(root), encoding="utf-8")
    lingering = _lingering() or _linger()
    if _systemctl("daemon-reload").returncode:
        print("Couldn't reach systemd for your user. That happens after su or sudo -i: log in as yourself (over\n"
              f"SSH is fine), or run  sudo loginctl enable-linger {_user()}  once, then try ./kit autostart on again.")
        return 1
    r = _systemctl("enable", SERVICE)
    if r.returncode == 0:
        r = _systemctl("restart", SERVICE)    # restart, so a changed kit folder or setting takes effect
    if r.returncode:
        print("systemd wouldn't start the kit: " + (r.stderr.strip() or r.stdout.strip()))
        return 1
    print("The kit is starting now, and will start whenever this computer does.")
    if not lingering:
        print("For now it starts only once you log in. To start it at boot without logging in, run this once:\n"
              f"  sudo loginctl enable-linger {_user()}")
    print(f"Check on it: systemctl --user status {SERVICE.split('.')[0]}   Logs: the logs folder in the kit.")
    return 0


def _launchd_on(root: Path) -> int:
    f = agent_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    log = str(root / "logs" / "autostart.log")
    with open(f, "wb") as out:
        plistlib.dump({"Label": AGENT, "ProgramArguments": ["/bin/bash", str(launcher(root)), "--no-browser"],
                       "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 30,
                       "StandardOutPath": log, "StandardErrorPath": log}, out)
    domain = f"gui/{os.getuid()}"
    _run(["launchctl", "bootout", f"{domain}/{AGENT}"])    # a previous copy, so the new settings take effect
    r = _run(["launchctl", "bootstrap", domain, str(f)])
    if r.returncode:
        print("macOS wouldn't start the kit: " + (r.stderr.strip() or r.stdout.strip()) +
              "\nLog in to this Mac's desktop (not just over SSH), then run ./kit autostart on again.")
        return 1
    print("The kit is starting now, and will start whenever you log in to this Mac.\n"
          "For a Mac that's a home server, turn on automatic login: System Settings > Users & Groups.")
    if str(root).startswith("/Volumes/"):
        print("The kit is on an external drive, and macOS may not let it start by itself from there. If it\n"
              "doesn't, keep the kit on this Mac instead (SETUP's \"This Mac\").")
    return 0


def _startup_on(root: Path) -> int:
    f = startup_file()
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(startup_script(root).encode("utf-8"))
        os.startfile(str(f))    # start it now, the way it starts when you sign in
    except OSError as e:
        print(f"Couldn't set up starting the kit when you sign in: {e}")
        return 1
    print("The kit is starting now, in a minimized window, and will start whenever you sign in to this PC.\n"
          "For a home server, keep this PC plugged in and signed in (locking it is fine), and sign in again after a\n"
          "restart.")
    return 0


def restart_if_autostarted(root: Path) -> bool:
    """Restart the kit when the computer started it, so a sharing change takes effect. True if it did. Not on
    Windows, where the window it started can't be told from one you opened."""
    if WINDOWS or autostart_state(root) != "on":
        return False
    if MAC:
        return _run(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{AGENT}"]).returncode == 0
    return _systemctl("try-restart", SERVICE).returncode == 0


# ----------------------------------------------------------------------------- command line

def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(prog="share.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the gate")
    s.add_argument("--root", type=Path, required=True)
    s.add_argument("--port", type=int, required=True)
    s.add_argument("--library", type=int, required=True)
    for name in ROUTES:
        s.add_argument(f"--{name}", type=int, default=0)
    b = sub.add_parser("banner", help="print the address, the access code and the QR code")
    b.add_argument("--root", type=Path, required=True)
    b.add_argument("--port", type=int, required=True)
    b.add_argument("--qr", action="store_true", help="draw the QR code even when not printing to a terminal")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    if args.cmd == "serve":
        ports = {"library": args.library, **{r: getattr(args, r) for r in ROUTES if getattr(args, r)}}
        serve(root, args.port, ports)
    else:
        print(banner(root, args.port, args.qr or sys.stdout.isatty()))


if __name__ == "__main__":
    main()
