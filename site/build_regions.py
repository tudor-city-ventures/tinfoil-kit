"""Build tools/regions.json: the places SETUP and the kit builder offer for "Where do you live?".

Each place is one Geofabrik extract: a US state, a country, or a part of a big country. For each it records the
street-detail area and the road data for directions (the extract's outline and file), the address database
(Photon's, by country), a default home (the biggest town inside it, from GeoNames), units, and the languages
Wikipedia can come in there (Kiwix). Needs the internet; the "refresh builder sizes" workflow runs it.

usage: python3 site/build_regions.py [--out FILE] [--cache DIR]
--cache keeps the big downloads (Geofabrik's index, GeoNames' towns) in DIR between runs.
"""
import argparse
import base64
import concurrent.futures
import gzip
import io
import json
import math
import re
import sys
import time
import unicodedata
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import kit  # noqa: E402  the kit's own downloads (curl), Kiwix catalog and Photon page readers

GEOFABRIK = kit.GEOFABRIK.rstrip("/") + "/"
INDEX = GEOFABRIK + "index-v1.json"
TOWNS = "https://download.geonames.org/export/dump/cities1000.zip"
COUNTRIES = "https://download.geonames.org/export/dump/countryInfo.txt"
STATES = "https://download.geonames.org/export/dump/admin1CodesASCII.txt"
# Bigger extracts are offered as their parts: building the road network for directions needs too much memory.
MAX_PBF = 2.2e9
ALWAYS = {"us-northeast"}                       # kit.json's default
US_GROUPS = ["us-northeast", "us-midwest", "us-south", "us-west"]    # for people near a state line
SKIP = {"antarctica", "great-britain"}          # nobody's home; a copy of the United Kingdom without Northern Ireland
IMPERIAL = {"us", "gb"}
# What people call a country besides its name, for the search in SETUP.
NICKNAMES = {"us": ["USA", "America", "United States"], "gb": ["UK", "Britain", "Great Britain"], "nl": ["Holland"],
             "cz": ["Czechia"], "ae": ["UAE", "Emirates"], "kr": ["South Korea"], "kp": ["North Korea"],
             "ci": ["Cote d'Ivoire"], "cd": ["DR Congo", "DRC"], "mm": ["Myanmar", "Burma"], "tl": ["Timor-Leste"]}
# Languages offered where one isn't enough. Elsewhere: the first of GeoNames' languages that has a Wikipedia.
LANGS = {"us": ["en", "es"], "ca": ["en", "fr"], "quebec": ["fr", "en"], "ch": ["de", "fr", "it"],
         "be": ["nl", "fr"], "lu": ["fr", "de"], "fi": ["fi", "sv"], "in": ["en", "hi"], "sg": ["en", "zh"],
         "za": ["en", "af"], "il": ["he", "ar"], "israel-and-palestine": ["he", "ar"], "ph": ["en", "tl"],
         "ie": ["en", "ga"], "pk": ["ur", "en"]}
