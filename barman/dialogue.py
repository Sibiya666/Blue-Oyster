"""Bounded private dialogue per SDK guild/channel/author. No channel backfill or source pages."""
from collections import OrderedDict
import time


class DialogueMemory:
    def __init__(self, *, ttl=900, capacity=128, turns=4):
        self.ttl, self.capacity, self.turns = ttl, capacity, turns
        self._dialogs = OrderedDict()

    def history(self, key, *, now=None):
        now = time.monotonic() if now is None else now
        entry = self._dialogs.get(key)
        if entry is None:
            return []
        if now - entry[1] >= self.ttl:
            del self._dialogs[key]
            return []
        return [dict(message) for message in entry[0]]

    def remember(self, key, question: str, answer: str, *, now=None):
        now = time.monotonic() if now is None else now
        messages = self.history(key, now=now)
        messages.extend(({"role": "user", "content": question[:2000]},
                         {"role": "assistant", "content": answer[:500]}))
        self._dialogs.pop(key, None)
        self._dialogs[key] = (messages[-self.turns * 2:], now)
        while len(self._dialogs) > self.capacity:
            self._dialogs.popitem(last=False)
