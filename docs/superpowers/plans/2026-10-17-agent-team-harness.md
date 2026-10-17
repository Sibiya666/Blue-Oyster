# Обвязка для команды агентов (A1) — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Особенность этого плана.** У каждой задачи указан исполнитель. **Исполнитель: заказчик** — файл пишет заказчик руками по скелету из плана, Claude проверяет шагом «Проверка». **Исполнитель: Claude** — Claude пишет файл целиком, код приведён в плане. **Исполнитель: агенты** — работу делает команда субагентов по протоколу эстафеты. Задачи заказчика нельзя делегировать субагентам: это противоречит цели проекта (спека, раздел 1 и 12). Поэтому план исполняется inline через superpowers:executing-plans.

**Goal:** Собрать внутри Claude Code команду из четырёх агентов с принудительными гейтами и прогнать через неё две задачи для Discord-бота, при этом роли, hooks и гейты заказчик пишет своими руками.

**Architecture:** Роли — markdown-файлы в `.claude/agents/`, артефакты — файлы в `docs/specs/` и `docs/reports/`, гейты — shell-скрипты в `team/gates/`, подключённые через hooks в `.claude/settings.json`. Главная сессия Claude Code вызывает агентов по шаблонам из `team/handoffs/` по просьбе заказчика. Всё вне `.claude/` не зависит от Claude Code.

**Tech Stack:** bash + jq (гейты), Claude Code subagents и hooks, Node 22 / TypeScript / discord.js v14 / vitest / Biome / Docker (бот, пишут агенты).

**Spec:** `docs/superpowers/specs/2026-10-17-agent-team-harness-design.md`

## Global Constraints

- Node 22 через `.nvmrc`; TypeScript strict; ESM; npm. Команды `npm test` (vitest) и `npm run lint` (Biome) обязаны существовать: на них опираются гейты.
- discord.js v14; intents `Guilds` и `GuildMessageReactions`; partials для `Message`, `Channel`, `Reaction`, `User`.
- Логика «эмодзи → роль, добавить или снять» в чистых функциях без импорта discord.js.
- Токен только через `DISCORD_TOKEN` в `.env` (в `.gitignore`); в репо `.env.example`.
- Имена артефактов: `docs/specs/NNN-<slug>.md`, `docs/reports/NNN-<slug>-test.md`, `docs/reports/NNN-<slug>-deploy.md`.
- Заголовки шаблонов на русском, точно как в спеке (раздел 6): по ним работают гейты.
- Скрипты гейтов читают из stdin только `hook_event_name`, `agent_type`, `agent_id`, `cwd`, `tool_input.file_path`, `tool_input.subagent_type`, `tool_input.prompt`. Ничего специфичного для Claude Code внутри скриптов.
- `SubagentStop`: код 0 — пропустить, код 2 + stderr — вернуть. `PreToolUse`: код 0 без вывода — разрешить, JSON `hookSpecificOutput.permissionDecision: "deny"` — запретить.
- Счётчик попыток: третий провал гейта выпускает агента с кодом 0 и записью `limit` в лог.
- `.team/` в `.gitignore`; там `gate.log` и `attempts/`.
- Агенты не коммитят. Заказчик коммитит после каждого шага.
- Ни заказчик, ни Claude не пишут код бота руками. Если агенты не справляются, чинится обвязка.
- Лимит раундов тестирования на задачу: три.

---

## Карта файлов

| Файл | Ответственность | Исполнитель |
|---|---|---|
| `.nvmrc` | версия Node | заказчик |
| `AGENTS.md`, `CLAUDE.md` | правила проекта для агентов | заказчик |
| `team/README.md` | протокол эстафеты для человека | заказчик |
| `team/templates/spec.md`, `test-report.md`, `deploy-report.md` | форма артефактов | заказчик |
| `team/gates/fixtures/*` | примеры артефактов для тестов гейтов | Claude |
| `team/gates/test.sh` | тесты гейтов | Claude |
| `team/gates/common.sh` | чтение stdin, лог, счётчик, dry-run | заказчик |
| `team/gates/path-policy.sh` | PreToolUse на Edit/Write: кому куда можно писать | заказчик |
| `team/gates/analyst.sh`, `developer.sh`, `tester.sh`, `devops.sh` | SubagentStop: проверка результата роли | заказчик |
| `team/gates/start-policy.sh` | PreToolUse на Agent: можно ли роли стартовать | заказчик |
| `.claude/agents/analyst.md`, `developer.md`, `tester.md`, `devops.md` | роли | заказчик |
| `team/handoffs/analyst.md`, `developer.md`, `tester.md`, `devops.md` | тексты вызова ролей | заказчик |
| `.claude/settings.json` | проводка hooks, permissions.allow | заказчик |
| всё в `src/`, `tests/`, `Dockerfile`, `compose.yaml`, `.github/` | бот | агенты |

---

## Фаза 0. Предпосылки

### Task 1: Окружение разработчика

**Исполнитель:** заказчик.

**Files:**
- Create: `.nvmrc`

- [ ] **Step 1: Поставить Node 22 и сделать его умолчанием**

```bash
nvm install 22
nvm alias default 22
```

Node 14 по умолчанию сломает `npm test` и в агентах, и в гейтах: shell-состояние между вызовами Bash не сохраняется, каждый вызов берёт Node из PATH. Старые проекты с собственным `.nvmrc` продолжат работать через `nvm use` в их директориях.

- [ ] **Step 2: Поставить jq**

```bash
brew install jq
```

- [ ] **Step 3: Запустить Docker Desktop и проверить**

Run: `docker info >/dev/null 2>&1 && echo ok || echo "docker не запущен"`
Expected: `ok`

- [ ] **Step 4: Создать `.nvmrc`**

Содержимое файла, одна строка:

```
22
```

- [ ] **Step 5: Перезапустить VS Code**

Расширение Claude Code наследует PATH от VS Code; без перезапуска hooks увидят Node 14.

- [ ] **Step 6: Проверка**

Run в новой сессии Claude Code (попросите Claude выполнить):

```bash
node --version; jq --version; docker info >/dev/null 2>&1 && echo docker-ok
```

Expected: `v22.x.x`, `jq-1.x`, `docker-ok`.

- [ ] **Step 7: Commit**

```bash
git add .nvmrc
git commit -m "chore: pin Node 22"
```

### Task 2: Discord и GitHub

**Исполнитель:** заказчик.

**Files:**
- Create: `.env` (в `.gitignore`, не коммитится)

- [ ] **Step 1: Создать приложение Discord**

На https://discord.com/developers/applications: New Application → вкладка Bot → Reset Token, скопировать токен. Привилегированные intents (Presence, Server Members, Message Content) включать не нужно.

- [ ] **Step 2: Пригласить бота на тестовый сервер**

Вкладка OAuth2 → URL Generator: scope `bot`; permissions `View Channels`, `Manage Roles`, `Add Reactions`, `Read Message History`. Открыть ссылку, выбрать тестовый сервер, где вы администратор.

- [ ] **Step 3: Поднять роль бота в иерархии**

Настройки сервера → Роли: перетащить роль бота выше всех ролей, которые он будет раздавать. Иначе Discord вернёт `Missing Permissions`.

- [ ] **Step 4: Создать `.env`**

```
DISCORD_TOKEN=вставьте_токен
```

- [ ] **Step 5: Проверка, что токен не попадёт в git**

Run: `git check-ignore .env && echo ignored`
Expected: `.env` и `ignored`.

- [ ] **Step 6: Создать пустой репозиторий на GitHub и подключить**

```bash
git remote add origin git@github.com:<user>/bot-role.git
git push -u origin main
```

Expected: ветка `main` на GitHub с двумя коммитами.

---

## Фаза 1. Основа

### Task 3: AGENTS.md и CLAUDE.md

**Исполнитель:** заказчик, по наброску.

**Files:**
- Create: `AGENTS.md`
- Create: `CLAUDE.md`

**Interfaces:**
- Produces: правила, которые читают все четыре роли и главная сессия. Разделы и команды из этого файла используют шаблоны передачи (Task 16) и промпты ролей (Task 15).

- [ ] **Step 1: Написать `AGENTS.md` по наброску**

Не длиннее 100 строк. Разделы и что в них должно быть:

```markdown
# bot-role

<!-- Назначение: два предложения. Discord-бот, роли по реакциям. Собирается командой агентов. -->

## Стек и команды
<!-- Node 22 (.nvmrc), TypeScript strict, ESM, npm.
     npm test — vitest; npm run lint — Biome (lint + format check); npm run build — tsc.
     Запуск локально: npm run dev (tsx) или docker compose up. -->

## Discord
<!-- discord.js v14. Intents: Guilds, GuildMessageReactions. Partials: Message, Channel, Reaction, User.
     Токен: DISCORD_TOKEN из .env. В репо только .env.example. -->

## Архитектура
<!-- Логика «эмодзи → роль, добавить/снять» — чистые функции в src/core/ без импорта discord.js.
     Адаптер к Discord — тонкий слой в src/discord/. Unit-тесты без сети. -->

## Артефакты команды
<!-- docs/specs/NNN-<slug>.md — спеки (аналитик).
     docs/reports/NNN-<slug>-test.md — отчёты тестировщика.
     docs/reports/NNN-<slug>-deploy.md — отчёты девопса.
     Шаблоны в team/templates/. -->

## Правила для агентов
<!-- Не коммитить. Не задавать вопросов по ходу — только в итоговом отчёте.
     Заканчивать работу коротким отчётом по форме из шаблона передачи.
     Если гейт вернул с ошибкой — исправить причину; после трёх попыток остановиться и описать проблему. -->

## Процесс
<!-- Одна строка: протокол эстафеты описан в team/README.md. -->
```

