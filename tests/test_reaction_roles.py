from barman.reaction_roles import Bindings, role_for_reaction

CH = "100000000000000001"


def test_bindings_persist(tmp_path):
    b = Bindings(tmp_path / "b.json")
    b.bind("m1", "r1")
    b.bind("m2", "r2")
    assert Bindings(tmp_path / "b.json").all() == {"m1": "r1", "m2": "r2"}
    b.unbind("m1")
    assert b.all() == {"m2": "r2"}


def test_role_for_reaction_rules(tmp_path):
    b = Bindings(tmp_path / "b.json")
    b.bind("m1", "r1")
    assert role_for_reaction(b, CH, channel_id=CH, message_id="m1", is_bot=False) == "r1"
    assert role_for_reaction(b, CH, channel_id="other", message_id="m1", is_bot=False) is None
    assert role_for_reaction(b, CH, channel_id=CH, message_id="m9", is_bot=False) is None
    assert role_for_reaction(b, CH, channel_id=CH, message_id="m1", is_bot=True) is None


def test_privileged_roles_never_assignable():
    from types import SimpleNamespace
    from barman.reaction_roles import is_privileged
    assert is_privileged(SimpleNamespace(administrator=True))
    assert is_privileged(SimpleNamespace(manage_roles=True, administrator=False))
    assert is_privileged(SimpleNamespace(ban_members=True))
    assert not is_privileged(SimpleNamespace(administrator=False, send_messages=True))


def test_author_cannot_bind_role_above_own():
    from barman.reaction_roles import can_bind
    assert can_bind(role_position=3, author_top=5, author_is_owner=False)
    assert not can_bind(role_position=5, author_top=5, author_is_owner=False)
    assert not can_bind(role_position=7, author_top=5, author_is_owner=False)
    assert can_bind(role_position=7, author_top=5, author_is_owner=True)


def test_bind_error_rules():
    from barman.reaction_roles import bind_error
    roles = {"777": "Игры"}
    assert bind_error("777", roles, role_position=2, author_top=5, author_is_owner=False) is None
    assert "не могу" in bind_error("999", roles, role_position=2, author_top=5, author_is_owner=False).lower()
    assert "выше твоей" in bind_error("777", roles, role_position=6, author_top=5, author_is_owner=False)
    assert bind_error("777", roles, role_position=6, author_top=5, author_is_owner=True) is None


def test_bindings_pages(tmp_path):
    from barman.reaction_roles import bindings_pages
    b = Bindings(tmp_path / "b.json")
    b.bind("m1", "r1")
    assert bindings_pages(b, "G", CH) == [f"https://discord.com/channels/G/{CH}/m1 → <@&r1>"]


def test_commands_to_push_only_missing_or_changed():
    from barman.reaction_roles import commands_to_push
    a = {"name": "роли", "type": 1, "description": "d", "default_member_permissions": 268435456}
    b = {"name": "Привязать роль", "type": 3, "default_member_permissions": 268435456}
    existing = [{"name": "роли", "type": 1, "description": "d", "default_member_permissions": "268435456", "id": "1"},
                {"name": "new", "type": 1, "description": "hermes"}]
    assert commands_to_push([a, b], existing) == [b]
    assert commands_to_push([dict(a, description="x")], existing) == [dict(a, description="x")]


def test_sync_app_commands_upserts_only_missing_and_swallows_errors():
    import asyncio
    from types import SimpleNamespace
    from barman.reaction_roles import sync_app_commands
    pushed = []

    class Http:
        async def get_global_commands(self, app_id):
            return [{"name": "есть", "type": 1, "description": "d"}]

        async def upsert_global_command(self, app_id, payload):
            pushed.append((app_id, payload["name"]))

    class Cmd:
        def __init__(self, name):
            self.name = name

        def to_dict(self, tree):
            return {"name": self.name, "type": 1, "description": "d"}

    bot = SimpleNamespace(application_id=42, http=Http(), tree=object())
    asyncio.run(sync_app_commands(bot, [Cmd("есть"), Cmd("нет")]))
    assert pushed == [(42, "нет")]

    class Down(Http):
        async def get_global_commands(self, app_id):
            raise RuntimeError("discord down")

    asyncio.run(sync_app_commands(SimpleNamespace(application_id=42, http=Down(), tree=None), [Cmd("x")]))


