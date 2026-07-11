---
description: Fix a bug — tester writes a failing repro test first, then the right dev agent fixes it.
---

Bug: $ARGUMENTS

1. Determine which service the bug is in (backend, bot, or the contract between them) from the description — ask if genuinely ambiguous.
2. Dispatch `tester` to write a failing repro test first. Run it, confirm it fails for the stated reason before touching any implementation code.
3. Dispatch `architect` only if the fix isn't obvious/localized (e.g. it implies a design change, not just a local correction). For a localized fix, skip straight to step 4.
4. Dispatch the matching dev agent (`django-dev` and/or `bot-dev`; both + `integration-guard` if the bug is in the shared contract — schema mirror, `/start` flow, `send_message`/webhook).
5. Re-run the repro test, confirm it now passes.
6. Dispatch `linter` then `reviewer`. Loop on CHANGES REQUIRED, max 3 times.
7. Summary: **root cause / fix / test (before-fail, after-pass) / reviewed.**
