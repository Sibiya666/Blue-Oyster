#!/bin/sh
# Выкатить код бармена на сервер и перезапустить его контейнер. Данные (barman/bindings.json) не трогаются.
# В .env на сервере выставляются только ключи ниже, остальное (токен, ключи) не трогается:
#   DISCORD_COMMAND_SYNC_POLICY=off — Hermes не регистрирует свои /-команды (список держит бармен);
#   DISCORD_ALLOWED_USERS = BARMAN_AI_USERS (ID через запятую) или 0 — с кем ИИ бармена разговаривает (0 — ни с кем);
#   DISCORD_ALLOWED_ROLES= — по ролям никого не пускаем;
#   DISCORD_ALLOWED_CHANNELS = BARMAN_AI_CHANNELS — где ИИ разговаривает (только если передан).
# В config.yaml Hermes (через hermes config set) — замки, ДО открытия доступа и с проверкой:
#   platforms.discord.extra.allow_admin_from / group_allow_admin_from = 0 — админов нет, поэтому служебные
#   /-команды Hermes (/model, /update, /restart…) не работают ни у кого, кроме безобидных /help и /whoami;
#   platforms.discord.extra.dm_policy = disabled — личка выключена.
# Как отвечает в Discord (всегда): без веток, прямо в канале реплаем на сообщение — пингуется только автор
#   (DISCORD_AUTO_THREAD=false; в ветках тоже только по упоминанию — DISCORD_THREAD_REQUIRE_MENTION=true;
#   DISCORD_REPLY_TO_MODE=first, пинги @user/@role/@everyone из текста ответа выключены);
#   DISCORD_HOME_CHANNEL=0 — «домашнего» канала нет: служебные сообщения Hermes (перезапуск, cron) никуда не уходят,
#   и нет подсказки «введите /sethome»; display.busy_input_mode=queue и HERMES_GATEWAY_BUSY_ACK_ENABLED=false —
#   если дописали, пока бармен думает, он ответит отдельно и без служебных плашек.
# Реплики без обращения (barman/comments.py): BARMAN_COMMENT_USERS — чьи сообщения изредка комментировать (нет — 0, выкл),
#   канал = BARMAN_AI_CHANNELS, модель = BARMAN_AI_MODEL; BARMAN_COMMENT_CHANCE (0.1) и BARMAN_COMMENT_COOLDOWN_MIN (60) — по желанию.
# model.default = BARMAN_AI_MODEL — модель OpenRouter для разговора (только если передан).
# SOUL.md = persona/SOUL.<BARMAN_SOUL>.md с эмодзи из BARMAN_EMOJI («peka=ID,…») — только если BARMAN_SOUL передан.
#   BARMAN_ROLES_CHANNEL, BARMAN_DIGEST_CHANNEL, BARMAN_DIGEST_USER, BARMAN_DIGEST_MODEL — только если переданы
#   (канал ролей; канал, кого упомянуть и модель ИИ для ежедневной выжимки DTF; BARMAN_DIGEST_CHANNEL=off — выключить).
# Куда выкатывать — BARMAN_TARGET: prod (по умолчанию) — бар, контейнер `barmen`, данные /root/barmen-hermes;
#   test — тестовый бот, контейнер `barmen-test`, данные /root/barmen-test-hermes. Другие боты не затрагиваются.
# Тестовый бот создаётся при первой выкатке сам: config.yaml и ключ OpenRouter копируются с бара прямо на сервере,
#   токен — BARMAN_BOT_TOKEN (обязателен для первого раза; передаётся через stdin, не в командной строке).
# Использование: deploy/update.sh <IP>   (бар — .github/workflows/deploy.yml, тест — deploy-test.yml)
set -eu
IP="$1"
KEY="${BARMAN_SSH_KEY:-$HOME/.ssh/companion_vps}"  # в GitHub Actions — отдельный deploy-ключ
TARGET="${BARMAN_TARGET:-prod}"
case "$TARGET" in
  prod) CT=barmen; DATA="${BARMAN_DATA:-/root/barmen-hermes}" ;;
  test) CT=barmen-test; DATA="${BARMAN_DATA:-/root/barmen-test-hermes}" ;;
  *) echo "BARMAN_TARGET — prod или test"; exit 1 ;;