Замените комментарии на текст. Комментарии в итоговом файле не оставляйте.

- [ ] **Step 2: Написать `CLAUDE.md`**

Одна строка:

```
@AGENTS.md
```

- [ ] **Step 3: Проверка**

Run: `wc -l AGENTS.md; grep -c '<!--' AGENTS.md`
Expected: первое число меньше 100, второе `0`.

В новой сессии Claude Code выполнить `/context` и убедиться, что в списке Memory files есть `CLAUDE.md`.

Ревью Claude по чеклисту: есть команды `npm test` и `npm run lint`; названы intents и partials; есть правило про чистые функции без discord.js; описаны три вида артефактов с точными шаблонами имён; есть правило «не коммитить».

- [ ] **Step 4: Commit**

```bash
git add AGENTS.md CLAUDE.md
git commit -m "docs: project rules for agents"
```

### Task 4: Шаблоны артефактов

**Исполнитель:** заказчик.

**Files:**
- Create: `team/templates/spec.md`
- Create: `team/templates/test-report.md`
- Create: `team/templates/deploy-report.md`

**Interfaces:**
- Produces: точные заголовки `## ...`, по которым работают гейты `analyst.sh`, `tester.sh`, `devops.sh` и фикстуры Task 6. Менять заголовки после этой задачи нельзя без правки гейтов и фикстур.

- [ ] **Step 1: Написать `team/templates/spec.md`**

Заголовки обязательны и должны совпадать посимвольно. Под каждым заголовком допишите одну строку-подсказку в HTML-комментарии, что сюда писать аналитику.

```markdown
---
task: NNN-slug
status: draft
---
# Название задачи

## Цель

## Пользовательские сценарии

## Критерии приёмки
- AC-1:

## Вне скоупа

## Технические ограничения

## Открытые вопросы
```

Правило для «Открытые вопросы»: если вопросов нет, в секции ровно одно слово `Нет`. Запишите это правило подсказкой в шаблоне.

- [ ] **Step 2: Написать `team/templates/test-report.md`**

```markdown
---
task: NNN-slug
round: 1
verdict: FAIL
---
## Проверка критериев
| AC | Результат | Доказательство |
|---|---|---|
| AC-1 | pass | tests/<file>.test.ts: "<имя теста>" |

## Дефекты
- D-1: <что не так>. Шаги: 1) ... 2) ... Ожидалось: ... Получилось: ...

## Добавленные тесты
```

Подсказки: `Результат` принимает `pass`, `fail`, `manual`; `verdict` — `PASS` или `FAIL`; один файл на задачу, новый раунд перезаписывает его и увеличивает `round`.

- [ ] **Step 3: Написать `team/templates/deploy-report.md`**

```markdown
---
task: NNN-slug
status: ok
---
## Сборка

## Локальный запуск

## Переменные окружения

## CI

## Отложено
```

- [ ] **Step 4: Проверка**

Run:

```bash
grep -c '^## ' team/templates/spec.md team/templates/test-report.md team/templates/deploy-report.md
```

Expected: `spec.md:6`, `test-report.md:3`, `deploy-report.md:5`.

- [ ] **Step 5: Commit**

```bash
git add team/templates
git commit -m "docs: artifact templates for the agent team"
```

### Task 5: Протокол эстафеты для человека

**Исполнитель:** заказчик, по наброску.

**Files:**
- Create: `team/README.md`

- [ ] **Step 1: Написать `team/README.md`**

Разделы:

```markdown
# Команда агентов: как пользоваться

## Роли
<!-- таблица: роль — вход — выход, из спеки раздел 5 -->

## Эстафета по шагам
<!-- семь шагов из спеки раздел 8 с точными фразами:
     «Запусти analyst: <описание>»
     «Запусти developer на NNN»
     «Запусти tester на NNN»
     «Запусти developer с отчётом NNN-<slug>-test.md»
     «Запусти devops на NNN»
     после каждого шага: посмотреть результат, закоммитить -->

## Состояние задачи по файлам
<!-- таблица из спеки раздел 6.4 -->

## Гейты
<!-- что проверяет каждый, где лог (.team/gate.log), лимит попыток 3 -->

## Если что-то пошло не так
<!-- гейт зациклился: смотреть .team/gate.log и .team/attempts/
     агент не стартует: проверить status: approved и пустые «Открытые вопросы»
     нужно продолжить агента с ответами: сказать «продолжи analyst: <ответы>» -->
```

- [ ] **Step 2: Проверка**

Run: `grep -c '<!--' team/README.md`
Expected: `0`.

Ревью Claude: все пять фраз эстафеты присутствуют; таблица состояний совпадает со спекой.

- [ ] **Step 3: Commit**

```bash
git add team/README.md
git commit -m "docs: relay protocol for the agent team"
```

---

## Фаза 2. Гейты по TDD

Порядок: сначала Claude пишет фикстуры и тесты (красные), потом заказчик пишет скрипты до зелёного. Запуск всех тестов: `bash team/gates/test.sh`; одного блока: `bash team/gates/test.sh path-policy`.

### Task 6: Фикстуры для тестов гейтов

**Исполнитель:** Claude.

**Files:**
- Create: `team/gates/fixtures/spec-good.md`
- Create: `team/gates/fixtures/spec-draft.md`
- Create: `team/gates/fixtures/spec-open-questions.md`
- Create: `team/gates/fixtures/spec-no-ac.md`
- Create: `team/gates/fixtures/spec-missing-section.md`
- Create: `team/gates/fixtures/report-test-pass.md`
- Create: `team/gates/fixtures/report-test-fail.md`
- Create: `team/gates/fixtures/report-test-missing-ac.md`
- Create: `team/gates/fixtures/report-test-bad-verdict.md`
- Create: `team/gates/fixtures/report-deploy-ok.md`
- Create: `team/gates/fixtures/package.json`
- Create: `team/gates/fixtures/Dockerfile`
- Create: `team/gates/fixtures/ci.yml`

**Interfaces:**
- Produces: идентификатор задачи во всех фикстурах `001-demo`; спека ссылается на `AC-1` и `AC-2`. Тесты в Task 7 копируют фикстуры под именами `docs/specs/001-demo.md`, `docs/reports/001-demo-test.md`, `docs/reports/001-demo-deploy.md`.

- [ ] **Step 1: `spec-good.md`**

```markdown
---
task: 001-demo
status: approved
---
# Демо-задача

## Цель
Проверить гейты на правильной спеке.

## Пользовательские сценарии
- Пользователь делает X и видит Y.

## Критерии приёмки
- AC-1: при X происходит Y.
- AC-2: при Z ничего не происходит.

## Вне скоупа
- Всё остальное.

## Технические ограничения
- Нет.

## Открытые вопросы
Нет
```

- [ ] **Step 2: `spec-draft.md`** — копия `spec-good.md`, но `status: draft`.

- [ ] **Step 3: `spec-open-questions.md`** — копия `spec-good.md`, но секция «Открытые вопросы»:

```markdown
## Открытые вопросы
- Какой эмодзи считать умолчанием?
```

- [ ] **Step 4: `spec-no-ac.md`** — копия `spec-good.md`, но секция «Критерии приёмки» пустая (заголовок есть, строк `- AC-` нет).

- [ ] **Step 5: `spec-missing-section.md`** — копия `spec-good.md` без заголовка и тела «## Открытые вопросы».

- [ ] **Step 6: `report-test-pass.md`**

```markdown
---
task: 001-demo
round: 1
verdict: PASS
---
## Проверка критериев
| AC | Результат | Доказательство |
|---|---|---|
| AC-1 | pass | tests/demo.test.ts: "does Y on X" |
| AC-2 | pass | tests/demo.test.ts: "ignores Z" |

## Дефекты
Нет

## Добавленные тесты
- tests/demo.test.ts
```

- [ ] **Step 7: `report-test-fail.md`** — как `report-test-pass.md`, но `verdict: FAIL`, строка AC-2 с результатом `fail`, в «Дефекты»:

```markdown
- D-1: при Z происходит Y. Шаги: 1) сделать Z. Ожидалось: ничего. Получилось: Y.
```

- [ ] **Step 8: `report-test-missing-ac.md`** — как `report-test-pass.md`, но в таблице только строка AC-1.

- [ ] **Step 9: `report-test-bad-verdict.md`** — как `report-test-pass.md`, но `verdict: MAYBE`.

- [ ] **Step 10: `report-deploy-ok.md`**

```markdown
---
task: 001-demo
status: ok
---
## Сборка
docker build -t bot-role .

## Локальный запуск
docker compose up

## Переменные окружения
DISCORD_TOKEN

## CI
.github/workflows/ci.yml: lint, test, build.

## Отложено
Хостинг.
```

- [ ] **Step 11: `package.json`**

```json
{
  "name": "gate-fixture",
  "private": true,
  "scripts": {
    "test": "exit 0",
    "lint": "exit 0"
  }
}
```

- [ ] **Step 12: `Dockerfile`**

```dockerfile
FROM node:22-alpine
CMD ["node", "-v"]
```

- [ ] **Step 13: `ci.yml`**

