"""Smoke test the website: build site/ (a static Next.js app), serve the build locally, and drive it in headless
Chromium. usage: python3 tests/site_test.py   (needs Node, and: pip install playwright && playwright install chromium)
Set KIT_AXE to axe-core's axe.min.js (node_modules/axe-core/axe.min.js, after npm ci --ignore-scripts in the repo root)
to also check accessibility."""
import datetime
import functools
import glob
import http.server
import json
import os
import re
import struct
import subprocess
import sys
import threading
from playwright.sync_api import sync_playwright

SITE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "site")
OUT = os.path.join(SITE, "out")     # what next build writes, and what Vercel serves
SHOTS = os.environ.get("KIT_TEST_SHOTS", os.path.join(os.path.dirname(__file__), "work", "shots"))
os.makedirs(SHOTS, exist_ok=True)
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + (f": {detail}" if detail else ""))
    fails += 0 if ok else 1


def axe(page, label):
    if os.environ.get("KIT_AXE"):
        page.add_script_tag(path=os.environ["KIT_AXE"])
        bad = page.evaluate("axe.run().then(r => r.violations.map(v => v.id + ' (' + v.nodes.length + ')'))")
        check(f"{label}: no accessibility violations (axe)", not bad, ", ".join(bad))


if not os.path.isdir(os.path.join(SITE, "node_modules")):
    subprocess.run(["npm", "ci", "--ignore-scripts"], cwd=SITE, check=True)
subprocess.run(["npm", "run", "build"], cwd=SITE, check=True, env={**os.environ, "NEXT_TELEMETRY_DISABLED": "1"})

# Serve with the same headers Vercel adds (site/vercel.json), so a too-strict CSP fails here first.
HEADERS = json.load(open(os.path.join(SITE, "vercel.json")))["headers"][0]["headers"]


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def end_headers(self):
        for h in HEADERS:
            self.send_header(h["key"], h["value"])
        super().end_headers()


handler = functools.partial(Quiet, directory=OUT)
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}/"
FRAME = "document.querySelector('.fig canvas').toDataURL()"
INKED = """(() => { const c = document.querySelector('.fig canvas'), d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
  let n = 0; for (let i = 3; i < d.length; i += 4) n += d[i] > 0; return n; })()"""
# Star on GitHub: beside the two main buttons, or under them when the row is full, and above the download note
STAR = """(() => { const r = s => document.querySelector(s).getBoundingClientRect(), s = r('.ctas .star'), g = r('.ctas .btn:not(.primary)'), n = r('.cta-note');
  if (!s.height || s.bottom > n.top) return 'misplaced';
  return Math.abs(s.top + s.height / 2 - g.top - g.height / 2) < 8 ? 'beside' : s.top >= g.bottom ? 'below' : 'misplaced'; })()"""

# Travis: never mention 2 TB; the drive's size isn't the point
copy = glob.glob(os.path.join(SITE, "app", "**", "*.jsx"), recursive=True) + glob.glob(os.path.join(SITE, "components", "**", "*.js*"), recursive=True)
site_text = " ".join(open(f, encoding="utf-8").read() for f in copy + [os.path.join(SITE, "public", "llms.txt")])
check("the site never mentions 2 TB", not re.search(r"\b2(\s|&nbsp;)*TB\b", site_text, re.I))
# Travis: people update whenever they like, so no copy names a schedule
check("the site names no update schedule", not re.search(r"\bmonths?\b|\bquarterly\b", site_text, re.I))
# the check-the-code prompt sends people's AIs to these files, so they have to exist
named = re.findall(r"SETUP\.command|SETUP-Windows\.bat|tools/\w+\.py|mac/", open(os.path.join(SITE, "components", "prompts.js"), encoding="utf-8").read())
gone = [f for f in named if not os.path.exists(os.path.join(SITE, "..", f))]
check("the check-the-code prompt names files that exist", len(named) >= 5 and not gone, ", ".join(gone))