def test_sync_waits_for_hermes_own_sync_before_pushing():
    import asyncio
    from types import SimpleNamespace
    from barman.reaction_roles import sync_app_commands
    order = []

    class Http:
        async def get_global_commands(self, app_id):
            order.append("fetch")
            return []

        async def upsert_global_command(self, app_id, payload):
            order.append("push")

    class Cmd:
        def to_dict(self, tree):
            return {"name": "роли", "type": 1, "description": "d"}

    async def main():
        async def hermes_sync():
            await asyncio.sleep(0.05)
            order.append("hermes-done")

        adapter = SimpleNamespace(_post_connect_task=asyncio.create_task(hermes_sync()))
        bot = SimpleNamespace(application_id=1, http=Http(), tree=None)
        await sync_app_commands(bot, [Cmd()], adapter)

    asyncio.run(main())
    assert order == ["hermes-done", "fetch", "push"]


# --- фейки для асинхронных проверок без discord.py ---
import asyncio as _asyncio
from types import SimpleNamespace as _NS


class _Reaction:
    def __init__(self, user_ids, burst_ids=(), broken=False):
        self._ids, self._burst, self._broken = user_ids, list(burst_ids), broken
        self.burst_count = len(self._burst)

    async def users(self, type=None):
        if self._broken:
            raise _HttpError(503)
        for i in (self._burst if type == "burst" else self._ids):
            yield _NS(id=i, bot=(i == 0))


class _HttpError(Exception):
    def __init__(self, status):
        self.status = status


def _messages(table):
    """{message_id: [[user_ids of reaction1], [..reaction2]]} → async fetch_message."""
    async def fetch(mid):
        if str(mid) not in table:
            raise _HttpError(404)                      # сообщение удалено
        v = table[str(mid)]
        if isinstance(v, Exception):
            raise v
        return _NS(reactions=[r if isinstance(r, _Reaction) else _Reaction(r) for r in v])
    return fetch


def test_still_reacting_other_emoji_or_other_message_of_same_role(tmp_path):
    from barman.reaction_roles import still_reacting
    b = Bindings(tmp_path / "b.json")
    b.bind("m1", "r1")
    b.bind("m2", "r1")
    b.bind("m3", "r2")
    fetch = _messages({"m1": [[5], [7]], "m2": [[8]], "m3": [[9]]})
    run = _asyncio.run
    assert run(still_reacting(b, "r1", 7, fetch))      # убрал одну реакцию, вторая стоит
    assert run(still_reacting(b, "r1", 8, fetch))      # стоит под другим сообщением той же роли
    assert not run(still_reacting(b, "r1", 9, fetch))  # реакция только под сообщением другой роли
    b.bind("gone", "r1")                                # удалённое сообщение не мешает
    assert not run(still_reacting(b, "r1", 42, fetch))


class _Member:
    def __init__(self, uid, roles=()):
        self.id, self.roles, self.added = uid, list(roles), []

    async def add_roles(self, role, reason=None):
        if self.id == 13:
            raise PermissionError("Forbidden")
        self.roles.append(role)
        self.added.append(role)


