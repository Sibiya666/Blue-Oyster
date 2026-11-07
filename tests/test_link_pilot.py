from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

from barman.link_pilot import PilotSettings, PilotState, eligible, parse_decision, anonymize

NOW = datetime(2026, 11, 7, tzinfo=timezone.utc)
SETTINGS = PilotSettings('7', NOW, NOW + timedelta(days=7))


def test_anonymization_happens_locally_before_external_classification():
    text='Sibiya <@123456789012345678> mail@example.com +7 (999) 123-45-67 https://private.example/secret /Users/alex/key known-secret-token-123 Когда релиз PoE 2?'
    clean=anonymize(text, {'OPENROUTER_API_KEY':'known-secret-token-123'}, names=['Sibiya'])
    assert 'Когда релиз PoE 2?' in clean
    assert all(s not in clean for s in ('Sibiya','123456789012345678','mail@example.com','999','private.example','/Users/alex','known-secret-token'))


def test_anonymization_masks_short_known_names_and_non_http_links():
    clean=anonymize('Jo www.example.com/account /tmp/private.data',{},names=['Jo'])
    assert all(value not in clean for value in ('Jo','example.com','/tmp/'))


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
    assert parse_decision('{"scope":"public_fact","answerable":true,"confidence":"high","query":"Product release date"}') == 'Product release date'
    for text in ('{}', 'not json', '{"answerable":true,"confidence":"low","query":"anything"}',
                 '{"answerable":false,"confidence":"high","query":"anything"}',
                 '{"answerable":true,"confidence":"high","query":"<@7> private"}'):
        assert parse_decision(text) is None


def test_owner_specific_question_cannot_be_replaced_by_public_pricing_query():
    assert parse_decision('{"scope":"owner_specific","answerable":true,"confidence":"high","query":"Product subscription pricing"}') is None


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
    async def classify(*args,**kwargs):
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
    message=msg();message.guild.members=[];message.created_at=now;message.reference=None
    async def fetch(mid): return message
    async def history(**kwargs):
        yield NS(author=NS(id=7))
    (tmp_path/'SOUL.md').write_text('Персона')
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
    async def classify(*args,**kwargs): return 'Public product release date'
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
    message=msg();message.guild.members=[];message.created_at=now;message.reference=None
    async def fetch(mid): return message
    async def history(**kwargs):
        for m in after: yield m
    (tmp_path/'SOUL.md').write_text('Персона')
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
    async def classify(*args,**kwargs): calls.append('classify');return 'Public product release date'
    monkeypatch.setattr(link_pilot.asyncio,'sleep',no_sleep)
    monkeypatch.setattr(link_pilot,'classify',classify)
    bot=NS(user=NS(id=99),get_channel=lambda i:NS(guild=NS(id=10)),
           add_listener=lambda fn,event:listeners.append(fn))
    env={'BARMAN_LINK_PILOT_OWNER':'7','BARMAN_SCOPE_CHANNEL':'10',
         'BARMAN_LINK_PILOT_START':(now-timedelta(minutes=1)).isoformat(),
         'BARMAN_LINK_PILOT_UNTIL':(now+timedelta(days=6)).isoformat()}
    message=msg(mentions=());message.guild.members=[];message.created_at=now
    message.reference=NS(channel_id=10,message_id=1,resolved=NS(id=1,created_at=now-timedelta(seconds=30),channel=NS(id=10),author=NS(id=7),content='Old context'))
    async def fetch(mid): return message if mid==100 else NS(content='Edited context')
    async def history(**kwargs):
        for m in []: yield m
    (tmp_path/'SOUL.md').write_text('Персона')
    message.channel=NS(id=10,fetch_message=fetch,history=history)
    link_pilot.install_link_pilot(bot,env,tmp_path)
    asyncio.run(listeners[0](message))
    assert calls==[]
    assert PilotState(tmp_path/'barman'/'link-pilot.json').entries['100']['status']=='owner_answered_or_stale'


def test_episode_keeps_related_owner_messages_but_not_other_people_or_channels():
    from barman.link_pilot import episode_context
    channel=NS(id=10)
    parent=NS(id=1,created_at=NOW,channel=channel,author=NS(id=7),content='Announcement')
    target=NS(id=9,created_at=NOW+timedelta(hours=2),channel=channel)
    valid=NS(id=2,created_at=NOW+timedelta(minutes=10),channel=channel,author=NS(id=7),content='Release features')
    other=NS(id=3,created_at=NOW+timedelta(minutes=20),channel=channel,author=NS(id=8),content='Private conversation')
    foreign=NS(id=4,created_at=NOW+timedelta(minutes=30),channel=NS(id=20),author=NS(id=7),content='Other channel')
    assert episode_context(parent,[foreign,other,valid], '7',target)==[parent,valid]


def test_long_root_cannot_push_recent_clarifications_out_of_context():
    from barman.link_pilot import anonymized_context
    packed=anonymized_context(['Old announcement '+('x'*5000), 'Clarified product and release'],{})
    assert len(packed)<2000
    assert 'Old announcement' in packed
    assert 'Clarified product and release' in packed
