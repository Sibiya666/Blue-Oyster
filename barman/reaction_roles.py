"""Роли по реакциям: реакция под привязанным сообщением в канале ролей → роль, сняли → роль снята."""
from __future__ import annotations

import json
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


PRIVILEGED = ("administrator", "manage_guild", "manage_roles", "manage_channels", "manage_webhooks", "ban_members",
              "kick_members", "moderate_members", "manage_messages", "mention_everyone", "manage_nicknames",
              "manage_emojis_and_stickers", "manage_events", "manage_threads", "view_audit_log",
              "mute_members", "deafen_members", "move_members", "manage_expressions", "create_expressions",
              "create_events", "view_guild_insights", "view_creator_monetization_analytics", "pin_messages")


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


def unbind_error(role_position: int | None, author_top: int, author_is_owner: bool) -> str | None:
    """Отвязать можно только то, что разрешено привязать (роль ниже своей). Удалённую роль — можно."""
    if role_position is None or can_bind(role_position, author_top, author_is_owner):
        return None
    return "Эта роль выше твоей — отвязать её может только тот, у кого роль выше."


def may_touch_role(role) -> bool:
    """Выдавать и снимать по реакции можно только существующую роль без прав модерации."""
    return role is not None and not is_privileged(role.permissions)


def rebind_error(bindings: Bindings, message_id, role_position, author_top: int,
                 author_is_owner: bool) -> str | None:
    """Перепривязка заменяет старую роль — значит, на старую нужны те же права, что и на отвязку.
    role_position(role_id) → позиция роли или None, если роли уже нет."""
    old = bindings.all().get(str(message_id))
    if old is None or unbind_error(role_position(old), author_top, author_is_owner) is None:
        return None
    return "К этому сообщению уже привязана роль выше твоей — менять привязку может только тот, у кого роль выше."


class RoleLocks:
    """Замок на пару (участник, роль): выдача, снятие и /синк для одного человека не перемешиваются."""

    def __init__(self):
        self._locks: dict = {}

    def get(self, user_id, role_id):
        import asyncio
        return self._locks.setdefault((int(user_id), str(role_id)), asyncio.Lock())


def _missing(exc) -> bool:
    """Сообщение удалено (404) — это не ошибка, его просто пропускаем."""
    return getattr(exc, "status", None) == 404


async def _users(reaction, burst):
    """Все, кто поставил реакцию: обычную и супер-реакцию (её discord.py по умолчанию не отдаёт)."""
    async for user in reaction.users():
        yield user
    if burst is not None and getattr(reaction, "burst_count", 0):
        async for user in reaction.users(type=burst):
            yield user


async def still_reacting(bindings: Bindings, role_id, user_id, fetch_message, burst=None) -> bool:
    """Стоит ли у участника ещё хоть одна реакция под любым сообщением, привязанным к этой роли.
    Удалённые сообщения пропускаем; любая другая ошибка пробрасывается — при сомнении роль не снимаем."""
    for mid, rid in bindings.all().items():
        if rid != str(role_id):
            continue
        try:
            msg = await fetch_message(mid)
        except Exception as exc:  # noqa: BLE001
            if _missing(exc):
                continue
            raise
        for reaction in msg.reactions:
            async for user in _users(reaction, burst):
                if user.id == user_id:
                    return True
    return False


async def _reacts_on(msg, user_id, burst) -> bool:
    """Стоит ли реакция участника под этим сообщением. Сломанный эмодзи пропускаем — ищем в остальных."""
    for reaction in msg.reactions:
        try:
            async for user in _users(reaction, burst):
                if user.id == user_id:
                    return True
        except Exception:  # noqa: BLE001
            continue
    return False