def test_grant_from_reactions_survives_left_members_and_counts_each_once(tmp_path):
    from barman.reaction_roles import grant_from_reactions
    b = Bindings(tmp_path / "b.json")
    b.bind("m1", "r1")
    b.bind("m2", "r2")
    role1 = _NS(id=1, permissions=_NS(administrator=False))
    role2 = _NS(id=2, permissions=_NS(administrator=True))   # стала привилегированной — не выдаём
    members = {5: _Member(5), 6: _Member(6, [role1]), 13: _Member(13)}

    async def member_of(uid):
        if uid not in members:
            raise LookupError("Unknown Member")            # ушёл с сервера
        return members[uid]

    fetch = _messages({"m1": [[5, 99, 0, 6, 13], [5]], "m2": [[5]]})
    added, failed, _ = _asyncio.run(grant_from_reactions(
        b, fetch, {"r1": role1, "r2": role2}.get, member_of, reason="t"))
    assert (added, failed) == (1, 2)                       # 5 получил; 99 ушёл, 13 — нет прав
    assert members[5].added == [role1]                     # дважды не выдаём за две реакции


def test_unbind_error_respects_hierarchy():
    from barman.reaction_roles import unbind_error
    assert unbind_error(role_position=3, author_top=5, author_is_owner=False) is None
    assert "выше твоей" in unbind_error(role_position=7, author_top=5, author_is_owner=False)
    assert unbind_error(role_position=7, author_top=5, author_is_owner=True) is None
    assert unbind_error(role_position=None, author_top=1, author_is_owner=False) is None  # роль удалена


def test_should_remove_role_never_for_privileged():
    from barman.reaction_roles import may_touch_role
    assert may_touch_role(_NS(permissions=_NS(administrator=False)))
    assert not may_touch_role(_NS(permissions=_NS(manage_messages=True)))
    assert not may_touch_role(None)


def test_still_reacting_raises_on_transient_error_instead_of_saying_no(tmp_path):
    import pytest
    from barman.reaction_roles import still_reacting
    b = Bindings(tmp_path / "b.json")
    b.bind("m1", "r1")
    b.bind("m2", "r1")
    with pytest.raises(_HttpError):
        _asyncio.run(still_reacting(b, "r1", 7, _messages({"m1": [[5]], "m2": _HttpError(503)})))
    with pytest.raises(_HttpError):
        _asyncio.run(still_reacting(b, "r1", 7, _messages({"m1": [_Reaction([], broken=True)], "m2": [[5]]})))


def test_super_reactions_count(tmp_path):
    from barman.reaction_roles import grant_from_reactions, still_reacting
    b = Bindings(tmp_path / "b.json")
    b.bind("m1", "r1")
    fetch = _messages({"m1": [_Reaction([], burst_ids=[7])]})
    assert _asyncio.run(still_reacting(b, "r1", 7, fetch, burst="burst"))
    role = _NS(id=1, permissions=_NS())
    m = _Member(7)
    added, failed, _ = _asyncio.run(grant_from_reactions(b, fetch, {"r1": role}.get,
                                                      lambda uid: _async(m), reason="t", burst="burst"))
    assert (added, failed) == (1, 0)


async def _async(v):
    return v


def test_grant_continues_after_broken_reaction_list(tmp_path):
    from barman.reaction_roles import grant_from_reactions
    b = Bindings(tmp_path / "b.json")
    b.bind("m1", "r1")
    b.bind("m2", "r1")
    role = _NS(id=1, permissions=_NS())
    m = _Member(5)
    fetch = _messages({"m1": [_Reaction([], broken=True)], "m2": [[5]]})
    added, failed, _ = _asyncio.run(grant_from_reactions(b, fetch, {"r1": role}.get,
                                                      lambda uid: _async(m), reason="t"))
    assert (added, failed) == (1, 1)


def test_voice_and_expression_moderation_is_privileged():
    from barman.reaction_roles import is_privileged
    for p in ("mute_members", "deafen_members", "move_members", "manage_expressions",
              "create_expressions", "create_events", "view_guild_insights"):
        assert is_privileged(_NS(**{p: True})), p


def test_rebind_checks_the_role_being_replaced(tmp_path):
    from barman.reaction_roles import rebind_error
    b = Bindings(tmp_path / "b.json")
    b.bind("m1", "high")
    pos = {"high": 9, "low": 1}.get
    assert "выше твоей" in rebind_error(b, "m1", pos, author_top=5, author_is_owner=False)
    assert rebind_error(b, "m1", pos, author_top=5, author_is_owner=True) is None
    assert rebind_error(b, "m2", pos, author_top=5, author_is_owner=False) is None   # привязки не было
    b.bind("m3", "low")
    assert rebind_error(b, "m3", pos, author_top=5, author_is_owner=False) is None


