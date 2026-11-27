"""Helpers for the drive test (tests/drive_test.sh, .github/workflows/drive.yml). Standard library only.

  drive.py check LIB_PORT AI_PORT   wait for the kit's library and AI, then search a book and get an answer; and
                                    when the kit's page says it has a map, get a street-level tile and directions
  drive.py share ADDRESS CODE LIB_PORT AI_PORT
                                    the kit shared on the home network, as a phone there finds it at ADDRESS
  drive.py vhd IMAGE                add a VHD footer to a raw disk image, so Windows can mount the drive a Mac made
  drive.py kitjson FILE [maps]      write the test kit's kit.json, as the website's builder makes one; with maps,
                                    also the map of Andorra, with every computer's real map programs

For the videos of a run, which people watch to see the kit set up and used on each OS:
  drive.py record NAME -- CMD...    run CMD while recording the screen, captioned with its "=== step" lines
  drive.py type LOG ANSWERS -- CMD...
                                    run CMD in this terminal and type its answers the way a person would
  drive.py videos FOLDER            make MP4s of the recordings, and log how each step ended (the videos job;
                                    needs ffmpeg, and tesseract to read the screen)
  drive.py summary NAME=URL...      the run page's list of videos, in Markdown
"""

import codecs
import http.client
import json
import math
import os
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from make_tiny_model import ANSWER

# A Windows console can't print every character (a mangled answer, a book's title).
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


HELLO = {"model": "Tiny", "messages": [{"role": "user", "content": "Hello"}], "max_tokens": 100}


