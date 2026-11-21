#!/usr/bin/env python3
"""Tinfoil Kit: keeps an offline AI + knowledge library on an external drive up to date.

Commands (run from the kit folder, e.g.  ./kit sync):
  plan [--json]      Show what would be downloaded or updated. Changes nothing.
                     --json prints every item's size, disabled ones too.
  sync [-y]          Download/update everything enabled in kit.json, verify every file
                     (SHA-256), then remove the old versions. Safe to interrupt and re-run.
  verify [--quick]   Re-check every file on the drive against its recorded SHA-256.
  status             What's installed, when it was last updated, free space.
  search WORDS...    Search the Kiwix catalog for more library content to add to kit.json.
  test               Start the offline servers briefly and check they actually work.

Only needs python3 (3.9+) and curl, both standard on macOS. aria2c is used if installed
(brew install aria2) for faster multi-connection downloads.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import datetime as dt
import email.utils
import fnmatch
import hashlib
import json
import math
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

USER_AGENT = "TinfoilKit/1.0 (+https://github.com/tudor-city-ventures/tinfoilkit)"
KIWIX_CATALOG = os.environ.get("KIT_KIWIX_CATALOG", "https://library.kiwix.org/catalog/v2/entries?count=-1")
KIWIX_RELEASES = os.environ.get("KIT_KIWIX_RELEASES", "https://download.kiwix.org/release/{product}/")
GITHUB_API = os.environ.get("KIT_GITHUB_API", "https://api.github.com")
HF = os.environ.get("KIT_HF", "https://huggingface.co")
ADOPTIUM_API = os.environ.get("KIT_ADOPTIUM_API", "https://api.adoptium.net")
MAVEN = os.environ.get("KIT_MAVEN", "https://repo1.maven.org/maven2")
NPM = os.environ.get("KIT_NPM", "https://registry.npmjs.org")
GITHUB_WEB = os.environ.get("KIT_GITHUB_WEB", "https://github.com")
PROTOMAPS_BUILDS = os.environ.get("KIT_PROTOMAPS_BUILDS", "https://build-metadata.protomaps.dev/builds.json")
PROTOMAPS_BUILD_BASE = os.environ.get("KIT_PROTOMAPS_BUILD_BASE", "https://build.protomaps.com")
PHOTON_DUMPS = os.environ.get("KIT_PHOTON_DUMPS", "https://download1.graphhopper.com/public/")
GB = 1_000_000_000
SECTIONS = ("runtimes", "models", "maps", "library", "extras")
MAPS_DEFAULTS: Dict[str, Any] = {
    "enabled": False,
    "label": "map region",
    "home": {"lat": 40.75, "lon": -73.99, "zoom": 10, "label": "Home"},
    "detail_bbox": [-80.6, 38.8, -66.8, 47.6],
    "detail_maxzoom": 15,
    "world_maxzoom": 7,
    "routing_osm_pbf": "https://download.geofabrik.de/north-america/us-northeast-latest.osm.pbf",
    "routing_profiles": ["car", "foot"],
    "geocoder_country": "us",
    "units": "imperial",
    "tiles_port": 8090,
    "geocoder_port": 2322,
    "routing_port": 8989,
    "routing_import_heap": "12g",
    "routing_heap": "2g",
    "geocoder_heap": "3g",
}
GH_ENCODED_VALUES = {
    "car": ["car_access", "car_average_speed", "road_access"],
    "foot": ["foot_access", "foot_priority", "foot_average_speed", "foot_road_access", "hike_rating",
             "mtb_rating", "country", "road_class"],
    "bike": ["bike_priority", "bike_access", "roundabout", "bike_average_speed", "bike_road_access",
             "foot_road_access", "mtb_rating", "hike_rating", "country", "road_class"],
}
GLYPH_FONTS = ["Noto Sans Regular", "Noto Sans Medium", "Noto Sans Italic"]
GLYPH_RANGES = ["0-255", "256-511", "8192-8447"]
SHARD_RE = re.compile(r"-\d{5}-of-\d{5}\.gguf$")
ZIM_RE = re.compile(r"^(?P<prefix>.+)_(?P<date>\d{4}-\d{2})\.zim$")
HEX64 = re.compile(r"\b([0-9a-fA-F]{64})\b")

ROOT = Path(__file__).resolve().parent.parent
LOG_FILE: Optional[Path] = None


# ----------------------------------------------------------------------------- output

def log(msg: str = "", end: str = "\n") -> None:
    print(msg, end=end, flush=True)
    if LOG_FILE:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(msg + end)
        except OSError:
            pass


def fmt_size(n: Optional[float]) -> str:
    if n is None:
        return "?"
    for unit, div in (("TB", 1e12), ("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if n >= div:
            return f"{n / div:.1f} {unit}"
    return f"{int(n)} B"


def now_iso() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


def die(msg: str, code: int = 1) -> None:
    log(f"ERROR: {msg}")
    sys.exit(code)


# ----------------------------------------------------------------------------- http (via curl)

class HttpError(Exception):
    def __init__(self, url: str, msg: str, status: Optional[int] = None):
        super().__init__(f"{msg} ({url})")
        self.url, self.status = url, status


_CURL_HELP: Optional[str] = None


def curl_supports(flag: str) -> bool:
    global _CURL_HELP
    if _CURL_HELP is None:
        try:
            _CURL_HELP = subprocess.run(["curl", "--help", "all"], capture_output=True, text=True).stdout
        except OSError:
            _CURL_HELP = ""
    return flag in _CURL_HELP


def _auth_headers(url: str) -> Dict[str, str]:
    host = urllib.parse.urlparse(url).hostname or ""
    if host.endswith("huggingface.co") and os.environ.get("HF_TOKEN"):
        return {"Authorization": f"Bearer {os.environ['HF_TOKEN']}"}
    if host == "api.github.com" or url.startswith(GITHUB_API):
        h = {"Accept": "application/vnd.github+json"}
        if os.environ.get("GITHUB_TOKEN"):
            h["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
        return h
    return {}


def http_get(url: str, timeout: int = 120, headers: Optional[Dict[str, str]] = None) -> bytes:
    cmd = ["curl", "-fsSL", "--retry", "3", "--retry-delay", "2", "--connect-timeout", "20",
           "--max-time", str(timeout), "-A", USER_AGENT]
    for k, v in {**_auth_headers(url), **(headers or {})}.items():
        cmd += ["-H", f"{k}: {v}"]
    cmd.append(url)
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        err = p.stderr.decode(errors="replace").strip()
        m = re.search(r"error: (\d{3})", err)
        raise HttpError(url, err or f"curl exit {p.returncode}", int(m.group(1)) if m else None)
    return p.stdout


def http_json(url: str, timeout: int = 60) -> Any:
    return json.loads(http_get(url, timeout).decode("utf-8"))


def http_head(url: str) -> Dict[str, str]:
    cmd = ["curl", "-fsSIL", "--connect-timeout", "20", "--max-time", "60", "-A", USER_AGENT, url]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise HttpError(url, p.stderr.strip() or "HEAD failed")
    blocks = [b for b in re.split(r"\r?\n\r?\n", p.stdout.strip()) if b.strip()]
    headers: Dict[str, str] = {}
    for line in (blocks[-1] if blocks else "").splitlines()[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    return headers


def fetch_sha256_sidecar(url: str) -> Optional[str]:
    """Kiwix publishes <file>.sha256 next to every download; .meta4 is the fallback."""
    for suffix, pattern in ((".sha256", HEX64),
                            (".meta4", re.compile(r'type="sha-256">\s*([0-9a-fA-F]{64})'))):
        try:
            m = pattern.search(http_get(url + suffix, timeout=60).decode(errors="replace"))
            if m:
                return m.group(1).lower()
        except HttpError:
            continue
    return None


# ----------------------------------------------------------------------------- data model

@dataclass
class RemoteFile:
    name: str
    url: str
    size: Optional[int] = None
    sha256: Optional[str] = None
    sha256_sidecar: bool = False  # fetch <url>.sha256 at download time (Kiwix)
    md5_sidecar: bool = False     # fetch <url>.md5 at download time (Geofabrik, Photon dumps)
    checks: Dict[str, str] = field(default_factory=dict)  # other published digests: {"sha1": hex, "sha512": hex}
    estimate: Optional[int] = None  # rough size when the real one is only known after downloading (map tiles)


@dataclass
class Item:
    section: str
    id: str
    cfg: Dict[str, Any]
    kind: str = "files"            # "files" (kept as-is), "archive" (extracted) or "custom" (own installer)
    dest: str = ""
    version: str = ""
    files: List[RemoteFile] = field(default_factory=list)
    error: Optional[str] = None
    status: str = ""               # ok | new | update | error
    need: List[RemoteFile] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.section}/{self.id}"

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get("enabled", True))

    @property
    def priority(self) -> int:
        return 0 if self.section == "runtimes" else int(self.cfg.get("priority", 2))

    @property
    def note(self) -> str:
        return self.cfg.get("note", "")

    def partial(self, root: Path, f: RemoteFile) -> Path:
        """Where f is downloaded to; an interrupted download resumes from here."""
        if self.kind == "archive" or self.cfg.get("type") == "photon_db":
            return root / ".kit" / "downloads" / (f.name + ".partial")
        return root / self.dest / (f.name + ".partial")

    def need_bytes(self, root: Path) -> int:
        total = 0
        for f in self.need:
            if f.size:
                partial = self.partial(root, f)
                done = partial.stat().st_size if partial.exists() else 0
                total += max(0, f.size - done)
            elif f.estimate:
                total += f.estimate
        return total


# ----------------------------------------------------------------------------- config & state

def load_config(root: Path) -> Dict[str, Any]:
    path = root / "kit.json"
    if not path.exists():
        die(f"{path} not found. Run this from the Tinfoil Kit folder.")
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        die(f"kit.json has a syntax error on line {e.lineno}, column {e.colno}: {e.msg}")
    cfg.setdefault("settings", {})
    for s in SECTIONS:
        cfg.setdefault(s, [])
    return cfg


def maps_settings(cfg: Dict[str, Any]) -> Dict[str, Any]:
    m = {**MAPS_DEFAULTS, **(cfg.get("maps") or {})}
    m["home"] = {**MAPS_DEFAULTS["home"], **(m.get("home") or {})}
    return m


def maps_items(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    m = maps_settings(cfg)
    if not m["enabled"]:
        return []
    return [
        {"id": "maplibre-gl", "type": "npm", "package": "maplibre-gl", "version_prefix": "5.", "priority": 1,
         "note": "Map display engine (MapLibre)"},
        {"id": "protomaps-basemaps", "type": "npm", "package": "@protomaps/basemaps", "version_prefix": "5.",
         "priority": 1, "note": "Map style (Protomaps)"},
        {"id": "basemaps-assets", "type": "github_archive", "repo": "protomaps/basemaps-assets", "branch": "main",
         "priority": 1, "note": "Map fonts and icons"},
        {"id": "basemap", "type": "protomaps", "priority": 2,
         "note": f"Offline map: {m['label']} in street detail, plus a world overview"},
        {"id": "routing", "type": "routing", "url": m["routing_osm_pbf"], "priority": 2,
         "note": "Road network for directions (GraphHopper)"},
        {"id": "geocoder", "type": "photon_db", "country": m["geocoder_country"], "priority": 3,
         "note": "Address and place search database (Photon)"},
    ]


def items_from_config(cfg: Dict[str, Any]) -> List[Item]:
    out = []
    maps_on = maps_settings(cfg)["enabled"]
    for section in SECTIONS:
        entries = maps_items(cfg) if section == "maps" else cfg.get(section, [])
        for entry in entries:
            if entry.get("requires") == "maps" and not maps_on:
                entry = {**entry, "enabled": False}
            if section == "library":
                entry = {"type": "zim", **entry}
                ident = entry.get("zim")
            else:
                ident = entry.get("id")
            if not ident:
                log(f"WARNING: an entry in '{section}' has no id/zim, skipped: {entry}")
                continue
            out.append(Item(section=section, id=ident, cfg=entry))
    return out


def state_path(root: Path) -> Path:
    return root / ".kit" / "state.json"


def load_state(root: Path) -> Dict[str, Any]:
    p = state_path(root)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            backup = p.with_suffix(".corrupt.json")
            shutil.copy2(p, backup)
            log(f"WARNING: state file was unreadable; saved a copy to {backup} and starting fresh "
                "(existing files will be re-verified, not re-downloaded).")
    return {"version": 1, "items": {}}


def save_state(root: Path, state: Dict[str, Any]) -> None:
    p = state_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)


# ----------------------------------------------------------------------------- resolvers

class Resolver:
    """Looks up the latest available version of each item (network, read-only)."""

    def __init__(self, root: Path, cfg: Dict[str, Any]):
        self.root, self.cfg = root, cfg
        self._catalog: Optional[Dict[str, Dict[str, Any]]] = None
        self._catalog_error: Optional[Exception] = None
        self._releases: Dict[str, Any] = {}
        self._listings: Dict[str, str] = {}
        self.resolved: Dict[str, Item] = {}

    # --- kiwix catalog
    def catalog(self, max_age_hours: float = 12) -> Dict[str, Dict[str, Any]]:
        if self._catalog is None:
            if self._catalog_error:      # every book asks; fetch it once
                raise self._catalog_error
            cache = self.root / ".kit" / "cache" / "kiwix-catalog.xml"
            cache.parent.mkdir(parents=True, exist_ok=True)
            if cache.exists() and time.time() - cache.stat().st_mtime < max_age_hours * 3600:
                try:
                    self._catalog = parse_kiwix_catalog(cache.read_bytes()) or None
                except ET.ParseError:
                    pass
            if self._catalog is None:
                log("Fetching the Kiwix catalog (all available libraries)...")
                try:
                    data = http_get(KIWIX_CATALOG, timeout=600)
                    # parse before caching: a Wi-Fi sign-in page answers every URL with HTML
                    self._catalog = parse_kiwix_catalog(data) or None
                except HttpError as e:
                    self._catalog_error = ValueError(f"couldn't reach the Kiwix catalog ({e}). Is this Mac online?")
                    raise self._catalog_error from e
                except ET.ParseError as e:
                    why = ("got a web page instead; does this Wi-Fi want you to sign in?"
                           if b"<html" in data[:4000].lower() else f"it's garbled: {e}")
                    self._catalog_error = ValueError(f"couldn't read the Kiwix catalog ({why})")
                    raise self._catalog_error from e
                if self._catalog is None:
                    self._catalog_error = ValueError("the Kiwix catalog came back empty; try again later")
                    raise self._catalog_error
                tmp = cache.with_suffix(".tmp")
                tmp.write_bytes(data)
                os.replace(tmp, cache)
        return self._catalog

    def resolve(self, item: Item) -> None:
        t = item.cfg.get("type")
        handlers = {"zim": self._zim, "hf": self._hf, "github": self._github, "kiwix_release": self._kiwix_release,
                    "url": self._url, "adoptium": self._adoptium, "maven": self._maven, "npm": self._npm,
                    "github_archive": self._github_archive, "protomaps": self._protomaps,
                    "routing": self._routing, "photon_db": self._photon_db}
        try:
            if t not in handlers:
                raise ValueError(f"unknown type '{t}'")
            handlers[t](item)
        except (HttpError, ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError, ET.ParseError) as e:
            item.error = str(e)
        self.resolved[item.id] = item

    def _zim(self, item: Item) -> None:
        entry = self.catalog().get(item.id)
        if not entry:
            raise ValueError(f"not found in the Kiwix catalog (try: ./kit search {item.id.split('_')[0]})")
        item.dest = "library"
        item.version = entry["date"]
        item.files = [RemoteFile(name=entry["file"], url=entry["url"], size=entry["size"],
                                 sha256_sidecar=True)]

    def _hf(self, item: Item) -> None:
        repo = item.cfg["repo"]
        try:
            info = http_json(f"{HF}/api/models/{repo}")
        except HttpError as e:
            if e.status in (401, 403):
                raise ValueError(f"{repo} is gated or private: accept its license on huggingface.co "
                                 "and set HF_TOKEN") from e
            if e.status == 404:
                raise ValueError(f"Hugging Face repo {repo} not found (renamed or removed?)") from e
            raise
        sha = info.get("sha") or "main"
        tree = hf_tree(repo, sha)
        chosen = select_hf_files(tree, item.cfg.get("files", []), repo)
        item.dest = f"models/{item.id}"
        item.version = sha[:12]
        item.files = []
        for f in chosen:
            lfs = f.get("lfs") or {}
            item.files.append(RemoteFile(
                name=f["path"].split("/")[-1],
                url=f"{HF}/{repo}/resolve/{sha}/{urllib.parse.quote(f['path'])}",
                size=int(lfs.get("size") or f.get("size") or 0) or None,
                sha256=(lfs.get("oid") or "").lower() or None))

    def pin_github(self, item: Item, prefix: str) -> bool:
        """Re-resolve a GitHub runtime to the newest release whose version starts with prefix."""
        old = dict(item.cfg)
        item.cfg = {**item.cfg, "version_prefix": prefix}
        try:
            self._github(item)
            return True
        except (ValueError, HttpError):
            item.cfg = old
            return False

    def _github(self, item: Item) -> None:
        repo, pattern = item.cfg["repo"], item.cfg["asset"]
        if repo not in self._releases:
            self._releases[repo] = http_json(f"{GITHUB_API}/repos/{repo}/releases?per_page=30")
        channel = self.cfg["settings"].get("llama_cpp_channel", "nightly")
        candidates = [r for r in self._releases[repo] if not r.get("draft")]
        if channel == "stable":
            stable = [r for r in candidates if not r.get("prerelease")]
            candidates = stable + [r for r in candidates if r.get("prerelease")]
        prefix = str(item.cfg.get("version_prefix", ""))
        for rel in candidates:
            if prefix and not rel["tag_name"].lstrip("v").startswith(prefix):
                continue
            for a in rel.get("assets", []):
                if fnmatch.fnmatch(a["name"], pattern):
                    digest = a.get("digest") or ""
                    is_archive = a["name"].endswith((".tar.gz", ".tgz", ".zip"))
                    item.kind = "archive" if is_archive else "files"
                    item.dest, item.version = f"bin/{item.id}", rel["tag_name"]
                    item.files = [RemoteFile(name=a["name"], url=a["browser_download_url"], size=a.get("size"),
                                             sha256=digest.split(":", 1)[1] if digest.startswith("sha256:") else None)]
                    return
        raise ValueError(f"no release of {repo} has an asset matching '{pattern}'")

    def _kiwix_release(self, item: Item) -> None:
        product, pattern = item.cfg["product"], item.cfg["pattern"]
        base = KIWIX_RELEASES.format(product=product)
        if base not in self._listings:
            self._listings[base] = http_get(base).decode(errors="replace")
        rx = re.compile("^" + re.escape(pattern).replace(re.escape("{version}"), r"(\d+(?:\.\d+)*(?:-\d+)?)") + "$")
        found = []
        for href in set(re.findall(r'href="([^"?#]+)"', self._listings[base])):
            name = urllib.parse.unquote(href.split("/")[-1])
            m = rx.match(name)
            if m:
                found.append((tuple(int(x) for x in re.split(r"[.-]", m.group(1))), m.group(1), name))
        if not found:
            raise ValueError(f"no file matching '{pattern}' in {base}")
        _, version, name = max(found)
        url = base + name
        size = None
        try:
            size = int(http_head(url).get("content-length", "0")) or None
        except (HttpError, ValueError):
            pass
        is_archive = name.endswith((".tar.gz", ".tgz", ".zip"))
        item.kind = "archive" if is_archive else "files"
        item.dest = f"bin/{item.id}" if is_archive else "installers"
        item.version = version
        item.files = [RemoteFile(name=name, url=url, size=size, sha256_sidecar=True)]

    def _url(self, item: Item) -> None:
        url = item.cfg["url"]
        name = item.cfg.get("filename") or urllib.parse.urlparse(url).path.split("/")[-1]
        h = http_head(url)
        size = int(h["content-length"]) if h.get("content-length", "").isdigit() else None
        item.dest = item.cfg.get("dest", "installers")
        item.version = h.get("etag") or h.get("last-modified") or (str(size) if size else "unknown")
        item.files = [RemoteFile(name=name, url=url, size=size, sha256=item.cfg.get("sha256"))]

    # --- maps: runtimes, viewer assets and data
    def _adoptium(self, item: Item) -> None:
        c = item.cfg
        url = (f"{ADOPTIUM_API}/v3/assets/latest/{c.get('feature_version', 21)}/hotspot?"
               f"architecture={c.get('arch', 'aarch64')}&image_type={c.get('image_type', 'jre')}"
               f"&os={c.get('os', 'mac')}&vendor=eclipse")
        data = http_json(url)
        if not data:
            raise ValueError("no Java runtime published for this platform")
        rel, pkg = data[0], data[0]["binary"]["package"]
        item.kind, item.dest = "archive", f"bin/{item.id}"
        item.version = rel.get("release_name") or rel["version"]["semver"]
        item.files = [RemoteFile(name=pkg["name"], url=pkg["link"], size=pkg.get("size"), sha256=pkg.get("checksum"))]

    def _maven(self, item: Item) -> None:
        c = item.cfg
        base = f"{MAVEN}/{c['group'].replace('.', '/')}/{c['artifact']}/"
        meta = http_get(base + "maven-metadata.xml").decode(errors="replace")
        prefix = str(c.get("version_prefix", ""))
        versions = [v for v in re.findall(r"<version>([^<]+)</version>", meta)
                    if v.startswith(prefix) and re.fullmatch(r"\d+(\.\d+)*", v)]
        if not versions:
            raise ValueError(f"no release of {c['artifact']} matching '{prefix}*'")
        v = max(versions, key=version_key)
        jar = f"{c['artifact']}-{v}.jar"
        url = f"{base}{v}/{jar}"
        checks = {}
        try:
            m = re.search(r"\b[0-9a-f]{40}\b", http_get(url + ".sha1").decode(errors="replace"))
            if m:
                checks["sha1"] = m.group(0)
        except HttpError:
            pass
        size = None
        try:
            size = int(http_head(url).get("content-length", "0")) or None
        except (HttpError, ValueError):
            pass
        item.kind, item.dest, item.version = "files", f"bin/{item.id}", v
        item.files = [RemoteFile(name=jar, url=url, size=size, checks=checks)]

    def _npm(self, item: Item) -> None:
        pkg, prefix = item.cfg["package"], str(item.cfg.get("version_prefix", ""))
        doc = http_json(f"{NPM}/{pkg}", timeout=180)
        versions = [v for v in doc.get("versions", {}) if v.startswith(prefix) and re.fullmatch(r"\d+\.\d+\.\d+", v)]
        if not versions:
            raise ValueError(f"no version of {pkg} matching '{prefix}*'")
        v = max(versions, key=version_key)
        dist = doc["versions"][v]["dist"]
        checks = {}
        integrity = dist.get("integrity", "")
        if integrity.startswith("sha512-"):
            checks["sha512"] = base64.b64decode(integrity[7:]).hex()
        elif dist.get("shasum"):
            checks["sha1"] = dist["shasum"]
        size = None
        try:
            size = int(http_head(dist["tarball"]).get("content-length", "0")) or None
        except (HttpError, ValueError):
            pass
        item.kind, item.dest, item.version = "archive", f"maps/viewer/{item.id}", v
        item.files = [RemoteFile(name=f"{item.id}-{v}.tgz", url=dist["tarball"], size=size, checks=checks)]

    def _github_archive(self, item: Item) -> None:
        repo, branch = item.cfg["repo"], item.cfg.get("branch", "main")
        sha = http_json(f"{GITHUB_API}/repos/{repo}/commits/{branch}")["sha"]
        item.kind, item.dest, item.version = "archive", f"maps/viewer/{item.id}", sha[:12]
        item.files = [RemoteFile(name=f"{item.id}-{sha[:12]}.tar.gz", url=f"{GITHUB_WEB}/{repo}/archive/{sha}.tar.gz")]

    def _protomaps(self, item: Item) -> None:
        builds = [b for b in http_json(PROTOMAPS_BUILDS) if str(b.get("key", "")).endswith(".pmtiles")]
        major = str(item.cfg.get("tiles_major", "4")) + "."
        usable = [b for b in builds if str(b.get("version", major)).startswith(major)] or builds
        if not usable:
            raise ValueError("no Protomaps map build listed")
        latest = max(usable, key=lambda b: b["key"])
        m = maps_settings(self.cfg)
        w, s, e, n = (float(x) for x in m["detail_bbox"])
        sq_deg = abs(e - w) * abs(n - s) * math.cos(math.radians((n + s) / 2))
        # rough: ~1 GB world overview + ~40 MB per square degree of street detail at zoom 15
        est = int(GB + sq_deg * 40e6 * 0.4 ** max(0, 15 - int(m["detail_maxzoom"])))
        item.kind, item.dest = "custom", "maps/tiles"
        item.version = latest["key"].replace(".pmtiles", "")
        item.files = [RemoteFile(name="basemap.pmtiles", url=f"{PROTOMAPS_BUILD_BASE}/{latest['key']}", estimate=est)]

    def _routing(self, item: Item) -> None:
        url = item.cfg["url"]
        h = http_head(url)
        size = int(h["content-length"]) if h.get("content-length", "").isdigit() else None
        gh = self.resolved.get("graphhopper")
        item.kind, item.dest = "custom", "maps/routing"
        item.version = http_day(h) or str(size)
        item.extra["gh_version"] = gh.version if gh is not None and not gh.error else ""
        item.files = [RemoteFile(name="region.osm.pbf", url=url, size=size, md5_sidecar=True)]

    def _photon_db(self, item: Item) -> None:
        cc = str(item.cfg.get("country", "us")).lower()
        base = PHOTON_DUMPS.rstrip("/") + "/"
        rows = photon_regions(http_get(base).decode(errors="replace"))
        top = [r for r in rows if cc in r["codes"]]
        if not top:
            raise ValueError(f"no Photon download covers country code '{cc}'")
        row = top[0]
        path, has_db = [row["slug"]], row["db"]
        if row["codes"] != [cc]:     # a continent: look for the country inside it
            sub = photon_regions(http_get(base + row["slug"] + "/").decode(errors="replace"))
            inner = [r for r in sub if cc in r["codes"]]
            if inner and inner[0]["db"]:
                path, has_db = [row["slug"], inner[0]["slug"]], True
        if not has_db:
            raise ValueError(f"no ready-made Photon database for '{cc}' (only a JSON dump); see the Photon docs")
        photon = self.resolved.get("photon")
        folder = base + "/".join(path) + "/"
        wanted = []
        if photon is not None and photon.version and not photon.error:
            wanted.append(".".join(photon.version.lstrip("v").split(".")[:2]))
        try:   # versions the folder actually offers, newest first
            listing = http_get(folder).decode(errors="replace")
            found = set(re.findall(r"photon-db-" + re.escape(path[-1]) + r"-(\d+\.\d+)-latest\.tar\.bz2", listing))
            wanted += [v for v in sorted(found, key=version_key, reverse=True) if v not in wanted]
        except HttpError:
            pass
        wanted += [v for v in ("1.0", "0.7") if v not in wanted]
        for ver in wanted:
            url = f"{folder}photon-db-{path[-1]}-{ver}-latest.tar.bz2"
            try:
                h = http_head(url)
            except HttpError:
                continue
            size = int(h["content-length"]) if h.get("content-length", "").isdigit() else None
            item.kind, item.dest = "custom", "maps/geocoder"
            item.version = f"{ver}/{http_day(h) or size}"
            item.extra["db_version"] = ver
            item.files = [RemoteFile(name=url.rsplit("/", 1)[-1], url=url, size=size, md5_sidecar=True)]
            return
        raise ValueError(f"couldn't find a Photon database file in {folder} for version(s) {', '.join(wanted)}")


def http_day(h: Dict[str, str]) -> str:
    """The date a remote file was last changed (from HTTP headers), for use as its version."""
    lm = h.get("last-modified")
    if lm:
        try:
            return email.utils.parsedate_to_datetime(lm).date().isoformat()
        except (TypeError, ValueError):
            return lm
    return h.get("etag") or ""


def version_key(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v))


def photon_regions(html: str) -> List[Dict[str, Any]]:
    """Rows of the region table on Photon's download pages: region, has a DB dump, ISO country codes."""
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S | re.I):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, flags=re.S | re.I)
        if len(cells) < 3:
            continue
        link = re.search(r'href="([^"]+)"', cells[0])
        text = re.sub(r"<[^>]+>", "", cells[0]).strip()
        slug = (link.group(1).replace("index.html", "").strip("/").split("/")[-1] if link else "") or text
        slug = slug.lower().replace(" ", "-")
        if not slug or slug == "region":
            continue
        codes = [c.strip().lower() for c in re.sub(r"<[^>]+>", "", cells[2]).split(",") if c.strip()]
        rows.append({"slug": slug, "db": "\u2713" in cells[1] or "&#10003;" in cells[1], "codes": codes})
    return rows


