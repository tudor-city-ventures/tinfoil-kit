#!/bin/bash
# Double-click me (macOS) to start the offline library and AI. Linux: run  bash "Open Tinfoil Kit.command"
# Add --share to let phones and laptops on your home network in, with an access code:  bash "Open Tinfoil Kit.command" --share
cd "$(dirname "$0")" && exec bash tools/launch.sh "$@"