def test_role_lock_serializes_same_member_and_role():
    from barman.reaction_roles import RoleLocks
    locks = RoleLocks()
    order = []

    async def job(name, delay):
        async with locks.get(1, "r1"):
            order.append(name + "-start")
            await _asyncio.sleep(delay)
            order.append(name + "-end")

    async def main():
        await _asyncio.gather(job("a", 0.02), job("b", 0))
    _asyncio.run(main())
    assert order == ["a-start", "a-end", "b-start", "b-end"]
    assert locks.get(1, "r1") is locks.get(1, "r1") and locks.get(1, "r1") is not locks.get(2, "r1")


def test_grant_rechecks_reaction_under_lock(tmp_path):
    """Пока /синк шёл по списку, участник снял реакцию — роль ему не выдаём."""
    from barman.reaction_roles import grant_from_reactions
    b = Bindings(tmp_path / "b.json")
    b.bind("m1", "r1")
    table = {"m1": [[5, 6]]}
    calls = {"n": 0}

    async def fetch(mid):
        calls["n"] += 1
        if calls["n"] > 1:              # после первого чтения 6 уже снял реакцию
            return _NS(reactions=[_Reaction([5])])
        return _NS(reactions=[_Reaction(table["m1"][0])])

    role = _NS(id=1, permissions=_NS())
    members = {5: _Member(5), 6: _Member(6)}
    added, failed, _ = _asyncio.run(grant_from_reactions(b, fetch, {"r1": role}.get,
                                                      lambda uid: _async(members[uid]), reason="t"))
    assert (added, failed) == (1, 0) and members[6].added == []


def test_grant_broken_emoji_does_not_skip_other_emoji(tmp_path):
    from barman.reaction_roles import grant_from_reactions
    b = Bindings(tmp_path / "b.json")
    b.bind("m1", "r1")
    role = _NS(id=1, permissions=_NS())
    m = _Member(5)
    fetch = _messages({"m1": [_Reaction([], broken=True), _Reaction([5])]})

    async def member_of(uid):
        return m
    added, failed, _ = _asyncio.run(grant_from_reactions(b, fetch, {"r1": role}.get, member_of, reason="t"))
    assert (added, failed) == (1, 1)


def test_pin_messages_is_privileged():
    from barman.reaction_roles import is_privileged
    assert is_privileged(_NS(pin_messages=True))


# --- очистка реакций модератором («Remove All Reactions» / снять один эмодзи) ---

class _Holder(_Member):
    def __init__(self, uid, roles=(), bot=False, fail=False):
        super().__init__(uid, roles)
        self.bot, self.fail, self.removed = bot, fail, []

    async def remove_roles(self, role, reason=None):
        if self.fail:
            raise PermissionError("Forbidden")
        self.roles.remove(role)
        self.removed.append(role)


def test_revoke_after_clear_removes_role_only_from_those_without_reaction(tmp_path):
    from barman.reaction_roles import RoleLocks, revoke_after_clear
    b = Bindings(tmp_path / "b.json")
    b.bind("m1", "r1")
    b.bind("m2", "r1")                                    # другое сообщение той же роли
    role = _NS(id=1, permissions=_NS())
    h = {i: _Holder(i, [role]) for i in (5, 6, 7, 8)}
    h[9] = _Holder(9, [role], bot=True)                   # ботов не трогаем
    # m1 очистили; 6 стоит другим эмодзи на m1, 7 — супер-реакцией, 8 — под m2
    fetch = _messages({"m1": [[6], _Reaction([], burst_ids=[7])], "m2": [[8]]})
    removed, failed = _asyncio.run(revoke_after_clear(b, "r1", role, list(h.values()), fetch, reason="t",
                                                      burst="burst", locks=RoleLocks()))
    assert (removed, failed) == (1, 0)
    assert h[5].removed == [role]
    assert all(h[i].removed == [] for i in (6, 7, 8, 9))


