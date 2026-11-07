"""Bounded, SDK-authenticated conversation episodes for the owner link pilot.

No permissions are granted here. Callers must authorize the incoming message first
and re-fetch snapshots before sending anything derived from an episode.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


@dataclass
class Episode:
    """Messages are chronological {role, text, message} records; message is the SDK object.

    Roles are ``owner`` and ``questioner`` (never model/system roles). Snapshots
    retain full original content and attachment IDs, even when prompt text is cut.
    ``topic_hint`` is untrusted channel-name data, never authorization evidence.
    """

    messages: list[dict[str, Any]] = field(default_factory=list)
    attachments: list[Any] = field(default_factory=list)
    snapshots: list[dict[str, Any]] = field(default_factory=list)
    addressed: bool = False
    topic_hint: str = ''


def _id(value) -> int | None:
    value = getattr(value, 'id', None)
    return value if type(value) is int and value > 0 else None


def _human(message) -> bool:
    author = getattr(message, 'author', None)
    return bool(_id(author) and not getattr(author, 'bot', True)
                and not getattr(message, 'webhook_id', None))


def _same_scope(candidate, current) -> bool:
    return bool(_id(candidate) and _human(candidate)
                and _id(getattr(candidate, 'guild', None)) == _id(current.guild)
                and _id(getattr(candidate, 'channel', None)) == _id(current.channel))


def _prior(candidate, current) -> bool:
    if not _same_scope(candidate, current) or candidate.id >= current.id:
        return False
    earlier, later = getattr(candidate, 'created_at', None), getattr(current, 'created_at', None)
    if not isinstance(earlier, datetime) or not isinstance(later, datetime):
        return False
    try:
        return earlier <= later
    except TypeError:  # Naive/aware timestamps cannot establish chronology.
        return False


async def _parent(message, current):
    reference = getattr(message, 'reference', None)
    if reference is None or getattr(reference, 'channel_id', None) != current.channel.id:
        return None
    if getattr(reference, 'guild_id', None) not in (None, current.guild.id):
        return None
    mid = getattr(reference, 'message_id', None)
    if type(mid) is not int or mid <= 0 or mid >= message.id:
        return None
    parent = getattr(reference, 'resolved', None)
    if parent is None:
        try:
            parent = await current.channel.fetch_message(mid)
        except Exception:  # Deleted, forbidden, missing SDK method, or transport failure.
            return None
    if _id(parent) != mid or not _prior(parent, message) or not _prior(parent, current):
        return None
    return parent


async def _chain(message, current, participants, *, start=None):
    chain = list(start or ())
    cursor = chain[-1] if chain else message
    for _ in range(4 - len(chain)):
        parent = await _parent(cursor, current)
        if parent is None or _id(parent.author) not in participants:
            break
        chain.append(parent)
        cursor = parent
    return chain


async def _recent(message, limit):
    result = []
    if not limit:
        return result
    try:
        async for item in message.channel.history(limit=limit, before=message, oldest_first=False):
            result.append(item)
            if len(result) >= limit:  # Bound iteration even for an imperfect SDK wrapper.
                break
    except Exception:
        # A partial read cannot prove that there was no human interruption.
        return []
    return sorted((m for m in result if _prior(m, message)), key=lambda m: m.id, reverse=True)


async def collect_episode(message, owner_id: str, bot, *, limit=24) -> Episode:
    """Collect at most 8 messages / 2 SDK attachments, without fetching media.

    Read up to min(limit, 24) prior channel messages and at most four reply
    ancestors. Implicit addressing requires a nonempty <=300-character follow-up
    immediately after the owner's SDK reply to this questioner, within 5 minutes.
    Bot/webhook traffic does not count as a human interruption. Failed SDK reads
    never establish implicit addressing. No channel names or message text confer
    identity. Recent context is limited to 12 hours; older reply roots keep
    only their validated chain and the current message. Rejected episodes carry
    no conversation data.
    """
    empty = Episode()
    if (not isinstance(owner_id, str) or not owner_id.isascii() or not owner_id.isdecimal()
            or int(owner_id) <= 0 or not _human(message) or not _id(message)
            or not _id(getattr(message, 'guild', None)) or not _id(getattr(message, 'channel', None))
            or _id(message.author) == _id(getattr(bot, 'user', None))):
        return empty
    owner = int(owner_id)
    questioner = message.author.id
    participants = {owner, questioner}
    limit = max(0, min(24, int(limit)))
    recent = await _recent(message, limit)
    chain = await _chain(message, message, participants)
    addressed = (any(_id(user) == owner for user in getattr(message, 'mentions', ()))
                 or any(m.author.id == owner for m in chain))
    text = getattr(message, 'content', '') or ''
    if not addressed and getattr(message, 'reference', None) is None and 0 < len(text.strip()) <= 300:
        previous = recent[0] if recent else None
        if previous is not None and previous.author.id == owner:
            age = (message.created_at - previous.created_at).total_seconds()
            if 0 <= age <= 300:
                parent = await _parent(previous, message)
                if parent is not None and parent.author.id == questioner:
                    addressed = True
                    chain = await _chain(previous, message, participants, start=(previous, parent))
    if not addressed:
        return empty

    # Keep all validated ancestors (especially an older screenshot root), then
    # fill remaining slots only for a current episode, within its 12-hour window.
    selected = {m.id: m for m in chain}
    selected[message.id] = message
    root_id = min(selected)
    window = timedelta(hours=12)
    old_root = bool(chain and message.created_at - selected[root_id].created_at > window)
    for item in (() if old_root else recent):
        if len(selected) >= 8:
            break
        if (item.author.id in participants and (not chain or item.id >= root_id)
                and message.created_at - item.created_at <= window):
            selected.setdefault(item.id, item)
    result = Episode(addressed=True, topic_hint=str(getattr(message.channel, 'name', '') or '')[:200])
    seen_attachments = set()
    for item in sorted(selected.values(), key=lambda m: m.id):
        content = getattr(item, 'content', '') or ''
        attachments = list(getattr(item, 'attachments', ()) or ())
        result.messages.append({'role': 'owner' if item.author.id == owner else 'questioner',
                                'text': content[:2000], 'message': item})
        result.snapshots.append({'message_id': item.id, 'guild_id': item.guild.id,
                                 'channel_id': item.channel.id, 'author_id': item.author.id,
                                 'content': content,
                                 'attachment_ids': tuple(a.id for a in attachments)})
        for attachment in attachments:
            if len(result.attachments) < 2 and attachment.id not in seen_attachments:
                result.attachments.append(attachment)
                seen_attachments.add(attachment.id)
    return result
