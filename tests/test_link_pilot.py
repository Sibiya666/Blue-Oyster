from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest

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
    async def research(question,context,env,**kwargs):
        calls.append(question)
        after.append(NS(author=NS(id=7)))
        return {'url':'https://example.com/manual','status':'grounded','audit':{}}
    monkeypatch.setattr(link_pilot.asyncio,'sleep',no_sleep)
    monkeypatch.setattr(link_pilot,'classify',classify)
    monkeypatch.setattr(link_pilot,'find_reference',research)
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
    assert calls==['Когда релиз?']
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
    message.reference=NS(channel_id=10,message_id=1,resolved=NS(id=1,created_at=now-timedelta(seconds=30),guild=message.guild,channel=NS(id=10),author=NS(id=7,bot=False),webhook_id=None,attachments=[],reference=None,content='Old context'))
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


# Synthetic SDK boundary shared by the cancellation/queue regressions below.
def pilot_runtime(tmp_path):
    now = datetime.now(timezone.utc)
    guild = NS(id=10, members=[])
    channel = NS(id=20, name='topic')
    messages, after, listeners = {}, [], []

    def make(mid, uid=8, *, guild_id=10, mentions=(7,), parent=None, text='Public question?'):
        message = NS(id=mid, guild=guild if guild_id == 10 else NS(id=guild_id, members=[]),
                     channel=channel, author=NS(id=uid, bot=False, name=f'Participant{uid}'),
                     content=text, created_at=now, mentions=[NS(id=i) for i in mentions],
                     attachments=[], webhook_id=None,
                     reference=NS(message_id=parent.id, channel_id=channel.id, guild_id=10,
                                  resolved=parent) if parent else None)
        messages[mid] = message
        return message

    async def fetch(mid): return messages[mid]
    async def history(**kwargs):
        source = after if 'after' in kwargs else sorted(messages.values(), key=lambda m: m.id, reverse=True)
        for item in source:
            if 'before' not in kwargs or item.id < kwargs['before'].id:
                yield item
    channel.fetch_message, channel.history = fetch, history
    bot = NS(user=NS(id=99), get_channel=lambda _: NS(guild=guild),
             add_listener=lambda fn, _: listeners.append(fn))
    env = {'BARMAN_LINK_PILOT_OWNER': '7', 'BARMAN_SCOPE_CHANNEL': '20',
           'BARMAN_LINK_PILOT_START': (now-timedelta(minutes=1)).isoformat(),
           'BARMAN_LINK_PILOT_UNTIL': (now+timedelta(days=1)).isoformat()}
    (tmp_path / 'SOUL.md').write_text('')
    return NS(make=make, messages=messages, after=after, listeners=listeners, bot=bot, env=env)


def test_context_withdrawn_during_image_processing_never_reaches_research(tmp_path, monkeypatch):
    import asyncio
    from barman import link_pilot
    runtime = pilot_runtime(tmp_path)
    root = runtime.make(10, uid=7, text='Original context')
    root.attachments = [NS(id=201)]
    message = runtime.make(100, parent=root)
    research_calls = []

    async def no_sleep(_): pass
    async def images(*args):
        root.content = 'Context withdrawn during OCR'
        return [{'image_url': 'sanitized'}]
    async def research(*args, **kwargs):
        research_calls.append(True)
        return {'url': None, 'status': 'skip', 'audit': {}}
    monkeypatch.setattr(link_pilot.asyncio, 'sleep', no_sleep)
    monkeypatch.setattr(link_pilot, 'prepare_images', images)
    monkeypatch.setattr(link_pilot, 'find_reference', research)
    link_pilot.install_link_pilot(runtime.bot, runtime.env, tmp_path)
    asyncio.run(runtime.listeners[0](message))
    assert research_calls == []
    assert PilotState(tmp_path/'barman/link-pilot.json').entries['100']['status'] == 'owner_answered_or_stale'


def test_research_receives_live_cancellation_callback(tmp_path, monkeypatch):
    import asyncio
    from barman import link_pilot
    runtime = pilot_runtime(tmp_path)
    message = runtime.make(100)
    checks = []
    async def no_sleep(_): pass
    async def research(*args, before_request, **kwargs):
        checks.append(await before_request())
        runtime.after.append(NS(author=NS(id=7)))
        checks.append(await before_request())
        return {'url': None, 'status': 'cancelled', 'audit': {}}
    monkeypatch.setattr(link_pilot.asyncio, 'sleep', no_sleep)
    monkeypatch.setattr(link_pilot, 'find_reference', research)
    link_pilot.install_link_pilot(runtime.bot, runtime.env, tmp_path)
    asyncio.run(runtime.listeners[0](message))
    assert checks == [True, False]
    assert PilotState(tmp_path/'barman/link-pilot.json').entries['100']['status'] == 'unverified_or_stale'