def select_hf_files(tree: List[Dict[str, Any]], patterns: List[str], repo: str) -> List[Dict[str, Any]]:
    """Pick the files matching each pattern; each must match exactly one file (or one split model)."""
    chosen: List[Dict[str, Any]] = []
    files = [f for f in tree if f.get("type") == "file"]
    for pattern in patterns:
        if "/" in pattern:
            hits = [f for f in files if fnmatch.fnmatch(f["path"], pattern)]
        else:   # top-level files first; look in subfolders (e.g. split models) only if nothing matches
            hits = ([f for f in files if "/" not in f["path"] and fnmatch.fnmatch(f["path"], pattern)]
                    or [f for f in files if fnmatch.fnmatch(f["path"].split("/")[-1], pattern)])
        if not hits:
            ggufs = ", ".join(sorted(f["path"] for f in files if f["path"].endswith(".gguf")))
            raise ValueError(f"pattern '{pattern}' matched no file in {repo}. Available: {ggufs}")
        if len(hits) > 1 and not all(SHARD_RE.search(h["path"]) for h in hits):
            raise ValueError(f"pattern '{pattern}' is ambiguous in {repo}: " + ", ".join(h["path"] for h in hits))
        chosen += hits
    return chosen


def hf_tree(repo: str, rev: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    url: Optional[str] = f"{HF}/api/models/{repo}/tree/{rev}?recursive=True&expand=False"
    while url:
        with tempfile.NamedTemporaryFile(delete=False) as hf:
            hdr_path = hf.name
        try:
            cmd = ["curl", "-fsSL", "--retry", "3", "--connect-timeout", "20", "--max-time", "120",
                   "-A", USER_AGENT, "-D", hdr_path]
            for k, v in _auth_headers(url).items():
                cmd += ["-H", f"{k}: {v}"]
            p = subprocess.run(cmd + [url], capture_output=True)
            if p.returncode != 0:
                raise HttpError(url, p.stderr.decode(errors="replace").strip())
            out += json.loads(p.stdout.decode("utf-8"))
            m = re.search(r'<([^>]+)>;\s*rel="next"', Path(hdr_path).read_text(errors="replace"))
            url = m.group(1) if m else None
        finally:
            os.unlink(hdr_path)
    return out


def parse_kiwix_catalog(data: bytes) -> Dict[str, Dict[str, Any]]:
    """Map 'file prefix' (e.g. wikipedia_en_all_maxi) -> newest entry."""
    best: Dict[str, Dict[str, Any]] = {}
    root = ET.fromstring(data)
    for entry in root:
        if not entry.tag.endswith("entry"):
            continue
        info: Dict[str, Any] = {}
        for child in entry:
            tag = child.tag.split("}")[-1]
            if tag == "link" and child.get("type") == "application/x-zim":
                info["url"] = (child.get("href") or "").split(".meta4")[0]
                try:
                    info["size"] = int(child.get("length") or 0) or None
                except ValueError:
                    info["size"] = None
            elif tag in ("title", "summary", "language", "category", "name", "flavour"):
                info[tag] = (child.text or "").strip()
        url = info.get("url")
        if not url:
            continue
        fname = urllib.parse.unquote(url.rstrip("/").split("/")[-1])
        m = ZIM_RE.match(fname)
        if not m:
            continue
        info.update(file=fname, prefix=m.group("prefix"), date=m.group("date"))
        cur = best.get(info["prefix"])
        if cur is None or info["date"] > cur["date"]:
            best[info["prefix"]] = info
    return best


# ----------------------------------------------------------------------------- planning

def evaluate(item: Item, state: Dict[str, Any], root: Path) -> None:
    if item.error:
        item.status = "error"
        return
    st = state["items"].get(item.key)
    if item.kind == "custom":
        d = root / item.dest
        t = item.cfg.get("type")
        if t == "routing":
            ok = (st is not None and st.get("version") == item.version and (d / "graph-cache" / "properties").exists()
                  and (not item.extra.get("gh_version") or st.get("gh_version") == item.extra["gh_version"]))
        elif t == "photon_db":
            ok = st is not None and st.get("version") == item.version and (d / "photon_data").is_dir()
        else:
            ok = st is not None and st.get("version") == item.version and all((d / f.name).exists() for f in item.files)
        item.need = [] if ok else list(item.files)
        item.status = "ok" if ok else ("update" if st else "new")
        return
    if item.kind == "archive":
        cur = (st or {}).get("current")
        target = root / item.dest / safe_name(cur)
        binary = item.cfg.get("binary")
        ok = (cur == item.version and target.is_dir() and any(target.iterdir())
              and (not binary or find_binary(target, binary) is not None))
        item.need = [] if ok else list(item.files)
    else:
        files_state = (st or {}).get("files", {})
        item.need = []
        if item.cfg.get("type") == "url" and st and st.get("version") != item.version:
            files_state = {}   # plain URL with no checksum: a changed ETag/date means a new file
        for f in item.files:
            fs = files_state.get(f.name)
            path = root / item.dest / f.name
            same_hash = fs is not None and (f.sha256 is None or fs.get("sha256") == f.sha256)
            same_size = path.exists() and (f.size is None or path.stat().st_size == f.size)
            if not (same_hash and same_size):
                item.need.append(f)
    item.status = "ok" if not item.need else ("update" if st else "new")


def safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s or "unknown")


