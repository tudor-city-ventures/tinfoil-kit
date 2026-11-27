#!/usr/bin/env python3
"""Keeps what AI agents read true to the code: the skills in .claude/skills, llms.txt, the GUIDE, the README,
AGENTS.md, CONTRIBUTING and the docs.

Every ./kit (or .\\kit.cmd) command they name has to exist, with options that command takes, and every option given to
SETUP, the launchers and UNINSTALL has to be one that script takes. llms.txt's table of SETUP's options lists every
one of them, the skills cover every command people use, AGENTS.md and llms.txt list every skill, and no skill runs a
command or approves a tool when it loads.
Usage: python3 tests/skills_test.py
"""

import platform
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODE = ROOT / "kit"  # the kit's code
SKILLS = sorted((CODE / ".claude" / "skills").glob("*/SKILL.md"))
LLMS = ROOT / "site" / "public" / "llms.txt"
DOCS = SKILLS + [LLMS, CODE / "GUIDE.md", ROOT / "README.md", ROOT / "AGENTS.md", ROOT / ".github" / "CONTRIBUTING.md"]
DOCS += sorted((ROOT / "docs").glob("*.md"))
# Commands no skill needs: SETUP runs them, or the maintainer does before a release.
INTERNAL = {"layout", "pins", "place"}

passed, failed = 0, 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"PASS  {name}")
    else:
        failed += 1
        print(f"FAIL  {name}" + (f": {detail}" if detail else ""))


# The commands and options come from the kit's own program, which tools/tinfoilkit/build.sh builds.
PLAT = {("Linux", "x86_64"): "linux-x64", ("Darwin", "arm64"): "macos-arm64"}.get(
    (platform.system(), platform.machine())
)
PROGRAM = CODE / "tools" / f"tinfoilkit-{PLAT}"
if not PLAT or not PROGRAM.exists():
    sys.exit("The tests need the kit's program for this computer: tools/tinfoilkit/build.sh builds it")
KIT_LINE = [str(PROGRAM), "kit"]


def kit_help(*args):
    out = subprocess.run([*KIT_LINE, *args, "-h"], capture_output=True, text=True, check=True).stdout
    flags, choices, section = set(), set(), None
    for line in out.splitlines():
        if re.match(r"^\S.*:$", line):
            section = line
        elif section in ("options:", "optional arguments:") and re.match(r"^\s+-", line):  # (Python 3.9 says optional)
            flags |= set(re.findall(r"(?<![\w-])--?[a-zA-Z][\w-]*", re.split(r"\s{2,}", line.strip())[0]))
        elif section == "positional arguments:" and re.match(r"^\s+\{", line):
            choices |= set(line.strip().split()[0].strip("{}").split(","))
    return flags, choices


top, commands = kit_help()
KIT = {c: kit_help(c) for c in sorted(commands)}
check(
    "./kit's commands and options can be read",
    {"sync", "pick", "share"} <= commands
    and "--root" in top
    and "--yes" in KIT["sync"][0]
    and "new-code" in KIT["share"][1],
    f"{sorted(commands)} {top}",
)


def script_options(path, prefix):
    """The options a script's own help lists, as lines like '#   --region PLACE'."""
    text = path.read_text(encoding="utf-8")
    return set(re.findall(rf"^{prefix}   (--[a-z][\w-]*)", text, re.M))


SETUP = {
    "SETUP.command": script_options(CODE / "SETUP.command", "#"),
    "SETUP-Windows.bat": script_options(CODE / "SETUP-Windows.bat", "rem"),
}
LAUNCH = set(
    re.findall(
        r"^\s+(--[a-z][\w-]*)",
        subprocess.run([str(PROGRAM), "open", "--help"], capture_output=True, text=True, timeout=30).stdout,
        re.M,
    )
)
WIN_LAUNCH = LAUNCH  # both launchers hand their options to the program's open
check(
    "the scripts' options can be read",
    len(SETUP["SETUP.command"]) >= 10
    and {"--share", "--no-maps", "--model"} <= LAUNCH
    and {"--share", "--no-browser"} <= WIN_LAUNCH,
    f"{SETUP} {LAUNCH} {WIN_LAUNCH}",
)
check(
    "SETUP takes the same options on a Mac or Linux and on Windows",
    SETUP["SETUP.command"] == SETUP["SETUP-Windows.bat"],
    str(SETUP["SETUP.command"] ^ SETUP["SETUP-Windows.bat"]),
)
UNINSTALL = {"--yes"}
for f in ("UNINSTALL.command", "UNINSTALL-Windows.bat"):
    check(f"{f} takes --yes", "--yes" in (CODE / f).read_text(encoding="utf-8"))


def code(text):
    """What a markdown file shows as code: inline spans, and the lines of indented or fenced blocks."""
    spans, fenced = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif fenced or line.startswith("    "):
            spans.append(line)
        else:
            spans += re.findall(r"`([^`]+)`", line)
    return spans