```yaml
name: ci
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
```

- [ ] **Step 14: Commit**

```bash
git add team/gates/fixtures
git commit -m "test: fixtures for gate tests"
```

### Task 7: Тесты гейтов

**Исполнитель:** Claude.

**Files:**
- Create: `team/gates/test.sh`

**Interfaces:**
- Consumes: фикстуры Task 6.
- Produces: контракт для скриптов заказчика. Имена скриптов: `common.sh`, `path-policy.sh`, `analyst.sh`, `developer.sh`, `tester.sh`, `devops.sh`, `start-policy.sh`. Переменные dry-run: `GATE_DRY_RUN=1`, `GATE_FAKE_LINT`, `GATE_FAKE_TEST`, `GATE_FAKE_DOCKER` (код выхода подменяемой команды). Лог: `<cwd>/.team/gate.log`, строка содержит `<gate> <agent_type> <result>`.

- [ ] **Step 1: Написать `team/gates/test.sh`**

```bash
#!/usr/bin/env bash
# Тесты гейтов. Запуск: bash team/gates/test.sh [имя-гейта]
# Каждый случай: временная директория с фикстурами, JSON на stdin, проверка кода выхода и вывода.
set -u

GATES="$(cd "$(dirname "$0")" && pwd)"
FIX="$GATES/fixtures"
ONLY="${1:-}"
PASS=0
FAIL=0
export GATE_DRY_RUN=1

want() { [ -z "$ONLY" ] || [ "$ONLY" = "$1" ]; }

new_tmp() {
  local d
  d="$(mktemp -d)"
  mkdir -p "$d/docs/specs" "$d/docs/reports" "$d/.team" "$d/.github/workflows" "$d/src" "$d/tests"
  echo "$d"
}

# hook_json <cwd> <event> [agent_type] [agent_id] [tool_name] [file_path] [subagent_type] [prompt]
hook_json() {
  jq -n --arg cwd "$1" --arg ev "$2" --arg at "${3:-}" --arg aid "${4:-}" \
        --arg tn "${5:-}" --arg fp "${6:-}" --arg st "${7:-}" --arg pr "${8:-}" '
    {hook_event_name: $ev, cwd: $cwd, session_id: "test"}
    + (if $at != "" then {agent_type: $at, agent_id: $aid} else {} end)
    + (if $tn != "" then {tool_name: $tn, tool_input: ({}
         + (if $fp != "" then {file_path: $fp} else {} end)
         + (if $st != "" then {subagent_type: $st} else {} end)
         + (if $pr != "" then {prompt: $pr} else {} end))} else {} end)'
}

# run_gate <script> <json> → RC, OUT, ERR
run_gate() {
  local out err
  out="$(mktemp)"
  err="$(mktemp)"
  printf '%s' "$2" | bash "$GATES/$1" >"$out" 2>"$err"
  RC=$?
  OUT="$(cat "$out")"
  ERR="$(cat "$err")"
  rm -f "$out" "$err"
}

check() { # check <name> <0|1> <details>
  if [ "$2" -eq 0 ]; then
    PASS=$((PASS + 1)); echo "  ok   $1"
  else
    FAIL=$((FAIL + 1)); echo "  FAIL $1"; echo "       $3"
  fi
}

expect_rc() { # expect_rc <name> <code>
  local ok=1; [ "$RC" -eq "$2" ] && ok=0
  check "$1" $ok "rc=$RC, ожидался $2; stderr: $(echo "$ERR" | head -3)"
}
expect_err_contains() { # expect_err_contains <name> <text>
  local ok=1; echo "$ERR" | grep -q -- "$2" && ok=0
  check "$1" $ok "stderr: $ERR"
}
expect_deny() { # expect_deny <name>
  local ok=1; echo "$OUT" | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null 2>&1 && ok=0
  check "$1" $ok "stdout: $OUT"
}
expect_allow() { # expect_allow <name>  — пустой stdout или JSON без deny
  local ok=0
  if [ -n "$OUT" ] && echo "$OUT" | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null 2>&1; then ok=1; fi
  check "$1" $ok "stdout: $OUT"
}
expect_log_contains() { # expect_log_contains <name> <cwd> <text>
  local ok=1; grep -q -- "$3" "$2/.team/gate.log" 2>/dev/null && ok=0
  check "$1" $ok "log: $(cat "$2/.team/gate.log" 2>/dev/null)"
}

# ---------------------------------------------------------------- analyst
if want analyst; then
  echo "analyst.sh"
  T=$(new_tmp); cp "$FIX/spec-good.md" "$T/docs/specs/001-demo.md"
  run_gate analyst.sh "$(hook_json "$T" SubagentStop analyst a1)"
  expect_rc "правильная спека проходит" 0
  expect_log_contains "пишет pass в лог" "$T" "analyst analyst pass"

  T=$(new_tmp); cp "$FIX/spec-missing-section.md" "$T/docs/specs/001-demo.md"
  run_gate analyst.sh "$(hook_json "$T" SubagentStop analyst a2)"
  expect_rc "без секции блокирует" 2
  expect_err_contains "называет недостающую секцию" "Открытые вопросы"

  T=$(new_tmp); cp "$FIX/spec-no-ac.md" "$T/docs/specs/001-demo.md"
  run_gate analyst.sh "$(hook_json "$T" SubagentStop analyst a3)"
  expect_rc "без критериев блокирует" 2
  expect_err_contains "упоминает AC" "AC"

  T=$(new_tmp)
  run_gate analyst.sh "$(hook_json "$T" SubagentStop analyst a4)"
  expect_rc "без спеки блокирует" 2
fi

# -------------------------------------------------------------- developer
if want developer; then
  echo "developer.sh"
  T=$(new_tmp); cp "$FIX/package.json" "$T/"
  export GATE_FAKE_LINT=0 GATE_FAKE_TEST=0
  run_gate developer.sh "$(hook_json "$T" SubagentStop developer d1)"
  expect_rc "зелёные lint и test проходят" 0
  expect_log_contains "пишет pass в лог" "$T" "developer developer pass"

  T=$(new_tmp)
  run_gate developer.sh "$(hook_json "$T" SubagentStop developer d2)"
  expect_rc "без package.json блокирует" 2
  expect_err_contains "упоминает package.json" "package.json"

  T=$(new_tmp); cp "$FIX/package.json" "$T/"
  export GATE_FAKE_LINT=1
  run_gate developer.sh "$(hook_json "$T" SubagentStop developer d3)"
  expect_rc "красный lint блокирует" 2
  expect_err_contains "упоминает lint" "lint"
  export GATE_FAKE_LINT=0

  T=$(new_tmp); cp "$FIX/package.json" "$T/"
  export GATE_FAKE_TEST=1
  run_gate developer.sh "$(hook_json "$T" SubagentStop developer d4)"
  expect_rc "красные тесты блокируют (попытка 1)" 2
  expect_err_contains "упоминает npm test" "npm test"
  run_gate developer.sh "$(hook_json "$T" SubagentStop developer d4)"
  expect_rc "попытка 2 всё ещё блокирует" 2
  run_gate developer.sh "$(hook_json "$T" SubagentStop developer d4)"
  expect_rc "попытка 3 выпускает по лимиту" 0
  expect_log_contains "пишет limit в лог" "$T" "developer developer limit"
  unset GATE_FAKE_LINT GATE_FAKE_TEST
fi

# ----------------------------------------------------------------- tester
if want tester; then
  echo "tester.sh"
  T=$(new_tmp); cp "$FIX/spec-good.md" "$T/docs/specs/001-demo.md"; cp "$FIX/report-test-pass.md" "$T/docs/reports/001-demo-test.md"; cp "$FIX/package.json" "$T/"
  export GATE_FAKE_TEST=0
  run_gate tester.sh "$(hook_json "$T" SubagentStop tester t1)"
  expect_rc "полный отчёт проходит" 0

  T=$(new_tmp); cp "$FIX/spec-good.md" "$T/docs/specs/001-demo.md"; cp "$FIX/report-test-fail.md" "$T/docs/reports/001-demo-test.md"; cp "$FIX/package.json" "$T/"
  run_gate tester.sh "$(hook_json "$T" SubagentStop tester t2)"
  expect_rc "отчёт с FAIL тоже проходит гейт (вердикт — не ошибка)" 0

  T=$(new_tmp); cp "$FIX/spec-good.md" "$T/docs/specs/001-demo.md"; cp "$FIX/report-test-missing-ac.md" "$T/docs/reports/001-demo-test.md"; cp "$FIX/package.json" "$T/"
  run_gate tester.sh "$(hook_json "$T" SubagentStop tester t3)"
  expect_rc "непокрытый AC блокирует" 2
  expect_err_contains "называет AC-2" "AC-2"

  T=$(new_tmp); cp "$FIX/spec-good.md" "$T/docs/specs/001-demo.md"; cp "$FIX/report-test-bad-verdict.md" "$T/docs/reports/001-demo-test.md"; cp "$FIX/package.json" "$T/"
  run_gate tester.sh "$(hook_json "$T" SubagentStop tester t4)"
  expect_rc "неверный verdict блокирует" 2
  expect_err_contains "упоминает verdict" "verdict"

  T=$(new_tmp); cp "$FIX/spec-good.md" "$T/docs/specs/001-demo.md"; cp "$FIX/package.json" "$T/"
  run_gate tester.sh "$(hook_json "$T" SubagentStop tester t5)"
  expect_rc "без отчёта блокирует" 2

  T=$(new_tmp); cp "$FIX/spec-good.md" "$T/docs/specs/001-demo.md"; cp "$FIX/report-test-pass.md" "$T/docs/reports/001-demo-test.md"; cp "$FIX/package.json" "$T/"
  export GATE_FAKE_TEST=1
  run_gate tester.sh "$(hook_json "$T" SubagentStop tester t6)"
  expect_rc "красные тесты блокируют тестировщика" 2
  unset GATE_FAKE_TEST
fi

# ----------------------------------------------------------------- devops
if want devops; then
  echo "devops.sh"
  export GATE_FAKE_DOCKER=0
  T=$(new_tmp); cp "$FIX/report-deploy-ok.md" "$T/docs/reports/001-demo-deploy.md"; cp "$FIX/Dockerfile" "$T/"; cp "$FIX/ci.yml" "$T/.github/workflows/ci.yml"
  run_gate devops.sh "$(hook_json "$T" SubagentStop devops v1)"
  expect_rc "полный набор проходит" 0

  T=$(new_tmp); cp "$FIX/report-deploy-ok.md" "$T/docs/reports/001-demo-deploy.md"; cp "$FIX/ci.yml" "$T/.github/workflows/ci.yml"
  run_gate devops.sh "$(hook_json "$T" SubagentStop devops v2)"
  expect_rc "без Dockerfile блокирует" 2
  expect_err_contains "упоминает Dockerfile" "Dockerfile"

  T=$(new_tmp); cp "$FIX/report-deploy-ok.md" "$T/docs/reports/001-demo-deploy.md"; cp "$FIX/Dockerfile" "$T/"
  run_gate devops.sh "$(hook_json "$T" SubagentStop devops v3)"
  expect_rc "без ci.yml блокирует" 2
  expect_err_contains "упоминает ci.yml" "ci.yml"

  T=$(new_tmp); cp "$FIX/Dockerfile" "$T/"; cp "$FIX/ci.yml" "$T/.github/workflows/ci.yml"
  run_gate devops.sh "$(hook_json "$T" SubagentStop devops v4)"
  expect_rc "без отчёта блокирует" 2

  T=$(new_tmp); cp "$FIX/report-deploy-ok.md" "$T/docs/reports/001-demo-deploy.md"; cp "$FIX/Dockerfile" "$T/"; cp "$FIX/ci.yml" "$T/.github/workflows/ci.yml"
  export GATE_FAKE_DOCKER=1
  run_gate devops.sh "$(hook_json "$T" SubagentStop devops v5)"
  expect_rc "упавший docker build блокирует" 2
  expect_err_contains "упоминает docker" "docker"
  unset GATE_FAKE_DOCKER
fi

# ------------------------------------------------------------ path-policy
if want path-policy; then
  echo "path-policy.sh"
  T=$(new_tmp)
  run_gate path-policy.sh "$(hook_json "$T" PreToolUse "" "" Write "$T/src/x.ts")"
  expect_allow "главная сессия пишет куда угодно"
  run_gate path-policy.sh "$(hook_json "$T" PreToolUse tester p1 Write "$T/src/x.ts")"
  expect_deny "tester не пишет в src/"
  expect_log_contains "пишет deny в лог" "$T" "path-policy tester deny"
  run_gate path-policy.sh "$(hook_json "$T" PreToolUse tester p1 Write "$T/tests/x.test.ts")"
  expect_allow "tester пишет в tests/"
  run_gate path-policy.sh "$(hook_json "$T" PreToolUse tester p1 Write "$T/docs/reports/001-demo-test.md")"
  expect_allow "tester пишет в docs/reports/"
  run_gate path-policy.sh "$(hook_json "$T" PreToolUse analyst p2 Write "$T/docs/specs/001-demo.md")"
  expect_allow "analyst пишет в docs/specs/"
  run_gate path-policy.sh "$(hook_json "$T" PreToolUse analyst p2 Write "$T/src/x.ts")"
  expect_deny "analyst не пишет в src/"
  run_gate path-policy.sh "$(hook_json "$T" PreToolUse devops p3 Edit "$T/src/index.ts")"
  expect_deny "devops не правит src/"
  run_gate path-policy.sh "$(hook_json "$T" PreToolUse devops p3 Write "$T/.github/workflows/ci.yml")"
  expect_allow "devops пишет в .github/"
  run_gate path-policy.sh "$(hook_json "$T" PreToolUse devops p3 Write "$T/Dockerfile")"
  expect_allow "devops пишет Dockerfile"
  run_gate path-policy.sh "$(hook_json "$T" PreToolUse developer p4 Write "$T/docs/specs/001-demo.md")"
  expect_deny "developer не пишет в docs/specs/"
  run_gate path-policy.sh "$(hook_json "$T" PreToolUse developer p4 Write "$T/docs/reports/001-demo-test.md")"
  expect_deny "developer не пишет в docs/reports/"
  run_gate path-policy.sh "$(hook_json "$T" PreToolUse developer p4 Write "$T/src/index.ts")"
  expect_allow "developer пишет в src/"
  run_gate path-policy.sh "$(hook_json "$T" PreToolUse developer p4 Write "$T/package.json")"
  expect_allow "developer пишет package.json"
  run_gate path-policy.sh "$(hook_json "$T" PreToolUse general-purpose p5 Write "$T/src/x.ts")"
  expect_allow "незнакомая роль проходит"
fi

# ----------------------------------------------------------- start-policy
if want start-policy; then
  echo "start-policy.sh"
  T=$(new_tmp)
  cp "$FIX/spec-good.md" "$T/docs/specs/001-demo.md"
  cp "$FIX/spec-draft.md" "$T/docs/specs/002-draft.md"
  cp "$FIX/spec-open-questions.md" "$T/docs/specs/003-open.md"
  cp "$FIX/report-test-pass.md" "$T/docs/reports/001-demo-test.md"
  cp "$FIX/report-test-fail.md" "$T/docs/reports/004-fail-test.md"

  run_gate start-policy.sh "$(hook_json "$T" PreToolUse "" "" Agent "" analyst "Напиши спеку: бот отвечает pong")"
  expect_allow "analyst стартует без условий"
  run_gate start-policy.sh "$(hook_json "$T" PreToolUse "" "" Agent "" developer "Реализуй спеку docs/specs/001-demo.md")"
  expect_allow "developer стартует на утверждённой спеке"
  run_gate start-policy.sh "$(hook_json "$T" PreToolUse "" "" Agent "" developer "Реализуй спеку docs/specs/002-draft.md")"
  expect_deny "developer не стартует на draft"
  expect_log_contains "пишет deny в лог" "$T" "start-policy developer deny"
  run_gate start-policy.sh "$(hook_json "$T" PreToolUse "" "" Agent "" developer "Реализуй спеку docs/specs/003-open.md")"
  expect_deny "developer не стартует при открытых вопросах"
  run_gate start-policy.sh "$(hook_json "$T" PreToolUse "" "" Agent "" developer "Реализуй что-нибудь")"
  expect_deny "developer не стартует без пути к спеке"
  run_gate start-policy.sh "$(hook_json "$T" PreToolUse "" "" Agent "" developer "Задача 001. Спека docs/specs/001-demo.md, отчёт docs/reports/001-demo-test.md, закрой дефекты")"
  expect_allow "developer на повторном раунде берёт путь спеки"
  run_gate start-policy.sh "$(hook_json "$T" PreToolUse "" "" Agent "" tester "Проверь спеку docs/specs/001-demo.md")"
  expect_allow "tester стартует на утверждённой спеке"
  run_gate start-policy.sh "$(hook_json "$T" PreToolUse "" "" Agent "" tester "Проверь спеку docs/specs/002-draft.md")"
  expect_deny "tester не стартует на draft"
  run_gate start-policy.sh "$(hook_json "$T" PreToolUse "" "" Agent "" devops "Отчёт docs/reports/001-demo-test.md")"
  expect_allow "devops стартует на PASS"
  run_gate start-policy.sh "$(hook_json "$T" PreToolUse "" "" Agent "" devops "Отчёт docs/reports/004-fail-test.md")"
  expect_deny "devops не стартует на FAIL"
  run_gate start-policy.sh "$(hook_json "$T" PreToolUse "" "" Agent "" devops "Сделай деплой")"
  expect_deny "devops не стартует без пути к отчёту"
  run_gate start-policy.sh "$(hook_json "$T" PreToolUse "" "" Agent "" general-purpose "Найди файл")"
  expect_allow "незнакомая роль проходит"
fi

echo
echo "passed: $PASS, failed: $FAIL"
[ "$FAIL" -eq 0 ]
```

