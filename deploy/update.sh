#!/bin/sh
# Выкатить код бармена на сервер и перезапустить Hermes. Данные профиля (barman/bindings.json, .env) не трогаются.
# Использование: deploy/update.sh <IP> [профиль]   (профиль по умолчанию: barmen)
set -eu
IP="$1"
P="${2:-barmen}"
case "$P" in *[!A-Za-z0-9_-]*|"") echo "Плохое имя профиля: $P"; exit 1;; esac
KEY="$HOME/.ssh/companion_vps"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
ssh -i "$KEY" "root@$IP" "test -d '/root/.hermes/profiles/$P'" || { echo "Нет профиля $P на сервере"; exit 1; }
rsync -a --delete --exclude '__pycache__' -e "ssh -i $KEY" "$REPO/barman/" "root@$IP:/root/.hermes/profiles/$P/plugins/barman/"
# gateway общий с другими профилями: при живом разговоре Hermes откажется перезапускаться — повторить позже
ssh -i "$KEY" "root@$IP" "chown -R 10000:10000 '/root/.hermes/profiles/$P' && docker exec hermes hermes gateway restart"
echo "Бармен обновлён: $P"
