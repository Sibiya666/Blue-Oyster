from barman.chat import build_request, render_search_reply, source_url
from barman.search_policy import search_policy
import asyncio
import json
import logging
import sys
from types import SimpleNamespace as NS

import pytest


def result(count=1, url="https://www.pathofexile.com/forum/view-forum/2212", answer="Лига стартует завтра."):
    data = {"id": "gen-test", "choices": [{"message": {"content": answer, "annotations": [
        {"type": "url_citation", "url_citation": {"url": url}}]}}]}
    if count is not None:
        data["usage"] = {"server_tool_use_details": {"web_search_requests": count}}
    return data


def test_screenshot_prompt_knows_poe2_default_and_only_clarifies_event():
    policy = search_policy("че когда поешечка выходит")
    assert policy.clarification and "?" in policy.clarification
    assert policy.game == "Path of Exile 2" and "полный релиз" in policy.clarification
    assert search_policy("Когда выйдет новая лига PoE 2?").clarification is None
    assert search_policy("Когда следующая лига Path of Exile?").clarification is None
    assert search_policy("Когда следующая лига поешечки во вторник?").game == "Path of Exile 2"
    assert search_policy("Когда следующая лига поешечки во вторник?").clarification is None
    assert search_policy("Когда новая лига PoE 1?").game == "Path of Exile"
    assert search_policy("Какая версия PoE 1.").game == "Path of Exile"
    assert search_policy("Когда новая лига поешечки?").game == "Path of Exile 2"
    assert search_policy("Когда новая лига Path of Exile?").game == "Path of Exile 2"
    assert search_policy("Когда новая лига первой поешечки?").game == "Path of Exile"
    assert search_policy("Когда пое 1.0 выходит?").game == "Path of Exile 2"


def test_fresh_game_search_uses_developer_domains():
    body = build_request("Персона", "Когда новая лига PoE 2?", "test/model")
    assert set(body["tools"][0]["parameters"]["allowed_domains"]) == {"pathofexile.com", "pathofexile2.com"}
    assert "news.blizzard.com" in search_policy("Последние патчноуты Diablo IV").domains
    assert not search_policy("Привет").requires_evidence
    assert not search_policy("Как у тебя настроение сегодня?").requires_evidence
    assert not search_policy("Когда у тебя выходной?").requires_evidence
    assert not search_policy("Расскажи анекдот про новости").requires_evidence
    assert search_policy("PoE 2: во сколько следующая лига?").requires_evidence


def test_no_verified_fresh_facts_without_search_counter_and_source():
    for count in (0, None):
        reply = render_search_reply(result(count=count), "Когда новая лига PoE 2?")
        assert reply["status"] == "unverified_fresh"
        assert "завтра" not in reply["prose"]
        assert reply["source"] is None
    reply = render_search_reply(result(url="https://dtf.ru/funpay/spam"), "Когда новая лига PoE 2?")
    assert reply["status"] == "unverified_fresh" and not reply["source"]
    reply = render_search_reply(result(url="https://www.pathofexile.com/forum/view-thread/123"), "Когда новая лига PoE 2?")
    assert reply["status"] == "unverified_fresh"  # no authenticated author: may be a user post


def test_verified_search_has_count_and_developer_source():
    reply = render_search_reply(result(), "Когда новая лига PoE 2?")
    assert reply["status"] == "verified_search"
    assert reply["web_search_requests"] == 1
    assert reply["source"].startswith("https://www.pathofexile.com/")
    assert render_search_reply(result(url="https://www.pathofexile.com/forum/view-forum/patch-notes"),
                               "Какая версия PoE 2?")["status"] == "unverified_fresh"


def test_token_truncated_reply_is_not_published_as_verified_fact():
    data = result(answer="Последний патч 3.29.3c, автор Kieren_GG")
    data["choices"][0]["finish_reason"] = "length"
    reply = render_search_reply(data, "Какая версия PoE 2?")
    assert reply["status"] == "truncated_response"
    assert reply["source"] is None and "Kieren" not in reply["prose"]


@pytest.mark.parametrize("question", ["Сколько стоит Diablo IV?", "Какая версия PoE 2?",
    "Когда выйдет новая лига PoE 2? И пошути в конце.", "Когда выйдет PoE 2? И пошути в конце."])
def test_current_factual_questions_cannot_skip_search_or_disable_it_with_a_joke(question):
    assert search_policy(question).requires_evidence
    assert render_search_reply(result(count=0), question)["status"] == "unverified_fresh"


def test_domain_filter_checks_boundaries_not_substrings():
    annotation = lambda url: [{"type": "url_citation", "url_citation": {"url": url}}]
    assert source_url(annotation("https://pathofexile.com.evil.example/x"), ("pathofexile.com",)) is None
    assert source_url(annotation("https://ru.pathofexile.com/forum/view-forum/news"), ("pathofexile.com",))


