"""Report renderers vs the text of the old backend/hr/reports.py.

`snapshots.json` holds the old builders' output for fixture data (generated once by running
the old code over the same data); the DTOs are stored next to it so the test is self-contained.
"""

import json
from pathlib import Path

from bot.hr import reports as R

from .conftest import fixture

SNAP = json.loads((Path(__file__).parent / "snapshots.json").read_text(encoding="utf-8"))


def test_live_day_report_matches_old_text():
    assert R.render_day(SNAP["_live_dto"], "T") == SNAP["day_live"]


def test_past_day_report_matches_old_text():
    assert R.render_day(SNAP["_past_dto"], "x") == SNAP["day_past"]
    assert "Bu kun uchun ma'lumot yo'q." in R.render_day(
        {"kind": "past", "day": "2026-10-26", "empty": True}, "x"
    )


def test_period_ranking_year_match_old_text():
    assert R.period_report(SNAP["_period_dto"], "T") == SNAP["period"]
    assert R.ranking_text(SNAP["_rank_rows"], "R") == SNAP["ranking"]
    assert R.ranking_text([], "R") == SNAP["ranking_empty"]
    assert R.month_winner_text("2026-10", SNAP["_rank_rows"]) == SNAP["month_winner"]
    assert R.year_report("2026", SNAP["_year_rows"]) == SNAP["year"]
    assert R.year_report("2026", []) == SNAP["year_empty"]


def test_contract_fixtures_render():
    live = fixture("dto.day_report_data.1")
    text = R.render_day(live, "📊 Kunlik hisobot (11:30)")
    assert "Kech qolganlar" in text and "Azizbek — 09:40 (+40 daq) — Sababsiz: probka" in text
    assert "Chilonzor filiali: ✅5 ⏰1 ⏳1 ❌1 📝1" in text
    assert "Botga ulanmaganlar (1): Hasan" in text
    assert "Kecha erta ketganlar" in text and "Kecha ketish otchetini tashlamaganlar" in text
    assert "Kecha" not in R.render_day(fixture("dto.day_report_data.2"), "x")
    assert "E'tibor talab qiladi" in R.period_report(fixture("dto.period_report_data.1"), "P")
