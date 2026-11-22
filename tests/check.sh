#!/bin/bash
# Quick gate: run before calling any change done. Needs python3 and node; uses shellcheck if installed.
cd "$(dirname "$0")/.." || exit 1
fail=0
step() { echo "== $*"; }
run() { if "$@"; then :; else echo "FAIL: $*"; fail=1; fi; }

step "python compiles"
run python3 -m py_compile tools/kit.py tools/share.py tests/*.py site/*.py

step "bash parses"
SH=(kit "Open Tinfoil Kit.command" SETUP.command UNINSTALL.command tools/launch.sh mac/app.sh mac/build.sh tests/check.sh tests/run_all.sh tests/build_fixtures.sh tests/drive_test.sh tests/fakes/java tests/fakes/pmtiles)
for f in "${SH[@]}"; do run bash -n "$f"; done

step "shellcheck"
if command -v shellcheck >/dev/null; then
  run shellcheck -S error "${SH[@]}"
else
  echo "skipped (not installed)"
fi

step "kit.json is valid"
run python3 -c "import json,sys; [json.load(open(f)) for f in sys.argv[1:]]" kit.json tools/pins.json tools/ai-chat.json tests/drive_kit.json tests/drive_kit_maps.json

step "site data matches kit.json and tools/regions.json"
run python3 -c "
import subprocess, sys
files = ['site/sources.json', 'site/kit.json', 'site/regions.json']
before = [open(f, encoding='utf-8').read() for f in files]
subprocess.run([sys.executable, 'site/build_sources.py'], check=True, stdout=subprocess.DEVNULL)
stale = [f for f, b in zip(files, before) if open(f, encoding='utf-8').read() != b]
sys.exit('stale: ' + ', '.join(stale) + ': run python3 site/build_sources.py' if stale else 0)"

step "agent skills (site/skills.py) never run a command or pre-approve a tool when they load"
run python3 -c "
import sys; sys.path.insert(0, 'site'); from skills import tame
md = tame('---\\nname: x\\nallowed-tools: Bash(npx x *)\\nhooks:\\n  PreToolUse:\\n    - x\\ndescription: y\\n---\\nRun !\\x60npx x info\\x60 now.\\n')
sys.exit(0 if md.startswith('---\\nname: x\\ndescription: y\\n---\\n') and 'npx x info' in md and '!\\x60' not in md else 'not tamed: ' + md)"

step "archives of the kit stamp kit.py with their commit (./kit update needs it)"
if git rev-parse --git-dir >/dev/null 2>&1; then
  run grep -q '^KIT_COMMIT = "\$Format:%H\$"' tools/kit.py
  run sh -c 'git check-attr export-subst tools/kit.py | grep -q ": set$"'
  # and carry the kit's own files only: no tests, docs, website (besides the two site files the kit reads) or Mac app
  run sh -c '! git archive --worktree-attributes HEAD | tar -t | grep -Ev "^(site/|site/kit.json|site/sources.json)$" | grep -E "^(tests|docs|\.github|site|mac)/"'
  # and none of the developer tools (package.json's)
  run sh -c '! git archive --worktree-attributes HEAD | tar -t | grep -E "(^|/)(package(-lock)?\.json|eslint\.config\.mjs|node_modules/)"'
else
  echo "skipped (not a git checkout)"
fi

step "Windows scripts keep CRLF and plain ASCII (cmd misreads anything else), and each goto and call has its label"
run python3 -c "
import glob, re, sys
bad = [f for f in glob.glob('*.bat') + glob.glob('*.cmd') for d in [open(f, 'rb').read()] if d.count(b'\n') != d.count(b'\r\n') or not d.isascii()]
for f in glob.glob('*.bat') + glob.glob('*.cmd'):
    code = [l.strip() for l in open(f, encoding='ascii', errors='replace') if not re.match(r'\s*rem\b', l, re.I)]
    labels = [l[1:].split()[0].lower() for l in code if l.startswith(':') and len(l) > 1]
    used = {m.lower() for l in code for m in re.findall(r'(?i)\b(?:goto\s+:?|call\s+:)([\w-]+)', l)} - {'eof'}
    bad += [f'{f}: no label :{x}' for x in sorted(used - set(labels))] + [f'{f}: label :{x} twice' for x in sorted({x for x in labels if labels.count(x) > 1})]
sys.exit(f'{bad}' if bad else 0)"

step "page script parses"
run node -e '
const h = require("fs").readFileSync("tools/portal.html", "utf8");
const m = { exports: {} };
new Function("module", "exports", h.split("<script>")[1].split("</script>")[0])(m, m.exports);
if (typeof m.exports.isMapQuestion !== "function") throw new Error("Kit not exported");'

step "the kit page's formatting and lint (npm run lint)"
if [ -x node_modules/.bin/prettier ] && [ -x node_modules/.bin/eslint ]; then
  run npm run --silent lint
else
  echo "skipped (not installed: npm ci --ignore-scripts)"
fi

step "nothing the kit runs installs or runs npm's developer tools"
run sh -c '! grep -nwE "npm|npx|node_modules" kit kit.cmd SETUP.command SETUP-Windows.bat UNINSTALL.command UNINSTALL-Windows.bat \
  "Open Tinfoil Kit.command" "Open Tinfoil Kit for Windows.bat" tools/launch.sh tools/share.py mac/app.sh mac/TinfoilKit.m'

step "contribution gate"
out=$(node tests/pr_gate_test.js 2>&1); rc=$?
echo "$out" | grep -E "^FAIL" ; echo "$out" | tail -1
[ $rc -eq 0 ] || fail=1

step "workflows: pinned actions, read-only tokens, no injection"
out=$(python3 tests/actions_test.py 2>&1); rc=$?
echo "$out" | grep -E "^FAIL" ; echo "$out" | tail -1
[ $rc -eq 0 ] || fail=1

step "sync engine against the mock internet"
out=$(python3 tests/sync_test.py 2>&1); rc=$?
echo "$out" | grep -E "^FAIL" ; echo "$out" | tail -1
[ $rc -eq 0 ] || fail=1

step "sharing on the home network: the gate, the QR code, ./kit share and autostart"
out=$(python3 tests/share_test.py 2>&1); rc=$?
echo "$out" | grep -E "^FAIL" ; echo "$out" | tail -1
[ $rc -eq 0 ] || fail=1

step "the Mac app's file work and icon"
out=$(python3 tests/mac_test.py 2>&1); rc=$?
echo "$out" | grep -E "^FAIL" ; echo "$out" | tail -1
[ $rc -eq 0 ] || fail=1

step "map logic against mocks"
pids=""
start() { python3 tests/mock_services.py "$@" >/dev/null 2>&1 & pids="$pids $!"; }
start photon 12322; MOCK_PHOTON_OLD=1 start photon 12323; start graphhopper 18989; start llama 18081
trap 'kill $pids 2>/dev/null' EXIT
sleep 1.5
out=$(timeout 120 node tests/map_logic_test.js tools/portal.html); rc=$?
echo "$out" | grep -E "^FAIL" ; echo "$out" | tail -1
[ $rc -eq 0 ] || fail=1

echo
[ $fail -eq 0 ] && echo "QUICK GATE PASSED" || echo "QUICK GATE FAILED"
exit $fail
