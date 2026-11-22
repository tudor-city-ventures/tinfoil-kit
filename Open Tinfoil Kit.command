#!/bin/bash
# Double-click me (macOS) to start the offline library and AI. Linux: run  bash "Open Tinfoil Kit.command"
# Add --share to let phones and laptops on your home network in, with an access code:  bash "Open Tinfoil Kit.command" --share
# Also: --model=NAME (the AI to load first: a folder in downloads/models), --no-browser, and --no-maps (doesn't start
# the map's servers, which saves about 5 GB of memory). The kit's own program does it all (./kit says what to do
# when this computer has none).
cd "$(dirname "$0")" && exec ./kit open "$@"