def find_binary(base: Path, name: Optional[str]) -> Optional[Path]:
    if not name or not base.exists():
        return None
    for p in sorted(base.rglob(name)):
        if p.is_file():
            return p
    return None


def build_plan(root: Path, cfg: Dict[str, Any], state: Dict[str, Any], only: List[str]) -> List[Item]:
    items = items_from_config(cfg)
    if only:
        items = [i for i in items if any(o.lower() in i.key.lower() for o in only)]
    resolver = Resolver(root, cfg)
    active = [i for i in items if i.enabled]
    log(f"Checking {len(active)} items for updates...")
    for n, item in enumerate(active, 1):
        if sys.stdout.isatty():
            print(f"  [{n}/{len(active)}] {item.key}".ljust(78)[:78], end="\r", flush=True)
        resolver.resolve(item)
        evaluate(item, state, root)
    # Photon only opens address databases made for its own version: use the release that matches the database
    geo = next((i for i in active if i.cfg.get("type") == "photon_db" and not i.error), None)
    photon = resolver.resolved.get("photon")
    want = geo.extra.get("db_version") if geo else None
    if want and photon is not None and not photon.error and not photon.version.lstrip("v").startswith(want + "."):
        if resolver.pin_github(photon, want + "."):
            evaluate(photon, state, root)
        else:
            log(f"WARNING: no Photon release matches the address database version {want}; address search may not start")
    if sys.stdout.isatty():
        print(" " * 78, end="\r", flush=True)
    return items