async def grant_from_reactions(bindings: Bindings, fetch_message, get_role, member_of, reason: str,
                               burst=None, locks: RoleLocks | None = None) -> tuple[int, int]:
    """Выдать роли всем, кто стоит в реакциях. Ошибка по участнику, эмодзи или сообщению (ушёл, нет прав,
    сбой Discord) не прерывает остальных. Перед выдачей под замком реакцию перепроверяем: пока /синк шёл
    по списку, её могли снять. Привязки удалённых сообщений убираем. Возвращает (выдано, не удалось, убрано)."""
    import contextlib
    added = failed = cleaned = 0
    for mid, rid in bindings.all().items():
        role = get_role(rid)
        try:
            msg = await fetch_message(mid)
        except Exception as exc:  # noqa: BLE001
            if _missing(exc):  # сообщение удалили — привязка больше не нужна
                bindings.unbind(mid)
                cleaned += 1
            else:
                failed += 1
            continue
        if not may_touch_role(role):
            continue
        seen: set = set()
        for reaction in msg.reactions:
            try:
                async for user in _users(reaction, burst):
                    if user.bot or user.id in seen:
                        continue
                    seen.add(user.id)
                    try:
                        async with (locks.get(user.id, rid) if locks else contextlib.nullcontext()):
                            if not await _reacts_on(await fetch_message(mid), user.id, burst):
                                continue
                            member = await member_of(user.id)
                            if role not in member.roles:
                                await member.add_roles(role, reason=reason)
                                added += 1
                    except Exception:  # noqa: BLE001
                        failed += 1
            except Exception:  # noqa: BLE001 — сбой перечисления одного эмодзи
                failed += 1
    return added, failed, cleaned


async def _reactors(bindings: Bindings, role_id, fetch_message, burst) -> set:
    """id всех, у кого стоит реакция под любым сообщением этой роли. Удалённые сообщения пропускаем,
    любой другой сбой пробрасываем."""
    ids: set = set()
    for mid, rid in bindings.all().items():
        if rid != str(role_id):
            continue
        try:
            msg = await fetch_message(mid)
        except Exception as exc:  # noqa: BLE001
            if _missing(exc):
                continue
            raise
        for reaction in msg.reactions:
            async for user in _users(reaction, burst):
                ids.add(user.id)
    return ids


async def revoke_after_clear(bindings: Bindings, role_id, role, holders, fetch_message, reason: str,
                             burst=None, locks: RoleLocks | None = None) -> tuple[int, int]:
    """Модератор очистил реакции (все или один эмодзи) — Discord не говорит, чьи. Поэтому идём по тем,
    у кого роль сейчас есть (holders), и снимаем её тем, у кого не осталось ни одной реакции под
    сообщениями этой роли. Сначала один общий снимок реакций (дёшево), затем для каждого кандидата
    перепроверка под замком: он мог успеть снова поставить реакцию. Сбой снимка пробрасывается и роли
    не снимаются никому (fail-closed); сбой по участнику — роль ему оставляем. Возвращает (снято, не удалось)."""
    import contextlib
    if not may_touch_role(role):
        return 0, 0
    reacting = await _reactors(bindings, role_id, fetch_message, burst)
    removed = failed = 0
    for member in holders:
        if member.bot or member.id in reacting:
            continue
        try:
            async with (locks.get(member.id, role_id) if locks else contextlib.nullcontext()):
                if role not in member.roles:
                    continue
                if await still_reacting(bindings, role_id, member.id, fetch_message, burst):
                    continue
                await member.remove_roles(role, reason=reason)
                removed += 1
        except Exception:  # noqa: BLE001
            failed += 1
    return removed, failed


DISCORD_LIMIT = 2000


HOW_TO_BIND = "ПКМ по сообщению в канале ролей → Приложения → «Привязать роль»."
UNBIND_DONE = ("Отвязал. У тех, кто уже получил роль, она осталась — "
               "если нужно, сними её вручную в настройках сервера.")


def bindings_pages(bindings: Bindings, guild_id, roles_channel, problems: dict | None = None,
                   limit: int = DISCORD_LIMIT) -> list[str]:
    """Список привязок, порезанный по строкам на сообщения не длиннее limit (лимит Discord — 2000).
    problems: {message_id: что не так} — помечается ⚠️. Пустой список — с подсказкой, как привязать."""
    problems = problems or {}
    rows = [f"https://discord.com/channels/{guild_id}/{roles_channel}/{m} → <@&{r}>"
            + (f" ⚠️ {problems[m]}" if m in problems else "")
            for m, r in bindings.all().items()]
    pages: list[str] = []
    for row in rows:
        if pages and len(pages[-1]) + 1 + len(row) <= limit:
            pages[-1] += "\n" + row
        else:
            pages.append(row)
    return pages or [f"Привязок пока нет. Чтобы добавить: {HOW_TO_BIND}"]


