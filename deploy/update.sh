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
# SOUL.md = persona/SOUL.<BARMAN_SOUL>.md с эмодзи из BARMAN_EMOJI («peka=ID,…») — только если BARMAN_SOUL передан.
#   BARMAN_ROLES_CHANNEL, BARMAN_DIGEST_CHANNEL, BARMAN_DIGEST_USER, BARMAN_DIGEST_MODEL — только если переданы
#   (канал ролей; канал, кого упомянуть и модель ИИ для ежедневной выжимки DTF; BARMAN_DIGEST_CHANNEL=off — выключить).
# Бармен живёт в своём контейнере `barmen` (данные — /root/barmen-hermes), другие боты не затрагиваются.
# Использование: deploy/update.sh <IP>   (после мержа в main это делает .github/workflows/deploy.yml)
set -eu
IP="$1"
KEY="${BARMAN_SSH_KEY:-$HOME/.ssh/companion_vps}"  # в GitHub Actions — отдельный deploy-ключ
DATA="${BARMAN_DATA:-/root/barmen-hermes}"
CH="${BARMAN_ROLES_CHANNEL:-}"
DCH="${BARMAN_DIGEST_CHANNEL:-}"
DUSER="${BARMAN_DIGEST_USER:-}"
DMODEL="${BARMAN_DIGEST_MODEL:-}"
AIUSERS="${BARMAN_AI_USERS:-}"
AICH="${BARMAN_AI_CHANNELS:-}"
SOUL="${BARMAN_SOUL:-}"
EMOJI="${BARMAN_EMOJI:-}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
case "$CH" in *[!0-9]*) echo "BARMAN_ROLES_CHANNEL — число (ID канала)"; exit 1 ;; esac
case "$DCH" in off) ;; *[!0-9]*) echo "BARMAN_DIGEST_CHANNEL — ID канала или off"; exit 1 ;; esac
case "$DUSER" in *[!A-Za-z0-9_.]*) echo "BARMAN_DIGEST_USER — имя пользователя Discord (буквы, цифры, _ .)"; exit 1 ;; esac
case "$DMODEL" in *[!A-Za-z0-9_.:/-]*) echo "BARMAN_DIGEST_MODEL — id модели OpenRouter"; exit 1 ;; esac
case "$AIUSERS$AICH" in *[!0-9,]*) echo "BARMAN_AI_USERS / BARMAN_AI_CHANNELS — ID через запятую"; exit 1 ;; esac
case "$SOUL" in *[!a-z0-9_-]*) echo "BARMAN_SOUL — имя личности из persona/ (например sibiya)"; exit 1 ;; esac
SOUL_FILE=""
if [ -n "$SOUL" ]; then  # собираем до выкатки: кривые BARMAN_EMOJI или нет файла — стоп, сервер не тронут
  [ -f "$REPO/persona/SOUL.$SOUL.md" ] || { echo "Нет persona/SOUL.$SOUL.md"; exit 1; }
  SOUL_FILE="$(mktemp)"
  python3 "$REPO/deploy/render_soul.py" "$REPO/persona/SOUL.$SOUL.md" "$EMOJI" > "$SOUL_FILE"
fi
ssh -i "$KEY" "root@$IP" "test -d $DATA" || { echo "Нет $DATA на сервере"; exit 1; }
rsync -a --delete --exclude '__pycache__' -e "ssh -i $KEY" "$REPO/barman/" "root@$IP:$DATA/plugins/barman/"
set_env() {  # заменить строку KEY=... в .env или дописать, если её нет
  ssh -i "$KEY" "root@$IP" "f=$DATA/.env; if grep -q '^$1=' \$f; then sed -i 's|^$1=.*|$1=$2|' \$f; else echo $1=$2 >> \$f; fi"
}
hermes_set() {  # замок в config.yaml Hermes + проверка, что он встал (иначе доступ не открываем)
  ssh -i "$KEY" "root@$IP" "docker exec -u 10000 barmen hermes config set --force $1 $2 >/dev/null && test \"\$(docker exec -u 10000 barmen hermes config get $1)\" = $2" || { echo "Не встал замок Hermes: $1"; exit 1; }
}
ssh -i "$KEY" "root@$IP" "docker start barmen >/dev/null"  # hermes config работает в запущенном контейнере
hermes_set platforms.discord.extra.allow_admin_from 0
hermes_set platforms.discord.extra.group_allow_admin_from 0
hermes_set platforms.discord.extra.dm_policy disabled
set_env DISCORD_COMMAND_SYNC_POLICY off
set_env DISCORD_ALLOWED_ROLES ""
set_env DISCORD_ALLOWED_USERS "${AIUSERS:-0}"
[ -z "$AICH" ] || set_env DISCORD_ALLOWED_CHANNELS "$AICH"
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
ssh -i "$KEY" "root@$IP" "chown -R 10000:10000 $DATA && docker restart barmen >/dev/null"
echo "Бармен обновлён и перезапущен"