esac
PROD_DATA="${BARMAN_PROD_DATA:-/root/barmen-hermes}"
TOKEN="${BARMAN_BOT_TOKEN:-}"
CH="${BARMAN_ROLES_CHANNEL:-}"
DCH="${BARMAN_DIGEST_CHANNEL:-}"
DUSER="${BARMAN_DIGEST_USER:-}"
DMODEL="${BARMAN_DIGEST_MODEL:-}"
AIUSERS="${BARMAN_AI_USERS:-}"
AICH="${BARMAN_AI_CHANNELS:-}"
SOUL="${BARMAN_SOUL:-}"
EMOJI="${BARMAN_EMOJI:-}"
AIMODEL="${BARMAN_AI_MODEL:-}"
CUSERS="${BARMAN_COMMENT_USERS:-}"
CCHANCE="${BARMAN_COMMENT_CHANCE:-}"
CCOOL="${BARMAN_COMMENT_COOLDOWN_MIN:-}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
case "$CH" in *[!0-9]*) echo "BARMAN_ROLES_CHANNEL — число (ID канала)"; exit 1 ;; esac
case "$DCH" in off) ;; *[!0-9]*) echo "BARMAN_DIGEST_CHANNEL — ID канала или off"; exit 1 ;; esac
case "$DUSER" in *[!A-Za-z0-9_.]*) echo "BARMAN_DIGEST_USER — имя пользователя Discord (буквы, цифры, _ .)"; exit 1 ;; esac
case "$DMODEL$AIMODEL" in *[!A-Za-z0-9_.:/-]*) echo "BARMAN_DIGEST_MODEL / BARMAN_AI_MODEL — id модели OpenRouter"; exit 1 ;; esac
case "$AIUSERS$AICH$CUSERS" in *[!0-9,]*) echo "BARMAN_AI_USERS / BARMAN_AI_CHANNELS / BARMAN_COMMENT_USERS — ID через запятую"; exit 1 ;; esac
case "$CCHANCE$CCOOL" in *[!0-9.]*) echo "BARMAN_COMMENT_CHANCE / BARMAN_COMMENT_COOLDOWN_MIN — числа"; exit 1 ;; esac
case "$TOKEN" in *[!A-Za-z0-9._-]*) echo "BARMAN_BOT_TOKEN — токен бота Discord"; exit 1 ;; esac
case "$SOUL" in *[!a-z0-9_-]*) echo "BARMAN_SOUL — имя личности из persona/ (например sibiya)"; exit 1 ;; esac
SOUL_FILE=""
if [ -n "$SOUL" ]; then  # собираем до выкатки: кривые BARMAN_EMOJI или нет файла — стоп, сервер не тронут
  [ -f "$REPO/persona/SOUL.$SOUL.md" ] || { echo "Нет persona/SOUL.$SOUL.md"; exit 1; }
  SOUL_FILE="$(mktemp)"
  python3 "$REPO/deploy/render_soul.py" "$REPO/persona/SOUL.$SOUL.md" "$EMOJI" > "$SOUL_FILE"
fi
if ! ssh -i "$KEY" "root@$IP" "test -d $DATA"; then
  [ "$TARGET" = test ] || { echo "Нет $DATA на сервере"; exit 1; }
  [ -n "$TOKEN" ] || { echo "Первый запуск теста: нужен BARMAN_BOT_TOKEN (токен тестового бота)"; exit 1; }
  echo "Создаю тестового бота: $DATA"
  ssh -i "$KEY" "root@$IP" "mkdir -p $DATA/plugins && cp $PROD_DATA/config.yaml $DATA/config.yaml && grep '^OPENROUTER_API_KEY=' $PROD_DATA/.env > $DATA/.env && chmod 600 $DATA/.env && chown -R 10000:10000 $DATA"
fi
rsync -a --delete --exclude '__pycache__' -e "ssh -i $KEY" "$REPO/barman/" "root@$IP:$DATA/plugins/barman/"
set_env() {  # заменить строку KEY=... в .env или дописать, если её нет
  ssh -i "$KEY" "root@$IP" "f=$DATA/.env; if grep -q '^$1=' \$f; then sed -i 's|^$1=.*|$1=$2|' \$f; else echo $1=$2 >> \$f; fi"
}
if [ -n "$TOKEN" ]; then  # токен через stdin: не светится в командной строке и логах
  printf '%s' "$TOKEN" | ssh -i "$KEY" "root@$IP" "t=\$(cat); f=$DATA/.env; grep -v '^DISCORD_BOT_TOKEN=' \$f > \$f.new; echo DISCORD_BOT_TOKEN=\$t >> \$f.new; mv \$f.new \$f; chmod 600 \$f"
