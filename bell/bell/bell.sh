#!/usr/bin/env bash
set -euo pipefail

# Play a simple bell sound using the terminal bell as fallback
if command -v ffplay &>/dev/null && [[ -f /usr/share/sounds/freedesktop/stereo/bell.oga ]]; then
  ffplay -nodisp -autoexit /usr/share/sounds/freedesktop/stereo/bell.oga 2>/dev/null
elif command -v paplay &>/dev/null && [[ -f /usr/share/sounds/freedesktop/stereo/bell.oga ]]; then
  paplay /usr/share/sounds/freedesktop/stereo/bell.oga
elif command -v pw-play &>/dev/null && [[ -f /usr/share/sounds/freedesktop/stereo/bell.oga ]]; then
  pw-play /usr/share/sounds/freedesktop/stereo/bell.oga
else
  printf '\a'
fi