def answer(body):
    """The answer in a chat completion, or what came instead. The test model always gives ANSWER."""
    try:
        return json.loads(body)["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        return body[:300]


def check_kit(lib, ai):
    base = f"http://127.0.0.1:{lib}"
    page = wait_for(base + "/", 120)  # containers install packages first
    check("library page", "Tinfoil Kit" in page, base)
    books = wait_for(base + "/catalog/v2/entries", 5).count("<entry>")
    check("both test books listed", books == 2, f"{books} books")
    found = wait_for(base + "/search?books.filter.lang=eng&pattern=tourniquet", 5)
    check("library search", "Tourniquet" in found)
    models = wait_for(f"http://127.0.0.1:{ai}/v1/models", 90)
    check("AI lists the model", "Tiny" in models, models[:200])
    props = wait_for(f"http://127.0.0.1:{ai}/props", 5)
    check("AI chat's page gets the kit's safety rules", "wild plant" in props, props[:200])
    try:
        said = answer(fetch(f"http://127.0.0.1:{ai}/v1/chat/completions", HELLO, timeout=180))
        check("AI answers, every character intact", said == ANSWER, "" if said == ANSWER else ascii(said)[:300])
    except OSError as e:
        check("AI answers, every character intact", False, str(e))
    # what each model runs with: never the speculative decoding draft beside the test model, as Gemma 4's crashed it
    models = wait_for(f"http://127.0.0.1:{ai}/v1/models", 5)
    check("AI leaves the draft beside the model alone", "model-draft" not in models, models[:300])
    check_map(page)


def check_map(page):
    """The map the kit's page offers (window.KIT_MAPS), if any: the tile over home at street level, address search and
    directions, from the servers this computer's own pmtiles and Java run. The test kit's map is Andorra (kitjson maps)."""
    m = re.search(r"window\.KIT_MAPS = (.*?);</script>", page, re.S)
    info = json.loads(m.group(1)) if m else {}
    if not info.get("available"):
        return
    ports, home, z = info["ports"], info["home"], info["detailMaxzoom"]
    tiles = f"http://127.0.0.1:{ports['tiles']}"
    try:
        tj = json.loads(wait_for(tiles + "/basemap.json", 60) or "{}")
        lat = math.radians(home["lat"])
        x = int((home["lon"] + 180) / 360 * 2**z)
        y = int((1 - math.asinh(math.tan(lat)) / math.pi) / 2 * 2**z)
        with urllib.request.urlopen(f"{tiles}/basemap/{z}/{x}/{y}.mvt", timeout=10) as r:
            tile = r.read()
        check(
            "map tiles",
            tj.get("maxzoom") == z and len(tile) > 0,
            f"zoom {tj.get('minzoom')} to {tj.get('maxzoom')}, and the tile over {home['label']} ({len(tile)} bytes)",
        )
    except (OSError, ValueError) as e:
        check("map tiles", False, str(e))
    if info["services"]["geocoder"]:  # what's near home, then a search for it by name, as ./kit test does
        geo, near = f"http://127.0.0.1:{ports['geocoder']}", f"lat={home['lat']}&lon={home['lon']}"
        try:
            found = json.loads(wait_for(f"{geo}/reverse?{near}&radius=10&limit=1", 180) or "{}").get("features", [])
            pr = found[0]["properties"] if found else {}
            name = pr.get("name") or pr.get("street")
            if name:
                found = json.loads(fetch(f"{geo}/api?q={urllib.parse.quote(name)}&limit=1&{near}")).get("features", [])
            pr = found[0]["properties"] if found else {}
            check(
                f"address search near {home['label']}",
                bool(found),
                ", ".join(str(pr[k]) for k in ("name", "street", "city", "country") if pr.get(k)) or "nothing found",
            )
        except (OSError, ValueError) as e:
            check(f"address search near {home['label']}", False, str(e))
    if info["services"]["routing"]:  # GraphHopper loads the roads first, which takes a while on a slow drive
        route = (
            f"http://127.0.0.1:{ports['routing']}/route?point=42.5063,1.5218&point=42.5345,1.5803"
            f"&profile={info['profiles'][0]}&points_encoded=false"
        )
        try:
            path = json.loads(wait_for(route, 180) or "{}").get("paths", [{}])[0]
            check(
                "directions across Andorra",
                path.get("distance", 0) > 0,
                f"{round(path.get('distance', 0))} m in {len(path.get('instructions', []))} steps",
            )
        except ValueError as e:
            check("directions across Andorra", False, str(e))


def ask(method, url, body=None, headers=None, timeout=10):
    """(status, body, headers), whatever the status, and without following redirects."""
    u = urllib.parse.urlsplit(url)
    c = http.client.HTTPConnection(u.hostname, u.port, timeout=timeout)
    try:
        c.request(method, (u.path or "/") + ("?" + u.query if u.query else ""), body, headers or {})
        r = c.getresponse()
        return r.status, r.read().decode("utf-8", "replace"), {k.lower(): v for k, v in r.getheaders()}
    except OSError as e:
        return 0, str(e), {}
    finally:
        c.close()


def check_share(address, code, lib, ai):
    """The gate at ADDRESS asks for the access code, then serves the page, the library and the AI. The servers
    behind it don't answer on the network themselves."""
    status, page = 0, ""
    for _ in range(90):
        status, page, _ = ask("GET", address + "/", headers={"Accept": "text/html"})
        if status:
            break
        time.sleep(1)
    check("the gate asks for the access code", status == 401 and "Access code" in page, str(status))
    status, _, _ = ask("GET", address + "/ai/v1/models")
    check("without the code, no AI", status == 401, str(status))
    form = {"Content-Type": "application/x-www-form-urlencoded"}
    status, _, _ = ask("POST", address + "/_kit/login", "code=00000001&next=/", form)
    check("a wrong code is turned away", status == 401, str(status))
    status, _, h = ask("POST", address + "/_kit/login", f"code={code}&next=/", form)
    cookie = h.get("set-cookie", "").split(";")[0]
    check("the right code lets the phone in", status == 303 and cookie.startswith("tinfoilkit="), str(status))
    signed = {"Cookie": cookie}
    status, page, _ = ask("GET", address + "/", headers=signed)
    check("the kit page, told it's shared", status == 200 and "Tinfoil Kit" in page and "KIT_GATE" in page, str(status))
    _, entries, _ = ask("GET", address + "/catalog/v2/entries", headers=signed)
    check("the library, through the gate", entries.count("<entry>") == 2, f"{entries.count('<entry>')} books")
    models = ""
    for _ in range(90):
        status, models, _ = ask("GET", address + "/ai/v1/models", headers=signed)
        if status == 200:
            break
        time.sleep(1)
    check("the AI, through the gate", "Tiny" in models, models[:200])
    status, out, _ = ask(
        "POST",
        address + "/ai/v1/chat/completions",
        json.dumps(HELLO),
        {**signed, "Content-Type": "application/json"},
        timeout=180,
    )
    said = answer(out)
    check(
        "the AI answers through the gate, every character intact",
        status == 200 and said == ANSWER,
        "" if said == ANSWER else f"{status} {ascii(said)[:300]}",
    )
    status, svg, _ = ask("GET", address + "/_kit/qr.svg", headers=signed)
    check("the QR code", status == 200 and svg.startswith("<svg"), str(status))
    # Share on the kit page on this computer, which has it from the notes server, and the link it copies
    status, out, _ = ask("GET", "http://127.0.0.1:8095/share", headers={"Origin": f"http://127.0.0.1:{lib}"})
    try:
        share = json.loads(out)
    except ValueError:
        share = {}
    check(
        "the kit page on this computer has Share, with the address and the code",
        status == 200 and share.get("address") == address and share.get("code", "").replace(" ", "") == code,
        f"{status} {out[:200]}",
    )
    status, _, h = ask("GET", f"{address}/?code={code}")
    check(
        "Share's link lets a new phone in, and takes the code out of the address",
        status == 303 and h.get("location") == "/" and h.get("set-cookie", "").startswith("tinfoilkit="),
        f"{status} {h.get('location')}",
    )
    status, _, _ = ask("GET", address + "/", headers={**signed, "Host": "evil.example.com"})
    check("a website's own name for this computer is turned away", status == 403, str(status))
    host = urllib.parse.urlsplit(address).hostname
    for name, port in (("library", lib), ("AI", ai)):
        try:
            socket.create_connection((host, int(port)), timeout=3).close()
            check(f"the {name} server doesn't answer on the network itself", False, f"{host}:{port} answered")
        except OSError:
            check(f"the {name} server doesn't answer on the network itself", True)


def kit_json(out, maps=False):
    """The test kit: the real Mac, Windows and Linux programs, the tiny model and two test books, and with maps, a
    map of two places whose roads are Andorra's (small and real), merged into one for directions. The try-it kit has
    the model and the books, and another tiny model as its sample, which nobody picks: it goes once the rest is in."""
    tests = Path(__file__).resolve().parent
    t = json.loads((tests / "drive_kit.json").read_text(encoding="utf-8"))
    k = json.loads((tests.parent / "kit" / "kit.json").read_text(encoding="utf-8"))
    t["runtimes"] = [r for r in k["runtimes"] if maps or not r.get("requires")]
    if (
        maps
    ):  # as "Where do you live?" sets it, and a place nearby, with tiles to zoom 5 only, all the mock's map build has
        t["maps"] = {**k["maps"], "region": ["andorra", "liechtenstein"], "world_maxzoom": 2, "detail_maxzoom": 5}
    t["models"] = [{**m, "starter": True} for m in t["models"] if m["id"] == "Tiny"] + [
        {**m, "enabled": False, "starter": True} for m in t["models"] if m["id"] == "Two"
    ]
    t["library"] = [
        {**z, "starter": True} for z in t["library"] if z["zim"] in ("testmed_en_all_maxi", "testsurvival_en")
    ]
    t["settings"].update(library_port=8888, ai_port=8080, data_port=8095)
    Path(out).write_text(json.dumps(t, indent=2), encoding="utf-8")


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
        footer = bytearray(
            struct.pack(
                ">8sIIQI4sI4sQQHBBII16sB",
                b"conectix",
                2,
                0x00010000,
                0xFFFFFFFFFFFFFFFF,
                int(time.time()) - 946684800,
                # "win " as the creator, as Windows writes it, so every reader takes the exact size, not the geometry's
                b"win ",
                0x000A0000,
                b"Wi2k",
                size,
                size,
                cyl,
                heads,
                spt,
                2,
                0,
                uuid.uuid4().bytes,
                0,
            )
        )
        footer += bytes(512 - len(footer))
        struct.pack_into(">I", footer, 64, ~sum(footer) & 0xFFFFFFFF)
        f.write(footer)


# The videos. `record` films the screen while a part of the drive test runs, and notes when each step starts;
# ui_test.py adds what its tour shows. `type` makes setup's questions and answers show in its window, the way
# they do for a person. The videos job turns the recordings into captioned MP4s and lists them on the run page.

VIDEO = Path(os.environ.get("KIT_TEST_WORK") or Path(__file__).resolve().parent / "work") / "video"
TITLES = {
    "mac": "Mac: set up onto an exFAT drive from a download, start it, use the page; then set up on the Mac as a "
    "home server, and uninstall",
    "windows": "Windows: plug in the drive the Mac made, double-click Open Tinfoil Kit for Windows.bat, use the page "
    "in Edge",
    "windows-setup": "Windows: SETUP-Windows.bat from a download, onto the PC and then onto a drive, and uninstall",
    "linux": "Linux: the drive the Mac made, started on Ubuntu, then Ubuntu 24.04 and 22.04, Debian 12 and Fedora; "
    "the page in Chrome; then a home server, and uninstall",
}
# How the scripts' questions end, so `type` knows when to answer: "[Y/n] ", "[y/N] ", "then press Return: ", "press
# Enter to close this window. ", "Type where you live: ". A line that names no key ("Right now: ", with the place
# still to come) is news, not a question.
QUESTION = re.compile(r"(\[y/n\]|\b(Return|Enter)\b.*[.:]|\btype\b.*:)\s*$", re.I)
ESCAPES = re.compile(r"\x1b(\[[0-9;?<=>]*[ -/]*[@-~]|\][^\x07\x1b]*(\x07|\x1b\\)?|[()][0-9A-Za-z]|[=>78DEHMc])")


def note(text):
    """A caption in the video from now on, when it's being recorded."""
    if os.environ.get("KIT_STEPS"):
        with open(os.environ["KIT_STEPS"], "a", encoding="utf-8") as f:
            f.write(f"{time.time():.2f}\t{text}\n")


def record(name, cmd):
    """Runs CMD while recording the screen, and notes when each `=== step` line it prints appears, for the
    captions. Leaves video/NAME.mov (Mac) or NAME.mkv, and NAME.steps. Returns CMD's exit code: the recording
    can't fail the test, it can only be missing."""
    VIDEO.mkdir(parents=True, exist_ok=True)
    steps = VIDEO / f"{name}.steps"
    env = dict(os.environ, KIT_VIDEO="1", KIT_STEPS=str(steps))
    log = open(VIDEO / f"{name}.recorder.log", "wb")
    rec, screen = None, None
    try:
        if sys.platform == "darwin":
            # The Mac's own recorder. Control-C stops it and finishes the file (it ignores keys typed to it).
            rec = subprocess.Popen(
                ["screencapture", "-v", "-C", "-k", str(VIDEO / f"{name}.mov")],
                stdin=subprocess.PIPE,
                stdout=log,
                stderr=log,
            )
        else:
            if os.name == "nt":
                grab = ["-f", "gdigrab", "-framerate", "10", "-i", "desktop"]
            else:
                if not env.get("DISPLAY"):  # CI has no screen: give the windows the test opens one
                    env["DISPLAY"] = ":99"
                    screen = subprocess.Popen(
                        ["Xvfb", ":99", "-screen", "0", "1280x800x24", "-nolisten", "tcp"], stdout=log, stderr=log
                    )
                    time.sleep(2)
                grab = ["-f", "x11grab", "-framerate", "10", "-i", env["DISPLAY"]]
            rec = subprocess.Popen(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    *grab,
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-crf",
                    "22",
                    "-pix_fmt",
                    "yuv420p",
                    str(VIDEO / f"{name}.mkv"),
                ],
                stdin=subprocess.PIPE,
                stdout=log,
                stderr=log,
                env=env,
            )
    except OSError as e:
        print(f"(no screen recording here: {e})", flush=True)
    started = time.time() + 0.5  # about when the first frame is taken
    time.sleep(1)
    if rec and rec.poll() is not None:
        print(f"(the screen recorder stopped at once, exit {rec.returncode}: {said(log)})", flush=True)
    steps.write_text(f"{started:.2f}\t\n", encoding="utf-8")

    def relay(out):
        for line in iter(out.readline, b""):
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()
            text = line.decode("utf-8", "replace").strip()
            if text.startswith("=== "):
                with steps.open("a", encoding="utf-8") as f:
                    f.write(f"{time.time():.2f}\t{text[4:]}\n")

    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
        reader = threading.Thread(target=relay, args=(p.stdout,), daemon=True)
        reader.start()
        code = p.wait()
        reader.join(10)  # not until the pipe closes: something CMD left running may hold it open
        return code
    finally:
        time.sleep(2)  # the last screen, for a moment
        if rec:
            try:
                if sys.platform == "darwin":
                    rec.send_signal(signal.SIGINT)
                else:
                    rec.stdin.write(b"q")  # ffmpeg finishes the file
                    rec.stdin.flush()
                rec.wait(60)
            except (OSError, subprocess.TimeoutExpired):
                rec.kill()
        if screen:
            screen.terminate()
        made = [f"{f.name} ({f.stat().st_size // 1024} KB)" for f in VIDEO.glob(f"{name}.m*")]
        print(f"(screen recording: {', '.join(made) or 'none. The recorder said: ' + said(log)})", flush=True)


