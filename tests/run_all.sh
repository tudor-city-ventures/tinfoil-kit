#!/bin/bash
# Full end-to-end test of the final kit (with maps) against the mock remote services.
set -u
T=/home/claude/test
cleanup() { pkill -f tools/launch.sh; pkill -f START-HERE; sleep 1; pkill -f llama-server; pkill -f kiwix-serve;
            pkill -f "mock_services.py (tiles|photon|graphhopper|llama)"; }
cleanup 2>/dev/null
pkill -f mock_remote.py; sleep 0.5; (python3 $T/mock_remote.py 19000 > /tmp/mock_remote.log 2>&1 &); sleep 1
rm -f $T/remote/STATE_V2; touch $T/remote/FLAKY
touch -d "2026-11-20 12:00" $T/remote/geofabrik/us-northeast-latest.osm.pbf $T/remote/photon/north-america/usa/photon-db-usa-1.3-latest.tar.bz2
rm -rf $T/drive && mkdir -p $T/drive && cp -a /home/claude/OfflineKit $T/drive/
cp $T/drive_kit_maps.json $T/drive/OfflineKit/kit.json
. $T/env.sh
cd $T/drive/OfflineKit
step() { echo; echo "=== $*"; }
step "plan";   ./kit plan | grep -A7 "\[maps\]"; ./kit plan | tail -2
step "sync v1"; ./kit sync -y > /tmp/sync1.log 2>&1; echo "exit $?"; grep -E "^\[[0-9]|FAILED|removed" /tmp/sync1.log | head -30
step "sync again (no-op)"; ./kit sync -y 2>&1 | tail -1
step "verify";  ./kit verify | tail -1
step "test";    timeout 600 ./kit test | tail -9
step "search";  ./kit search test | head -2
step "launcher"; (timeout 900 bash START-HERE.command --no-browser > /tmp/launch.out 2>&1 &); sleep 12; grep -E "Library:|AI:|Maps" /tmp/launch.out
(python3 $T/mock_services.py llama 18081 > /tmp/m_llama.log 2>&1 &)
(MOCK_PHOTON_OLD=1 python3 $T/mock_services.py photon 12323 > /tmp/m_photon_old.log 2>&1 &)
sleep 1
step "portal logic"; (cd $T && timeout 180 node portal_test.js drive/OfflineKit/tools/portal.html | tail -1)
step "map logic";    (cd $T && timeout 180 node map_logic_test.js drive/OfflineKit/tools/portal.html | tail -1)
step "portal UI";    (cd $T && timeout 240 python3 ui_test.py | tail -1)
step "map UI";       (cd $T && timeout 400 python3 map_ui_test.py | tail -1)
cleanup 2>/dev/null
step "launcher --no-maps"; (timeout 60 bash START-HERE.command --no-browser --no-maps > /tmp/launch2.out 2>&1 &); sleep 8
grep -q "Starting maps" /tmp/launch2.out && echo "FAIL: maps started" || echo "ok: no map servers"; pgrep -f "mock_services.py (tiles|photon|graphhopper)" >/dev/null && echo "FAIL: map process running" || true
cleanup 2>/dev/null
step "update (3 months later)"; touch $T/remote/STATE_V2; rm -f .kit/cache/kiwix-catalog.xml
touch -d "2027-02-03 06:00" $T/remote/geofabrik/us-northeast-latest.osm.pbf $T/remote/photon/north-america/usa/photon-db-usa-1.3-latest.tar.bz2
./kit sync -y > /tmp/sync2.log 2>&1; echo "exit $?"; grep -E "^\[[0-9]|removed|UPDATE" /tmp/sync2.log | head -30
step "test after update"; timeout 600 ./kit test | tail -1
step "status"; ./kit status | tail -14
cleanup 2>/dev/null
