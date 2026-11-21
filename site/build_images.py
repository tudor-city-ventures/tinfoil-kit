"""Render the site's icon files and link-preview cards from site/icon.svg, in headless Chromium.
usage: python3 site/build_images.py   (needs: pip install playwright && playwright install chromium)
Writes site/favicon.ico, site/apple-touch-icon.png, site/og.png and docs/social-preview.png.
GitHub can't read a repo's preview image from the repo: upload social-preview.png under Settings > General > Social preview."""
import base64
import math
import os
import struct
from string import Template
from playwright.sync_api import sync_playwright

SITE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SITE)
INK, INK2, OLIVE, SIGNAL, BUTTON = "#1C1F1A", "#3A3E36", "#4A5A2A", "#D9531E", "#E4672F"
FOIL = ("#BFC3BD", "#FBFBF8", "#979C96", "#6F746E")    # lit from the left: mid, highlight, shade, shadow
CRINKLES = "M-15 -13 L-11.5 -9.5 L-13.5 -5 M-2.5 -31 L0.5 -27.5 L-1.5 -24 M8 -24 L10.5 -21 L8.5 -17.5 M-7 -6 L-4 -3"    # so it reads as foil, not a party hat


def data_uri(path, mime):
    return f"data:{mime};base64," + base64.b64encode(open(path, "rb").read()).decode()


ICON = data_uri(os.path.join(SITE, "icon.svg"), "image/svg+xml")
FONTS = "".join(f"@font-face{{font-family:{fam};font-weight:{wt};src:url({data_uri(os.path.join(SITE, 'fonts', f), 'font/woff2')})}}"
                for fam, wt, f in (("Sans", "400 700", "plex-sans.woff2"), ("Mono", "500", "plex-mono-500.woff2"), ("Mono", "600", "plex-mono-600.woff2")))


def hat(scale, outline, crease, teeth=18, crimp=0.025, cuts=(0, 6, 10, 14, 18)):
    """The foil hat from icon.svg, redrawn with more crimps for large sizes. Base center at (0,0), base 50 wide, tip at (2,-46)."""
    pts = []
    for i in range(teeth + 1):
        t, k = math.pi * (1 - i / teeth), (1 - crimp if i % 2 else 1)
        pts.append(f"{25 * k * math.cos(t):.2f} {6.5 * k * math.sin(t):.2f}")
    tip = "2 -46"
    facets = "".join(f'<path d="M{tip} {" ".join(pts[a:b + 1])}Z" fill="{tone}"/>' for a, b, tone in zip(cuts, cuts[1:], FOIL))
    creases = "".join(f"M{tip} {pts[c]}" for c in cuts[1:-1])
    return (f'<g transform="scale({scale})" stroke="{INK}" stroke-width="{outline / scale:.3f}" stroke-linejoin="round" stroke-linecap="round">'
            f'{facets}<path d="{creases}" stroke-width="{crease / scale:.3f}"/><path d="{CRINKLES}" fill="none" stroke-width="{crease * 0.7 / scale:.3f}"/>'
            f'<path d="M{tip} {" ".join(pts)}Z" fill="none"/></g>')


CALLOUTS = (("01", "LOCAL AI", (1.5, -37)), ("02", "WIKIPEDIA", (2.5, -21)), ("03", "MEDICINE", (11, -13)), ("04", "MAPS", (19.5, -3)))