def offline(items: List[Item]) -> bool:
    """Every lookup failed: no internet, or a Wi-Fi sign-in page answering instead."""
    active = [i for i in items if i.enabled]
    return len(active) > 1 and all(i.status == "error" for i in active)


def print_plan(root: Path, items: List[Item], state: Dict[str, Any], cfg: Dict[str, Any]) -> int:
    free = shutil.disk_usage(root).free
    total = 0
    labels = {"ok": "ok      ", "new": "NEW     ", "update": "UPDATE  ", "error": "ERROR   "}
    for section in SECTIONS:
        group = [i for i in items if i.section == section and i.enabled]
        if not group:
            continue
        log(f"\n[{section}]")
        for i in sorted(group, key=lambda x: (x.priority, x.id.lower())):
            need = i.need_bytes(root)
            total += need
            if i.status == "error":
                detail = i.error or ""
            elif i.status == "ok":
                detail = f"{i.version}"
            else:
                old = (state["items"].get(i.key) or {}).get("version")
                arrow = f"{old} -> {i.version}" if old and old != i.version else i.version
                size = fmt_size(need)
                if any(not f.size for f in i.need):     # some sizes are only known after downloading
                    size = "~" + size if need else "?"
                detail = f"{size:>9}   {arrow}"
            log(f"  {labels.get(i.status, i.status)}{i.id[:44]:<46}{detail}")
    disabled = [i for i in items if not i.enabled]
    if disabled:
        log(f"\n  ({len(disabled)} disabled in kit.json: {', '.join(i.id for i in disabled)})")
    if offline(items):
        log("\nNothing could be looked up. Check that this Mac is online (on hotel or cafe Wi-Fi, "
            "open any web page and sign in first), then try again.")
        return 0
    keep = float(cfg["settings"].get("keep_free_gb", 25)) * GB
    log(f"\nTo download: {fmt_size(total)}   Free on drive: {fmt_size(free)}   "
        f"Free afterwards: ~{fmt_size(max(0, free - total))} (before old versions are removed)")
    if free - total < keep:
        log(f"WARNING: that leaves less than keep_free_gb ({fmt_size(keep)}). Items that don't fit "
            "will be skipped; disable some in kit.json or use a bigger drive.")
    return total


# ----------------------------------------------------------------------------- downloading

def download(url: str, partial: Path, size: Optional[int], downloader: str) -> None:
    partial.parent.mkdir(parents=True, exist_ok=True)
    if size and partial.exists() and partial.stat().st_size > size:
        partial.unlink()
    if size and partial.exists() and partial.stat().st_size == size:
        return
    use_aria = downloader == "aria2c" or (downloader == "auto" and shutil.which("aria2c"))
    for attempt in range(1, 6):
        before = partial.stat().st_size if partial.exists() else 0
        status = ""
        if use_aria:
            cmd = ["aria2c", "-c", "-x", "8", "-s", "8", "-k", "8M", "--file-allocation=none",
                   "--auto-file-renaming=false", "--allow-overwrite=true", "--summary-interval=0",
                   "--console-log-level=warn", "--max-tries=10", "--retry-wait=5",
                   f"--user-agent={USER_AGENT}", "-d", str(partial.parent), "-o", partial.name]
            for k, v in _auth_headers(url).items():
                cmd.append(f"--header={k}: {v}")
            rc = subprocess.run(cmd + [url]).returncode
        else:
            cmd = ["curl", "-L", "--fail", "--retry", "10", "--retry-delay", "5", "--connect-timeout", "30",
                   "-A", USER_AGENT, "-C", "-", "-o", str(partial), "-w", "%{http_code}"]
            if curl_supports("--retry-all-errors"):
                cmd.append("--retry-all-errors")
            for k, v in _auth_headers(url).items():
                cmd += ["-H", f"{k}: {v}"]
            p = subprocess.run(cmd + [url], stdout=subprocess.PIPE, text=True)   # progress still shows (stderr)
            rc, status = p.returncode, p.stdout.strip()[-3:]
        got = partial.stat().st_size if partial.exists() else 0
        if rc == 0 and (not size or got == size):
            return
        if (use_aria and rc == 9) or (not use_aria and rc == 23):    # retrying won't help
            try:
                free = f" ({fmt_size(shutil.disk_usage(partial.parent).free)} free)"
            except OSError:
                free = ""
            raise RuntimeError(f"couldn't write {partial.name} to the drive{free}. Is it full, or was it unplugged?")
        if not use_aria and (rc == 33 or status == "416"):   # can't resume this partial file: start over
            partial.unlink(missing_ok=True)
        log(f"    download interrupted (exit {rc}, {fmt_size(got)} of {fmt_size(size)}); "
            f"retrying ({attempt}/5)...")
        time.sleep(10 if got > before else 30)
    raise RuntimeError(f"download failed after 5 attempts: {url}")


def hash_file(path: Path, algos: List[str], label: str = "") -> Dict[str, str]:
    """Compute several digests in one pass over the file."""
    hs = {a: hashlib.new(a) for a in set(algos) | {"sha256"}}
    total = path.stat().st_size
    done, last = 0, time.time()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(8 * 1024 * 1024)
            if not chunk:
                break
            for h in hs.values():
                h.update(chunk)
            done += len(chunk)
            if total > 2 * GB and time.time() - last > 3 and sys.stdout.isatty():
                print(f"    verifying {label or path.name}: {done * 100 // total}%", end="\r", flush=True)
                last = time.time()
    if total > 2 * GB and sys.stdout.isatty():
        print(" " * 70, end="\r")
    return {a: h.hexdigest() for a, h in hs.items()}


def sha256_file(path: Path, label: str = "") -> str:
    return hash_file(path, ["sha256"], label)["sha256"]


def expected_digests(f: RemoteFile) -> Dict[str, str]:
    """Every published checksum we can find for this file (may be empty)."""
    exp = {k: v.lower() for k, v in f.checks.items() if v}
    if f.sha256:
        exp["sha256"] = f.sha256.lower()
    elif f.sha256_sidecar:
        got = fetch_sha256_sidecar(f.url)
        if got:
            exp["sha256"] = got
    if f.md5_sidecar and "md5" not in exp:
        try:
            m = re.search(r"\b([0-9a-fA-F]{32})\b", http_get(f.url + ".md5", timeout=60).decode(errors="replace"))
            if m:
                exp["md5"] = m.group(1).lower()
        except HttpError:
            pass
    return exp


def verify_download(path: Path, f: RemoteFile, expected: Dict[str, str]) -> str:
    """Check a downloaded file against its published checksums; return its SHA-256."""
    got = hash_file(path, list(expected), f.name)
    for algo, want in expected.items():
        if got[algo] != want:
            path.unlink(missing_ok=True)
            raise RuntimeError(f"{f.name} failed its {algo} checksum (corrupt download); deleted it, run sync again")
    return got["sha256"]


def ensure_space(root: Path, need: int, cfg: Dict[str, Any]) -> bool:
    keep = float(cfg["settings"].get("keep_free_gb", 25)) * GB
    return shutil.disk_usage(root).free - need >= keep


def fetch(root: Path, state: Dict[str, Any], item: Item, f: RemoteFile, cfg: Dict[str, Any], force: bool,
          room: int = 1, label: str = "") -> Path:
    """Download f into its partial file and return that path. An interrupted download resumes,
    unless it was of an older version under the same name. room: how many times f.size must fit."""
    partial = item.partial(root, f)
    rel = partial.relative_to(root).as_posix()
    tag = f.sha256 or f"{item.version}|{f.size or ''}"
    partials = state.setdefault("partials", {})
    if partial.exists() and (partials.get(rel, {}).get("tag", tag) != tag
                             or (f.size and partial.stat().st_size > f.size)):
        log(f"    discarding an unfinished download of a different version of {f.name}")
        partial.unlink()
    have = partial.stat().st_size if partial.exists() else 0
    need = max(0, (f.size or 0) * room - have)
    if not force and not ensure_space(root, need, cfg):
        raise RuntimeError(f"not enough free space for {label or f.name} (needs about {fmt_size(need)} more); "
                           "free up space or lower keep_free_gb in kit.json")
    partials[rel] = {"item": item.key, "tag": tag}
    save_state(root, state)
    log(f"    downloading {label or f.name} ({fmt_size(f.size)})" + (f", resuming at {fmt_size(have)}" if have else ""))
    download(f.url, partial, f.size, cfg["settings"].get("downloader", "auto"))
    return partial


