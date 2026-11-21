"""Drive the real portal page in headless Chrome against the live kit servers."""
import os
import sys
from playwright.sync_api import sync_playwright

SHOTS = os.environ.get("KIT_TEST_SHOTS", os.path.join(os.path.dirname(__file__), "work", "shots"))
os.makedirs(SHOTS, exist_ok=True)

URL = "http://localhost:18888/?model=Tiny&ai=18080"   # localhost on purpose: must redirect to 127.0.0.1
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + (f": {detail}" if detail else ""))
    fails += 0 if ok else 1


with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox"])
    page = b.new_page(viewport={"width": 1100, "height": 900})
    errors = []
    page.on("console", lambda m: errors.append(m.text + " @ " + str(m.location)) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("response", lambda r: print("   HTTP", r.status, r.url) if r.status >= 400 else None)
    page.goto(URL)
    page.wait_for_function("document.getElementById('aiStatus').textContent.includes('ready')", timeout=20000)
    check("redirected localhost -> 127.0.0.1", page.url.startswith("http://127.0.0.1:18888/"), page.url)
    check("AI status pill", "ready" in page.inner_text("#aiStatus"))
    opts = page.eval_on_selector_all("#scope option", "els => els.map(e => e.textContent)")
    check("scope options", len(opts) >= 3, " | ".join(opts))
    check("model preselected", page.input_value("#model") == "Tiny")
    page.fill("#q", "How much bleach per gallon of water to make it safe to drink?")
    page.click("#askBtn")
    page.wait_for_function("document.getElementById('progress').textContent.startsWith('Done')", timeout=120000)
    srcs = page.eval_on_selector_all("#sources li a", "els => els.map(e => e.textContent)")
    check("sources listed", "Water purification" in srcs, ", ".join(srcs))
    check("answer rendered", len(page.inner_text("#answer")) > 0)
    page.screenshot(path=os.path.join(SHOTS, "shot_ask.png"), full_page=True)
    href = page.get_attribute("#sources li a", "href")
    r = page.request.get("http://127.0.0.1:18888" + href)
    check("source link opens the article", r.ok and "8 drops" in r.text(), href)
    page.click("nav a[data-tab=library]")
    cards = page.eval_on_selector_all(".book-card a", "els => els.map(e => e.textContent)")
    check("library cards", len(cards) == 2, ", ".join(cards))
    page.screenshot(path=os.path.join(SHOTS, "shot_library.png"), full_page=True)
    page.fill("#libQ", "tourniquet")
    page.click("#libSearch button")
    page.wait_for_load_state()
    check("library search page", "Tourniquet" in page.content(), page.url)
    errors = [e for e in errors if "favicon" not in e]
    check("no JS errors", not errors, "; ".join(errors))

    if os.environ.get("KIT_AXE"):     # axe-core's axe.min.js
        for scheme in ("light", "dark"):
            pa = b.new_page(color_scheme=scheme)
            pa.goto("http://127.0.0.1:18888/?model=Tiny&ai=18080")
            pa.wait_for_function("document.querySelectorAll('#scope option').length > 1", timeout=20000)
            pa.add_script_tag(path=os.environ["KIT_AXE"])
            for tab in ("ask", "map", "library", "help"):
                pa.click(f"nav a[data-tab={tab}]")
                bad = pa.evaluate("axe.run().then(r => r.violations.map(v => v.id + ' (' + v.nodes.length + ')'))")
                check(f"{scheme} mode, {tab} tab: no accessibility violations (axe)", not bad, ", ".join(bad))
            pa.close()

    # AI down, on a phone (how family members use a shared kit): answers fall back to library passages
    page2 = b.new_page(viewport={"width": 390, "height": 844})
    page2.goto("http://127.0.0.1:18888/?model=Tiny&ai=18999")
    page2.wait_for_function("document.getElementById('aiStatus').textContent.includes('off')", timeout=15000)
    page2.fill("#q", "tourniquet placement")
    page2.click("#askBtn")
    page2.wait_for_function("document.getElementById('progress').textContent.includes('passages') || "
                            "document.getElementById('progress').textContent.includes('Nothing')", timeout=60000)
    check("AI-off fallback shows passages", "5 to 7 cm" in page2.inner_text("#answer"), page2.inner_text("#progress"))
    page2.screenshot(path=os.path.join(SHOTS, "shot_ai_off.png"), full_page=True)
    for tab in ("ask", "map", "library", "help"):
        page2.click(f"nav a[data-tab={tab}]")
        width = page2.evaluate("document.documentElement.scrollWidth")
        check(f"phone, {tab} tab: no sideways scroll", width <= 390, f"{width}px")
    b.close()

print("\nALL PASSED" if not fails else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
