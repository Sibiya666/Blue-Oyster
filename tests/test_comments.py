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


def test_temporary_permission_expires_at_the_exact_deadline():
    settings=_settings(BARMAN_COMMENT_UNTIL=(T0+timedelta(hours=2)).isoformat())
    gate=CommentGate(settings)
    kwargs=dict(author_id='42',channel_id='7',content='Продолжение разговора',mentions_bot=False,author_is_bot=False,roll=0.0)
    assert gate.should_comment(now=T0,**kwargs)
    assert not gate.should_comment(now=T0+timedelta(hours=2),**kwargs)
    assert not settings.active_at(T0+timedelta(hours=2,seconds=1))


def test_invalid_or_naive_permission_deadline_never_becomes_unlimited():
    for deadline in ('invalid','2026-11-07T20:15:03',''):
        assert _settings(BARMAN_COMMENT_UNTIL=deadline) is None


def test_temporary_conversation_allows_short_implicit_address_for_model_assessment():
    kwargs=dict(author_id='42',channel_id='7',content='Бармен?',mentions_bot=False,author_is_bot=False,now=T0,roll=0.0)
    assert CommentGate(_settings(BARMAN_COMMENT_UNTIL=(T0+timedelta(hours=2)).isoformat())).should_comment(**kwargs)
    assert not CommentGate(_settings()).should_comment(**kwargs)


def test_conversation_skip_does_not_consume_reply_cooldown_and_inflight_is_bounded():
    gate=CommentGate(_settings(BARMAN_COMMENT_UNTIL=(T0+timedelta(hours=2)).isoformat(),BARMAN_COMMENT_COOLDOWN_MIN='1'))
    kwargs=dict(author_id='42',channel_id='7',content='Продолжение разговора',mentions_bot=False,author_is_bot=False,roll=0.0)
    gate.begin(T0)
    assert not gate.should_comment(now=T0+timedelta(seconds=1),**kwargs)
    gate.complete(T0+timedelta(seconds=2),posted=False)
    assert gate.should_comment(now=T0+timedelta(seconds=3),**kwargs)
    gate.begin(T0+timedelta(seconds=3))
    gate.complete(T0+timedelta(seconds=4),posted=True)
    assert not gate.should_comment(now=T0+timedelta(seconds=30),**kwargs)
    assert gate.should_comment(now=T0+timedelta(seconds=65),**kwargs)
