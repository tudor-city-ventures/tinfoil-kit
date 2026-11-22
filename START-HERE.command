#!/bin/bash
# Double-click me (macOS) to start the offline library and AI. Linux: run  bash START-HERE.command
# Add --share to let phones and laptops on your home network in, with an access code:  bash START-HERE.command --share
cd "$(dirname "$0")" && exec bash tools/launch.sh "$@"