def said(log):
    """The end of what the recorder wrote to LOG, for the job's log: its artifacts are harder to get at."""
    log.flush()
    return Path(log.name).read_text(encoding="utf-8", errors="replace")[-600:].strip() or "nothing"


def typed(log, answers, cmd):
    """Runs CMD in a terminal of its own and answers its questions the way a person at the keyboard would: each
    answer is typed once CMD has asked something and gone quiet. What CMD shows goes to this terminal, and into
    LOG. ANSWERS is a line per answer, as printf '%b' takes them ("1\\ny\\n\\n" is 1, y, then just Return), or
    @FILE with a line per answer. Returns CMD's exit code."""
    if answers.startswith("@"):
        todo = Path(answers[1:]).read_text(encoding="utf-8").splitlines()
    else:
        todo = codecs.decode(answers, "unicode_escape").split("\n")
        if todo[-1] == "":
            todo.pop()
    try:
        code, left = (typed_windows if os.name == "nt" else typed_posix)(log, todo, cmd)
    except NoTerminal as e:  # the test still runs, its answers typed ahead
        print(f"(drive.py type: no terminal to type into ({e}), so the answers go in all at once)", flush=True)
        with open(log, "wb") as out:
            code = subprocess.run(
                cmd, input="".join(a + "\n" for a in todo).encode(), stdout=out, stderr=subprocess.STDOUT
            ).returncode
        left = []
    if left:
        print(f"\n(drive.py type: it ended with {len(left)} answer(s) left over: {left})", flush=True)
    return code


