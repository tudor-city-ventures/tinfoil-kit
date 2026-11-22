"""Helpers for the drive test (tests/drive_test.sh, .github/workflows/drive.yml). Standard library only.

  drive.py check LIB_PORT AI_PORT   wait for the kit's library and AI, then search a book and get an answer; and
                                    when the kit's page says it has a map, get a street-level tile and directions
  drive.py share ADDRESS CODE LIB_PORT AI_PORT
                                    the kit shared on the home network, as a phone there finds it at ADDRESS
  drive.py vhd IMAGE                add a VHD footer to a raw disk image, so Windows can mount the drive a Mac made
  drive.py kitjson FILE [maps]      write the test kit's kit.json, as the website's builder makes one; with maps,
                                    also the map of Andorra, with every computer's real map programs
"""
import http.client
import json
import math
import re
import socket
import struct
import sys
import time
import uuid
import urllib.parse
import urllib.request
from pathlib import Path

from make_tiny_model import ANSWER

# A Windows console can't print every character (a mangled answer, a book's title).
sys.stdout.reconfigure(errors="backslashreplace")
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + (f": {detail}" if detail else ""), flush=True)
    fails += 0 if ok else 1


def fetch(url, body=None, timeout=10):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data, {"Content-Type": "application/json"} if body else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def wait_for(url, seconds):
    for _ in range(seconds):
        try:
            return fetch(url)
        except OSError:
            time.sleep(1)
    return ""


HELLO = {"model": "Tiny", "messages": [{"role": "user", "content": "Hello"}], "max_tokens": 100}


