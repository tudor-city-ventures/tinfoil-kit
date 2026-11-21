#!/bin/bash
# End-to-end test of the kit against the mock internet. Run tests/build_fixtures.sh first.
# Copies the kit onto a fake drive, syncs, tests, launches, drives the page, then simulates
# an update 3 months later. Exits non-zero if anything failed.
set -u
TESTS="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$TESTS")"
export KIT_TEST_DIR="$TESTS"
export KIT_TEST_WORK="${KIT_TEST_WORK:-$TESTS/work}"
W="$KIT_TEST_WORK" R="$KIT_TEST_WORK/remote" L="$KIT_TEST_WORK/logs"
[ -f "$R/gh2/basemaps-assets.sha" ] || { echo "No fixtures. Run tests/build_fixtures.sh first."; exit 2; }
mkdir -p "$L"
D="$W/drive/TinfoilKit"

cleanup() { pkill -f tools/launch.sh; pkill -f START-HERE; sleep 1; pkill -f llama-server; pkill -f kiwix-serve;
            pkill -f "mock_services.py (tiles|photon|graphhopper|llama)"; }
main() {
cleanup 2>/dev/null
pkill -f mock_remote.py; sleep 0.5; (python3 "$TESTS/mock_remote.py" 19000 > "$L/mock_remote.log" 2>&1 &); sleep 1
rm -f "$R/STATE_V2"; touch "$R/FLAKY"
touch -d "2026-11-20 12:00" "$R/geofabrik/us-northeast-latest.osm.pbf" "$R/photon/north-america/usa/photon-db-usa-1.3-latest.tar.bz2"
rm -rf "$W/drive" && mkdir -p "$D"
cp -a "$ROOT"/{kit,kit.json,START-HERE.command,SETUP.command,START-HERE-Windows.bat,GUIDE.md,tools} "$D/"
cp "$TESTS/drive_kit_maps.json" "$D/kit.json"
. "$TESTS/env.sh"
cd "$D" || exit 1
step() { echo; echo "=== $*"; }
# Runs one test: prints its failures and last line, and FAIL if it crashed or timed out. Full output in logs/.
run_test() { # log-name seconds command...
  local log="$L/$1.log" secs="$2" rc; shift 2
  timeout "$secs" "$@" > "$log" 2>&1; rc=$?
  grep -E "^FAIL" "$log"; tail -1 "$log"
  [ $rc -eq 0 ] || echo "FAIL: exit $rc, see $log"
}
step "plan";   ./kit plan | grep -A7 "\[maps\]"; ./kit plan | tail -2
step "sync v1"; ./kit sync -y > "$L/sync1.log" 2>&1; rc=$?
grep -E "^\[[0-9]|FAILED|removed" "$L/sync1.log" | head -30
# Three entries are broken on purpose: sync installs everything else, names them, and exits 1.
[ $rc -eq 1 ] && echo "ok: exit 1" || echo "FAIL: sync exit $rc, expected 1"
for k in models/Ambiguous models/Missing library/does_not_exist_en; do
  grep -q -- "- $k:" "$L/sync1.log" || echo "FAIL: $k not listed under Problems"
done
python3 -c "
import json; c = json.load(open('kit.json'))
c['models'] = [m for m in c['models'] if m['id'] not in ('Ambiguous', 'Missing')]
c['library'] = [z for z in c['library'] if z['zim'] != 'does_not_exist_en']
json.dump(c, open('kit.json', 'w'), indent=2)"
step "verify";  ./kit verify | tail -1
# SETUP.command = plan, sync (a no-op now), test. Answers: start download yes, open the kit no, close.
step "setup (sync again, then test)"; printf 'y\nn\n\n' | timeout 600 bash SETUP.command > "$L/setup.log" 2>&1; echo "exit $?"
grep -E "PASS|FAIL|up to date|All set" "$L/setup.log" | tail -12
step "search";  ./kit search test | head -2
step "launcher"; (timeout 900 bash START-HERE.command --no-browser > "$L/launch.out" 2>&1 &); sleep 12; grep -E "Library:|AI:|Maps" "$L/launch.out"
(python3 "$TESTS/mock_services.py" llama 18081 > "$L/m_llama.log" 2>&1 &)
(MOCK_PHOTON_OLD=1 python3 "$TESTS/mock_services.py" photon 12323 > "$L/m_photon_old.log" 2>&1 &)
sleep 1
step "portal logic"; run_test portal_logic 180 node "$TESTS/portal_test.js" "$D/tools/portal.html"
step "map logic";    run_test map_logic 180 node "$TESTS/map_logic_test.js" "$D/tools/portal.html"
step "portal UI";    run_test portal_ui 240 python3 "$TESTS/ui_test.py"
step "map UI";       run_test map_ui 400 python3 "$TESTS/map_ui_test.py"
cleanup 2>/dev/null
step "launcher --no-maps"; (timeout 60 bash START-HERE.command --no-browser --no-maps > "$L/launch2.out" 2>&1 &); sleep 8
grep -q "Starting maps" "$L/launch2.out" && echo "FAIL: maps started" || echo "ok: no map servers"
pgrep -f "mock_services.py (tiles|photon|graphhopper)" >/dev/null && echo "FAIL: map process running"
cleanup 2>/dev/null
step "update (3 months later)"; touch "$R/STATE_V2"; rm -f .kit/cache/kiwix-catalog.xml
touch -d "2027-02-03 06:00" "$R/geofabrik/us-northeast-latest.osm.pbf" "$R/photon/north-america/usa/photon-db-usa-1.3-latest.tar.bz2"
./kit sync -y > "$L/sync2.log" 2>&1; echo "exit $?"; grep -E "^\[[0-9]|removed|UPDATE" "$L/sync2.log" | head -30
step "test after update"; timeout 600 ./kit test | tail -1
step "status"; ./kit status | tail -14
cleanup 2>/dev/null
pkill -f mock_remote.py
}

main 2>&1 | tee "$L/e2e.log"
echo
if grep -qE "^FAIL|FAILED|^exit [1-9]|Traceback" "$L/e2e.log"; then echo "E2E FAILED (logs in $L)"; exit 1; fi
echo "E2E PASSED"
