"""The internet the phone app reaches, in miniature, for its tests in CI.

Kiwix: every book the app asks for is published with its SHA-256, behind a redirect to a mirror the way
download.kiwix.org answers. Given a folder of the test books tests/make_zims.py makes, each is one of those (the
medical one for medical books); otherwise a small file.

Protomaps: given a folder from src/kit/protomaps.test.ts (E2E_MAP), its piece of the world map, answering range
requests as build.protomaps.com does, and the kit page's fonts and icons.

A kit at home, shared with the access code 48217736: its list of what a phone can copy (/data/files), one book and
the book itself, and, given the piece of the world map, a map of Alabama from the next day's world map, with the
fonts and icons, as the kit's gate and notes server answer. The app reaches it when the address is typed in.

python3 mobile/e2e/internet.py [PORT [BOOKS [MAP]]], and build the app with
EXPO_PUBLIC_KIWIX_CATALOG=http://localhost:PORT/catalog/v2/entries
EXPO_PUBLIC_PROTOMAPS_BUILDS=http://localhost:PORT/protomaps/builds.json
EXPO_PUBLIC_PROTOMAPS_BUILD_BASE=http://localhost:PORT/protomaps
EXPO_PUBLIC_BASEMAPS_ASSETS=http://localhost:PORT/assets
"""

import hashlib
import json
import re
import sys
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 19100
BOOKS = Path(sys.argv[2]) if len(sys.argv) > 2 else None
MAP = Path(sys.argv[3]) if len(sys.argv) > 3 else None


CODE = "48217736"
KIT_BOOK = "downloads/library/ready.gov_en_all_2026-04.zim"  # a book the try-it kit doesn't have
KIT_MAP = "downloads/maps/tiles/basemap.pmtiles"
KIT_ASSETS = "downloads/maps/viewer/basemaps-assets/2026-11-01/basemaps-assets-main"
REGIONS = Path(__file__).resolve().parents[2] / "site" / "regions.json"


def world_map() -> Path | None:
    """The piece of the world map, named for its day"""
    return MAP / json.loads((MAP / "builds.json").read_text())[0]["key"] if MAP else None


def kit_map() -> dict | None:
    """The kit at home's map: Alabama's, from the day after the piece's world map, so it's newer than the phone's"""
    world = world_map()
    if not world:
        return None
    alabama = next(r for r in json.loads(REGIONS.read_text())["regions"] if r["id"] == "us/alabama")
    day = date(int(world.name[:4]), int(world.name[4:6]), int(world.name[6:8])) + timedelta(days=1)
    return {
        "id": "map",
        "title": "Map",
        "group": "Maps",
        "why": "Streets and places in Alabama.",
        "files": [{"path": KIT_MAP, "bytes": world.stat().st_size}],
        "areas": [alabama["bbox"]],
        "day": day.strftime("%Y%m%d"),
        "assets": KIT_ASSETS,
    }


def content(file: str) -> bytes:
    if BOOKS:
        return (
            BOOKS / ("testmed_en_all_maxi_2026-01.zim" if "medic" in file else "testsurvival_en_2026-05.zim")
        ).read_bytes()
    return (file.encode() + b"\n") * 4000  # a few hundred KB, so the app shows some progress


class Internet(BaseHTTPRequestHandler):
    def send(self, body: bytes, kind: str, status=200, location="", extra=()):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        if location:
            self.send_header("Location", location)
        for name, value in extra:
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    # A file, or the bytes a Range header asks for
    def send_file(self, file: Path, kind: str):
        body = file.read_bytes()
        m = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers.get("Range", ""))
        if not m:
            return self.send(body, kind, extra=[("Accept-Ranges", "bytes")])
        first = int(m.group(1))
        last = min(int(m.group(2) or len(body) - 1), len(body) - 1)
        if first > last:
            return self.send(b"", kind, 416, extra=[("Content-Range", f"bytes */{len(body)}")])
        return self.send(
            body[first : last + 1], kind, 206, extra=[("Content-Range", f"bytes {first}-{last}/{len(body)}")]
        )

    def do_GET(self):
        url = urlparse(self.path)
        base = f"http://{self.headers.get('Host', f'localhost:{PORT}')}"
        if url.path.startswith("/data/"):
            return self.kit(url.path)
        if url.path == "/catalog/v2/entries":
            entries = ""
            for name in parse_qs(url.query).get("name", []):
                file = f"{name}_2026-01.zim"
                entries += f"""<entry><name>{name}</name>
  <link rel="http://opds-spec.org/acquisition/open-access" type="application/x-zim" href="{base}/zim/{file}.meta4" length="{len(content(file))}" />
</entry>"""
            feed = (
                f'<?xml version="1.0" encoding="UTF-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>\n'
            )
            return self.send(feed.encode(), "application/atom+xml")
        m = re.fullmatch(r"/zim/([\w.-]+\.zim)(\.sha256)?", url.path)
        if m and m.group(2):
            return self.send(
                f"{hashlib.sha256(content(m.group(1))).hexdigest()}  {m.group(1)}\n".encode(), "text/plain"
            )
        if m:
            return self.send(b"", "text/plain", 302, f"{base}/mirror/{m.group(1)}")
        m = re.fullmatch(r"/mirror/([\w.-]+\.zim)", url.path)
        if m:
            return self.send(content(m.group(1)), "application/octet-stream")
        m = re.fullmatch(r"/(protomaps|assets)/(.+)", unquote(url.path))
        if MAP and m and ".." not in m.group(2):
            file = MAP / m.group(2) if m.group(1) == "protomaps" else MAP / "assets" / m.group(2)
            if file.is_file():
                return self.send_file(
                    file, "application/json" if file.suffix == ".json" else "application/octet-stream"
                )
        self.send_error(404)

    do_HEAD = do_GET

    def kit(self, path: str):
        if self.headers.get("Authorization") != f"Bearer {CODE}":
            return self.send(b'{"error": "this needs the kit\'s access code"}', "application/json", 401)
        book = content("survival")
        path = unquote(path)
        if path == "/data/files":
            files = [{"path": KIT_BOOK, "bytes": len(book), "sha256": hashlib.sha256(book).hexdigest()}]
            listing = {
                "name": "Kitchen Mac",
                "books": [{"id": "ready.gov_en_all", "title": "Ready.gov", "group": "", "why": "", "files": files}],
                "map": kit_map(),
            }
            return self.send(json.dumps(listing).encode(), "application/json")
        if path == f"/data/files/{KIT_BOOK}" and BOOKS:
            return self.send_file(BOOKS / "testsurvival_en_2026-05.zim", "application/octet-stream")
        world = world_map()
        if path == f"/data/files/{KIT_MAP}" and world:
            return self.send_file(world, "application/octet-stream")
        style = path.removeprefix(f"/data/files/{KIT_ASSETS}/")
        if MAP and style != path and ".." not in style and (MAP / "assets" / style).is_file():
            return self.send_file(MAP / "assets" / style, "application/octet-stream")
        return self.send(b'{"error": "Nothing here."}', "application/json", 404)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Internet).serve_forever()
