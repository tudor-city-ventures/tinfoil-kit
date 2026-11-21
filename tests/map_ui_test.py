"""Drive the real portal map in headless Chrome: real MapLibre + Protomaps style + embedded fonts/icons,
against mock tile / address / routing servers and a mock tool-calling AI."""
import os
import sys
from playwright.sync_api import sync_playwright

SHOTS = os.environ.get("KIT_TEST_SHOTS", os.path.join(os.path.dirname(__file__), "work", "shots"))
os.makedirs(SHOTS, exist_ok=True)

BASE = "http://127.0.0.1:18888"
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + (f": {detail}" if detail else ""))
    fails += 0 if ok else 1


def watch(page, errors, warnings):
    page.on("console", lambda m: (errors if m.type == "error" else warnings if m.type == "warning" else []).append(m.text))
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("response", lambda r: print("   HTTP", r.status, r.url[:120]) if r.status >= 400 else None)


with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    page = b.new_page(viewport={"width": 1280, "height": 860})
    errors, warnings = [], []
    watch(page, errors, warnings)
    page.goto(BASE + "/?model=Tiny&ai=18080")
    page.wait_for_function("document.getElementById('mapStatus').textContent.includes('Directions: ready')", timeout=30000)
    check("map services detected", "Address search: ready" in page.inner_text("#mapStatus"), page.inner_text("#mapStatus"))
    page.click("nav a[data-tab=map]")
    page.wait_for_function("window.__kitMap && window.__kitMap.loaded() && window.__kitMap.isStyleLoaded()", timeout=60000)
    check("map loads (style, sprite, tiles)", True)
    page.wait_for_timeout(1500)
    hits = page.evaluate("window.__kitHits")
    check("icons served from the page itself", hits["sprite"] >= 1, str(hits))
    layers = page.evaluate("window.__kitMap.getStyle().layers.length")
    check("Protomaps style layers", layers > 50, f"{layers} layers")
    check("home marker shown", page.locator(".maplibregl-marker").count() == 1)
    check("home label", "Westchester" in page.inner_text("#homeLabel"), page.inner_text("#homeLabel"))
    modes = page.eval_on_selector_all("#dirMode option", "els => els.map(e => e.textContent)")
    check("travel modes", modes == ["Drive", "Walk"], str(modes))
    page.screenshot(path=os.path.join(SHOTS, "shot_map.png"))

    # search an address, pick it
    page.fill("#placeQ", "100 Main Street White Plains")
    page.wait_for_selector("#placeResults div[data-i]", timeout=10000)
    first = page.inner_text("#placeResults div[data-i]")
    check("address suggestions", "100 Main Street" in first, first.replace("\n", " "))
    page.click("#placeResults div[data-i]")
    page.wait_for_timeout(1200)
    check("result marker + popup", page.locator(".maplibregl-marker").count() == 2 and page.locator(".maplibregl-popup").count() == 1)
    page.wait_for_timeout(800)
    hits = page.evaluate("window.__kitHits")
    check("label fonts served from the page itself", hits["glyph"] >= 1, str(hits))
    labels = page.evaluate("window.__kitMap.querySourceFeatures('labels').length")
    check("result label drawn", labels >= 1, f"{labels} label features")

    # "Directions here" from the popup
    page.click(".maplibregl-popup button[data-act=to]")
    page.wait_for_function("document.getElementById('dirSteps').children.length > 0", timeout=10000)
    summary = page.inner_text("#dirSummary")
    check("directions from popup", "driving" in summary and "100 Main Street" in summary and " mi," in summary, summary)
    page.wait_for_timeout(1200)
    route = page.evaluate("window.__kitMap.querySourceFeatures('route').length")
    check("route line drawn", route >= 1, f"{route} route features")

    # typed directions, walking
    page.fill("#dirFrom", "100 Main Street White Plains")
    page.fill("#dirTo", "Westchester Medical")
    page.select_option("#dirMode", "foot")
    page.click("#dirGo")
    page.wait_for_function("document.getElementById('dirSummary').textContent.includes('walking')", timeout=10000)
    steps = page.eval_on_selector_all("#dirSteps li", "els => els.map(e => e.textContent)")
    check("typed walking directions", len(steps) == 3 and "Woods Road" in steps[1], " / ".join(steps))
    page.click("#dirSteps li:nth-child(2)")
    page.wait_for_timeout(1500)
    zoom = page.evaluate("window.__kitMap.getZoom()")
    check("clicking a step zooms to it", zoom > 15, f"zoom {zoom:.1f}")
    page.screenshot(path=os.path.join(SHOTS, "shot_map_route.png"))

    # nearest
    page.fill("#dirFrom", "")
    page.locator("#nearbyChips button", has_text="Hospital").click()
    page.wait_for_function("document.querySelectorAll('#nearbyList li[data-i]').length > 0", timeout=10000)
    near = page.eval_on_selector_all("#nearbyList li[data-i]", "els => els.map(e => e.textContent)")
    check("nearest hospitals", len(near) == 3 and near[0].startswith("White Plains Hospital"), " | ".join(near))
    page.wait_for_timeout(1200)
    check("nearest shown as markers", page.locator(".maplibregl-marker").count() == 4)
    page.screenshot(path=os.path.join(SHOTS, "shot_map_nearby.png"))

    # set home
    page.click("#setHome")
    check("set home to map center", page.inner_text("#homeLabel").startswith("Map point"), page.inner_text("#homeLabel"))
    page.reload()
    page.wait_for_function("document.getElementById('homeLabel').textContent.length > 0", timeout=10000)
    check("home remembered after reload", page.inner_text("#homeLabel").startswith("Map point"), page.inner_text("#homeLabel"))
    page.evaluate("localStorage.clear()")

    errors = [e for e in errors if "favicon" not in e]
    check("no JS errors on the map", not errors, "; ".join(errors)[:600])
    warnings = [w for w in warnings if "GL Driver" not in w]
    check("no map warnings", not warnings, "; ".join(warnings)[:600])

    # Ask: a tool-calling AI answers a map question and the route appears on the map
    p2 = b.new_page(viewport={"width": 1280, "height": 860})
    e2, w2 = [], []
    watch(p2, e2, w2)
    p2.goto(BASE + "/?model=Mock-Tools&ai=18081")
    p2.wait_for_function("document.getElementById('aiStatus').textContent.includes('ready') && "
                         "document.getElementById('mapStatus').textContent.includes('Directions: ready')", timeout=30000)
    p2.fill("#q", "What's the nearest hospital and how do I get there?")
    p2.click("#askBtn")
    p2.wait_for_function("document.getElementById('progress').textContent.startsWith('Done')", timeout=30000)
    ans = p2.inner_text("#answer")
    check("AI map answer", "Mock answer" in ans and "White Plains Hospital" in ans, ans[:140].replace("\n", " "))
    check("sources hidden for map answers", not p2.is_visible("#sources li"))
    p2.click("#openMap")
    p2.wait_for_function("window.__kitMap && window.__kitMap.loaded()", timeout=60000)
    p2.wait_for_timeout(1500)
    steps = p2.eval_on_selector_all("#dirSteps li", "els => els.map(e => e.textContent)")
    check("AI route shown on the map", len(steps) == 3 and p2.evaluate("window.__kitMap.querySourceFeatures('route').length") >= 1,
          p2.inner_text("#dirSummary"))
    p2.screenshot(path=os.path.join(SHOTS, "shot_ask_map.png"))
    p2.click("nav a[data-tab=ask]")
    p2.fill("#q", "Where is the Shire in the story?")     # looks like a map question; the AI answers without the map
    p2.click("#askBtn")
    p2.wait_for_function("document.getElementById('progress').textContent.startsWith('Done in') || "
                         "document.getElementById('progress').textContent.includes('Nothing')", timeout=60000)
    check("AI skips the map -> library answers", "Library answer" in p2.inner_text("#answer") and p2.locator("#openMap").count() == 0,
          p2.inner_text("#progress") + " | " + p2.inner_text("#answer")[:80])
    e2 = [e for e in e2 if "favicon" not in e]
    check("no JS errors (AI map flow)", not e2, "; ".join(e2)[:600])

    # Ask with the AI off: falls back to reading the question itself
    p3 = b.new_page(viewport={"width": 1280, "height": 860})
    e3, w3 = [], []
    watch(p3, e3, w3)
    p3.goto(BASE + "/?model=Tiny&ai=18999")
    p3.wait_for_function("document.getElementById('aiStatus').textContent.includes('off') && "
                         "document.getElementById('mapStatus').textContent.includes('Directions: ready')", timeout=30000)
    p3.fill("#q", "where is the nearest pharmacy?")
    p3.click("#askBtn")
    p3.wait_for_function("document.getElementById('progress').textContent.startsWith('Done')", timeout=30000)
    ans = p3.inner_text("#answer")
    check("map answer without AI", "CVS Pharmacy" in ans and "mi" in ans, ans[:140].replace("\n", " "))
    p3.fill("#q", "directions to Westchester Medical Center")
    p3.click("#askBtn")
    p3.wait_for_function("document.getElementById('answer').textContent.includes('Driving to')", timeout=30000)
    check("directions without AI", "Turn left onto Woods Road" in p3.inner_text("#answer"), p3.inner_text("#answer")[:140].replace("\n", " "))
    p3.fill("#q", "where is Zzyzx Nowhere Road?")         # map-looking, nothing on the map -> library instead
    p3.click("#askBtn")
    p3.wait_for_function("!document.getElementById('progress').textContent.startsWith('Looking')", timeout=60000)
    p3.wait_for_function("document.getElementById('progress').textContent.includes('passages') || "
                         "document.getElementById('progress').textContent.includes('Nothing')", timeout=60000)
    check("nothing on the map -> library", p3.locator("#openMap").count() == 0, p3.inner_text("#progress"))
    p3.fill("#q", "directions to Zzyzx Nowhere")
    p3.click("#askBtn")
    p3.wait_for_function("document.getElementById('answer').textContent.includes('offline map')", timeout=30000)
    check("unknown destination explained", "Couldn't find" in p3.inner_text("#answer"), p3.inner_text("#answer")[:120])
    p3.fill("#q", "how do I purify water?")
    p3.click("#askBtn")
    p3.wait_for_function("document.getElementById('progress').textContent.includes('passages') || "
                         "document.getElementById('progress').textContent.includes('Nothing')", timeout=60000)
    check("non-map questions still go to the library", "Water purification" in p3.inner_text("#answer") or "8 drops" in p3.inner_text("#answer"),
          p3.inner_text("#progress"))
    e3 = [e for e in e3 if "favicon" not in e and "ERR_CONNECTION_REFUSED" not in e]   # the AI is off on purpose
    check("no JS errors (no-AI flow)", not e3, "; ".join(e3)[:600])

    # maps not installed: clear message instead of a broken map
    p4 = b.new_page()
    p4.route("**/*", lambda route: route.continue_())
    p4.add_init_script("Object.defineProperty(window, 'KIT_MAPS', {set(v){}, get(){ return {available:false, reason:'Not downloaded yet: map tiles. Run ./kit sync while online.'}; }})")
    p4.goto(BASE + "/?model=Tiny&ai=18080")
    p4.click("nav a[data-tab=map]")
    check("maps-missing message", p4.is_visible("#mapOff") and "kit sync" in p4.inner_text("#mapOff") and not p4.is_visible("#mapWrap"),
          p4.inner_text("#mapOff"))
    b.close()

print("\nALL PASSED" if not fails else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