class NoTerminal(Exception):
    """There's no pseudo terminal to run it in (pywinpty isn't installed, say)."""


def asking(tail, quiet):
    """Is it waiting for an answer? Its last line ends like a question and it's been quiet a moment; or it's
    been quiet a long while in the middle of a line (a question this doesn't know)."""
    line = ESCAPES.sub("", tail).replace("\r\n", "\n").split("\n")[-1].split("\r")[-1]
    return (quiet > 1.5 and QUESTION.search(line)) or (quiet > 30 and line.strip())


def type_line(write, answer, enter):
    time.sleep(0.8)  # reading the question
    for ch in answer:
        write(ch)
        time.sleep(0.15)
    time.sleep(0.3)
    write(enter)


def typed_posix(log, todo, cmd):
    import pty
    import select

    try:
        pid, fd = pty.fork()
    except OSError as e:
        raise NoTerminal(e)
    if pid == 0:
        try:
            os.execvp(cmd[0], cmd)
        finally:
            os._exit(127)
    try:  # the window's size, so its lines wrap as they would for a person
        import fcntl
        import termios

        fcntl.ioctl(fd, termios.TIOCSWINSZ, fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, b"\0" * 8))
    except OSError:
        pass
    tail, heard, quiet = "", False, time.time()
    with open(log, "wb") as out:
        while True:
            if select.select([fd], [], [], 0.1)[0]:
                try:
                    data = os.read(fd, 65536)
                except OSError:  # Linux, once it has ended
                    data = b""
                if not data:
                    break
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
                out.write(data.replace(b"\r\n", b"\n"))
                out.flush()
                tail = (tail + data.decode("utf-8", "replace"))[-2000:]
                heard, quiet = True, time.time()
            elif todo and heard and asking(tail, time.time() - quiet):
                type_line(lambda s: os.write(fd, s.encode()), todo.pop(0), "\r")
                heard = False
    os.close(fd)
    return os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1]), todo


