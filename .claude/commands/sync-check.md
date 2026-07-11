---
description: Runs integration-guard on the current state to verify the bot↔backend contract still holds.
---

Dispatch `integration-guard` against the current working tree state (not just a diff — check the full current contract, since this command is meant to catch drift even without a recent change):

1. Schema mirror: `backend/oauth/models.py` `User` vs `bot/db/models/oauth.py` `User`.
2. `/start` deep-link flow compatibility.
3. `send_message`/`POST /user/{chat_id}/message` contract shape.
4. `POSTGRES_*` env var name alignment between `backend/core/settings.py` and `bot/db/config.py`.

Report `integration-guard`'s full output verbatim (the OK/BREAK table + verdict) — don't paraphrase a BREAK finding away.
