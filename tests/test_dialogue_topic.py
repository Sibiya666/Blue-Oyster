from barman.dialogue import TopicMemory
from barman.search_policy import search_policy


def test_followup_keeps_only_own_topic_not_conversation_text():
    memory = TopicMemory()
    key = (1, 2, 3)
    memory.resolve(key, "таки что там по поешечке", now=0)
    resolved = memory.resolve(key, "а релиз когда?", now=10)
    assert resolved.game_hint == "Path of Exile 2"
    assert resolved.text == "а релиз когда?"
    assert search_policy(resolved.text, game_hint=resolved.game_hint).requires_evidence
    assert memory.resolve((1, 2, 4), "а релиз когда?", now=11).game_hint is None
    assert memory.resolve((1, 5, 3), "а релиз когда?", now=11).game_hint is None
    assert search_policy("а релиз когда?").clarification == "Релиз какой игры?"


def test_context_expires_and_is_bounded():
    memory = TopicMemory(ttl=60, capacity=2)
    memory.resolve((1, 1, 1), "PoE 2", now=0)
    assert memory.resolve((1, 1, 1), "а релиз когда?", now=61).game_hint is None
    for i in range(3):
        memory.resolve((1, 1, i), "PoE 2", now=100)
    assert memory.resolve((1, 1, 0), "а релиз когда?", now=101).game_hint is None


def test_explicit_new_game_and_unknown_topic_do_not_inherit_poe():
    memory = TopicMemory()
    key = (1, 2, 3)
    memory.resolve(key, "PoE 2", now=0)
    memory.resolve(key, "Когда новый патч Diablo IV?", now=1)
    assert memory.resolve(key, "а релиз когда?", now=2).game_hint == "Diablo IV"
    memory.resolve(key, "А когда GTA 6?", now=3)
    assert memory.resolve(key, "а релиз когда?", now=4).game_hint is None


def test_event_clarification_can_be_answered_without_retyping_game():
    memory = TopicMemory()
    key = (1, 2, 3)
    memory.resolve(key, "Когда поешечка выходит?", now=0)
    resolved = memory.resolve(key, "полный релиз", now=1)
    assert resolved.text == "Когда полный релиз?"
    assert resolved.game_hint == "Path of Exile 2"
    memory.resolve(key, "Когда поешечка выходит?", now=2)
    assert memory.resolve(key, "полный", now=3).text == "Когда полный релиз?"
    memory.resolve(key, "Когда поешечка выходит?", now=4)
    assert memory.resolve(key, "новую лигу", now=5).text == "Когда новая лига?"
