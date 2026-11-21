"""Smoke test the website: serve site/ locally, drive the kit builder in headless Chromium.
usage: python3 tests/site_test.py   (needs: pip install playwright && playwright install chromium)"""
import functools
import http.server
import json
import os
import sys
import threading
from playwright.sync_api import sync_playwright

SITE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "site")
SHOTS = os.environ.get("KIT_TEST_SHOTS", os.path.join(os.path.dirname(__file__), "work", "shots"))
os.makedirs(SHOTS, exist_ok=True)
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + (f": {detail}" if detail else ""))
    fails += 0 if ok else 1


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


handler = functools.partial(Quiet, directory=SITE)
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}/"

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.environ.get("KIT_CHROMIUM") or None)
    for name, vp in (("desktop", {"width": 1440, "height": 900}), ("phone", {"width": 390, "height": 844})):
        page = b.new_page(viewport=vp, accept_downloads=True)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("https://fonts.*/**", lambda r: r.abort())   # offline-friendly; fonts aren't under test
        page.goto(URL)
        page.wait_for_selector(".card")
        totals = {}
        for preset in ("essentials", "everything", "recommended"):
            page.click(f"[data-preset={preset}]")
            totals[preset] = int(page.inner_text("#totalText").split("ABOUT ")[1].split(" GB")[0])
        check(f"{name}: presets order by size", totals["essentials"] < totals["recommended"] < totals["everything"], str(totals))
        width = page.evaluate("document.documentElement.scrollWidth")
        check(f"{name}: no sideways scroll", width <= vp["width"], f"{width}px")
        first = page.locator(".card input").first
        before = page.inner_text("#totalText")
        first.uncheck()
        check(f"{name}: unticking a source changes the total", page.inner_text("#totalText") != before)
        check(f"{name}: no page errors", not errors, "; ".join(errors))
        if name == "desktop":
            with page.expect_download() as dl:
                page.click("#downloadKit")
            kit = json.loads(open(dl.value.path()).read())
            off = [m["id"] for m in kit["models"] if not m["enabled"]]
            check("downloaded kit.json reflects the picks", len(off) == 1 and kit["settings"]["default_model"] != off[0], str(off))
        page.screenshot(path=os.path.join(SHOTS, f"site_{name}.png"), full_page=True)
    b.close()
srv.shutdown()
print("\nALL PASSED" if not fails else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
