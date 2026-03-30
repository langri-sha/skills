#!/usr/bin/env bash
set -euo pipefail

message="${1:?Usage: notify.sh <message>}"

curl -s https://api.openai.com/v1/audio/speech \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg input "$message" '{
    model: "gpt-4o-mini-tts",
    input: $input,
    voice: "nova",
    response_format: "mp3"
  }')" \
  -o /tmp/notify-me.mp3

ffplay -nodisp -autoexit /tmp/notify-me.mp3 2>/dev/null
