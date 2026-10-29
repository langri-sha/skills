---
name: notify-me
description: >-
  Speaks a one- or two-sentence summary aloud when the current task finishes,
  through Mistral or OpenAI text-to-speech, or rings a bell when no API key is
  set. Use when the user asks to be told, or notified, when the work is done.
  Not for an immediate sound (bell).
---

When the user invokes `/notify-me`, they want an audio notification when you
finish your current task.

## Behavior

1. Continue working on whatever task is in progress.
2. When the task is **complete**, run `notify.sh` with a short summary of what
   you accomplished.

## How to play the notification

Run `notify.sh`, where `<skill-dir>` is the directory holding this file:

```bash
bash <skill-dir>/notify.sh "<short summary of what was accomplished>"
```

Keep the summary to one or two sentences. If the task failed or was blocked, say
so honestly.