def role_problem(role, bot_top: int) -> str | None:
    """Почему бот не сможет выдавать эту роль — с подсказкой, что починить. None — всё в порядке."""
    if role is None:
        return "роль удалена"
    if role.is_default():
        return "это @everyone, её нельзя выдать"
    if getattr(role, "managed", False):
        return "роль управляется интеграцией (ботом или подпиской), её нельзя выдать"
    if is_privileged(role.permissions):
        return "у роли права модерации — по реакции такие не выдаю"
    if role.position >= bot_top:
        return "роль выше моей — подними роль «Бармен» выше неё в настройках сервера"
    return None


def pickable_roles(roles, bot_top: int, author_top: int, author_is_owner: bool, limit: int = 25):
    """Роли, которые этот модератор может привязать, а бот — выдать. Сверху вниз; в меню Discord влезает 25.
    Возвращает (роли, обрезан_ли_список)."""
    ok = [r for r in roles if role_problem(r, bot_top) is None and can_bind(r.position, author_top, author_is_owner)]
    ok.sort(key=lambda r: -r.position)
    return ok[:limit], len(ok) > limit


async def binding_problems(bindings: Bindings, get_role, fetch_message, bot_top: int) -> dict:
    """Что сломано в привязках: роль удалена/выше бота/стала модераторской, сообщение удалено."""
    out = {}
    for mid, rid in bindings.all().items():
        problem = role_problem(get_role(rid), bot_top)
        if problem is None:
            try:
                await fetch_message(mid)
            except Exception as exc:  # noqa: BLE001
                problem = ("сообщение удалено — /синк уберёт привязку" if _missing(exc)
                           else "не смог проверить сообщение")
        if problem:
            out[mid] = problem
    return out


def bind_done_text(role_mention: str, seeded: bool) -> str:
    if seeded:
        return f"Привязал: реакция под тем сообщением → {role_mention}. Поставил ✅, чтобы участникам было что нажать."
    return (f"Привязал: реакция под тем сообщением → {role_mention}. Но не смог поставить ✅ — "
            "дай мне право «Добавлять реакции» в этом канале, иначе участникам может быть нечего нажать.")


def sync_text(added: int, failed: int, cleaned: int) -> str:
    text = f"Синхронизировал: выдано ролей — {added}."
    if failed:
        text += f" Не удалось — {failed} (ушли с сервера, мне не хватает прав или сбой Discord)."
    if cleaned:
        text += f" Убрал привязок удалённых сообщений — {cleaned}."
    return text


_COMPARED = ("type", "description", "default_member_permissions", "dm_permission", "options")


def commands_to_push(desired: list[dict], existing: list[dict]) -> list[dict]:
    """Какие из наших команд в Discord отсутствуют или отличаются (чужие команды не трогаем)."""
    def norm(c: dict) -> tuple:
        return tuple(str(c.get(k) if c.get(k) not in (None, []) else "") for k in _COMPARED)
    have = {str(c.get("name")): norm(c) for c in existing}
    return [d for d in desired if have.get(str(d["name"])) != norm(d)]


async def _wait_hermes_sync(adapter) -> None:
    """Ждём, пока Hermes закончит свою синхронизацию команд: она удаляет всё, чего нет в её списке,
    и, идя параллельно, стёрла бы только что досланные наши команды."""
    import asyncio
    for _ in range(5):  # задачу могут пересоздать при переподключении
        task = getattr(adapter, "_post_connect_task", None)
        if task is None or task.done():
            return
        await asyncio.wait({task}, timeout=900)


async def sync_app_commands(bot, commands, adapter=None) -> None:
    """Hermes синхронизирует команды до подключения плагинов, поэтому свои добавляем сами —
    после его синхронизации, по одной (upsert), без массовой перезаливки чужих команд."""
    import logging
    log = logging.getLogger(__name__)
    try:
        await _wait_hermes_sync(adapter)
        existing = await bot.http.get_global_commands(bot.application_id)
        push = commands_to_push([c.to_dict(bot.tree) for c in commands], existing)
        for payload in push:
            await bot.http.upsert_global_command(bot.application_id, payload)
        if push:
            log.info("barman: app commands pushed: %s", [p["name"] for p in push])
    except Exception:  # noqa: BLE001
        log.warning("barman: command sync failed", exc_info=True)