- [ ] **Step 2: Запустить и убедиться, что всё красное**

Run: `bash team/gates/test.sh`
Expected: много строк `FAIL`, в конце `failed:` больше нуля, код выхода 1. Скриптов ещё нет, поэтому каждый `run_gate` получает «No such file».

- [ ] **Step 3: Commit**

```bash
git add team/gates/test.sh
git commit -m "test: gate tests (red)"
```

### Task 8: common.sh

**Исполнитель:** заказчик, по скелету.

**Files:**
- Create: `team/gates/common.sh`

**Interfaces:**
- Produces: переменные `HOOK_EVENT`, `AGENT_TYPE`, `AGENT_ID`, `CWD`, `TOOL_NAME`, `TOOL_FILE_PATH`, `TOOL_SUBAGENT_TYPE`, `TOOL_PROMPT`, `STATE_DIR`; функции `gate_log`, `gate_pass`, `gate_block`, `gate_deny`, `gate_allow`, `run_checked`, `latest_file`, `frontmatter_value`, `section_body`, `node_env`. Все шесть гейтов начинаются с `source "$(dirname "$0")/common.sh"`.

- [ ] **Step 1: Написать `team/gates/common.sh` по скелету**

Каждая функция описана комментарием. Замените `:` на реализацию. Подсказки по командам даны в комментариях.