def choose(page, select, option, group=None):
    """Picks an option in one of the builder's dropdowns: by its exact text, or a pattern, within a group if given."""
    page.click(select)
    scope = page.locator("[role=listbox]")
    if group:
        scope = scope.locator("[role=group]", has=page.get_by_text(group, exact=True))
    scope.get_by_role("option", name=option, exact=isinstance(option, str)).click()
    page.wait_for_selector("[role=listbox]", state="detached")


with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.environ.get("KIT_CHROMIUM") or None)
    for name, vp in (("desktop", {"width": 1440, "height": 900}), ("phone", {"width": 390, "height": 844})):
        page = b.new_page(viewport=vp, accept_downloads=True)
        errors, offsite = [], []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("request", lambda r: None if r.url.startswith((URL, "data:", "blob:")) else offsite.append(r.url))
        page.goto(URL)
        page.wait_for_selector(".card")
        faces = page.evaluate("document.fonts.ready.then(() => [...document.fonts].map(f => f.family.replace(/\"/g, '') + ' ' + f.weight + ': ' + f.status))")
        own = [f for f in faces if "Fallback" not in f]     # next/font's size-matched stand-ins come from the computer, if it has them
        check(f"{name}: fonts load from the site", not [f for f in own if f.endswith("error")]
              and all(any(f.startswith(fam) and f.endswith("loaded") for f in own) for fam in ("plexSans", "plexMono")), ", ".join(faces))
        # the hero is drawn on a canvas each frame: it should move, and hold still once paused
        page.locator(".fig canvas").scroll_into_view_if_needed()
        inked = page.evaluate(INKED)
        before = page.evaluate(FRAME)
        page.wait_for_timeout(250)
        check(f"{name}: hero draws and moves", inked > 5000 and page.evaluate(FRAME) != before, f"{inked} inked pixels")
        playing_clean = not page.is_visible(".viz-state")
        page.click(".viz-toggle")
        page.evaluate("new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")   # let a queued redraw land
        before = page.evaluate(FRAME)
        page.wait_for_timeout(250)
        check(f"{name}: clicking the hero pauses it, and nothing but a paused hero shows a control", playing_clean
              and page.evaluate(FRAME) == before and page.get_attribute(".viz-toggle", "aria-pressed") == "true" and page.is_visible(".viz-state"))
        page.click(".viz-toggle")
        totals = {}
        for preset in ("essentials", "everything", "no-ai", "recommended"):
            page.click(f"[data-preset={preset}]")
            totals[preset] = int(page.inner_text("#totalText").split("ABOUT ")[1].split(" GB")[0])
            if preset == "no-ai":
                models = page.locator(".group", has=page.locator("h3", has_text="AI models")).locator("[role=checkbox][aria-checked=true]").count()
        check(f"{name}: presets order by size", totals["essentials"] < totals["recommended"] < totals["everything"], str(totals))
        check(f"{name}: No AI picks no models and is smaller than Recommended", models == 0 and totals["no-ai"] < totals["recommended"],
              f"{models} models, {totals}")
        width = page.evaluate("document.documentElement.scrollWidth")
        check(f"{name}: no sideways scroll", width <= vp["width"], f"{width}px")
        star, where = page.locator(".ctas .star"), page.evaluate(STAR)
        check(f"{name}: Star on GitHub sits {'beside' if name == 'desktop' else 'under'} the main buttons",
              where == ("beside" if name == "desktop" else "below") and star.inner_text().strip() == "Star on GitHub"
              and star.get_attribute("href") == "https://github.com/tudor-city-ventures/tinfoil-kit", where)
        if name == "phone":
            page.set_viewport_size({"width": 320, "height": 640})    # the narrowest width WCAG asks a page to fit
            width = page.evaluate("document.documentElement.scrollWidth")
            check("320px phone: no sideways scroll", width <= 320, f"{width}px")
            page.set_viewport_size(vp)
            closed = page.is_visible("#menu") and not page.is_visible("nav.links a[href='#faq']")
            page.click("#menu")
            opened = page.is_visible("nav.links a[href='#faq']") and page.get_attribute("#menu", "aria-expanded") == "true"
            page.click("nav.links a[href='#faq']")
            check("phone: sections sit behind Menu, which closes after a pick", closed and opened
                  and page.get_attribute("#menu", "aria-expanded") == "false" and not page.is_visible("nav.links a[href='#faq']"))
        else:
            check("desktop: sections listed, no Menu button", page.is_visible("nav.links a[href='#faq']") and not page.is_visible("#menu"))
        first = page.locator(".card [role=checkbox]").first
        before = page.inner_text("#totalText")
        first.uncheck()
        check(f"{name}: unticking a source changes the total", page.inner_text("#totalText") != before)
        check(f"{name}: no page errors", not errors, "; ".join(errors))
        check(f"{name}: nothing loads from other sites", not offsite, ", ".join(offsite))
        axe(page, name)
        if name == "desktop":
            page.context.grant_permissions(["clipboard-read", "clipboard-write"])
            page.click("[data-copy=installPrompt]")
            page.wait_for_selector("[data-copy=installPrompt]:text-is('Copied')", timeout=5000)   # (the CSP blocks wait_for_function)
            check("Copy puts the prompt on the clipboard", page.evaluate("navigator.clipboard.readText()").startswith("I want to set up Tinfoil Kit"))
            # Travis: AI setup is the main button, Download the second; step 2 of How it works opens the same prompt
            check("the hero's main button is Set up with your AI, then Download",
                  page.inner_text(".ctas .btn.primary") == "Set up with your AI" and page.locator(".ctas .btn").nth(1).get_attribute("id") == "getKit")
            page.evaluate("navigator.clipboard.writeText('')")
            page.click("#askAI")
            opened = page.evaluate("document.getElementById('aiSetup').open") and not page.is_visible("#aiSetup .dl-phone")
            page.click("#copyHero")
            page.wait_for_selector("#copyHero:text-is('Copied')", timeout=5000)
            check("Set up with your AI shows the setup prompt, and Copy copies it", opened
                  and page.evaluate("navigator.clipboard.readText()") == page.text_content("#installPrompt"))
            page.keyboard.press("Escape")
            steps = page.locator("#how .how-steps h3").all_inner_texts()
            page.click("#how a[href='#prompts']")
            check("How it works: get a drive, have your AI set it up, use it anywhere; step 2 opens the prompt",
                  len(steps) == 3 and "external" in steps[0] and "AI" in steps[1] and page.evaluate("document.getElementById('aiSetup').open"), str(steps))
            page.keyboard.press("Escape")
            page.click("[data-copy=auditPrompt]")
            page.wait_for_selector("[data-copy=auditPrompt]:text-is('Copied')", timeout=5000)
            audit = page.evaluate("navigator.clipboard.readText()")
            check("Check the code: the prompt has the AI read the code and run nothing",
                  "https://github.com/tudor-city-ventures/tinfoil-kit" in audit and "Don't install or run anything" in audit)
            for pid, label in (("installPrompt", "Install ours"), ("ownPrompt", "Build your own")):
                text = page.text_content("#" + pid).lower()
                missing = [w for w in ("opt in or out", "ai", "maps", "wikipedia", "medical", "preparedness", "repair",
                                       "courses", "home") if w not in text]
                check(f"{label}: the prompt lets you opt in or out of each part", not missing, ", ".join(missing))
            old = b.new_page()    # a browser without the clipboard API (e.g. the page opened over plain http)
            old.add_init_script("Object.defineProperty(Navigator.prototype, 'clipboard', {get: () => undefined})")
            old.goto(URL)
            old.wait_for_selector(".card")
            old.click("#copySetup")
            check("Copy works without the clipboard API", old.inner_text("#toast").startswith("Copied."), old.inner_text("#toast"))
            old.close()
            stuck = b.new_page()    # nothing can copy: the prompt shows, selected, for Cmd-C
            stuck.add_init_script("Object.defineProperty(Navigator.prototype, 'clipboard', {get: () => undefined});"
                                  "Document.prototype.execCommand = () => false")
            stuck.goto(URL)
            stuck.wait_for_selector(".card")
            stuck.click("#copySetup")
            check("when nothing can copy, the setup prompt shows selected", stuck.is_visible("#setupText")
                  and stuck.evaluate("getSelection().toString()").startswith("I want to set up Tinfoil Kit"), stuck.inner_text("#toast"))
            stuck.close()
            unticked = page.locator(".card strong").first.inner_text()
            # Where you live: sets the map card and Wikipedia's language, and goes into the setup prompt
            regions = json.load(open(os.path.join(SITE, "regions.json"), encoding="utf-8"))["regions"]
            home = next(r["name"] for r in regions if r["id"] == json.load(open(os.path.join(SITE, "kit.json")))["maps"]["region"])
            wiki_titles = "[...document.querySelectorAll('.card strong')].map(e => e.textContent).filter(t => t.startsWith('Wikipedia'))"
            check("the builder starts at kit.json's place, with Wikipedia in English",
                  page.inner_text("#place") == home and page.evaluate(wiki_titles) == ["Wikipedia, with images"]
                  and page.inner_text("#wikiLang").startswith("English"), page.inner_text("#place"))
            page.click("#place")
            groups = page.evaluate("[...document.querySelectorAll('[role=listbox] [role=group]')].map(g => "
                                   "[g.querySelector('[data-slot=select-label]').textContent, g.querySelectorAll('[role=option]').length])")
            page.locator("[role=listbox]").screenshot(path=os.path.join(SHOTS, "site_place_list.png"))
            page.keyboard.press("Escape")
            us_areas = sum(1 for r in regions if r["group"] == "United States" and "/" not in r["id"])
            check("the place dropdown lists every place, by part of the world: groups of US states on top, then the states",
                  len(groups) >= 7 and groups[0] == ["Groups of US states", us_areas] and groups[1][0] == "US states"
                  and sum(n for _, n in groups) == len(regions), str(groups))
            before = page.inner_text("#totalText")
            choose(page, "#place", "Germany: Bayern")
            maps_why = page.locator(".card", has_text="Offline maps").locator(".why").inner_text()
            check("a place sets the map card and offers its language first",
                  page.inner_text("#place") == "Germany: Bayern" and "Germany: Bayern" in maps_why
                  and "address search for all of Germany" in maps_why
                  and page.inner_text("#wikiLang").startswith("German")
                  and page.evaluate(wiki_titles) == ["Wikipedia in German, with images"] and page.inner_text("#totalText") != before,
                  maps_why)
            choose(page, "#wikiLang", re.compile(r"^German and English \("))
            check("two languages: a Wikipedia card for each", page.evaluate(wiki_titles) == ["Wikipedia in German, with images",
                                                                                         "Wikipedia, with images"])
            choose(page, "#wikiLang", re.compile(r"^German \("))
            page.click("#copySetup")
            page.wait_for_selector("#toast:has-text('Copied')", timeout=5000)
            prompt = page.evaluate("navigator.clipboard.readText()")
            ticked = page.evaluate("[...document.querySelectorAll('.card')].filter(c => c.querySelector('[role=checkbox]').ariaChecked === 'true')"
                                   ".map(c => c.querySelector('strong').textContent)")
            check("the setup prompt lists the picks, and not what was unticked", "- Wikipedia in German, with images (" in prompt
                  and all("- " + t + " (" in prompt for t in ticked) and "- " + unticked + " (" not in prompt, unticked)
            check("the setup prompt says where you live, as a ./kit region command", "./kit region bayern --wikipedia de" in prompt)
            us_georgia = next(r["name"] for r in regions if r["id"] == "us/georgia")
            page.click("#place")
            in_us = page.locator("[role=listbox] [role=group]", has=page.get_by_text("US states", exact=True)).get_by_role("option", name=us_georgia, exact=True).count()
            page.keyboard.press("Escape")
            choose(page, "#place", "Georgia", group="Europe")
            check("the builder: two places called Georgia, the country under Europe", in_us == 1
                  and "for Georgia" in page.locator(".card", has_text="Offline maps").locator(".why").inner_text()
                  and page.inner_text("#wikiLang").startswith("Georgian"), us_georgia)
            page.locator(".where").screenshot(path=os.path.join(SHOTS, "site_place_picker.png"))
        # Read as: the human page is the default; AI agent shows the markdown with no images or icons, and the pick sticks
        def wide_enough(label):
            w = page.evaluate("document.documentElement.scrollWidth")
            check(f"{label}: no sideways scroll", w <= page.viewport_size["width"], f"{w}px")
        check(f"{name}: the human page is the default", page.is_visible(".hero h1") and not page.is_visible("#instructions"))
        page.click(".readas [data-reader=agent]")
        page.wait_for_selector("#agentDoc b", timeout=5000)   # heading lines are bold once llms.txt loads
        pictures = page.evaluate("[...document.querySelectorAll('img, svg, canvas')].filter(e => e.getClientRects().length).length")
        check(f"{name}: AI agent shows the markdown, with no images or icons", page.inner_text("#agentDoc").startswith("# Tinfoil Kit")
              and not page.is_visible(".hero") and not page.is_visible("#builder") and not pictures
              and page.is_visible("nav.links a[href='/llms.txt']") and not page.is_visible("#menu")
              and "for=agent" in page.url and page.get_attribute(".readas [data-reader=agent]", "aria-pressed") == "true",
              f"{pictures} images or icons showing")
        if name == "desktop":
            page.click("[data-copy=agentDoc]")
            page.wait_for_selector("[data-copy=agentDoc]:text-is('Copied')", timeout=5000)
            check("Copy puts the markdown on the clipboard", page.evaluate("navigator.clipboard.readText()") == open(os.path.join(SITE, "public", "llms.txt")).read())
        wide_enough(f"{name} agent page")
        if name == "phone":
            page.set_viewport_size({"width": 320, "height": 640})
            wide_enough("320px phone agent page")
            page.set_viewport_size(vp)
        axe(page, f"{name} agent page")
        page.screenshot(path=os.path.join(SHOTS, f"site_{name}_agent.png"), full_page=True)
        page.goto(URL)
        check(f"{name}: the pick sticks on the next visit", page.is_visible("#instructions") and not page.is_visible(".hero"))
        page.wait_for_selector(".card", state="attached")
        page.click(".readas [data-reader=human]")
        check(f"{name}: Human switches back", page.is_visible(".hero h1") and page.is_visible(".fig") and "for=" not in page.url)
        page.screenshot(path=os.path.join(SHOTS, f"site_{name}.png"), full_page=True)
    # Download: the button gets this computer's file, and the dialog says what to click next. GitHub's answer is
    # stood in for here: an attachment, as its release files come, so the page stays put.
    def attach(route):
        route.fulfill(status=200, headers={"Content-Type": "application/octet-stream",
                      "Content-Disposition": "attachment; filename=" + route.request.url.rsplit("/", 1)[1]}, body=b"kit")
    REL = "https://github.com/tudor-city-ventures/tinfoil-kit/releases/latest/download/"
    FILES = {"mac": "TinfoilKit-Mac.zip", "windows": "TinfoilKit-Windows.zip", "linux": "TinfoilKit.tar.gz"}
    UAS = {"mac": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.1 Safari/605.1.15",
           "windows": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
           "linux": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"}
    VIEWS = "[...document.querySelectorAll('#downloads [data-view]')].filter(v => !v.hidden).map(v => v.dataset.view)"
    for os_, ua in UAS.items():
        ctx = b.new_context(user_agent=ua, accept_downloads=True, viewport={"width": 1280, "height": 900})
        pg, errs = ctx.new_page(), []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route("https://github.com/**", attach)
        pg.goto(URL)
        pg.wait_for_selector(".card")
        label, href = pg.inner_text("#getKit"), pg.get_attribute("#getKit", "href")
        with pg.expect_download() as dl:
            pg.click("#getKit")
        check(f"{os_}: Download gets {FILES[os_]} and says what to click next", label.startswith("Download for ")
              and href == REL + FILES[os_] and dl.value.suggested_filename == FILES[os_] and pg.url == URL
              and pg.evaluate("document.getElementById('downloads').open") and pg.evaluate(VIEWS) == [os_] and not errs,
              f"{label}, {href}, {pg.evaluate(VIEWS)}, {errs}")
        if os_ == "mac":
            check("mac: the steps show what macOS asks before it opens the app, and what to click",
                  "Move to Applications" in pg.inner_text("#downloads") and pg.is_visible("#downloads .mac-alert .hit"))
            pg.locator("#downloads").screenshot(path=os.path.join(SHOTS, "site_download_mac.png"))
            axe(pg, "download steps for a Mac")
            pg.click("#downloads [data-view=mac] .dl-back")
            links = pg.evaluate("[...document.querySelectorAll('.dl-list li')].map(l => l.dataset.os + ' ' + l.querySelector('a').href)")
            check("All downloads lists every computer's file, this one's first",
                  links == [f"{o} {REL}{FILES[o]}" for o in ("mac", "windows", "linux")] and pg.evaluate(VIEWS) == ["all"], str(links))
            pg.keyboard.press("Escape")
            check("Escape closes the dialog", not pg.evaluate("document.getElementById('downloads').open"))
        ctx.close()
    ctx = b.new_context(**p.devices["iPhone 15"])
    pg = ctx.new_page()
    pg.goto(URL)
    pg.wait_for_selector(".card")
    pg.click("#getKit")
    check("phone: Download lists every computer's file and says it runs on a laptop",
          pg.evaluate("document.getElementById('downloads').open") and pg.evaluate(VIEWS) == ["all"]
          and pg.is_visible("#downloads .dl-phone") and pg.inner_text("#getKit") == "Download free")
    box = pg.locator("#downloads").bounding_box()
    check("phone: the dialog fits the screen", box and box["x"] >= 0 and box["x"] + box["width"] <= 393, str(box))
    axe(pg, "All downloads on a phone")
    pg.screenshot(path=os.path.join(SHOTS, "site_download_all_phone.png"))
    pg.keyboard.press("Escape")
    pg.click("#askAI")
    check("phone: Set up with your AI says to do it on the computer", pg.is_visible("#aiSetup .dl-phone"))
    box = pg.locator("#aiSetup").bounding_box()
    check("phone: the AI setup dialog fits the screen", box and box["x"] >= 0 and box["x"] + box["width"] <= 393, str(box))
    axe(pg, "AI setup on a phone")
    ctx.close()
    deep = b.new_page()        # a shared link opens the version it names
    deep.goto(URL + "?for=agent")
    deep.wait_for_selector("#agentDoc b", timeout=5000)
    check("?for=agent opens the agent page", deep.is_visible("#instructions") and not deep.is_visible(".hero"))
    deep.close()
    still = b.new_page(reduced_motion="reduce")
    still.goto(URL)
    still.wait_for_selector(".card")
    still.wait_for_timeout(500)        # it redraws once its sizes and fonts arrive, then should stop
    before = still.evaluate(FRAME)
    still.wait_for_timeout(300)
    check("reduced motion: the hero holds one still frame", still.evaluate(INKED) > 5000 and still.evaluate(FRAME) == before
          and still.get_attribute(".viz-toggle", "aria-pressed") == "true")
    still.close()
    nf = b.new_page()     # Vercel serves 404.html for any unknown address
    nf.goto(URL + "404.html")
    check("404 page links home", nf.get_attribute("a", "href") == "/" and "isn't here" in nf.inner_text("h1"))
    if os.environ.get("KIT_AXE"):
        nf.add_script_tag(path=os.environ["KIT_AXE"])
        bad = nf.evaluate("axe.run().then(r => r.violations.map(v => v.id + ' (' + v.nodes.length + ')'))")
        check("404 page: no accessibility violations (axe)", not bad, ", ".join(bad))
    nf.screenshot(path=os.path.join(SHOTS, "site_404.png"))
    home = b.new_page()
    home.goto(URL)
    refs = home.evaluate("""[...document.querySelectorAll('link[rel~=icon], link[rel=apple-touch-icon]')].map(l => l.getAttribute('href'))
        .concat(new URL(document.querySelector('meta[property="og:image"]').content).pathname)""")
    missing = [r for r in refs if home.request.get(URL + r.lstrip("/")).status != 200]
    check("icons and the link-preview card are all served", len(refs) == 4 and not missing, ", ".join(missing) or str(refs))
    card = home.request.get(URL + "og.png").body()
    size = struct.unpack(">II", card[16:24])     # a PNG's width and height sit in its first chunk
    check("link-preview card is the size its tags say", size == (1200, 630), "%dx%d" % size)
    # search engines and AI answer engines: robots.txt lets every crawler in and names the sitemap, the sitemap lists
    # the canonical address, and the JSON-LD describes the kit there
    canonical = home.get_attribute("link[rel=canonical]", "href")
    robots = home.request.get(URL + "robots.txt").text()
    check("robots.txt lets every crawler in and names the sitemap", "User-agent: *" in robots and "Disallow" not in robots
          and f"Sitemap: {canonical}sitemap.xml" in robots)
    # security.txt (RFC 9116) tells researchers where to report; it must be renewed before it expires
    sectxt = home.request.get(URL + ".well-known/security.txt").text()
    expires = re.search(r"^Expires: (\d{4}-\d\d-\d\d)", sectxt, re.M)
    check("security.txt names the private report form and isn't within 30 days of expiring (bump its Expires)",
          "Contact: https://github.com/tudor-city-ventures/tinfoil-kit/security/advisories/new" in sectxt and expires
          and datetime.date.fromisoformat(expires.group(1)) - datetime.date.today() > datetime.timedelta(days=30))
    locs = re.findall(r"<loc>(.*?)</loc>", home.request.get(URL + "sitemap.xml").text())
    check("sitemap.xml lists the canonical address", locs == [canonical], str(locs))
    ld = [json.loads(t) for t in home.eval_on_selector_all("script[type='application/ld+json']", "s => s.map(e => e.textContent)")]
    app = [n for d in ld for n in d.get("@graph", [d]) if n["@type"] == "SoftwareApplication"]
    check("structured data describes Tinfoil Kit, free, at the canonical address", len(app) == 1 and app[0]["name"] == "Tinfoil Kit"
          and app[0]["url"] == canonical and app[0]["offers"]["price"] == "0", json.dumps(app)[:200])
    # each FAQ entry is a schema.org Question and Answer they can quote, and the first defines the kit on its own
    faq = home.evaluate("""[...document.querySelectorAll('.faq[itemscope][itemtype="https://schema.org/FAQPage"] > details')].map(d =>
        d.matches('[itemscope][itemprop=mainEntity][itemtype="https://schema.org/Question"]') && [d.querySelector(':scope > summary[itemprop=name]'),
        d.querySelector(':scope > [itemscope][itemprop=acceptedAnswer][itemtype="https://schema.org/Answer"] > [itemprop=text]')].map(e => e && e.textContent))""")
    total = home.locator(".faq details").count()
    check("every FAQ entry is marked up as a question and its answer", total and len(faq) == total and all(f and all(f) for f in faq),
          f"{sum(bool(f and all(f)) for f in faq)} of {total}")
    check("the FAQ opens by saying what Tinfoil Kit is", bool(faq and faq[0] and faq[0][0] == "What is Tinfoil Kit?"
          and faq[0][1].startswith("Tinfoil Kit is ")))
    b.close()
srv.shutdown()
print("\nALL PASSED" if not fails else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
