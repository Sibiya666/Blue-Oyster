from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

from barman.link_pilot import PilotSettings, PilotState, eligible, parse_decision

NOW = datetime(2026, 11, 7, tzinfo=timezone.utc)
SETTINGS = PilotSettings('7', NOW, NOW + timedelta(days=7))


def msg(author=8, guild=10, mentions=(7,), bot=False):
    return NS(id=100, author=NS(id=author, bot=bot), guild=NS(id=guild) if guild else None,
              mentions=[NS(id=i) for i in mentions], webhook_id=None, content='Когда релиз?', created_at=NOW)


def test_only_live_human_questions_directed_to_owner_in_own_server_are_candidates():
    assert eligible(msg(), SETTINGS, '10', '99', NOW)
    assert not eligible(msg(guild=None), SETTINGS, '10', '99', NOW)
    assert not eligible(msg(guild=11), SETTINGS, '10', '99', NOW)
    assert not eligible(msg(bot=True), SETTINGS, '10', '99', NOW)
    assert not eligible(msg(author=7), SETTINGS, '10', '99', NOW)
    assert not eligible(msg(mentions=(7,99)), SETTINGS, '10', '99', NOW)
    assert not eligible(msg(mentions=()), SETTINGS, '10', '99', NOW)
    assert eligible(msg(mentions=()), SETTINGS, '10', '99', NOW, reference_author='7')
    assert not eligible(msg(), SETTINGS, '10', '99', NOW + timedelta(days=7))


def test_invalid_or_personal_decisions_cannot_trigger_search():
    assert parse_decision('{"answerable":true,"confidence":"high","query":"Product release date"}') == 'Product release date'
    for text in ('{}', 'not json', '{"answerable":true,"confidence":"low","query":"anything"}',
                 '{"answerable":false,"confidence":"high","query":"anything"}',
                 '{"answerable":true,"confidence":"high","query":"<@7> private"}'):
        assert parse_decision(text) is None


def test_reservations_survive_restart_and_daily_budget_is_bounded(tmp_path):
    path = tmp_path / 'state.json'
    state = PilotState(path)
    assert state.reserve('1', '8', '10', NOW)
    assert not PilotState(path).reserve('1', '8', '10', NOW)
    for i in range(2, 26):
        assert state.reserve(str(i), '8', '10', NOW)
    assert not state.reserve('26', '8', '10', NOW)
    assert state.reserve('26', '8', '10', NOW + timedelta(days=1))


def test_settings_require_explicit_owner_and_fixed_week():
    assert PilotSettings.from_env({}) is None
    env={'BARMAN_LINK_PILOT_OWNER':'7','BARMAN_LINK_PILOT_START':NOW.isoformat(),
         'BARMAN_LINK_PILOT_UNTIL':(NOW+timedelta(days=7)).isoformat()}
    assert PilotSettings.from_env(env) == SETTINGS
    assert PilotSettings.from_env({**env,'BARMAN_LINK_PILOT_UNTIL':(NOW+timedelta(days=8)).isoformat()}) is None
    assert PilotSettings.from_env({**env,'BARMAN_LINK_PILOT_START':'2026-11-07'}) is None


def test_link_cooldown_and_daily_send_limit(tmp_path):
    state=PilotState(tmp_path/'state.json')
    assert state.reserve('1','8','10',NOW)
    state.finish('1','sent',sent_at=NOW.isoformat())
    assert not state.reserve('2','8','10',NOW+timedelta(minutes=59))
    assert state.reserve('2','8','10',NOW+timedelta(hours=1))
    for i in range(3,12):
        assert state.reserve(str(i),str(i+100),'10',NOW)
        state.finish(str(i),'sent',sent_at=NOW.isoformat())
    assert not state.can_send('999',NOW)