```bash
#!/usr/bin/env bash
# Общие функции гейтов. Подключение в начале каждого гейта:
#   source "$(dirname "$0")/common.sh"
# Контракт: читает JSON hook-а со stdin, экспортирует переменные, даёт функции pass/block/deny/allow.
set -u

# --- 1. Вход -----------------------------------------------------------------
# Прочитать stdin целиком: HOOK_INPUT="$(cat)"
# Заполнить через jq -r '.поле // empty' <<<"$HOOK_INPUT":
#   HOOK_EVENT         ← .hook_event_name
#   AGENT_TYPE         ← .agent_type
#   AGENT_ID           ← .agent_id
#   CWD                ← .cwd, если пусто: ${CLAUDE_PROJECT_DIR:-$(pwd)}
#   TOOL_NAME          ← .tool_name
#   TOOL_FILE_PATH     ← .tool_input.file_path
#   TOOL_SUBAGENT_TYPE ← .tool_input.subagent_type
#   TOOL_PROMPT        ← .tool_input.prompt
# STATE_DIR="$CWD/.team"; mkdir -p "$STATE_DIR/attempts"
# RUN_OUTPUT=""

# --- 2. Лог и исходы ---------------------------------------------------------

gate_log() { # gate_log <gate> <result> <reason>
  # Роль для лога: role="${GATE_ROLE:-${AGENT_TYPE:--}}". Внутри субагента это AGENT_TYPE; в главной сессии
  # (start-policy) скрипт сам выставляет GATE_ROLE из tool_input.subagent_type; если ничего нет — '-'.
  # Добавить в "$STATE_DIR/gate.log" строку:
  #   "<дата UTC в формате %FT%TZ> <gate> <role> <result> <reason>"
  # Тесты ищут в логе подстроку "<gate> <role> <result>", например "developer developer limit" или "start-policy developer deny".
  :
}

gate_pass() { # gate_pass <gate>
  # gate_log "$1" pass ""; удалить файл попыток (см. gate_block); exit 0
  :
}

gate_block() { # gate_block <gate> <reason>
  # Файл попыток: "$STATE_DIR/attempts/${AGENT_TYPE}-${AGENT_ID}". Прочитать число (0, если файла нет), прибавить 1, записать.
  # Если число >= 3: gate_log "$1" limit "$2"; удалить файл; echo "гейт $1 не пройден 3 раза, остановлено по лимиту: $2" >&2; exit 0
  # Иначе: gate_log "$1" block "$2"; echo "$2" >&2; exit 2
  :
}

gate_deny() { # gate_deny <gate> <reason>
  # gate_log "$1" deny "$2"
  # Напечатать на stdout JSON (jq -n --arg r "$2"):
  #   {"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":$r}}
  # exit 0
  :
}

gate_allow() { # gate_allow <gate>
  # gate_log "$1" pass ""; exit 0 без вывода на stdout
  :
}

# --- 3. Запуск команд с подменой в тестах ------------------------------------

run_checked() { # run_checked <LABEL> <cmd...>  → код команды; вывод в RUN_OUTPUT
  # LABEL — одно из LINT, TEST, DOCKER.
  # Если GATE_DRY_RUN=1: код = значение переменной GATE_FAKE_<LABEL> (по умолчанию 0), RUN_OUTPUT="dry-run <LABEL>".
  #   Подсказка для косвенного имени: local var="GATE_FAKE_$1"; local rc="${!var:-0}"
  # Иначе: node_env; RUN_OUTPUT="$(cd "$CWD" && "${@:2}" 2>&1)"; вернуть код команды.
  :
}

# --- 4. Файлы и markdown -----------------------------------------------------

latest_file() { # latest_file <glob>  → самый свежий по mtime файл или пустая строка
  # ls -t $1 2>/dev/null | head -n 1   (glob передавать без кавычек внутри функции)
  :
}

frontmatter_value() { # frontmatter_value <file> <key>  → значение "key: value" между первой и второй строкой '---'
  # awk -v k="$2" '/^---/{c++; next} c==1 && index($0, k":")==1 {sub(/^[^:]*:[ ]*/, ""); print; exit}' "$1"
  :
}

section_body() { # section_body <file> <heading>  → текст между "## <heading>" и следующим "## " или концом файла
  # awk -v h="## $2" '$0==h{f=1; next} f && /^## /{exit} f{print}' "$1"
  :
}

node_env() {
  # Если есть "$CWD/.nvmrc" и файл "${NVM_DIR:-$HOME/.nvm}/nvm.sh": source его и выполнить nvm use --silent в $CWD.
  # Ошибки глушить: гейт не должен падать из-за nvm.
  :
}
```

- [ ] **Step 2: Проверка синтаксиса и чтения stdin**

Run:

```bash
bash -n team/gates/common.sh && echo syntax-ok
echo '{"cwd":"/tmp/x","agent_type":"tester","agent_id":"t9","tool_input":{"file_path":"/tmp/x/src/a.ts"}}' \
  | bash -c 'source team/gates/common.sh; echo "$CWD|$AGENT_TYPE|$AGENT_ID|$TOOL_FILE_PATH"'
```

Expected: `syntax-ok`, затем `/tmp/x|tester|t9|/tmp/x/src/a.ts`. Директория `/tmp/x/.team/attempts` должна появиться.

- [ ] **Step 3: Проверка frontmatter_value и section_body на фикстуре**

Run:

```bash
echo '{}' | bash -c 'source team/gates/common.sh; frontmatter_value team/gates/fixtures/spec-good.md status; section_body team/gates/fixtures/spec-good.md "Открытые вопросы"'
```

Expected: `approved`, затем `Нет`.

- [ ] **Step 4: Commit**

```bash
git add team/gates/common.sh
git commit -m "feat(gates): common helpers"
```

### Task 9: path-policy.sh

**Исполнитель:** заказчик, по скелету.

**Files:**
- Create: `team/gates/path-policy.sh`

**Interfaces:**
- Consumes: `common.sh`: `AGENT_TYPE`, `TOOL_FILE_PATH`, `CWD`, `gate_allow`, `gate_deny`.

- [ ] **Step 1: Написать `team/gates/path-policy.sh` по скелету**

```bash
#!/usr/bin/env bash
# PreToolUse на Edit|Write. Кому куда можно писать (спека, раздел 9.5).
source "$(dirname "$0")/common.sh"
GATE=path-policy

# 1. Если AGENT_TYPE пустой (главная сессия): gate_allow "$GATE".
# 2. REL — путь относительно CWD: убрать префикс "$CWD/" из TOOL_FILE_PATH (${TOOL_FILE_PATH#"$CWD/"}).
# 3. case "$AGENT_TYPE":
#      analyst)   разрешено: docs/specs/*
#      developer) запрещено: docs/specs/*, docs/reports/*; всё остальное разрешено
#      tester)    разрешено: tests/*, docs/reports/*
#      devops)    разрешено: Dockerfile*, .dockerignore, compose.yaml, .env.example, .github/*, docs/reports/*
#      *)         незнакомая роль: gate_allow
#    Подсказка: сравнение с шаблоном в bash — [[ "$REL" == docs/specs/* ]]
# 4. Разрешено → gate_allow "$GATE".
#    Запрещено → gate_deny "$GATE" "роль $AGENT_TYPE не может писать в $REL; разрешено: <список для роли>"
```

- [ ] **Step 2: Прогнать тесты блока**

Run: `bash team/gates/test.sh path-policy`
Expected: все строки `ok`, `failed: 0`.

- [ ] **Step 3: Commit**

```bash
git add team/gates/path-policy.sh
git commit -m "feat(gates): path policy for roles"
```

### Task 10: analyst.sh

**Исполнитель:** заказчик, по скелету.

**Files:**
- Create: `team/gates/analyst.sh`

- [ ] **Step 1: Написать по скелету**

```bash
#!/usr/bin/env bash
# SubagentStop для analyst: спека на месте и по форме (спека, раздел 9.4).
source "$(dirname "$0")/common.sh"
GATE=analyst

# 1. SPEC="$(latest_file "$CWD/docs/specs/*.md")"; пусто → gate_block "$GATE" "спека в docs/specs/ не найдена"
# 2. task="$(frontmatter_value "$SPEC" task)"; status="$(frontmatter_value "$SPEC" status)"
#    пусто или status не draft/approved → gate_block "$GATE" "frontmatter: нужны task и status (draft|approved)"
# 3. Для каждого заголовка из списка проверить grep -qx "## $h" "$SPEC":
#      Цель; Пользовательские сценарии; Критерии приёмки; Вне скоупа; Технические ограничения; Открытые вопросы
#    Собрать недостающие в missing; если непусто → gate_block "$GATE" "нет секции: $missing"
# 4. grep -Eq '^- AC-[0-9]+:' "$SPEC" иначе → gate_block "$GATE" "нет ни одного критерия приёмки (строки вида '- AC-1: ...')"
# 5. gate_pass "$GATE"
```