def test_revoke_after_clear_is_fail_closed(tmp_path):
    import pytest
    from barman.reaction_roles import revoke_after_clear
    b = Bindings(tmp_path / "b.json")
    b.bind("m1", "r1")
    b.bind("m2", "r1")
    role = _NS(id=1, permissions=_NS())
    h = _Holder(5, [role])
    with pytest.raises(_HttpError):                       # Discord сбоит — никого не трогаем
        _asyncio.run(revoke_after_clear(b, "r1", role, [h], _messages({"m1": [], "m2": _HttpError(503)}),
                                        reason="t"))
    assert h.removed == [] and h.roles == [role]
    admin = _NS(id=2, permissions=_NS(manage_messages=True))
    a = _Holder(5, [admin])
    assert _asyncio.run(revoke_after_clear(b, "r1", admin, [a], _messages({"m1": [], "m2": []}),
                                           reason="t")) == (0, 0)
    assert a.removed == []                                # роль модерации не снимаем никогда
    bad = _Holder(6, [role], fail=True)                   # ошибка по одному не мешает остальным
    ok = _Holder(7, [role])
    assert _asyncio.run(revoke_after_clear(b, "r1", role, [bad, ok], _messages({"m1": [], "m2": []}),
                                           reason="t")) == (1, 1)


def test_revoke_after_clear_rechecks_under_lock(tmp_path):
    """Пока шла очистка, участник снова поставил реакцию — роль не снимаем."""
    from barman.reaction_roles import revoke_after_clear
    b = Bindings(tmp_path / "b.json")
    b.bind("m1", "r1")
    calls = {"n": 0}

    async def fetch(mid):
        calls["n"] += 1
        return _NS(reactions=[_Reaction([5] if calls["n"] > 1 else [])])

    role = _NS(id=1, permissions=_NS())
    h = _Holder(5, [role])
    assert _asyncio.run(revoke_after_clear(b, "r1", role, [h], fetch, reason="t")) == (0, 0)
    assert h.removed == []


# --- /роли: ответ Discord не длиннее 2000 символов ---

def test_bindings_pages_split_under_discord_limit(tmp_path):
    from barman.reaction_roles import bindings_pages
    b = Bindings(tmp_path / "b.json")
    assert bindings_pages(b, "G", CH)[0].startswith("Привязок пока нет.")
    for i in range(60):
        b.bind(f"1{i:018d}", f"2{i:018d}")
    pages = bindings_pages(b, "123456789012345678", CH)
    assert len(pages) > 1 and all(len(p) <= 2000 for p in pages)
    lines = "\n".join(pages).split("\n")
    assert len(lines) == 60 and lines[0].endswith(f"→ <@&2{0:018d}>")   # строки не рвём и не теряем


def test_bindings_text_hint_when_empty_and_problems_marked(tmp_path):
    from barman.reaction_roles import bindings_pages as bindings_text
    b = Bindings(tmp_path / "b.json")
    empty = bindings_text(b, "G", CH)
    assert len(empty) == 1 and "Привязок пока нет" in empty[0] and "Привязать роль" in empty[0]
    b.bind("m1", "r1")
    b.bind("m2", "r2")
    out = bindings_text(b, "G", CH, {"m2": "роль удалена"})
    assert out == [f"https://discord.com/channels/G/{CH}/m1 → <@&r1>\n"
                   f"https://discord.com/channels/G/{CH}/m2 → <@&r2> ⚠️ роль удалена"]


