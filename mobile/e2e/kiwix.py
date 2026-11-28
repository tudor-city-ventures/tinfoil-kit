"""A stand-in for Kiwix's catalog and downloads, for the phone app's tests in CI: every book the app asks for is
published with its SHA-256, behind a redirect to a mirror the way download.kiwix.org answers. Given a folder of the
test books tests/make_zims.py makes, each is one of those (the medical one for medical books); otherwise a small file.

python3 mobile/e2e/kiwix.py [PORT [BOOKS]], and build the app with
EXPO_PUBLIC_KIWIX_CATALOG=http://localhost:PORT/catalog/v2/entries
"""

import hashlib
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 19100
BOOKS = Path(sys.argv[2]) if len(sys.argv) > 2 else None


def content(file: str) -> bytes:
    if BOOKS:
        return (
            BOOKS / ("testmed_en_all_maxi_2026-01.zim" if "medic" in file else "testsurvival_en_2026-05.zim")
        ).read_bytes()
    return (file.encode() + b"\n") * 4000  # a few hundred KB, so the app shows some progress


class Kiwix(BaseHTTPRequestHandler):
    def send(self, body: bytes, kind: str, status=200, location=""):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        if location:
            self.send_header("Location", location)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        base = f"http://{self.headers.get('Host', f'localhost:{PORT}')}"
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
        self.send_error(404)

    do_HEAD = do_GET


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Kiwix).serve_forever()
