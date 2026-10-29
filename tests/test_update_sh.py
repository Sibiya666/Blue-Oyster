"""deploy/update.sh против поддельного сервера: ssh выполняет команду локально, docker/rsync/chown — заглушки с журналом."""
import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

FAKE_DOCKER = """#!/bin/sh
echo "docker $*" >> "$LOG"
case "$1" in
  inspect) [ "$2" = barmen ] && { echo sha256:IMG; exit 0; }; [ -f "$STATE/$2" ] && exit 0; exit 1 ;;
  run) n=$(echo "$*" | sed -E 's/.*--name ([^ ]+).*/\\1/'); touch "$STATE/$n"; exit 0 ;;
  exec) case "$*" in *"python3 -"*) [ -n "$STALE_IDS" ] && echo "$STALE_IDS"; exit 0 ;; esac
    shift 6
    if [ "$1" = set ]; then shift; [ "$1" = --force ] && shift; echo "$1=$2" >> "$CFG"; fi
    if [ "$1" = get ]; then grep "^$2=" "$CFG" | tail -1 | cut -d= -f2-; fi ;;
esac
exit 0
"""


def _exe(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def fake(tmp_path):
    b = tmp_path / "bin"
    b.mkdir()
    _exe(b / "ssh", '#!/bin/sh\nfor a; do last=$a; done; sh -c "$last"\n')
    _exe(b / "rsync", '#!/bin/sh\necho "rsync $*" >> "$LOG"\n')
    _exe(b / "chown", '#!/bin/sh\necho "chown $*" >> "$LOG"\n')
    _exe(b / "docker", FAKE_DOCKER)
    real_sed = "/usr/bin/sed"
    _exe(b / "sed", f'#!/bin/sh\nif [ "$1" = -i ] && [ "$(uname)" = Darwin ]; then shift; exec {real_sed} -i "" "$@"; fi\n'
                    f'exec {real_sed} "$@"\n')
    prod = tmp_path / "prod"
    prod.mkdir()
    (prod / "config.yaml").write_text("model: x\n")
    (prod / ".env").write_text("DISCORD_BOT_TOKEN=PROD\nOPENROUTER_API_KEY=sk-or-x\n")
    (tmp_path / "state").mkdir()
    env = {**os.environ, "PATH": f"{b}:{os.environ['PATH']}", "LOG": str(tmp_path / "log"),
           "CFG": str(tmp_path / "cfg"), "STATE": str(tmp_path / "state"), "BARMAN_PROD_DATA": str(prod)}
    return tmp_path, env


def _run(env, **kw):
    return subprocess.run(["sh", str(REPO / "deploy/update.sh"), "1.2.3.4"], env={**env, **kw},
                          capture_output=True, text=True)


def test_test_bot_first_deploy_and_env_owner_after_token(fake):
    tmp, env = fake
    data = tmp / "test"
    r = _run(env, BARMAN_TARGET="test", BARMAN_DATA=str(data), BARMAN_BOT_TOKEN="abc.DEF_1-2",
             BARMAN_AI_USERS="1", BARMAN_SOUL="angmar")
    assert r.returncode == 0, r.stdout + r.stderr
    dotenv = (data / ".env").read_text()
    assert "DISCORD_BOT_TOKEN=abc.DEF_1-2" in dotenv and "PROD" not in dotenv and "OPENROUTER_API_KEY" in dotenv
    log = (tmp / "log").read_text().splitlines()
    owner_fix = next(i for i, l in enumerate(log) if l.startswith(f"chown 10000:10000 {data}/.env."))
    first_hermes = next(i for i, l in enumerate(log) if "hermes config" in l)
    assert owner_fix < first_hermes                     # Hermes (uid 10000) читает .env уже со своим владельцем
    assert any(l.startswith("docker run -d --name barmen-test") for l in log)


def test_redeploy_with_token_fixes_owner_again(fake):
    tmp, env = fake
    data = tmp / "test"
    assert _run(env, BARMAN_TARGET="test", BARMAN_DATA=str(data), BARMAN_BOT_TOKEN="t1").returncode == 0
    (tmp / "log").write_text("")
    r = _run(env, BARMAN_TARGET="test", BARMAN_DATA=str(data), BARMAN_BOT_TOKEN="t2")
    assert r.returncode == 0, r.stdout + r.stderr
    log = (tmp / "log").read_text().splitlines()
    assert any(l.startswith(f"chown 10000:10000 {data}/.env.") for l in log)  # владелец ставится до mv
    assert not any(l.startswith("docker run") for l in log)  # контейнер уже есть — не пересоздаём
    assert "DISCORD_BOT_TOKEN=t2" in (data / ".env").read_text()


def test_prod_default_target_untouched(fake):
    tmp, env = fake
    prod = Path(env["BARMAN_PROD_DATA"])
    r = _run(env, BARMAN_DATA=str(prod))
    assert r.returncode == 0, r.stdout + r.stderr
    log = (tmp / "log").read_text()
    assert "barmen-test" not in log and "docker restart barmen" in log
    assert "DISCORD_BOT_TOKEN=PROD" in (prod / ".env").read_text()


@pytest.mark.parametrize("kw,msg", [
    ({"BARMAN_TARGET": "staging"}, "prod или test"),
    ({"BARMAN_TARGET": "test", "BARMAN_BOT_TOKEN": "x;rm -rf /"}, "токен"),
    ({"BARMAN_AI_USERS": "1;rm"}, "ID через запятую"),
])
def test_rejects_garbage(fake, kw, msg):
    _, env = fake
    r = _run(env, **kw)
    assert r.returncode != 0 and msg in r.stdout + r.stderr


# --- ловушки-ссылки: взломанный процесс бота (uid 10000) подкладывает ссылку, а выкатка пишет от root ---

def _prod(fake):
    tmp, env = fake
    return tmp, env, Path(env["BARMAN_PROD_DATA"])


@pytest.mark.parametrize("name", [".env", "SOUL.md", "config.yaml", "plugins", "plugins/barman"])
def test_refuses_when_data_path_is_a_symlink(fake, name):
    tmp, env, prod = _prod(fake)
    victim = tmp / "root_secret"
    victim.write_text("ROOT ONLY\n")
    (prod / "plugins").mkdir(exist_ok=True)
    link = prod / name
    if link.exists() or link.is_symlink():
        if link.is_dir() and not link.is_symlink():
            link.rmdir()
        else:
            link.unlink()
    link.symlink_to(victim)
    r = _run(env, BARMAN_DATA=str(prod), BARMAN_SOUL="sibiya", BARMAN_AI_USERS="1")
    assert r.returncode != 0 and "ссылка" in (r.stdout + r.stderr).lower(), r.stdout + r.stderr
    assert victim.read_text() == "ROOT ONLY\n"                      # по ссылке ничего не записали
    log = (tmp / "log").read_text() if (tmp / "log").exists() else ""
    assert "rsync" not in log and "docker restart" not in log       # остановились до любых действий


def test_writes_do_not_follow_planted_temp_files(fake):
    """Старые фиксированные имена временных файлов (.env.new) не используются: подложенная ссылка не сработает."""
    tmp, env = fake
    data = tmp / "test"
    assert _run(env, BARMAN_TARGET="test", BARMAN_DATA=str(data), BARMAN_BOT_TOKEN="t1").returncode == 0
    victim = tmp / "root_secret"
    victim.write_text("ROOT ONLY\n")
    (data / ".env.new").symlink_to(victim)
    r = _run(env, BARMAN_TARGET="test", BARMAN_DATA=str(data), BARMAN_BOT_TOKEN="t2", BARMAN_SOUL="angmar")
    assert r.returncode == 0, r.stdout + r.stderr
    assert victim.read_text() == "ROOT ONLY\n"
    assert "DISCORD_BOT_TOKEN=t2" in (data / ".env").read_text()
    assert not (data / ".env").is_symlink() and not (data / "SOUL.md").is_symlink()


def test_env_and_soul_are_owned_by_bot_after_deploy(fake):
    tmp, env, prod = _prod(fake)
    r = _run(env, BARMAN_DATA=str(prod), BARMAN_SOUL="sibiya", BARMAN_AI_USERS="1")
    assert r.returncode == 0, r.stdout + r.stderr
    log = (tmp / "log").read_text()
    assert "rsync" in log and "--no-links" in log                    # код плагина копируем без ссылок
    assert "chown 10000:10000" in log


def test_test_bootstrap_refuses_symlinked_prod_files(fake):
    """Первый запуск теста копирует config.yaml и ключ с бара — ссылка там не должна утащить чужой файл."""
    tmp, env, prod = _prod(fake)
    victim = tmp / "root_secret"
    victim.write_text("OPENROUTER_API_KEY=stolen-root-file\n")
    (prod / "config.yaml").unlink()
    (prod / "config.yaml").symlink_to(victim)
    data = tmp / "test"
    r = _run(env, BARMAN_TARGET="test", BARMAN_DATA=str(data), BARMAN_BOT_TOKEN="t1")
    assert r.returncode != 0 and "ссылка" in (r.stdout + r.stderr).lower()
    assert not (data / "config.yaml").exists()


def test_deploy_drops_stale_discord_sessions_before_restart(fake):
    """Hermes держит личность в открытой сессии (архив её не закрывает): устаревшие сессии удаляем до рестарта."""
    tmp, env, prod = _prod(fake)
    r = _run(env, BARMAN_DATA=str(prod), BARMAN_SOUL="drakonia", STALE_IDS="20261026_192416_d45d5ba0")
    assert r.returncode == 0, r.stdout + r.stderr
    log = (tmp / "log").read_text().splitlines()
    check = next(i for i, l in enumerate(log) if "python3 - /opt/data/state.db /opt/data/SOUL.md" in l)
    delete = next(i for i, l in enumerate(log) if "hermes sessions delete 20261026_192416_d45d5ba0 --yes" in l)
    restart = next(i for i, l in enumerate(log) if l.startswith("docker restart"))
    assert check < delete < restart
    assert not any("sessions archive" in l for l in log)


def test_deploy_ignores_garbage_session_ids(fake):
    """id приходят из базы на сервере — в shell попадают только [A-Za-z0-9_-]."""
    tmp, env, prod = _prod(fake)
    r = _run(env, BARMAN_DATA=str(prod), BARMAN_SOUL="drakonia", STALE_IDS="x;touch_pwned $(id)")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not any("sessions delete" in l for l in (tmp / "log").read_text().splitlines())
