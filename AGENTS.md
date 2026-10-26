# AGENTS.md

Инструкция для ИИ-агентов и разработчиков. Прочитай целиком перед правками.

## Что это

**Бармен** — Discord-бот на [Hermes Agent](https://github.com/NousResearch/hermes-agent) (Nous Research), профиль Hermes `barmen`, плагин `barman/`.

Что умеет: роли по реакциям в канале раздачи ролей. Участник ставит любую реакцию под привязанным сообщением → получает роль; снимает → роль снята. Одно сообщение = одна роль.

Управление — только для тех, у кого есть право «Управлять ролями» (остальные команды не видят), только в канале ролей, ответы бота видит только вызвавший (ephemeral):

- ПКМ по сообщению → Приложения → «Привязать роль» / «Отвязать роль». В меню только роли, которые модератор может привязать, а бот — выдать; после привязки бот ставит ✅ под сообщением. Отвязка не снимает уже выданные роли.
- `/роли` — список привязок с пометкой ⚠️ и подсказкой, если роль удалена, выше бота, стала модераторской или сообщение удалено
- `/синк` — выдать роли тем, кто уже стоит в реакциях; заодно убирает привязки удалённых сообщений

Ещё бармен раз в день в **21:00 по Москве** постит в заданный канал выжимку DTF (`barman/digest.py`): 10 самых популярных постов за день по лайкам + комментариям — сначала редакционные новости, затем добор популярными постами; к каждому пересказ ИИ (OpenRouter, по умолчанию `anthropic/claude-haiku-4.5`; при сбое — описание от DTF) и упоминание одного участника. Первый выпуск — сразу при первом запуске; время последнего выпуска хранится в `/root/barmen-hermes/barman/digest.json`, перезапуски не дублируют пост, пропущенные 21:00 догоняются при старте.

Язык всего, что видят люди, — **русский**.

## Структура

```
barman/
  __init__.py        register(ctx): слушатели реакций и команды Discord (discord.py внутри Hermes)
  reaction_roles.py  чистая логика: привязки, проверки, синхронизация команд — без импорта discord
  digest.py          чистая логика ежедневной выжимки DTF: отбор, пересказ, расписание — без discord и сети
  comments.py        чистая логика редких реплик на сообщения завсегдатаев — без discord и сети
  plugin.yaml        манифест плагина (kind: standalone)
tests/               pytest, без сети и без discord.py
deploy/update.sh     выкатка на сервер (BARMAN_TARGET=prod — бар, test — тестовый бот)
deploy/render_soul.py сборка SOUL.md: заглушки эмодзи → <:имя:ID>
persona/            личности бармена: SOUL.sibiya.md, SOUL.fidel.md, SOUL.angmar.md
```

## Разработка

```bash
~/.local/bin/uv venv -p 3.12 .venv && ~/.local/bin/uv pip install -p .venv/bin/python -e ".[dev]"
.venv/bin/pytest -q            # все тесты зелёные перед коммитом
```

- **TDD:** сначала падающий тест, потом код. Логику выносить в `reaction_roles.py` и тестировать там.
- Импорты внутри плагина — **только относительные** (`from .reaction_roles import …`): Hermes грузит папку как `hermes_plugins.barman`.
- `discord` импортируется только внутри фабрики (его даёт Hermes). Модуль под `from __future__ import annotations`, поэтому тип параметра контекстного меню задаётся объектом (`callback.__annotations__[...] = discord.Message`).
- В Discord у бота только команды бармена (`/роли`, `/синк`, «Привязать/Отвязать роль»). Hermes свои команды не регистрирует (`DISCORD_COMMAND_SYNC_POLICY=off`), а бармен при старте (`sync_app_commands`) перезаписывает список своими, если там есть чужие, иначе досылает недостающие по одной. Массовый `tree.sync()` не использовать — он зальёт ~70 команд Hermes.
- ИИ бармена (Hermes) разговаривает только с теми, кто в `DISCORD_ALLOWED_USERS` (секрет `BARMAN_AI_USERS`, ID через запятую; нет секрета — `0`, ни с кем), только в `DISCORD_ALLOWED_CHANNELS` (секрет `BARMAN_AI_CHANNELS`) и только по упоминанию. Без списка пользователей Hermes пускает всех из `DISCORD_ALLOWED_CHANNELS` — поэтому `0`, а не пусто.
- Служебные команды Hermes (`/model`, `/update`, `/restart`, навыки…) закрыты для всех, даже для пущенных к разговору: в `config.yaml` `platforms.discord.extra.allow_admin_from` и `group_allow_admin_from` = `0` (админов нет) — остаются только `/help` и `/whoami`. Личка выключена: `dm_policy: disabled`. Выкатка ставит эти замки через `hermes config set`, проверяет их и только потом открывает доступ; не встали — стоп.
- Отвечает прямо в канале, без веток (`DISCORD_AUTO_THREAD=false`), и в ветках тоже только по упоминанию (`DISCORD_THREAD_REQUIRE_MENTION=true`, иначе в ветке Hermes отвечает на всё подряд), реплаем на сообщение того, кто обратился — пингуется только он (`DISCORD_REPLY_TO_MODE=first`, пинги @user/@role/@everyone в тексте ответа выключены). Домашнего канала нет (`DISCORD_HOME_CHANNEL=0`): служебные сообщения Hermes никуда не уходят, подсказки «/sethome» нет. Дописали, пока он думает, — отвечает отдельно, без служебных плашек (`display.busy_input_mode: queue`, `HERMES_GATEWAY_BUSY_ACK_ENABLED=false`).
- Реплики без обращения (`barman/comments.py`, не Hermes): на сообщения людей из секрета `BARMAN_COMMENT_USERS` в канале `BARMAN_AI_CHANNELS` бармен изредка отвечает одной фразой — шанс `BARMAN_COMMENT_CHANCE` (0.1), не чаще раза в `BARMAN_COMMENT_COOLDOWN_MIN` (60) минут, реплаем без пинга, голосом из `SOUL.md`; модель — `BARMAN_AI_MODEL`. Не реагирует на обращения к себе (их отвечает Hermes), ссылки, команды и короткое; модель может промолчать (SKIP). Нет секрета — выключено.
- Инструментов у ИИ в Discord нет (`platform_toolsets.discord: []`) — не включать: с инструментом ИИ дотянется до `.env` с ключами.
- Личность — `persona/SOUL.<имя>.md` (`sibiya`, `fidel`, `angmar`), выбирается секретом `BARMAN_SOUL`. Переключить: `gh secret set BARMAN_SOUL --body fidel` и Actions → deploy → Run workflow. Новая личность — новый файл в `persona/` с теми же неизменными правилами (их проверяет тест) и эмодзи только заглушками. Эмодзи сервера в личности — заглушки `{{emoji:peka}}`; выкатка подставляет `<:peka:ID>` из секрета `BARMAN_EMOJI` (`peka=ID,neponi=ID,…`), ID в репо не кладём (`deploy/render_soul.py`).
- Секреты только в `.env` профиля на сервере. В репозитории (он публичный) — никаких токенов, ID и ключей.

## Известные ограничения (приняты для маленького сервера)

- Выжимка DTF берёт неофициальный API `api.dtf.ru/v2.8/timeline?sorting=day` (лента «популярное за день», ~130 постов). Сменится API — выпуск упадёт (3 попытки раз в 10 минут, потом пропуск до завтра), смотреть `agent.log`. Текст DTF и ответ ИИ — чужие данные: из них вырезаются все упоминания, пингуется только `BARMAN_DIGEST_USER`.

- Снятие реакции и `/синк` перечисляют всех, кто поставил реакции на привязанных сообщениях (точечного запроса «стоит ли реакция у X» в API нет). На больших сообщениях это много запросов и риск rate limit.
- Очистка реакций модератором («Remove All Reactions» или один эмодзи): Discord не сообщает, чьи реакции ушли. Бармен проверяет всех, у кого роль сейчас есть (по кешу участников — нужен intent Server Members; кого нет в кеше, того не трогаем), одним снимком реакций, а кандидатов на снятие перепроверяет по одному (`revoke_after_clear`). На роли с сотнями участников это много запросов.
- `/синк` должен уложиться в 15 минут (срок жизни interaction), иначе итог не придёт.
- При сбое Discord во время проверки реакций роль **не** снимается (fail-closed) — лучше лишняя роль, чем отнятая.

## Ветки и мерж

- Любое изменение — в отдельной ветке от свежего `main` (`feat/…`, `fix/…`, `docs/…`, `chore/…`), в `main` только через PR.
- **Напрямую коммитить, пушить или вливать в `main` нельзя никому**, включая владельца (ruleset «main: только через PR…» + защита ветки).
- **Любой PR требует апрува владельца кода** (@Sibiya666, `.github/CODEOWNERS`); новый push в PR сбрасывает апрув. Чужой PR вливается только после апрува владельца.
- **Свои PR владелец вливает сам** в обход апрува (одобрить собственный PR GitHub не даёт): кнопка «Merge without waiting for requirements» или `gh pr merge <N> --admin --squash`. Тесты этим не обойти — `main` требует зелёный `pytest` и от админа.
- **ИИ-агенты PR не вливают** (ни `--admin`, ни `--auto`): создают PR, доводят до зелёных тестов и сообщают владельцу номер PR.

## Две ветки: test и main

- **`test` → тестовый бот** (`barmen-test`, секреты `TEST_*`): каждый push в `test` выкатывает тестового бота. **`main` → бармен «Паба»**.
- Порядок: ветка фичи от свежего **`test`** → PR в `test` (squash) → проверка вживую на тестовом сервере → **PR `test` → `main`**.
- PR `test` → `main` вливается **обычным merge, без squash** (`gh pr merge <N> --admin --merge`): иначе истории разойдутся и следующий PR из `test` снова покажет уже влитое и даст конфликты.
- Срочная правка прямо в `main` (мимо теста) — после мержа сразу влить `main` обратно в `test` (`git switch test && git merge origin/main && git push`), чтобы тест не отставал.

## Как изменение попадает в main

1. Локально: ревью пройдено, все замечания исправлены, `.venv/bin/pytest -q` зелёный.
2. `gh pr create --fill --base test` — PR в `test`; проверили на тестовом боте — `gh pr create --base main --head test` (без автомержа: с обязательным апрувом он всё равно не сработает).
3. GitHub Actions гоняет `pytest` на PR (`.github/workflows/tests.yml`). Красный — чинить в той же ветке.
4. Конфликт с `main`: `git fetch && git merge origin/main`, поправить, `pytest`, push.
5. Владелец вливает PR: фичу в `test` — `--squash`, `test` в `main` — `--merge` (или кнопкой с тем же способом). Ветка фичи на GitHub удаляется сама; `test` — нет: её защищает ruleset «test: не удалять и не перезаписывать» (нельзя удалить и force-push; обычные push и PR — можно).
6. После мержа GitHub сам выкатывает на VPS (`.github/workflows/deploy.yml`: тесты → `deploy/update.sh`). Руками — только `deploy/update.sh <IP>` из свежего `main`.

## Неснимаемые правила

1. Роли с правами модерации/администрирования по реакции не выдаются никогда (`is_privileged`), даже если их привязали.
2. Привязать можно только роль ниже собственной высшей роли (кроме владельца сервера).
3. Команды управления — только с правом «Управлять ролями».

## Где работает и как выкатывать

- Прод: VPS (IP знает владелец, в публичный репо не писать). Отдельный Docker-контейнер **`barmen`** (образ `nousresearch/hermes-agent`, `--memory 768m`, `restart unless-stopped`), данные — `/root/barmen-hermes` → `/opt/data` (владелец uid **10000**). На том же сервере в своём контейнере `hermes` живут другие боты — их не трогать.
- Вход: `ssh -i ~/.ssh/companion_vps root@<IP>`.
- Выкатка: `deploy/update.sh <IP>` — rsync плагина в `/root/barmen-hermes/plugins/barman` и `docker restart barmen`.
- **Тестовый бармен** — отдельный бот (своё приложение Discord и токен), контейнер `barmen-test`, данные `/root/barmen-test-hermes`. Выкатывается из ветки **`test`**: каждый push в неё — тесты и выкатка на тестового бота (`.github/workflows/deploy-test.yml`), как `main` → бар. Вручную — Actions → **deploy-test** → Run workflow. Настройки — те же секреты с префиксом `TEST_` (`TEST_DISCORD_BOT_TOKEN`, `TEST_BARMAN_AI_USERS`, `TEST_BARMAN_AI_CHANNELS`, `TEST_BARMAN_SOUL`, …). Первая выкатка создаёт его сама: `config.yaml` и ключ OpenRouter копируются с бара на сервере, токен — из `TEST_DISCORD_BOT_TOKEN`. Те же замки Hermes, что у бара. `update.sh` выбирает цель по `BARMAN_TARGET` (`prod` | `test`).
- Автовыкатка: после каждого мержа в `main` (и вручную — Actions → deploy → Run workflow). Секреты репозитория: `VPS_HOST`, `VPS_SSH_KEY` (отдельный deploy-ключ, не `companion_vps`), `VPS_KNOWN_HOSTS`. Без них выкатка пропускается с предупреждением.
- Выкатка сама выставляет замки Hermes: в `.env` `DISCORD_COMMAND_SYNC_POLICY=off`, `DISCORD_ALLOWED_ROLES=`, `DISCORD_ALLOWED_USERS` из `BARMAN_AI_USERS` (иначе `0`); в `config.yaml` — админов нет, личка выключена (см. `deploy/update.sh`). Секреты ИИ: `BARMAN_AI_USERS`, `BARMAN_AI_CHANNELS`, `BARMAN_SOUL`, `BARMAN_EMOJI`, `BARMAN_AI_MODEL` (модель разговора в OpenRouter, ставится в `model.default`; сейчас `anthropic/claude-haiku-5.5` — дешёвая; дорогие модели не ставить без нужды: каждое упоминание бармена — запрос).
- Выжимка DTF: секреты `BARMAN_DIGEST_CHANNEL` (ID канала), `BARMAN_DIGEST_USER` (имя пользователя Discord без @, бот находит его на сервере сам), `BARMAN_DIGEST_MODEL` (необязательно). Выключить, не удаляя код: секрет `BARMAN_DIGEST_CHANNEL=off` + deploy (канал в `.env` очищается, в логе «DTF digest disabled»); включить — вернуть ID канала. **Сейчас выключена.** Ключ ИИ — `OPENROUTER_API_KEY` из `.env`.
- Канал ролей: секрет `BARMAN_ROLES_CHANNEL` (ID канала). Выкатка вписывает его в `.env` на сервере — сменить канал = поменять секрет и запустить deploy. Секрета нет — `.env` не трогается.
- Команды в контейнере — только `docker exec -u 10000 barmen …` (от root появляются root-файлы и бот ломается).
- Настройки: `/root/barmen-hermes/.env` (`DISCORD_BOT_TOKEN`, `BARMAN_ROLES_CHANNEL`, `DISCORD_ALLOWED_CHANNELS`, `OPENROUTER_API_KEY`), `config.yaml` (`plugins.enabled: [barman]`, `platform_toolsets.discord: []`).
- Привязки — `/root/barmen-hermes/barman/bindings.json`. Логи — `/root/barmen-hermes/logs/{agent,errors}.log`, `docker logs barmen`.
- Один токен — один процесс: не запускать бармена ещё где-то (локально, в другом контейнере) одновременно с сервером.
