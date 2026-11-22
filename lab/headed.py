import sys
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    kind = sys.argv[1]
    if kind == "webkit":
        b = p.webkit.launch(headless=False)
    elif kind == "msedge":
        b = p.chromium.launch(channel="msedge", headless=False)
    else:
        b = p.chromium.launch(headless=False, args=["--no-sandbox"])
    pg = b.new_page(viewport={"width": 1000, "height": 650})
    pg.goto("https://example.com")
    pg.wait_for_timeout(5000)
    print("headed", kind, "ok")
    b.close()
