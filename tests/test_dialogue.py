from barman.dialogue import DialogueMemory


def test_private_history_is_universal_and_isolated_by_user_channel_and_guild():
    memory = DialogueMemory()
    key = (1, 2, 3)
    memory.remember(key, "Какая версия редактора?", "Версия 4.", now=0)
    assert memory.history(key, now=1) == [{"role": "user", "content": "Какая версия редактора?"},
                                          {"role": "assistant", "content": "Версия 4."}]
    assert memory.history((1, 2, 4), now=1) == []
    assert memory.history((1, 5, 3), now=1) == []
    assert memory.history((6, 2, 3), now=1) == []


def test_history_expires_and_has_bounded_turns_and_capacity():
    memory = DialogueMemory(ttl=60, capacity=2, turns=2)
    memory.remember(1, "one", "answer", now=0)
    assert memory.history(1, now=60) == []
    for i in range(3): memory.remember(i, "question", "answer", now=100)
    assert memory.history(0, now=101) == []
    for i in range(4): memory.remember(2, str(i), "answer", now=102)
    assert len(memory.history(2, now=103)) == 4


def test_history_limits_text_and_returns_copies():
    memory = DialogueMemory()
    memory.remember(1, "q" * 10000, "a" * 10000, now=0)
    history = memory.history(1, now=1)
    assert len(history[0]["content"]) == 2000 and len(history[1]["content"]) == 500
    history[0]["content"] = "changed"
    assert memory.history(1, now=2)[0]["content"] != "changed"
