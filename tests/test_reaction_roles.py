from barman.reaction_roles import Bindings, parse_role_arg, role_for_reaction

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


def test_parse_role_arg_mention_id_and_name():
    roles = {"777": "Корги­войны", "888": "Dota 2"}
    assert parse_role_arg("<@&777>", roles) == "777"
    assert parse_role_arg("888", roles) == "888"
    assert parse_role_arg("dota 2", roles) == "888"
    assert parse_role_arg("@Корги­войны", roles) == "777"
    assert parse_role_arg("нет такой", roles) is None


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


def test_bindings_text(tmp_path):
    from barman.reaction_roles import bindings_text
    b = Bindings(tmp_path / "b.json")
    assert bindings_text(b, "G", CH) == "Привязок пока нет."
    b.bind("m1", "r1")
    assert bindings_text(b, "G", CH) == f"https://discord.com/channels/G/{CH}/m1 → <@&r1>"


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