NAMES = {   # code: (English, native)
    "af": ("Afrikaans", "Afrikaans"), "am": ("Amharic", "አማርኛ"), "ar": ("Arabic", "العربية"),
    "az": ("Azerbaijani", "Azərbaycanca"), "be": ("Belarusian", "Беларуская"), "bg": ("Bulgarian", "Български"),
    "bn": ("Bengali", "বাংলা"), "bs": ("Bosnian", "Bosanski"), "ca": ("Catalan", "Català"), "cs": ("Czech", "Čeština"),
    "cy": ("Welsh", "Cymraeg"), "da": ("Danish", "Dansk"), "de": ("German", "Deutsch"), "el": ("Greek", "Ελληνικά"),
    "en": ("English", "English"), "eo": ("Esperanto", "Esperanto"), "es": ("Spanish", "Español"),
    "et": ("Estonian", "Eesti"), "eu": ("Basque", "Euskara"), "fa": ("Persian", "فارسی"), "fi": ("Finnish", "Suomi"),
    "fo": ("Faroese", "Føroyskt"), "fr": ("French", "Français"), "ga": ("Irish", "Gaeilge"), "gl": ("Galician", "Galego"),
    "gu": ("Gujarati", "ગુજરાતી"), "ha": ("Hausa", "Hausa"), "he": ("Hebrew", "עברית"), "hi": ("Hindi", "हिन्दी"),
    "hr": ("Croatian", "Hrvatski"), "ht": ("Haitian Creole", "Kreyòl ayisyen"), "hu": ("Hungarian", "Magyar"),
    "hy": ("Armenian", "Հայերեն"), "id": ("Indonesian", "Bahasa Indonesia"), "ig": ("Igbo", "Igbo"),
    "is": ("Icelandic", "Íslenska"), "it": ("Italian", "Italiano"), "ja": ("Japanese", "日本語"),
    "ka": ("Georgian", "ქართული"), "kk": ("Kazakh", "Қазақша"), "km": ("Khmer", "ខ្មែរ"), "kn": ("Kannada", "ಕನ್ನಡ"),
    "ko": ("Korean", "한국어"), "ky": ("Kyrgyz", "Кыргызча"), "lb": ("Luxembourgish", "Lëtzebuergesch"),
    "lo": ("Lao", "ລາວ"), "lt": ("Lithuanian", "Lietuvių"), "lv": ("Latvian", "Latviešu"), "mg": ("Malagasy", "Malagasy"),
    "mk": ("Macedonian", "Македонски"), "ml": ("Malayalam", "മലയാളം"), "mn": ("Mongolian", "Монгол"),
    "mr": ("Marathi", "मराठी"), "ms": ("Malay", "Bahasa Melayu"), "mt": ("Maltese", "Malti"), "my": ("Burmese", "မြန်မာ"),
    "ne": ("Nepali", "नेपाली"), "nl": ("Dutch", "Nederlands"), "no": ("Norwegian", "Norsk"), "pa": ("Punjabi", "ਪੰਜਾਬੀ"),
    "pl": ("Polish", "Polski"), "ps": ("Pashto", "پښتو"), "pt": ("Portuguese", "Português"), "ro": ("Romanian", "Română"),
    "ru": ("Russian", "Русский"), "rw": ("Kinyarwanda", "Ikinyarwanda"), "si": ("Sinhala", "සිංහල"),
    "sk": ("Slovak", "Slovenčina"), "sl": ("Slovenian", "Slovenščina"), "so": ("Somali", "Soomaali"),
    "sq": ("Albanian", "Shqip"), "sr": ("Serbian", "Српски"), "sv": ("Swedish", "Svenska"), "sw": ("Swahili", "Kiswahili"),
    "ta": ("Tamil", "தமிழ்"), "te": ("Telugu", "తెలుగు"), "tg": ("Tajik", "Тоҷикӣ"), "th": ("Thai", "ไทย"),
    "tk": ("Turkmen", "Türkmençe"), "tl": ("Tagalog", "Tagalog"), "tr": ("Turkish", "Türkçe"), "uk": ("Ukrainian", "Українська"),
    "ur": ("Urdu", "اردو"), "uz": ("Uzbek", "Oʻzbekcha"), "vi": ("Vietnamese", "Tiếng Việt"), "yo": ("Yoruba", "Yorùbá"),
    "zh": ("Chinese", "中文"), "zu": ("Zulu", "isiZulu"),
}
ALIAS = {"nb": "no", "nn": "no", "fil": "tl", "cmn": "zh", "iw": "he", "in": "id"}   # GeoNames code -> Wikipedia's
PBF_PATH = re.compile(r"^[a-z0-9][a-z0-9/_-]*-latest\.osm\.pbf$")
SAFE = re.compile(r"^[a-z0-9][a-z0-9/_-]*$")
warnings = []


def warn(msg):
    warnings.append(msg)
    print("WARNING: " + msg, flush=True)