def figure(x, y, s=5.2):
    """The hat as an annotated technical drawing: center line, hidden back edge, callouts and a dimension line. (x, y) is the base center."""
    rx, ry, top = 25 * s, 6.5 * s, y - 46 * s
    lines = ""
    for i, (num, label, (ax, ay)) in enumerate(CALLOUTS):
        ly, px, py = y - 252 + 70 * i, x + ax * s, y + ay * s
        lines += (f'<path d="M{x + 138} {ly} H{x + 112} L{px:.1f} {py:.1f}" fill="none" stroke="{INK}" stroke-width="1.6"/>'
                  f'<circle cx="{px:.1f}" cy="{py:.1f}" r="6" fill="{SIGNAL}" stroke="{INK}" stroke-width="2"/>'
                  f'<text x="{x + 146}" y="{ly + 6}" class="lab"><tspan fill="{OLIVE}">{num}</tspan> {label}</text>')
    return (f'<g transform="translate({x} {y})">{hat(s, 3.4, 2)}</g>'
            f'<g fill="none" stroke="{INK}" stroke-width="1.4"><path d="M{x} {top - 26} V{y + ry + 18}" stroke-dasharray="14 5 3 5" opacity=".7"/>'
            f'<path d="M{x - rx} {y} A{rx} {ry} 0 0 1 {x + rx} {y}" stroke-dasharray="7 6" opacity=".8"/>'
            f'<path d="M{x - rx} {y + 58} H{x + rx} M{x - rx} {y + 46} V{y + 70} M{x + rx} {y + 46} V{y + 70}" stroke-width="1.6"/></g>'
            f'<text x="{x}" y="{y + 96}" text-anchor="middle" class="lab">FITS ON ONE 2 TB SSD</text>{lines}')


CARD = Template("""<style>$fonts
*{box-sizing:border-box}
body{margin:0;width:${w}px;height:${h}px;position:relative;overflow:hidden;background:#F3F0E6;color:$ink;font-family:Sans}
.plate{position:absolute;inset:28px;border:3px solid $ink;background-image:linear-gradient(#E6E1D2 1px,transparent 1px),linear-gradient(90deg,#E6E1D2 1px,transparent 1px);background-size:32px 32px;background-position:15px 15px}
svg{position:absolute;inset:0}
.lab{font:600 18px Mono;letter-spacing:1px;fill:$ink}
.copy{position:absolute;left:84px;top:${top}px;bottom:${top}px;width:580px;display:flex;flex-direction:column}
.kicker{font:500 21px Mono;letter-spacing:.1em;color:$olive}
.title{display:flex;align-items:center;gap:20px;margin-top:28px}
h1{margin:0;font-size:90px;line-height:1;font-weight:700;letter-spacing:-.025em;white-space:nowrap}
.tag{margin-top:24px;font-size:38px;line-height:1.22;font-weight:600;color:$ink2;max-width:520px}
.foot{margin-top:auto;display:flex;align-items:center;gap:22px;font:600 21px Mono;letter-spacing:.06em;white-space:nowrap}
.chip{background:$button;border:3px solid $ink;padding:8px 14px}
.cap{position:absolute;right:56px;bottom:52px;font:500 14px Mono;letter-spacing:.08em;color:$ink2}
</style>
<div class="plate"></div>
<svg viewBox="0 0 $w $h" width="$w" height="$h">$figure</svg>
<div class="copy">
<div class="kicker">OPEN SOURCE · MIT · APPLE SILICON MACS</div>
<div class="title"><img src="$icon" width="78" height="78" alt=""><h1>Tinfoil Kit</h1></div>
<div class="tag">The internet's knowledge, offline, on one drive.</div>
<div class="foot"><span class="chip">AI · LIBRARY · MAPS</span><span>tinfoilkit.com</span></div>
</div>
<div class="cap">FIG. 1 · TINFOIL HAT, ANNOTATED</div>""")


def card(w, h):
    return CARD.substitute(fonts=FONTS, icon=ICON, w=w, h=h, top=78 + (h - 630) // 2, figure=figure(w - 348, h // 2 + 133),
                           ink=INK, ink2=INK2, olive=OLIVE, button=BUTTON)


def icon_page(size, background="transparent"):
    return f'<body style="margin:0;background:{background}"><img src="{ICON}" width="{size}" height="{size}" style="display:block"></body>'


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
    # iOS masks the corners itself and turns transparency black, so the touch icon is a full square of the tile's color.
    save("site/apple-touch-icon.png", render(icon_page(180, SIGNAL), 180, 180))
    save("site/og.png", render(card(1200, 630), 1200, 630))
    save("docs/social-preview.png", render(card(1280, 640), 1280, 640))
    browser.close()