def test_listener_waits_and_skips_if_owner_already_answered(tmp_path,monkeypatch):
    import asyncio
    from barman import link_pilot
    now=datetime.now(timezone.utc)
    calls=[]
    async def no_sleep(seconds): calls.append(('sleep',seconds))
    async def classify(*args):
        calls.append(('classify',))
        return 'Public product release date'
    monkeypatch.setattr(link_pilot.asyncio,'sleep',no_sleep)
    monkeypatch.setattr(link_pilot,'classify',classify)
    listeners=[]
    bot=NS(user=NS(id=99),get_channel=lambda i:NS(guild=NS(id=10)),
           add_listener=lambda fn,event:listeners.append(fn))
    env={'BARMAN_LINK_PILOT_OWNER':'7','BARMAN_SCOPE_CHANNEL':'10',
         'BARMAN_LINK_PILOT_START':(now-timedelta(minutes=1)).isoformat(),
         'BARMAN_LINK_PILOT_UNTIL':(now+timedelta(days=6)).isoformat()}
    message=msg();message.created_at=now;message.reference=None
    async def fetch(mid): return message
    async def history(**kwargs):
        yield NS(author=NS(id=7))
    message.channel=NS(id=10,fetch_message=fetch,history=history)
    link_pilot.install_link_pilot(bot,env,tmp_path)
    link_pilot.install_link_pilot(bot,env,tmp_path)
    assert len(listeners)==1
    asyncio.run(listeners[0](message))
    assert calls==[('sleep',20)]
    assert PilotState(tmp_path/'barman'/'link-pilot.json').entries['100']['status']=='owner_answered_or_stale'


def test_listener_rechecks_owner_response_after_research(tmp_path,monkeypatch):
    import asyncio
    from barman import link_pilot
    now=datetime.now(timezone.utc)
    after=[];calls=[];listeners=[]
    async def no_sleep(seconds): pass
    async def classify(*args): return 'Public product release date'
    async def research(message,query,env,home,**kwargs):
        calls.append(query)
        assert kwargs['link_only'] is True
        after.append(NS(author=NS(id=7)))
        assert not await kwargs['before_send']()
        return None
    monkeypatch.setattr(link_pilot.asyncio,'sleep',no_sleep)
    monkeypatch.setattr(link_pilot,'classify',classify)
    monkeypatch.setattr(link_pilot,'answer_owner',research)
    bot=NS(user=NS(id=99),get_channel=lambda i:NS(guild=NS(id=10)),
           add_listener=lambda fn,event:listeners.append(fn))
    env={'BARMAN_LINK_PILOT_OWNER':'7','BARMAN_SCOPE_CHANNEL':'10',
         'BARMAN_LINK_PILOT_START':(now-timedelta(minutes=1)).isoformat(),
         'BARMAN_LINK_PILOT_UNTIL':(now+timedelta(days=6)).isoformat()}
    message=msg();message.created_at=now;message.reference=None
    async def fetch(mid): return message
    async def history(**kwargs):
        for m in after: yield m
    message.channel=NS(id=10,fetch_message=fetch,history=history)
    link_pilot.install_link_pilot(bot,env,tmp_path)
    asyncio.run(listeners[0](message))
    assert calls==['Public product release date']
    assert PilotState(tmp_path/'barman'/'link-pilot.json').entries['100']['status']=='unverified_or_stale'


def test_listener_cancels_if_referenced_context_was_edited(tmp_path,monkeypatch):
    import asyncio
    from barman import link_pilot
    now=datetime.now(timezone.utc);listeners=[];calls=[]
    async def no_sleep(seconds): pass
    async def classify(*args): calls.append('classify');return 'Public product release date'
    monkeypatch.setattr(link_pilot.asyncio,'sleep',no_sleep)
    monkeypatch.setattr(link_pilot,'classify',classify)
    bot=NS(user=NS(id=99),get_channel=lambda i:NS(guild=NS(id=10)),
           add_listener=lambda fn,event:listeners.append(fn))
    env={'BARMAN_LINK_PILOT_OWNER':'7','BARMAN_SCOPE_CHANNEL':'10',
         'BARMAN_LINK_PILOT_START':(now-timedelta(minutes=1)).isoformat(),
         'BARMAN_LINK_PILOT_UNTIL':(now+timedelta(days=6)).isoformat()}
    message=msg(mentions=());message.created_at=now
    message.reference=NS(channel_id=10,message_id=1,resolved=NS(author=NS(id=7),content='Old context'))
    async def fetch(mid): return message if mid==100 else NS(content='Edited context')
    async def history(**kwargs):
        for m in []: yield m
    message.channel=NS(id=10,fetch_message=fetch,history=history)
    link_pilot.install_link_pilot(bot,env,tmp_path)
    asyncio.run(listeners[0](message))
    assert calls==[]
    assert PilotState(tmp_path/'barman'/'link-pilot.json').entries['100']['status']=='owner_answered_or_stale'
