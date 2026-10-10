#!/usr/bin/env bash
set -euo pipefail

message="${1:?Usage: notify.sh <message>}"
PROVIDER="${PROVIDER:-mistral}"

outfile=$(mktemp "${TMPDIR:-/tmp}/notify-me.XXXXXX.wav")
trap 'rm -f "$outfile"' EXIT

case "$PROVIDER" in
  mistral)
    curl -s https://api.mistral.ai/v1/audio/speech \
      -H "Authorization: Bearer $MISTRAL_API_KEY" \
      -H "Content-Type: application/json" \
      -d "$(jq -n --arg input "$message" '{
        model: "voxtral-mini-tts-2603",
        input: $input,
        voice_id: "a3e41ea8-020b-44c0-8d8b-f6cc03524e31",
        response_format: "wav"
      }')" \
      | jq -r '.audio_data' | base64 -d > "$outfile"
    ;;
  openai)
    curl -s https://api.openai.com/v1/audio/speech \
      -H "Authorization: Bearer $OPENAI_API_KEY" \
      -H "Content-Type: application/json" \
      -d "$(jq -n --arg input "$message" '{
        model: "gpt-4o-mini-tts",
        input: $input,
        voice: "marin",
        speed: 1.0,
        response_format: "wav"
      }')" \
      -o "$outfile"
    ;;
  *)
    echo "Unknown provider: $PROVIDER" >&2
    exit 1
    ;;
esac

ffplay -nodisp -autoexit "$outfile" 2>/dev/null
