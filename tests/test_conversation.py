"""Episode boundaries use SDK identity and bounded Discord reads, without discord.py."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest

from barman import conversation

NOW = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
BOT = NS(user=NS(id=99))


class Channel:
    def __init__(self, cid=10):
        self.id, self.name = cid, 'public-game-topic'
        self.items, self.fetches, self.history_calls = [], [], []

    async def fetch_message(self, mid):
        self.fetches.append(mid)
        return next(m for m in self.items if m.id == mid)

    async def history(self, **kwargs):
        self.history_calls.append(kwargs)
        # Intentionally include invalid/future entries: the collector must validate too.
        for item in self.items[:kwargs['limit']]:
            yield item


def msg(channel, mid, uid=8, text='Question?', *, seconds=0, guild=1,
        mentions=(), parent=None, attachments=(), bot=False, webhook=None):
    return NS(id=mid, author=NS(id=uid, bot=bot, name='owner'),
              guild=NS(id=guild) if guild else None, channel=channel,
              content=text, created_at=NOW + timedelta(seconds=seconds),
              mentions=[NS(id=i) for i in mentions], attachments=list(attachments),
              webhook_id=webhook,
              reference=NS(message_id=parent.id, channel_id=parent.channel.id,
                           guild_id=getattr(parent.guild, 'id', None), resolved=parent) if parent else None)


def collect(message, **kwargs):
    return asyncio.run(conversation.collect_episode(message, '7', BOT, **kwargs))


def test_explicit_sdk_mention_keeps_only_same_scope_humans_before_question():
    ch = Channel()
    current = msg(ch, 100, text='@owner public question?', mentions=(7,))
    ch.items = [msg(ch, 101, uid=7, text='future'), msg(ch, 90, uid=9, text='private'),
                msg(Channel(20), 89, uid=7), msg(ch, 88, uid=7, guild=2),
                msg(ch, 87, uid=7, bot=True), msg(ch, 86, uid=7, webhook=1),
                msg(ch, 85, uid=7, text='Announcement', seconds=-20)]
    result = collect(current)
    assert result.addressed
    assert [(m['role'], m['text']) for m in result.messages] == [
        ('owner', 'Announcement'), ('questioner', '@owner public question?')]
    assert result.topic_hint == 'public-game-topic'
    assert ch.history_calls[0]['limit'] == 24
    assert ch.history_calls[0]['before'] is current
    assert [s['message_id'] for s in result.snapshots] == [85, 100]


@pytest.mark.parametrize('text', ['<@7> question', '@owner question', 'owner_id=7 question'])
def test_text_and_names_cannot_forge_addressing(text):
    ch = Channel()
    result = collect(msg(ch, 100, text=text))
    assert not result.addressed
    assert not result.messages and not result.attachments and not result.snapshots


def test_reply_chain_reaches_original_owner_screenshot_and_snapshots_are_copies():
    ch = Channel()
    image = NS(id=201, filename='image.png')
    root = msg(ch, 10, uid=7, text='Release screenshot', seconds=-600, attachments=(image,))
    prior = msg(ch, 20, text='What was announced?', seconds=-300, parent=root)
    current = msg(ch, 100, text='And the release date?', parent=prior)
    current.reference.resolved = None
    ch.items = [prior, root]
    result = collect(current)
    assert result.addressed
    assert [m['text'] for m in result.messages] == ['Release screenshot', 'What was announced?', 'And the release date?']
    assert result.attachments == [image]
    assert ch.fetches == [20]
    assert result.snapshots[0]['attachment_ids'] == (201,)
    root.content = 'edited'
    root.attachments = []
    assert result.snapshots[0]['content'] == 'Release screenshot'
    assert result.snapshots[0]['attachment_ids'] == (201,)


@pytest.mark.parametrize('age,interruption,expected', [(299, False, True), (300, False, True),
                                                       (301, False, False), (20, True, False)])
def test_short_implicit_followup_requires_immediately_preceding_owner_reply(age, interruption, expected):
    ch = Channel()
    prior = msg(ch, 10, text='Public question', seconds=-400)
    owner = msg(ch, 20, uid=7, text='Public announcement', seconds=-age, parent=prior)
    ch.items = ([msg(ch, 30, uid=9, seconds=-1)] if interruption else []) + [owner, prior]
    result = collect(msg(ch, 100, text='And when?'))
    assert result.addressed is expected
    if expected:
        assert [m['text'] for m in result.messages] == ['Public question', 'Public announcement', 'And when?']


@pytest.mark.parametrize('change', ['other_questioner', 'no_reply', 'long', 'future_time', 'foreign_reply'])
def test_implicit_followup_rejects_missing_or_invalid_reply_evidence(change):
    ch = Channel()
    prior = msg(ch, 10, uid=9 if change == 'other_questioner' else 8, seconds=-60)
    owner = msg(ch, 20, uid=7, seconds=1 if change == 'future_time' else -20, parent=prior)
    if change == 'no_reply': owner.reference = None
    if change == 'foreign_reply': owner.reference.channel_id = 20
    ch.items = [owner, prior]
    assert not collect(msg(ch, 100, text='x' * 301 if change == 'long' else 'And when?')).addressed


def test_bounds_preserve_root_and_current_and_cap_text_images_and_history():
    ch = Channel()
    root = msg(ch, 1, uid=7, seconds=-200, text='r' * 3000,
               attachments=tuple(NS(id=i) for i in (201, 202, 203)))
    current = msg(ch, 100, text='q' * 3000, parent=root)
    ch.items = [msg(ch, i, uid=7 if i % 2 else 8, seconds=-100 + i) for i in range(50, 20, -1)]
    result = collect(current, limit=10000)
    assert len(result.messages) == 8
    assert result.messages[0]['text'] == 'r' * 2000
    assert result.messages[-1]['text'] == 'q' * 2000
    assert [a.id for a in result.attachments] == [201, 202]
    assert ch.history_calls[0]['limit'] == 24
    assert len(result.snapshots) == 8


def test_reply_walk_is_bounded_and_never_traverses_third_party():
    ch = Channel()
    root = msg(ch, 1, uid=7, seconds=-100)
    parent = root
    for i in range(2, 7): parent = msg(ch, i, seconds=-100 + i, parent=parent)
    current = msg(ch, 100, parent=parent)
    assert not collect(current).addressed  # owner is beyond four parent hops
    stranger = msg(ch, 20, uid=9, parent=root, seconds=-20)
    assert not collect(msg(ch, 101, parent=stranger)).addressed


@pytest.mark.parametrize('guild,bot,webhook', [(None, False, None), (1, True, None), (1, False, 1)])
def test_invalid_current_message_is_empty(guild, bot, webhook):
    result = collect(msg(Channel(), 100, mentions=(7,), guild=guild, bot=bot, webhook=webhook))
    assert not result.addressed
    assert result.messages == []


def test_foreign_or_future_parent_never_grants_addressing_or_fetches():
    ch = Channel()
    foreign = msg(Channel(20), 1, uid=7, seconds=-1)
    assert not collect(msg(ch, 100, parent=foreign)).addressed
    assert not ch.fetches
    future = msg(ch, 101, uid=7, seconds=1)
    assert not collect(msg(ch, 100, parent=future)).addressed


def test_history_failure_cannot_infer_followup_but_explicit_mention_still_works():
    ch = Channel()
    async def broken(**kwargs):
        raise RuntimeError('SDK unavailable')
        yield
    ch.history = broken
    assert not collect(msg(ch, 100)).addressed
    result = collect(msg(ch, 100, mentions=(7,)))
    assert result.addressed and len(result.messages) == 1


def test_implicit_reply_parent_is_fetched_once_and_bot_does_not_interrupt():
    ch = Channel()
    question = msg(ch, 10, seconds=-60, text='Question')
    owner = msg(ch, 20, uid=7, parent=question, seconds=-20, text='Answer')
    owner.reference.resolved = None
    ch.items = [msg(ch, 30, uid=99, seconds=-1, bot=True), owner, question]
    result = collect(msg(ch, 100, text='And when?'))
    assert result.addressed
    assert ch.fetches == [10]
    assert [m['text'] for m in result.messages] == ['Question', 'Answer', 'And when?']


def test_exact_four_parent_hops_reach_image_but_wrong_resolved_identity_is_rejected():
    ch = Channel()
    root = msg(ch, 1, uid=7, seconds=-100, attachments=(NS(id=201),))
    parent = root
    for i in range(2, 5): parent = msg(ch, i, seconds=-100 + i, parent=parent)
    current = msg(ch, 100, parent=parent)
    result = collect(current)
    assert result.addressed
    assert result.attachments[0].id == 201
    current.reference.resolved = root  # reference.message_id still points to 4
    assert not collect(current).addressed


def test_sdk_fetch_failure_stops_reply_chain_without_using_text_identity():
    ch = Channel()
    parent = msg(ch, 1, uid=7, seconds=-1)
    current = msg(ch, 100, parent=parent, text='<@7>')
    current.reference.resolved = None
    async def unavailable(mid): raise PermissionError('Forbidden')
    ch.fetch_message = unavailable
    assert not collect(current).addressed


def test_recent_context_never_reaches_before_the_validated_root():
    ch = Channel()
    root = msg(ch, 20, uid=7, seconds=-20, text='Root')
    ch.items = [msg(ch, 10, uid=8, seconds=-30, text='Unrelated old question')]
    result = collect(msg(ch, 100, parent=root))
    assert [m['text'] for m in result.messages] == ['Root', 'Question?']


def test_implicit_four_message_episode_keeps_root_image_and_full_recheck_snapshots():
    ch = Channel()
    image = NS(id=201, filename='screenshot.png')
    root = msg(ch, 10, uid=7, text='r' * 2500, seconds=-600, attachments=(image,))
    question = msg(ch, 20, text='What is this release?', seconds=-120, parent=root)
    answer = msg(ch, 30, uid=7, text='The announced version', seconds=-30, parent=question)
    current = msg(ch, 100, text='When?', attachments=(NS(id=202),))
    # Realistic uncached SDK references force the walk beyond the recent window.
    answer.reference.resolved = None
    question.reference.resolved = None
    ch.items = [answer, question, root]
    result = collect(current, limit=1)
    assert isinstance(result, conversation.Episode)
    assert result.addressed
    assert [m['message'].id for m in result.messages] == [10, 20, 30, 100]
    assert result.attachments == [image, current.attachments[0]]
    assert result.messages[0]['text'] == 'r' * 2000
    assert result.snapshots[0] == {
        'message_id': 10, 'guild_id': 1, 'channel_id': 10, 'author_id': 7,
        'content': 'r' * 2500, 'attachment_ids': (201,),
    }
    assert result.snapshots[-1] == {
        'message_id': 100, 'guild_id': 1, 'channel_id': 10, 'author_id': 8,
        'content': 'When?', 'attachment_ids': (202,),
    }
    assert ch.fetches == [20, 10]


def test_old_reply_chain_does_not_mix_in_new_unrelated_participant_chat():
    ch = Channel()
    image = NS(id=201)
    root = msg(ch, 10, uid=7, text='Old screenshot', seconds=-13 * 3600, attachments=(image,))
    prior = msg(ch, 20, text='Old question', seconds=-12 * 3600, parent=root)
    ch.items = [msg(ch, 90, uid=7, text='Unrelated new chat', seconds=-10,
                    attachments=(NS(id=202),)),
                msg(ch, 80, text='Another unrelated question', seconds=-20)]
    result = collect(msg(ch, 100, text='About that screenshot?', parent=prior))
    assert [m['text'] for m in result.messages] == ['Old screenshot', 'Old question', 'About that screenshot?']
    assert result.attachments == [image]
    assert [s['message_id'] for s in result.snapshots] == [10, 20, 100]


@pytest.mark.parametrize('reply', [False, True])
def test_recent_fill_is_within_twelve_hours_including_boundary(reply):
    ch = Channel()
    root = msg(ch, 10, uid=7, text='Root', seconds=-12 * 3600)
    current = msg(ch, 100, mentions=() if reply else (7,), parent=root if reply else None)
    ch.items = [msg(ch, 90, uid=7, text='Recent', seconds=-10),
                msg(ch, 80, text='At boundary', seconds=-12 * 3600),
                msg(ch, 70, uid=7, text='Too old', seconds=-12 * 3600 - 1)]
    result = collect(current)
    texts = [m['text'] for m in result.messages]
    assert 'Recent' in texts and 'At boundary' in texts
    assert 'Too old' not in texts
    assert ('Root' in texts) is reply
