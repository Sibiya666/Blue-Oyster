"""Short-lived per-user topics, not transcript/history or tool permissions."""
from collections import OrderedDict
from dataclasses import dataclass
import re
import time

from .search_policy import search_policy

FOLLOWUP_WORDS = frozenset("а и но ну так таки что там это этой этот он она оно его ее когда же то все ок ладно наконец скажи пожалуйста во сколько выйдет выходит выходить релиз релиза полный полная новая новую новый следующая следующую лигу лига лиги обновление обновления патч патча дата даты старт старта будет уже еще тогда ранний доступ первой вторую первую второй 1 2 1.0 один два".split())


@dataclass(frozen=True)
class TopicInput:
    text: str
    game_hint: str | None = None


class TopicMemory:
    def __init__(self, *, ttl=900, capacity=128):
        self.ttl, self.capacity = ttl, capacity
        self._topics = OrderedDict()

    def resolve(self, key, text: str, *, now=None) -> TopicInput:
        now = time.monotonic() if now is None else now
        previous = self._topics.pop(key, None)
        if previous and now - previous[2] >= self.ttl:
            previous = None
        explicit = search_policy(text)
        hint = None
        effective = text
        if explicit.game is None:
            words = re.findall(r"[\w.]+", text.lower().replace("ё", "е").strip(" .!?"))
            if previous and words and all(w in FOLLOWUP_WORDS for w in words):
                hint = previous[0]
                if previous[1]:
                    selection = " ".join(words)
                    if re.fullmatch(r"полный(?:\s+релиз)?|релиз", selection):
                        effective = "Когда полный релиз?"
                    elif re.fullmatch(r"(?:(?:новая|новую|следующая|следующую)\s+)?лиг[ау]", selection):
                        effective = "Когда новая лига?"
                    elif selection in ("обновление", "патч", "новый патч"):
                        effective = "Когда обновление?"
            else:
                return TopicInput(text)  # unknown/new topic clears the previous hint
        policy = search_policy(effective, game_hint=hint)
        if policy.game:
            self._topics[key] = (policy.game, bool(policy.clarification), now)
            while len(self._topics) > self.capacity:
                self._topics.popitem(last=False)
        return TopicInput(effective, hint)