def typed_windows(log, todo, cmd):
    """The same in Windows' pseudo console (pip install pywinpty), for a .bat file: CMD is the file and its
    arguments. set /p reads what's typed there as it does from a keyboard."""
    import ctypes

    k32 = ctypes.windll.kernel32
    handle, mode = k32.GetStdHandle(-11), ctypes.c_uint32()
    if k32.GetConsoleMode(handle, ctypes.byref(mode)):  # so this window draws the colors and moves it's sent
        k32.SetConsoleMode(handle, mode.value | 4)
    cols, rows = shutil.get_terminal_size((120, 30))
    args = subprocess.list2cmdline(cmd[1:])
    try:
        from winpty import PTY

        pty = PTY(cols, rows)
        # cmd.exe /c ""C:\path\SETUP-Windows.bat" args": cmd drops the outer quotes. pywinpty puts this right after
        # the program's name, hence the space it starts with.
        pty.spawn(
            os.environ.get("COMSPEC", "cmd.exe"),
            cmdline=f' /c ""{os.path.abspath(cmd[0])}"{" " + args if args else ""}"',
            cwd=os.getcwd(),
            env="\0".join(f"{k}={v}" for k, v in os.environ.items()) + "\0",
        )
    except Exception as e:
        raise NoTerminal(e)
    tail, heard, quiet, ended = "", False, time.time(), 0.0
    with open(log, "w", encoding="utf-8", newline="\n") as out:
        while True:
            try:
                data = pty.read(blocking=False)
            except Exception:  # pywinpty says so once the output has ended
                data = ""
                if not pty.isalive():
                    break
            if data:
                if "\x1b[6n" in data:  # the pseudo console asks where the cursor is: the top left
                    pty.write("\x1b[1;1R")
                    data = data.replace("\x1b[6n", "")
                sys.stdout.write(data)
                sys.stdout.flush()
                out.write(ESCAPES.sub("", data).replace("\r\n", "\n"))
                out.flush()
                tail = (tail + data)[-2000:]
                heard, quiet = True, time.time()
                continue
            if not pty.isalive():
                ended = ended or time.time()
                if pty.iseof() or time.time() - ended > 2:
                    break
            elif todo and heard and asking(tail, time.time() - quiet):
                type_line(pty.write, todo.pop(0), "\r")
                heard = False
            time.sleep(0.05)
    code = pty.get_exitstatus()
    return (1 if code is None else code), todo


