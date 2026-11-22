"""Stand-ins for Photon, GraphHopper, `pmtiles serve` and a tool-calling llama-server, for tests.

usage: mock_services.py photon|graphhopper|tiles|llama PORT [DIR]
Responses follow the real APIs' formats (Photon GeoJSON, GraphHopper /route JSON, OpenAI tool calls).
"""

import json
import math
import os
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

MODE, PORT = sys.argv[1], int(sys.argv[2])

PLACES = [
    # name, housenumber, street, city, postcode, lat, lon, osm_key, osm_value
    (
        "Kestrel Bay Medical Center",
        "100",
        "Heron Road",
        "Kestrel Bay",
        "00595",
        40.7974,
        -74.0298,
        "amenity",
        "hospital",
    ),
    (
        "Larkspur General Hospital",
        "41",
        "East Lark Road",
        "Testville",
        "00601",
        40.7415,
        -73.9875,
        "amenity",
        "hospital",
    ),
    ("Pellwood Hospital", "55", "Fennel Avenue", "Pellwood", "00708", 40.6578, -74.0500, "amenity", "hospital"),
    ("Corner Pharmacy", "1", "Main Street", "Testville", "00601", 40.7458, -73.9910, "amenity", "pharmacy"),
    (
        "Quarry Hill Police Department",
        "2",
        "Quarry Road",
        "Quarry Hill",
        "00583",
        40.7018,
        -74.0340,
        "amenity",
        "police",
    ),
    (None, "100", "Main Street", "Testville", "00601", 40.7453, -73.9920, "place", "house"),
    ("Fuel Stop", "300", "Central Avenue", "Testville", "00606", 40.7328, -74.0160, "amenity", "fuel"),
]


def dist(a, b):
    r, t = 6371000, math.pi / 180
    dlat, dlon = (b[0] - a[0]) * t, (b[1] - a[1]) * t
    h = math.sin(dlat / 2) ** 2 + math.cos(a[0] * t) * math.cos(b[0] * t) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def feature(p):
    name, hn, street, city, pc, lat, lon, k, v = p
    props = {
        "osm_type": "N",
        "osm_id": abs(hash(street + hn)) % 10**8,
        "osm_key": k,
        "osm_value": v,
        "type": "house",
        "housenumber": hn,
        "street": street,
        "city": city,
        "state": "New York",
        "postcode": pc,
        "country": "United States",
        "countrycode": "US",
    }
    if name:
        props["name"] = name
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": props}


def zz(n):
    return (n << 1) ^ (n >> 31)


def varint(n):
    out = b""
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out += bytes([b | 0x80])
        else:
            return out + bytes([b])


def field(num, wire, payload):
    key = varint((num << 3) | wire)
    if wire == 2:
        return key + varint(len(payload)) + payload
    return key + payload