- [ ] **Step 2: Прогнать тесты блока**

Run: `bash team/gates/test.sh analyst`
Expected: `failed: 0`.

- [ ] **Step 3: Commit**

```bash
git add team/gates/analyst.sh
git commit -m "feat(gates): analyst spec gate"
```

### Task 11: developer.sh

**Исполнитель:** заказчик, по скелету.

**Files:**
- Create: `team/gates/developer.sh`

- [ ] **Step 1: Написать по скелету**

```bash
#!/usr/bin/env bash
# SubagentStop для developer: lint и тесты зелёные (спека, раздел 9.4).
source "$(dirname "$0")/common.sh"
GATE=developer

# 1. [ -f "$CWD/package.json" ] иначе → gate_block "$GATE" "нет package.json со скриптами test и lint"
# 2. jq -e '.scripts.test and .scripts.lint' "$CWD/package.json" >/dev/null иначе → тот же block
# 3. run_checked LINT npm run lint; код != 0 → gate_block "$GATE" "npm run lint упал:\n$(echo "$RUN_OUTPUT" | tail -n 40)"
# 4. run_checked TEST npm test;     код != 0 → gate_block "$GATE" "npm test упал:\n$(echo "$RUN_OUTPUT" | tail -n 40)"
# 5. gate_pass "$GATE"
# Подсказка: чтобы \n в reason стал переводом строки, используйте printf -v reason '...' или $'...'.
```

- [ ] **Step 2: Прогнать тесты блока**

Run: `bash team/gates/test.sh developer`
Expected: `failed: 0`, включая случай «попытка 3 выпускает по лимиту».

- [ ] **Step 3: Commit**

```bash
git add team/gates/developer.sh
git commit -m "feat(gates): developer lint+test gate"
```

### Task 12: tester.sh

**Исполнитель:** заказчик, по скелету.

**Files:**
- Create: `team/gates/tester.sh`

- [ ] **Step 1: Написать по скелету**

```bash
#!/usr/bin/env bash
# SubagentStop для tester: отчёт покрывает все AC и тесты зелёные (спека, раздел 9.4).
source "$(dirname "$0")/common.sh"
GATE=tester

# 1. REPORT="$(latest_file "$CWD/docs/reports/*-test.md")"; пусто → gate_block "$GATE" "отчёт docs/reports/NNN-<slug>-test.md не найден"
# 2. verdict="$(frontmatter_value "$REPORT" verdict)"; не PASS и не FAIL → gate_block "$GATE" "verdict должен быть PASS или FAIL, сейчас: '$verdict'"
# 3. task="$(frontmatter_value "$REPORT" task)"; SPEC="$CWD/docs/specs/$task.md"; нет файла → gate_block "$GATE" "спека $SPEC для task из отчёта не найдена"
# 4. Для каждого AC из спеки: grep -Eo '^- AC-[0-9]+:' "$SPEC" | grep -Eo 'AC-[0-9]+'
#      если нет строки таблицы, начинающейся с "| AC-N " в отчёте (grep -q "^| $ac " "$REPORT") → добавить в missing
#    missing непусто → gate_block "$GATE" "в отчёте нет критериев: $missing"
# 5. run_checked TEST npm test; код != 0 → gate_block "$GATE" "npm test упал:\n$(echo "$RUN_OUTPUT" | tail -n 40)"
# 6. gate_pass "$GATE"
```

- [ ] **Step 2: Прогнать тесты блока**

Run: `bash team/gates/test.sh tester`
Expected: `failed: 0`.

- [ ] **Step 3: Commit**

```bash
git add team/gates/tester.sh
git commit -m "feat(gates): tester report gate"
```

### Task 13: devops.sh

**Исполнитель:** заказчик, по скелету.

**Files:**
- Create: `team/gates/devops.sh`

- [ ] **Step 1: Написать по скелету**

```bash
#!/usr/bin/env bash
# SubagentStop для devops: отчёт, Dockerfile, сборка, CI (спека, раздел 9.4).
source "$(dirname "$0")/common.sh"
GATE=devops

# 1. REPORT="$(latest_file "$CWD/docs/reports/*-deploy.md")"; пусто → gate_block "$GATE" "отчёт docs/reports/NNN-<slug>-deploy.md не найден"
# 2. status="$(frontmatter_value "$REPORT" status)"; не ok и не failed → gate_block "$GATE" "status должен быть ok или failed"
# 3. [ -f "$CWD/Dockerfile" ] иначе → gate_block "$GATE" "нет Dockerfile"
# 4. [ -f "$CWD/.github/workflows/ci.yml" ] && grep -q '^jobs:' "$CWD/.github/workflows/ci.yml" иначе → gate_block "$GATE" "нет .github/workflows/ci.yml с секцией jobs:"
# 5. run_checked DOCKER docker build -q .; код != 0 → gate_block "$GATE" "docker build упал:\n$(echo "$RUN_OUTPUT" | tail -n 40)"
# 6. gate_pass "$GATE"
```

- [ ] **Step 2: Прогнать тесты блока**

Run: `bash team/gates/test.sh devops`
Expected: `failed: 0`.

- [ ] **Step 3: Commit**

```bash
git add team/gates/devops.sh
git commit -m "feat(gates): devops build gate"
```

### Task 14: start-policy.sh

**Исполнитель:** заказчик, по скелету.

**Files:**
- Create: `team/gates/start-policy.sh`

- [ ] **Step 1: Написать по скелету**

```bash
#!/usr/bin/env bash
# PreToolUse на Agent: можно ли роли стартовать на этом артефакте (спека, раздел 9.6).
source "$(dirname "$0")/common.sh"
GATE=start-policy

# Вспомогательная: open_questions_empty <spec> → 0, если тело секции «Открытые вопросы» после удаления
#   пробелов пустое или равно «Нет» (с точкой или без, с большой или маленькой буквы).
#   Подсказка: body="$(section_body "$1" "Открытые вопросы" | tr -d '[:space:]')"
#              case "$body" in ""|Нет|Нет.|нет|нет.) return 0;; *) return 1;; esac
#   nocasematch для кириллицы не использовать: зависит от локали.

# 1. role="$TOOL_SUBAGENT_TYPE"; GATE_ROLE="$role"   # чтобы в логе была роль, а не '-'
# 2. case "$role":
#   analyst)   gate_allow "$GATE"
#   developer|tester)
#       spec_rel="$(grep -Eo 'docs/specs/[^[:space:]]+\.md' <<<"$TOOL_PROMPT" | head -n 1)"
#       пусто → gate_deny "$GATE" "в промпте нет пути к спеке docs/specs/NNN-<slug>.md"
#       SPEC="$CWD/$spec_rel"; нет файла → gate_deny "$GATE" "спека $spec_rel не найдена"
#       status != approved → gate_deny "$GATE" "спека $spec_rel не утверждена (status: $status)"
#       для developer дополнительно: ! open_questions_empty "$SPEC" → gate_deny "$GATE" "в спеке $spec_rel остались открытые вопросы"
#       gate_allow "$GATE"
#   devops)
#       report_rel="$(grep -Eo 'docs/reports/[^[:space:]]+-test\.md' <<<"$TOOL_PROMPT" | head -n 1)"
#       пусто → gate_deny "$GATE" "в промпте нет пути к отчёту тестировщика"
#       нет файла → gate_deny; verdict != PASS → gate_deny "$GATE" "отчёт $report_rel: verdict $verdict, нужен PASS"
#       gate_allow "$GATE"
#   *) gate_allow "$GATE"
```

- [ ] **Step 2: Прогнать тесты блока и все тесты**

Run: `bash team/gates/test.sh start-policy && bash team/gates/test.sh`
Expected: оба запуска `failed: 0`, код выхода 0.

- [ ] **Step 3: Commit**

```bash
git add team/gates/start-policy.sh
git commit -m "feat(gates): start policy for roles; all gate tests green"
```

---

## Фаза 3. Роли, передачи, проводка

### Task 15: Четыре файла ролей

**Исполнитель:** заказчик, по скелетам.

**Files:**
- Create: `.claude/agents/analyst.md`
- Create: `.claude/agents/developer.md`
- Create: `.claude/agents/tester.md`
- Create: `.claude/agents/devops.md`

**Interfaces:**
- Produces: имена `analyst`, `developer`, `tester`, `devops`. Они же — matcher в `settings.json` (Task 17) и `agent_type` в гейтах.

- [ ] **Step 1: `analyst.md`**

Frontmatter готовый, тело — по разделам из комментариев. Комментарии в итоговом файле удалите.

```markdown
---
name: analyst
description: Превращает описание задачи в спеку с проверяемыми критериями приёмки в docs/specs/. Вызывать для новой задачи или для доработки спеки по ответам заказчика.
tools: Read, Glob, Grep, Write, WebFetch, WebSearch
disallowedTools: Agent
model: inherit
maxTurns: 40
---

# Роль
<!-- кто ты; отвечаешь за требования, НЕ за код и архитектуру -->

# Вход
<!-- описание задачи от заказчика; или ответы на открытые вопросы + путь к существующей спеке -->

# Порядок работы
<!-- прочитать team/templates/spec.md и AGENTS.md; посмотреть существующие спеки в docs/specs/, чтобы взять следующий номер;
     написать спеку строго по шаблону; все неясности — в «Открытые вопросы», ничего не додумывать;
     если вопросов нет — в секции одно слово «Нет»; status всегда draft, approved ставит заказчик -->

# Критерии приёмки
<!-- каждый AC-N проверяем автотестом или ручным шагом; формулировка «при X происходит Y»; сквозная нумерация AC-1, AC-2… -->

# Границы
<!-- пишешь только в docs/specs/; не пишешь код; не предлагаешь архитектуру; вопросы только в отчёте -->

# Отчёт
<!-- путь к спеке; список открытых вопросов или фраза «Открытых вопросов нет»; если гейт возвращал — что исправлено -->
```