def fetch(url, cache, name, timeout=900):
    if cache:
        p = cache / name
        if p.exists():
            return p.read_bytes()
    data = kit.http_get(url, timeout=timeout)
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
        (cache / name).write_bytes(data)
    return data


def head(url):
    """A file's size, asking again when the server is busy (Geofabrik turns away many requests at once)."""
    for attempt in range(5):
        try:
            return kit.content_length(kit.http_head(url))
        except kit.HttpError as e:
            err = e
            if re.search(r"error: 40[34]", str(e)):
                break
            time.sleep(3 * (attempt + 1))
    warn(f"{url}: {err}")
    return None


def sizes(urls):
    """HEAD a few URLs at a time: their sizes, or None."""
    with concurrent.futures.ThreadPoolExecutor(3) as ex:
        return dict(zip(urls, ex.map(head, urls)))


def codes(value):
    """Geofabrik writes country codes as "DE", "PS,IL" or a list."""
    if isinstance(value, str):
        value = value.split(",")
    return [c.strip().lower() for c in value or [] if c.strip()]


def fold(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower()


# ----------------------------------------------------------------------------- outlines

def polygons(geom):
    if not geom:
        return []
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"]
    return []


def bbox_of(polys, ident):
    """[west, south, east, north] around the outlines. An area across the 180th meridian (Alaska's islands, the
    Russian Far East) keeps only its bigger side, since a map extract can't wrap around."""
    boxes = []
    for poly in polys:
        xs, ys = [p[0] for p in poly[0]], [p[1] for p in poly[0]]
        boxes.append((min(xs), min(ys), max(xs), max(ys)))
    if not boxes:
        return None
    w, e = min(b[0] for b in boxes), max(b[2] for b in boxes)
    if e - w > 180 and any(b[2] < 0 for b in boxes) and any(b[0] > 0 for b in boxes):
        sides = [[b for b in boxes if (b[0] + b[2]) / 2 < 0], [b for b in boxes if (b[0] + b[2]) / 2 >= 0]]
        boxes = max(sides, key=lambda bs: sum((b[2] - b[0]) * (b[3] - b[1]) for b in bs))
        warn(f"{ident}: crosses the 180th meridian; street detail leaves out its smaller side")
        w, e = min(b[0] for b in boxes), max(b[2] for b in boxes)
    s, n = min(b[1] for b in boxes), max(b[3] for b in boxes)
    lo, hi = (lambda v: math.floor(v * 100 + 1e-6) / 100), (lambda v: math.ceil(v * 100 - 1e-6) / 100)
    return [lo(w), lo(s), hi(e), hi(n)]


def in_ring(x, y, ring):
    inside, j = False, len(ring) - 1
    for i in range(len(ring)):
        xi, yi, xj, yj = ring[i][0], ring[i][1], ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def in_polys(x, y, polys):
    return any(in_ring(x, y, p[0]) and not any(in_ring(x, y, h) for h in p[1:]) for p in polys)


# ----------------------------------------------------------------------------- sources

def load_towns(data):
    """GeoNames towns of 1,000 people or more, by country, biggest first."""
    by_cc = {}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        text = z.read("cities1000.txt").decode("utf-8")
    for line in text.splitlines():
        c = line.split("\t")
        if len(c) < 15 or not c[14].isdigit():
            continue
        by_cc.setdefault(c[8].lower(), []).append((int(c[14]), c[1], float(c[4]), float(c[5]), c[10]))
    for towns in by_cc.values():
        towns.sort(key=lambda t: -t[0])
    return by_cc


def load_states(data):
    """"DE.02" -> "Bavaria": the English names of states and provinces, keyed as towns' country and admin1 codes."""
    out = {}
    for line in data.decode("utf-8").splitlines():
        c = line.split("\t")
        if len(c) > 2:
            out[c[0].lower()] = c[2]
    return out


def load_countries(data):
    """ISO code -> (English name, ISO3, Wikipedia language codes in GeoNames' order)."""
    out = {}
    for line in data.decode("utf-8").splitlines():
        if line.startswith("#"):
            continue
        c = line.split("\t")
        if len(c) > 15:
            langs = []
            for code in c[15].split(","):
                code = code.strip().split("-")[0].lower()
                code = ALIAS.get(code, code)
                if code and code not in langs:
                    langs.append(code)
            out[c[0].lower()] = (c[4], c[1], langs)
    return out


def photon_db(cc, base, pages):
    """Where Photon's address database for a country is: (folder, file, fallback?). The same search kit.py's
    _photon_db does: a country's own database, or else the one for the region of the world it's in."""
    def page(path):
        if path not in pages:
            try:
                pages[path] = kit.photon_regions(kit.http_get(base + path).decode(errors="replace"))
            except kit.HttpError as e:
                warn(f"Photon page {base + path}: {e}")
                pages[path] = []
        return pages[path]

    top = [r for r in page("") if cc in r["codes"]]
    if not top:
        return None
    row = top[0]
    path, has_db, fallback = [row["slug"]], row["db"], False
    if row["codes"] != [cc]:
        inner = [r for r in page(row["slug"] + "/") if cc in r["codes"]]
        if inner and inner[0]["db"]:
            path, has_db = [row["slug"], inner[0]["slug"]], True
        else:
            fallback = True
    if not has_db:
        return None
    folder = "/".join(path) + "/"
    try:
        listing = kit.http_get(base + folder).decode(errors="replace")
    except kit.HttpError:
        listing = ""
    found = sorted(set(re.findall(r"photon-db-" + re.escape(path[-1]) + r"-(\d+\.\d+)-latest\.tar\.bz2", listing)),
                   key=kit.version_key, reverse=True)
    if not found:
        warn(f"Photon folder {folder} lists no database file")
        return None
    return folder, f"photon-db-{path[-1]}-{found[0]}-latest.tar.bz2", fallback


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "tools" / "regions.json")
    ap.add_argument("--cache", type=Path)
    ap.add_argument("--print", action="store_true", help="also print the result, gzipped and base64, to stdout")
    args = ap.parse_args()

    index = json.loads(fetch(INDEX, args.cache, "geofabrik-index-v1.json"))
    feats = {f["properties"]["id"]: f for f in index["features"]}
    kids = {}
    for f in index["features"]:
        kids.setdefault(f["properties"].get("parent"), []).append(f["properties"]["id"])
    print(f"Geofabrik: {len(feats)} extracts; top level: {', '.join(sorted(kids.get(None, [])))}", flush=True)

    def prop(ident, key, default=None):
        return feats[ident]["properties"].get(key, default)

    def iso(ident):
        return codes(prop(ident, "iso3166-1:alpha2"))

    def ancestors(ident):
        out = []
        while prop(ident, "parent"):
            ident = prop(ident, "parent")
            out.append(ident)
        return out

    pbf_url = {i: prop(i, "urls", {}).get("pbf", "") for i in feats}
    for i, u in pbf_url.items():
        if u and not (u.startswith(GEOFABRIK) and PBF_PATH.match(u[len(GEOFABRIK):])):
            warn(f"{i}: unexpected download address {u}; left out")
            pbf_url[i] = ""
    pbf_size = sizes([u for i, u in pbf_url.items() if u and i not in SKIP])
    size = {i: pbf_size.get(u) for i, u in pbf_url.items()}

    picked = []

    def offer(ident):
        if ident in SKIP or not pbf_url[ident]:
            return
        parts = [k for k in kids.get(ident, []) if k not in SKIP and k not in US_GROUPS]   # groups come below
        if size[ident] is None:
            warn(f"{ident}: Geofabrik didn't say how big its road data is")
        if (size[ident] is not None and size[ident] <= MAX_PBF) or not parts:
            if (size[ident] or 0) > MAX_PBF:
                warn(f"{ident}: {size[ident] / 1e9:.1f} GB of road data and no smaller parts; offered anyway")
            picked.append(ident)
        else:
            print(f"  {ident}: {(size[ident] or 0) / 1e9:.1f} GB, offered as {len(parts)} parts", flush=True)
            for k in sorted(parts):
                offer(k)

    for ident in sorted(feats):
        p = prop(ident, "parent")
        if iso(ident) and (p is None or not iso(p)) and not any(iso(a) for a in ancestors(ident)):
            offer(ident)
    for ident in sorted(ALWAYS | set(US_GROUPS)):
        if ident in feats and ident not in picked and (ident in ALWAYS or (size[ident] or MAX_PBF + 1) <= MAX_PBF):
            picked.append(ident)
    for ident in ALWAYS:
        if ident not in picked:
            sys.exit(f"{ident} (kit.json's default region) isn't in Geofabrik's index any more")

    countries = load_countries(fetch(COUNTRIES, args.cache, "countryInfo.txt"))
    states = load_states(fetch(STATES, args.cache, "admin1CodesASCII.txt"))
    towns = load_towns(fetch(TOWNS, args.cache, "cities1000.zip"))
    catalog = kit.parse_kiwix_catalog(kit.http_get(kit.KIWIX_CATALOG, timeout=900))
    continents = [(prop(t, "name"), polygons(feats[t].get("geometry")))
                  for t in kids.get(None, []) if t not in SKIP and t != "russia"]

    def wikipedia(code):
        for flavour in ("maxi", "nopic", "mini"):
            e = catalog.get(f"wikipedia_{code}_all_{flavour}")
            if e:
                return e, flavour
        return None, None

    regions, used_langs, photon_pages, photon_cache = [], {"en"}, {}, {}
    photon_base = kit.PHOTON_DUMPS.rstrip("/") + "/"
    for ident in picked:
        chain = [ident] + ancestors(ident)
        country = next((a for a in chain if iso(a)), None)      # the extract that is the whole country
        ccs = iso(country) if country else (["us"] if ident in US_GROUPS else [])
        polys = polygons(feats[ident].get("geometry"))
        box = bbox_of(polys, ident)
        if not box:
            warn(f"{ident}: no outline; left out")
            continue

        inside = {}         # country code -> its biggest towns inside the outline
        for c in ccs:
            inside[c] = []
            for t in towns.get(c, []):
                if box[1] <= t[2] <= box[3] and box[0] <= t[3] <= box[2] and in_polys(t[3], t[2], polys):
                    inside[c].append(t)
                    if len(ccs) == 1 and len(inside[c]) == 3:
                        break
        # An extract of several countries ("Israel and Palestine") takes the address database and languages of the
        # one most of its people live in.
        cc = max(ccs, key=lambda c: sum(t[0] for t in inside[c])) if ccs else ""
        biggest = sorted((t + (c,) for c in ccs for t in inside[c]), key=lambda t: -t[0])[:3]
        if biggest:
            pop, town, lat, lon, admin1, c = biggest[0]
            label = f"{town}, {admin1}" if c == "us" and re.fullmatch(r"[A-Z]{2}", admin1) else town
            home = {"label": label, "lat": round(lat, 4), "lon": round(lon, 4)}
        else:
            warn(f"{ident}: no town found inside it; home is its middle")
            home = {"label": prop(ident, "name"), "lat": round((box[1] + box[3]) / 2, 4),
                    "lon": round((box[0] + box[2]) / 2, 4)}

        name, top = prop(ident, "name"), chain[-1]
        part = country != ident             # a state, province or region of a country, or a group of US states
        if cc == "us":
            group = "United States"
        elif country and any(iso(a) for a in chain[chain.index(country) + 1:]):
            # Overseas (Bermuda under the United Kingdom, Réunion under France): grouped where it is.
            group = next((n for n, ps in continents if in_polys(home["lon"], home["lat"], ps)), prop(top, "name"))
        else:
            group = "Europe" if top == "russia" else prop(top, "name")
        if part and cc != "us":
            name = f"{countries.get(cc, (prop(country, 'name'),))[0]}: {name}"

        if cc not in photon_cache:
            photon_cache[cc] = photon_db(cc, photon_base, photon_pages) if cc else None
            if not photon_cache[cc]:
                warn(f"Photon has no address database for '{cc}' ({ident} and any others there have no address search)")
        ph = photon_cache[cc]

        langs = []
        for code in LANGS.get(ident) or LANGS.get(cc) or countries.get(cc, ("", "", []))[2][:3]:
            if wikipedia(code)[0] and code not in langs:
                langs.append(code)
            if not (LANGS.get(ident) or LANGS.get(cc)) and langs:
                break
        langs = langs or ["en"]
        used_langs.update(langs)

        # What else someone might type for it: the countries' names and codes, its biggest towns, the English name
        # of the state it's in (Bavaria for Bayern). A state's code only where people use them (NY, ON, NSW): others
        # clash with countries' codes.
        also = [c.upper() for c in iso(ident)]
        if cc in ("us", "ca", "au"):
            also += [c.split("-", 1)[1].upper() for c in codes(prop(ident, "iso3166-2")) if "-" in c]
        for c in ccs:
            gn_name, iso3, _ = countries.get(c, ("", "", []))
            also += [gn_name] + NICKNAMES.get(c, []) + ([] if part else [iso3])
        if part and cc != "us":
            also.append(prop(ident, "name"))
        if ident not in US_GROUPS:
            also += [t[1] for t in biggest]
            if part and cc != "us" and biggest:
                also += [states.get(f"{biggest[0][5]}.{biggest[0][4]}".lower(), "")]
        r = {"id": ident, "name": name, "group": group, "pbf": pbf_url[ident][len(GEOFABRIK):], "bbox": box,
             "country": cc, "home": home, "units": "imperial" if cc in IMPERIAL else "metric", "langs": langs}
        also = sorted({a for a in also if a and fold(a) != fold(name)}, key=fold)
        if also:
            r["also"] = also
        if ph:
            r["photon"] = ph[0] + ph[1]
            # Address search covers the whole country, or the region of the world where a country has none of its own.
            where = (ph[0].split("/")[0].replace("-", " ").title() if ph[2] else
                     "the United States" if cc == "us" else countries.get(cc, (name,))[0])
            if fold(where) != fold(name):
                r["addresses"] = where
        r["_pbf_bytes"] = size[ident]
        r["_polys"] = polys
        regions.append(r)

    # A group of US states says which: "US Northeast (CT, MA, ...)".
    abbr = {r["id"]: [a for a in r.get("also", []) if re.fullmatch(r"[A-Z]{2}", a) and a != "US"]
            for r in regions if r["country"] == "us" and r["id"] not in US_GROUPS}
    for g in [r for r in regions if r["id"] in US_GROUPS]:
        covered = sorted(abbr[r["id"]][0] for r in regions
                         if abbr.get(r["id"]) and in_polys(r["home"]["lon"], r["home"]["lat"], g["_polys"]))
        if covered:
            g["name"] += f" ({', '.join(covered)})"
    for r in regions:
        del r["_polys"]

    photon_sizes = sizes(sorted({photon_base + r["photon"] for r in regions if "photon" in r}))
    for r in regions:
        pbf = r.pop("_pbf_bytes") or 0
        addr = photon_sizes.get(photon_base + r.get("photon", "")) or 0
        tiles = kit.tiles_estimate(r["bbox"], 15, pbf)
        r["mb"] = {"tiles": round(tiles / 1e6), "roads": round(pbf / 1e6), "addresses": round(addr / 1e6)}

    languages = {}
    for code in sorted(used_langs):
        e, flavour = wikipedia(code)
        if not e:
            warn(f"no Wikipedia for '{code}' in the Kiwix catalog")
            continue
        en, native = NAMES.get(code, (code, code))
        if code not in NAMES:
            warn(f"no name for language '{code}'; add it to NAMES")
        languages[code] = {"name": en, "native": native, "zim": e["prefix"], "mb": round((e.get("size") or 0) / 1e6),
                           "pictures": flavour == "maxi"}

    order = {"United States": "0"}
    regions.sort(key=lambda r: (order.get(r["group"], "1" + r["group"]), fold(r["name"])))
    check(regions, languages)

    print("\nPhoton pages read:")
    for path, rows in sorted(photon_pages.items()):
        print(f"  /{path}: " + "; ".join(f"{r['slug']}{'*' if r['db'] else ''} [{','.join(r['codes'][:6])}]" for r in rows[:40]))
    print("\nPlaces:")
    for r in regions:
        print(f"  {r['group'][:14]:<15}{r['id'][:28]:<29}{r['name'][:34]:<35}{r['mb']['roads']:>6} MB roads"
              f"{r['mb']['addresses']:>7} MB addr  home {r['home']['label']}  {'/'.join(r['langs'])}  {r.get('photon', '-')}")
    print("\nLanguages: " + ", ".join(f"{c} {v['zim']} {v['mb'] / 1000:.0f} GB" for c, v in languages.items()))

    lines = ['{',
             ' "_readme": "Made by site/build_regions.py from Geofabrik, Photon, Kiwix and GeoNames. Don\'t edit by hand: '
             'set your own area in kit.json\'s maps instead.",',
             ' "languages": {']
    lines += [f'  {json.dumps(c)}: {json.dumps(v, ensure_ascii=False)}' + ("," if n < len(languages) - 1 else "")
              for n, (c, v) in enumerate(languages.items())]
    lines += [' },', ' "regions": [']
    lines += ["  " + json.dumps(r, ensure_ascii=False) + ("," if n < len(regions) - 1 else "") for n, r in enumerate(regions)]
    lines += [" ]", "}", ""]
    text = "\n".join(lines)
    json.loads(text)
    args.out.write_text(text, encoding="utf-8")
    print(f"\nwrote {len(regions)} places and {len(languages)} languages to {args.out}" +
          (f", with {len(warnings)} warnings" if warnings else ""))
    if args.print:
        blob = base64.b64encode(gzip.compress(text.encode("utf-8"), 9)).decode()
        print("===== regions.json.gz.b64 begin =====")
        for i in range(0, len(blob), 76):
            print(blob[i:i + 76])
        print("===== regions.json.gz.b64 end =====")