def mvt_tile():
    """A real Mapbox Vector Tile: an 'earth' polygon covering the tile and a 'places' point."""

    def layer(name, ftype, geom, props):
        keys, vals, tags = list(props), [], []
        for i, k in enumerate(keys):
            v = props[k]
            vals.append(field(1, 2, v.encode()) if isinstance(v, str) else field(4, 0, varint(v)))
            tags += [i, i]
        feat = (
            field(2, 2, b"".join(varint(t) for t in tags))
            + field(3, 0, varint(ftype))
            + field(4, 2, b"".join(varint(g) for g in geom))
        )
        body = field(15, 0, varint(2)) + field(1, 2, name.encode()) + field(2, 2, feat)
        body += b"".join(field(3, 2, k.encode()) for k in keys) + b"".join(field(4, 2, v) for v in vals)
        body += field(5, 0, varint(4096))
        return field(3, 2, body)

    poly = [9, zz(0), zz(0), 26, zz(4096), zz(0), zz(0), zz(4096), zz(-4096), zz(0), 15]
    point = [9, zz(2048), zz(2048)]
    return layer("earth", 3, poly, {"kind": "earth"}) + layer(
        "places", 1, point, {"kind": "locality", "name": "Testville", "min_zoom": 0, "population_rank": 10}
    )


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def cors(self):
        origin = self.headers.get("Origin")
        if MODE == "llama":
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
        else:
            self.send_header("Access-Control-Allow-Origin", "*")

    def reply(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else (json.dumps(body) if not isinstance(body, str) else body).encode()
        self.send_response(code)
        self.cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if MODE == "photon":
            if u.path == "/status":
                return self.reply(200, {"status": "Ok", "import_date": "2026-11-15T00:00:00Z"})
            if u.path == "/api":
                words = [w for w in re.findall(r"[a-z0-9]+", q.get("q", [""])[0].lower()) if w not in ("st", "ny")]
                hits = [
                    p
                    for p in PLACES
                    if words
                    and all(
                        w in " ".join(str(x) for x in p[:5] if x).lower().replace("street", "street st") for w in words
                    )
                ]
                return self.reply(
                    200,
                    {
                        "type": "FeatureCollection",
                        "features": [feature(p) for p in hits[: int(q.get("limit", ["5"])[0])]],
                    },
                )
            if u.path == "/reverse":
                lat, lon = float(q["lat"][0]), float(q["lon"][0])
                inc = set(",".join(q.get("include", [])).split(",")) - {""}
                tags = set(q.get("osm_tag", []))
                if inc and os.environ.get("MOCK_PHOTON_OLD"):  # an old Photon without categories
                    return self.reply(400, {"message": "Unknown query parameter 'include'."})
                pool = [
                    p
                    for p in PLACES
                    if (not inc or f"osm.{p[7]}.{p[8]}" in inc) and (not tags or f"{p[7]}:{p[8]}" in tags)
                ]
                pool.sort(key=lambda p: dist((lat, lon), (p[5], p[6])))
                return self.reply(
                    200,
                    {
                        "type": "FeatureCollection",
                        "features": [feature(p) for p in pool[: int(q.get("limit", ["1"])[0])]],
                    },
                )
        if MODE == "graphhopper":
            if u.path == "/health":
                return self.reply(200, "OK", "text/plain")
            if u.path == "/route":
                prof = q.get("profile", ["car"])[0]
                if prof not in ("car", "foot"):
                    return self.reply(400, {"message": f"The requested profile '{prof}' does not exist"})
                pts = [tuple(map(float, p.split(","))) for p in q.get("point", [])]
                (a, b) = pts[0], pts[1]
                coords = [[a[1] + (b[1] - a[1]) * i / 19, a[0] + (b[0] - a[0]) * i / 19] for i in range(20)]
                d = dist(a, b) * 1.3
                t = d / (13.4 if prof == "car" else 1.4) * 1000
                ins = [
                    {
                        "text": "Continue onto Main Street",
                        "street_name": "Main Street",
                        "distance": d * 0.3,
                        "time": t * 0.3,
                        "sign": 0,
                        "interval": [0, 5],
                    },
                    {
                        "text": "Turn left onto Heron Road",
                        "street_name": "Heron Road",
                        "distance": d * 0.7,
                        "time": t * 0.7,
                        "sign": -2,
                        "interval": [5, 19],
                    },
                    {
                        "text": "Arrive at destination",
                        "street_name": "",
                        "distance": 0,
                        "time": 0,
                        "sign": 4,
                        "interval": [19, 19],
                    },
                ]
                return self.reply(
                    200,
                    {
                        "paths": [
                            {
                                "distance": d,
                                "time": t,
                                "points_encoded": False,
                                "points": {"type": "LineString", "coordinates": coords},
                                "instructions": ins,
                                "bbox": [min(a[1], b[1]), min(a[0], b[0]), max(a[1], b[1]), max(a[0], b[0])],
                            }
                        ],
                        "info": {"copyrights": ["GraphHopper", "OpenStreetMap contributors"]},
                    },
                )
        if MODE == "tiles":
            if u.path == "/basemap.json":
                return self.reply(
                    200,
                    {
                        "tilejson": "3.0.0",
                        "tiles": [f"http://127.0.0.1:{PORT}/basemap/{{z}}/{{x}}/{{y}}.mvt"],
                        "minzoom": 0,
                        "maxzoom": 15,
                        "vector_layers": [{"id": "earth"}, {"id": "places"}],
                    },
                )
            if re.match(r"^/basemap/\d+/\d+/\d+\.mvt$", u.path):
                return self.reply(200, mvt_tile(), "application/x-protobuf")
        if MODE == "llama" and u.path == "/v1/models":
            return self.reply(200, {"object": "list", "data": [{"id": "Mock-Tools", "object": "model"}]})
        self.reply(404, {"message": "not found"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        if MODE != "llama" or self.path != "/v1/chat/completions":
            return self.reply(404, {"message": "not found"})
        msgs = body.get("messages", [])
        question = next((m["content"] for m in reversed(msgs) if m["role"] == "user"), "")
        tools_used = [m for m in msgs if m["role"] == "tool"]
        if body.get("tools") and "story" not in question.lower():  # "story" questions: the model answers without tools
            if not tools_used:
                if "nearest" in question.lower():
                    call = ("find_nearby", {"category": "hospital"})
                elif " to " in question.lower():
                    call = ("get_directions", {"from": "home", "to": question.lower().split(" to ", 1)[1].strip(" ?.")})
                else:
                    call = ("search_places", {"query": question})
            else:
                last = json.loads(tools_used[-1]["content"])
                prev = [m for m in msgs if m.get("tool_calls")][-1]["tool_calls"][0]["function"]["name"]
                if prev == "find_nearby" and "results" in last and last["results"] and "get" in question.lower():
                    call = ("get_directions", {"from": "home", "to": last["results"][0]["name"]})
                else:
                    summary = json.dumps(last)[:300]
                    return self.reply(
                        200,
                        {
                            "choices": [
                                {
                                    "index": 0,
                                    "finish_reason": "stop",
                                    "message": {
                                        "role": "assistant",
                                        "content": f"**Mock answer** based on the map: {summary}",
                                    },
                                }
                            ]
                        },
                    )
            return self.reply(
                200,
                {
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "tool_calls",
                            "message": {
                                "role": "assistant",
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": f"call_{len(tools_used)}",
                                        "type": "function",
                                        "function": {"name": call[0], "arguments": json.dumps(call[1])},
                                    }
                                ],
                            },
                        }
                    ]
                },
            )
        if body.get("stream"):
            chunks = [
                {"choices": [{"index": 0, "delta": {"content": w}}]}
                for w in ("Library ", "answer ", "[1]. ", "½ cup — café")
            ]
            data = (
                "".join(f"data: {json.dumps(c, ensure_ascii=False)}\n\n" for c in chunks) + "data: [DONE]\n\n"
            ).encode()
            # in two parts, cut inside "½" as a network can cut it, so the page has to put the character back together
            cut = data.index("½".encode()) + 1
            self.send_response(200)
            self.cors()
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data[:cut])
            self.wfile.flush()
            time.sleep(0.2)
            self.wfile.write(data[cut:])
            return
        return self.reply(
            200,
            {
                "choices": [
                    {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "plain answer"}}
                ]
            },
        )


print(f"mock {MODE} on {PORT}", flush=True)
ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
