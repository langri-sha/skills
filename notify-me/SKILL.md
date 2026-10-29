---
name: notify-me
user_invocable: true
description: 'Play an audio notification when the current task is done.'
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