def opts(rest):
    return [t.split("=")[0].rstrip(".,)") for t in rest.split() if t.startswith("-")]


END = r"([^;&|#\n]*)"
named = set()
for doc in DOCS:
    rel, bad = doc.relative_to(ROOT), []
    for span in code(doc.read_text(encoding="utf-8")):
        for m in re.finditer(r"(?:^|[\s;&|(\"'])(?:\./kit|\.\\kit\.cmd)\s+([a-z][\w-]*)" + END, span):
            cmd, rest = m.group(1), m.group(2)
            if cmd not in KIT:
                bad.append(f"./kit {cmd} isn't a command")
                continue
            if doc in SKILLS:
                named.add(cmd)
            flags, choices = KIT[cmd]
            bad += [f"./kit {cmd} has no {o}" for o in opts(rest) if o not in flags | top]
            first = next((t for t in rest.split() if not t.startswith("-")), "")
            if choices and re.fullmatch(r"[a-z][a-z-]*", first) and first not in choices:
                bad.append(f"./kit {cmd} takes {', '.join(sorted(choices))}, not {first}")
        for m in re.finditer(r"(SETUP\.command|SETUP-Windows\.bat)\"?" + END, span):
            bad += [
                f"{m.group(1)} has no {o}" for o in opts(m.group(2)) if o not in SETUP[m.group(1)] | {"-h", "--help"}
            ]
        for m in re.finditer(r"Open Tinfoil Kit\.command\"?" + END, span):
            bad += [f"Open Tinfoil Kit.command has no {o}" for o in opts(m.group(1)) if o not in LAUNCH]
        for m in re.finditer(r"Open Tinfoil Kit for Windows\.bat\"?" + END, span):
            bad += [f"Open Tinfoil Kit for Windows.bat has no {o}" for o in opts(m.group(1)) if o not in WIN_LAUNCH]
        for m in re.finditer(r"UNINSTALL(?:\.command|-Windows\.bat)\"?" + END, span):
            bad += [f"UNINSTALL has no {o}" for o in opts(m.group(1)) if o not in UNINSTALL]
    check(f"{rel}: every command and option it names exists", not bad, "; ".join(sorted(set(bad))))

check(
    "the skills cover every command people use",
    not commands - INTERNAL - named,
    "no skill names ./kit " + ", ./kit ".join(sorted(commands - INTERNAL - named)),
)

llms = LLMS.read_text(encoding="utf-8")
for doc in (LLMS, CODE / ".claude" / "skills" / "tinfoil-install" / "SKILL.md"):
    table = {
        o
        for line in doc.read_text(encoding="utf-8").splitlines()
        if line.startswith("| `--")
        for o in re.findall(r"`(--[a-z][\w-]*)", line.split("|")[1])
    }
    check(
        f"{doc.relative_to(ROOT)}: its table of SETUP's options lists every one, and nothing else",
        table == SETUP["SETUP.command"],
        str(table ^ SETUP["SETUP.command"]),
    )

names = []
for s in SKILLS:
    text = s.read_text(encoding="utf-8")
    front = re.match(r"---\n(.*?)\n---\n", text, re.S)
    meta = dict(re.findall(r"^([\w-]+):(.*)$", front.group(1), re.M)) if front else {}
    meta = {k: v.strip() for k, v in meta.items()}
    desc = meta.get("description", "")
    names.append(meta.get("name"))
    check(
        f"{s.parent.name}: named for its folder, and says when to use it",
        meta.get("name") == s.parent.name
        and 40 <= len(desc) <= 1024
        and "Use when" in desc
        and not re.search("[<>]", desc),
        str(meta),
    )
    # They ship in every kit, where an agent loads them: no allowed-tools, hooks or !`command` that runs on loading
    check(
        f"{s.parent.name}: runs nothing and approves no tool when it loads",
        set(meta) == {"name", "description"} and "!`" not in text,
        str(sorted(meta)),
    )
check(
    "there's a skill to install, update, choose what goes in, check, share and remove a kit",
    {"tinfoil-install", "tinfoil-update", "tinfoil-data", "tinfoil-status", "tinfoil-home-server", "tinfoil-uninstall"}
    <= set(names),
    str(names),
)
agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
check(
    "AGENTS.md and llms.txt list every skill",
    all(n in agents and n in llms for n in names),
    ", ".join(n for n in names if n not in agents or n not in llms),
)
mentioned = {m for d in DOCS for m in re.findall(r"\b(tinfoil-[a-z-]+) skill", d.read_text(encoding="utf-8"))}
check("every skill they point to exists", mentioned <= set(names), str(mentioned - set(names)))

print(f"{failed} FAILED, {passed} passed" if failed else f"ALL {passed} PASSED")
sys.exit(1 if failed else 0)
