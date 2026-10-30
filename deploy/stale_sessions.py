"""Печатает id открытых Discord-сессий Hermes, чей системный промт не содержит текущую SOUL.md.

Hermes записывает личность в сессию при её создании и держит сессию канала открытой — новая SOUL
без этого не вступает в силу. Запускается на сервере внутри контейнера, скриптом из stdin:
    docker exec -i -u 10000 <ct> python3 - /opt/data/state.db /opt/data/SOUL.md < stale_sessions.py
Базу только читает; удаляет сам update.sh через `hermes sessions delete`.
"""
import sqlite3
import sys


def stale_ids(db_path, soul_text):
    soul_text = soul_text.strip()
    if not soul_text:
        return []
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT s.id, COALESCE(s.system_prompt, p.prompt, '') FROM sessions s"
            " LEFT JOIN system_prompts p ON p.hash = s.system_prompt_hash"
            " WHERE s.source = 'discord' AND s.ended_at IS NULL"
        ).fetchall()
    finally:
        con.close()
    return [sid for sid, prompt in rows if soul_text not in prompt]


if __name__ == "__main__":
    db, soul = sys.argv[1], sys.argv[2]
    try:
        text = open(soul, encoding="utf-8").read()
    except FileNotFoundError:
        sys.exit(0)  # личность не задана — сессии не трогаем
    for sid in stale_ids(db, text):
        print(sid)
