import asyncio
from datetime import datetime, timedelta, timezone

from barman.comments import CommentGate, build_messages, clean_reply, parse_settings

T0 = datetime(2026, 10, 26, 18, 0, tzinfo=timezone.utc)


def _settings(**kw):
    env = {"BARMAN_COMMENT_USERS": "42,43", "BARMAN_COMMENT_CHANNELS": "7", "BARMAN_COMMENT_CHANCE": "0.1",
           "BARMAN_COMMENT_COOLDOWN_MIN": "60"}
    env.update(kw)
    return parse_settings(env)


def test_parse_settings_defaults_and_off():
    s = parse_settings({"BARMAN_COMMENT_USERS": "42", "BARMAN_COMMENT_CHANNELS": "7"})
    assert s.users == {"42"} and s.channels == {"7"} and s.chance == 0.1 and s.cooldown == timedelta(minutes=60)
    assert parse_settings({}) is None                                   # не настроено — выключено
    assert parse_settings({"BARMAN_COMMENT_USERS": "42"}) is None       # без канала — выключено
    assert parse_settings({"BARMAN_COMMENT_USERS": "0", "BARMAN_COMMENT_CHANNELS": "7"}) is None
    assert _settings(BARMAN_COMMENT_CHANCE="5").chance == 1.0           # больше 1 — режем до 1
    assert _settings(BARMAN_COMMENT_CHANCE="мусор").chance == 0.1


def test_gate_only_listed_user_in_listed_channel_with_chance():
    g = CommentGate(_settings())
    ok = dict(author_id="42", channel_id="7", content="покрасил нового рыцаря", mentions_bot=False,
              author_is_bot=False, now=T0, roll=0.05)
    assert g.should_comment(**ok)
    g2 = CommentGate(_settings())
    assert not g2.should_comment(**{**ok, "author_id": "99"})          # чужой — нет
    assert not g2.should_comment(**{**ok, "channel_id": "8"})          # другой канал — нет
    assert not g2.should_comment(**{**ok, "roll": 0.5})                # не выпало — нет
    assert not g2.should_comment(**{**ok, "mentions_bot": True})       # обращение — это к Hermes, не дублируем
    assert not g2.should_comment(**{**ok, "author_is_bot": True})
    assert not g2.should_comment(**{**ok, "content": "https://x.y/z"})  # только ссылка — нечего комментировать
    assert not g2.should_comment(**{**ok, "content": "ок"})            # слишком коротко
    assert not g2.should_comment(**{**ok, "content": "/help"})         # команда


def test_gate_cooldown():
    g = CommentGate(_settings())
    base = dict(author_id="42", channel_id="7", content="напечатал сорок скелетов", mentions_bot=False,
                author_is_bot=False, roll=0.0)
    assert g.should_comment(now=T0, **base)
    g.mark(T0)
    assert not g.should_comment(now=T0 + timedelta(minutes=59), **base)
    assert g.should_comment(now=T0 + timedelta(minutes=61), **base)


def test_build_messages_uses_soul_and_context_but_marks_it_as_data():
    msgs = build_messages("ТЫ БАРМЕН", "Angmar", "покрасил нового рыцаря",
                          [("Fidel", "красиво"), ("Angmar", "покрасил нового рыцаря")])
    assert msgs[0] == {"role": "system", "content": msgs[0]["content"]}
    assert msgs[0]["content"].startswith("ТЫ БАРМЕН")
    user = msgs[-1]["content"]
    assert "покрасил нового рыцаря" in user and "Fidel: красиво" in user
    assert "данные" in user and "одной" in user.lower() and "SKIP" in user


def test_clean_reply_strips_pings_keeps_server_emoji_and_skips_empty():
    assert clean_reply("класс <:peka:123>") == "класс <:peka:123>"
    out = clean_reply("@everyone смотрите <@555> <@&9>")
    assert "@everyone" not in out and "<@" not in out
    assert clean_reply("   ") is None
    assert clean_reply("SKIP") is None                                   # модель решила промолчать
    assert len(clean_reply("а" * 1000)) <= 300
