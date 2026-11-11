"""Worker card of an outsource team hides phone / address / map; the rest is unchanged."""

from __future__ import annotations

from bot.painter import texts

from .conftest import task


def test_outsource_worker_card_hides_contact():
    card = texts.task_card(task(outsource=True))
    assert "📞" not in card and "+998901234567" not in card
    assert "📍" not in card and "Chilonzor" not in card and "xarita" not in card
    assert "Karim Aliyev" in card and "№406" in card and "3.5" in card and "Emal" in card


def test_outsource_reassigned_card_hides_contact():
    card = texts.reassigned_card(task(outsource=True))
    assert "📞" not in card and "📍" not in card


def test_non_outsource_card_unchanged():
    card = texts.task_card(task(outsource=False))
    assert "📞 +998901234567" in card
    assert "📍 Chilonzor 7 &amp; 12" in card and "xarita" in card


def test_missing_outsource_key_is_false():
    t = task()
    t.pop("outsource")
    assert "📞" in texts.task_card(t)


def test_head_cards_keep_contact_even_if_outsource():
    t = task(outsource=True)
    assert "📞" in texts.head_card(t) and "📍" in texts.head_card(t)
    assert "📞" in texts.ready_msg(t)