def check(regions, languages):
    """The kit downloads from what this file says: only Geofabrik paths and Photon folders, nothing else."""
    bad = []
    ids = set()
    for r in regions:
        if r["id"] in ids:
            bad.append(f"{r['id']}: listed twice")
        ids.add(r["id"])
        w, s, e, n = r["bbox"]
        h = r["home"]
        if not (PBF_PATH.match(r["pbf"]) and ".." not in r["pbf"]):
            bad.append(f"{r['id']}: bad road data path {r['pbf']}")
        if "photon" in r and not (SAFE.match(r["photon"].rsplit("/", 1)[0]) and ".." not in r["photon"]
                                  and re.fullmatch(r"photon-db-[a-z0-9_-]+-\d+\.\d+-latest\.tar\.bz2", r["photon"].rsplit("/", 1)[1])):
            bad.append(f"{r['id']}: bad address database path {r['photon']}")
        if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
            bad.append(f"{r['id']}: bad area {r['bbox']}")
        if not (s <= h["lat"] <= n and w <= h["lon"] <= e):
            bad.append(f"{r['id']}: home {h} is outside its area")
        if not all(c in languages for c in r["langs"]):
            bad.append(f"{r['id']}: a language has no Wikipedia: {r['langs']}")
    for c, v in languages.items():
        if not re.fullmatch(r"wikipedia_[a-z-]+_all_(maxi|nopic|mini)", v["zim"]):
            bad.append(f"language {c}: bad Wikipedia name {v['zim']}")
    if bad:
        sys.exit("regions.json would be wrong:\n  " + "\n  ".join(bad))


if __name__ == "__main__":
    main()
