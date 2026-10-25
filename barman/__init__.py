"""Плагин Hermes «barman»: роли по реакциям в Discord.

Участник ставит реакцию под привязанным сообщением в канале ролей → получает роль; снимает → роль снята.
Команды видят только те, у кого есть право «Управлять ролями»; работают в канале ролей,
ответы бота видит только вызвавший:
  ПКМ по сообщению → Приложения → «Привязать роль» / «Отвязать роль»
  /роли — список привязок
  /синк — выдать роли всем, кто уже стоит в реакциях
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)
_tasks: set = set()


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
    from .reaction_roles import (Bindings, RoleLocks, bind_error, bindings_text, grant_from_reactions, is_privileged,
                                 may_touch_role, rebind_error, role_for_reaction, still_reacting, sync_app_commands,
                                 unbind_error)

    channel = _env(home).get("BARMAN_ROLES_CHANNEL", "")
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

        class Picker(discord.ui.View):
            def __init__(self, message_id: str):
                super().__init__(timeout=300)
                self.message_id = message_id

            @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="Выбери роль")
            async def pick(self, interaction, select):
                role, guild, user = select.values[0], interaction.guild, interaction.user
                if not getattr(user.guild_permissions, "manage_roles", False):  # права могли отозвать
                    await interaction.response.edit_message(content="Нужно право «Управлять ролями».", view=None)
                    return
                owner = guild.owner_id == user.id
                err = rebind_error(bindings, self.message_id, position_in(guild), user.top_role.position, owner)
                if err:
                    await interaction.response.edit_message(content=err, view=None)
                    return
                err = bind_error(str(role.id), assignable(guild), role.position, user.top_role.position, owner)
                if err:
                    await interaction.response.edit_message(content=err + " Выбери другую.", view=self)
                    return
                bindings.bind(self.message_id, str(role.id))
                await interaction.response.edit_message(
                    content=f"Привязал: реакция под тем сообщением → {role.mention}.",
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
            await hidden(interaction, "К какой роли привязать это сообщение?", view=Picker(str(message.id)))

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
            await hidden(interaction, "Отвязал.")

        async def list_cmd(interaction):
            if await allowed(interaction):
                await hidden(interaction, bindings_text(bindings, interaction.guild.id, channel))

        async def sync_cmd(interaction):
            if not await allowed(interaction):
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            guild = interaction.guild
            try:
                added, failed = await grant_from_reactions(
                    bindings, fetch_from(guild), lambda rid: guild.get_role(int(rid)),
                    lambda uid: member_of(guild, uid), reason, burst=burst, locks=locks)
                text = f"Синхронизировал: выдано ролей — {added}."
                if failed:
                    text += f" Не удалось — {failed} (ушли с сервера или мне не хватает прав)."
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

    ctx.register_platform_handler("discord", factory)