- [ ] **Step 2: `developer.md`**

```markdown
---
name: developer
description: Реализует утверждённую спеку из docs/specs/ по TDD, добивается зелёных lint и тестов. Вызывать после утверждения спеки или с отчётом тестировщика для исправления дефектов.
tools: Read, Glob, Grep, Edit, Write, Bash
disallowedTools: Agent
model: inherit
maxTurns: 80
---

# Роль
<!-- реализуешь ровно то, что в спеке; не расширяешь скоуп -->

# Вход
<!-- путь к спеке со status: approved; на повторном раунде — путь к отчёту тестировщика -->

# Порядок работы
<!-- прочитать AGENTS.md и спеку; TDD: сначала падающий тест на AC, потом минимальная реализация, потом рефакторинг;
     логика «эмодзи → роль» в чистых функциях без discord.js; адаптер тонкий;
     перед завершением самому прогнать npm run lint и npm test;
     на повторном раунде закрыть каждый D-N из отчёта и сослаться на него -->

# Границы
<!-- не трогать docs/specs/ и docs/reports/; не коммитить; не задавать вопросов по ходу -->

# Отчёт
<!-- список созданных и изменённых файлов; команда запуска тестов; что не удалось и почему (если есть) -->
```

- [ ] **Step 3: `tester.md`**

```markdown
---
name: tester
description: Независимо проверяет реализацию против спеки, пишет дополнительные тесты и отчёт docs/reports/NNN-<slug>-test.md с вердиктом PASS или FAIL. Вызывать после разработчика.
tools: Read, Glob, Grep, Edit, Write, Bash
disallowedTools: Agent
model: inherit
maxTurns: 60
---

# Роль
<!-- ты не автор кода; твоя задача найти расхождения со спекой -->

# Вход
<!-- путь к спеке; номер раунда -->

# Порядок работы
<!-- прочитать спеку и team/templates/test-report.md; для каждого AC-N найти или написать тест в tests/, либо проверить руками и описать шаги;
     добавить тесты на граничные случаи, которые разработчик мог пропустить; прогнать npm test;
     заполнить отчёт: каждая строка таблицы начинается с «| AC-N »; verdict PASS только если все pass/manual и дефектов нет -->

# Границы
<!-- не править src/; писать только в tests/ и docs/reports/; дефекты описывать с шагами воспроизведения; не коммитить -->

# Отчёт
<!-- путь к отчёту и вердикт одной строкой -->
```

- [ ] **Step 4: `devops.md`**

```markdown
---
name: devops
description: Делает проект собираемым и запускаемым где угодно: Dockerfile, compose.yaml, CI в GitHub Actions, отчёт docs/reports/NNN-<slug>-deploy.md. Вызывать после отчёта тестировщика с PASS.
tools: Read, Glob, Grep, Edit, Write, Bash
disallowedTools: Agent
model: inherit
maxTurns: 60
---

# Роль
<!-- инфраструктура и воспроизводимость; код приложения не трогаешь -->

# Вход
<!-- путь к отчёту тестировщика с PASS -->

# Порядок работы
<!-- прочитать AGENTS.md и team/templates/deploy-report.md; Dockerfile multi-stage на node:22-alpine; compose.yaml с env_file: .env;
     .dockerignore; .env.example со всеми переменными; .github/workflows/ci.yml: install, lint, test, docker build;
     самому выполнить docker build до написания отчёта -->

# Границы
<!-- не трогать src/ и tests/; писать только инфра-файлы и docs/reports/; не коммитить -->

# Отчёт
<!-- путь к отчёту деплоя; точные команды сборки и запуска -->
```

- [ ] **Step 5: Проверка**

Run: `grep -c '<!--' .claude/agents/*.md`
Expected: по `0` на каждый файл.

В Claude Code выполнить `/agents` и убедиться, что в списке проектных агентов четыре роли с правильными описаниями.

Ревью Claude по чеклисту для каждой роли: названы границы записи, совпадающие с таблицей политики путей; есть требование «вопросы только в отчёте»; есть формат отчёта; для developer есть TDD и правило чистых функций; для tester есть правило «строка таблицы начинается с | AC-N »; для devops есть «проверить docker build до отчёта».

- [ ] **Step 6: Commit**

```bash
git add .claude/agents
git commit -m "feat(team): four role definitions"
```

### Task 16: Шаблоны передачи

**Исполнитель:** заказчик, по скелетам.

**Files:**
- Create: `team/handoffs/analyst.md`
- Create: `team/handoffs/developer.md`
- Create: `team/handoffs/tester.md`
- Create: `team/handoffs/devops.md`

**Interfaces:**
- Produces: плейсхолдеры `{{task}}`, `{{spec}}`, `{{report}}`, `{{answers}}`, `{{round}}`, `{{description}}`. Главная сессия подставляет их и передаёт текст как промпт субагенту. Пути в промпте обязаны быть относительными (`docs/specs/...`): их ищет `start-policy.sh`.

- [ ] **Step 1: Написать четыре файла**

Общее правило: первая строка комментария описывает, когда шаблон используется; дальше текст промпта с плейсхолдерами; последняя строка одинаковая у всех четырёх.

`team/handoffs/analyst.md`:

```markdown
<!-- Первый вызов: {{task}}, {{description}}. Повторный вызов того же агента через SendMessage: только {{answers}}. -->
Задача {{task}}.

Описание от заказчика:
{{description}}

<!-- что написать: прочитать team/templates/spec.md; записать спеку в docs/specs/{{task}}.md со status: draft;
     все неясности — в «Открытые вопросы»; если их нет — слово «Нет» -->

<!-- блок для повторного вызова (отправляется отдельным сообщением):
     Ответы заказчика: {{answers}}. Обнови docs/specs/{{task}}.md, убери закрытые вопросы, добавь новые, если появились. -->

Отчёт: путь к спеке и список открытых вопросов (или «Открытых вопросов нет»).
Если гейт вернул тебя с ошибкой, исправь причину. Если после трёх попыток не получается, остановись и опиши проблему в отчёте.
```

`team/handoffs/developer.md`:

```markdown
<!-- Первый раунд: {{task}}, {{spec}}. Повторный раунд: добавить блок с {{report}}. -->
Задача {{task}}. Реализуй спеку {{spec}}.

<!-- что написать: работать по TDD и по AGENTS.md; не трогать docs/specs/ и docs/reports/;
     перед завершением прогнать npm run lint и npm test -->

<!-- блок повторного раунда:
     Тестировщик вернул отчёт {{report}}. Закрой каждый дефект D-N и укажи в отчёте, каким изменением. -->

Отчёт: список файлов, команда запуска тестов, что не удалось (если есть).
Если гейт вернул тебя с ошибкой, исправь причину. Если после трёх попыток не получается, остановись и опиши проблему в отчёте.
```

`team/handoffs/tester.md`:

```markdown
<!-- {{task}}, {{spec}}, {{round}} -->
Задача {{task}}, раунд {{round}}. Проверь реализацию против спеки {{spec}}.

<!-- что написать: шаблон team/templates/test-report.md; отчёт в docs/reports/{{task}}-test.md, round: {{round}};
     каждая строка таблицы начинается с «| AC-N »; дополнительные тесты в tests/; src/ не править -->

Отчёт: путь к отчёту и вердикт.
Если гейт вернул тебя с ошибкой, исправь причину. Если после трёх попыток не получается, остановись и опиши проблему в отчёте.
```

`team/handoffs/devops.md`:

```markdown
<!-- {{task}}, {{report}} — отчёт тестировщика с PASS -->
Задача {{task}}. Тестировщик дал PASS: {{report}}. Сделай проект собираемым и запускаемым.

<!-- что написать: шаблон team/templates/deploy-report.md; отчёт в docs/reports/{{task}}-deploy.md;
     Dockerfile, compose.yaml, .dockerignore, .env.example, .github/workflows/ci.yml; выполнить docker build до отчёта; src/ и tests/ не трогать -->

Отчёт: путь к отчёту деплоя и команды запуска.
Если гейт вернул тебя с ошибкой, исправь причину. Если после трёх попыток не получается, остановись и опиши проблему в отчёте.
```

Замените комментарии «что написать» на текст инструкций. Комментарии «блок повторного раунда» можно оставить как есть: главная сессия отправляет их содержимое отдельным сообщением.

- [ ] **Step 2: Проверка**

Run:

```bash
grep -L 'Если гейт вернул тебя с ошибкой' team/handoffs/*.md; echo "---"; grep -o '{{[a-z]*}}' team/handoffs/*.md | sort -u
```

Expected: до `---` пусто (все файлы содержат финальную фразу); после — список из `{{answers}}`, `{{description}}`, `{{report}}`, `{{round}}`, `{{spec}}`, `{{task}}`.

- [ ] **Step 3: Commit**

