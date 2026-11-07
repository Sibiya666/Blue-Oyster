import asyncio
from datetime import datetime,timedelta,timezone
import json
import sys
from types import SimpleNamespace as NS

import pytest

import barman
from barman.comments import CommentSettings


@pytest.fixture
def runtime(tmp_path,monkeypatch):
    state=NS(sent=[],requests=[],expired=False,expire_during_response=False,finish='stop')
    owner=NS(id=1,bot=False,name='OwnerPrivate',display_name='OwnerPrivate',global_name=None)
    author=NS(id=2,bot=False,name='FidelPrivate',display_name='FidelPrivate',global_name=None)
    guild=NS(members=[owner,author])
    async def history(**kwargs):
        yield NS(author=owner,content='FidelPrivate, это просто шутка')
    async def reply(text,**kwargs):state.sent.append(text)
    message=NS(id=100,guild=guild,author=author,content='OwnerPrivate, поддержи шутку',
               webhook_id=None,channel=NS(id=30,history=history),reply=reply)
    env={'BARMAN_COMMENT_USERS':'2','BARMAN_COMMENT_CHANNELS':'30','BARMAN_COMMENT_OWNER':'1',
         'BARMAN_COMMENT_UNTIL':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),
         'OPENROUTER_API_KEY':'synthetic-api-key-long-enough'}
    (tmp_path/'SOUL.md').write_text('Friendly persona')
    class Response:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        def raise_for_status(self):pass
        async def json(self):
            if state.expire_during_response:state.expired=True
            return {'choices':[{'finish_reason':state.finish,'message':{'content':'Одна фраза. Вторая. Лишняя третья.'}}]}
    class Session:
        def __init__(self,*args,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        def post(self,url,**kwargs):state.requests.append(kwargs);return Response()
    monkeypatch.setitem(sys.modules,'aiohttp',NS(ClientSession=Session,ClientTimeout=lambda **kwargs:None))
    active=CommentSettings.active_at
    monkeypatch.setattr(CommentSettings,'active_at',lambda self,now:not state.expired and active(self,now))
    discord=NS(AllowedMentions=NS(none=lambda:None))
    state.message=message
    state.run=lambda:asyncio.run(barman._comment(NS(user=NS(id=3,name='BotPrivate',display_name='Бармен',global_name=None)),env,tmp_path,discord,message))
    state.env=env
    return state


def test_comment_context_is_anonymized_and_reply_is_at_most_two_sentences(runtime):
    runtime.run()
    payload=json.dumps(runtime.requests[0]['json'],ensure_ascii=False)
    assert 'OwnerPrivate' not in payload and 'FidelPrivate' not in payload
    assert runtime.sent==['Одна фраза. Вторая.']


def test_comment_permission_expiring_during_generation_prevents_send(runtime):
    runtime.expire_during_response=True
    runtime.run()
    assert len(runtime.requests)==1 and runtime.sent==[]


def test_expired_comment_permission_does_not_call_model(runtime):
    runtime.env['BARMAN_COMMENT_UNTIL']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    runtime.run()
    assert runtime.requests==[] and runtime.sent==[]


def test_truncated_comment_response_is_not_posted(runtime):
    runtime.finish='length'
    runtime.run()
    assert runtime.sent==[]


def test_anonymization_preserves_an_implicit_address_to_the_bot(runtime):
    runtime.message.content="BotPrivate, что скажешь?"
    runtime.run()
    payload=json.dumps(runtime.requests[0]["json"],ensure_ascii=False)
    assert "BotPrivate" not in payload
    assert "Бармен, что скажешь?" in payload