def test_bindings_text_split_under_discord_limit(tmp_path):
    from barman.reaction_roles import bindings_pages as bindings_text
    b = Bindings(tmp_path / "b.json")
    for i in range(60):
        b.bind(f"{10**18 + i}", f"{10**18 + i}")
    parts = bindings_text(b, "1" * 19, "2" * 19)
    assert len(parts) > 1 and all(len(p) <= 2000 for p in parts)
    assert sum(p.count("\n") + 1 for p in parts) == 60       # ни одна строка не потерялась и не разрезана


def _role(rid, position, perms=None, managed=False, default=False):
    return _NS(id=rid, name=f"R{rid}", position=position, permissions=_NS(**(perms or {})), managed=managed,
               is_default=lambda: default)


def test_role_problem_says_exactly_what_to_fix():
    from barman.reaction_roles import role_problem
    assert role_problem(_role(1, 3), bot_top=5) is None
    assert "удален" in role_problem(None, bot_top=5)
    assert "выше" in role_problem(_role(1, 7), bot_top=5) and "Бармен" in role_problem(_role(1, 7), bot_top=5)
    assert "модерац" in role_problem(_role(1, 3, {"ban_members": True}), bot_top=5)
    assert "интеграц" in role_problem(_role(1, 3, managed=True), bot_top=5)
    assert role_problem(_role(1, 0, default=True), bot_top=5) is not None


def test_pickable_roles_only_what_bot_and_author_can_bind_sorted_and_capped():
    from barman.reaction_roles import pickable_roles
    roles = [_role(1, 1), _role(2, 2), _role(3, 4), _role(4, 9), _role(5, 2, {"administrator": True}),
             _role(6, 0, default=True), _role(7, 3, managed=True)]
    got, cut = pickable_roles(roles, bot_top=8, author_top=4, author_is_owner=False)
    assert [r.id for r in got] == [2, 1] and not cut          # 3 — не ниже автора, 4 — выше бота
    got, _ = pickable_roles(roles, bot_top=8, author_top=4, author_is_owner=True)
    assert [r.id for r in got] == [3, 2, 1]
    many = [_role(i, i) for i in range(1, 40)]
    got, cut = pickable_roles(many, bot_top=100, author_top=100, author_is_owner=False)
    assert len(got) == 25 and cut and got[0].id == 39


def test_binding_problems_reports_roles_and_deleted_messages(tmp_path):
    from barman.reaction_roles import binding_problems
    b = Bindings(tmp_path / "b.json")
    b.bind("ok", "r1")
    b.bind("high", "r2")
    b.bind("gone", "r1")
    b.bind("norole", "r9")
    roles = {"r1": _role(1, 2), "r2": _role(2, 9)}
    fetch = _messages({"ok": [[1]], "high": [[1]], "norole": [[1]]})
    got = _asyncio.run(binding_problems(b, roles.get, fetch, bot_top=5))
    assert set(got) == {"high", "gone", "norole"}
    assert "выше" in got["high"] and "удалено" in got["gone"] and "удален" in got["norole"]


def test_grant_cleans_bindings_of_deleted_messages(tmp_path):
    from barman.reaction_roles import grant_from_reactions
    b = Bindings(tmp_path / "b.json")
    b.bind("gone", "r1")
    b.bind("m1", "r1")
    role = _NS(id=1, permissions=_NS())
    m = _Member(5)
    added, failed, cleaned = _asyncio.run(grant_from_reactions(
        b, _messages({"m1": [[5]]}), {"r1": role}.get, lambda uid: _async(m), reason="t"))
    assert (added, failed, cleaned) == (1, 0, 1) and b.all() == {"m1": "r1"}


def test_user_facing_texts():
    from barman.reaction_roles import UNBIND_DONE, bind_done_text, sync_text
    assert "осталась" in UNBIND_DONE
    assert "✅" in bind_done_text("<@&1>", seeded=True)
    assert "не смог" in bind_done_text("<@&1>", seeded=False)
    assert sync_text(2, 0, 0) == "Синхронизировал: выдано ролей — 2."
    t = sync_text(0, 1, 3)
    assert "не удалось — 1" in t.lower() and "3" in t and "удалён" in t