def answer(body):
    """The answer in a chat completion, or what came instead. The test model always gives ANSWER."""
    try:
        return json.loads(body)["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        return body[:300]


def check_kit(lib, ai):
    base = f"http://127.0.0.1:{lib}"
    page = wait_for(base + "/", 120)    # containers install packages first
    check("library page", "Tinfoil Kit" in page, base)
    books = wait_for(base + "/catalog/v2/entries", 5).count("<entry>")
    check("both test books listed", books == 2, f"{books} books")
    found = wait_for(base + "/search?books.filter.lang=eng&pattern=tourniquet", 5)
    check("library search", "Tourniquet" in found)
    models = wait_for(f"http://127.0.0.1:{ai}/v1/models", 90)
    check("AI lists the model", "Tiny" in models, models[:200])
    props = wait_for(f"http://127.0.0.1:{ai}/props", 5)
    check("AI chat's page gets the kit's safety rules", "wild plant" in props, props[:200])
    try:
        said = answer(fetch(f"http://127.0.0.1:{ai}/v1/chat/completions", HELLO, timeout=180))
        check("AI answers, every character intact", said == ANSWER, "" if said == ANSWER else ascii(said)[:300])
    except OSError as e:
        check("AI answers, every character intact", False, str(e))
    check_map(page)


def check_map(page):
    """The map the kit's page offers (window.KIT_MAPS), if any: the tile over home at street level, and directions,
    from the servers this computer's own pmtiles and Java run. The test kit's map is Andorra (kitjson maps)."""
    m = re.search(r"window\.KIT_MAPS = (.*?);</script>", page, re.S)
    info = json.loads(m.group(1)) if m else {}
    if not info.get("available"):
        return
    ports, home, z = info["ports"], info["home"], info["detailMaxzoom"]
    tiles = f"http://127.0.0.1:{ports['tiles']}"
    try:
        tj = json.loads(wait_for(tiles + "/basemap.json", 60) or "{}")
        lat = math.radians(home["lat"])
        x = int((home["lon"] + 180) / 360 * 2 ** z)
        y = int((1 - math.asinh(math.tan(lat)) / math.pi) / 2 * 2 ** z)
        with urllib.request.urlopen(f"{tiles}/basemap/{z}/{x}/{y}.mvt", timeout=10) as r:
            tile = r.read()
        check("map tiles", tj.get("maxzoom") == z and len(tile) > 0,
              f"zoom {tj.get('minzoom')} to {tj.get('maxzoom')}, and the tile over {home['label']} ({len(tile)} bytes)")
    except (OSError, ValueError) as e:
        check("map tiles", False, str(e))
    if info["services"]["routing"]:    # GraphHopper loads the roads first, which takes a while on a slow drive
        route = f"http://127.0.0.1:{ports['routing']}/route?point=42.5063,1.5218&point=42.5345,1.5803" \
                f"&profile={info['profiles'][0]}&points_encoded=false"
        try:
            path = json.loads(wait_for(route, 180) or "{}").get("paths", [{}])[0]
            check("directions across Andorra", path.get("distance", 0) > 0,
                  f"{round(path.get('distance', 0))} m in {len(path.get('instructions', []))} steps")
        except ValueError as e:
            check("directions across Andorra", False, str(e))


def ask(method, url, body=None, headers=None, timeout=10):
    """(status, body, headers), whatever the status, and without following redirects."""
    u = urllib.parse.urlsplit(url)
    c = http.client.HTTPConnection(u.hostname, u.port, timeout=timeout)
    try:
        c.request(method, (u.path or "/") + ("?" + u.query if u.query else ""), body, headers or {})
        r = c.getresponse()
        return r.status, r.read().decode("utf-8", "replace"), {k.lower(): v for k, v in r.getheaders()}
    except OSError as e:
        return 0, str(e), {}
    finally:
        c.close()


def check_share(address, code, lib, ai):
    """The gate at ADDRESS asks for the access code, then serves the page, the library and the AI. The servers
    behind it don't answer on the network themselves."""
    status, page = 0, ""
    for _ in range(90):
        status, page, _ = ask("GET", address + "/", headers={"Accept": "text/html"})
        if status:
            break
        time.sleep(1)
    check("the gate asks for the access code", status == 401 and "Access code" in page, str(status))
    status, _, _ = ask("GET", address + "/ai/v1/models")
    check("without the code, no AI", status == 401, str(status))
    form = {"Content-Type": "application/x-www-form-urlencoded"}
    status, _, _ = ask("POST", address + "/_kit/login", "code=00000001&next=/", form)
    check("a wrong code is turned away", status == 401, str(status))
    status, _, h = ask("POST", address + "/_kit/login", f"code={code}&next=/", form)
    cookie = h.get("set-cookie", "").split(";")[0]
    check("the right code lets the phone in", status == 303 and cookie.startswith("tinfoilkit="), str(status))
    signed = {"Cookie": cookie}
    status, page, _ = ask("GET", address + "/", headers=signed)
    check("the kit page, told it's shared", status == 200 and "Tinfoil Kit" in page and "KIT_GATE" in page, str(status))
    _, entries, _ = ask("GET", address + "/catalog/v2/entries", headers=signed)
    check("the library, through the gate", entries.count("<entry>") == 2, f"{entries.count('<entry>')} books")
    models = ""
    for _ in range(90):
        status, models, _ = ask("GET", address + "/ai/v1/models", headers=signed)
        if status == 200:
            break
        time.sleep(1)
    check("the AI, through the gate", "Tiny" in models, models[:200])
    status, out, _ = ask("POST", address + "/ai/v1/chat/completions", json.dumps(HELLO),
                         {**signed, "Content-Type": "application/json"}, timeout=180)
    said = answer(out)
    check("the AI answers through the gate, every character intact", status == 200 and said == ANSWER,
          "" if said == ANSWER else f"{status} {ascii(said)[:300]}")
    status, svg, _ = ask("GET", address + "/_kit/qr.svg", headers=signed)
    check("the QR code", status == 200 and svg.startswith("<svg"), str(status))
    status, _, _ = ask("GET", address + "/", headers={**signed, "Host": "evil.example.com"})
    check("a website's own name for this computer is turned away", status == 403, str(status))
    host = urllib.parse.urlsplit(address).hostname
    for name, port in (("library", lib), ("AI", ai)):
        try:
            socket.create_connection((host, int(port)), timeout=3).close()
            check(f"the {name} server doesn't answer on the network itself", False, f"{host}:{port} answered")
        except OSError:
            check(f"the {name} server doesn't answer on the network itself", True)


def kit_json(out, maps=False):
    """The test kit: the real Mac, Windows and Linux programs, the tiny model and two test books, and with maps, a
    map whose roads are Andorra's (small and real)."""
    tests = Path(__file__).resolve().parent
    t = json.loads((tests / "drive_kit.json").read_text(encoding="utf-8"))
    k = json.loads((tests.parent / "kit.json").read_text(encoding="utf-8"))
    t["runtimes"] = [r for r in k["runtimes"] if maps or not r.get("requires")]
    if maps:    # as "Where do you live?" sets it, with tiles to zoom 5 only, all the mock's map build has
        t["maps"] = {**k["maps"], "region": "andorra", "world_maxzoom": 2, "detail_maxzoom": 5}
    t["models"] = [m for m in t["models"] if m["id"] == "Tiny"]
    t["library"] = [z for z in t["library"] if z["zim"] in ("testmed_en_all_maxi", "testsurvival_en")]
    t["settings"].update(library_port=8888, ai_port=8080)
    Path(out).write_text(json.dumps(t, indent=2), encoding="utf-8")


def chs(total_sectors):
    """Disk geometry, as the VHD format specifies it."""
    total_sectors = min(total_sectors, 65535 * 16 * 255)
    if total_sectors >= 65535 * 16 * 63:
        spt, heads = 255, 16
        cyl_heads = total_sectors // spt
    else:
        spt = 17
        cyl_heads = total_sectors // spt
        heads = max((cyl_heads + 1023) // 1024, 4)
        if cyl_heads >= heads * 1024 or heads > 16:
            spt, heads = 31, 16
            cyl_heads = total_sectors // spt
        if cyl_heads >= heads * 1024:
            spt, heads = 63, 16
            cyl_heads = total_sectors // spt
    return cyl_heads // heads, heads, spt


def add_vhd_footer(path):
    """A fixed VHD is the raw disk followed by a 512-byte footer."""
    with open(path, "r+b") as f:
        size = f.seek(0, 2)
        if size % 512:
            sys.exit(f"{path}: size {size} is not a whole number of sectors")
        cyl, heads, spt = chs(size // 512)
        footer = bytearray(struct.pack(
            ">8sIIQI4sI4sQQHBBII16sB",
            b"conectix", 2, 0x00010000, 0xFFFFFFFFFFFFFFFF, int(time.time()) - 946684800,
            # "win " as the creator, as Windows writes it, so every reader takes the exact size, not the geometry's
            b"win ", 0x000A0000, b"Wi2k", size, size, cyl, heads, spt, 2, 0, uuid.uuid4().bytes, 0))
        footer += bytes(512 - len(footer))
        struct.pack_into(">I", footer, 64, ~sum(footer) & 0xFFFFFFFF)
        f.write(footer)


if __name__ == "__main__":
    if sys.argv[1:2] == ["check"] and len(sys.argv) == 4:
        check_kit(sys.argv[2], sys.argv[3])
        print("\nALL PASSED" if not fails else f"\n{fails} FAILED")
        sys.exit(1 if fails else 0)
    if sys.argv[1:2] == ["share"] and len(sys.argv) == 6:
        check_share(*sys.argv[2:6])
        print("\nALL PASSED" if not fails else f"\n{fails} FAILED")
        sys.exit(1 if fails else 0)
    if sys.argv[1:2] == ["vhd"] and len(sys.argv) == 3:
        add_vhd_footer(sys.argv[2])
        sys.exit(0)
    if sys.argv[1:2] == ["kitjson"] and len(sys.argv) in (3, 4):
        kit_json(sys.argv[2], sys.argv[3:] == ["maps"])
        sys.exit(0)
    sys.exit(__doc__)