def ffprobe_seconds(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
    ).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def clock(seconds):
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def screen_text(path, at):
    """The words on a frame, read by tesseract when it's installed."""
    if not shutil.which("tesseract"):
        return ""
    png = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{at:.1f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "image2",
            "-c:v",
            "png",
            "-",
        ],
        capture_output=True,
    ).stdout
    text = subprocess.run(["tesseract", "-", "-"], input=png, capture_output=True).stdout.decode("utf-8", "replace")
    return "\n".join(line.rstrip() for line in text.splitlines() if len(line.strip()) > 2)


def ascii_frame(path, at, width=110):
    """A frame as text, for the job log: whoever can read the log but not download the video can still check
    that windows were on screen."""
    raw = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{at:.1f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            f"scale={width}:{width * 3 // 10},format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
    ).stdout
    ramp = " .:-=+*#%@"
    return "\n".join(
        "".join(ramp[b * len(ramp) // 256] for b in raw[i : i + width]).rstrip() for i in range(0, len(raw), width)
    )


def make_videos(folder):
    """NAME.mp4 from each recording in FOLDER: captioned with its steps, at most 1280 wide, 10 frames a second,
    and small enough to download in a moment. Also NAME.chapters, the steps with their times."""
    folder = Path(folder)
    for steps in sorted(folder.rglob("*.steps")):
        name, raw = (
            steps.stem,
            next((p for p in (steps.with_suffix(".mov"), steps.with_suffix(".mkv")) if p.exists()), None),
        )
        length = ffprobe_seconds(raw) if raw else 0
        if not length:
            print(f"{name}: no recording")
            continue
        rows = [line.split("\t", 1) for line in steps.read_text(encoding="utf-8").splitlines() if "\t" in line]
        start = float(rows[0][0])
        marks = [(min(max(0.0, float(t) - start), length), text) for t, text in rows[1:] if text]
        run = " ".join(x for x in (os.environ.get("GITHUB_SHA", "")[:7], time.strftime("%Y-%m-%d")) if x)
        # What it is, at the top for the first seconds; then each step at the bottom until the next.
        srt = [
            f"1\n{srt_time(0)} --> {srt_time(min(8.0, length))}\n"
            f"{{\\an8}}Tinfoil Kit drive test, {run}: {TITLES.get(name, name)}\n"
        ]
        for i, (t, text) in enumerate(marks):
            end = marks[i + 1][0] if i + 1 < len(marks) else length
            if end - t >= 0.3:
                srt.append(f"{len(srt) + 1}\n{srt_time(t)} --> {srt_time(end)}\n{text}\n")
        steps.with_suffix(".srt").write_text("\n".join(srt), encoding="utf-8")
        steps.with_suffix(".chapters").write_text(
            "".join(f"{clock(t)}  {text}\n" for t, text in marks), encoding="utf-8"
        )
        style = (
            "FontName=DejaVu Sans,FontSize=9,PrimaryColour=&H00FFFFFF,BackColour=&H30000000,BorderStyle=4,"
            "Outline=0,Shadow=0,MarginV=6,MarginL=8,MarginR=8"
        )
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                raw.name,
                "-an",
                "-vf",
                f"fps=10,scale='min(1280,iw)':-2:flags=lanczos,subtitles={name}.srt:force_style='{style}'",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "30",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                f"{name}.mp4",
            ],
            cwd=steps.parent,
            check=True,
        )
        mp4 = steps.with_suffix(".mp4")
        print(f"\n######## {mp4.name}: {clock(length)}, {mp4.stat().st_size // 1024} KB")
        shown = [(0.0, "start")] + marks
        for i, (t, text) in enumerate(shown[:40]):
            end = shown[i + 1][0] if i + 1 < len(shown) else length
            at = min(max(t + 1, end - 1.5), max(length - 0.5, 0))  # how the step ended
            print(f"\n---- {clock(at)}, the end of: {text}\n{ascii_frame(mp4, at)}\n{screen_text(raw, at)}")


