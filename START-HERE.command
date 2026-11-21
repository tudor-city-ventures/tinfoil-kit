#!/bin/bash
# Double-click me (macOS) to start the offline library and AI. Linux: run  bash START-HERE.command
# Add --share to let phones on the same Wi-Fi/hotspot use it:  bash START-HERE.command --share
cd "$(dirname "$0")" && exec bash tools/launch.sh "$@"
