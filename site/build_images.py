"""Render the site's icon files and link-preview cards from site/icon.svg, in headless Chromium.
usage: python3 site/build_images.py   (needs: pip install playwright && playwright install chromium)
Writes site/favicon.ico, site/apple-touch-icon.png, site/og.png and docs/social-preview.png.
GitHub can't read a repo's preview image from the repo: upload social-preview.png under Settings > General > Social preview."""
import base64
import math
import os
import re
import struct
import sys
from string import Template
from playwright.sync_api import sync_playwright

SITE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SITE)
INK, INK2, OLIVE, PAPER, SIGNAL, BUTTON = "#1C1F1A", "#3A3E36", "#4A5A2A", "#F3F0E6", "#D9531E", "#E4672F"
FOIL = ("#BFC3BD", "#FBFBF8", "#979C96", "#6F746E")    # lit from the left: mid, highlight, shade, shadow
CRINKLES = "M-15 -13 L-11.5 -9.5 L-13.5 -5 M-2.5 -31 L0.5 -27.5 L-1.5 -24 M8 -24 L10.5 -21 L8.5 -17.5 M-7 -6 L-4 -3"    # so it reads as foil, not a party hat
HEADLINE = "The internet's down.<br>Your AI isn't."


def data_uri(path, mime):
    return f"data:{mime};base64," + base64.b64encode(open(path, "rb").read()).decode()


ICON = data_uri(os.path.join(SITE, "icon.svg"), "image/svg+xml")
FONTS = "".join(f"@font-face{{font-family:{fam};font-weight:{wt};src:url({data_uri(os.path.join(SITE, 'fonts', f), 'font/woff2')})}}"
                for fam, wt, f in (("Sans", "400 700", "plex-sans.woff2"), ("Mono", "500", "plex-mono-500.woff2"), ("Mono", "600", "plex-mono-600.woff2")))

# The card's globe is the hero's: hero.js holds the land as a bitmap of 2-degree cells, rows from the north, bits low first.
LAND = re.search(r"atob\('([A-Za-z0-9+/=]+)'\)", open(os.path.join(SITE, "hero.js")).read())
if not LAND:
    sys.exit("site/hero.js no longer holds the land bitmap as atob('...'): update LAND in this script to match")
LAND = base64.b64decode(LAND.group(1))


