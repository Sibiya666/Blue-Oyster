#!/bin/sh
# Довести текущую ветку до main. Запускать, когда локальное ревью пройдено и все замечания исправлены.
#   1. Локальные тесты (.venv/bin/pytest -q) — красные → стоп.
#   2. Push ветки, PR в main (если его ещё нет).
#   3. Цикл, пока PR не в main:
#      - отстал от main или конфликт → вливаем свежий main в ветку, снова тесты, push;
#        если git не может слить сам (конфликт в файлах) → стоп с кодом 2: правим конфликт, коммитим, запускаем снова;
#      - без конфликтов и проверки PR зелёные (или их нет) → merge (squash), ветка на GitHub удаляется;
#      - проверки PR красные → стоп.
#   4. После мержа, если задан BARMAN_VPS_IP, — выкатка на VPS ровно того, что в origin/main.
# Нужен gh с входом в GitHub (brew install gh && gh auth login).
# Использование: deploy/ship.sh            (BARMAN_VPS_IP=<IP> deploy/ship.sh — с выкаткой)
set -eu

die() { echo "ship: $*" >&2; exit "${CODE:-1}"; }
command -v gh >/dev/null || die "нет gh: brew install gh && gh auth login"
cd "$(git rev-parse --show-toplevel)"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
[ "$BRANCH" != main ] && [ "$BRANCH" != HEAD ] || die "нужна рабочая ветка, не main"
[ -z "$(git status --porcelain)" ] || die "есть незакоммиченные изменения"

tests() { "${PYTEST:-.venv/bin/pytest}" -q || die "тесты красные"; }  # PYTEST=… — если .venv в другом месте

tests
git push -u origin "$BRANCH"
gh pr view "$BRANCH" --json number >/dev/null 2>&1 || gh pr create --base main --head "$BRANCH" --fill

tries=0
while :; do
  tries=$((tries + 1))
  [ "$tries" -le 20 ] || die "20 кругов, а PR всё ещё не в main — разберись вручную"
  info="$(gh pr view "$BRANCH" --json state,mergeable,mergeStateStatus \
          -q '.state + " " + .mergeable + " " + .mergeStateStatus')"
  set -- $info
  state=$1 mergeable=$2 status=$3
  echo "ship: PR $state, mergeable=$mergeable, status=$status"
  case "$state" in
    MERGED) break ;;
    CLOSED) die "PR закрыт без мержа" ;;
  esac
  if [ "$mergeable" = UNKNOWN ]; then          # GitHub ещё считает — подождём
    sleep 5; continue
  fi
  if [ "$mergeable" = CONFLICTING ] || [ "$status" = BEHIND ] || [ "$status" = DIRTY ]; then
    git fetch -q origin main
    if ! git merge --no-edit origin/main; then
      git merge --abort
      CODE=2 die "конфликт с main: git merge origin/main, поправить, закоммитить, запустить снова"
    fi
    tests
    git push origin "$BRANCH"
    sleep 5; continue
  fi
  # проверок может не быть вовсе — тогда gh пишет «no checks reported», это считаем зелёным
  if ! out="$(gh pr checks "$BRANCH" --watch --fail-fast 2>&1)"; then
    echo "$out" | grep -qi "no checks reported" || { echo "$out"; die "проверки PR красные"; }
  fi
  # main мог уйти вперёд, пока ждали проверки, — тогда merge откажет и цикл обновит ветку
  # без --delete-branch: он переключил бы локальную папку на main, а её могут делить несколько сессий
  gh pr merge "$BRANCH" --squash || sleep 5
done

echo "ship: $BRANCH в main"
git push -q origin --delete "$BRANCH" 2>/dev/null || true
if [ -n "${BARMAN_VPS_IP:-}" ]; then
  git fetch -q origin main
  tmp="$(mktemp -d)"
  git worktree add -q --detach "$tmp" origin/main
  sh "$tmp/deploy/update.sh" "$BARMAN_VPS_IP" || { git worktree remove --force "$tmp"; die "выкатка не удалась"; }
  git worktree remove --force "$tmp"
fi
