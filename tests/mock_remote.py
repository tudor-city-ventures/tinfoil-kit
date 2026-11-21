"""Mock of library.kiwix.org, download.kiwix.org, api.github.com and huggingface.co for testing.

State "v1" = initial release; touch remote/STATE_V2 to simulate the world 3 months later
(newer ZIM date, new llama.cpp build, re-uploaded model file).
"""
import hashlib
import json
import os
import re
import sys
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, unquote

R = Path(os.environ.get("KIT_TEST_WORK", Path(__file__).parent / "work")) / "remote"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 19000
BASE = f"http://127.0.0.1:{PORT}"


def v2():
    return (R / "STATE_V2").exists()


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def catalog() -> bytes:
    zims = ["testmed_en_all_maxi_2026-01.zim", "testsurvival_en_2026-05.zim" if v2() else "testsurvival_en_2026-02.zim"]
    entries = []
    for z in zims:
        p = R / "zim" / z
        name = z.rsplit("_", 1)[0]
        entries.append(f"""  <entry>
    <id>urn:uuid:{hashlib.md5(z.encode()).hexdigest()}</id>
    <title>{name.replace('_', ' ').title()}</title>
    <summary>Summary of {name}</summary>
    <language>eng</language>
    <name>{name}</name>
    <flavour>maxi</flavour>
    <category>test</category>
    <tags>_ftindex:yes</tags>
    <link type="text/html" href="/content/{z[:-4]}" />
    <link rel="http://opds-spec.org/acquisition/open-access" type="application/x-zim" href="{BASE}/zim/{z}.meta4" length="{p.stat().st_size}" />
  </entry>""")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom">\n'
            + "\n".join(entries) + "\n</feed>\n").encode()


def releases() -> bytes:
    tag = "b99999" if v2() else "b99990"
    asset = R / "gh" / f"llama-{tag}-bin-ubuntu-x64.tar.gz"
    data = [
        {"tag_name": "v1.0.0", "draft": False, "prerelease": False, "assets": [
            {"name": "nightly-tag.txt", "size": 7, "browser_download_url": f"{BASE}/gh/nightly-tag.txt"}]},
        {"tag_name": tag, "draft": False, "prerelease": True, "assets": [
            {"name": asset.name, "size": asset.stat().st_size, "digest": "sha256:" + sha(asset),
             "browser_download_url": f"{BASE}/gh/{asset.name}"}]},
    ]
    return json.dumps(data).encode()


HF_REPOS = {"test/Tiny-GGUF": "tiny", "test/Two-GGUF": "two"}


