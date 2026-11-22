#!/usr/bin/env python3
"""Keeps what the person writes on the kit page in the kit's data folder, which a new version never touches: the
notes Ask hands the AI with every question (data/notes.txt), and the map's home and pins (data/places.json). Both
are plain files, readable without the kit.

It listens on 127.0.0.1 and answers the kit page only: a request from another web page is turned away by its Origin,
and one by any name but this computer's own (a website pointing a name of its own at 127.0.0.1) by its Host. Through
tools/share.py's gate, the devices at home that have the access code reach it at /data/. Standard library only, like
kit.py. The launchers start it; without Python the page keeps all this in the browser instead.

  python3 tools/data.py --data KIT/data --port 8095 --library 8888

  GET    /notes             {"text", "version"}
  PUT    /notes             {"text", "version"}, version being the one the edit started from: 409 with the notes
                            as they are now if they changed since
  GET    /places            {"home", "pins"}
  PUT    /places/home       {"lat", "lon", "label", "zoom"}
  PUT    /places/pins/ID    {"name", "note", "lat", "lon"}
  DELETE /places/pins/ID
"""
from __future__ import annotations

import argparse
import hashlib
import http.server
import json
import math
import os
import re
import socketserver
import sys
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Dict, Optional

MAX_NOTES = 100_000     # characters, pages of them; Ask hands the AI the first few thousand
MAX_PINS = 1000
MAX_BODY = 1_000_000
PIN_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
LOCAL = ("127.0.0.1", "localhost", "::1")


