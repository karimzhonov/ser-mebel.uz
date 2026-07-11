---
description: Full pipeline for a new feature or change — auto-detects which service(s) are affected.
---

Task: $ARGUMENTS

Run the full pipeline from root `CLAUDE.md`:

1. Dispatch to `architect` with the task description. It reads both services' `CLAUDE.md` and `docs/ARCHITECTURE_ANALYSIS.md`, then produces a design stating which service(s) are touched and whether the backend↔bot contract is involved.
2. Based on the architect's scope call:
   - Backend only → dispatch `django-dev`.
   - Bot only → dispatch `bot-dev`.
   - Both / contract touched → dispatch both `django-dev` and `bot-dev` (they can run in parallel if their file scopes don't overlap), then dispatch `integration-guard`.
3. Dispatch `tester` per the architect's test plan. For any bug-shaped part of the task, the failing repro test must exist and be confirmed failing before the fix, then confirmed passing after.
4. Dispatch `linter` on the files that changed.
5. Dispatch `reviewer`. If it returns CHANGES REQUIRED, loop back to the relevant dev agent — max 3 loops total. If still not resolved after 3, stop and report to the user instead of looping further.
6. Finish with a summary: **designed / changed / tested (results) / reviewed.**

If the task is trivial (typo, copy tweak, comment-only change), skip the pipeline and say so explicitly instead of dispatching agents.
