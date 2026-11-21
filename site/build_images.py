"""Render the site's icon files and link-preview cards from site/icon.svg, in headless Chromium.
usage: python3 site/build_images.py   (needs: pip install playwright && playwright install chromium)
Writes site/favicon.ico, site/apple-touch-icon.png, site/og.png and docs/social-preview.png.
GitHub can't read a repo's preview image from the repo: upload social-preview.png under Settings > General > Social preview."""
import base64
import os
import struct
from string import Template
from playwright.sync_api import sync_playwright

SITE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SITE)
INK, INK2, PAPER, SIGNAL = "#1C1F1A", "#3A3E36", "#F3F0E6", "#D9531E"
HEADLINE = "The internet's down.<br>Your AI isn't."


def data_uri(path, mime):
    return f"data:{mime};base64," + base64.b64encode(open(path, "rb").read()).decode()


ICON = data_uri(os.path.join(SITE, "icon.svg"), "image/svg+xml")
FONT = data_uri(os.path.join(SITE, "fonts", "plex-sans.woff2"), "font/woff2")

# Link previews show the card at a quarter of its size or less, so it holds only the name, the headline and the mark, all large.
CARD = Template("""<style>
@font-face{font-family:Sans;font-weight:400 700;src:url($font)}
body{margin:0;width:${w}px;height:${h}px;position:relative;overflow:hidden;background:$paper;color:$ink;font-family:Sans}
.copy{position:absolute;left:88px;top:0;bottom:0;display:flex;flex-direction:column;justify-content:center}
h1{margin:0;font-size:116px;line-height:1;font-weight:700;letter-spacing:-.03em}
p{margin:30px 0 0;font-size:70px;line-height:1.1;font-weight:700;letter-spacing:-.02em;color:$ink2}
img{position:absolute;right:${right}px;top:${top}px}
</style>
<div class="copy"><h1>Tinfoil Kit</h1><p>$headline</p></div>
<img src="$icon" width="$size" height="$size" alt="">""")


def card(w, h, size=500):
    # The mark is drawn between x 14 and 50 of its 64-unit box: offset the box so the drawing sits 100 px from the right edge.
    return CARD.substitute(font=FONT, icon=ICON, headline=HEADLINE, w=w, h=h, size=size, right=100 - 14 * size // 64,
                           top=(h - size) // 2, ink=INK, ink2=INK2, paper=PAPER)


def icon_page(size, background="transparent", pad=0):
    return (f'<body style="margin:0;background:{background}"><img src="{ICON}" width="{size - 2 * pad}" height="{size - 2 * pad}" '
            f'style="display:block;margin:{pad}px"></body>')


def ico(pngs):
    """An .ico that holds PNGs, which every current browser reads."""
    head, body, offset = struct.pack("<HHH", 0, 1, len(pngs)), b"", 6 + 16 * len(pngs)
    for size, png in pngs:
        head += struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(png), offset + len(body))
        body += png
    return head + body


def save(rel, data):
    with open(os.path.join(ROOT, rel), "wb") as f:
        f.write(data)
    print(f"wrote {rel} ({len(data) // 1024 or 1} KB)")


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=os.environ.get("KIT_CHROMIUM") or None)
    page = browser.new_page()

    def render(html, w, h, transparent=False):
        page.set_viewport_size({"width": w, "height": h})
        page.set_content(html)
        page.evaluate("document.fonts.ready")
        return page.screenshot(omit_background=transparent)

    save("site/favicon.ico", ico([(s, render(icon_page(s), s, s, True)) for s in (16, 32, 48)]))
    # iOS rounds the corners itself and shows transparency as black, so the touch icon is the mark on a full orange square.
    save("site/apple-touch-icon.png", render(icon_page(180, SIGNAL, 18), 180, 180))
    save("site/og.png", render(card(1200, 630), 1200, 630))
    save("docs/social-preview.png", render(card(1280, 640), 1280, 640))
    browser.close()