def forget_partial(root: Path, state: Dict[str, Any], partial: Path) -> None:
    state.get("partials", {}).pop(partial.relative_to(root).as_posix(), None)


def sweep_partials(root: Path, state: Dict[str, Any], items: List[Item]) -> None:
    """Delete unfinished downloads that a newer version has made useless (they can be 100 GB).
    Kept: the ones this sync resumes, and those of items switched off or not found this time."""
    keep = {i.partial(root, f).relative_to(root).as_posix() for i in items if i.enabled and not i.error for f in i.need}
    current = {i.key for i in items if i.enabled and not i.error}
    known = {i.key for i in items}
    partials = state.get("partials", {})
    for rel, rec in list(partials.items()):
        p = root / rel
        if p.exists() and rel not in keep and (rec.get("item") in current or rec.get("item") not in known):
            p.unlink()
            log(f"Removed an unfinished download that's out of date: {rel}")
        if not p.exists():
            partials.pop(rel)


def matches(path: Path, f: RemoteFile, expected: Dict[str, str]) -> Optional[str]:
    """The SHA-256 of a file already on the drive if it's exactly f (same size and published checksums)."""
    if not expected or not path.is_file() or (f.size and path.stat().st_size != f.size):
        return None
    log(f"    found {path.name} on the drive, checking it...")
    got = hash_file(path, list(expected))
    return got["sha256"] if all(got[a] == v for a, v in expected.items()) else None


def install_files(root: Path, item: Item, state: Dict[str, Any], cfg: Dict[str, Any], force: bool) -> int:
    dest = root / item.dest
    dest.mkdir(parents=True, exist_ok=True)
    old = state["items"].get(item.key) or {}
    old_files: Dict[str, Any] = dict(old.get("files", {}))
    new_files: Dict[str, Any] = {}
    downloaded = 0
    for f in item.files:
        final = dest / f.name
        if f not in item.need:
            new_files[f.name] = old_files[f.name]
            continue
        expected = expected_digests(f)
        # already on the drive (copied by hand, state lost, or a sync stopped before saving): keep it if it checks out
        have = matches(final, f, expected)
        if have:
            new_files[f.name] = {"size": final.stat().st_size, "sha256": have, "verified": True}
            continue
        partial = fetch(root, state, item, f, cfg, force)
        got = verify_download(partial, f, expected)
        os.replace(partial, final)
        forget_partial(root, state, partial)
        downloaded += final.stat().st_size
        new_files[f.name] = {"size": final.stat().st_size, "sha256": got, "verified": bool(expected)}
        log(f"    ok: {f.name}" + ("" if expected else " (no published checksum to compare; recorded ours)"))
    for name in old_files:
        if name not in new_files:
            (dest / name).unlink(missing_ok=True)
            log(f"    removed old version: {name}")
    state["items"][item.key] = {"version": item.version, "dest": item.dest, "files": new_files,
                                "updated": now_iso(), "note": item.note}
    return downloaded


def install_archive(root: Path, item: Item, state: Dict[str, Any], cfg: Dict[str, Any], force: bool) -> int:
    f = item.files[0]
    expected = expected_digests(f)
    partial = fetch(root, state, item, f, cfg, force, room=3)
    got = verify_download(partial, f, expected)
    base = root / item.dest
    target = base / safe_name(item.version)
    extract_archive(partial, f.name, target)
    binary = find_binary(target, item.cfg.get("binary"))
    if item.cfg.get("binary") and not binary:
        shutil.rmtree(target, ignore_errors=True)
        raise RuntimeError(f"{item.cfg['binary']} not found inside {f.name}; the release layout changed")
    if binary and not binary.name.endswith(".exe"):
        for p in binary.parent.iterdir():
            if p.is_file() and not p.suffix:
                try:
                    p.chmod(p.stat().st_mode | 0o111)
                except OSError:
                    pass
    if sys.platform == "darwin":
        subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(target)], capture_output=True)
    (base / "CURRENT").write_text(safe_name(item.version) + "\n", encoding="utf-8")
    old = state["items"].get(item.key) or {}
    versions = [v for v in old.get("versions", []) if v != item.version and (base / safe_name(v)).is_dir()]
    keep = int(cfg["settings"].get("keep_previous_runtime_versions", 1))
    for v in versions[keep:]:
        shutil.rmtree(base / safe_name(v), ignore_errors=True)
        log(f"    removed old version: {v}")
    partial.unlink(missing_ok=True)
    forget_partial(root, state, partial)
    log(f"    ok: {binary.relative_to(root) if binary else target.relative_to(root)}")
    state["items"][item.key] = {
        "version": item.version, "current": item.version, "versions": [item.version] + versions[:keep],
        "dest": item.dest, "archive": f.name, "archive_sha256": got, "verified": bool(expected),
        "binary": str(binary.relative_to(root)) if binary else None, "updated": now_iso(), "note": item.note}
    return f.size or 0



# ----------------------------------------------------------------------------- maps installers

def dir_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.is_dir() else 0


def newest_file(folder: Path, pattern: str) -> Optional[Path]:
    hits = [p for p in folder.glob(pattern) if p.is_file()] if folder.is_dir() else []
    return max(hits, key=lambda p: version_key(p.name)) if hits else None


def run_logged(cmd: List[str], what: str, cwd: Optional[Path] = None, attempts: int = 1) -> None:
    for n in range(1, attempts + 1):
        rc = subprocess.run([str(c) for c in cmd], cwd=str(cwd) if cwd else None).returncode
        if rc == 0:
            return
        if n < attempts:
            log(f"    {what} failed (exit {rc}); retrying ({n}/{attempts - 1})...")
            time.sleep(15)
    raise RuntimeError(f"{what} failed (exit {rc}); see the messages above")


def install_protomaps(root: Path, item: Item, state: Dict[str, Any], cfg: Dict[str, Any], force: bool) -> int:
    m = maps_settings(cfg)
    pm = runtime_binary(root, "pmtiles", "pmtiles")
    if not pm:
        raise RuntimeError("the pmtiles program (runtimes) isn't installed yet; run sync again")
    est = item.files[0].estimate or 15 * GB
    if not force and not ensure_space(root, 2 * est, cfg):     # world + region + combined copy, briefly
        raise RuntimeError(f"not enough free space for the map tiles (needs about {fmt_size(2 * est)} while building)")
    dest = root / item.dest
    work = dest / ".build"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    src = item.files[0].url
    wmax, dmax = int(m["world_maxzoom"]), int(m["detail_maxzoom"])
    bbox = ",".join(str(x) for x in m["detail_bbox"])
    world, region, out = work / "world.pmtiles", work / "region.pmtiles", work / "basemap.pmtiles"
    log(f"    map tiles: world overview (zoom 0-{wmax}) from build {item.version}...")
    run_logged([pm, "extract", src, world, f"--maxzoom={wmax}"], "map extract (world)", attempts=3)
    log(f"    map tiles: {m['label']} street detail (zoom {wmax + 1}-{dmax})...")
    run_logged([pm, "extract", src, region, f"--bbox={bbox}", f"--minzoom={wmax + 1}", f"--maxzoom={dmax}"],
               "map extract (region)", attempts=3)
    log("    map tiles: combining and checking...")
    run_logged([pm, "merge", world, region, out], "map merge")
    run_logged([pm, "verify", out], "map verify")
    sha = sha256_file(out)
    os.replace(out, dest / "basemap.pmtiles")
    shutil.rmtree(work, ignore_errors=True)
    size = (dest / "basemap.pmtiles").stat().st_size
    log(f"    ok: maps/tiles/basemap.pmtiles ({fmt_size(size)})")
    state["items"][item.key] = {"version": item.version, "dest": item.dest, "updated": now_iso(), "note": item.note,
                                "files": {"basemap.pmtiles": {"size": size, "sha256": sha, "verified": False}}}
    return size


def graphhopper_yaml(m: Dict[str, Any], graph_dir: str, storage: str) -> str:
    profiles = [p for p in m.get("routing_profiles", ["car", "foot"]) if p in GH_ENCODED_VALUES] or ["car"]
    evs: List[str] = []
    for p in profiles:
        evs += [e for e in GH_ENCODED_VALUES[p] if e not in evs]
    lines = ["graphhopper:",
             "  datareader.file: region.osm.pbf",
             f"  graph.location: {graph_dir}",
             "  profiles:"]
    for p in profiles:
        lines += [f"    - name: {p}", f"      custom_model_files: [{p}.json]"]
    lines += ["  profiles_ch:"] + (["    - profile: car"] if "car" in profiles else [])
    if "car" not in profiles:
        lines[-1] = "  profiles_ch: []"
    lines += ["  profiles_lm: []",
              f"  graph.encoded_values: {', '.join(evs)}",
              "  prepare.min_network_size: 200",
              "  prepare.subnetworks.threads: 1",
              "  routing.snap_preventions_default: tunnel, bridge, ferry",
              "  routing.non_ch.max_waypoint_distance: 1000000",
              "  import.osm.ignored_highways: " + ('""' if set(profiles) - {"car"} else "footway,construction,cycleway,path,steps"),
              "  datareader.preferred_language: en",
              f"  graph.dataaccess.default_type: {storage}",
              "  graph.locktype: simple",
              "server:",
              "  application_connectors:",
              "  - type: http",
              f"    port: {int(m['routing_port'])}",
              "    bind_host: localhost",
              "    max_request_header_size: 50k",
              "  request_log:",
              "    appenders: []",
              "  admin_connectors:",
              "  - type: http",
              f"    port: {int(m['routing_port']) + 1}",
              "    bind_host: localhost",
              "logging:",
              "  appenders:",
              "    - type: console",
              "      time_zone: UTC",
              ""]
    return "\n".join(lines)