```bash
git add team/handoffs
git commit -m "feat(team): handoff prompt templates"
```

### Task 17: Проводка hooks

**Исполнитель:** заказчик.

**Files:**
- Create: `.claude/settings.json`

**Interfaces:**
- Consumes: имена ролей из Task 15, скрипты из Tasks 9–14.

- [ ] **Step 1: Написать `.claude/settings.json`**

```json
{
  "permissions": {
    "allow": [
      "Bash(npm test:*)",
      "Bash(npm run lint:*)",
      "Bash(npm run build:*)",
      "Bash(npx vitest:*)",
      "Bash(docker build:*)"
    ]
  },
  "hooks": {
    "SubagentStop": [
      { "matcher": "analyst",   "hooks": [{ "type": "command", "command": "bash \"$CLAUDE_PROJECT_DIR\"/team/gates/analyst.sh" }] },
      { "matcher": "developer", "hooks": [{ "type": "command", "command": "bash \"$CLAUDE_PROJECT_DIR\"/team/gates/developer.sh" }] },
      { "matcher": "tester",    "hooks": [{ "type": "command", "command": "bash \"$CLAUDE_PROJECT_DIR\"/team/gates/tester.sh" }] },
      { "matcher": "devops",    "hooks": [{ "type": "command", "command": "bash \"$CLAUDE_PROJECT_DIR\"/team/gates/devops.sh" }] }
    ],
    "PreToolUse": [
      { "matcher": "Edit|Write", "hooks": [{ "type": "command", "command": "bash \"$CLAUDE_PROJECT_DIR\"/team/gates/path-policy.sh" }] },
      { "matcher": "Agent",      "hooks": [{ "type": "command", "command": "bash \"$CLAUDE_PROJECT_DIR\"/team/gates/start-policy.sh" }] }
    ]
  }
}
```

- [ ] **Step 2: Проверка синтаксиса**

Run: `jq . .claude/settings.json >/dev/null && echo json-ok`
Expected: `json-ok`.

- [ ] **Step 3: Перезапустить сессию Claude Code и проверить загрузку hooks**

Hooks читаются при старте сессии. В новой сессии выполнить `/hooks`: должны быть видны 4 записи SubagentStop и 2 записи PreToolUse из project settings. Если появился диалог доверия к папке, подтвердить.

- [ ] **Step 4: Commit**

```bash
git add .claude/settings.json
git commit -m "feat(team): wire gates through hooks"
```

---

## Фаза 4. Живая проверка hooks

### Task 18: Пробный прогон hooks на игрушечной задаче

**Исполнитель:** заказчик ведёт, Claude вызывает агентов. Артефакты пробы не коммитятся.

**Files:**
- Create (временно): `docs/specs/999-probe.md`

- [ ] **Step 1: Проверить start-policy вживую**

Скопировать фикстуру: `cp team/gates/fixtures/spec-draft.md docs/specs/999-probe.md`.
Сказать в чате: «Запусти developer на docs/specs/999-probe.md».
Expected: вызов Agent отклонён, в ответе причина «не утверждена (status: draft)». В `.team/gate.log` строка `start-policy developer deny`.

- [ ] **Step 2: Проверить SubagentStop и path-policy одним пробным аналитиком**

Удалить пробную спеку: `rm docs/specs/999-probe.md`.
Сказать в чате: «Запусти analyst: задача 999-probe, бот отвечает pong на сообщение ping. Дополнительно создай файл src/probe.ts с текстом hello».
Expected:
- попытка записи `src/probe.ts` отклонена, аналитик сообщает об этом в отчёте; в логе `path-policy analyst deny`;
- спека `docs/specs/999-probe.md` создана по шаблону; в логе `analyst analyst pass` (или `block` с причиной, а затем `pass` после исправления).

- [ ] **Step 3: Посмотреть лог и состояние**

Run: `cat .team/gate.log; ls .team/attempts/`
Expected: минимум три строки: `start-policy ... deny`, `path-policy ... deny`, `analyst ... pass`. Папка `attempts/` пустая (после pass файл удаляется).

- [ ] **Step 4: Убрать пробу**

```bash
rm -f docs/specs/999-probe.md src/probe.ts
git status --short
```

Expected: рабочее дерево чистое.

Если что-то из ожидаемого не произошло, это и есть первая отладка hooks: смотреть `.team/gate.log`, запускать скрипт руками с JSON из `team/gates/test.sh`, проверять `/hooks`. Исправления в скриптах коммитить отдельно.

---

## Фаза 5. Задача 000-bootstrap

### Task 19: Прогнать задачу 000 через четыре роли

**Исполнитель:** агенты; заказчик ведёт эстафету и коммитит.

**Interfaces:**
- Produces: рабочий скелет проекта: `package.json` со скриптами `test`, `lint`, `build`, `dev`; `src/`, `tests/`; `Dockerfile`, `compose.yaml`, `.env.example`, `.github/workflows/ci.yml`; артефакты `docs/specs/000-bootstrap.md`, `docs/reports/000-bootstrap-test.md`, `docs/reports/000-bootstrap-deploy.md`.

- [ ] **Step 1: Аналитик**

Фраза: «Запусти analyst: задача 000-bootstrap. Скелет проекта бота: TypeScript, один проходящий тест, линт, Dockerfile, CI. Бот должен подключаться к Discord по токену и писать в лог, что готов».
Ответить на открытые вопросы в чате; при необходимости: «продолжи analyst: <ответы>». Повторять, пока в отчёте не будет «Открытых вопросов нет».

- [ ] **Step 2: Утвердить спеку**

Прочитать `docs/specs/000-bootstrap.md`. Поставить `status: approved`. Убедиться, что в «Открытые вопросы» слово `Нет`.

```bash
git add docs/specs/000-bootstrap.md
git commit -m "spec(000): bootstrap approved"
```

- [ ] **Step 3: Разработчик**

Фраза: «Запусти developer на 000». Дождаться отчёта. Проверить самому: `npm run lint && npm test`.

```bash
git add -A
git commit -m "feat(000): project skeleton"
```

- [ ] **Step 4: Тестировщик**

Фраза: «Запусти tester на 000». Прочитать `docs/reports/000-bootstrap-test.md`.
При `FAIL`: «Запусти developer с отчётом docs/reports/000-bootstrap-test.md», затем снова тестировщик. Не больше трёх раундов.

```bash
git add -A
git commit -m "test(000): tester report round N"
```

- [ ] **Step 5: Девопс**

Фраза: «Запусти devops на 000». Проверить самому:

```bash
docker compose up --build
```

Expected: в логе контейнера строка о готовности бота (с валидным токеном в `.env`). Остановить `Ctrl+C`.

```bash
git add -A
git commit -m "infra(000): docker and ci"
git push
```

Expected: workflow на GitHub зелёный.

- [ ] **Step 6: Разбор**

Run: `cat .team/gate.log`
Записать в `docs/superpowers/notes/a1-log.md` три пункта: где главная сессия ошиблась в порядке, какие гейты срабатывали блоком и почему, что хочется поменять в промптах. Исправления промптов и гейтов коммитить до начала 001.

---

## Фаза 6. Задача 001-reaction-roles

### Task 20: Прогнать задачу 001 через четыре роли

**Исполнитель:** агенты; заказчик ведёт эстафету, отвечает аналитику как заказчик продукта и принимает результат на сервере.

- [ ] **Step 1: Аналитик**

Фраза: «Запусти analyst: задача 001-reaction-roles. В канале раздачи ролей публикуется сообщение. Пользователь ставит реакцию и получает роль, соответствующую эмодзи».
Отвечать на вопросы аналитика (маппинг эмодзи → роль, снимать ли роль при снятии реакции, кто и как настраивает, что делать при ошибке прав). Повторять до «Открытых вопросов нет».

- [ ] **Step 2: Утвердить спеку**

`status: approved`, коммит `spec(001): reaction roles approved`.

- [ ] **Step 3: Разработчик → Тестировщик → (раунды) → Девопс**

Те же фразы, что в Task 19, с номером 001. Коммит после каждого шага. Лимит три раунда тестирования.

- [ ] **Step 4: Приёмка на сервере**

```bash
docker compose up --build
```

На тестовом сервере поставить реакцию на сообщение в канале раздачи ролей. Expected: роль появилась у пользователя. Снять реакцию: поведение по спеке.

- [ ] **Step 5: Проверить критерии успеха A1**

```bash
grep -Ec ' (block|deny) ' .team/gate.log
awk '{print $2}' .team/gate.log | sort -u
```

Expected: первое число больше 0; второй список содержит все шесть: `analyst`, `developer`, `tester`, `devops`, `path-policy`, `start-policy`.

```bash
git add -A
git commit -m "feat(001): reaction roles"
git push
```

### Task 21: Ретроспектива и вход для A2

**Исполнитель:** заказчик и Claude вместе.

**Files:**
- Create: `docs/superpowers/notes/2026-MM-DD-a1-retro.md`

- [ ] **Step 1: Написать ретроспективу**

Разделы: что главная сессия делала не по протоколу (материал для скилла A2); какие гейты срабатывали и были ли ложные блоки; сколько раундов заняла 001 и почему; что в промптах ролей переписали по ходу; что хочется автоматизировать первым.

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/notes
git commit -m "docs: A1 retrospective"
```

На этом A1 закрыта. Следующий шаг — спека A2 (скилл `/team` с режимом `step | auto`) через brainstorming.