def srt_time(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def summary(pairs):
    """The run page's list of videos: each one's link, what it shows, and its chapters."""
    out = [
        "## Videos of this run",
        "",
        "Each video is the screen of one machine while the drive test ran on it, captioned with what it was "
        "doing. Click one to download it; it plays in QuickTime or a browser. The AI in them is a tiny test "
        "model that gives the same answer to every question.",
        "",
    ]
    for pair in pairs:
        name, url = pair.split("=", 1)
        mp4 = VIDEO / f"{name}.mp4"
        if not url or not mp4.exists():
            out += [f"No video of {name}: that part didn't run, or stopped before it was filmed.", ""]
            continue
        length = clock(ffprobe_seconds(mp4))
        out += [
            f"### [{name}.mp4]({url}) ({length}, {mp4.stat().st_size // 1024 // 1024 or 1} MB)",
            "",
            TITLES.get(name, name),
            "",
        ]
        chapters = VIDEO / f"{name}.chapters"
        if chapters.exists() and chapters.read_text(encoding="utf-8").strip():
            out += [
                "<details><summary>Chapters</summary>",
                "",
                "```",
                chapters.read_text(encoding="utf-8").rstrip(),
                "```",
                "</details>",
                "",
            ]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    if sys.argv[1:2] == ["check"] and len(sys.argv) == 4:
        check_kit(sys.argv[2], sys.argv[3])
        print("\nALL PASSED" if not fails else f"\n{fails} FAILED")
        sys.exit(1 if fails else 0)
    if sys.argv[1:2] == ["share"] and len(sys.argv) == 6:
        check_share(*sys.argv[2:6])
        print("\nALL PASSED" if not fails else f"\n{fails} FAILED")
        sys.exit(1 if fails else 0)
    if sys.argv[1:2] == ["vhd"] and len(sys.argv) == 3:
        add_vhd_footer(sys.argv[2])
        sys.exit(0)
    if sys.argv[1:2] == ["kitjson"] and len(sys.argv) in (3, 4):
        kit_json(sys.argv[2], sys.argv[3:] == ["maps"])
        sys.exit(0)
    if sys.argv[1:2] == ["record"] and sys.argv[3:4] == ["--"] and len(sys.argv) > 4:
        sys.exit(record(sys.argv[2], sys.argv[4:]))
    if sys.argv[1:2] == ["type"] and sys.argv[4:5] == ["--"] and len(sys.argv) > 5:
        sys.exit(typed(sys.argv[2], sys.argv[3], sys.argv[5:]))
    if sys.argv[1:2] == ["videos"] and len(sys.argv) == 3:
        make_videos(sys.argv[2])
        sys.exit(0)
    if sys.argv[1:2] == ["summary"]:
        print(summary(sys.argv[2:]), end="")
        sys.exit(0)
    sys.exit(__doc__)
