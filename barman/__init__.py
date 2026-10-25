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
    from .reaction_roles import Bindings, bind_error, bindings_text, is_privileged, role_for_reaction, sync_app_commands

    channel = _env(home).get("BARMAN_ROLES_CHANNEL", "")
    bindings = Bindings(home / "barman" / "bindings.json")

    def factory(bot, adapter=None):
        import discord  # внутри Hermes

        reason = "Бармен: роль по реакции"
        quiet = discord.AllowedMentions.none()  # не пинговать роль при ответе бота

        def assignable(guild) -> dict[str, str]:
            top = guild.me.top_role.position if guild.me else 0
            return {str(r.id): r.name for r in guild.roles
                    if not r.is_default() and not r.managed and r.position < top
                    and not is_privileged(r.permissions)}

        async def member_of(guild, user_id):
            return guild.get_member(user_id) or await guild.fetch_member(user_id)

        async def on_raw_reaction_add(payload):
            is_bot = bool(payload.member and payload.member.bot)
            rid = role_for_reaction(bindings, channel, payload.channel_id, payload.message_id, is_bot)
            if not rid or not payload.guild_id:
                return
            guild = bot.get_guild(payload.guild_id)
            role = guild and guild.get_role(int(rid))
            if role and not is_privileged(role.permissions):  # права роли могли поменять после привязки
                try:
                    member = payload.member or await member_of(guild, payload.user_id)
                    if not member.bot and role not in member.roles:
                        await member.add_roles(role, reason=reason)
                except Exception:  # noqa: BLE001
                    log.warning("barman: add role failed", exc_info=True)

        async def on_raw_reaction_remove(payload):
            rid = role_for_reaction(bindings, channel, payload.channel_id, payload.message_id, False)
            if not rid or not payload.guild_id:
                return
            guild = bot.get_guild(payload.guild_id)
            role = guild and guild.get_role(int(rid))
            if role:
                try:
                    member = await member_of(guild, payload.user_id)
                    if not member.bot and role in member.roles:
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
                err = bind_error(str(role.id), assignable(guild), role.position, user.top_role.position,
                                 guild.owner_id == user.id)
                if err:
                    await interaction.response.edit_message(content=err + " Выбери другую.", view=self)
                    return
                bindings.bind(self.message_id, str(role.id))
                await interaction.response.edit_message(
                    content=f"Привязал: реакция под тем сообщением → {role.mention}.",
                    view=None, allowed_mentions=quiet)

        async def bind_menu(interaction, message):
            if await allowed(interaction):
                await hidden(interaction, "К какой роли привязать это сообщение?", view=Picker(str(message.id)))

        async def unbind_menu(interaction, message):
            if await allowed(interaction):
                had = str(message.id) in bindings.all()
                bindings.unbind(str(message.id))
                await hidden(interaction, "Отвязал." if had else "К этому сообщению роль не привязана.")

        async def list_cmd(interaction):
            if await allowed(interaction):
                await hidden(interaction, bindings_text(bindings, interaction.guild.id, channel))

        async def sync_cmd(interaction):
            if not await allowed(interaction):
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            guild, added = interaction.guild, 0
            for mid, rid in bindings.all().items():
                role = guild.get_role(int(rid))
                try:
                    msg = await interaction.channel.fetch_message(int(mid))
                except Exception:  # noqa: BLE001
                    continue
                for reaction in msg.reactions:
                    async for user in reaction.users():
                        if user.bot or role is None or is_privileged(role.permissions):
                            continue
                        member = await member_of(guild, user.id)
                        if role not in member.roles:
                            await member.add_roles(role, reason=reason)
                            added += 1
            await interaction.followup.send(f"Синхронизировал: выдано ролей — {added}.", ephemeral=True)

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
        task = asyncio.get_running_loop().create_task(sync_app_commands(bot, commands))
        _tasks.add(task)  # держим ссылку, иначе задачу может собрать GC
        task.add_done_callback(_tasks.discard)

        bot.add_listener(on_raw_reaction_add, "on_raw_reaction_add")
        bot.add_listener(on_raw_reaction_remove, "on_raw_reaction_remove")

    ctx.register_platform_handler("discord", factory)
