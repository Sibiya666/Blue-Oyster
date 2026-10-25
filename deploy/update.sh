#!/bin/sh
# Выкатить код бармена на сервер и перезапустить его контейнер. Данные (barman/bindings.json, .env) не трогаются.
# Бармен живёт в своём контейнере `barmen` (данные — /root/barmen-hermes), другие боты не затрагиваются.
# Использование: deploy/update.sh <IP>   (после мержа в main это делает .github/workflows/deploy.yml)
set -eu
IP="$1"
KEY="${BARMAN_SSH_KEY:-$HOME/.ssh/companion_vps}"  # в GitHub Actions — отдельный deploy-ключ
DATA=/root/barmen-hermes
REPO="$(cd "$(dirname "$0")/.." && pwd)"
ssh -i "$KEY" "root@$IP" "test -d $DATA" || { echo "Нет $DATA на сервере"; exit 1; }
rsync -a --delete --exclude '__pycache__' -e "ssh -i $KEY" "$REPO/barman/" "root@$IP:$DATA/plugins/barman/"
ssh -i "$KEY" "root@$IP" "chown -R 10000:10000 $DATA && docker restart barmen >/dev/null"
echo "Бармен обновлён и перезапущен"
