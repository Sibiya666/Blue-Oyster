# bot-role

Discord-бот, который выдаёт и снимает роли участникам по реакциям на сообщение. Код пишет команда из четырёх агентов по протоколу эстафеты.

## Стек и команды

- Node 22 (`.nvmrc`), TypeScript strict, ESM, npm.
- `npm test` — vitest; `npm run lint` — Biome (lint + format check); `npm run build` — tsc.
- Запуск локально: `npm run dev` (tsx) или `docker compose up`.

## Discord

- discord.js v14.
- Intents: `Guilds`, `GuildMessageReactions`. Partials: `Message`, `Channel`, `Reaction`, `User`.
- Токен: `DISCORD_TOKEN` из `.env`. В репо только `.env.example`.

## Архитектура

- Логика «эмодзи → роль, добавить/снять» — чистые функции в `src/core/` без импорта discord.js.
- Адаптер к Discord — тонкий слой в `src/discord/`. Unit-тесты без сети.

## Артефакты команды

- `docs/specs/NNN-<slug>.md` — спеки (аналитик).
- `docs/reports/NNN-<slug>-test.md` — отчёты тестировщика.
- `docs/reports/NNN-<slug>-deploy.md` — отчёты девопса.
- Шаблоны в `team/templates/`.

## Правила для агентов

- Не коммитить. Не задавать вопросов по ходу — только в итоговом отчёте.
- Заканчивать работу коротким отчётом по форме из шаблона передачи.
- Если гейт вернул с ошибкой — исправить причину; после трёх попыток остановиться и описать проблему.

## Процесс

Протокол эстафеты описан в `team/README.md`.
