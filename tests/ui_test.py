"""Drive the real portal page in a headless browser against the live kit servers.
KIT_BROWSER picks chromium (default), webkit (Safari's engine), msedge or chrome; KIT_LIBRARY_PORT and KIT_AI_PORT
the ports. With KIT_SHARE_URL (the address the launcher shows for the home network) and KIT_SHARE_CODE, it also uses
the kit the way a phone on the home network does: through the gate, with the access code, AI chat page included.
With KIT_VIDEO (tests/drive.py record sets it), the page is in a window and goes at a person's pace for the drive
test's videos: typing, pausing on answers, and also opening a source, AI chat, the map and Help."""
import os
import sys
from playwright.sync_api import sync_playwright
from drive import note
from make_tiny_model import ANSWER

SHOTS = os.environ.get("KIT_TEST_SHOTS", os.path.join(os.path.dirname(__file__), "work", "shots"))
os.makedirs(SHOTS, exist_ok=True)

LIB = os.environ.get("KIT_LIBRARY_PORT", "18888")
AI = os.environ.get("KIT_AI_PORT", "18080")
BROWSER = os.environ.get("KIT_BROWSER", "chromium")
URL = f"http://localhost:{LIB}/?model=Tiny&ai={AI}"   # localhost on purpose: must redirect to 127.0.0.1
VIDEO = bool(os.environ.get("KIT_VIDEO"))
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + (f": {detail}" if detail else ""))
    fails += 0 if ok else 1


def intact(page):
    """Is the answer the test model's, as the page shows it (bold, [1] a link to the source), every character intact?
    If not, what arrived, spelled in ASCII so a mangled character shows as its code."""
    shown = page.inner_text("#answer")
    ok = " ".join(shown.split()) == " ".join(ANSWER.replace("**", "").split()) and page.locator("#answer a.cite").count() == 1
    return ok, "" if ok else ascii(shown)[:400]


def pause(page, seconds=2.5):
    """In the video, time to see what's on the page."""
    if VIDEO:
        page.wait_for_timeout(seconds * 1000)


def type_in(page, sel, text):
    if VIDEO:
        page.fill(sel, "")
        page.locator(sel).press_sequentially(text, delay=45)
    else:
        page.fill(sel, text)


def popup(page, sel, then):
    """In the video: click a link that opens a tab (a source, AI chat), show it, close it. Never a failure."""
    try:
        with page.expect_popup() as tab:
            page.click(sel)
        tab.value.wait_for_load_state()
        then(tab.value)
        tab.value.close()
    except Exception as e:
        print(f"(video only: {sel} didn't show: {str(e).splitlines()[0]})")


def chat(tab):
    """llama-server's chat page: type a message with real keys (its editor ignores text set directly), send it."""
    box = tab.locator("textarea:visible, [contenteditable=true]:visible").first
    box.wait_for(timeout=20000)
    pause(tab, 1.5)
    box.click()
    tab.keyboard.type("Hello! What can you help with?", delay=45)
    send = tab.get_by_role("button", name="Send")
    if send.count():
        send.first.click()
    else:
        tab.keyboard.press("Enter")
    tab.wait_for_timeout(9000)


