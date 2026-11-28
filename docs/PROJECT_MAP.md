# Карта проекта: Бармен

Пилот и команда его проверки сверены по рабочему дереву 2026-11-27; остальные разделы — 2026-11-09. Discord-бот на Hermes, профиль `barmen`. Карта помогает выбрать область чтения; политика доступа, отправки сообщений и выкатки — в AGENTS.md.

## Точки входа и связи

`barman/__init__.py` регистрирует плагин, Discord-обработчики и команды. Чистая логика отделена от SDK и сети; тесты запускаются без Discord и реальных запросов.

| Задача | Куда смотреть сначала | Проверки |
|---|---|---|
| Роли по реакциям | `barman/reaction_roles.py`, регистрация в `barman/__init__.py` | `tests/test_reaction_roles.py` |
| Доступ, ответы и поиск | `barman/chat.py`, `barman/dialogue.py` | `tests/test_chat_policy.py`, `tests/test_dialogue.py`, `tests/test_search_quality.py` |
| Выделенная комната ответа (сверено 2026-11-28) | `barman/routed_chat.py`, хук в `barman/chat.py`, регистрация в `barman/__init__.py` | `tests/test_routed_chat.py` |
| Ежедневная выжимка | `barman/digest.py` | `tests/test_digest.py` |
| Редкие реплики | `barman/comments.py` | `tests/test_comments.py`, `tests/test_comment_runtime.py` |
| Ограниченный эпизод разговора | `barman/conversation.py` | `tests/test_conversation.py` |
| Пилот ссылок и исследование | `barman/link_pilot.py`, `barman/link_research.py`, `deploy/check_link_pilot.py` | `tests/test_link_pilot.py`, `tests/test_link_research.py`, `tests/test_link_images.py` |
| Скриншоты и OCR | `barman/screenshots.py`, `deploy/Dockerfile.ocr` | `tests/test_screenshots.py`, `tests/test_screenshots_rapid.py` |
| Личность и эмодзи | `persona/`, `deploy/render_soul.py` | `tests/test_render_soul.py` |
| Выкатка и совместимость Hermes | `deploy/update.sh`, `deploy/check_chat_runtime.py`, `deploy/stale_sessions.py` | `tests/test_update_sh.py`, `tests/test_chat_runtime.py`, `tests/test_stale_sessions.py` |

Политика чата проверяется до вызовов моделей и доставки. `dialogue.py` хранит ограниченный контекст; исследовательский pipeline и публичный fetch имеют собственные ограничения. Не переносить их возможности в обычный чат без отдельной задачи и проверок.

## Команды проверки

Из корня: `reslop t -- .venv/bin/pytest -q`. Для локальной правки передавать соответствующий тестовый файл; перед коммитом нужен весь pytest. Если Reslop недоступен — `.venv/bin/pytest -q`, явно сообщив о fallback. Для изменений только этой карты достаточно проверить пути и ссылку из AGENTS.md.

CI: `.github/workflows/tests.yml`; выкатка: `.github/workflows/deploy-test.yml` и `.github/workflows/deploy.yml`. Порядок test → main и ограничения продакшена сохраняются; наличие команды в карте не разрешает выкатку.

Изолированный сетевой прогон четырёх обезличенных примеров: `python deploy/check_link_pilot.py --profile-home /opt/data --output /tmp/pilot-receipt.json` в контейнере тестового Бармена из отдельной папки кандидата. Команда использует реальный OpenRouter/поиск и синтетические SDK-сообщения, не подключает Discord-клиент, блокирует отправку и не изменяет рабочие профили или срок пилота. `--runtime-env-stdin` допускает временный ключ провайдера через JSON в stdin без записи в профиль; ключ нельзя передавать аргументом команды или выводить в отчёт.

## Документы и границы чтения

- Описание запуска — `README.md`; планы и спецификации — `docs/superpowers/`. Открывать только документ по задаче.
- `persona/` содержит исходные тексты личностей, а не генерируемые ассеты.
- Обычно не читать `.venv/`, `.git/`, `__pycache__/`, `blue_oyster.egg-info/`, `.log/`, бинарные OCR-модели и временные результаты.
- Секреты и живые данные не являются материалом для карты; ключи, пользовательские ID и серверные .env не читать для обычной разработки.
- Компаньон находится в отдельном репозитории; контейнер Бармена не менять в рамках задач компаньона.

При изменении маршрутизации, точки входа или команды проверки обновлять соответствующий раздел карты и дату.
