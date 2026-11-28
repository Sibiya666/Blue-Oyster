import asyncio
from datetime import datetime,timezone
from types import SimpleNamespace as NS

import pytest
import sys


@pytest.fixture(autouse=True)
def discord_stub(monkeypatch):
    monkeypatch.setitem(sys.modules,"discord",NS(AllowedMentions=NS(none=lambda:None)))


def runtime(tmp_path,*,source=20,target_guild=10,text='<@99> привет',uid=8):
    sent=[];listeners={};calls=[]
    guild=NS(id=10,members=[])
    async def send(text,**kwargs):sent.append((30,text));return NS(id=500)
    target=NS(id=30,guild=NS(id=target_guild),send=send)
    async def forbidden(*args,**kwargs):pytest.fail('response leaked to original channel')
    msg=NS(id=100,author=NS(id=uid,bot=False,name='Person'),guild=guild,
           content=text,mentions=[NS(id=99)] if '<@99>' in text else [],
           attachments=[],webhook_id=None,reference=None,created_at=datetime.now(timezone.utc))
    async def fetch(mid):return msg
    msg.channel=NS(id=source,guild=guild,send=forbidden,fetch_message=fetch);msg.reply=forbidden
    bot=NS(user=NS(id=99,name='Бармен'),get_channel=lambda cid:target if cid==30 else NS(guild=guild),
        add_listener=lambda fn,event:listeners.setdefault(event,fn))
    async def generate(text,history,soul,env):calls.append((text,history));return 'Привет. Что наливаем?'
    env={'BARMAN_SCOPE_CHANNEL':'50','BARMAN_CHAT_ROUTES':'{"8":"30"}'}
    (tmp_path/'SOUL.md').write_text('Персона')
    from barman.routed_chat import install_routed_chat
    install_routed_chat(bot,env,tmp_path,generate=generate)
    return NS(message=msg,listeners=listeners,sent=sent,calls=calls)


@pytest.mark.parametrize('source',[20,30,40])
def test_address_from_any_channel_is_sent_only_to_destination(tmp_path,source):
    r=runtime(tmp_path,source=source)
    asyncio.run(r.listeners['on_message'](r.message))
    assert r.sent==[(30,'Привет. Что наливаем?')]


@pytest.mark.parametrize('kind',['other_user','bot','webhook','other_guild','not_addressed','command'])
def test_routing_rejects_ineligible_events(tmp_path,kind):
    r=runtime(tmp_path)
    if kind=='other_user':r.message.author.id=9
    elif kind=='bot':r.message.author.bot=True
    elif kind=='webhook':r.message.webhook_id=123
    elif kind=='other_guild':r.message.guild=NS(id=11)
    elif kind=='not_addressed':r.message.content='чужая беседа';r.message.mentions=[]
    else:r.message.content='<@99> /restart'
    asyncio.run(r.listeners['on_message'](r.message))
    assert r.sent==[] and r.calls==[]


def test_foreign_destination_fails_closed(tmp_path):
    r=runtime(tmp_path,target_guild=11)
    asyncio.run(r.listeners['on_message'](r.message))
    assert not r.sent and not r.calls


def test_name_address_and_reply_are_accepted(tmp_path):
    r=runtime(tmp_path,text='Бармен, привет')
    async def run():
        await r.listeners['on_message'](r.message)
        r.message.id=101;r.message.content='Как дела?'
        r.message.reference=NS(channel_id=20,message_id=50,resolved=NS(id=50,author=NS(id=99)))
        await r.listeners['on_message'](r.message)
    asyncio.run(run())
    assert len(r.sent)==2 and len(r.calls[1][1])==2


def test_gateway_never_handles_routed_user_in_original_channel(tmp_path):
    from barman.chat import install_chat_hooks
    hooks={};ctx=NS(register_hook=lambda name,fn:hooks.update({name:fn}))
    bot=NS(user=NS(id=99),get_channel=lambda cid:NS(guild=NS(id=10)))
    install_chat_hooks(ctx,{'BARMAN_SCOPE_CHANNEL':'50','BARMAN_CHAT_ROUTES':'{"8":"30"}'},tmp_path,lambda:bot)
    msg=NS(author=NS(id=8),guild=NS(id=10),mentions=[NS(id=99)])
    result=asyncio.run(hooks['pre_gateway_dispatch'](event=NS(source=NS(platform=NS(value='discord')),raw_message=msg)))
    assert result['action']=='skip'


@pytest.mark.parametrize('raw',['{','[]','{"8":"*"}','{"8":"0"}','{"8":["30"]}'])
def test_bad_routes_cannot_grant_access(raw):
    from barman.routed_chat import parse_routes
    assert parse_routes(raw) is None


def test_deleted_or_edited_source_does_not_publish(tmp_path):
    r=runtime(tmp_path)
    async def deleted(mid):raise LookupError('deleted')
    r.message.channel.fetch_message=deleted
    asyncio.run(r.listeners['on_message'](r.message))
    assert r.sent==[]


def test_model_gets_anonymized_own_dialogue_not_channel_history(tmp_path):
    r=runtime(tmp_path,text='<@99> Person mail@example.com привет')
    asyncio.run(r.listeners['on_message'](r.message))
    assert 'Person' not in r.calls[0][0] and 'mail@example.com' not in r.calls[0][0]
    assert r.calls[0][1]==[]
