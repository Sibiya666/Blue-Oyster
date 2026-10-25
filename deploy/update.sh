#!/bin/sh
# Выкатить код бармена на сервер и перезапустить его контейнер. Данные (barman/bindings.json) не трогаются;
# в .env меняется только BARMAN_ROLES_CHANNEL, и только если он передан (BARMAN_ROLES_CHANNEL=<id канала>).
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
if [ -n "$CH" ]; then  # канал ролей: заменить строку в .env или дописать, если её нет
  ssh -i "$KEY" "root@$IP" "f=$DATA/.env; if grep -q '^BARMAN_ROLES_CHANNEL=' \$f; then sed -i 's/^BARMAN_ROLES_CHANNEL=.*/BARMAN_ROLES_CHANNEL=$CH/' \$f; else echo BARMAN_ROLES_CHANNEL=$CH >> \$f; fi"
  echo "Канал ролей: $CH"
fi
ssh -i "$KEY" "root@$IP" "chown -R 10000:10000 $DATA && docker restart barmen >/dev/null"
echo "Бармен обновлён и перезапущен"
