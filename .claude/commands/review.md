---
description: Run reviewer on the current diff.
---

1. Determine the current diff scope (`git status`, `git diff`) and which service(s) it touches.
2. Dispatch `reviewer` on the resulting diff.
3. If the diff touches the backend↔bot contract (oauth.User schema, `/start` flow, `send_message`/webhook route) and `integration-guard` hasn't run yet in this session for this diff, dispatch it before `reviewer`'s verdict is treated as final.
4. Report `reviewer`'s findings and verdict directly — don't summarize away specific file:line findings.
