"""deploy/stale_sessions.py: какие открытые Discord-сессии Hermes держат старую личность."""
import sqlite3
import subprocess
import sys
from pathlib import Path

from deploy.stale_sessions import stale_ids

REPO = Path(__file__).resolve().parents[1]
SOUL = "Неизменные правила\nТы — Дракония."


def _db(tmp_path):
    db = tmp_path / "state.db"
    c = sqlite3.connect(db)
    c.execute("create table sessions (id text, source text, ended_at real, system_prompt text, system_prompt_hash text)")
    c.execute("create table system_prompts (hash text, prompt text)")
    c.executemany("insert into system_prompts values (?,?)", [("old", "шапка\nНеизменные правила\nТы — Ангмар."),
                                                              ("new", "шапка\n" + SOUL + "\nхвост")])
    c.executemany("insert into sessions values (?,?,?,?,?)", [
        ("stale", "discord", None, None, "old"),
        ("fresh", "discord", None, None, "new"),
        ("inline", "discord", None, "Ты — Ангмар.", None),
        ("ended", "discord", 1.0, None, "old"),
        ("cli", "cli", None, None, "old"),
    ])
    c.commit()
    return db


def test_only_open_discord_sessions_without_current_soul(tmp_path):
    assert sorted(stale_ids(_db(tmp_path), SOUL)) == ["inline", "stale"]


def test_empty_soul_drops_nothing(tmp_path):
    assert stale_ids(_db(tmp_path), "  \n") == []


def test_runs_as_stdin_script_like_on_server(tmp_path):
    soul = tmp_path / "SOUL.md"
    soul.write_text(SOUL + "\n", encoding="utf-8")
    r = subprocess.run([sys.executable, "-", str(_db(tmp_path)), str(soul)], stdin=open(REPO / "deploy/stale_sessions.py"),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert sorted(r.stdout.split()) == ["inline", "stale"]


def test_missing_soul_file_drops_nothing(tmp_path):
    r = subprocess.run([sys.executable, "-", str(_db(tmp_path)), str(tmp_path / "nope.md")],
                       stdin=open(REPO / "deploy/stale_sessions.py"), capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == ""
