"""Helpers for the drive test (tests/drive_test.sh, .github/workflows/drive.yml). Standard library only.

  drive.py check LIB_PORT AI_PORT   wait for the kit's library and AI, then search a book and get an answer
  drive.py vhd IMAGE                add a VHD footer to a raw disk image, so Windows can mount the drive a Mac made
"""
import json
import struct
import sys
import time
import uuid
import urllib.request

# A Windows console can't print every character a tiny test model makes up.
sys.stdout.reconfigure(errors="backslashreplace")
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + (f": {detail}" if detail else ""), flush=True)
    fails += 0 if ok else 1


def fetch(url, body=None, timeout=10):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data, {"Content-Type": "application/json"} if body else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def wait_for(url, seconds):
    for _ in range(seconds):
        try:
            return fetch(url)
        except OSError:
            time.sleep(1)
    return ""


def check_kit(lib, ai):
    base = f"http://127.0.0.1:{lib}"
    check("library page", "Tinfoil Kit" in wait_for(base + "/", 120), base)    # containers install packages first
    books = wait_for(base + "/catalog/v2/entries", 5).count("<entry>")
    check("both test books listed", books == 2, f"{books} books")
    found = wait_for(base + "/search?books.filter.lang=eng&pattern=tourniquet", 5)
    check("library search", "Tourniquet" in found)
    models = wait_for(f"http://127.0.0.1:{ai}/v1/models", 90)
    check("AI lists the model", "Tiny" in models, models[:200])
    try:
        out = json.loads(fetch(f"http://127.0.0.1:{ai}/v1/chat/completions", {
            "model": "Tiny", "messages": [{"role": "user", "content": "Hello"}], "max_tokens": 8}, timeout=180))
        check("AI answers", bool(out.get("choices")), str(out)[:200])
    except (OSError, ValueError) as e:
        check("AI answers", False, str(e))


def chs(total_sectors):
    """Disk geometry, as the VHD format specifies it."""
    total_sectors = min(total_sectors, 65535 * 16 * 255)
    if total_sectors >= 65535 * 16 * 63:
        spt, heads = 255, 16
        cyl_heads = total_sectors // spt
    else:
        spt = 17
        cyl_heads = total_sectors // spt
        heads = max((cyl_heads + 1023) // 1024, 4)
        if cyl_heads >= heads * 1024 or heads > 16:
            spt, heads = 31, 16
            cyl_heads = total_sectors // spt
        if cyl_heads >= heads * 1024:
            spt, heads = 63, 16
            cyl_heads = total_sectors // spt
    return cyl_heads // heads, heads, spt


def add_vhd_footer(path):
    """A fixed VHD is the raw disk followed by a 512-byte footer."""
    with open(path, "r+b") as f:
        size = f.seek(0, 2)
        if size % 512:
            sys.exit(f"{path}: size {size} is not a whole number of sectors")
        cyl, heads, spt = chs(size // 512)
        footer = bytearray(struct.pack(
            ">8sIIQI4sI4sQQHBBII16sB",
            b"conectix", 2, 0x00010000, 0xFFFFFFFFFFFFFFFF, int(time.time()) - 946684800,
            # "win " as the creator, as Windows writes it, so every reader takes the exact size, not the geometry's
            b"win ", 0x000A0000, b"Wi2k", size, size, cyl, heads, spt, 2, 0, uuid.uuid4().bytes, 0))
        footer += bytes(512 - len(footer))
        struct.pack_into(">I", footer, 64, ~sum(footer) & 0xFFFFFFFF)
        f.write(footer)


if __name__ == "__main__":
    if sys.argv[1:2] == ["check"] and len(sys.argv) == 4:
        check_kit(sys.argv[2], sys.argv[3])
        print("\nALL PASSED" if not fails else f"\n{fails} FAILED")
        sys.exit(1 if fails else 0)
    if sys.argv[1:2] == ["vhd"] and len(sys.argv) == 3:
        add_vhd_footer(sys.argv[2])
        sys.exit(0)
    sys.exit(__doc__)