with sync_playwright() as p:
    show = {"headless": not VIDEO, "slow_mo": 150 if VIDEO else 0}
    if BROWSER == "webkit":
        b = p.webkit.launch(**show)
    elif BROWSER in ("msedge", "chrome"):
        b = p.chromium.launch(channel=BROWSER, **show)
    else:
        b = p.chromium.launch(args=["--no-sandbox"], **show)
    size, phone_height = {"width": 1100, "height": 900}, 844
    if VIDEO:    # the window has to fit the screen it's filmed on
        probe = b.new_page()
        w, h = probe.evaluate("[screen.availWidth, screen.availHeight]")
        probe.close()
        size, phone_height = {"width": min(1100, w - 40), "height": min(900, h - 110)}, min(844, h - 110)
    page = b.new_page(viewport=size)
    errors = []
    page.on("console", lambda m: errors.append(m.text + " @ " + str(m.location)) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("response", lambda r: print("   HTTP", r.status, r.url) if r.status >= 400 else None)
    note("The kit's page, as START-HERE opens it. Ask anything: it looks in the offline library first")
    page.goto(URL)
    page.wait_for_function("document.getElementById('aiStatus').textContent.includes('ready')", timeout=20000)
    check("redirected localhost -> 127.0.0.1", page.url.startswith(f"http://127.0.0.1:{LIB}/"), page.url)
    check("AI status pill", "ready" in page.inner_text("#aiStatus"))
    opts = page.eval_on_selector_all("#scope option", "els => els.map(e => e.textContent)")
    check("scope options", len(opts) >= 3, " | ".join(opts))
    check("model preselected", page.input_value("#model") == "Tiny")
    pause(page)
    type_in(page, "#q", "How much bleach per gallon of water to make it safe to drink?")
    pause(page, 1)
    page.click("#askBtn")
    note("It finds passages in the library, then the AI on this computer answers from them")
    page.wait_for_function("document.getElementById('progress').textContent.startsWith('Done')", timeout=120000)
    srcs = page.eval_on_selector_all("#sources li a", "els => els.map(e => e.textContent)")
    check("sources listed", "Water purification" in srcs, ", ".join(srcs))
    check("the AI's answer arrives with every character intact, and cites its source", *intact(page))
    note("The answer and its sources. This test kit's AI always gives the same answer; the real ones answer the question")
    pause(page, 5)
    page.screenshot(path=os.path.join(SHOTS, "shot_ask.png"), full_page=True)
    href = page.get_attribute("#sources li a", "href")
    r = page.request.get(f"http://127.0.0.1:{LIB}" + href)
    check("source link opens the article", r.ok and "8 drops" in r.text(), href)
    if VIDEO:
        note("A source opens its article in the offline library")
        popup(page, "#sources li a", lambda tab: pause(tab, 4))
        note("AI chat: llama.cpp's own chat page, for anything that isn't in the library")
        popup(page, "#chatLink", chat)
    note("The Library tab: the books on this kit")
    page.click("nav a[data-tab=library]")
    pause(page)
    cards = page.eval_on_selector_all(".book-card a", "els => els.map(e => e.textContent)")
    check("library cards", len(cards) == 2, ", ".join(cards))
    page.screenshot(path=os.path.join(SHOTS, "shot_library.png"), full_page=True)
    note("Searching every book at once")
    type_in(page, "#libQ", "tourniquet")
    page.click("#libSearch button")
    page.wait_for_load_state()
    pause(page, 3)
    check("library search page", "Tourniquet" in page.content(), page.url)
    errors = [e for e in errors if "favicon" not in e]
    check("no JS errors", not errors, "; ".join(errors))
    if VIDEO:
        page.go_back()
        for tab, what in (("map", "The Map tab (this test kit has no map files)"), ("help", "Help")):
            note(what)
            page.click(f"nav a[data-tab={tab}]")
            pause(page, 3.5)

    if os.environ.get("KIT_AXE"):     # axe-core's axe.min.js
        for scheme in ("light", "dark"):
            pa = b.new_page(color_scheme=scheme)
            pa.goto(f"http://127.0.0.1:{LIB}/?model=Tiny&ai={AI}")
            pa.wait_for_function("document.querySelectorAll('#scope option').length > 1", timeout=20000)
            pa.add_script_tag(path=os.environ["KIT_AXE"])
            for tab in ("ask", "map", "library", "help"):
                pa.click(f"nav a[data-tab={tab}]")
                bad = pa.evaluate("axe.run().then(r => r.violations.map(v => v.id + ' (' + v.nodes.length + ')'))")
                check(f"{scheme} mode, {tab} tab: no accessibility violations (axe)", not bad, ", ".join(bad))
            pa.close()

    # AI down, on a phone (how family members use a shared kit): answers fall back to library passages
    page2 = b.new_page(viewport={"width": 390, "height": phone_height})
    note("On a phone, with the AI off: the answer is the library's best passages")
    page2.goto(f"http://127.0.0.1:{LIB}/?model=Tiny&ai=18999")    # nothing listens on 18999
    page2.wait_for_function("document.getElementById('aiStatus').textContent.includes('off')", timeout=15000)
    type_in(page2, "#q", "tourniquet placement")
    page2.click("#askBtn")
    page2.wait_for_function("document.getElementById('progress').textContent.includes('passages') || "
                            "document.getElementById('progress').textContent.includes('Nothing')", timeout=60000)
    check("AI-off fallback shows passages", "5 to 7 cm" in page2.inner_text("#answer"), page2.inner_text("#progress"))
    pause(page2, 4)
    page2.screenshot(path=os.path.join(SHOTS, "shot_ai_off.png"), full_page=True)
    for tab in ("ask", "map", "library", "help"):
        page2.click(f"nav a[data-tab={tab}]")
        width = page2.evaluate("document.documentElement.scrollWidth")
        check(f"phone, {tab} tab: no sideways scroll", width <= 390, f"{width}px")

    share = os.environ.get("KIT_SHARE_URL")
    if share:
        code = os.environ["KIT_SHARE_CODE"]
        phone = b.new_context(viewport={"width": 390, "height": 844})
        p3 = phone.new_page()
        bad, js = [], []
        p3.on("response", lambda r: bad.append(f"{r.status} {r.url}") if r.status >= 400 and "favicon" not in r.url else None)
        p3.on("pageerror", lambda e: js.append(str(e)))
        p3.goto(share + "/?model=Tiny")
        check("shared: a phone on the network gets the access code page", p3.locator("input[name=code]").count() == 1, p3.url)
        width = p3.evaluate("document.documentElement.scrollWidth")
        check("shared: the access code page fits a phone", width <= 390, f"{width}px")
        p3.screenshot(path=os.path.join(SHOTS, "shot_share_code.png"))
        bad.clear()    # the code page itself answers 401
        p3.fill("input[name=code]", code[:4] + " " + code[4:])
        p3.click("button[type=submit]")
        p3.wait_for_function("document.getElementById('aiStatus').textContent.includes('ready')", timeout=30000)
        check("shared: in with the code, and the AI is ready through the gate", p3.url.startswith(share), p3.url)
        check("shared: the page says it's shared", p3.is_visible("#sharePill"))
        p3.screenshot(path=os.path.join(SHOTS, "shot_share_page.png"))
        p3.fill("#q", "How much bleach per gallon of water to make it safe to drink?")
        p3.click("#askBtn")
        p3.wait_for_function("document.getElementById('progress').textContent.startsWith('Done')", timeout=120000)
        srcs = p3.eval_on_selector_all("#sources li a", "els => els.map(e => e.textContent)")
        check("shared: asking works through the gate", "Water purification" in srcs, ", ".join(srcs))
        check("shared: the AI's answer arrives intact through the gate", *intact(p3))
        r = p3.request.get(share + p3.get_attribute("#sources li a", "href"))
        check("shared: a source opens through the gate", r.ok and "8 drops" in r.text())
        p3.click("nav a[data-tab=help]")
        check("shared: Help shows the address and the access code",
              share.split("//")[1] in p3.inner_text("#shareAddr") and p3.inner_text("#shareCode").replace(" ", "") == code,
              p3.inner_text("#shareOn"))
        p3.wait_for_function("document.getElementById('shareQr').naturalWidth > 0", timeout=10000)
        p3.screenshot(path=os.path.join(SHOTS, "shot_share_help.png"), full_page=True)
        p3.click("nav a[data-tab=map]")
        p3.wait_for_function("/Address search: ready.*Directions: ready/.test(document.getElementById('mapStatus').textContent)",
                             timeout=90000)
        check("shared: address search and directions answer through the gate", True)
        p3.wait_for_function("window.__kitMap && window.__kitMap.loaded()", timeout=30000)
        with p3.expect_response(lambda r: "/tiles/" in r.url, timeout=30000) as tile:
            p3.evaluate("window.__kitMap.zoomIn()")
        check("shared: map tiles come through the gate", tile.value.ok, tile.value.url)
        check("shared: nothing failed", not bad and not js, "; ".join(bad + js))

        # The AI chat link opens llama-server's own chat page, which asks for its API by paths of its own. It
        # keeps a connection open, so the page never goes quiet: wait for the message box instead (the visible one:
        # the page has hidden text boxes too).
        bad.clear()
        pending, sent = {}, []
        p3.on("request", lambda r: pending.__setitem__(r, r.url))
        p3.on("response", lambda r: sent.append(f"{r.request.method} {r.status} {r.url}") if r.request.method != "GET" else None)
        p3.on("requestfinished", lambda r: pending.pop(r, None))
        p3.on("requestfailed", lambda r: pending.pop(r, None))
        asked_with = ""
        try:
            p3.goto(share + "/ai/")
            box = p3.locator("textarea:visible, [contenteditable=true]:visible").first
            box.wait_for(timeout=30000)
            box.click()
            p3.keyboard.type("Hello")    # real keys: the page's editor doesn't notice text set directly
            send = p3.get_by_role("button", name="Send")
            asked = ("chat/completions", "/responses", "/completion")    # whichever API this llama.cpp's page uses
            with p3.expect_response(lambda r: r.request.method == "POST" and any(a in r.url for a in asked),
                                    timeout=120000) as reply:
                if send.count():
                    send.first.click()
                else:
                    p3.keyboard.press("Enter")
            answered, why = reply.value.ok, reply.value.url
            asked_with = reply.value.request.post_data or ""
            p3.wait_for_timeout(2000)
        except Exception as e:    # a timeout: say what was on screen and what was still loading
            answered = False
            boxes = p3.evaluate("[...document.querySelectorAll('textarea, [contenteditable]')].map(e => e.tagName + ' '"
                                " + e.offsetWidth + 'x' + e.offsetHeight + ' ' + getComputedStyle(e).visibility).join(', ')")
            why = (str(e).splitlines()[0] + " | on screen: " + " ".join(p3.inner_text("body").split())[:300]
                   + " | text boxes: " + boxes + " | still loading: " + ", ".join(sorted(set(pending.values())))[:300]
                   + " | sent: " + "; ".join(sent)[:300])
        p3.screenshot(path=os.path.join(SHOTS, "shot_share_ai_chat.png"))
        check("shared: AI chat answers through the gate", answered, why)
        # tools/ai-chat.json, through llama-server's UI settings: the stock page asks with Ask's safety rules.
        check("shared: AI chat asks with the kit's safety rules", "wild plant" in asked_with, asked_with[:300])
        # The page asks whether llama-server's own tools are on. They aren't, and the gate keeps them off.
        tools = p3.request.get(share + "/ai/tools")
        check("shared: llama-server's tools stay off", tools.status == 403 and "feature_disabled" in tools.text(),
              f"{tools.status} {tools.text()[:80]}")
        bad[:] = [b for b in bad if not b.startswith("403 ") or not b.split("?")[0].endswith(("/ai/tools", "/ai/cors-proxy"))]
        check("shared: AI chat's requests all work", not bad, "; ".join(bad))
        outsider = b.new_context().request.get(share + "/ai/v1/models")
        check("shared: no AI without the code", outsider.status == 401, str(outsider.status))
        phone.close()
    b.close()

print("\nALL PASSED" if not fails else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
