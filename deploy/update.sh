#!/bin/sh
# Выкатить код бармена на сервер и перезапустить его контейнер. Данные (barman/bindings.json) не трогаются.
# В .env на сервере выставляются только ключи ниже, остальное (токен, ключи) не трогается:
#   DISCORD_COMMAND_SYNC_POLICY=off — Hermes не регистрирует свои /-команды (список держит бармен);
#   DISCORD_ALLOWED_USERS=0, DISCORD_ALLOWED_ROLES= — Hermes (ИИ и его команды) не отвечает никому, в личке молчит;
#   BARMAN_ROLES_CHANNEL           — только если передан (BARMAN_ROLES_CHANNEL=<id канала>).
# Бармен живёт в своём контейнере `barmen` (данные — /root/barmen-hermes), другие боты не затрагиваются.
# Использование: deploy/update.sh <IP>   (после мержа в main это делает .github/workflows/deploy.yml)
set -eu
IP="$1"
KEY="${BARMAN_SSH_KEY:-$HOME/.ssh/companion_vps}"  # в GitHub Actions — отдельный deploy-ключ
DATA="${BARMAN_DATA:-/root/barmen-hermes}"
CH="${BARMAN_ROLES_CHANNEL:-}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
case "$CH" in *[!0-9]*) echo "BARMAN_ROLES_CHANNEL должен быть числом (ID канала)"; exit 1 ;; esac
ssh -i "$KEY" "root@$IP" "test -d $DATA" || { echo "Нет $DATA на сервере"; exit 1; }
rsync -a --delete --exclude '__pycache__' -e "ssh -i $KEY" "$REPO/barman/" "root@$IP:$DATA/plugins/barman/"
set_env() {  # заменить строку KEY=... в .env или дописать, если её нет
  ssh -i "$KEY" "root@$IP" "f=$DATA/.env; if grep -q '^$1=' \$f; then sed -i 's/^$1=.*/$1=$2/' \$f; else echo $1=$2 >> \$f; fi"
}
set_env DISCORD_COMMAND_SYNC_POLICY off
set_env DISCORD_ALLOWED_USERS 0
set_env DISCORD_ALLOWED_ROLES ""
if [ -n "$CH" ]; then
  set_env BARMAN_ROLES_CHANNEL "$CH"
  echo "Канал ролей: $CH"
fi
ssh -i "$KEY" "root@$IP" "chown -R 10000:10000 $DATA && docker restart barmen >/dev/null"
echo "Бармен обновлён и перезапущен"
