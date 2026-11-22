"""One-off probe of Geofabrik's index and download URLs (temporary, branch only)."""
import json, re, subprocess, sys
def sh(*cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.stdout + p.stderr
idx = json.loads(subprocess.run(["curl", "-fsSL", "--max-time", "300", "https://download.geofabrik.de/index-v1.json"], capture_output=True).stdout)
feats = {f["properties"]["id"]: f for f in idx["features"]}
print("top keys:", [k for k in idx if k != "features"])
for i in ("romania", "us-northeast", "bayern", "us/texas", "gcc-states", "afghanistan"):
    if i in feats:
        print(i, json.dumps(feats[i]["properties"]))
for i in ("romania", "us-northeast", "bayern"):
    u = feats[i]["properties"]["urls"]["pbf"]
    flat = re.sub(r"/([^/]+)/\1-latest\.osm\.pbf$", r"/\1-latest.osm.pbf", u)
    for url in dict.fromkeys([u, flat]):
        print("== HEAD", url)
        print("\n".join(l for l in sh("curl", "-sIL", "--max-time", "60", url).splitlines()
                        if re.match(r"(HTTP/|location:|content-length:|last-modified:|server:)", l, re.I)))
html = sh("curl", "-fsSL", "--max-time", "60", "https://download.geofabrik.de/europe.html")
for m in list(re.finditer(r"romania", html))[:3]:
    print("== europe.html:", html[max(0, m.start() - 300):m.start() + 300].replace("\n", " "))
html = sh("curl", "-fsSL", "--max-time", "60", "https://download.geofabrik.de/europe/germany.html")
for m in list(re.finditer(r"bayern", html))[:2]:
    print("== germany.html:", html[max(0, m.start() - 300):m.start() + 300].replace("\n", " "))
