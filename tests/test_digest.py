import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from barman.digest import (MSK, DigestState, collect_day, day_window, due_slot, format_digest, next_slot,
                           pick_top, plain_text, sanitize, summarize)


def _e(i, date, likes=0, comments=0, news=False, title=None, desc=None, text=None):
    return {"id": i, "date": date, "isNews": news, "title": title or f"Пост {i}",
            "url": f"https://dtf.ru/x/{i}", "ogDescription": desc,
            "blocks": [{"type": "text", "data": {"text": text}}] if text else [],
            "likes": {"counterLikes": likes}, "counters": {"comments": comments}}


DAY = datetime(2026, 10, 25, 15, 0, tzinfo=MSK)
START, END = day_window(DAY)


def test_day_window_is_moscow_calendar_day():
    assert datetime.fromtimestamp(START, MSK) == datetime(2026, 10, 25, 0, 0, tzinfo=MSK)
    assert END - START == 24 * 3600
    late_utc = datetime(2026, 10, 25, 22, 30, tzinfo=timezone.utc)   # в Москве уже 26-е
    assert datetime.fromtimestamp(day_window(late_utc)[0], MSK).day == 26


def test_pick_top_news_first_then_popular_posts_today_only():
    entries = [_e(1, START + 10, likes=5, news=True), _e(2, START + 20, likes=300, comments=50),
               _e(3, START + 30, likes=1, comments=1, news=True), _e(4, START - 5, likes=999, news=True),
               _e(5, START + 40, likes=100), _e(6, END + 1, likes=999), _e(2, START + 20, likes=300)]
    top = pick_top(entries, START, END, n=4)
    assert [e["id"] for e in top] == [1, 3, 2, 5]          # новости по популярности, затем посты; без дублей


def test_pick_top_likes_none_counts_as_zero():
    top = pick_top([{**_e(1, START + 1, comments=3), "likes": {"counterLikes": None}}], START, END)
    assert [e["id"] for e in top] == [1]


def test_plain_text_strips_html_and_limits():
    e = _e(1, 0, desc="Коротко.", text="<p>Первый <b>абзац</b> &amp; ещё</p>")
    assert plain_text(e) == "Коротко.\nПервый абзац & ещё"
    assert len(plain_text(_e(2, 0, text="<p>" + "а" * 5000 + "</p>"), limit=100)) == 100


def test_sanitize_kills_mentions_and_limits_length():
    s = sanitize("Привет @everyone и @here, <@123> <@&9> <#5> " + "x" * 500, limit=60)
    assert "@everyone" not in s and "@here" not in s and "<@" not in s and "<#" not in s
    assert len(s) <= 60


def test_next_slot_is_next_21_moscow():
    assert next_slot(datetime(2026, 10, 25, 20, 59, tzinfo=MSK)) == datetime(2026, 10, 25, 21, 0, tzinfo=MSK)
    assert next_slot(datetime(2026, 10, 25, 21, 0, tzinfo=MSK)) == datetime(2026, 10, 26, 21, 0, tzinfo=MSK)


def test_due_slot_first_run_catch_up_and_no_repeat(tmp_path):
    st = DigestState(tmp_path / "d.json")
    morning = datetime(2026, 10, 25, 10, 0, tzinfo=MSK)
    assert due_slot(st.last_posted(), morning) == morning                 # первая публикация — сразу
    st.mark(morning)
    assert DigestState(tmp_path / "d.json").last_posted() == morning      # переживает перезапуск
    assert due_slot(st.last_posted(), morning + timedelta(hours=1)) is None   # до 21:00 — ждём
    late = datetime(2026, 10, 25, 22, 0, tzinfo=MSK)
    assert due_slot(st.last_posted(), late) == datetime(2026, 10, 25, 21, 0, tzinfo=MSK)  # пропустили 21:00
    st.mark(late)
    assert due_slot(st.last_posted(), late + timedelta(minutes=30)) is None   # повторно не постим


def test_collect_day_paginates_until_older_than_day_and_skips_wrappers():
    pages = [
        {"items": [{"type": "entry", "data": _e(1, START + 5)},
                   {"type": "news", "data": {"news": [{"type": "entry", "data": _e(2, START + 6, news=True)}]}}],
         "lastId": 2, "lastSortingValue": "100"},
        {"items": [{"type": "entry", "data": _e(3, START - 100)}], "lastId": 3, "lastSortingValue": "50"},
        {"items": [{"type": "entry", "data": _e(4, START - 200)}], "lastId": 4, "lastSortingValue": "10"},
    ]
    urls = []

    async def fetch(url):
        urls.append(url)
        return pages[len(urls) - 1] if len(urls) <= len(pages) else {"items": []}

    got = asyncio.run(collect_day(fetch, START, max_pages=10))
    assert {e["id"] for e in got} == {1, 2, 3, 4}
    assert "lastId=2" in urls[1] and "lastSortingValue=100" in urls[1]


def test_collect_day_stops_on_repeating_page():
    page = {"items": [{"type": "entry", "data": _e(1, START + 5)}], "lastId": 1, "lastSortingValue": "1"}
    calls = []

    async def fetch(url):
        calls.append(url)
        return page

    assert [e["id"] for e in asyncio.run(collect_day(fetch, START, max_pages=50))] == [1]
    assert len(calls) <= 2


def test_summarize_uses_llm_json_and_falls_back_to_description():
    items = [_e(1, 0, title="A", desc="опис A"), _e(2, 0, title="B", desc="опис B")]
    seen = {}

    async def llm(messages):
        seen["prompt"] = messages[-1]["content"]
        return 'Вот: ["Пересказ A", "Пересказ B @everyone"]'

    out = asyncio.run(summarize(items, llm))
    assert out[0] == "Пересказ A" and "@everyone" not in out[1]
    assert "A" in seen["prompt"] and "опис B" in seen["prompt"]

    async def broken(messages):
        raise RuntimeError("openrouter down")
    assert asyncio.run(summarize(items, broken)) == ["опис A", "опис B"]

    async def short(messages):
        return '["только один"]'
    assert asyncio.run(summarize(items, short)) == ["опис A", "опис B"]   # не то число — не верим

    assert asyncio.run(summarize(items, None)) == ["опис A", "опис B"]     # без ключа ИИ


def test_format_digest_mentions_once_and_fits_discord_limit():
    items = [_e(i, 0, likes=i, comments=2 * i, news=(i == 1), title=f"Заголовок {i}") for i in range(1, 11)]
    pages = format_digest(items, ["Пересказ " + "з" * 250] * 10, "<@42>", datetime(2026, 10, 25, 21, tzinfo=MSK))
    assert all(len(p) <= 2000 for p in pages) and len(pages) >= 2
    joined = "\n".join(pages)
    assert pages[0].startswith("<@42>") and joined.count("<@42>") == 1
    assert "25 октября" in pages[0]
    assert "[Заголовок 1](<https://dtf.ru/x/1>)" in joined            # без превью-эмбедов
    assert "👍 10 · 💬 20" in joined and "📰" in joined


def test_format_digest_without_mention_and_empty_day():
    assert format_digest([], [], None, DAY)[0].startswith("За 25 октября на DTF")