class Refused(Exception):
    def __init__(self, status: int, message: str, extra: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status, self.extra = status, extra or {}


def version(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()[:16] if raw else ""


def write_file(path: Path, data: bytes) -> None:
    """All or nothing: a crash or a pulled drive leaves the old file, never half of the new one. Into the data folder
    as it is: if it's gone (the kit was removed, the drive unplugged), the save fails instead of starting a new one."""
    tmp = path.with_name(path.name + ".new")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def number(v: Any, low: float, high: float) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and low <= v <= high


def words(v: Any, most: int, needed: bool = False) -> bool:
    return isinstance(v, str) and len(v) <= most and (bool(v.strip()) or not needed)


def spot(p: Any) -> bool:
    return isinstance(p, dict) and number(p.get("lat"), -90, 90) and number(p.get("lon"), -180, 180)


def pin_ok(p: Any) -> bool:
    return spot(p) and isinstance(p.get("id"), str) and bool(PIN_ID.match(p["id"])) and words(p.get("name"), 200, True)


class Store:
    """The two files. One lock, so two devices saving at once take turns."""

    def __init__(self, data: Path):
        self.notes, self.places = data / "notes.txt", data / "places.json"
        self.lock = threading.Lock()

    def get_notes(self) -> Dict[str, str]:
        try:
            raw = self.notes.read_bytes()
        except FileNotFoundError:
            raw = b""
        return {"text": raw.decode("utf-8-sig", "replace"), "version": version(raw)}    # (Notepad may add a BOM)

    def put_notes(self, body: Dict[str, Any]) -> Dict[str, str]:
        text, since = body.get("text"), body.get("version")
        if not words(text, MAX_NOTES) or not isinstance(since, str):
            raise Refused(400, f"Notes are text, up to {MAX_NOTES:,} characters, with the version the edit started from.")
        with self.lock:
            now = self.get_notes()
            if now["version"] != since:
                raise Refused(409, "These notes changed on another device since this page loaded them.", now)
            raw = text.encode("utf-8", "replace")
            write_file(self.notes, raw)
            return {"text": raw.decode("utf-8"), "version": version(raw)}

    def raw_places(self) -> Dict[str, Any]:
        """places.json as it is, with anything else someone put in it, which a change keeps."""
        try:
            raw = json.loads(self.places.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (ValueError, UnicodeDecodeError):
            raw = None
        if not isinstance(raw, dict) or not isinstance(raw.get("pins", []), list):
            raise Refused(500, f"{self.places} isn't in a shape the kit reads, so it leaves it as it is. Fix it in a "
                               "text editor, or move it out of the data folder to start again.")
        return raw

    def get_places(self) -> Dict[str, Any]:
        raw = self.raw_places()
        return {"home": raw.get("home") if spot(raw.get("home")) else None,
                "pins": [p for p in raw.get("pins", []) if pin_ok(p)]}

    def change_places(self, change: Callable[[Dict[str, Any]], None]) -> Dict[str, Any]:
        with self.lock:
            raw = self.raw_places()
            change(raw)
            write_file(self.places, (json.dumps(raw, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
            return self.get_places()

    def put_home(self, body: Dict[str, Any]) -> Dict[str, Any]:
        if not spot(body) or not words(body.get("label", ""), 200) or not number(body.get("zoom", 12), 0, 22):
            raise Refused(400, "Home is a lat and lon, with a label and a zoom if you like.")
        home = {"lat": body["lat"], "lon": body["lon"], "label": body.get("label", ""), "zoom": body.get("zoom", 12)}
        return self.change_places(lambda raw: raw.update(home=home))

    def put_pin(self, pid: str, body: Dict[str, Any]) -> Dict[str, Any]:
        pin = {"id": pid, "name": body.get("name"), "note": body.get("note", ""), "lat": body.get("lat"),
               "lon": body.get("lon")}
        if not pin_ok(pin) or not words(pin["note"], 5000):
            raise Refused(400, "A pin is a name (up to 200 characters), a note (up to 5,000), and a lat and lon.")

        def change(raw: Dict[str, Any]) -> None:
            pins = raw.setdefault("pins", [])
            at = next((i for i, p in enumerate(pins) if isinstance(p, dict) and p.get("id") == pid), None)
            if at is not None:
                pins[at] = pin
            elif len(pins) >= MAX_PINS:
                raise Refused(400, f"That's {MAX_PINS:,} pins already. Delete some first.")
            else:
                pins.append(pin)
        return self.change_places(change)

    def delete_pin(self, pid: str) -> Dict[str, Any]:
        def change(raw: Dict[str, Any]) -> None:
            raw["pins"] = [p for p in raw.get("pins", []) if not (isinstance(p, dict) and p.get("id") == pid)]
        return self.change_places(change)


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = os.name != "nt"    # on Windows it would share a port another program listens on

    def __init__(self, port: int, store: Store, library: int):
        self.store = store
        self.origins = {f"http://127.0.0.1:{library}", f"http://localhost:{library}"}
        super().__init__(("127.0.0.1", port), Handler)

    def server_bind(self) -> None:
        # without http.server's lookup of this computer's name, which on a Mac asks to "find devices on local networks"
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    body_read = False
    server: Server

    def version_string(self) -> str:
        return "TinfoilKit"

    def log_request(self, code: object = "-", size: object = "-") -> None:
        pass

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {fmt % args}\n")

    def origin(self) -> Optional[str]:
        """The Origin to allow: "" for a request with none (a program on this computer, or the gate, which drops it),
        None for a web page other than the kit's."""
        o = self.headers.get("Origin")
        if o is None:
            return ""
        return o if o in self.server.origins else None

    def host_ok(self) -> bool:
        host = self.headers.get("Host", "").strip().lower()
        name = host[1:].split("]")[0] if host.startswith("[") else host.rsplit(":", 1)[0]
        return name in LOCAL

    def reply(self, status: int, obj: Any, origin: str = "") -> None:
        body = b"" if obj is None else json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        if obj is not None:
            self.send_header("Content-Type", "application/json; charset=utf-8")
        for k, v in (("Content-Length", str(len(body))), ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff")):
            self.send_header(k, v)
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            if self.command == "OPTIONS":    # what the page may send
                self.send_header("Access-Control-Allow-Methods", "GET, PUT, DELETE")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Max-Age", "600")
        if not self.body_read and (self.headers.get("Transfer-Encoding") or
                                   (self.headers.get("Content-Length") or "0").strip() not in ("", "0")):
            self.close_connection = True    # what it sent, unread, would be taken for the next request
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def body(self) -> Dict[str, Any]:
        if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
            raise Refused(415, "Send JSON.")
        try:
            n = int(self.headers.get("Content-Length") or -1)
        except ValueError:
            n = -1
        if n < 0 or n > MAX_BODY:
            raise Refused(413 if n > MAX_BODY else 411, "Send JSON, up to 1 MB, with its length.")
        self.body_read = True
        try:
            got = json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            got = None
        if not isinstance(got, dict):
            raise Refused(400, "Send a JSON object.")
        return got

    def do_GET(self) -> None:
        self.body_read = False
        try:
            self.route()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True

    do_HEAD = do_PUT = do_DELETE = do_POST = do_PATCH = do_OPTIONS = do_GET

    def route(self) -> None:
        origin = self.origin()
        if not self.host_ok() or origin is None:
            return self.reply(403, {"error": "This answers the kit's own page only."})
        if self.command == "OPTIONS":
            return self.reply(204, None, origin)
        path, store = urllib.parse.urlsplit(self.path).path, self.server.store
        reading = self.command in ("GET", "HEAD")
        try:
            if path == "/" and reading:
                return self.reply(200, {"name": "Tinfoil Kit", "notes": "/notes", "places": "/places"}, origin)
            if path == "/notes" and reading:
                return self.reply(200, store.get_notes(), origin)
            if path == "/notes" and self.command == "PUT":
                return self.reply(200, store.put_notes(self.body()), origin)
            if path == "/places" and reading:
                return self.reply(200, store.get_places(), origin)
            if path == "/places/home" and self.command == "PUT":
                return self.reply(200, store.put_home(self.body()), origin)
            pid = path[len("/places/pins/"):] if path.startswith("/places/pins/") else None
            if pid is not None and not PIN_ID.match(pid):
                raise Refused(404, "No such pin.")
            if pid and self.command == "PUT":
                return self.reply(200, store.put_pin(pid, self.body()), origin)
            if pid and self.command == "DELETE":
                return self.reply(200, store.delete_pin(pid), origin)
            if path in ("/", "/notes", "/places", "/places/home") or pid:
                return self.reply(405, {"error": "Not that way."}, origin)
            return self.reply(404, {"error": "Nothing here."}, origin)
        except Refused as e:
            if e.status >= 500:
                self.log_message("%s", e)
            return self.reply(e.status, {"error": str(e), **e.extra}, origin)
        except OSError as e:
            self.log_message("couldn't save: %s", e)
            return self.reply(500, {"error": f"Couldn't save in the kit's data folder: {e.strerror or e}. Is its drive "
                                             "still plugged in, with room on it?"}, origin)


def main() -> None:
    ap = argparse.ArgumentParser(prog="data.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, required=True, help="the kit's data folder")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--library", type=int, required=True, help="the library's port: the kit page's own address")
    args = ap.parse_args()
    if not args.data.is_dir():
        sys.exit(f"Can't keep notes and pins: there's no data folder at {args.data}")
    try:
        server = Server(args.port, Store(args.data), args.library)
    except OSError as e:
        sys.exit(f"Can't keep notes and pins on port {args.port}: {e.strerror}")
    print(f"Notes and pins on port {args.port}, in {args.data}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
