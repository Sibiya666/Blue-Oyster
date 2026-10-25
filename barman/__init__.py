"""Плагин Hermes «barman»: роли по реакциям в Discord.

Участник ставит реакцию под привязанным сообщением в канале ролей → получает роль; снимает → роль снята.
Команды видят только те, у кого есть право «Управлять ролями»; работают в канале ролей,
ответы бота видит только вызвавший:
  ПКМ по сообщению → Приложения → «Привязать роль» / «Отвязать роль»
  /роли — список привязок
  /синк — выдать роли всем, кто уже стоит в реакциях
Плюс ежедневная выжимка DTF в 21:00 по Москве (digest.py), если задан BARMAN_DIGEST_CHANNEL.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)
_tasks: set = set()
_digest: dict = {}  # одна задача выжимки на процесс: фабрику могут вызвать повторно при переподключении


def _env(home: Path) -> dict:
    out = {}
    p = home / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"')
    return out


def register(ctx) -> None:
    if not hasattr(ctx, "register_platform_handler"):
        return
    home = Path(getattr(getattr(ctx, "_manager", None), "home_path", "") or os.environ.get("HERMES_HOME", ""))
    if not str(home):
        return
    from .reaction_roles import (UNBIND_DONE, Bindings, RoleLocks, bind_done_text, bind_error, binding_problems,
                                 bindings_pages, grant_from_reactions, is_privileged, may_touch_role, pickable_roles,
                                 rebind_error, revoke_after_clear, role_for_reaction, still_reacting,
                                 sync_app_commands, sync_text, unbind_error)

    env = _env(home)
    channel = env.get("BARMAN_ROLES_CHANNEL", "")
    bindings = Bindings(home / "barman" / "bindings.json")

    def factory(bot, adapter=None):
        import discord  # внутри Hermes

        reason = "Бармен: роль по реакции"
        burst = discord.ReactionType.burst  # супер-реакции discord.py по умолчанию не перечисляет
        locks = RoleLocks()
        quiet = discord.AllowedMentions.none()  # не пинговать роль при ответе бота

        def assignable(guild) -> dict[str, str]:
            top = guild.me.top_role.position if guild.me else 0
            return {str(r.id): r.name for r in guild.roles
                    if not r.is_default() and not r.managed and r.position < top
                    and not is_privileged(r.permissions)}

        async def member_of(guild, user_id):
            return guild.get_member(user_id) or await guild.fetch_member(user_id)

        def fetch_from(guild):
            async def fetch(mid):
                ch = guild.get_channel(int(channel)) or await guild.fetch_channel(int(channel))
                return await ch.fetch_message(int(mid))
            return fetch

        async def on_raw_reaction_add(payload):
            is_bot = bool(payload.member and payload.member.bot)
            rid = role_for_reaction(bindings, channel, payload.channel_id, payload.message_id, is_bot)
            if not rid or not payload.guild_id:
                return
            guild = bot.get_guild(payload.guild_id)
            role = guild and guild.get_role(int(rid))
            if guild and may_touch_role(role):  # права роли могли поменять после привязки
                try:
                    async with locks.get(payload.user_id, rid):
                        member = payload.member or await member_of(guild, payload.user_id)
                        if not member.bot:  # без оглядки на кеш ролей: он мог отстать, а выдача идемпотентна
                            await member.add_roles(role, reason=reason)
                except Exception:  # noqa: BLE001
                    log.warning("barman: add role failed", exc_info=True)

        async def on_raw_reaction_remove(payload):
            rid = role_for_reaction(bindings, channel, payload.channel_id, payload.message_id, False)
            if not rid or not payload.guild_id:
                return
            guild = bot.get_guild(payload.guild_id)
            role = guild and guild.get_role(int(rid))
            if guild and may_touch_role(role):  # роль модератора по реакции не снимаем никогда
                try:
                    async with locks.get(payload.user_id, rid):
                        member = await member_of(guild, payload.user_id)
                        if member.bot:
                            return
                        # реакция могла остаться: другой эмодзи, супер-реакция или другое сообщение этой роли;
                        # при сбое проверки still_reacting бросает исключение — роль тогда не снимаем
                        if await still_reacting(bindings, rid, payload.user_id, fetch_from(guild), burst):
                            return
                        await member.remove_roles(role, reason=reason)
                except Exception:  # noqa: BLE001
                    log.warning("barman: remove role failed", exc_info=True)

        async def on_raw_reaction_clear(payload):
            # «Remove All Reactions» или снятие одного эмодзи: Discord не присылает, чьи реакции ушли.
            # Проверяем тех, у кого роль сейчас есть (кеш участников): без реакции — роль снимаем.
            rid = role_for_reaction(bindings, channel, payload.channel_id, payload.message_id, False)
            if not rid or not payload.guild_id:
                return
            guild = bot.get_guild(payload.guild_id)
            role = guild and guild.get_role(int(rid))
            if not (guild and may_touch_role(role)):
                return
            try:
                removed, failed = await revoke_after_clear(bindings, rid, role, list(role.members),
                                                           fetch_from(guild), reason, burst=burst, locks=locks)
                if failed:
                    log.warning("barman: after reaction clear %s role(s) not removed", failed)
            except Exception:  # noqa: BLE001 — сбой Discord: роли не снимаем никому
                log.warning("barman: revoke after reaction clear failed", exc_info=True)

        from discord import app_commands

        mod_perms = discord.Permissions(manage_roles=True)  # обычные участники команд не видят

        async def hidden(interaction, text, **kw):
            await interaction.response.send_message(text, ephemeral=True, allowed_mentions=quiet, **kw)

        async def allowed(interaction) -> bool:
            if not interaction.guild or not getattr(interaction.user.guild_permissions, "manage_roles", False):
                await hidden(interaction, "Нужно право «Управлять ролями».")
                return False
            if str(interaction.channel_id) != channel:
                await hidden(interaction, f"Это работает только в <#{channel}>.")
                return False
            return True

        def bot_top(guild) -> int:
            return guild.me.top_role.position if guild.me else 0

        class Picker(discord.ui.View):
            """Меню только из ролей, которые этот модератор может привязать, а бот — выдать."""

            def __init__(self, message_id: str, roles):
                super().__init__(timeout=300)
                self.message_id = message_id
                select = discord.ui.Select(placeholder="Выбери роль", options=[
                    discord.SelectOption(label=r.name[:100], value=str(r.id)) for r in roles])
                select.callback = self.pick
                self.add_item(select)
                self.select = select

            async def pick(self, interaction):
                guild, user = interaction.guild, interaction.user
                role = guild.get_role(int(self.select.values[0]))
                if not getattr(user.guild_permissions, "manage_roles", False):  # права могли отозвать
                    await interaction.response.edit_message(content="Нужно право «Управлять ролями».", view=None)
                    return
                owner = guild.owner_id == user.id
                err = rebind_error(bindings, self.message_id, position_in(guild), user.top_role.position, owner)
                if err:
                    await interaction.response.edit_message(content=err, view=None)
                    return
                err = role is None and "Роль уже удалили." or bind_error(
                    str(role.id), assignable(guild), role.position, user.top_role.position, owner)
                if err:  # пока меню было открыто, роли могли поменять
                    await interaction.response.edit_message(content=err + " Открой меню заново.", view=None)
                    return
                bindings.bind(self.message_id, str(role.id))
                seeded = True
                try:  # своя реакция: участникам сразу видно, что нажать (реакции бота бармен игнорирует)
                    await (await fetch_from(guild)(self.message_id)).add_reaction("✅")
                except Exception:  # noqa: BLE001
                    seeded = False
                await interaction.response.edit_message(content=bind_done_text(role.mention, seeded),
                                                        view=None, allowed_mentions=quiet)

        def position_in(guild):
            return lambda rid: (r.position if (r := guild.get_role(int(rid))) else None)

        async def bind_menu(interaction, message):
            if not await allowed(interaction):
                return
            user = interaction.user
            err = rebind_error(bindings, message.id, position_in(interaction.guild), user.top_role.position,
                               interaction.guild.owner_id == user.id)
            if err:
                await hidden(interaction, err)
                return
            roles, cut = pickable_roles(interaction.guild.roles, bot_top(interaction.guild), user.top_role.position,
                                        interaction.guild.owner_id == user.id)
            if not roles:
                await hidden(interaction, "Нет ролей, которые я могу выдать от твоего имени. Роль «Бармен» должна "
                                          "стоять выше раздаваемых ролей, а сами роли — без прав модерации "
                                          "и ниже твоей.")
                return
            text = "К какой роли привязать это сообщение?"
            if cut:
                text += " Показаны 25 верхних — Discord больше в меню не помещает."
            await hidden(interaction, text, view=Picker(str(message.id), roles))

        async def unbind_menu(interaction, message):
            if not await allowed(interaction):
                return
            rid = bindings.all().get(str(message.id))
            if rid is None:
                await hidden(interaction, "К этому сообщению роль не привязана.")
                return
            role, user = interaction.guild.get_role(int(rid)), interaction.user
            err = unbind_error(role.position if role else None, user.top_role.position,
                               interaction.guild.owner_id == user.id)
            if err:
                await hidden(interaction, err)
                return
            bindings.unbind(str(message.id))
            await hidden(interaction, UNBIND_DONE)

        async def list_cmd(interaction):
            if not await allowed(interaction):
                return
            await interaction.response.defer(ephemeral=True, thinking=True)  # проверка ходит в Discord
            guild = interaction.guild
            try:
                problems = await binding_problems(bindings, lambda rid: guild.get_role(int(rid)), fetch_from(guild),
                                                  bot_top(guild))
            except Exception:  # noqa: BLE001
                log.warning("barman: binding check failed", exc_info=True)
                problems = {}
            for page in bindings_pages(bindings, guild.id, channel, problems):  # лимит Discord — 2000 символов
                await interaction.followup.send(page, ephemeral=True, allowed_mentions=quiet)

        async def sync_cmd(interaction):
            if not await allowed(interaction):
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            guild = interaction.guild
            try:
                added, failed, cleaned = await grant_from_reactions(
                    bindings, fetch_from(guild), lambda rid: guild.get_role(int(rid)),
                    lambda uid: member_of(guild, uid), reason, burst=burst, locks=locks)
                text = sync_text(added, failed, cleaned)
            except Exception:  # noqa: BLE001
                log.warning("barman: sync failed", exc_info=True)
                text = "Не получилось синхронизировать, подробности в логе."
            await interaction.followup.send(text, ephemeral=True)

        # Модуль под `from __future__ import annotations`: тип сообщения для меню задаём объектом.
        bind_menu.__annotations__["message"] = unbind_menu.__annotations__["message"] = discord.Message
        commands = [
            app_commands.ContextMenu(name="Привязать роль", callback=bind_menu),
            app_commands.ContextMenu(name="Отвязать роль", callback=unbind_menu),
            app_commands.Command(name="роли", description="Бармен: какие сообщения к каким ролям привязаны",
                                 callback=list_cmd),
            app_commands.Command(name="синк", description="Бармен: выдать роли всем, кто уже стоит в реакциях",
                                 callback=sync_cmd),
        ]
        for cmd in commands:
            cmd.default_permissions, cmd.guild_only = mod_perms, True
            bot.tree.add_command(cmd, override=True)
        import asyncio
        task = asyncio.get_running_loop().create_task(sync_app_commands(bot, commands, adapter))
        _tasks.add(task)  # держим ссылку, иначе задачу может собрать GC
        task.add_done_callback(_tasks.discard)

        bot.add_listener(on_raw_reaction_add, "on_raw_reaction_add")
        bot.add_listener(on_raw_reaction_remove, "on_raw_reaction_remove")
        bot.add_listener(on_raw_reaction_clear, "on_raw_reaction_clear")
        bot.add_listener(on_raw_reaction_clear, "on_raw_reaction_clear_emoji")

        if not env.get("BARMAN_DIGEST_CHANNEL"):
            log.info("barman: DTF digest disabled (no BARMAN_DIGEST_CHANNEL)")
        elif not (_digest.get("task") and not _digest["task"].done()):
            _digest["task"] = asyncio.get_running_loop().create_task(_digest_loop(bot, env, home, discord))

    ctx.register_platform_handler("discord", factory)


async def _digest_loop(bot, env: dict, home: Path, discord) -> None:
    """Выжимка DTF: сразу при первом запуске, дальше каждый день в 21:00 по Москве; пропущенный выпуск
    (бот лежал в 21:00) догоняется при старте. Сбой — повтор через 10 минут, после трёх сбоев выпуск пропускаем."""
    import asyncio
    from datetime import datetime

    from .digest import MSK, DigestState, due_slot, next_slot
    state = DigestState(home / "barman" / "digest.json")
    await bot.wait_until_ready()
    failures = 0
    while True:
        now = datetime.now(MSK)
        if due_slot(state.last_posted(), now) is not None:
            try:
                await _post_digest(bot, env, discord, now)
                state.mark(now)
                failures = 0
            except Exception:  # noqa: BLE001
                failures += 1
                log.warning("barman: digest failed (%s/3)", failures, exc_info=True)
                if failures >= 3:
                    state.mark(now)
                    failures = 0
                else:
                    await asyncio.sleep(600)
                    continue
        wait = (next_slot(datetime.now(MSK)) - datetime.now(MSK)).total_seconds()
        await asyncio.sleep(max(1.0, min(wait, 3600.0)))  # просыпаемся хотя бы раз в час: часы могли уйти


async def _post_digest(bot, env: dict, discord, now) -> None:
    import aiohttp

    from .digest import collect_day, day_window, format_digest, pick_top, summarize
    start, end = day_window(now)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60),
                                     headers={"User-Agent": "BarmanBot/1.0 (Discord digest)"}) as http:
        async def fetch_json(url):
            async with http.get(url) as r:
                r.raise_for_status()
                return (await r.json(content_type=None)).get("result") or {}

        top = pick_top(await collect_day(fetch_json, start), start, end)

        llm = None
        if env.get("OPENROUTER_API_KEY"):
            async def llm(messages):
                body = {"model": env.get("BARMAN_DIGEST_MODEL") or "anthropic/claude-haiku-4.5",
                        "messages": messages, "temperature": 0.3, "max_tokens": 2000}
                async with http.post("https://openrouter.ai/api/v1/chat/completions", json=body,
                                     headers={"Authorization": f"Bearer {env['OPENROUTER_API_KEY']}"}) as r:
                    r.raise_for_status()
                    return (await r.json())["choices"][0]["message"]["content"]
        summaries = await summarize(top, llm)

    channel_id = int(env["BARMAN_DIGEST_CHANNEL"])
    channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
    guild = channel.guild
    if not channel.permissions_for(guild.me).send_messages:
        raise PermissionError(f"barman: no Send Messages in digest channel {channel_id}")
    member = None
    if env.get("BARMAN_DIGEST_USER"):
        name = env["BARMAN_DIGEST_USER"].lstrip("@").lower()
        found = await guild.query_members(query=name, limit=10)
        member = next((m for m in found if m.name.lower() == name), None)
        if member is None:
            log.warning("barman: digest user %r not found on the server", name)
    pages = format_digest(top, summaries, member.mention if member else None, now)
    for i, page in enumerate(pages):
        allowed = discord.AllowedMentions(everyone=False, roles=False, users=[member] if member and i == 0 else False)
        await channel.send(page, allowed_mentions=allowed, suppress_embeds=True)
    log.info("barman: digest posted: %d items, %d message(s), mention=%s", len(top), len(pages), bool(member))