@pytest.mark.parametrize('invalid_kind', ['foreign_guild', 'bot_mention', 'command', 'stale', 'short'])
def test_ineligible_events_cannot_occupy_queue_slots(tmp_path, monkeypatch, invalid_kind):
    import asyncio
    from barman import link_pilot
    runtime = pilot_runtime(tmp_path)
    real_sleep = asyncio.sleep
    async def research(*args, **kwargs): return {'url': None, 'status': 'skip', 'audit': {}}
    monkeypatch.setattr(link_pilot, 'find_reference', research)

    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        async def paused(seconds):
            assert seconds == 20
            entered.set()
            await release.wait()
        monkeypatch.setattr(link_pilot.asyncio, 'sleep', paused)
        link_pilot.install_link_pilot(runtime.bot, runtime.env, tmp_path)
        listener = runtime.listeners[0]
        first = asyncio.create_task(listener(runtime.make(100)))
        await entered.wait()
        ineligible = [runtime.make(mid, guild_id=11 if invalid_kind == 'foreign_guild' else 10)
                      for mid in (101, 102)]
        for item in ineligible:
            if invalid_kind == 'bot_mention': item.mentions.append(NS(id=99))
            if invalid_kind == 'command': item.content = '/command'
            if invalid_kind == 'stale': item.created_at -= timedelta(days=2)
            if invalid_kind == 'short': item.content = '?'
        invalid = [asyncio.create_task(listener(item)) for item in ineligible]
        await real_sleep(0)
        valid = asyncio.create_task(listener(runtime.make(103)))
        await real_sleep(0)
        release.set()
        await asyncio.gather(first, *invalid, valid)
    asyncio.run(run())
    entries = PilotState(tmp_path/'barman/link-pilot.json').entries
    assert set(entries) == {'100', '103'}
    assert all(entry['status'] == 'unverified_or_stale' for entry in entries.values())


def test_owner_reply_updates_fast_followup_cache_without_queue_admission(tmp_path, monkeypatch):
    import asyncio
    from barman import link_pilot
    runtime = pilot_runtime(tmp_path)
    prior = runtime.make(10, mentions=(), text='Prior public question')
    owner = runtime.make(20, uid=7, mentions=(), parent=prior, text='Public answer')
    current = runtime.make(100, mentions=(), text='And when?')
    researched = []
    async def no_sleep(_): pass
    async def research(question, *args, **kwargs):
        researched.append(question)
        return {'url': None, 'status': 'skip', 'audit': {}}
    monkeypatch.setattr(link_pilot.asyncio, 'sleep', no_sleep)
    monkeypatch.setattr(link_pilot, 'find_reference', research)
    link_pilot.install_link_pilot(runtime.bot, runtime.env, tmp_path)
    async def run():
        for message in (prior, owner, current): await runtime.listeners[0](message)
    asyncio.run(run())
    assert researched == ['And when?']
    assert set(PilotState(tmp_path/'barman/link-pilot.json').entries) == {'100'}


@pytest.mark.parametrize('mode', [None, 'log', 'invalid'])
def test_observation_mode_records_exact_candidate_without_discord_send(tmp_path, monkeypatch, mode):
    import asyncio
    from barman import link_pilot
    runtime = pilot_runtime(tmp_path)
    if mode is not None: runtime.env['BARMAN_LINK_PILOT_MODE'] = mode
    message = runtime.make(100, text='Private original question')
    async def no_sleep(_): pass
    async def forbidden_send(*args, **kwargs): pytest.fail('observation mode must never send')
    async def research(*args, **kwargs):
        return {'status':'grounded','url':'https://example.com/manual','verdict':'yes','audit':{}}
    import sys
    monkeypatch.setitem(sys.modules, 'discord', NS(AllowedMentions=NS(none=lambda:None)))
    message.reply = forbidden_send
    monkeypatch.setattr(link_pilot.asyncio, 'sleep', no_sleep)
    monkeypatch.setattr(link_pilot, 'find_reference', research)
    link_pilot.install_link_pilot(runtime.bot, runtime.env, tmp_path)
    asyncio.run(runtime.listeners[0](message))
    entry = PilotState(tmp_path/'barman/link-pilot.json').entries['100']
    assert entry['status'] == 'logged'
    assert entry['candidate_reply'] == 'Да. <https://example.com/manual>'
    assert 'reply_message_id' not in entry
    assert 'Private original question' not in repr(entry)


def test_logged_candidates_keep_the_same_cooldown_and_daily_limit(tmp_path):
    now = datetime.now(timezone.utc)
    state = PilotState(tmp_path/'pilot.json')
    assert state.reserve('1', '8', '20', now)
    state.finish('1', 'logged', decided_at=now.isoformat(), candidate_reply='Да. <https://example.com/manual>')
    assert not state.can_send('8', now+timedelta(minutes=20))
    assert state.can_send('8', now+timedelta(hours=1))
    for i in range(2, 11):
        assert state.reserve(str(i), str(i+10), '20', now)
        state.finish(str(i), 'logged', decided_at=now.isoformat())
    assert not state.can_send('fresh_user', now)


def test_only_explicit_post_mode_sends_and_records_delivery(tmp_path, monkeypatch):
    import asyncio,sys
    from barman import link_pilot
    runtime = pilot_runtime(tmp_path)
    runtime.env['BARMAN_LINK_PILOT_MODE'] = 'post'
    message = runtime.make(100)
    sent=[]
    async def no_sleep(_): pass
    async def reply(content, **kwargs): sent.append(content);return NS(id=123)
    async def research(*args, **kwargs):
        return {'status':'grounded','url':'https://example.com/manual','verdict':'no','audit':{}}
    message.reply=reply
    monkeypatch.setitem(sys.modules,'discord',NS(AllowedMentions=NS(none=lambda:None)))
    monkeypatch.setattr(link_pilot.asyncio,'sleep',no_sleep)
    monkeypatch.setattr(link_pilot,'find_reference',research)
    link_pilot.install_link_pilot(runtime.bot,runtime.env,tmp_path)
    asyncio.run(runtime.listeners[0](message))
    assert sent==['Нет. <https://example.com/manual>']
    entry=PilotState(tmp_path/'barman/link-pilot.json').entries['100']
    assert entry['status']=='sent' and entry['reply_message_id']=='123'