def install_routing(root: Path, item: Item, state: Dict[str, Any], cfg: Dict[str, Any], force: bool) -> int:
    m = maps_settings(cfg)
    java = runtime_binary(root, "java", "java")
    gh = newest_file(root / "bin" / "graphhopper", "graphhopper-web-*.jar")
    if not java or not gh:
        raise RuntimeError("Java or GraphHopper (runtimes) isn't installed yet; run sync again")
    dest = root / item.dest
    dest.mkdir(parents=True, exist_ok=True)
    f = item.files[0]
    pbf = dest / f.name
    old = state["items"].get(item.key) or {}
    downloaded = 0
    if old.get("version") != item.version or not pbf.exists():
        expected = expected_digests(f)
        sha = matches(pbf, f, expected)    # downloaded last time, but the import failed (e.g. out of memory)
        if not sha:
            partial = fetch(root, state, item, f, cfg, force, room=3, label="road data")
            sha = verify_download(partial, f, expected)
            os.replace(partial, pbf)
            forget_partial(root, state, partial)
            downloaded = pbf.stat().st_size
    else:
        sha = (old.get("files", {}).get(f.name) or {}).get("sha256") or sha256_file(pbf)
    (dest / "gh-import.yml").write_text(graphhopper_yaml(m, "graph-cache.new", "RAM_STORE"), encoding="utf-8")
    (dest / "gh-serve.yml").write_text(graphhopper_yaml(m, "graph-cache", "MMAP"), encoding="utf-8")
    new = dest / "graph-cache.new"
    shutil.rmtree(new, ignore_errors=True)
    log("    building the road network for directions (GraphHopper import, 10-40 minutes)...")
    run_logged([java, f"-Xmx{m['routing_import_heap']}", "-jar", gh, "import", "gh-import.yml"],
               "GraphHopper import", cwd=dest)
    if not (new / "properties").exists():
        raise RuntimeError("GraphHopper import finished but produced no graph; see the messages above")
    current, trash = dest / "graph-cache", dest / "graph-cache.old"
    shutil.rmtree(trash, ignore_errors=True)
    if current.exists():
        os.replace(current, trash)
    os.replace(new, current)
    shutil.rmtree(trash, ignore_errors=True)
    log("    ok: maps/routing/graph-cache")
    state["items"][item.key] = {
        "version": item.version, "gh_version": item.extra.get("gh_version") or gh.name, "dest": item.dest,
        "updated": now_iso(), "note": item.note, "unpacked_size": dir_bytes(current),
        "files": {f.name: {"size": pbf.stat().st_size, "sha256": sha, "verified": True}}}
    return downloaded


def install_photon(root: Path, item: Item, state: Dict[str, Any], cfg: Dict[str, Any], force: bool) -> int:
    f = item.files[0]
    dest = root / item.dest
    expected = expected_digests(f)
    # the download plus about 3x that unpacked
    partial = fetch(root, state, item, f, cfg, force, room=4, label="the address database")
    sha = verify_download(partial, f, expected)
    staging = dest.with_name(dest.name + ".new")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    log("    unpacking it (10-40 minutes)...")
    fast = shutil.which("pbzip2") or shutil.which("lbzip2")
    if fast:
        unpack = subprocess.Popen([fast, "-dc", str(partial)], stdout=subprocess.PIPE)
        untar = subprocess.run(["tar", "-x", "-f", "-", "-C", str(staging)], stdin=unpack.stdout)   # "-f -": BSD tar may default to a tape
        unpack.stdout.close()
        ok = unpack.wait() == 0 and untar.returncode == 0
    else:
        ok = subprocess.run(["tar", "-xjf", str(partial), "-C", str(staging)]).returncode == 0
    data = staging / "photon_data"
    if not data.is_dir():
        nested = [d for d in staging.glob("*/photon_data") if d.is_dir()]
        if nested:
            os.replace(nested[0], data)
    if not ok or not data.is_dir():
        shutil.rmtree(staging, ignore_errors=True)
        raise RuntimeError("unpacking the address database failed")
    trash = dest.with_name(dest.name + ".old")
    shutil.rmtree(trash, ignore_errors=True)
    if dest.exists():
        os.replace(dest, trash)
    os.replace(staging, dest)
    shutil.rmtree(trash, ignore_errors=True)
    partial.unlink(missing_ok=True)
    forget_partial(root, state, partial)
    log("    ok: maps/geocoder/photon_data")
    state["items"][item.key] = {"version": item.version, "dest": item.dest, "archive": f.name, "archive_sha256": sha,
                                "db_version": item.extra.get("db_version"), "updated": now_iso(), "note": item.note,
                                "unpacked_size": dir_bytes(dest)}
    return f.size or 0


def installer_for(item: Item):
    if item.kind == "custom":
        return {"protomaps": install_protomaps, "routing": install_routing,
                "photon_db": install_photon}[item.cfg["type"]]
    return install_archive if item.kind == "archive" else install_files



# ----------------------------------------------------------------------------- portal page

def current_dir(root: Path, rel: str) -> Optional[Path]:
    base = root / rel
    cur = base / "CURRENT"
    if cur.exists():
        d = base / cur.read_text(encoding="utf-8").strip()
        if d.is_dir():
            return d
    return None


def b64file(p: Path) -> str:
    return base64.b64encode(p.read_bytes()).decode("ascii")


def build_portal(root: Path, cfg: Dict[str, Any]) -> Path:
    """Assemble the portal page served by kiwix-serve, with the map engine and map config embedded
    (kiwix-serve can only serve one custom page, so everything the map needs goes inside it)."""
    tpl = (root / "tools" / "portal.html").read_text(encoding="utf-8")
    m = maps_settings(cfg)
    info: Dict[str, Any] = {"available": False}
    inject = ""
    if not m["enabled"]:
        info["reason"] = "Maps are turned off in kit.json."
    else:
        ml = current_dir(root, "maps/viewer/maplibre-gl")
        bm = current_dir(root, "maps/viewer/protomaps-basemaps")
        ba = current_dir(root, "maps/viewer/basemaps-assets")
        parts = {
            "map engine": ml / "package" / "dist" / "maplibre-gl.js" if ml else None,
            "map engine styles": ml / "package" / "dist" / "maplibre-gl.css" if ml else None,
            "map style": bm / "package" / "dist" / "basemaps.js" if bm else None,
            "map fonts": next(iter(ba.glob("*/fonts")), None) if ba else None,
            "map icons": next(iter(ba.glob("*/sprites/v4")), None) if ba else None,
            "map tiles": root / "maps" / "tiles" / "basemap.pmtiles",
        }
        missing = [k for k, v in parts.items() if v is None or not v.exists()]
        if missing:
            info["reason"] = "Not downloaded yet: " + ", ".join(missing) + ". Run ./kit sync while online."
        else:
            fonts, sprites = parts["map fonts"], parts["map icons"]
            glyphs = {f"{font}/{rng}": b64file(fonts / font / f"{rng}.pbf")
                      for font in GLYPH_FONTS for rng in GLYPH_RANGES if (fonts / font / f"{rng}.pbf").exists()}
            spr: Dict[str, Any] = {}
            for name in ("light", "light@2x"):
                if (sprites / f"{name}.json").exists() and (sprites / f"{name}.png").exists():
                    spr[f"{name}.json"] = json.loads((sprites / f"{name}.json").read_text(encoding="utf-8"))
                    spr[f"{name}.png"] = b64file(sprites / f"{name}.png")
            info = {
                "available": True, "label": m["label"], "home": m["home"], "bbox": m["detail_bbox"],
                "detailMaxzoom": int(m["detail_maxzoom"]), "units": m["units"],
                "profiles": [p for p in m["routing_profiles"] if p in GH_ENCODED_VALUES],
                "ports": {"tiles": int(m["tiles_port"]), "geocoder": int(m["geocoder_port"]),
                          "routing": int(m["routing_port"])},
                "tileset": "basemap", "glyphs": glyphs, "sprites": spr,
                "services": {"geocoder": (root / "maps" / "geocoder" / "photon_data").is_dir(),
                             "routing": (root / "maps" / "routing" / "graph-cache" / "properties").exists()},
            }
            def code(p: Path) -> str:
                return p.read_text(encoding="utf-8").replace("</script", "<\\/script")
            inject = (f"<style>{parts['map engine styles'].read_text(encoding='utf-8')}</style>\n"
                      f"<script>{code(parts['map engine'])}</script>\n<script>{code(parts['map style'])}</script>\n")
    inject += "<script>window.KIT_MAPS = " + json.dumps(info).replace("</", "<\\/") + ";</script>\n"
    html = tpl.replace("<!--KIT:MAPS-->", inject)
    # kiwix-serve renders this page as a Mustache template: switch the tag markers to something
    # that appears nowhere in the embedded code, so "{{" inside it is left alone.
    for o, c in (("<%", "%>"), ("[[kit:", ":kit]]"), ("@@kit<", ">kit@@")):
        if o not in html and c not in html:
            break
    else:
        raise RuntimeError("could not find safe template markers for the portal page")
    html = "{{=" + o + " " + c + "=}}" + html.replace("{{root}}", o + "root" + c)
    out = root / ".kit" / "portal.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(html, encoding="utf-8")
    os.replace(tmp, out)
    return out


def extract_archive(archive: Path, name: str, target: Path) -> None:
    """Extract on the internal disk first, then copy with symlinks resolved:
    exFAT drives (readable by Windows/Linux too) can't store symlinks."""
    tmp = Path(tempfile.mkdtemp(prefix="offlinekit-"))
    try:
        if name.endswith(".zip"):
            cmd = ["unzip", "-q", "-o", str(archive), "-d", str(tmp)]
        else:
            cmd = ["tar", "-xzf", str(archive), "-C", str(tmp)]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            raise RuntimeError(f"could not extract {name}: {p.stderr.strip()}")
        staging = target.with_name(target.name + ".partial")
        shutil.rmtree(staging, ignore_errors=True)
        shutil.copytree(tmp, staging, symlinks=False)
        shutil.rmtree(target, ignore_errors=True)
        os.replace(staging, target)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ----------------------------------------------------------------------------- housekeeping

def prepare_drive(root: Path) -> None:
    if sys.platform != "darwin":
        return
    # A kit downloaded as a ZIP is marked "from the internet", and macOS won't open marked scripts until
    # they're approved in System Settings. Lift the mark so START-HERE opens with a plain double-click in an outage.
    subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(root / "START-HERE.command"), str(root / "SETUP.command"),
                    str(root / "kit"), str(root / "tools")], capture_output=True)
    parts = root.resolve().parts
    if len(parts) >= 3 and parts[1] == "Volumes":   # keep Spotlight from indexing 500 GB of archives
        marker = Path("/", parts[1], parts[2], ".metadata_never_index")
        try:
            marker.touch(exist_ok=True)
        except OSError:
            pass


def write_inventory(root: Path, state: Dict[str, Any], cfg: Dict[str, Any]) -> None:
    lines = ["# What's on this drive", "",
             f"Last updated: {state.get('last_sync', 'never')}  ",
             "Generated by `./kit sync`. Start everything by double-clicking START-HERE.command.", ""]
    for section in SECTIONS:
        rows = [(k.split("/", 1)[1], v) for k, v in sorted(state["items"].items()) if k.startswith(section + "/")]
        if not rows:
            continue
        lines += [f"## {section.capitalize()}", "", "| Item | Version | Size | Notes |", "|---|---|---|---|"]
        for ident, v in rows:
            size = sum(f.get("size", 0) for f in v.get("files", {}).values()) + v.get("unpacked_size", 0)
            lines.append(f"| {ident} | {v.get('version', '')} | {fmt_size(size) if size else ''} | "
                         f"{(v.get('note') or '').replace('|', '/')} |")
        lines.append("")
    (root / "INVENTORY.md").write_text("\n".join(lines), encoding="utf-8")


