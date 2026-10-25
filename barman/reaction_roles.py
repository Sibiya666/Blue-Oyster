"""Роли по реакциям: реакция под привязанным сообщением в канале ролей → роль, сняли → роль снята."""
from __future__ import annotations

import json
import re
from pathlib import Path


class Bindings:
    """message_id → role_id, хранится в JSON-файле профиля."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def all(self) -> dict[str, str]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def bind(self, message_id: str, role_id: str) -> None:
        self._save({**self.all(), str(message_id): str(role_id)})

    def unbind(self, message_id: str) -> None:
        data = self.all()
        data.pop(str(message_id), None)
        self._save(data)


def role_for_reaction(bindings: Bindings, roles_channel: str, channel_id, message_id, is_bot: bool) -> str | None:
    if is_bot or str(channel_id) != str(roles_channel):
        return None
    return bindings.all().get(str(message_id))


def parse_role_arg(arg: str, roles: dict[str, str]) -> str | None:
    """«<@&id>», «id» или имя роли (без учёта регистра, с @ или без) → id из roles {id: name}."""
    a = (arg or "").strip()
    if m := re.fullmatch(r"<@&(\d+)>", a):
        return m.group(1) if m.group(1) in roles else None
    if a in roles:
        return a
    name = a.lstrip("@").strip().lower()
    return next((rid for rid, n in roles.items() if n.lower() == name), None)


PRIVILEGED = ("administrator", "manage_guild", "manage_roles", "manage_channels", "manage_webhooks", "ban_members",
              "kick_members", "moderate_members", "manage_messages", "mention_everyone", "manage_nicknames",
              "manage_emojis_and_stickers", "manage_events", "manage_threads", "view_audit_log")


def is_privileged(permissions) -> bool:
    """Роль с правами модерации/администрирования по реакции не выдаётся никогда."""
    return any(getattr(permissions, p, False) for p in PRIVILEGED)


def can_bind(role_position: int, author_top: int, author_is_owner: bool) -> bool:
    """Привязать можно только роль ниже собственной высшей роли автора (как в самом Discord)."""
    return author_is_owner or role_position < author_top


def bind_error(role_id: str, assignable: dict[str, str], role_position: int, author_top: int,
               author_is_owner: bool) -> str | None:
    """Почему роль нельзя привязать (текст для модератора) или None, если можно."""
    if str(role_id) not in assignable:
        return ("Эту роль я не могу выдавать: моя роль должна быть выше неё, "
                "а роли с правами модерации я не выдаю.")
    if not can_bind(role_position, author_top, author_is_owner):
        return "Эта роль выше твоей — привязать её может только тот, у кого роль выше."
    return None


def bindings_text(bindings: Bindings, guild_id, roles_channel) -> str:
    rows = [f"https://discord.com/channels/{guild_id}/{roles_channel}/{m} → <@&{r}>"
            for m, r in bindings.all().items()]
    return "\n".join(rows) or "Привязок пока нет."


_COMPARED = ("type", "description", "default_member_permissions", "dm_permission", "options")


def commands_to_push(desired: list[dict], existing: list[dict]) -> list[dict]:
    """Какие из наших команд в Discord отсутствуют или отличаются (чужие команды не трогаем)."""
    def norm(c: dict) -> tuple:
        return tuple(str(c.get(k) if c.get(k) not in (None, []) else "") for k in _COMPARED)
    have = {str(c.get("name")): norm(c) for c in existing}
    return [d for d in desired if have.get(str(d["name"])) != norm(d)]


async def sync_app_commands(bot, commands) -> None:
    """Hermes синхронизирует команды до подключения плагинов, поэтому свои добавляем сами —
    по одной (upsert), без массовой перезаливки чужих команд."""
    import logging
    log = logging.getLogger(__name__)
    try:
        existing = await bot.http.get_global_commands(bot.application_id)
        push = commands_to_push([c.to_dict(bot.tree) for c in commands], existing)
        for payload in push:
            await bot.http.upsert_global_command(bot.application_id, payload)
        if push:
            log.info("barman: app commands pushed: %s", [p["name"] for p in push])
    except Exception:  # noqa: BLE001
        log.warning("barman: command sync failed", exc_info=True)
