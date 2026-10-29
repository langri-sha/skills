#!/usr/bin/env bash
set -euo pipefail

message="${1:?Usage: notify.sh <message>}"
PROVIDER="${PROVIDER:-mistral}"

bell() {
  local sound=/usr/share/sounds/freedesktop/stereo/bell.oga
  if [[ -f "$sound" ]] && command -v ffplay &>/dev/null; then
    ffplay -nodisp -autoexit "$sound" 2>/dev/null
  elif [[ -f "$sound" ]] && command -v paplay &>/dev/null; then
    paplay "$sound"
  elif [[ -f "$sound" ]] && command -v pw-play &>/dev/null; then
    pw-play "$sound"
  else
    printf '\a'
  fi
}

case "$PROVIDER" in
  mistral) key_var=MISTRAL_API_KEY ;;
  openai) key_var=OPENAI_API_KEY ;;
  *) key_var= ;;
esac
if [[ -n "$key_var" && -z "${!key_var:-}" ]]; then
  echo "$key_var is not set, so ringing a bell instead: $message" >&2
  bell
  exit 0
fi

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