class Lock:
    def __init__(self, root: Path):
        self.path = root / ".kit" / "lock"
        self.fh = None

    def __enter__(self) -> "Lock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "w")
        try:
            import fcntl
            fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            die("another ./kit sync is already running on this drive")
        except (OSError, ImportError):
            pass  # filesystem without locking support: carry on
        return self

    def __exit__(self, *exc: Any) -> None:
        if self.fh:
            self.fh.close()


# ----------------------------------------------------------------------------- commands

def cmd_plan(root: Path, args: argparse.Namespace) -> None:
    cfg, state = load_config(root), load_state(root)
    if args.json:
        return plan_json(root, cfg, args.only)
    items = build_plan(root, cfg, state, args.only)
    print_plan(root, items, state, cfg)
    if offline(items):
        sys.exit(1)
    pending = [i for i in items if i.enabled and i.status in ("new", "update")]
    log(f"\n{len(pending)} item(s) to download. Run ./kit sync to do it." if pending else "\nEverything is up to date.")


def plan_json(root: Path, cfg: Dict[str, Any], only: List[str]) -> None:
    """Print the full download size of every item, disabled ones included, as JSON on stdout.
    Feeds the website's kit builder (site/build_sources.py). Downloads nothing."""
    cfg = json.loads(json.dumps(cfg))
    for section in ("models", "library", "extras"):
        for entry in cfg.get(section, []):
            entry["enabled"] = True
    cfg.setdefault("maps", {})["enabled"] = True
    with contextlib.redirect_stdout(sys.stderr):
        items = build_plan(root, cfg, {"items": {}}, only)
    out = {}
    for i in items:
        if not i.enabled:
            continue
        sizes = [f.size or f.estimate for f in i.files]
        out[i.key] = {"version": i.version or None, "error": i.error,
                      "bytes": sum(x for x in sizes if x) if any(sizes) else None,
                      "estimated": any(not f.size for f in i.files)}
    print(json.dumps(out, indent=1, sort_keys=True))


def cmd_sync(root: Path, args: argparse.Namespace) -> None:
    global LOG_FILE
    (root / "logs").mkdir(exist_ok=True)
    LOG_FILE = root / "logs" / f"sync-{dt.date.today().isoformat()}.log"
    log(f"\n===== sync started {now_iso()} =====")
    with Lock(root):
        prepare_drive(root)
        cfg, state = load_config(root), load_state(root)
        items = build_plan(root, cfg, state, args.only)
        print_plan(root, items, state, cfg)
        if offline(items):
            sys.exit(1)
        todo = sorted([i for i in items if i.enabled and i.status in ("new", "update")],
                      key=lambda i: (i.priority, i.need_bytes(root)))
        if todo and not args.yes and sys.stdin.isatty():
            if input(f"\nDownload {len(todo)} item(s) now? [Y/n] ").strip().lower() not in ("", "y", "yes"):
                return
        if not args.only:
            sweep_partials(root, state, items)
        failures, done_bytes, start = [], 0, time.time()
        try:
            for n, item in enumerate(todo, 1):
                log(f"\n[{n}/{len(todo)}] {item.key}  ({item.version})")
                try:
                    done_bytes += installer_for(item)(root, item, state, cfg, args.force)
                except Exception as e:    # one bad item mustn't end a sync that runs for hours
                    failures.append((item.key, str(e) or type(e).__name__))
                    log(f"    FAILED: {failures[-1][1]}")
                save_state(root, state)
        except KeyboardInterrupt:
            save_state(root, state)
            log("\nStopped. Everything finished so far is saved; run ./kit sync again to resume.")
            sys.exit(130)
        errors = [i for i in items if i.enabled and i.status == "error"]
        if not failures and not errors and not args.only:
            state["last_sync"] = now_iso()
        save_state(root, state)
        write_inventory(root, state, cfg)
        try:
            build_portal(root, cfg)
        except (OSError, RuntimeError, ValueError) as e:
            failures.append(("portal page", str(e)))
        if todo:
            log(f"\nDownloaded {fmt_size(done_bytes)} in {(time.time() - start) / 60:.0f} min.")
        elif not failures and not errors:
            log("\nEverything is up to date.")
        if failures or errors:
            log("\nProblems (everything else is done):")
            for key, msg in failures:
                log(f"  - {key}: {msg}")
            for i in errors:
                log(f"  - {i.key}: {i.error}")
            log("Re-run ./kit sync to retry. Fix or disable items in kit.json if they keep failing.")
        if todo:
            every = int(cfg["settings"].get("update_every_days", 75))
            log(f"\nNext update due around {(dt.date.today() + dt.timedelta(days=every)).isoformat()}. "
                "Now run ./kit test to check that everything starts.")
    sys.exit(1 if failures or errors else 0)


def cmd_verify(root: Path, args: argparse.Namespace) -> None:
    state = load_state(root)
    bad, checked, broken = [], 0, []
    for key, v in sorted(state["items"].items()):
        if "files" in v:
            for name, meta in v["files"].items():
                path = root / v["dest"] / name
                checked += 1
                if not path.exists():
                    bad.append(f"{key}: {name} is missing")
                    broken.append((key, name, path))
                elif path.stat().st_size != meta.get("size"):
                    bad.append(f"{key}: {name} has the wrong size")
                    broken.append((key, name, path))
                elif not args.quick and meta.get("sha256"):
                    if sys.stdout.isatty():
                        print(f"  checking {name}...".ljust(78)[:78], end="\r", flush=True)
                    if sha256_file(path) != meta["sha256"]:
                        bad.append(f"{key}: {name} is CORRUPT (checksum mismatch)")
                        broken.append((key, name, path))
        elif v.get("binary"):
            checked += 1
            if not (root / v["binary"]).exists():
                bad.append(f"{key}: {v['binary']} is missing")
    if sys.stdout.isatty():
        print(" " * 78, end="\r", flush=True)
    if bad:
        log("Problems found:\n  " + "\n  ".join(bad))
        if args.fix:
            for key, name, path in broken:
                path.unlink(missing_ok=True)
                state["items"][key]["files"].pop(name, None)
            save_state(root, state)
            log("Removed the bad files. Run ./kit sync (while online) to download fresh copies.")
        else:
            log("Fix: run ./kit verify --fix, then ./kit sync while online to download fresh copies.")
        sys.exit(1)
    log(f"All {checked} files OK" + (" (sizes only; drop --quick for full checksums)." if args.quick else "."))


def cmd_status(root: Path, args: argparse.Namespace) -> None:
    state, cfg = load_state(root), load_config(root)
    usage = shutil.disk_usage(root)
    total = 0
    for section in SECTIONS:
        rows = [(k, v) for k, v in sorted(state["items"].items()) if k.startswith(section + "/")]
        if rows:
            log(f"\n[{section}]")
        for key, v in rows:
            size = sum(f.get("size", 0) for f in v.get("files", {}).values()) + v.get("unpacked_size", 0)
            total += size
            log(f"  {key.split('/', 1)[1][:44]:<46}{v.get('version', ''):<16}{fmt_size(size) if size else '':>9}"
                f"   {v.get('updated', '')[:10]}")
    left = sorted(set(state.get("partials", {})) | {p.relative_to(root).as_posix() for pattern in
                  ("library/*.partial", "models/*/*.partial", "maps/*/*.partial", ".kit/downloads/*.partial")
                  for p in root.glob(pattern)})
    left = [(rel, (root / rel).stat().st_size) for rel in left if (root / rel).is_file()]
    if left:
        log("\nUnfinished downloads (sync resumes them while the item is on in kit.json; delete one to free its space):")
        for rel, size in left:
            log(f"  {rel[:60]:<62}{fmt_size(size):>9}")
    last = state.get("last_sync")
    log(f"\nKit content: {fmt_size(total)}.  Drive: {fmt_size(usage.free)} free of {fmt_size(usage.total)}.")
    if last:
        age = (dt.datetime.now() - dt.datetime.fromisoformat(last)).days
        every = int(cfg["settings"].get("update_every_days", 75))
        log(f"Last complete sync: {last[:10]} ({age} days ago)." + ("  Time to run ./kit sync." if age >= every else ""))
    else:
        log("Never fully synced. Run ./kit sync.")


def cmd_search(root: Path, args: argparse.Namespace) -> None:
    cfg = load_config(root)
    try:
        catalog = Resolver(root, cfg).catalog(max_age_hours=72)
    except ValueError as e:
        die(str(e))
    words = [w.lower() for w in args.words]
    configured = {e.get("zim") for e in cfg.get("library", [])}
    hits = [e for e in catalog.values()
            if all(w in " ".join([e["prefix"], e.get("title", ""), e.get("summary", "")]).lower() for w in words)]
    if not hits:
        log("No matches. Try fewer or different words.")
        return
    hits.sort(key=lambda e: e.get("size") or 0)
    for e in hits[:60]:
        mark = "  (already in kit.json)" if e["prefix"] in configured else ""
        log(f"{fmt_size(e.get('size')):>9}  {e['date']}  {e['prefix']}{mark}\n           {e.get('title', '')}: "
            f"{(e.get('summary') or '')[:90]}")
    if len(hits) > 60:
        log(f"... and {len(hits) - 60} more; add words to narrow it down.")
    log('\nTo add one, put a line like this in the "library" list in kit.json, then run ./kit sync:\n'
        f'    {{"zim": "{hits[0]["prefix"]}", "note": "{hits[0].get("title", "")}"}},')


# ----------------------------------------------------------------------------- self-test

def platform_tag() -> str:
    sysname, mach = platform.system(), platform.machine().lower()
    if sysname == "Darwin":
        return "macos-arm64" if mach in ("arm64", "aarch64") else "macos-x64"
    if sysname == "Linux":
        return "linux-x64" if mach in ("x86_64", "amd64") else f"linux-{mach}"
    return "windows-x64"


def runtime_binary(root: Path, product: str, name: str) -> Optional[Path]:
    override = os.environ.get(f"KIT_{product.upper().replace('.', '').replace('-', '_')}_BIN")
    if override:
        return Path(override)
    base = root / "bin" / f"{product}-{platform_tag()}"
    cur = base / "CURRENT"
    if cur.exists():
        found = find_binary(base / cur.read_text().strip(), name)
        if found:
            return found
    return find_binary(base, name)


def wait_http(url: str, timeout: float) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            http_get(url, timeout=5)
            return True
        except HttpError:
            time.sleep(1)
    return False


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]