def is_land(la, lo):
    i = int((90 - la) // 2) * 180 + int((lo + 180) // 2) % 180
    return LAND[i >> 3] >> (i & 7) & 1


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


# Each callout points at the hat (in its own frame) or at a place on the globe (latitude, longitude).
CALLOUTS = (("01", "LOCAL AI", ("hat", 2, -30)), ("02", "WIKIPEDIA", ("geo", 60, -76)),
            ("03", "MEDICINE", ("geo", 33, -84)), ("04", "MAPS", ("geo", 6, -64)))


def figure(x, y, r=118, lam0=-95, phi0=25):
    """The world in a foil hat, drawn like a plate in a manual: a dotted globe facing North America, the hat, callouts and a dimension line."""
    l0, p0 = math.radians(lam0), math.radians(phi0)

    def place(la, lo):    # orthographic projection; c is how squarely the point faces us
        a, b = math.radians(la), math.radians(lo) - l0
        c = math.sin(p0) * math.sin(a) + math.cos(p0) * math.cos(a) * math.cos(b)
        return x + r * math.cos(a) * math.sin(b), y - r * (math.cos(p0) * math.sin(a) - math.sin(p0) * math.cos(a) * math.cos(b)), c

    dots = []
    for step, land in ((2.2, 1), (4.0, 0)):
        la = -56 + step / 2
        while la < 84:
            n = round(360 / step * math.cos(math.radians(la)))
            for k in range(n):
                lo = -180 + (k + 0.5) * 360 / n
                if is_land(la, lo) != land:
                    continue
                px, py, c = place(la, lo)
                if c > 0.06:
                    dots.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{(0.8 + 1.1 * c if land else 1.1):.2f}" opacity="{(0.3 + 0.6 * c if land else 0.2):.2f}"/>')
            la += step
    s, hx, hy, tilt = r / 42, x + r * 0.03, y - r * 0.93, math.radians(6)    # smaller than on the mark, so the land shows
    anchors = []
    for num, label, (kind, u, v) in CALLOUTS:
        if kind == "hat":
            anchors.append((hx + s * (u * math.cos(tilt) - v * math.sin(tilt)), hy + s * (u * math.sin(tilt) + v * math.cos(tilt))))
        else:
            anchors.append(place(u, v)[:2])
    lx, notes = x + r + 46, ""
    for i, ((num, label, _), (ax, ay)) in enumerate(zip(CALLOUTS, anchors)):
        ly = y - 214 + 84 * i
        notes += (f'<path d="M{lx - 8} {ly} H{lx - 30} L{ax:.1f} {ay:.1f}" fill="none" stroke="{INK}" stroke-width="1.6"/>'
                  f'<circle cx="{ax:.1f}" cy="{ay:.1f}" r="6" fill="{SIGNAL}" stroke="{INK}" stroke-width="2"/>'
                  f'<text x="{lx}" y="{ly + 6}" class="lab"><tspan fill="{OLIVE}">{num}</tspan> {label}</text>')
    return (f'<circle cx="{x}" cy="{y}" r="{r}" fill="{PAPER}"/><g fill="{INK}">{"".join(dots)}</g>'
            f'<circle cx="{x}" cy="{y}" r="{r}" fill="none" stroke="{INK}" stroke-width="2.6"/>'
            f'<g transform="translate({hx:.1f} {hy:.1f}) rotate(6)">{hat(s, 3.4, 2)}</g>'
            f'<g fill="none" stroke="{INK}" stroke-width="1.6"><path d="M{x - r} {y + r + 34} H{x + r} M{x - r} {y + r + 22} V{y + r + 46} M{x + r} {y + r + 22} V{y + r + 46}"/></g>'
            f'<text x="{x}" y="{y + r + 72}" text-anchor="middle" class="lab">FITS ON ONE 2 TB SSD</text>{notes}')


CARD = Template("""<style>$fonts
*{box-sizing:border-box}
body{margin:0;width:${w}px;height:${h}px;position:relative;overflow:hidden;background:$paper;color:$ink;font-family:Sans}
.plate{position:absolute;inset:28px;border:3px solid $ink;background-image:linear-gradient(#E6E1D2 1px,transparent 1px),linear-gradient(90deg,#E6E1D2 1px,transparent 1px);background-size:32px 32px;background-position:15px 15px}
svg{position:absolute;inset:0}
.lab{font:600 18px Mono;letter-spacing:1px;fill:$ink}
.copy{position:absolute;left:84px;top:${top}px;bottom:${top}px;width:560px;display:flex;flex-direction:column}
.kicker{font:500 21px Mono;letter-spacing:.1em;color:$olive}
.title{display:flex;align-items:center;gap:14px;margin-top:30px;margin-left:-10px}
h1{margin:0;font-size:92px;line-height:1;font-weight:700;letter-spacing:-.025em;white-space:nowrap}
.tag{margin-top:26px;font-size:46px;line-height:1.14;font-weight:700;letter-spacing:-.01em;color:$ink2}
.foot{margin-top:auto;display:flex;align-items:center;gap:22px;font:600 21px Mono;letter-spacing:.06em;white-space:nowrap}
.chip{background:$button;border:3px solid $ink;padding:8px 14px}
.cap{position:absolute;right:56px;top:52px;font:500 14px Mono;letter-spacing:.08em;color:$ink2}
</style>
<div class="plate"></div>
<svg viewBox="0 0 $w $h" width="$w" height="$h">$figure</svg>
<div class="copy">
<div class="kicker">OPEN SOURCE · MIT · APPLE SILICON MACS</div>
<div class="title"><img src="$icon" width="96" height="96" alt=""><h1>Tinfoil Kit</h1></div>
<div class="tag">$headline</div>
<div class="foot"><span class="chip">AI · LIBRARY · MAPS</span><span>tinfoilkit.com</span></div>
</div>
<div class="cap">FIG. 1 · THE WORLD, IN A TINFOIL HAT</div>""")


def card(w, h):
    return CARD.substitute(fonts=FONTS, icon=ICON, headline=HEADLINE, w=w, h=h, top=78 + (h - 630) // 2,
                           figure=figure(w - 362, h // 2 + 62), ink=INK, ink2=INK2, olive=OLIVE, paper=PAPER, button=BUTTON)


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
