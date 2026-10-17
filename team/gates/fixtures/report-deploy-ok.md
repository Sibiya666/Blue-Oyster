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