def test_maps(root: Path, m: Dict[str, Any], check: Any, procs: List[subprocess.Popen], logs_dir: Path) -> None:
    home = m["home"]
    pm = runtime_binary(root, "pmtiles", "pmtiles")
    tiles = root / "maps" / "tiles" / "basemap.pmtiles"
    check("map tiles present", bool(pm) and tiles.exists(), "" if tiles.exists() else "run ./kit sync")
    if pm and tiles.exists():
        port = free_port()
        procs.append(subprocess.Popen([str(pm), "serve", str(tiles.parent), "--port", str(port),
                                       "--interface", "127.0.0.1", "--cors", "*"],
                                      stdout=open(logs_dir / "test-tiles.log", "w"), stderr=subprocess.STDOUT))
        up = wait_http(f"http://127.0.0.1:{port}/basemap.json", 30)
        ok = False
        if up:
            try:
                ok = len(http_get(f"http://127.0.0.1:{port}/basemap/0/0/0.mvt")) > 0
            except HttpError:
                ok = False
        check("map tile server works", ok)
    java = runtime_binary(root, "java", "java")
    photon = newest_file(root / "bin" / "photon", "photon-*.jar")
    gdir = root / "maps" / "geocoder"
    check("address search installed", bool(java and photon and (gdir / "photon_data").is_dir()))
    if java and photon and (gdir / "photon_data").is_dir():
        port = free_port()
        procs.append(subprocess.Popen([str(java), f"-Xmx{m['geocoder_heap']}", "-jar", str(photon), "serve",
                                       "-data-dir", str(gdir), "-listen-ip", "127.0.0.1", "-listen-port", str(port),
                                       "-cors-any"],
                                      stdout=open(logs_dir / "test-geocoder.log", "w"), stderr=subprocess.STDOUT))
        up = wait_http(f"http://127.0.0.1:{port}/status", 240)
        detail = "did not start (see logs/test-geocoder.log)"
        ok = False
        if up:
            try:
                res = http_json(f"http://127.0.0.1:{port}/api?q=Main+Street&limit=3&lat={home['lat']}&lon={home['lon']}")
                feats = res.get("features", [])
                ok = bool(feats)
                if feats:
                    pr = feats[0].get("properties", {})
                    detail = ", ".join(str(pr[k]) for k in ("name", "city", "state") if pr.get(k))
                else:
                    detail = "no results"
            except (HttpError, ValueError) as e:
                detail = str(e)
        check("address search works", ok, detail)
    gh = newest_file(root / "bin" / "graphhopper", "graphhopper-web-*.jar")
    rdir = root / "maps" / "routing"
    check("directions installed", bool(java and gh and (rdir / "graph-cache" / "properties").exists()))
    if java and gh and (rdir / "graph-cache" / "properties").exists():
        port = free_port()
        procs.append(subprocess.Popen([str(java), f"-Xmx{m['routing_heap']}",
                                       f"-Ddw.server.application_connectors[0].port={port}",
                                       f"-Ddw.server.admin_connectors[0].port={free_port()}",
                                       "-jar", str(gh), "server", "gh-serve.yml"], cwd=str(rdir),
                                      stdout=open(logs_dir / "test-routing.log", "w"), stderr=subprocess.STDOUT))
        up = wait_http(f"http://127.0.0.1:{port}/health", 240)
        detail, ok = "did not start (see logs/test-routing.log)", False
        if up:
            profile = (m["routing_profiles"] or ["car"])[0]
            lat, lon = float(home["lat"]), float(home["lon"])
            try:
                res = http_json(f"http://127.0.0.1:{port}/route?point={lat},{lon}&point={lat + 0.02},{lon + 0.02}"
                                f"&profile={profile}&points_encoded=false&locale=en")
                path = res["paths"][0]
                ok = path["distance"] > 0 and bool(path.get("instructions"))
                detail = f"{path['distance'] / 1000:.1f} km, {len(path.get('instructions', []))} steps ({profile})"
            except (HttpError, ValueError, KeyError, IndexError) as e:
                detail = str(e)[:200]
        check("directions work", ok, detail)


def cmd_test(root: Path, args: argparse.Namespace) -> None:
    results: List[tuple] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok))
        log(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f": {detail}" if detail else ""))

    cfg = load_config(root)
    try:
        portal = build_portal(root, cfg)
    except (OSError, RuntimeError, ValueError) as e:
        log(f"  (could not build the portal page: {e}; testing the plain one)")
        portal = root / "tools" / "portal.html"
    kiwix = runtime_binary(root, "kiwix-tools", "kiwix-serve")
    llama = runtime_binary(root, "llama.cpp", "llama-server")
    zims = sorted((root / "library").glob("*.zim"))
    models = sorted(p for p in (root / "models").glob("*") if p.is_dir() and list(p.glob("*.gguf")))
    log(f"Platform: {platform_tag()}")
    check("library server installed", bool(kiwix), str(kiwix or "run ./kit sync"))
    check("AI server installed", bool(llama), str(llama or "run ./kit sync"))
    check("library files present", bool(zims), f"{len(zims)} .zim files")
    check("models present", bool(models), ", ".join(m.name for m in models))
    procs: List[subprocess.Popen] = []
    logs_dir = root / "logs"
    logs_dir.mkdir(exist_ok=True)
    try:
        if kiwix and zims:
            kport = free_port()
            procs.append(subprocess.Popen(
                [str(kiwix), "--port", str(kport), "--address", "127.0.0.1",
                 "--customIndex", str(portal), *map(str, zims)],
                stdout=open(logs_dir / "test-kiwix.log", "w"), stderr=subprocess.STDOUT))
            up = wait_http(f"http://127.0.0.1:{kport}/", 60)
            check("library server starts", up)
            if up:
                page = http_get(f"http://127.0.0.1:{kport}/").decode(errors="replace")
                check("portal page served", "Tinfoil Kit" in page and "{{" not in page[:200])
                if maps_settings(cfg)["enabled"]:
                    mi = re.search(r"window\.KIT_MAPS = (\{.*?\});</script>", page, flags=re.S)
                    avail = bool(mi) and '"available": true' in mi.group(1)
                    check("map page built", avail, "" if avail else (json.loads(mi.group(1)).get("reason", "") if mi else "missing"))
                cat = http_get(f"http://127.0.0.1:{kport}/catalog/v2/entries?count=-1").decode(errors="replace")
                check("all books listed", cat.count("<entry>") >= len(zims), f"{cat.count('<entry>')} books")
                books = re.findall(r'<link type="text/html" href="[^"]*/content/([^"]+)"', cat)
                hits = 0
                for book in books[:5]:
                    try:
                        xml = http_get(f"http://127.0.0.1:{kport}/search?content={urllib.parse.quote(book)}"
                                       f"&pattern=water&format=xml&pageLength=3").decode(errors="replace")
                        hits += xml.count("<item>")
                    except HttpError:
                        pass
                check("full-text search works", hits > 0, f"{hits} results for 'water'")
        if llama and models:
            lport = free_port()
            small = min(models, key=lambda m: sum(f.stat().st_size for f in m.glob("*.gguf")))
            name = args.model or small.name
            procs.append(subprocess.Popen(
                [str(llama), "--models-dir", str(root / "models"), "--models-max", "1", "-c", "4096",
                 "--host", "127.0.0.1", "--port", str(lport), "--cors-origins", "http://127.0.0.1:8888"],
                stdout=open(logs_dir / "test-llama.log", "w"), stderr=subprocess.STDOUT))
            up = wait_http(f"http://127.0.0.1:{lport}/v1/models", 90)
            check("AI server starts", up)
            if up:
                listed = [m.get("id") for m in http_json(f"http://127.0.0.1:{lport}/v1/models").get("data", [])]
                check("models discovered", all(m.name in listed for m in models), ", ".join(map(str, listed)))
                body = json.dumps({"model": name, "max_tokens": 64, "temperature": 0,
                                   "messages": [{"role": "user", "content": "Reply with just the word OK."}]})
                t0 = time.time()
                p = subprocess.run(["curl", "-fsS", "--max-time", "600", "-H", "Content-Type: application/json",
                                    "-d", body, f"http://127.0.0.1:{lport}/v1/chat/completions"],
                                   capture_output=True, text=True)
                ok, detail = False, p.stderr.strip()
                if p.returncode == 0:
                    msg = json.loads(p.stdout)["choices"][0]["message"]
                    reply = (msg.get("content") or msg.get("reasoning_content") or "").strip()
                    ok, detail = bool(reply), f"{name} answered in {time.time() - t0:.0f}s: {reply[:40]!r}"
                check("model answers", ok, detail)
                pre = subprocess.run(["curl", "-sS", "-o", "/dev/null", "-D", "-", "-X", "OPTIONS",
                                      "-H", "Origin: http://127.0.0.1:8888",
                                      "-H", "Access-Control-Request-Method: POST",
                                      f"http://127.0.0.1:{lport}/v1/chat/completions"],
                                     capture_output=True, text=True).stdout.lower()
                acao = re.search(r"access-control-allow-origin:\s*(\S+)", pre)
                check("portal may call the AI (CORS)", bool(acao) and acao.group(1) in ("*", "http://127.0.0.1:8888"),
                      acao.group(1) if acao else "no CORS header")
        m = maps_settings(cfg)
        if m["enabled"]:
            test_maps(root, m, check, procs, logs_dir)
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=15)
            except subprocess.TimeoutExpired:
                p.kill()
    failed = [n for n, ok in results if not ok]
    log("\nAll checks passed. The kit works offline." if not failed else
        f"\n{len(failed)} check(s) failed. Logs are in {logs_dir}.")
    sys.exit(1 if failed else 0)


# ----------------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(prog="kit", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=None, help="kit folder (default: the folder containing ./kit)")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("plan", help="preview what sync would do")
    p.add_argument("--only", nargs="*", default=[], help="limit to items whose section/id contains these words")
    p.add_argument("--json", action="store_true", help="print every item's size as JSON, disabled ones too")
    p = sub.add_parser("sync", help="download and update everything")
    p.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    p.add_argument("--force", action="store_true", help="ignore the keep_free_gb safety margin")
    p.add_argument("--only", nargs="*", default=[], help="limit to items whose section/id contains these words")
    p = sub.add_parser("verify", help="re-check files against their checksums")
    p.add_argument("--quick", action="store_true", help="check sizes only (fast)")
    p.add_argument("--fix", action="store_true", help="delete corrupt files so the next sync replaces them")
    sub.add_parser("status", help="show what's installed")
    p = sub.add_parser("search", help="search the Kiwix catalog for more content")
    p.add_argument("words", nargs="+")
    p = sub.add_parser("test", help="check that the offline servers start and answer")
    p.add_argument("--model", help="model folder name to test (default: the smallest)")
    args = ap.parse_args()
    root = (args.root or ROOT).resolve()
    if not shutil.which("curl"):
        die("curl is required")
    commands = {"plan": cmd_plan, "sync": cmd_sync, "verify": cmd_verify, "status": cmd_status,
                "search": cmd_search, "test": cmd_test}
    if args.cmd not in commands:
        ap.print_help()
        return
    try:
        commands[args.cmd](root, args)
    except KeyboardInterrupt:
        log("\nStopped.")
        sys.exit(130)


if __name__ == "__main__":
    main()