def test_vague_poe_question_cannot_bypass_source_checks():
    assert search_policy("таки что там по поешечке").requires_evidence
    reply = render_search_reply(result(url="https://dtf.ru/funpay/spam"), "таки что там по поешечке")
    assert reply["status"] == "unverified_fresh"
    assert search_policy("Почему в PoE 2 не работает торговля?").requires_evidence
    assert render_search_reply(result(count=0), "Почему в PoE 2 не работает торговля?")["status"] == "unverified_fresh"


def test_official_announcement_section_is_allowed_but_general_forum_is_not():
    data = result(url="https://www.pathofexile.com/forum/view-thread/3999366")
    citation = data["choices"][0]["message"]["annotations"][0]["url_citation"]
    citation["title"] = "Early Access Announcements - Path of Exile 2 Fully Releases on December 11! - Forum - Path of Exile"
    assert render_search_reply(data, "Когда полный релиз PoE 2?")["status"] == "verified_search"
    citation["title"] = "General Discussion - Early Access Announcements - Fan predictions - Forum"
    assert render_search_reply(data, "Когда полный релиз PoE 2?")["status"] == "unverified_fresh"
    citation["title"] = "Announcements - First game news - Forum - Path of Exile"
    assert render_search_reply(data, "Когда полный релиз PoE 2?")["status"] == "unverified_fresh"


@pytest.fixture
def reply_path(tmp_path, monkeypatch):
    from barman.chat import answer_owner
    state = NS(data=result(), posts=[], replies=[], fail_delivery=False)

    class Context:
        def __init__(self, value): self.value = value
        async def __aenter__(self): return self.value
        async def __aexit__(self, *args): return False

    async def response_json(): return state.data

    def post(url, **kwargs):
        state.posts.append(kwargs)
        return Context(NS(status=200, raise_for_status=lambda: None, json=response_json))

    monkeypatch.setitem(sys.modules, "aiohttp", NS(
        ClientSession=lambda **kwargs: Context(NS(post=post)), ClientTimeout=lambda **kwargs: None))
    monkeypatch.setitem(sys.modules, "discord", NS(AllowedMentions=NS(none=lambda: None)))
    (tmp_path / "SOUL.md").write_text("Персона", encoding="utf-8")

    async def send(text, **kwargs):
        if state.fail_delivery:
            raise RuntimeError("delivery failed")
        state.replies.append(text)
        return NS(id=2)

    def run(text):
        asyncio.run(answer_owner(NS(id=1, reply=send), text, {"OPENROUTER_API_KEY": "token-secret"}, tmp_path))
    return state, run


def audit(caplog):
    return json.loads(next(r.message.split("reply_audit ", 1)[1] for r in caplog.records if "reply_audit " in r.message))


def test_ambiguous_reply_does_not_call_model_and_is_audited(reply_path, caplog):
    state, run = reply_path
    caplog.set_level(logging.INFO, logger="barman.chat")
    run("че когда поешечка выходит")
    assert not state.posts
    assert state.replies == ["Про новую лигу, обновление или полный релиз PoE 2?"]
    assert audit(caplog)["status"] == "clarification"


def test_successful_search_is_logged_without_keys_queries_or_conversation(reply_path, caplog):
    state, run = reply_path
    state.data = result(url="https://www.pathofexile.com/news?private=hidden")
    caplog.set_level(logging.INFO, logger="barman.chat")
    run("Когда новая лига PoE 2?")
    record = audit(caplog)
    assert record["web_search_requests"] == 1 and record["delivered"] is True
    assert record["reply_message_id"] == "2" and record["sentences"] <= 2
    assert record["source"] == "https://www.pathofexile.com/news"
    assert record["chars"] == len(state.replies[0]) and record["chars"] > record["prose_chars"]
    assert all(secret not in caplog.text for secret in ("token-secret", "private=hidden", "Когда новая"))
    assert "allowed_domains" in state.posts[0]["json"]["tools"][0]["parameters"]


def test_fresh_claim_without_search_is_not_delivered_as_fact(reply_path, caplog):
    state, run = reply_path
    state.data = result(count=0)
    caplog.set_level(logging.INFO, logger="barman.chat")
    run("Когда новая лига PoE 2?")
    assert "завтра" not in state.replies[0] and "https://" not in state.replies[0]
    assert audit(caplog)["status"] == "unverified_fresh"


def test_failed_delivery_is_not_logged_as_delivered(reply_path, caplog):
    state, run = reply_path
    state.fail_delivery = True
    caplog.set_level(logging.INFO, logger="barman.chat")
    with pytest.raises(RuntimeError, match="delivery failed"):
        run("Когда новая лига PoE 2?")
    assert audit(caplog)["delivered"] is False
