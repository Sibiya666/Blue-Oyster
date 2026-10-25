#!/bin/sh
# Выкатить код бармена на сервер и перезапустить его контейнер. Данные (barman/bindings.json) не трогаются.
# В .env на сервере выставляются только ключи ниже, остальное (токен, ключи) не трогается:
#   DISCORD_COMMAND_SYNC_POLICY=off — Hermes не регистрирует свои /-команды (список держит бармен);
#   DISCORD_ALLOWED_USERS=0, DISCORD_ALLOWED_ROLES= — Hermes (ИИ и его команды) не отвечает никому, в личке молчит;
#   BARMAN_ROLES_CHANNEL, BARMAN_DIGEST_CHANNEL, BARMAN_DIGEST_USER, BARMAN_DIGEST_MODEL — только если переданы
#   (канал ролей; канал, кого упомянуть и модель ИИ для ежедневной выжимки DTF).
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
REPO="$(cd "$(dirname "$0")/.." && pwd)"
case "$CH$DCH" in *[!0-9]*) echo "BARMAN_ROLES_CHANNEL и BARMAN_DIGEST_CHANNEL — числа (ID канала)"; exit 1 ;; esac
case "$DUSER" in *[!A-Za-z0-9_.]*) echo "BARMAN_DIGEST_USER — имя пользователя Discord (буквы, цифры, _ .)"; exit 1 ;; esac
case "$DMODEL" in *[!A-Za-z0-9_.:/-]*) echo "BARMAN_DIGEST_MODEL — id модели OpenRouter"; exit 1 ;; esac
ssh -i "$KEY" "root@$IP" "test -d $DATA" || { echo "Нет $DATA на сервере"; exit 1; }
rsync -a --delete --exclude '__pycache__' -e "ssh -i $KEY" "$REPO/barman/" "root@$IP:$DATA/plugins/barman/"
set_env() {  # заменить строку KEY=... в .env или дописать, если её нет
  ssh -i "$KEY" "root@$IP" "f=$DATA/.env; if grep -q '^$1=' \$f; then sed -i 's|^$1=.*|$1=$2|' \$f; else echo $1=$2 >> \$f; fi"
}
set_env DISCORD_COMMAND_SYNC_POLICY off
set_env DISCORD_ALLOWED_USERS 0
set_env DISCORD_ALLOWED_ROLES ""
if [ -n "$CH" ]; then
  set_env BARMAN_ROLES_CHANNEL "$CH"
  echo "Канал ролей: $CH"
fi
[ -z "$DCH" ] || set_env BARMAN_DIGEST_CHANNEL "$DCH"
[ -z "$DUSER" ] || set_env BARMAN_DIGEST_USER "$DUSER"
[ -z "$DMODEL" ] || set_env BARMAN_DIGEST_MODEL "$DMODEL"
ssh -i "$KEY" "root@$IP" "chown -R 10000:10000 $DATA && docker restart barmen >/dev/null"
echo "Бармен обновлён и перезапущен"