fi
ssh -i "$KEY" "root@$IP" "docker inspect $CT >/dev/null 2>&1 || docker run -d --name $CT --memory 768m --restart unless-stopped -v $DATA:/opt/data \$(docker inspect barmen --format '{{.Image}}') gateway run >/dev/null"
hermes_set() {  # замок в config.yaml Hermes + проверка, что он встал (иначе доступ не открываем)
  ssh -i "$KEY" "root@$IP" "docker exec -u 10000 $CT hermes config set --force $1 $2 >/dev/null && test \"\$(docker exec -u 10000 $CT hermes config get $1)\" = $2" || { echo "Не встал замок Hermes: $1"; exit 1; }
}
ssh -i "$KEY" "root@$IP" "docker start $CT >/dev/null"  # hermes config работает в запущенном контейнере
hermes_set platforms.discord.extra.allow_admin_from 0
hermes_set platforms.discord.extra.group_allow_admin_from 0
hermes_set platforms.discord.extra.dm_policy disabled
hermes_set display.busy_input_mode queue  # дописал, пока бармен думает — отдельный ответ, без «перенаправил запуск»
[ -z "$AIMODEL" ] || { hermes_set model.default "$AIMODEL"; echo "Модель разговора: $AIMODEL"; }
set_env DISCORD_COMMAND_SYNC_POLICY off
set_env DISCORD_AUTO_THREAD false
set_env DISCORD_THREAD_REQUIRE_MENTION true
set_env DISCORD_REPLY_TO_MODE first
set_env DISCORD_ALLOW_MENTION_EVERYONE false
set_env DISCORD_ALLOW_MENTION_ROLES false
set_env DISCORD_ALLOW_MENTION_USERS false
set_env DISCORD_ALLOW_MENTION_REPLIED_USER true
set_env DISCORD_HOME_CHANNEL 0
set_env HERMES_GATEWAY_BUSY_ACK_ENABLED false  # без служебных «⚡ прерываю…» в чате
set_env DISCORD_ALLOWED_ROLES ""
set_env DISCORD_ALLOWED_USERS "${AIUSERS:-0}"
[ -z "$AICH" ] || set_env DISCORD_ALLOWED_CHANNELS "$AICH"
set_env BARMAN_COMMENT_USERS "${CUSERS:-0}"
[ -z "$AICH" ] || set_env BARMAN_COMMENT_CHANNELS "$AICH"
[ -z "$AIMODEL" ] || set_env BARMAN_COMMENT_MODEL "$AIMODEL"
[ -z "$CCHANCE" ] || set_env BARMAN_COMMENT_CHANCE "$CCHANCE"
[ -z "$CCOOL" ] || set_env BARMAN_COMMENT_COOLDOWN_MIN "$CCOOL"
if [ -n "$SOUL_FILE" ]; then
  ssh -i "$KEY" "root@$IP" "cat > $DATA/SOUL.md" < "$SOUL_FILE"
  rm -f "$SOUL_FILE"
  echo "Личность: $SOUL"
fi
echo "ИИ бармена: ${AIUSERS:-никому}"
if [ -n "$CH" ]; then
  set_env BARMAN_ROLES_CHANNEL "$CH"
  echo "Канал ролей: $CH"
fi
case "$DCH" in  # off — выжимка выключена: канал в .env очищается, код остаётся
  "") ;;
  off) set_env BARMAN_DIGEST_CHANNEL ""; echo "Выжимка DTF выключена" ;;
  *) set_env BARMAN_DIGEST_CHANNEL "$DCH" ;;
esac
[ -z "$DUSER" ] || set_env BARMAN_DIGEST_USER "$DUSER"
[ -z "$DMODEL" ] || set_env BARMAN_DIGEST_MODEL "$DMODEL"
ssh -i "$KEY" "root@$IP" "chown -R 10000:10000 $DATA && docker restart $CT >/dev/null"
echo "Бармен ($TARGET) обновлён и перезапущен"
