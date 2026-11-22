#!/usr/bin/env python3
"""Tinfoil Kit: keeps an offline AI + knowledge library up to date, on an external drive or this computer.

Commands (run from the kit folder, e.g.  ./kit sync):
  plan [--json]      Show what would be downloaded or updated. Changes nothing.
                     --json prints every item's size, disabled ones too.
  sync [-y]          Download/update everything enabled in kit.json, verify every file
                     (SHA-256), then remove the old versions. Safe to interrupt and re-run.
                     --essentials: only the programs, the map, the most important books and the AI
                     this computer runs plus the smallest. SETUP's first run gets these first.
  verify [--quick]   Re-check every downloaded file against its recorded SHA-256.
                     --fix deletes the bad ones so the next sync replaces them.
  status             What's installed, when it was last updated, free space.
  search WORDS...    Search the Kiwix catalog for more library content to add to kit.json.
  test               Start the offline servers briefly and check they actually work.
  update [-y]        Replace the kit's own code with its newest release on GitHub, if it's signed
                     with the kit's release key (tools/release-signers), keeping your kit.json
                     changes. Shows what's new and asks first. SETUP.command runs it first.
  pins               Pin the newest build of every program, with its SHA-256, in tools/pins.json.
                     Run before a release: drives install exactly those builds.
  estimate           About how many GB this kit.json needs, from the sizes the website's kit
                     builder lists (--essentials: just those). Needs no internet. SETUP.command uses it.
  drives [--json]    The plugged-in drives the kit could go on: folder, format, GB free, and why
                     not (or -). --json adds this computer's free space and what the kit needs.
  place DEST         Put the kit at DEST (a TinfoilKit folder at the top of a drive or in the home
                     folder), ready to set up there. Prints its folder. SETUP.command uses it.
  space PATH         Whether the kit, or just its essentials, fits at PATH (a kit folder, or where one
                     would go) and leaves 10% of the computer's disk, or 5% of a drive, free.
  essentials [on|off]
                     Get just the essentials from now on (on), or everything switched on (off).
  fit [--ask]        Which AI model this computer runs, given its memory, and the switched-on ones
                     too big for it. --ask (SETUP.command) asks whether to download those anyway;
                     --skip switches them off, --restore back on. --json for scripts and agents.
  share [on|off|new-code]
                     Let phones and laptops on your home network use the kit, once they type its
                     access code. Shows the address, the code and a QR code.
  autostart [on|off] Start the kit whenever this computer starts, for a home server (Linux: a
                     systemd user service; Mac: when you log in).
  region [PLACE]     Where you live (a US state or a country): sets the map area, the road data for
                     directions, address search, home and units. --wikipedia en,es also picks Wikipedia's
                     languages; --find WORDS lists places; --languages lists a place's languages.

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
import io
import json
import math
import os
import platform
import plistlib
import re
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

USER_AGENT = "TinfoilKit/1.0 (+https://github.com/tudor-city-ventures/tinfoilkit)"
KIWIX_CATALOG = os.environ.get("KIT_KIWIX_CATALOG", "https://library.kiwix.org/catalog/v2/entries?count=-1")
KIWIX_RELEASES = os.environ.get("KIT_KIWIX_RELEASES", "https://download.kiwix.org/release/{product}/")
GITHUB_API = os.environ.get("KIT_GITHUB_API", "https://api.github.com")
KIT_REPO = os.environ.get("KIT_REPO", "tudor-city-ventures/tinfoilkit")    # where ./kit update gets the kit's code
KIT_COMMIT = "$Format:%H$"    # git archive (a release, or Code > Download ZIP) writes the commit it packed here
HF = os.environ.get("KIT_HF", "https://huggingface.co")
ADOPTIUM_API = os.environ.get("KIT_ADOPTIUM_API", "https://api.adoptium.net")
MAVEN = os.environ.get("KIT_MAVEN", "https://repo1.maven.org/maven2")
NPM = os.environ.get("KIT_NPM", "https://registry.npmjs.org")
GITHUB_WEB = os.environ.get("KIT_GITHUB_WEB", "https://github.com")
PROTOMAPS_BUILDS = os.environ.get("KIT_PROTOMAPS_BUILDS", "https://build-metadata.protomaps.dev/builds.json")
PROTOMAPS_BUILD_BASE = os.environ.get("KIT_PROTOMAPS_BUILD_BASE", "https://build.protomaps.com")
PHOTON_DUMPS = os.environ.get("KIT_PHOTON_DUMPS", "https://download1.graphhopper.com/public/")
GEOFABRIK = os.environ.get("KIT_GEOFABRIK", "https://download.geofabrik.de")    # the road data in tools/regions.json
GB = 1_000_000_000
SECTIONS = ("runtimes", "models", "maps", "library", "extras")
MAPS_DEFAULTS: Dict[str, Any] = {
    "enabled": False,
    "label": "map region",
    "home": {"lat": 40.75, "lon": -73.99, "zoom": 10, "label": "Home"},
    "detail_bbox": [-80.6, 38.8, -66.8, 47.6],
    "detail_maxzoom": 15,
    "world_maxzoom": 7,
    "routing_osm_pbf": f"{GEOFABRIK.rstrip('/')}/north-america/us-northeast-latest.osm.pbf",
    "routing_profiles": ["car", "foot"],
    "geocoder_country": "us",
    "units": "imperial",
    "tiles_port": 8090,
    "geocoder_port": 2322,
    "routing_port": 8989,
    "routing_import_heap": "auto",
    "routing_heap": "2g",
    "geocoder_heap": "3g",
    "lang": "en",
}
# What a place in tools/regions.json sets ("Where do you live?"). Any of these in kit.json's maps wins over it.
REGION_KEYS = ("label", "home", "detail_bbox", "routing_osm_pbf", "geocoder_country", "geocoder_wide", "units", "lang")
REGIONS_FILE = Path(__file__).resolve().parent / "regions.json"
WIKIPEDIA_RE = re.compile(r"^wikipedia_([a-z]{2,3}(?:-[a-z]+)?)_all_")
GH_ENCODED_VALUES = {
    "car": ["car_access", "car_average_speed", "road_access"],
    "foot": ["foot_access", "foot_priority", "foot_average_speed", "foot_road_access", "hike_rating",
             "mtb_rating", "country", "road_class"],
    "bike": ["bike_priority", "bike_access", "roundabout", "bike_average_speed", "bike_road_access",
             "foot_road_access", "mtb_rating", "hike_rating", "country", "road_class"],
}
GLYPH_FONTS = ["Noto Sans Regular", "Noto Sans Medium", "Noto Sans Italic"]
GLYPH_RANGES = ["0-255", "256-511", "8192-8447"]
ARCHIVE_SUFFIXES = (".tar.gz", ".tgz", ".zip")
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


def http_get(url: str, timeout: int = 120, headers: Optional[Dict[str, str]] = None,
             save_headers: Optional[Path] = None) -> bytes:
    cmd = ["curl", "-fsSL", "--retry", "3", "--retry-delay", "2", "--connect-timeout", "20",
           "--max-time", str(timeout), "-A", USER_AGENT]
    if save_headers:
        cmd += ["-D", str(save_headers)]
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


def content_length(h: Dict[str, str]) -> Optional[int]:
    v = h.get("content-length", "")
    return (int(v) or None) if v.isdigit() else None


def head_size(url: str) -> Optional[int]:
    """A remote file's size, or None when the server won't say."""
    try:
        return content_length(http_head(url))
    except HttpError:
        return None


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
    status: str = ""               # ok | new | update | later (refresh_days) | error
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


# Programs, as opposed to the books, models and map data they serve: the kinds of source tools/pins.json can pin.
PINNED_TYPES = ("github", "kiwix_release", "adoptium", "maven", "npm", "github_archive")
PIN_GONE = ("the build this version of the kit names (tools/pins.json). Run SETUP to update the kit, "
            "or set \"pin_programs\": false in kit.json")


def load_pins(root: Path, cfg: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """tools/pins.json: the exact build of each program this version of the kit installs, and its SHA-256.
    Every release brings its own copy, signed with the rest, so a drive gets a new build of a program only with a new
    version of the kit, and a file swapped upstream under the same version is refused. ./kit pins writes it.
    "pin_programs": false in kit.json's settings takes the newest builds instead."""
    if cfg["settings"].get("pin_programs", True) is False:
        return {}
    try:
        pins = json.loads((root / "tools" / "pins.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in pins.items() if isinstance(v, dict) and isinstance(v.get("version"), str)}


_REGIONS: Dict[str, Any] = {}


def regions() -> Dict[str, Any]:
    """tools/regions.json: the places "Where do you live?" offers and Wikipedia's languages, made by
    site/build_regions.py from Geofabrik, Photon, Kiwix and GeoNames."""
    if not _REGIONS:
        try:
            _REGIONS.update(json.loads(REGIONS_FILE.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        _REGIONS.setdefault("regions", [])
        _REGIONS.setdefault("languages", {})
    return _REGIONS


def region(ident: Any) -> Optional[Dict[str, Any]]:
    return next((r for r in regions()["regions"] if r["id"] == ident), None) if ident else None


def region_maps(r: Dict[str, Any]) -> Dict[str, Any]:
    """A place's map settings, as kit.json's maps would spell them. Its road data can only come from Geofabrik."""
    if ".." in r["pbf"] or not re.fullmatch(r"[a-z0-9][a-z0-9/_-]*-latest\.osm\.pbf", r["pbf"]):
        raise ValueError(f"tools/regions.json has a bad road data path for {r['id']}")
    return {"label": r["name"], "home": {**r["home"], "zoom": 10}, "detail_bbox": r["bbox"],
            "routing_osm_pbf": f"{GEOFABRIK.rstrip('/')}/{r['pbf']}",
            "geocoder_country": r["country"] if r.get("photon") else "",    # Photon publishes none for a few places
            # a place with no address database of its own gets its whole region of the world's (most of Europe)
            "geocoder_wide": bool(r.get("addresses_wide")),
            "units": r["units"], "lang": (r.get("langs") or ["en"])[0]}


def maps_settings(cfg: Dict[str, Any]) -> Dict[str, Any]:
    user = cfg.get("maps") or {}
    preset: Dict[str, Any] = {}
    if user.get("region"):
        r = region(user["region"])
        try:
            preset = region_maps(r) if r else {"region_error": f"kit.json's region '{user['region']}' isn't one the kit "
                                                               "knows; ./kit region --find WORDS lists them"}
        except ValueError as e:
            preset = {"region_error": str(e)}
    m = {**MAPS_DEFAULTS, **preset, **user}
    m["home"] = {**MAPS_DEFAULTS["home"], **(preset.get("home") or {}), **(user.get("home") or {})}
    if "geocoder_country" in user and "geocoder_wide" not in user:
        m["geocoder_wide"] = False
    return m


def maps_items(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    m = maps_settings(cfg)
    if not m["enabled"]:
        return []
    geocoder = [{"id": "geocoder", "type": "photon_db", "country": m["geocoder_country"], "priority": 3,
                 "wide": bool(m.get("geocoder_wide")),
                 "note": "Address and place search database (Photon)"}] if m.get("geocoder_country") else []
    return [
        {"id": "maplibre-gl", "type": "npm", "package": "maplibre-gl", "version_prefix": "5.", "priority": 1,
         "note": "Map display engine (MapLibre)"},
        {"id": "protomaps-basemaps", "type": "npm", "package": "@protomaps/basemaps", "version_prefix": "5.",
         "priority": 1, "note": "Map style (Protomaps)"},
        {"id": "basemaps-assets", "type": "github_archive", "repo": "protomaps/basemaps-assets", "branch": "main",
         "priority": 1, "note": "Map fonts and icons"},
        {"id": "routing", "type": "routing", "url": m["routing_osm_pbf"], "priority": 2,
         "note": "Road network for directions (GraphHopper)"},
        {"id": "basemap", "type": "protomaps", "priority": 2,    # after routing: its size estimate uses the road data's
         "note": f"Offline map: {m['label']} in street detail, plus a world overview"},
    ] + geocoder


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
        self.pins = load_pins(root, cfg)

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
                    self._catalog_error = ValueError(f"couldn't reach the Kiwix catalog ({e}). Is this computer online?")
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
            pin = self.pins.get(item.id) if t in PINNED_TYPES else None
            if pin and pin.get("sha256") and item.files:
                f = item.files[0]
                if f.sha256 and f.sha256.lower() != pin["sha256"].lower():
                    raise ValueError(f"the file published as {item.version} changed after this version of the kit "
                                     f"pinned it (tools/pins.json), so it's left alone. Please report it at {REPORT}")
                f.sha256 = pin["sha256"].lower()
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
        """Re-resolve a GitHub runtime to the newest release whose version starts with prefix, even past its pin in
        tools/pins.json: a program that can't open its data is no use."""
        old, pins = dict(item.cfg), self.pins
        item.cfg, self.pins = {**item.cfg, "version_prefix": prefix}, {}
        try:
            self._github(item)
            return True
        except (ValueError, HttpError):
            item.cfg = old
            return False
        finally:
            self.pins = pins

    def pinned(self, item: Item) -> str:
        return str(self.pins.get(item.id, {}).get("version") or "")

    def _github(self, item: Item) -> None:
        repo, pattern, pin = item.cfg["repo"], item.cfg["asset"], self.pinned(item)
        if pin:    # llama.cpp publishes several builds a day, so a pinned one is soon past the first page
            if f"{repo}@{pin}" not in self._releases:
                try:
                    rel = http_json(f"{GITHUB_API}/repos/{repo}/releases/tags/{urllib.parse.quote(pin)}")
                except HttpError as e:
                    if e.status != 404:
                        raise
                    raise ValueError(f"{repo} no longer publishes {pin}, {PIN_GONE}") from e
                self._releases[f"{repo}@{pin}"] = [rel]
            repo_key = f"{repo}@{pin}"
        else:
            repo_key = repo
            if repo not in self._releases:
                self._releases[repo] = http_json(f"{GITHUB_API}/repos/{repo}/releases?per_page=30")
        candidates = [r for r in self._releases[repo_key] if not r.get("draft")]
        # llama.cpp's builds are its nightly prereleases. Every other program takes a full release while it has one.
        nightly = repo.endswith("/llama.cpp") and self.cfg["settings"].get("llama_cpp_channel", "nightly") != "stable"
        if not nightly:
            candidates.sort(key=lambda r: bool(r.get("prerelease")))    # a stable sort: each kind stays newest first
        prefix = str(item.cfg.get("version_prefix", ""))
        for rel in candidates:
            if prefix and not rel["tag_name"].lstrip("v").startswith(prefix):
                continue
            for a in rel.get("assets", []):
                if fnmatch.fnmatch(a["name"], pattern):
                    digest = a.get("digest") or ""
                    item.kind = "archive" if a["name"].endswith(ARCHIVE_SUFFIXES) else "files"
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
        pin = self.pinned(item)
        found = [f for f in found if f[1] == pin] if pin else found
        if not found:
            raise ValueError(f"no file matching '{pattern}'{f' for version {pin}' if pin else ''} in {base}")
        _, version, name = max(found)
        url = base + name
        is_archive = name.endswith(ARCHIVE_SUFFIXES)
        item.kind = "archive" if is_archive else "files"
        item.dest = f"bin/{item.id}" if is_archive else "installers"
        item.version = version
        item.files = [RemoteFile(name=name, url=url, size=head_size(url), sha256_sidecar=True)]

    def _url(self, item: Item) -> None:
        url = item.cfg["url"]
        name = item.cfg.get("filename") or urllib.parse.urlparse(url).path.split("/")[-1]
        h = http_head(url)
        size = content_length(h)
        item.dest = item.cfg.get("dest", "installers")
        item.version = h.get("etag") or h.get("last-modified") or (str(size) if size else "unknown")
        item.files = [RemoteFile(name=name, url=url, size=size, sha256=item.cfg.get("sha256"))]

    # --- maps: runtimes, viewer assets and data
    def _adoptium(self, item: Item) -> None:
        c = item.cfg
        query = f"architecture={c.get('arch', 'aarch64')}&image_type={c.get('image_type', 'jre')}&os={c.get('os', 'mac')}"
        pin = self.pinned(item)
        if pin:    # by its release name: a lookup by version must match Adoptium's own spelling, "-LTS" and all
            try:
                rels = http_json(f"{ADOPTIUM_API}/v3/assets/release_name/eclipse/{urllib.parse.quote(pin, safe='')}?"
                                 f"{query}&heap_size=normal&jvm_impl=hotspot&project=jdk")
            except HttpError as e:
                if e.status != 404:
                    raise
                rels = []
            rel = next((r for r in (rels if isinstance(rels, list) else [rels])
                        if isinstance(r, dict) and r.get("release_name") == pin), {})
            builds = [b for b in rel.get("binaries", []) if b.get("package") and (b.get("image_type"), b.get("os"),
                      b.get("architecture")) == (c.get("image_type", "jre"), c.get("os", "mac"), c.get("arch", "aarch64"))]
            if not builds:
                raise ValueError(f"Adoptium no longer publishes Java {pin} for {c.get('os', 'mac')} "
                                 f"{c.get('arch', 'aarch64')}, {PIN_GONE}")
            pkg = builds[0]["package"]
        else:
            data = http_json(f"{ADOPTIUM_API}/v3/assets/latest/{c.get('feature_version', 21)}/hotspot?{query}&vendor=eclipse")
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
        pin = self.pinned(item)
        versions = [v for v in versions if v == pin] if pin else versions
        if not versions:
            raise ValueError(f"no release of {c['artifact']} matching '{pin or prefix + '*'}'")
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
        item.kind, item.dest, item.version = "files", f"bin/{item.id}", v
        item.files = [RemoteFile(name=jar, url=url, size=head_size(url), checks=checks)]

    def _npm(self, item: Item) -> None:
        pkg, prefix = item.cfg["package"], str(item.cfg.get("version_prefix", ""))
        doc = http_json(f"{NPM}/{pkg}", timeout=180)
        versions = [v for v in doc.get("versions", {}) if v.startswith(prefix) and re.fullmatch(r"\d+\.\d+\.\d+", v)]
        pin = self.pinned(item)
        versions = [v for v in versions if v == pin] if pin else versions
        if not versions:
            raise ValueError(f"no version of {pkg} matching '{pin or prefix + '*'}'")
        v = max(versions, key=version_key)
        dist = doc["versions"][v]["dist"]
        checks = {}
        integrity = dist.get("integrity", "")
        if integrity.startswith("sha512-"):
            checks["sha512"] = base64.b64decode(integrity[7:]).hex()
        elif dist.get("shasum"):
            checks["sha1"] = dist["shasum"]
        item.kind, item.dest, item.version = "archive", f"maps/viewer/{item.id}", v
        item.files = [RemoteFile(name=f"{item.id}-{v}.tgz", url=dist["tarball"], size=head_size(dist["tarball"]), checks=checks)]

    def _github_archive(self, item: Item) -> None:
        repo, branch = item.cfg["repo"], item.cfg.get("branch", "main")
        sha = self.pinned(item) or http_json(f"{GITHUB_API}/repos/{repo}/commits/{branch}")["sha"]
        item.kind, item.dest, item.version = "archive", f"maps/viewer/{item.id}", sha[:12]
        item.files = [RemoteFile(name=f"{item.id}-{sha[:12]}.tar.gz", url=f"{GITHUB_WEB}/{repo}/archive/{sha}.tar.gz")]

    def _map_area(self) -> Dict[str, Any]:
        m = maps_settings(self.cfg)
        if m.get("region_error"):
            raise ValueError(m["region_error"])
        return m

    def _protomaps(self, item: Item) -> None:
        m = self._map_area()
        builds = [b for b in http_json(PROTOMAPS_BUILDS) if str(b.get("key", "")).endswith(".pmtiles")]
        major = str(item.cfg.get("tiles_major", "4")) + "."
        usable = [b for b in builds if str(b.get("version", major)).startswith(major)] or builds
        if not usable:
            raise ValueError("no Protomaps map build listed")
        latest = max(usable, key=lambda b: b["key"])
        roads = self.resolved.get("routing")
        est = tiles_estimate(m["detail_bbox"], m["detail_maxzoom"], roads.files[0].size if roads and roads.files else None)
        item.kind, item.dest = "custom", "maps/tiles"
        item.version = f"{latest['key'].replace('.pmtiles', '')} {m['label']}"
        # a different area is a new map, even from the same build
        item.extra["area"] = [[float(x) for x in m["detail_bbox"]], int(m["world_maxzoom"]), int(m["detail_maxzoom"])]
        item.files = [RemoteFile(name="basemap.pmtiles", url=f"{PROTOMAPS_BUILD_BASE}/{latest['key']}", estimate=est)]

    def _routing(self, item: Item) -> None:
        self._map_area()
        latest = item.cfg["url"]
        url, h = geofabrik_head(latest)
        size = content_length(h)
        gh = self.resolved.get("graphhopper")
        item.kind, item.dest = "custom", "maps/routing"
        # which extract it is, then its date: another place's road data is new even on the same day
        item.version = f"{latest.rsplit('/', 1)[-1].replace('-latest.osm.pbf', '')} {http_day(h) or size}"
        item.extra["gh_version"] = gh.version if gh is not None and not gh.error else ""
        item.files = [RemoteFile(name="region.osm.pbf", url=url, size=size, md5_sidecar=True)]

    def _photon_db(self, item: Item) -> None:
        self._map_area()
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
            size = content_length(h)
            item.kind, item.dest = "custom", "maps/geocoder"
            item.version = f"{path[-1]} {ver}/{http_day(h) or size}"
            item.extra["db_version"] = ver
            item.files = [RemoteFile(name=url.rsplit("/", 1)[-1], url=url, size=size, md5_sidecar=True)]
            return
        raise ValueError(f"couldn't find a Photon database file in {folder} for version(s) {', '.join(wanted)}")


def geofabrik_head(url: str) -> Tuple[str, Dict[str, str]]:
    """A road data file's address and headers. Geofabrik's -latest sends you on to the day's file (name-YYMMDD), which
    can be missing while they publish it: then the newest of the week before."""
    try:
        return url, http_head(url)
    except HttpError as first:
        if not url.endswith("-latest.osm.pbf"):
            raise
        for days in range(1, 8):
            dated = url[:-len("-latest.osm.pbf")] + (dt.date.today() - dt.timedelta(days=days)).strftime("-%y%m%d.osm.pbf")
            try:
                return dated, http_head(dated)
            except HttpError:
                continue
        raise first


def tiles_estimate(bbox: List[float], maxzoom: Any, roads_bytes: Optional[int] = None) -> int:
    """Rough size of the map tiles: about 1 GB of world overview, plus street detail at about 40 MB per square
    degree where streets are dense. A big, mostly empty area (a desert state's box) is capped at twice its road data."""
    w, s, e, n = (float(x) for x in bbox)
    detail = abs(e - w) * abs(n - s) * math.cos(math.radians((n + s) / 2)) * 40e6
    if roads_bytes:
        detail = min(detail, 2 * roads_bytes)
    return int(GB + detail * 0.4 ** max(0, 15 - int(maxzoom)))


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
    with tempfile.TemporaryDirectory() as tmp:
        headers = Path(tmp) / "headers"
        while url:     # a long list comes in pages, each naming the next in its Link header
            out += json.loads(http_get(url, save_headers=headers).decode("utf-8"))
            m = re.search(r'<([^>]+)>;\s*rel="next"', headers.read_text(errors="replace"))
            url = m.group(1) if m else None
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
        ok = st is not None and st.get("version") == item.version
        if t == "routing":
            ok = (ok and (d / "graph-cache" / "properties").exists()
                  and (not item.extra.get("gh_version") or st.get("gh_version") == item.extra["gh_version"]))
        elif t == "photon_db":
            ok = ok and (d / "photon_data").is_dir()
        else:
            ok = ok and all((d / f.name).exists() for f in item.files)
        if "area" in item.extra:
            ok = ok and st.get("area") == item.extra["area"]
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


def hold(item: Item, state: Dict[str, Any], root: Path, only: List[str]) -> None:
    """A book with refresh_days in kit.json keeps the edition it has until that one is so many days old: a new
    Wikipedia every few weeks isn't worth 115 GB each time. Naming it in --only gets the new edition now."""
    days, st = item.cfg.get("refresh_days"), state["items"].get(item.key) or {}
    if item.section != "library" or item.status != "update" or not isinstance(days, int) or only:
        return
    try:
        due = dt.datetime.fromisoformat(st["updated"]) + dt.timedelta(days=days)
    except (KeyError, TypeError, ValueError):
        return
    if due > dt.datetime.now() and st.get("files") and all((root / st.get("dest", item.dest) / name).is_file()
                                                            for name in st["files"]):
        item.status, item.need, item.extra["due"] = "later", [], due.date().isoformat()


def safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s or "unknown")


def find_binary(base: Path, name: Optional[str]) -> Optional[Path]:
    if not name or not base.exists():
        return None
    for p in sorted(base.rglob(name)):
        if p.is_file():
            return p
    return None


def essential(item: Item, fit: Dict[str, Any]) -> bool:
    """What the kit can't do without: the programs, the map, the most important books, and the AI model this computer
    runs plus the smallest one. SETUP's first run downloads and checks these first, so the kit works hours sooner."""
    if item.section == "models":
        return item.id in (fit["runs"], fit["smallest"])
    if item.cfg.get("wide"):     # address search for a whole region of the world, tens of GB
        return False
    return item.section in ("runtimes", "maps") or (item.section == "library" and item.priority <= 1)


def build_plan(root: Path, cfg: Dict[str, Any], state: Dict[str, Any], only: List[str],
               essentials: bool = False) -> List[Item]:
    items = items_from_config(cfg)
    if only:
        items = [i for i in items if any(o.lower() in i.key.lower() for o in only)]
    if essentials:
        fit = fit_report(root, cfg, state)
        items = [i for i in items if essential(i, fit)]
    resolver = Resolver(root, cfg)
    active = [i for i in items if i.enabled]
    log(f"Checking {len(active)} items for updates...")
    for n, item in enumerate(active, 1):
        if sys.stdout.isatty():
            print(f"  [{n}/{len(active)}] {item.key}".ljust(78)[:78], end="\r", flush=True)
        resolver.resolve(item)
        evaluate(item, state, root)
        hold(item, state, root, only)
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


def print_plan(root: Path, items: List[Item], state: Dict[str, Any], cfg: Dict[str, Any]) -> None:
    free = shutil.disk_usage(root).free
    total = 0
    labels = {"ok": "ok      ", "new": "NEW     ", "update": "UPDATE  ", "later": "later   ", "error": "ERROR   "}
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
            elif i.status == "later":
                detail = f"{(state['items'].get(i.key) or {}).get('version')}   ({i.version} waits until {i.extra['due']})"
            else:
                old = (state["items"].get(i.key) or {}).get("version")
                arrow = f"{old} -> {i.version}" if old and old != i.version else i.version
                size = fmt_size(need)
                if any(not f.size for f in i.need):     # some sizes are only known after downloading
                    size = "~" + size if need else "?"
                detail = f"{size:>9}   {arrow}"
            log(f"  {labels.get(i.status, i.status)}{i.id[:44]:<46}{detail}")
    if any(i.status == "later" for i in items if i.enabled):
        log("\n  later: a big book keeps the edition it has until its refresh_days in kit.json pass. "
            "To get the new one now:  ./kit sync --only NAME")
    disabled = [i for i in items if not i.enabled]
    if disabled:
        log(f"\n  ({len(disabled)} disabled in kit.json: {', '.join(i.id for i in disabled)})")
    if offline(items):
        log("\nNothing could be looked up. Check that this computer is online (on hotel or cafe Wi-Fi, "
            "open any web page and sign in first), then try again.")
        return
    keep, leave = keep_free(root, cfg), leave_free(root, cfg)
    log(f"\nTo download: {fmt_size(total)}   Free space: {fmt_size(free)}   "
        f"Free afterwards: ~{fmt_size(max(0, free - total))} (before old versions are removed)")
    if cfg["settings"].get("essentials_only") is True:
        log("Just the essentials, as chosen at setup. To get everything else too: ./kit essentials off")
    if free - total < keep:
        log(f"WARNING: that leaves less than the {fmt_size(keep)} the kit keeps free. Items that don't fit "
            "are skipped, the most important ones download first. Switch some off in kit.json, ./kit essentials on "
            "for just the essentials, or make room.")
    elif free - total < leave:
        log(f"Note: that leaves less than {fmt_size(leave)} free, the {10 if on_this_computer(root) else 5}% of the "
            "disk worth keeping free. Switch some off in kit.json, or ./kit essentials on for just the essentials.")


# ----------------------------------------------------------------------------- downloading

def drop_partial(partial: Path) -> None:
    """Delete an unfinished download, along with aria2c's record of which parts of it had arrived."""
    partial.unlink(missing_ok=True)
    partial.with_name(partial.name + ".aria2").unlink(missing_ok=True)


def download(url: str, partial: Path, size: Optional[int], downloader: str) -> None:
    partial.parent.mkdir(parents=True, exist_ok=True)
    if size and partial.exists() and partial.stat().st_size > size:
        drop_partial(partial)
    # aria2c fills a file in several places at once, so one it was stopped on can be full length with gaps in it.
    # Its record (<file>.aria2) is there until the download is whole.
    if (size and partial.exists() and partial.stat().st_size == size
            and not partial.with_name(partial.name + ".aria2").exists()):
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
            raise RuntimeError(f"couldn't save {partial.name}{free}. Is the disk full, or was the drive unplugged?")
        if not use_aria and (rc == 33 or status == "416"):   # can't resume this partial file: start over
            drop_partial(partial)
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


def sha256_file(path: Path) -> str:
    return hash_file(path, ["sha256"])["sha256"]


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


def on_this_computer(root: Path) -> bool:
    """True when the kit is on the computer's own disk (the one with the home folder), not on a drive."""
    try:
        return root.stat().st_dev == Path.home().stat().st_dev
    except OSError:
        return False


def keep_free(root: Path, cfg: Dict[str, Any]) -> float:
    """Bytes to leave free. The computer's own disk keeps more, so it still has room for system updates."""
    s = cfg["settings"]
    gb = float(s.get("keep_free_gb", 25))
    if on_this_computer(root):
        gb = max(gb, float(s.get("keep_free_gb_this_computer", 50)))
    return gb * GB


def leave_free(root: Path, cfg: Dict[str, Any]) -> float:
    """Bytes a comfortable install leaves free: 10% of the computer's own disk, 5% of a drive, or what the kit keeps
    free if that's more. SETUP steers people away from going below it; sync itself stops only at keep_free."""
    return max(keep_free(root, cfg), shutil.disk_usage(root).total * (0.10 if on_this_computer(root) else 0.05))


def ensure_space(root: Path, need: int, cfg: Dict[str, Any]) -> bool:
    return shutil.disk_usage(root).free - need >= keep_free(root, cfg)


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
        drop_partial(partial)
    have = partial.stat().st_size if partial.exists() else 0
    need = max(0, (f.size or 0) * room - have)
    if not force and not ensure_space(root, need, cfg):
        raise RuntimeError(f"not enough free space for {label or f.name} (needs about {fmt_size(need)} more, "
                           f"and the kit keeps {fmt_size(keep_free(root, cfg))} free); make room or switch it off in kit.json")
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
            drop_partial(p)
            log(f"Removed an unfinished download that's out of date: {rel}")
        if not p.exists():
            partials.pop(rel)


def drop_replaced_wikipedias(root: Path, state: Dict[str, Any], items: List[Item]) -> None:
    """A Wikipedia in a language ./kit region switched away from (50 to 130 GB) goes once the new one is in."""
    wanted = [i for i in items if i.section == "library" and WIKIPEDIA_RE.match(i.id) and i.enabled]
    if not wanted or not all("files" in state["items"].get(i.key, {}) for i in wanted):
        return
    listed = {i.key for i in items}
    for key, v in list(state["items"].items()):
        section, _, ident = key.partition("/")
        if section == "library" and WIKIPEDIA_RE.match(ident) and key not in listed and "files" in v:
            for name in v["files"]:
                (root / v["dest"] / name).unlink(missing_ok=True)
            del state["items"][key]
            log(f"Removed {ident}: kit.json has Wikipedia in another language now.")


def matches(path: Path, f: RemoteFile, expected: Dict[str, str]) -> Optional[str]:
    """The SHA-256 of a file already in the kit if it's exactly f (same size and published checksums)."""
    if not expected or not path.is_file() or (f.size and path.stat().st_size != f.size):
        return None
    log(f"    found {path.name} already here, checking it...")
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
        # already here (copied by hand, state lost, or a sync stopped before saving): keep it if it checks out
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


def inside(dest: Path, name: str) -> Path:
    """Where an archive member goes, refusing names that would land outside dest (downloads are untrusted)."""
    parts = PurePosixPath(name.replace("\\", "/")).parts
    if not parts or name.startswith(("/", "\\")) or ".." in parts or ":" in parts[0]:
        raise RuntimeError(f"the archive has an unexpected path in it: {name}")
    return dest.joinpath(*parts)


def link_target(dest: Path, link: Path, target: str) -> Optional[Path]:
    """Where a link in an archive points, if that's inside the archive: links can't go on exFAT, so they're copied."""
    if not target or target.startswith(("/", "\\")) or ":" in target:
        return None
    path = Path(os.path.normpath(link.parent / target.replace("\\", "/")))
    return path if path != link and os.path.commonpath([dest, path]) == str(dest) else None


def copy_links(links: List[Tuple[Path, Path]]) -> None:
    """Make each link a copy of what it points at. Links to files go first, a link to a link once that's copied,
    and links to folders last, so a copied folder has its links too."""
    while links:
        ready = [lt for lt in links if lt[1].is_file()] or [lt for lt in links if lt[1].is_dir()]
        if not ready:
            return    # the rest point at nothing in the archive
        for link, target in ready:
            link.parent.mkdir(parents=True, exist_ok=True)
            if target.is_file():
                shutil.copy(target, link)
            elif target not in link.parents:    # a link to a folder it's in would copy itself forever
                shutil.copytree(target, link, dirs_exist_ok=True)
        links = [lt for lt in links if lt not in ready]


def unzip_py(archive: Path, dest: Path) -> None:
    """unzip in Python, for Windows and Linux PCs without unzip."""
    links = []
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            path = inside(dest, info.filename)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                target = link_target(dest, path, z.read(info).decode("utf-8", "replace"))
                if target:
                    links.append((path, target))
            elif info.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, open(path, "wb") as out:
                    shutil.copyfileobj(src, out, 1 << 20)
                if mode & 0o111:
                    with contextlib.suppress(OSError):
                        path.chmod(0o755)
    copy_links(links)


def untar_py(archive: Path, dest: Path, compression: str) -> None:
    """tar in Python: Windows' tar can't always read bzip2, and a tar from Git for Windows takes C: for a
    remote host. Read as a stream, front to back, since the Photon database is tens of GB. Links become
    copies (a Mac's or Linux PC's programs have some, set up from Windows onto a drive)."""
    links = []
    with tarfile.open(archive, "r|" + compression) as tf:
        for m in tf:
            path = inside(dest, m.name)
            if m.isdir():
                path.mkdir(parents=True, exist_ok=True)
            elif m.isfile():
                path.parent.mkdir(parents=True, exist_ok=True)
                with tf.extractfile(m) as src, open(path, "wb") as out:
                    shutil.copyfileobj(src, out, 1 << 20)
                if m.mode & 0o111:
                    with contextlib.suppress(OSError):
                        path.chmod(0o755)
            elif m.issym() or m.islnk():
                target = link_target(dest, path, m.linkname) if m.issym() else inside(dest, m.linkname)
                if target:
                    links.append((path, target))
    copy_links(links)


def extract_archive(archive: Path, name: str, target: Path) -> None:
    """Extract on the internal disk first, then copy with symlinks resolved:
    exFAT drives (readable by Windows/Linux too) can't store symlinks."""
    tmp = Path(tempfile.mkdtemp(prefix="tinfoilkit-"))
    try:
        zipped = name.endswith(".zip")
        tool = "unzip" if zipped else "tar"
        if os.name == "nt" or not shutil.which(tool):
            try:
                unzip_py(archive, tmp) if zipped else untar_py(archive, tmp, "gz")
            except (OSError, EOFError, tarfile.TarError, zipfile.BadZipFile) as e:
                raise RuntimeError(f"could not extract {name}: {e}") from None
        else:
            cmd = ["unzip", "-q", "-o", str(archive), "-d", str(tmp)] if zipped else ["tar", "-xzf", str(archive), "-C", str(tmp)]
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

def drop_finder_files(root: Path) -> None:
    """macOS keeps Finder metadata for files on exFAT drives in "._name" files beside them. The servers
    scan library/ and models/ and could take ._name.zim or ._name.gguf for a book or a model."""
    for p in [*(root / "library").glob("._*"), *(root / "models").glob("**/._*")]:
        if p.is_file():
            p.unlink()


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
    state["items"][item.key] = {"version": item.version, "area": item.extra.get("area"), "dest": item.dest,
                                "updated": now_iso(), "note": item.note,
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
              f"  datareader.preferred_language: {m.get('lang') or 'en'}",
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


def import_heap(m: Dict[str, Any]) -> str:
    """Java memory for building the directions network: kit.json's routing_import_heap, else 12 GB or 60% of this
    computer's memory if that's less, so an 8 or 16 GB laptop doesn't run out."""
    if m["routing_import_heap"] != "auto":
        return str(m["routing_import_heap"])
    gb = memory_bytes() // 2**30    # Java's g
    return f"{min(12, max(2, gb * 6 // 10))}g" if gb else "12g"


def build_routing(java: Path, gh: Path, m: Dict[str, Any], dest: Path) -> None:
    """GraphHopper's import into dest/graph-cache.new: in memory, the fast way, and if that runs out of memory,
    again with the graph on disk, which needs far less."""
    heap = import_heap(m)
    for storage in ("RAM_STORE", "MMAP"):
        (dest / "gh-import.yml").write_text(graphhopper_yaml(m, "graph-cache.new", storage), encoding="utf-8")
        shutil.rmtree(dest / "graph-cache.new", ignore_errors=True)
        log("    building the road network for directions (GraphHopper import, 10-40 minutes)..." if storage == "RAM_STORE"
            else f"    that ran out of memory ({heap}), so building it again on disk, which takes longer...")
        rc = subprocess.run([str(java), f"-Xmx{heap}", "-XX:+ExitOnOutOfMemoryError", "-jar", str(gh), "import",
                             "gh-import.yml"], cwd=str(dest)).returncode
        if rc == 0:
            break
        if rc != 3:    # what -XX:+ExitOnOutOfMemoryError exits with
            raise RuntimeError(f"GraphHopper import failed (exit {rc}); see the messages above")
    else:
        raise RuntimeError(f"building the directions network ran out of memory ({heap}) even on disk. Close other apps "
                           "and run sync again, or choose a smaller map region")
    if not (dest / "graph-cache.new" / "properties").exists():
        raise RuntimeError("GraphHopper import finished but produced no graph; see the messages above")


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
    (dest / "gh-serve.yml").write_text(graphhopper_yaml(m, "graph-cache", "MMAP"), encoding="utf-8")
    new = dest / "graph-cache.new"
    build_routing(java, gh, m, dest)
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
    ok = False
    if os.name == "nt":
        pass
    elif fast:
        unpack = subprocess.Popen([fast, "-dc", str(partial)], stdout=subprocess.PIPE)
        untar = subprocess.run(["tar", "-x", "-f", "-", "-C", str(staging)], stdin=unpack.stdout)   # "-f -": BSD tar may default to a tape
        unpack.stdout.close()
        ok = unpack.wait() == 0 and untar.returncode == 0
    else:
        ok = subprocess.run(["tar", "-xjf", str(partial), "-C", str(staging)]).returncode == 0
    if not ok:    # Windows, or a Linux PC without bzip2
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        try:
            untar_py(partial, staging, "bz2")
            ok = True
        except (OSError, EOFError, tarfile.TarError, RuntimeError) as e:
            log(f"    {e}")
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
                "detailMaxzoom": int(m["detail_maxzoom"]), "units": m["units"], "lang": m.get("lang") or "en",
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
    inject += f"<script>window.KIT_REFRESHED = {json.dumps(load_state(root).get('last_sync'))};</script>\n"
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


# ----------------------------------------------------------------------------- housekeeping

def prepare_folder(root: Path) -> None:
    if sys.platform == "win32":
        # A kit unzipped from a download is marked "from the internet", and Windows warns before it runs a marked
        # script. Lift the mark from the kit's own scripts and tools (an exFAT drive can't hold it anyway).
        for p in [*root.glob("*.bat"), *root.glob("*.cmd"), *(root / "tools").glob("*")]:
            with contextlib.suppress(OSError):
                os.remove(f"{p}:Zone.Identifier")
        return
    if sys.platform != "darwin":
        return
    # A kit downloaded as a ZIP is marked "from the internet", and macOS won't open marked scripts until
    # they're approved in System Settings. Lift the mark so Open Tinfoil Kit opens with a plain double-click in an outage.
    subprocess.run(["xattr", "-dr", "com.apple.quarantine", *(str(root / f) for f in
                    ("Open Tinfoil Kit.command", "SETUP.command", "UNINSTALL.command", "kit", "tools"))], capture_output=True)
    if on_this_computer(root):
        # Time Machine would copy 300 GB of downloads to the backup disk at its next backup. A sticky exclusion
        # (no administrator needed) travels with the folder, and goes when the folder does.
        subprocess.run(["tmutil", "addexclusion", str(root)], capture_output=True)
        return
    parts = root.resolve().parts
    if len(parts) >= 3 and parts[1] == "Volumes":   # keep Spotlight from indexing 500 GB of archives
        marker = Path("/", parts[1], parts[2], ".metadata_never_index")
        try:
            marker.touch(exist_ok=True)
        except OSError:
            pass


# ----------------------------------------------------------------------------- where the kit lives

KIT_FOLDER = "TinfoilKit"    # at the top of a drive, or in the home folder
THIS = "this Mac" if sys.platform == "darwin" else "this PC" if sys.platform == "win32" else "this computer"


def drive_bases() -> List[Path]:
    """Where plugged-in drives show up (KIT_DRIVES: that folder instead, for tests)."""
    if os.environ.get("KIT_DRIVES"):
        return [Path(os.environ["KIT_DRIVES"])]
    if sys.platform == "win32":
        return []    # drive letters instead: win_drives()
    if sys.platform == "darwin":
        return [Path("/Volumes")]
    user = os.environ.get("USER", "")
    return [Path("/media", user), Path("/run/media", user)] if user else []


def win_volume(path: Path) -> Tuple[str, str]:
    """A Windows drive's label and format ("exFAT", "NTFS", "FAT32"), or "" for what can't be read."""
    import ctypes
    letter = os.path.splitdrive(os.path.abspath(path))[0]
    label, fs = ctypes.create_unicode_buffer(261), ctypes.create_unicode_buffer(261)
    if not ctypes.windll.kernel32.GetVolumeInformationW(letter + "\\", label, 261, None, None, None, fs, 261):
        return "", ""
    return label.value, fs.value


def win_drives() -> List[Path]:
    """The drive letters of disks plugged into this PC, internal or USB, but not the one with the home folder.
    No network drives or CD drives, nor disks Windows can't read (locked by BitLocker, or empty card readers)."""
    import ctypes
    k32, home = ctypes.windll.kernel32, os.path.splitdrive(str(Path.home()))[0].upper()
    mask = k32.GetLogicalDrives()
    roots = [Path(f"{chr(65 + i)}:\\") for i in range(26) if mask >> i & 1 and f"{chr(65 + i)}:" != home]
    return [r for r in roots if k32.GetDriveTypeW(str(r)) in (2, 3) and win_volume(r)[1]]    # removable, fixed


def drive_format(path: Path) -> str:
    """A drive's format as the system names it ("ExFAT", "MS-DOS (FAT32)", "exfat", "vfat"...), or "" if unknown."""
    if sys.platform == "win32":
        return win_volume(path)[1]
    if sys.platform == "darwin":
        try:
            info = plistlib.loads(subprocess.run(["diskutil", "info", "-plist", str(path)],
                                                 capture_output=True, timeout=30).stdout)
        except (OSError, ValueError, subprocess.SubprocessError):
            return ""
        return info.get("FilesystemUserVisibleName") or info.get("FilesystemName") or ""
    try:
        mounts = Path("/proc/mounts").read_text().splitlines()
    except OSError:
        return ""
    where, best, fs = str(path.resolve()), "", ""
    for line in mounts:
        f = line.split()
        mnt = f[1].replace("\\040", " ") if len(f) > 2 else ""
        if mnt and (where == mnt or where.startswith(mnt.rstrip("/") + "/")) and len(mnt) >= len(best):
            best, fs = mnt, f[2]
    return fs


def drive_problem(fs: str) -> str:
    """Why the kit can't live on a drive of this format, or "" if it can."""
    f = fs.lower()
    if "fat" in f.replace("exfat", "") or "ms-dos" in f or f == "msdos":
        return f"it's formatted as {fs}, which can't hold files over 4 GB, and the AI models and books are bigger"
    if sys.platform == "darwin" and ("ntfs" in f or "windows" in f):
        return f"it's formatted as {fs}, which a Mac can read but can't save to"
    return ""


def list_drives() -> List[Dict[str, Any]]:
    """The drives plugged in: folder, name, format, free bytes, whether a kit is there, and why the kit can't go there,
    if it can't. Drives that can't be written to (installer disk images, backups) are left out, unless their format is
    the reason, so SETUP can say why those won't do. In /Volumes the Mac's own disk is a link to /."""
    found = []
    for base in drive_bases() or [None]:
        try:
            folders = sorted(base.iterdir()) if base else win_drives() if sys.platform == "win32" else []
        except OSError:
            continue
        for v in folders:
            if v.name.startswith(".") or v.is_symlink() or not v.is_dir():
                continue
            fs = drive_format(v)
            problem = drive_problem(fs)
            if not problem and not os.access(v, os.W_OK):
                continue
            try:
                free = shutil.disk_usage(v).free
            except OSError:
                continue
            found.append({"path": str(v), "name": drive_name(v), "format": fs or "unknown", "free_bytes": free,
                          "problem": problem or None, "has_kit": (v / KIT_FOLDER / "kit").is_file()})
    return found


def drive_name(path: Path) -> str:
    """The name of the drive a folder is on."""
    if sys.platform == "win32" and not os.environ.get("KIT_DRIVES"):
        letter = os.path.splitdrive(os.path.abspath(path))[0]
        label = win_volume(path)[0]
        return f"{label} ({letter})" if label else letter
    for base in drive_bases():
        try:
            return path.relative_to(base).parts[0]
        except (ValueError, IndexError):
            continue
    while not os.path.ismount(path) and path.parent != path:
        path = path.parent
    return path.name or str(path)


def where_is(folder: Path) -> str:
    """"this Mac" or "the drive NAME", for messages."""
    if not any(b == folder or b in folder.parents for b in drive_bases()) and on_this_computer(folder):
        return THIS
    return f"the drive {drive_name(folder)}"


def copy_code(src: Path, dst: Path) -> None:
    """Copy files and folders with their contents and permissions, never extended attributes (no ._ files on exFAT,
    no "from the internet" marks) or timestamps, which some drive formats refuse."""
    if src.is_dir():
        dst.mkdir()
        for c in sorted(src.iterdir()):
            if not c.name.startswith("._"):
                copy_code(c, dst / c.name)
    else:
        shutil.copyfile(src, dst)
        with contextlib.suppress(OSError):
            shutil.copymode(src, dst)


def place_kit(root: Path, dest: Path) -> Tuple[Path, str]:
    """Put the kit at dest, ready to set up there. Returns its folder and what happened, in words. A fresh download is
    moved there, so there's one copy: renamed on the same disk, copied to another (the code, never downloads). A git
    checkout is a developer's: it stays put, or is copied to another disk. A kit already at dest is used as it is.
    On Windows it's always a copy, since Windows won't rename or delete a folder a running script is in."""
    git = (root / ".git").exists()
    if not dest.parent.is_dir():
        raise RuntimeError(f"{dest.parent} isn't there. If it's a drive, is it plugged in?")
    if dest == root or dest.parent == root or (git and root.stat().st_dev == dest.parent.stat().st_dev):
        (root / ".kit").mkdir(exist_ok=True)
        return root, ""
    if root in dest.parents:
        raise RuntimeError(f"The kit can't go inside its own folder ({dest}).")
    where = where_is(dest.parent)
    if dest.exists():
        if (dest / "kit").is_file() and (dest / "tools" / "kit.py").is_file():
            (dest / ".kit").mkdir(exist_ok=True)
            return dest, f"There's already a Tinfoil Kit on {where} ({dest}). Carrying on with that one."
        raise RuntimeError(f"There's already a folder called {dest.name} on {where} ({dest}), and it isn't a "
                           "Tinfoil Kit.\nRename it or move it somewhere else, then double-click SETUP again.")
    if not git and sys.platform != "win32" and root.stat().st_dev == dest.parent.stat().st_dev:
        try:
            root.rename(dest)
        except OSError:
            pass    # copy it instead
        else:
            (dest / ".kit").mkdir(exist_ok=True)
            return dest, f"Moved the kit to {where}: {dest}"
    partial = dest.with_name(dest.name + ".partial")
    shutil.rmtree(partial, ignore_errors=True)
    try:
        partial.mkdir()
    except OSError as e:
        why = f"Couldn't save anything on {where} ({e.strerror or e})."
        if sys.platform == "darwin":
            why += ("\nIf macOS asked whether Terminal may use files there, it needs a yes. Open System Settings > "
                    "Privacy & Security > Files and Folders, turn on Removable Volumes under Terminal, then try again.")
        raise RuntimeError(why) from None
    try:
        for f in sorted(root.iterdir()):
            if f.name not in KEEP - {".git"} and not f.name.startswith("._"):
                copy_code(f, partial / f.name)
        partial.rename(dest)
    except OSError as e:
        shutil.rmtree(partial, ignore_errors=True)
        raise RuntimeError(f"Copying the kit to {where} stopped partway ({e.strerror or e}). "
                           "Is the drive full, or was it unplugged?") from None
    (dest / ".kit").mkdir(exist_ok=True)
    if git or root == Path.home() or sys.platform == "win32":
        return dest, f"Copied the kit to {where}: {dest}. Use that copy from now on."
    shutil.rmtree(root, ignore_errors=True)    # the download isn't needed now that the kit is in its place
    return dest, f"Moved the kit to {where}: {dest}"


def drive_bytes(rec: Dict[str, Any]) -> int:
    """What an item in state.json takes up on disk."""
    return sum(f.get("size", 0) for f in rec.get("files", {}).values()) + rec.get("unpacked_size", 0)


def write_inventory(root: Path, state: Dict[str, Any]) -> None:
    lines = ["# What's in this kit", "",
             f"Last updated: {state.get('last_sync', 'never')}  ",
             "Generated by `./kit sync`. Start everything by double-clicking Open Tinfoil Kit.", ""]
    for section in SECTIONS:
        rows = [(k.split("/", 1)[1], v) for k, v in sorted(state["items"].items()) if k.startswith(section + "/")]
        if not rows:
            continue
        lines += [f"## {section.capitalize()}", "", "| Item | Version | Size | Notes |", "|---|---|---|---|"]
        for ident, v in rows:
            size = drive_bytes(v)
            lines.append(f"| {ident} | {v.get('version', '')} | {fmt_size(size) if size else ''} | "
                         f"{(v.get('note') or '').replace('|', '/')} |")
        lines.append("")
    (root / "INVENTORY.md").write_text("\n".join(lines), encoding="utf-8")


@contextlib.contextmanager
def keep_awake():
    """Keep the computer from sleeping (the screen may) through hours of downloads. Ends when this process does."""
    child = None
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)    # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    else:
        pid = str(os.getpid())
        cmd = (["caffeinate", "-i", "-w", pid] if sys.platform == "darwin" else
               ["systemd-inhibit", "--what=idle:sleep", "--who=Tinfoil Kit", "--why=Downloading the kit",
                "tail", f"--pid={pid}", "-f", os.devnull])
        if shutil.which(cmd[0]):
            with contextlib.suppress(OSError):    # no stdin, so it can't stop to ask for a password
                child = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL)
    try:
        yield
    finally:
        if child:
            child.terminate()
        if sys.platform == "win32":
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)


class Lock:
    def __init__(self, root: Path):
        self.path = root / ".kit" / "lock"
        self.fh = None

    def __enter__(self) -> "Lock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "a")    # not "w": Windows won't empty a file another sync has locked
        try:
            if os.name == "nt":
                import msvcrt
                try:
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
                except PermissionError:
                    raise BlockingIOError from None
            else:
                import fcntl
                fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            die("another ./kit sync is already running on this kit")
        except (OSError, ImportError):
            pass  # filesystem without locking support: carry on
        return self

    def __exit__(self, *exc: Any) -> None:
        if self.fh:
            self.fh.close()


# ----------------------------------------------------------------------------- self-update

# ./kit update never writes here, whatever a release holds: the downloads, the kit's state and logs, a git checkout.
KEEP = {".git", ".kit", "bin", "installers", "library", "logs", "maps", "models", "INVENTORY.md"}
NEEDED = ("kit", "kit.json", "SETUP.command", "Open Tinfoil Kit.command", "UNINSTALL.command", "tools/kit.py", "tools/launch.sh",
          "tools/portal.html", "tools/share.py")
MISSING = object()
# A release is a tarball the maintainer built and signed on their own computer (.github/release.sh), so taking over
# the kit's GitHub account isn't enough to put code on every drive. tools/release-signers holds the keys a drive
# accepts, and each release brings the next copy of it: a new key arrives signed by the old one.
RELEASE_NAMESPACE = "tinfoilkit-release"
REPORT = "https://github.com/tudor-city-ventures/tinfoilkit/security"


def item_key(x: Any) -> Any:
    return (x.get("id") or x.get("zim")) if isinstance(x, dict) else None


def keyed(x: Any) -> bool:
    """A kit.json list of items (models, books...): these merge item by item."""
    return isinstance(x, list) and bool(x) and all(item_key(i) for i in x)


def merge3(base: Any, ours: Any, theirs: Any) -> Any:
    """Three-way merge of kit.json values: this kit's changes (base to ours) win, and the new version's
    (base to theirs) apply everywhere else. MISSING stands for a key or item that isn't there."""
    if ours == base:
        return theirs
    if theirs == base or theirs == ours:
        return ours
    if isinstance(ours, dict) and isinstance(theirs, dict):
        b = base if isinstance(base, dict) else {}
        merged = {}
        for k in [*theirs, *(k for k in ours if k not in theirs)]:
            v = merge3(b.get(k, MISSING), ours.get(k, MISSING), theirs.get(k, MISSING))
            if v is not MISSING:
                merged[k] = v
        return merged
    if keyed(ours) and keyed(theirs):
        b = {item_key(i): i for i in base} if keyed(base) else {}
        o, t = {item_key(i): i for i in ours}, {item_key(i): i for i in theirs}
        items = []
        for k in [*t, *(k for k in o if k not in t)]:
            if k not in t and k in b and k in o and {**o[k], "enabled": 0} == {**b[k], "enabled": 0}:
                continue    # the new version dropped it (gone from its source): being switched on or off doesn't keep it
            v = merge3(b.get(k, MISSING), o.get(k, MISSING), t.get(k, MISSING))
            if v is not MISSING:
                items.append(v)
        return items
    return ours


def merge_kit_json(root: Path, theirs_text: str) -> Tuple[str, str]:
    """This kit's kit.json with the new version's changes, and a line on what happened. The copy of kit.json
    that came with the kit's current version (site/kit.json) shows which parts were changed here."""
    mine = root / "kit.json"
    if not mine.exists():
        return theirs_text, "kit.json is the new version's."
    ours_text = mine.read_text(encoding="utf-8")
    try:
        ours = json.loads(ours_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"kit.json has a syntax error on line {e.lineno}, column {e.colno}: {e.msg}. "
                         "Fix it, or delete it to start from the standard list, then run this again") from None
    try:
        base = json.loads((root / "site" / "kit.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ours_text, "kit.json stays exactly as it was (there's no copy of the old version's to compare with)."
    theirs = json.loads(theirs_text)
    merged = merge3(base, ours, theirs)
    text = theirs_text if merged == theirs else json.dumps(merged, indent=2, ensure_ascii=False) + "\n"
    return text, ("kit.json is the new version's, with your changes kept." if ours != base else
                  "kit.json is the new version's.")


# Ed25519 (RFC 8032) and OpenSSH's signature format (PROTOCOL.sshsig), checking only: Python has no Ed25519 of its
# own, and ssh-keygen isn't on every Windows and Linux computer. The tests check the same signatures with ssh-keygen.
ED_P = 2**255 - 19
ED_L = 2**252 + 27742317777372353535851937790883648493
ED_D = -121665 * pow(121666, ED_P - 2, ED_P) % ED_P


def ed_add(a: Tuple[int, ...], b: Tuple[int, ...]) -> Tuple[int, ...]:
    """Add two points in extended coordinates (x, y, z, t)."""
    p, q = (a[1] - a[0]) * (b[1] - b[0]) % ED_P, (a[1] + a[0]) * (b[1] + b[0]) % ED_P
    r, s = 2 * a[3] * b[3] * ED_D % ED_P, 2 * a[2] * b[2] % ED_P
    e, f, g, h = q - p, s - r, s + r, q + p
    return e * f % ED_P, g * h % ED_P, f * g % ED_P, e * h % ED_P


def ed_mul(n: int, a: Tuple[int, ...]) -> Tuple[int, ...]:
    out = (0, 1, 1, 0)
    while n:
        if n & 1:
            out = ed_add(out, a)
        a, n = ed_add(a, a), n >> 1
    return out


def ed_point(b: bytes) -> Optional[Tuple[int, ...]]:
    """Decode a point, or None if these 32 bytes aren't one."""
    y = int.from_bytes(b, "little")
    sign, y = y >> 255, y & ((1 << 255) - 1)
    if len(b) != 32 or y >= ED_P:
        return None
    x2 = (y * y - 1) * pow(ED_D * y * y + 1, ED_P - 2, ED_P) % ED_P
    x = pow(x2, (ED_P + 3) // 8, ED_P)
    if (x * x - x2) % ED_P:
        x = x * pow(2, (ED_P - 1) // 4, ED_P) % ED_P
    if (x * x - x2) % ED_P or (x == 0 and sign):
        return None
    if x & 1 != sign:
        x = ED_P - x
    return x, y, 1, x * y % ED_P


ED_B = ed_point((4 * pow(5, ED_P - 2, ED_P) % ED_P).to_bytes(32, "little"))


def ed25519_ok(key: bytes, msg: bytes, sig: bytes) -> bool:
    a, r, s = ed_point(key), ed_point(sig[:32]), int.from_bytes(sig[32:], "little")
    if a is None or r is None or len(sig) != 64 or s >= ED_L:
        return False
    k = int.from_bytes(hashlib.sha512(sig[:32] + key + msg).digest(), "little") % ED_L
    x1, y1, z1, _ = ed_mul(s, ED_B)
    x2, y2, z2, _ = ed_add(r, ed_mul(k, a))
    return (x1 * z2 - x2 * z1) % ED_P == 0 and (y1 * z2 - y2 * z1) % ED_P == 0


def ssh_strings(b: bytes) -> List[bytes]:
    """Split SSH wire format into its length-prefixed strings."""
    out = []
    while b:
        n = int.from_bytes(b[:4], "big")
        if len(b) < 4 + n:
            raise ValueError("truncated")
        out.append(b[4:4 + n])
        b = b[4 + n:]
    return out


def release_keys(signers: Path) -> List[bytes]:
    """The Ed25519 keys tools/release-signers lists for the kit's releases (ssh-keygen's allowed-signers format)."""
    try:
        text = signers.read_text(encoding="utf-8")
    except OSError:
        return []
    keys = []
    for m in re.finditer(rf"(?m)^{RELEASE_NAMESPACE}\s(?:.*?\s)?ssh-ed25519\s+([A-Za-z0-9+/]+=*)", text):
        with contextlib.suppress(ValueError):
            kind, key = ssh_strings(base64.b64decode(m.group(1)))
            if kind == b"ssh-ed25519" and len(key) == 32:
                keys.append(key)
    return keys


def verify_release(root: Path, data: bytes, sig: bytes) -> None:
    """Refuse a release unless one of this copy's keys signed it, the way ssh-keygen -Y sign does."""
    keys = release_keys(root / "tools" / "release-signers")
    if not keys:
        raise ValueError("this copy of the kit has no release key to check it with (tools/release-signers). "
                         "Download the kit again from tinfoilkit.com")
    try:
        lines = sig.decode("ascii").split()
        blob = base64.b64decode("".join(lines[lines.index("SIGNATURE-----") + 1:lines.index("-----END")]), validate=True)
        key_blob, namespace, reserved, alg, sig_blob = ssh_strings(blob[10:]) if blob[:10] == b"SSHSIG\0\0\0\1" else []
        (kind, key), (sig_kind, raw) = ssh_strings(key_blob), ssh_strings(sig_blob)
    except ValueError:
        raise ValueError(f"its signature file is damaged. Please report it at {REPORT}") from None
    if not (key in keys and kind == sig_kind == b"ssh-ed25519" and namespace == RELEASE_NAMESPACE.encode()
            and alg in (b"sha256", b"sha512")
            and ed25519_ok(key, b"SSHSIG" + b"".join(len(x).to_bytes(4, "big") + x for x in (
                namespace, reserved, alg, hashlib.new(alg.decode(), data).digest())), raw)):
        raise ValueError("it isn't signed with the kit's release key. Someone other than the kit's maintainer may have "
                         f"published it: don't install it by hand, and please report it at {REPORT}")


def unpack_release(data: bytes, dest: Path) -> None:
    """Unpack a GitHub release archive into dest without trusting it: plain files and folders only, all inside
    its one top folder, and nothing for the kit's own folders of downloads (KEEP)."""
    total, top = 0, None
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        for m in tf:
            parts = PurePosixPath(m.name).parts
            if not parts or m.name.startswith("/") or ".." in parts or parts[0] != (top or parts[0]):
                raise ValueError(f"the archive has an unexpected path in it: {m.name}")
            top = parts[0]
            if not (m.isfile() or m.isdir()):
                raise ValueError(f"the archive has a link in it ({m.name}), which an exFAT drive can't hold")
            if len(parts) < 2 or parts[1] in KEEP:
                continue
            path = dest.joinpath(*parts[1:])
            if m.isdir():
                path.mkdir(parents=True, exist_ok=True)
                continue
            total += m.size
            if total > 500 * 10**6:
                raise ValueError("the archive is far bigger than a kit release")
            path.parent.mkdir(parents=True, exist_ok=True)
            with tf.extractfile(m) as src, open(path, "wb") as out:
                shutil.copyfileobj(src, out)
            with contextlib.suppress(OSError):    # exFAT keeps no permissions
                path.chmod(0o755 if m.mode & 0o111 else 0o644)


def check_release(new: Path) -> None:
    """Refuse a release that's incomplete or that this computer couldn't run."""
    missing = [rel for rel in NEEDED if not (new / rel).is_file()]
    if missing:
        raise ValueError(f"the release is missing {', '.join(missing)}")
    if not release_keys(new / "tools" / "release-signers"):
        raise ValueError("it has no release key (tools/release-signers), so the kit could never update again")
    try:
        compile((new / "tools" / "kit.py").read_text(encoding="utf-8"), "tools/kit.py", "exec")
    except SyntaxError as e:
        raise ValueError(f"its tools/kit.py won't run with this computer's Python {platform.python_version()} "
                         f"({e.msg}, line {e.lineno})") from None
    try:
        json.loads((new / "kit.json").read_text(encoding="utf-8"))
    except ValueError as e:
        raise ValueError(f"its kit.json doesn't parse ({e})") from None
    for script in ("kit", "SETUP.command", "Open Tinfoil Kit.command", "UNINSTALL.command", "tools/launch.sh"):
        if shutil.which("bash") and subprocess.run(["bash", "-n", str(new / script)], capture_output=True).returncode:
            raise ValueError(f"its {script} has a syntax error")


def install_release(root: Path, new: Path, old_files: List[str]) -> List[str]:
    """Move the unpacked release over the kit's code (renames on the same disk, so it takes a moment), then
    remove the files the last update installed that this version no longer has. Returns the files installed."""
    files = sorted(p.relative_to(new).as_posix() for p in new.rglob("*") if p.is_file())
    # kit.py goes last: if this stops partway, the old kit.py (which knows it's older) runs the retry.
    files.sort(key=lambda rel: rel == "tools/kit.py")
    for rel in files:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        os.replace(new / rel, root / rel)
    for rel in sorted(set(old_files) - set(files)):
        if rel != "kit.json" and PurePosixPath(rel).parts[0] not in KEEP:
            (root / rel).unlink(missing_ok=True)
    return files


# ----------------------------------------------------------------------------- commands

def cmd_plan(root: Path, args: argparse.Namespace) -> None:
    cfg, state = load_config(root), load_state(root)
    if args.json:
        return plan_json(root, cfg, args.only)
    items = build_plan(root, cfg, state, args.only, args.essentials or cfg["settings"].get("essentials_only") is True)
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


PINS_README = ["The exact build of each program this version of the kit installs, and its SHA-256. ./kit pins writes it,",
               "and every release carries it, signed with the rest. To take each program's newest build instead, set",
               "\"pin_programs\": false in kit.json's settings."]


def cmd_pins(root: Path, args: argparse.Namespace) -> None:
    """Write tools/pins.json: the newest build of every program kit.json lists, for every system, with its SHA-256 from
    its publisher, or from downloading it where the publisher gives none. Run before a release (a weekly workflow
    does it). A program that can't be looked up keeps its old pin, and so does one whose file changed under the same
    version, which also fails the command: a publisher shouldn't replace a file it has published."""
    cfg = json.loads(json.dumps(load_config(root)))
    cfg["settings"]["pin_programs"] = False
    cfg["models"], cfg["library"] = [], []
    for entry in cfg["runtimes"] + cfg["extras"]:
        entry["enabled"] = True
    cfg["maps"] = {**(cfg.get("maps") or {}), "enabled": True}
    path = root / "tools" / "pins.json"
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = {}
    pins, problems, changed = {}, [], []
    # the plan's own lookup, so Photon is the release that opens the newest address database
    for item in build_plan(root, cfg, {"version": 1, "items": {}}, []):
        if not item.enabled or item.cfg.get("type") not in PINNED_TYPES:
            continue
        was = old.get(item.id) if isinstance(old.get(item.id), dict) else {}
        try:
            if item.error or not item.files:
                raise ValueError(item.error or "nothing to download")
            f = item.files[0]
            if item.cfg.get("type") == "github_archive":    # GitHub can repack its archives, so only the commit is pinned
                pins[item.id] = {"version": f.url.rsplit("/", 1)[-1].split(".")[0]}
            else:
                digest = f.sha256 or (fetch_sha256_sidecar(f.url) if f.sha256_sidecar else None)
                if not digest and was.get("version") == item.version and was.get("sha256"):
                    digest = was["sha256"]    # pinned before and its publisher gives no SHA-256: no need to download it again
                if not digest:
                    data = http_get(f.url, timeout=900)
                    for algo, want in f.checks.items():
                        if hashlib.new(algo, data).hexdigest() != want.lower():
                            raise ValueError(f"the download doesn't match its published {algo}")
                    digest = hashlib.sha256(data).hexdigest()
                if was.get("version") == item.version and was.get("sha256", digest).lower() != digest.lower():
                    changed.append(item.id)
                    raise ValueError(f"the file published as {item.version} changed after it was pinned. Find out why "
                                     "before you pin it again: delete its entry in tools/pins.json and run ./kit pins")
                pins[item.id] = {"version": item.version, "sha256": digest.lower()}
        except (HttpError, ValueError) as e:
            problems.append(f"  {item.id}: {e}")
            if was:
                pins[item.id] = was
        if was.get("version") != pins.get(item.id, {}).get("version"):
            log(f"  {item.id}: {was.get('version', 'not pinned')} -> {pins.get(item.id, {}).get('version', 'not pinned')}")
    path.write_text(json.dumps({"_readme": PINS_README, **dict(sorted(pins.items()))}, indent=1) + "\n", encoding="utf-8")
    log(f"Pinned {len(pins)} program builds in tools/pins.json.")
    if problems:
        log("Couldn't pin these, so each keeps the pin it had, if any:\n" + "\n".join(problems))
    if changed:
        sys.exit(f"A publisher replaced a file it had already published ({', '.join(changed)}). Don't release the kit "
                 "until you know why.")


def cmd_sync(root: Path, args: argparse.Namespace) -> None:
    global LOG_FILE
    (root / "logs").mkdir(exist_ok=True)
    LOG_FILE = root / "logs" / f"sync-{dt.date.today().isoformat()}.log"
    log(f"\n===== sync started {now_iso()} =====")
    with Lock(root), keep_awake():
        prepare_folder(root)
        cfg, state = load_config(root), load_state(root)
        items = build_plan(root, cfg, state, args.only,
                           args.essentials or cfg["settings"].get("essentials_only") is True)
        part = args.only or args.essentials    # just this once: the next full sync gets the rest
        print_plan(root, items, state, cfg)
        if offline(items):
            sys.exit(1)
        todo = sorted([i for i in items if i.enabled and i.status in ("new", "update")],
                      key=lambda i: (i.priority, i.need_bytes(root)))
        if todo and not args.yes and sys.stdin.isatty():
            if input(f"\nDownload {len(todo)} item(s) now? [Y/n] ").strip().lower() not in ("", "y", "yes"):
                return
        if not part:
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
        if not part:
            drop_replaced_wikipedias(root, state, items)
        if not failures and not errors and not part:
            state["last_sync"] = now_iso()
        save_state(root, state)
        write_inventory(root, state)
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
            log("\nNow run ./kit test to check that everything starts.")
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
    state = load_state(root)
    usage = shutil.disk_usage(root)
    total = 0
    for section in SECTIONS:
        rows = [(k, v) for k, v in sorted(state["items"].items()) if k.startswith(section + "/")]
        if rows:
            log(f"\n[{section}]")
        for key, v in rows:
            size = drive_bytes(v)
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
    disk = "this computer's disk" if on_this_computer(root) else "the drive"
    log(f"\nKit content: {fmt_size(total)}.  Free on {disk}: {fmt_size(usage.free)} of {fmt_size(usage.total)}.")
    if last:
        age = (dt.datetime.now() - dt.datetime.fromisoformat(last)).days
        log(f"Last complete sync: {last[:10]} ({age} days ago). To get newer versions, run SETUP.command again, "
            "or ./kit update and then ./kit sync, whenever you like.")
    else:
        log("Never fully synced. Run ./kit sync.")
    if state.get("kit_version"):
        log(f"Kit version: {state['kit_version']}.")


def estimate_gb(root: Path, cfg: Dict[str, Any], essentials: Optional[bool] = None) -> int:
    """About how many GB the switched-on items need, from the sizes the kit builder lists (site/sources.json), plus
    about 1 GB of programs. Needs no internet, so SETUP can say how much room the kit needs before choosing where.
    essentials: only those (see essential()); None goes by kit.json's essentials_only."""
    if essentials is None:
        essentials = cfg["settings"].get("essentials_only") is True
    fit = fit_report(root, cfg, load_state(root)) if essentials else {}
    try:
        listed = json.loads((root / "site" / "sources.json").read_text(encoding="utf-8"))["sources"]
        sizes = {s["id"]: s.get("bytes") or 0 for s in listed}
    except (OSError, ValueError, KeyError, TypeError):
        sizes = {}
    # a place's maps, and Wikipedia in other languages, are sized in tools/regions.json
    for lang in regions()["languages"].values():
        sizes.setdefault(lang["zim"], lang.get("mb", 0) * 1e6)
    maps = cfg.get("maps") or {}
    r = region(maps.get("region"))
    if r and not any(k in maps for k in ("detail_bbox", "routing_osm_pbf", "geocoder_country")):
        wide = essentials and r.get("addresses_wide")     # see essential()
        mb = {k: v for k, v in (r.get("mb") or {}).items() if not (wide and k == "addresses")}
        sizes["maps"] = sum(mb.values()) * 1e6 + 0.1 * GB    # plus the map viewer, fonts and icons
    on = [m["id"] for m in cfg.get("models", [])
          if m.get("enabled", True) and (not essentials or m["id"] in (fit["runs"], fit["smallest"]))]
    on += [z["zim"] for z in cfg.get("library", [])
           if z.get("enabled", True) and (not essentials or int(z.get("priority", 2)) <= 1)]
    if maps_settings(cfg)["enabled"]:
        on.append("maps")
    return math.ceil((sum(sizes.get(i, 0) for i in on) + GB) / GB)


def cmd_estimate(root: Path, args: argparse.Namespace) -> None:
    print(estimate_gb(root, load_config(root), True if args.essentials else None))


def space_at(path: Path, root: Path, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """How the kit would fit at path (its folder, which may not exist yet): the disk's free and total bytes, what the
    kit keeps free there and what a comfortable install leaves, the full kit's size and the essentials', and for each
    of those "fits" (leaving that comfortable amount), "tight" (fits, but leaves less) or "no"."""
    at = path
    while not at.exists() and at != at.parent:
        at = at.parent
    usage = shutil.disk_usage(at)
    keep, leave = keep_free(at, cfg), leave_free(at, cfg)
    have = 0
    with contextlib.suppress(OSError):
        if path.resolve() == root.resolve():    # the kit's own folder: what's downloaded already counts
            have = sum(drive_bytes(v) for v in load_state(root)["items"].values())
    full = max(0, estimate_gb(root, cfg, False) * GB - have)
    ess = max(0, estimate_gb(root, cfg, True) * GB - have)

    def verdict(need: int) -> str:
        return "fits" if usage.free - need >= leave else "tight" if usage.free - need >= keep else "no"
    return {"path": str(path), "free_bytes": usage.free, "total_bytes": usage.total, "keeps_free_bytes": int(keep),
            "leaves_free_bytes": int(leave), "full_bytes": full, "essentials_bytes": ess,
            "full": verdict(full), "essentials": verdict(ess)}


def cmd_space(root: Path, args: argparse.Namespace) -> None:
    """One tab-separated line for scripts: the full kit's verdict, the essentials', then GB free, GB in all, GB the
    full kit and the essentials need, and GB a comfortable install leaves free."""
    sp = space_at(Path(os.path.abspath(os.path.expanduser(args.path))), root, load_config(root))
    if args.json:
        print(json.dumps(sp, indent=2))
        return
    print("\t".join([sp["full"], sp["essentials"], str(sp["free_bytes"] // GB), str(round(sp["total_bytes"] / GB)),
                     str(math.ceil(sp["full_bytes"] / GB)), str(math.ceil(sp["essentials_bytes"] / GB)),
                     str(math.ceil(sp["leaves_free_bytes"] / GB))]))


def cmd_essentials(root: Path, args: argparse.Namespace) -> None:
    if args.action:
        set_setting(root, "essentials_only", True if args.action == "on" else None)
    cfg = load_config(root)
    if cfg["settings"].get("essentials_only") is True:
        log(f"Just the essentials (about {estimate_gb(root, cfg)} GB): the programs, the map, the most important "
            "books, and the AI this computer runs plus the smallest. To get everything: ./kit essentials off")
    else:
        log(f"Everything switched on in kit.json (about {estimate_gb(root, cfg)} GB). "
            "To get just the essentials: ./kit essentials on")


# ----------------------------------------------------------------------------- the AI models this computer can run

def memory_bytes() -> int:
    """This computer's memory, or 0 if it can't tell. KIT_MEMORY_MB stands in for it, as in tools/launch.sh."""
    if os.environ.get("KIT_MEMORY_MB", "").isdigit():
        return int(os.environ["KIT_MEMORY_MB"]) * 1048576
    try:
        if sys.platform == "darwin":
            return int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout)
        if sys.platform == "win32":
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [("size", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [(n, ctypes.c_ulonglong) for n in
                            ("total", "avail", "page", "page_avail", "virtual", "virtual_avail", "extended")]
            s = Status()
            s.size = ctypes.sizeof(Status)
            return s.total if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)) else 0
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (OSError, ValueError, AttributeError):
        return 0


def model_sizes(root: Path, cfg: Dict[str, Any]) -> Dict[str, int]:
    """Each model's download size, from the kit builder's list (site/sources.json), else the "~N GB" in its note."""
    try:
        listed = {s["id"]: int(s.get("bytes") or 0)
                  for s in json.loads((root / "site" / "sources.json").read_text(encoding="utf-8"))["sources"]}
    except (OSError, ValueError, KeyError, TypeError):
        listed = {}
    sizes = {}
    for m in cfg.get("models", []):
        noted = re.search(r"~(\d+(?:\.\d+)?) ?GB", m.get("note", ""))
        sizes[m["id"]] = listed.get(m["id"]) or (int(float(noted.group(1)) * GB) if noted else 0)
    return sizes


def fits(size: int, memory: int) -> bool:
    """A model may take 60% of the memory, leaving the rest for everything else (tools/launch.sh's rule too)."""
    return not memory or not size or size <= memory * 0.6


def memory_for(size: int) -> int:
    """The smallest usual amount of memory, in GB, that runs a model of this size."""
    need = size / 0.6 / 2**30
    return next((g for g in (8, 16, 24, 32, 48, 64, 96, 128, 192, 256, 512) if g >= need), math.ceil(need))


def fit_report(root: Path, cfg: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    """Which model the AI starts with on this computer (tools/launch.sh picks the same way: the default model if it
    fits, else the biggest that does, else the smallest), the switched-on models it can't run that aren't downloaded
    yet, and the ones switched off for that on a computer with less memory that this one runs. Those are listed in
    kit.json, not .kit/state.json, so the list moves with the kit when SETUP puts it in its place."""
    memory, sizes = memory_bytes(), model_sizes(root, cfg)
    default = cfg["settings"].get("default_model")
    models = [{"id": m["id"], "bytes": sizes[m["id"]], "fits": fits(sizes[m["id"]], memory),
               "needs_memory_gb": memory_for(sizes[m["id"]]) if sizes[m["id"]] else None,
               "enabled": m.get("enabled", True)} for m in cfg.get("models", [])]
    on = [m for m in models if m["enabled"]]
    smallest = min(on, key=lambda m: m["bytes"] or math.inf, default=None)
    runs = (next((m for m in on if m["id"] == default and m["fits"]), None)
            or max((m for m in on if m["fits"]), key=lambda m: m["bytes"], default=None) or smallest)
    return {"memory_bytes": memory, "runs": runs and runs["id"], "smallest": smallest and smallest["id"],
            "models": models,
            "too_big": [m["id"] for m in on if not m["fits"] and m is not runs and f"models/{m['id']}" not in state["items"]],
            "fits_now": [m["id"] for m in models if not m["enabled"] and m["fits"]
                         and m["id"] in cfg["settings"].get("models_off_for_memory", [])]}


def switch_models(root: Path, ids: List[str], on: bool) -> None:
    """Switch models on or off in kit.json, changing only their "enabled" so the file keeps its layout."""
    path = root / "kit.json"
    text = path.read_text(encoding="utf-8")
    cfg = json.loads(text)
    for m in cfg["models"]:
        if m.get("id") in ids and on:
            m.pop("enabled", None)
        elif m.get("id") in ids:
            m["enabled"] = False
    start = re.search(r'"models"\s*:\s*\[', text)
    for ident in ids:
        hit = re.compile(r'\{[^{}]*"id"\s*:\s*' + re.escape(json.dumps(ident)) + r'[^{}]*\}').search(text, start.end()) \
            if start else None
        if not hit:
            continue
        obj = new = hit.group(0)
        if on:
            new = re.sub(r',\s*"enabled"\s*:\s*false\b|"enabled"\s*:\s*false\s*,\s*', "", obj, count=1)
        elif re.search(r'"enabled"\s*:\s*true\b', obj):
            new = re.sub(r'"enabled"\s*:\s*true\b', '"enabled": false', obj, count=1)
        else:
            sep = re.search(r',(\s*)"', obj)
            gap = sep.group(1) if sep else " "
            note = re.search(r'"note"\s*:', obj)
            if note:
                new = f'{obj[:note.start()]}"enabled": false,{gap}{obj[note.start():]}'
            else:
                body = obj[:-1].rstrip()
                new = f'{body},{gap}"enabled": false{obj[len(body):]}'
        text = text[:hit.start()] + new + text[hit.end():]
    if json.loads(text) != cfg:    # a layout this doesn't know: write it plainly
        text = json.dumps(cfg, indent=2, ensure_ascii=False) + "\n"
    tmp = path.with_name("kit.json.partial")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def read_line() -> str:
    """One answer from stdin, read a byte at a time: a script feeding SETUP its answers from a file or pipe keeps the
    lines after it for the prompts that come later (Python's own buffered stdin would read ahead and take them)."""
    said = b""
    with contextlib.suppress(OSError):
        while True:
            c = os.read(0, 1)
            if not c or c == b"\n":
                break
            said += c
    return said.decode(errors="replace").strip()


def names(ids: List[str]) -> str:
    return ids[0] if len(ids) == 1 else ", ".join(ids[:-1]) + " and " + ids[-1]


def cmd_fit(root: Path, args: argparse.Namespace) -> None:
    """--ask reads the answers from stdin even when it isn't a terminal, so SETUP's tests can answer."""
    cfg, state = load_config(root), load_state(root)
    fit = fit_report(root, cfg, state)
    if args.json:
        print(json.dumps(fit, indent=2))
        return
    if not fit["runs"]:
        log("No AI model is switched on in kit.json.")
        return
    memory, this = fit["memory_bytes"], THIS[0].upper() + THIS[1:]
    if not memory:
        log(f"\nThe kit can't tell how much memory {THIS} has. Its AI will be {fit['runs']} if that fits.")
        return

    def answer(question: str, default: bool) -> bool:
        print(f"\n{question} {'[Y/n]' if default else '[y/N]'} ", end="", flush=True)
        said = read_line().lower()
        return default if not said else said in ("y", "yes")

    def downloads(ids: List[str]) -> str:
        return fmt_size(sum(m["bytes"] for m in fit["models"] if m["id"] in ids)) + " of downloads"

    gb = f"{this} has {round(memory / 2**30)} GB of memory"
    back = fit["fits_now"]
    if back:
        log(f"\n{gb}. It can run {names(back)}, skipped before on a computer with less memory ({downloads(back)}).")
        if args.restore or (args.ask and answer("Download them now?", True)):
            switch_models(root, back, on=True)
            off = sorted(set(cfg["settings"].get("models_off_for_memory", [])) - set(back))
            set_setting(root, "models_off_for_memory", off or None)
            log("Switched them back on.")
            cfg = load_config(root)
            fit = fit_report(root, cfg, state)
        elif not args.ask:
            log("To get them: ./kit fit --restore")
        log(f"Its AI will be {fit['runs']}.")
    else:
        log(f"\n{gb}, so its AI will be {fit['runs']}.")
    if not next(m for m in fit["models"] if m["id"] == fit["runs"])["fits"]:
        log("That's the smallest, and it still needs most of the memory: close other apps before asking it something.")
    big = fit["too_big"]
    if not big:
        return
    log(f"It can't run {names(big)}: {'it needs' if len(big) == 1 else 'they need'} "
        f"{min(m['needs_memory_gb'] for m in fit['models'] if m['id'] in big)} GB of memory or more ({downloads(big)}).")
    if not on_this_computer(root):
        log("A computer with more memory could, with this drive plugged in.")
    if args.skip or (args.ask and not answer("Download them anyway?", False)):
        switch_models(root, big, on=False)
        set_setting(root, "models_off_for_memory", sorted(set(cfg["settings"].get("models_off_for_memory", [])) | set(big)))
        log("Skipped them. On a computer with more memory, SETUP offers them again.")
    elif not args.ask:
        log("To skip them: ./kit fit --skip")
# ----------------------------------------------------------------------------- where you live

def fold(s: str) -> str:
    """Lower case, without accents or punctuation, for matching what someone typed."""
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def find_regions(text: str) -> List[Dict[str, Any]]:
    """The places that best match what someone typed: exact names (or other names: "UK", "Bavaria", a big town) if
    any, else names that start with it, else names with a word that starts with it, else names that contain it.
    Nothing typed: all of them."""
    q = fold(text)
    if not q:
        return list(regions()["regions"])
    found = []
    for r in regions()["regions"]:
        keys = [fold(k) for k in [r["name"], r["id"], *r.get("also", []), *r["name"].split(": ")[1:]]]
        if q in keys:
            rank = 0
        elif any(k.startswith(q) for k in keys):
            rank = 1
        elif any(f" {q}" in f" {k}" for k in keys):
            rank = 2
        elif len(q) > 2 and any(q in k for k in keys):
            rank = 3
        else:
            continue
        found.append((rank, r))
    best = min((rank for rank, _ in found), default=None)
    return [r for rank, r in found if rank == best]


def wikipedia_langs(cfg: Dict[str, Any]) -> List[str]:
    """The languages of the Wikipedias switched on in kit.json."""
    return [m.group(1) for z in cfg.get("library", []) if z.get("enabled", True)
            for m in [WIKIPEDIA_RE.match(z.get("zim", ""))] if m]


def lang_names(codes: List[str]) -> str:
    names = [regions()["languages"].get(c, {}).get("name", c) for c in codes]
    return ", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else "".join(names)


def language_choices(r: Dict[str, Any]) -> List[Tuple[List[str], str, int]]:
    """Wikipedia's languages to offer for a place: each of its own, English, and its first two together. A small
    Wikipedia (under 1 GB) comes only with another, so nobody swaps English for a few thousand articles by mistake.
    Each is (codes, label, GB)."""
    langs = regions()["languages"]
    codes = [c for c in r.get("langs", []) if c in langs]
    if "en" in langs and "en" not in codes:
        codes.append("en")
    picks = [[c] for c in codes if c == "en" or langs[c].get("mb", 0) >= 1000] + ([codes[:2]] if len(codes) > 1 else [])
    out = []
    for p in picks:
        if len(p) == 1:
            name, native = langs[p[0]]["name"], langs[p[0]].get("native", "")
            label = f"{name} ({native})" if native and native != name else name
        else:
            label = lang_names(p)
        out.append((p, label, max(1, round(sum(langs[c].get("mb", 0) for c in p) / 1000))))
    return out


def describe_region(cfg: Dict[str, Any]) -> str:
    m = maps_settings(cfg)
    r = region((cfg.get("maps") or {}).get("region"))
    wiki = wikipedia_langs(cfg)
    where = m["label"] if r else f"{m['label']} (set by hand in kit.json)"
    maps = f"Maps are for {where}" if m["enabled"] else "Maps are switched off"
    return f"{maps}, and Wikipedia is in {lang_names(wiki)}." if wiki else f"{maps}, with no Wikipedia."


def set_region(root: Path, r: Dict[str, Any], wiki: Optional[List[str]]) -> Dict[str, Any]:
    """Point kit.json's maps at a place, and swap its Wikipedia for the languages given (None: leave it)."""
    path = root / "kit.json"
    cfg = load_config(root)
    raw = json.loads(path.read_text(encoding="utf-8"))
    old = raw.get("maps") or {}
    maps = {"enabled": old.get("enabled", True), "region": r["id"]}
    maps.update({k: v for k, v in old.items() if k not in maps and k not in REGION_KEYS})
    raw["maps"] = maps
    if wiki is not None:
        langs = regions()["languages"]
        lib = raw.get("library", [])
        was = [i for i, z in enumerate(lib) if WIKIPEDIA_RE.match(z.get("zim", ""))]
        # the new ones keep the old one's settings (priority, refresh_days)
        keep = {k: v for k, v in lib[was[0]].items() if k not in ("zim", "note")} if was else {"priority": 2}
        new = [{"zim": langs[c]["zim"], **keep,
                "note": f"All of {langs[c]['name']} Wikipedia{' with images' if langs[c].get('pictures') else ''}"
                        f" (~{max(1, round(langs[c].get('mb', 0) / 1000))} GB)"} for c in wiki]
        at = was[0] if was else len(lib)
        lib = [z for i, z in enumerate(lib) if i not in was]
        lib[at:at] = new
        raw["library"] = lib
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return {**cfg, **raw}


def cmd_region(root: Path, args: argparse.Namespace) -> None:
    """Where you live: sets the map area, the road data for directions, the address search, home, units and the
    language Wikipedia comes in. SETUP and the website's kit builder use it."""
    if not regions()["regions"]:
        die(f"{REGIONS_FILE} is missing or broken; get the kit again (./kit update) to restore it")
    if args.find is not None:
        for r in find_regions(" ".join(args.find)):
            print(f"{r['id']}\t{r['name']}\t{r['group']}")
        return
    cfg = load_config(root)
    if not args.place:
        if args.languages:
            r = region((cfg.get("maps") or {}).get("region"))
            if not r:
                die("kit.json has no region yet: ./kit region --languages PLACE")
            args.place = [r["id"]]
        else:
            print(describe_region(cfg))
            return
    text = " ".join(args.place)
    r = region(text)
    if not r:
        found = find_regions(text)
        if len(found) != 1:
            if not found:
                die(f"No place matches \"{text}\". Try a US state or a country, in English: ./kit region --find WORDS")
            die(f"\"{text}\" could be: " + "; ".join(f"{f['name']} ({f['id']})" for f in found[:12]) +
                ("; ..." if len(found) > 12 else "") + ". Run it again with the one in brackets.")
        r = found[0]
    choices = language_choices(r)
    if args.languages:
        for codes, label, gb in choices:
            print(f"{','.join(codes)}\t{label}\t{gb}")
        return
    wiki = None
    if args.wikipedia:
        wiki = [c.strip().lower() for c in args.wikipedia.split(",") if c.strip()]
        langs = regions()["languages"]
        bad = [c for c in wiki if c not in langs]
        if bad or not wiki:
            die(f"Wikipedia doesn't come in '{','.join(bad)}' here. Languages: " +
                ", ".join(f"{c} ({v['name']})" for c, v in sorted(langs.items())))
    cfg = set_region(root, r, wiki)
    m = maps_settings(cfg)
    log(f"Maps: {r['name']}. Street maps and directions for {r['name']}, and a simple map of the whole world.")
    if not r.get("photon"):
        log("Address search: none, since nobody publishes it for there yet.")
    elif r.get("addresses_wide"):
        log(f"Address search: all of {r['addresses']} (about {max(1, round(r['mb'].get('addresses', 0) / 1000))} GB), "
            f"since nobody publishes it for {r['name']} alone. Just the essentials leave it out.")
    else:
        log(f"Address search: all of {r.get('addresses') or r['name']}.")
    if not m["enabled"]:
        log('Maps are switched off in kit.json ("enabled": false under "maps"), so none of this downloads.')
    log(f"Home: {m['home'].get('label') or 'the middle of it'}. Directions and \"nearest\" searches start there; "
        "set your own on the Map tab.")
    wiki_now = wikipedia_langs(cfg)
    if wiki_now:
        gb = round(sum(v.get("mb", 0) for c, v in regions()["languages"].items() if c in wiki_now) / 1000)
        log(f"Wikipedia: {lang_names(wiki_now)} (about {gb} GB).")
    else:
        log("Wikipedia: none.")


def cmd_drives(root: Path, args: argparse.Namespace) -> None:
    drives = list_drives()
    if not args.json:
        for d in drives:
            print("\t".join([d["path"], d["format"], str(d["free_bytes"] // GB), d["problem"] or "-", d["name"]]))
        return
    cfg, home = load_config(root), Path.home()
    print(json.dumps({
        "kit": str(root), "kit_on_this_computer": on_this_computer(root), "needs_gb": estimate_gb(root, cfg, False),
        "needs_essentials_gb": estimate_gb(root, cfg, True),
        "this_computer": {"path": str(home / KIT_FOLDER), "free_bytes": shutil.disk_usage(home).free,
                          "keeps_free_gb": float(cfg["settings"].get("keep_free_gb_this_computer", 50)),
                          "space": space_at(home / KIT_FOLDER, root, cfg)},
        "drives": [{**d, "kit_path": str(Path(d["path"]) / KIT_FOLDER),
                    "space": space_at(Path(d["path"]) / KIT_FOLDER, root, cfg)} for d in drives]}, indent=2))


def cmd_place(root: Path, args: argparse.Namespace) -> None:
    """Messages go to stderr, so a script can read the kit's new folder from stdout."""
    try:
        new, said = place_kit(root, Path(os.path.abspath(os.path.expanduser(args.dest))))
    except RuntimeError as e:
        print(f"\n{e}", file=sys.stderr)
        sys.exit(1)
    if said:
        print(f"\n{said}", file=sys.stderr)
    print(new)


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
        return "linux-x64" if mach in ("x86_64", "amd64") else "linux-arm64" if mach in ("arm64", "aarch64") else f"linux-{mach}"
    return "windows-x64"


def runtime_binary(root: Path, product: str, name: str) -> Optional[Path]:
    override = os.environ.get(f"KIT_{product.upper().replace('.', '').replace('-', '_')}_BIN")
    if override:
        return Path(override)
    if os.name == "nt" and not name.endswith(".exe"):
        name += ".exe"
    rel = f"bin/{product}-{platform_tag()}"
    cur = current_dir(root, rel)
    return (find_binary(cur, name) if cur else None) or find_binary(root / rel, name)


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


def start_server(procs: List[subprocess.Popen], log: Path, cmd: List[Any], cwd: Optional[Path] = None) -> None:
    with open(log, "w") as f:    # the server keeps its own handle on the log
        procs.append(subprocess.Popen([str(c) for c in cmd], cwd=cwd, stdin=subprocess.DEVNULL, stdout=f,
                                      stderr=subprocess.STDOUT))


def test_maps(root: Path, m: Dict[str, Any], check: Any, procs: List[subprocess.Popen], logs_dir: Path) -> None:
    home = m["home"]
    pm = runtime_binary(root, "pmtiles", "pmtiles")
    tiles = root / "maps" / "tiles" / "basemap.pmtiles"
    check("map tiles present", bool(pm) and tiles.exists(), "" if tiles.exists() else "run ./kit sync")
    if pm and tiles.exists():
        port = free_port()
        start_server(procs, logs_dir / "test-tiles.log",
                     [pm, "serve", tiles.parent, "--port", port, "--interface", "127.0.0.1", "--cors", "http://127.0.0.1:8888",
                      "--public-url", f"http://127.0.0.1:{port}"])  # without it, /basemap.json is a 501
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
        start_server(procs, logs_dir / "test-geocoder.log",
                     [java, f"-Xmx{m['geocoder_heap']}", "-jar", photon, "serve", "-data-dir", gdir,
                      "-listen-ip", "127.0.0.1", "-listen-port", port, "-cors-origin", "http://127.0.0.1:8888"])
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
        start_server(procs, logs_dir / "test-routing.log",
                     [java, f"-Xmx{m['routing_heap']}", f"-Ddw.server.application_connectors[0].port={port}",
                      f"-Ddw.server.admin_connectors[0].port={free_port()}", "-jar", gh, "server", "gh-serve.yml"], cwd=rdir)
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
    drop_finder_files(root)
    zims = sorted((root / "library").glob("*.zim"))
    models = sorted(p for p in (root / "models").glob("*") if p.is_dir() and list(p.glob("*.gguf")))
    log(f"Platform: {platform_tag()}")
    check("library server installed", bool(kiwix), str(kiwix or "run ./kit sync"))
    check("AI server installed", bool(llama), str(llama or "run ./kit sync"))
    check("library files present", bool(zims), f"{len(zims)} .zim files")
    if any(m.get("enabled", True) for m in cfg.get("models", [])):
        check("models present", bool(models), ", ".join(m.name for m in models))
    else:
        log("  SKIP  models: kit.json switches them all off, so the kit runs without the AI")
    procs: List[subprocess.Popen] = []
    logs_dir = root / "logs"
    logs_dir.mkdir(exist_ok=True)
    try:
        if kiwix and zims:
            kport = free_port()
            start_server(procs, logs_dir / "test-kiwix.log",
                         [kiwix, "--port", kport, "--address", "127.0.0.1", "--customIndex", portal, *zims])
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
            start_server(procs, logs_dir / "test-llama.log",
                         [llama, "--models-dir", root / "models", "--models-max", "1", "-c", "4096",
                          "--host", "127.0.0.1", "--port", lport, "--cors-origins", "http://127.0.0.1:8888"])
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
                pre = subprocess.run(["curl", "-sS", "-o", os.devnull, "-D", "-", "-X", "OPTIONS",
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


# ----------------------------------------------------------------------------- the home network

def share_tools() -> Any:
    """tools/share.py: the gate that shares the kit on the home network, its QR code, and starting with the computer."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import share
    return share


def set_setting(root: Path, key: str, value: Any) -> None:
    """Change one setting in kit.json (None removes it), and leave the rest of the file as it is."""
    path = root / "kit.json"
    text = path.read_text(encoding="utf-8")
    val = json.dumps(value)
    name = rf'"{re.escape(key)}"\s*:\s*'
    now = r'(?:true|false|null|-?[\d.]+|"(?:[^"\\]|\\.)*"|\[[^\[\]{}]*\])'
    if value is None:    # with the comma and space after it, or before it if it's the last one
        new, n = re.subn(name + now + r"\s*,\s*", "", text, count=1)
        if not n:
            new = re.sub(r",\s*" + name + now, "", text, count=1)
    else:
        new, n = re.subn(f"({name}){now}", lambda m: m.group(1) + val, text, count=1)
        if not n:    # a kit.json from before this setting: it goes first in "settings"
            new = re.sub(r'("settings"\s*:\s*\{)(\s*)', lambda m: f'{m.group(1)}{m.group(2)}"{key}": {val},{m.group(2)}',
                         text, count=1)
    try:
        ok = json.loads(new).get("settings", {}).get(key) == value
    except ValueError:
        ok = False
    if not ok:
        cfg = json.loads(text)
        cfg.setdefault("settings", {})[key] = value
        if value is None:
            cfg["settings"].pop(key)
        new = json.dumps(cfg, indent=2) + "\n"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(new, encoding="utf-8")
    os.replace(tmp, path)


def cmd_share(root: Path, args: argparse.Namespace) -> None:
    share = share_tools()
    s = load_config(root)["settings"]
    port, on = int(s.get("share_port", 8000)), s.get("share_on_network") is True
    if args.code is not None and not share.valid_code(args.code):
        die("An access code needs 6 to 64 letters or digits.")
    if args.action in ("on", "new-code"):
        access = share.load_access(root)
        if args.action == "new-code" or args.code:
            access["code"] = share.clean_code(args.code) if args.code else share.new_code()
            share.save_access(root, access)
    if args.action == "off":
        set_setting(root, "share_on_network", False)
        log("Sharing is off: only this computer can open the kit.")
        log("The kit restarted without it." if share.restart_if_autostarted(root) else
            "If the kit is running, close its window and start it again.")
        return
    if args.action == "on" and on:
        log("Sharing is already on.")
    elif args.action == "on":
        set_setting(root, "share_on_network", True)
        on = True
        log("Sharing is on: phones and laptops on your home network need the access code.")
        start = "Open Tinfoil Kit for Windows.bat" if share.WINDOWS else "Open Tinfoil Kit.command"
        log("The kit restarted with sharing on." if share.restart_if_autostarted(root) else
            f"Start the kit to share it ({start}), or restart it if it's running.")
    elif args.action == "new-code":
        log("New access code. Phones and laptops that used the old one need this one now.")
    if not on:
        log(f"Sharing is off: only this computer can open the kit. {share.kit_cmd('share on')} lets phones and\n"
            "laptops on your home network open it too, once they type an access code.")
        return
    log("")
    log(share.banner(root, port, args.qr or sys.stdout.isatty()))
    if not args.action:
        log("")
        share.autostart(root, "status")


def cmd_autostart(root: Path, args: argparse.Namespace) -> None:
    share = share_tools()
    rc = share.autostart(root, args.action or "status")
    if rc == 0 and args.action == "on":
        if load_config(root)["settings"].get("share_on_network") is not True:
            log(f"Sharing is off, so only this computer can use the kit. {share.kit_cmd('share on')} lets your phones "
                "and laptops in.")
        elif share.WINDOWS:    # the first time Python listens on the network
            log("If Windows asks whether Python may use the network, allow it, or phones and laptops can't reach\n"
                "the kit.")
    sys.exit(rc)


# ----------------------------------------------------------------------------- update command

def kit_github(path: str, *keys: str) -> Optional[Dict[str, Any]]:
    """Ask the kit's own GitHub repo. None if GitHub has no such thing; exits if it can't be reached or makes no sense."""
    try:
        answer = http_json(f"{GITHUB_API}/repos/{KIT_REPO}/{path}")
    except HttpError as e:
        if e.status == 404:
            return None
        log(f"Couldn't reach GitHub, so this version stays. ({e})")
        sys.exit(1)
    except ValueError:
        answer = None
    if isinstance(answer, dict) and all(isinstance(answer.get(k), str) for k in keys):
        return answer
    log("GitHub's answer made no sense (a Wi-Fi sign-in page?), so this version stays.")
    sys.exit(1)


def cmd_update(root: Path, args: argparse.Namespace) -> None:
    """Exits 3 after installing a new version, so SETUP.command knows to start over on it."""
    if (root / ".git").exists():
        log("This kit folder is a git checkout. Update it with:  git pull")
        return
    with Lock(root):
        state = load_state(root)
        log("Checking GitHub for a newer version of the kit...")
        release = kit_github("releases/latest", "tag_name")
        if release is None:
            log("No version of the kit is published yet, so this one stays.")
            return
        tag = release["tag_name"]
        if tag == state.get("kit_version") and not args.force:
            log(f"This is the newest version ({tag}).")
            return
        if re.fullmatch(r"[0-9a-f]{40}", KIT_COMMIT) and not args.force:
            # A copy downloaded from the main branch can be newer than the latest release. No answer means GitHub
            # doesn't know this copy's commit, so the release is the version to have.
            status = (kit_github(f"compare/{tag}...{KIT_COMMIT}", "status") or {}).get("status")
            if status == "identical":
                state["kit_version"] = tag
                save_state(root, state)
                log(f"This is the newest version ({tag}).")
                return
            if status == "ahead":
                log(f"This copy of the kit is newer than its latest release ({tag}), so it stays.")
                return
        name = f"tinfoilkit-{tag}.tar.gz"
        assets = {a.get("name"): a.get("browser_download_url") for a in release.get("assets") or [] if isinstance(a, dict)}
        stage = root / ".kit" / "update"
        shutil.rmtree(stage, ignore_errors=True)
        try:
            if not (isinstance(assets.get(name), str) and isinstance(assets.get(name + ".sig"), str)):
                raise ValueError(f"it isn't signed (the release has no {name} and {name}.sig)")
            data = http_get(assets[name], timeout=600)
            verify_release(root, data, http_get(assets[name + ".sig"]))
            unpack_release(data, stage)
            check_release(stage)
            text, note = merge_kit_json(root, (stage / "kit.json").read_text(encoding="utf-8"))
            (stage / "kit.json").write_text(text, encoding="utf-8")
        except Exception as e:     # whatever goes wrong before the first file moves, the kit stays as it was
            shutil.rmtree(stage, ignore_errors=True)
            die(f"couldn't install version {tag}, so this one stays as it was: {e}")
        news = [line.rstrip() for line in str(release.get("body") or "").splitlines() if line.strip()][:12]
        log(f"Version {tag} of the kit is ready, signed by its maintainer." +
            ("\nWhat's new:\n" + "\n".join("  " + line for line in news) if news else ""))
        if not args.yes and sys.stdin.isatty() and input("Install it now? [Y/n] ").strip().lower() not in ("", "y", "yes"):
            shutil.rmtree(stage, ignore_errors=True)
            log(f"This version stays. Run SETUP again when you want {tag}.")
            return
        try:
            state["kit_files"] = install_release(root, stage, state.get("kit_files", []))
        except OSError as e:
            die(f"the update stopped partway ({e}). Run it again to finish.")
        state["kit_version"] = tag
        save_state(root, state)
        shutil.rmtree(stage, ignore_errors=True)
    log(f"Installed version {tag}. {note}")
    sys.exit(3)


# ----------------------------------------------------------------------------- main

def main() -> None:
    for stream in (sys.stdout, sys.stderr):    # a Windows console can't show every character in a book's title
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(prog="kit", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=None, help="kit folder (default: the folder containing ./kit)")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("plan", help="preview what sync would do")
    p.add_argument("--only", nargs="*", default=[], help="limit to items whose section/id contains these words")
    p.add_argument("--json", action="store_true", help="print every item's size as JSON, disabled ones too")
    p.add_argument("--essentials", action="store_true", help="only what the kit can't do without")
    p = sub.add_parser("sync", help="download and update everything")
    p.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    p.add_argument("--force", action="store_true", help="ignore the free space the kit keeps (keep_free_gb)")
    p.add_argument("--only", nargs="*", default=[], help="limit to items whose section/id contains these words")
    p.add_argument("--essentials", action="store_true", help="only the programs, the map, the most important books "
                   "and the AI this computer runs plus the smallest (SETUP's first run gets these first)")
    p = sub.add_parser("verify", help="re-check files against their checksums")
    p.add_argument("--quick", action="store_true", help="check sizes only (fast)")
    p.add_argument("--fix", action="store_true", help="delete corrupt files so the next sync replaces them")
    sub.add_parser("status", help="show what's installed")
    p = sub.add_parser("search", help="search the Kiwix catalog for more content")
    p.add_argument("words", nargs="+")
    p = sub.add_parser("test", help="check that the offline servers start and answer")
    p.add_argument("--model", help="model folder name to test (default: the smallest)")
    p = sub.add_parser("update", help="install the newest version of the kit's own code, keeping kit.json changes")
    p.add_argument("--force", action="store_true", help="reinstall even if this is the newest version")
    p.add_argument("-y", "--yes", action="store_true", help="don't ask before installing")
    sub.add_parser("pins", help="pin the newest build of every program, with its checksum, in tools/pins.json (before a release)")
    p = sub.add_parser("estimate", help="about how many GB this kit.json needs (no internet needed)")
    p.add_argument("--essentials", action="store_true", help="just the essentials")
    p = sub.add_parser("drives", help="the plugged-in drives the kit could go on")
    p.add_argument("--json", action="store_true", help="with this computer's free space and what the kit needs")
    p = sub.add_parser("place", help="put the kit at DEST, a TinfoilKit folder on a drive or in the home folder")
    p.add_argument("dest")
    p = sub.add_parser("space", help="whether the kit, or just its essentials, fits at PATH with room to spare")
    p.add_argument("path")
    p.add_argument("--json", action="store_true", help="print it all as JSON")
    p = sub.add_parser("essentials", help="get just the essentials from now on (on), or everything again (off)")
    p.add_argument("action", nargs="?", choices=("on", "off"))
    p = sub.add_parser("fit", help="which AI model this computer runs, and the ones too big for its memory")
    p.add_argument("--ask", action="store_true", help="ask whether to download the models it can't run (SETUP)")
    p.add_argument("--skip", action="store_true", help="switch off the models it can't run, in kit.json")
    p.add_argument("--restore", action="store_true", help="switch back on the ones skipped for a smaller computer")
    p.add_argument("--json", action="store_true", help="print it all as JSON")
    p = sub.add_parser("share", help="let phones and laptops on your home network use the kit, with an access code")
    p.add_argument("action", nargs="?", choices=("on", "off", "new-code"))
    p.add_argument("--code", help="the access code to use (6 to 64 letters or digits) instead of a random one")
    p.add_argument("--qr", action="store_true", help="draw the QR code even when not printing to a terminal")
    p = sub.add_parser("autostart", help="start the kit whenever this computer starts, for a home server")
    p.add_argument("action", nargs="?", choices=("on", "off"))
    p = sub.add_parser("region", help="where you live: sets the map area, directions, address search, home and "
                                      "Wikipedia's language")
    p.add_argument("place", nargs="*", help="a US state or a country (a name, or an id from --find)")
    p.add_argument("--find", nargs="*", metavar="WORDS", help="list the places matching WORDS: id, name, group")
    p.add_argument("--languages", action="store_true", help="the Wikipedia languages to offer for the place: codes, "
                                                            "name, GB")
    p.add_argument("--wikipedia", metavar="CODES", help="Wikipedia's languages, comma-separated (en, es, de...)")
    args = ap.parse_args()
    root = (args.root or ROOT).resolve()
    if args.cmd not in ("share", "autostart") and not shutil.which("curl"):
        die("curl is required")
    commands = {"plan": cmd_plan, "sync": cmd_sync, "verify": cmd_verify, "status": cmd_status,
                "search": cmd_search, "test": cmd_test, "update": cmd_update, "estimate": cmd_estimate,
                "drives": cmd_drives, "place": cmd_place, "space": cmd_space, "essentials": cmd_essentials,
                "fit": cmd_fit, "share": cmd_share, "autostart": cmd_autostart, "pins": cmd_pins, "region": cmd_region}
    if args.cmd not in commands:
        ap.print_help()
        return
    try:
        commands[args.cmd](root, args)
    except KeyboardInterrupt:
        log("\nStopped.")
        sys.exit(130)
    except BrokenPipeError:    # piped into head or the like, which stopped reading: not an error worth a traceback
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(1)


if __name__ == "__main__":
    main()