def hf_files(repo: str):
    d = R / "hf" / HF_REPOS[repo]
    if repo == "test/Tiny-GGUF" and v2():
        d = R / "hf" / "tiny_v2"
    return d


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_bytes(self, data: bytes, ctype="application/octet-stream", head=False, mtime=None):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        if mtime:
            from email.utils import formatdate
            self.send_header("Last-Modified", formatdate(mtime, usegmt=True))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        if not head:
            self.wfile.write(data)

    def send_file(self, p: Path, head=False):
        if not p.is_file():
            return self.send_error(404)
        data = p.read_bytes()
        rng = self.headers.get("Range")
        if rng and not head:
            m = re.match(r"bytes=(\d+)-", rng)
            start = int(m.group(1))
            if start >= len(data):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{len(data)}")
                self.end_headers()
                return
            # simulate a flaky connection: the first request for the big file drops halfway
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
            self.send_header("Content-Length", str(len(data) - start))
            self.end_headers()
            self.wfile.write(data[start:])
            return
        if p.name.endswith(".gguf") and not head and (R / "FLAKY").exists():
            (R / "FLAKY").unlink()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.write(data[: len(data) // 2])
            self.wfile.flush()
            self.close_connection = True
            return
        self.send_bytes(data, head=head, mtime=p.stat().st_mtime)

    def do_HEAD(self):
        self.route(head=True)

    def do_GET(self):
        self.route()

    def route(self, head=False):
        u = urlparse(self.path)
        path = unquote(u.path)
        if path == "/catalog/v2/entries":
            return self.send_bytes(catalog(), "application/atom+xml", head)
        if path == "/wifi-sign-in":    # what a hotel or cafe network answers every URL with until you log in
            return self.send_bytes(b'<!DOCTYPE html><html><head><meta charset="utf-8"><title>Sign in</title></head>'
                                   b'<body><p>Welcome to Hotel Wi-Fi<br>Accept the terms to continue</body></html>', "text/html", head)
        m = re.match(r"^/zim/(.+\.zim)(\.sha256)?$", path)
        if m:
            p = R / "zim" / m.group(1)
            if m.group(2):
                return self.send_bytes(f"{sha(p)}  {p.name}\n".encode(), "text/plain", head) if p.exists() else self.send_error(404)
            return self.send_file(p, head)
        m = re.match(r"^/release/([^/]+)/(.*)$", path)
        if m:
            d = R / "release" / m.group(1)
            if not m.group(2):
                names = sorted(x.name for x in d.iterdir() if v2() or "3.9" not in x.name)
                html = "<html><body>" + "".join(f'<a href="{n}">{n}</a><br>' for n in names) + "</body></html>"
                return self.send_bytes(html.encode(), "text/html", head)
            name = m.group(2)
            if name.endswith(".sha256"):
                p = d / name[:-7]
                return self.send_bytes(f"{sha(p)}  {p.name}\n".encode(), "text/plain", head) if p.exists() else self.send_error(404)
            return self.send_file(d / name, head)
        if path == "/repos/tudor-city-ventures/tinfoilkit/releases/latest":    # ./kit update: none until a test publishes one
            p = R / "kit" / "release.json"
            return self.send_bytes(p.read_bytes(), "application/json", head) if p.exists() else self.send_error(404)
        if path.startswith("/repos/tudor-city-ventures/tinfoilkit/compare/"):    # "BASE...HEAD": answered only if a test wrote one
            p = R / "kit" / "compare" / path.split("/compare/", 1)[1]
            return self.send_bytes(p.read_bytes(), "application/json", head) if p.is_file() else self.send_error(404)
        if path == "/repos/ggml-org/llama.cpp/releases":
            return self.send_bytes(releases(), "application/json", head)
        if path == "/repos/protomaps/go-pmtiles/releases":
            a = R / "gh2" / "go-pmtiles_1.31.2_Linux_x86_64.tar.gz"
            return self.send_bytes(json.dumps([{"tag_name": "v1.31.2", "draft": False, "prerelease": False, "assets": [
                {"name": a.name, "size": a.stat().st_size, "browser_download_url": f"{BASE}/gh2/{a.name}"}]}]).encode(), "application/json", head)
        if path == "/repos/komoot/photon/releases":
            a = R / "gh2" / "photon-1.3.0.jar"
            a2 = R / "gh2" / "photon-1.2.1.jar"
            older = [{"tag_name": "1.2.1", "draft": False, "prerelease": False, "assets": [
                {"name": a2.name, "size": a2.stat().st_size, "digest": "sha256:" + sha(a2), "browser_download_url": f"{BASE}/gh2/{a2.name}"}]}]
            return self.send_bytes(json.dumps(older[:0] + [
                {"tag_name": "2.0.0-beta", "draft": False, "prerelease": True, "assets": [
                    {"name": "photon-2.0.0-beta.jar", "size": 5, "browser_download_url": f"{BASE}/gh2/nope.jar"}]},
                {"tag_name": "1.3.0", "draft": False, "prerelease": False, "assets": [
                    {"name": "original-photon-1.3.0.jar", "size": 5, "browser_download_url": f"{BASE}/gh2/nope.jar"},
                    {"name": a.name, "size": a.stat().st_size, "digest": "sha256:" + sha(a), "browser_download_url": f"{BASE}/gh2/{a.name}"}]}] + older).encode(),
                "application/json", head)
        if path == "/repos/protomaps/basemaps-assets/commits/main":
            return self.send_bytes(json.dumps({"sha": (R / "gh2" / "basemaps-assets.sha").read_text().strip()}).encode(), "application/json", head)
        m = re.match(r"^/ghweb/protomaps/basemaps-assets/archive/([0-9a-f]+)\.tar\.gz$", path)
        if m:
            return self.send_file(R / "gh2" / f"basemaps-assets-{m.group(1)}.tar.gz", head)
        if path.startswith("/gh2/"):
            return self.send_file(R / "gh2" / path[5:], head)
        if path == "/adoptium/v3/assets/latest/21/hotspot":
            a = R / "adoptium" / "OpenJDK21U-jre_x64_linux_hotspot_21.0.9_10.tar.gz"
            return self.send_bytes(json.dumps([{"release_name": "jdk-21.0.9+10", "version": {"semver": "21.0.9+10"}, "binary": {
                "image_type": "jre", "package": {"name": a.name, "link": f"{BASE}/adoptium/file/{a.name}", "size": a.stat().st_size,
                                                 "checksum": sha(a)}}}]).encode(), "application/json", head)
        if path.startswith("/adoptium/file/"):
            return self.send_file(R / "adoptium" / path.split("/")[-1], head)
        if path.startswith("/maven/"):
            return self.send_file(R / "maven" / path[len("/maven/"):], head)
        if path in ("/npm/maplibre-gl", "/npm/@protomaps/basemaps"):
            import base64
            f = next((R / "npm").glob("maplibre-gl-*.tgz" if "maplibre" in path else "basemaps-*.tgz"))
            ver = f.name[:-4].rsplit("-", 1)[1]
            raw = f.read_bytes()
            doc = {"name": path[5:], "versions": {
                ver: {"dist": {"tarball": f"{BASE}/npmfile/{f.name}", "shasum": hashlib.sha1(raw).hexdigest(),
                               "integrity": "sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode()}},
                "6.19.0": {"dist": {"tarball": f"{BASE}/npmfile/nope.tgz", "integrity": "sha512-AAAA"}},
                "5.0.0-pre.1": {"dist": {"tarball": f"{BASE}/npmfile/nope.tgz"}}}}
            return self.send_bytes(json.dumps(doc).encode(), "application/json", head)
        if path.startswith("/npmfile/"):
            return self.send_file(R / "npm" / path.split("/")[-1], head)
        if path == "/protomaps/builds.json":
            return self.send_bytes(json.dumps([
                {"key": "20261101.pmtiles", "size": 130000000000, "version": "4.15.1", "uploaded": "2026-11-02"},
                {"key": "20261115.pmtiles", "size": 131000000000, "version": "4.15.2", "uploaded": "2026-11-16"},
                {"key": "20261116.pmtiles", "size": 131000000000, "version": "5.0.0", "uploaded": "2026-11-17"},
                {"key": "20261115.layerstats.parquet", "size": 10}] +
                ([{"key": "20270201.pmtiles", "size": 132000000000, "version": "4.16.0", "uploaded": "2027-02-02"}] if v2() else [])
                ).encode(), "application/json", head)
        if path.startswith("/geofabrik/"):
            return self.send_file(R / "geofabrik" / path.split("/")[-1], head)
        if path == "/photon/":
            return self.send_bytes(b"""<html><body><h1>Photon dumps</h1><table><tr><th>Region</th><th>DB dump</th><th>Countries</th></tr>
<tr><td><a href="planet/index.html">planet</a></td><td>\xe2\x9c\x93</td><td></td></tr>
<tr><td><a href="europe/index.html">europe</a></td><td>\xe2\x9c\x93</td><td>ad, at, be, de, fr</td></tr>
<tr><td><a href="north-america/index.html">north-america</a></td><td>\xe2\x9c\x93</td><td>ca, mx, us</td></tr></table></body></html>""", "text/html", head)
        if path in ("/photon/north-america/", "/photon/north-america/index.html"):
            return self.send_bytes(b"""<html><body><table><tr><th>Region</th><th>DB dump</th><th>Countries</th></tr>
<tr><td><a href="caribbean/index.html">caribbean</a></td><td></td><td>bs, cu, jm</td></tr>
<tr><td><a href="canada/index.html">canada</a></td><td>\xe2\x9c\x93</td><td>ca</td></tr>
<tr><td><a href="usa/index.html">usa</a></td><td>\xe2\x9c\x93</td><td>us</td></tr></table></body></html>""", "text/html", head)
        old_dump = (R / "PHOTON_OLD_DUMP").exists()     # only an older database version is published
        if path in ("/photon/north-america/usa/", "/photon/north-america/usa/index.html"):
            names = ["photon-db-usa-1.2-latest.tar.bz2", "photon-db-usa-master-latest.tar.bz2"] if old_dump else \
                    ["photon-db-usa-1.3-latest.tar.bz2", "photon-db-usa-1.2-latest.tar.bz2"]
            return self.send_bytes(("<html><body>" + "".join(f'<a href="{n}">{n}</a><br>' for n in names) + "</body></html>").encode(), "text/html", head)
        m = re.match(r"^/photon/north-america/usa/photon-db-usa-([0-9.]+)-latest\.tar\.bz2(\.md5)?$", path)
        if m:
            if m.group(1) not in (("1.2",) if old_dump else ("1.3", "1.2")):
                return self.send_error(404)
            f = R / "photon" / "north-america" / "usa" / "photon-db-usa-1.3-latest.tar.bz2"
            if m.group(2):
                return self.send_bytes(f"{hashlib.md5(f.read_bytes()).hexdigest()}  {path.split('/')[-1][:-4]}\n".encode(), "text/plain", head)
            return self.send_file(f, head)
        if path.startswith("/gh/"):
            return self.send_file(R / "gh" / path[4:], head)
        m = re.match(r"^/api/models/([^/]+/[^/]+)(/tree/[^/]+)?$", path)
        if m:
            repo = m.group(1)
            if repo not in HF_REPOS:
                return self.send_error(404)
            d = hf_files(repo)
            commit = hashlib.sha1(str(sorted((p.name, sha(p)) for p in d.iterdir())).encode()).hexdigest()
            if not m.group(2):
                return self.send_bytes(json.dumps({"id": repo, "sha": commit}).encode(), "application/json", head)
            tree = [{"type": "file", "path": ".gitattributes", "size": 10, "oid": "x" * 40}]
            for p in sorted(d.iterdir()):
                tree.append({"type": "file", "path": p.name, "size": p.stat().st_size, "oid": "y" * 40,
                             "lfs": {"oid": sha(p), "size": p.stat().st_size, "pointerSize": 130}})
            return self.send_bytes(json.dumps(tree).encode(), "application/json", head)
        m = re.match(r"^/([^/]+/[^/]+)/resolve/[^/]+/(.+)$", path)
        if m and m.group(1) in HF_REPOS:
            return self.send_file(hf_files(m.group(1)) / m.group(2), head)
        if path == "/files/guide.pdf":
            return self.send_file(R / "files" / "guide.pdf", head)
        self.send_error(404)


if __name__ == "__main__":
    print(f"mock remote on {BASE}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
